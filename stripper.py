#!/usr/bin/env python3
"""Deterministic research collator stripper.

Walks the research roots in config.yaml and pulls structured records into
a SQLite index. NO LLM CALLS. Pure regex/json/yaml/AST parsing.

Usage:
    python3 stripper.py [--smoke N] [--config config.yaml]

--smoke N caps total processed files to N (across all roots) for quick tests.
"""

from __future__ import annotations

import argparse
import ast
import csv as csv_mod
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import yaml

EXTRACTION_VERSION = "stripper_v2"

# Regexes used by the markdown handler — all anchored, all bounded.
RE_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
RE_H1 = re.compile(r"^# +(.+?)$", re.MULTILINE)
RE_HEADING = re.compile(r"^(#{1,3}) +(.+?)$", re.MULTILINE)
RE_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$", re.MULTILINE)

# JSON keys that we treat as numeric metrics (case-insensitive substring match).
METRIC_KEY_PATTERNS = (
    "metric", "score", "loss", "acc", "accuracy", "rate", "delta",
    "mean", "median", "p50", "p95", "p99", "min", "max", "std",
    "elo", "passrate", "pass_rate", "perplexity", "ppl", "bleu",
    "f1", "precision", "recall", "ms", "us", "ns", "throughput",
    "tokens_per_sec", "tok_s", "size_mb", "params", "flops", "mflops",
    "gflops", "tflops", "epochs", "step", "iter",
)


# ---------- DB helpers ---------------------------------------------------------

ARTIFACT_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_label ON artifacts(source_label)",
    "CREATE INDEX IF NOT EXISTS idx_kind ON artifacts(file_kind)",
    "CREATE INDEX IF NOT EXISTS idx_mtime ON artifacts(mtime_iso)",
    "CREATE INDEX IF NOT EXISTS idx_title ON artifacts(title)",
    # Common retrieval surfaces for the locked daily template: same-kind time
    # scans, source/kind slicing, and content-hash dedup.
    "CREATE INDEX IF NOT EXISTS idx_kind_mtime ON artifacts(file_kind, mtime_iso)",
    "CREATE INDEX IF NOT EXISTS idx_source_kind ON artifacts(source_label, file_kind)",
    "CREATE INDEX IF NOT EXISTS idx_content_sha ON artifacts(content_sha256)",
)


def ensure_artifact_indexes(conn: sqlite3.Connection) -> None:
    for ddl in ARTIFACT_INDEX_DDL:
        conn.execute(ddl)


def init_db(path: str) -> sqlite3.Connection:
    new = not os.path.exists(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    if new:
        conn.executescript(
            """
            CREATE TABLE artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_root TEXT NOT NULL,
                source_label TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                abs_path TEXT NOT NULL UNIQUE,
                file_kind TEXT NOT NULL,
                file_size_bytes INTEGER NOT NULL,
                mtime_iso TEXT NOT NULL,
                content_sha256 TEXT,

                title TEXT,
                summary TEXT,
                frontmatter_json TEXT,
                section_headings_json TEXT,
                tables_json TEXT,

                metrics_json TEXT,

                docstring TEXT,
                argparse_description TEXT,

                csv_columns_json TEXT,
                csv_row_count INTEGER,
                csv_numeric_summary_json TEXT,

                too_large INTEGER NOT NULL DEFAULT 0,
                parse_error TEXT,

                extraction_version TEXT NOT NULL,
                extracted_at_iso TEXT NOT NULL
            );

            CREATE TABLE walk_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at_iso TEXT NOT NULL,
                finished_at_iso TEXT,
                total_files_scanned INTEGER,
                total_files_kept INTEGER,
                wall_seconds REAL,
                stripper_version TEXT NOT NULL,
                config_snapshot TEXT
            );
            """
        )
    ensure_artifact_indexes(conn)
    conn.commit()
    return conn


def upsert_artifact(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    cols = list(row.keys())
    placeholders = ",".join(["?"] * len(cols))
    update_clause = ",".join(f"{c}=excluded.{c}" for c in cols if c != "abs_path")
    sql = (
        f"INSERT INTO artifacts ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(abs_path) DO UPDATE SET {update_clause}"
    )
    conn.execute(sql, [row[c] for c in cols])


# ---------- Per-extension handlers --------------------------------------------

def _is_metric_key(k: str) -> bool:
    kl = k.lower()
    return any(p in kl for p in METRIC_KEY_PATTERNS)


def _walk_metrics(obj: Any, path: str = "", out: dict[str, float] | None = None,
                  depth: int = 0, max_depth: int = 6) -> dict[str, float]:
    """Walk a dict/list and pull numeric leaves whose key matches a metric pattern."""
    if out is None:
        out = {}
    if depth > max_depth or len(out) > 200:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else str(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if _is_metric_key(str(k)):
                    out[new_path] = float(v)
            else:
                _walk_metrics(v, new_path, out, depth + 1, max_depth)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:20]):  # cap list expansion
            _walk_metrics(v, f"{path}[{i}]", out, depth + 1, max_depth)
    return out


def handle_markdown(abs_path: str, size: int, max_bytes: int) -> dict[str, Any]:
    record: dict[str, Any] = {"file_kind": "md"}
    if size > max_bytes:
        record["too_large"] = 1
        return record
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        record["parse_error"] = f"read: {type(e).__name__}: {e}"
        return record

    # Frontmatter
    fm = RE_FRONTMATTER.match(text)
    fm_dict: dict[str, Any] | None = None
    if fm:
        try:
            fm_dict = yaml.safe_load(fm.group(1))
        except yaml.YAMLError:
            fm_dict = None
        text_body = text[fm.end():]
    else:
        text_body = text

    if isinstance(fm_dict, dict):
        record["frontmatter_json"] = json.dumps(fm_dict, default=str)
        if "name" in fm_dict and not record.get("title"):
            record["title"] = str(fm_dict["name"])[:300]
        elif "title" in fm_dict and not record.get("title"):
            record["title"] = str(fm_dict["title"])[:300]

    # Title from first H1 if not from frontmatter
    if not record.get("title"):
        m = RE_H1.search(text_body)
        if m:
            record["title"] = m.group(1).strip()[:300]

    # Summary: first non-heading paragraph after frontmatter / first H1
    paragraphs = []
    for chunk in re.split(r"\n\s*\n", text_body):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("#"):
            continue
        if chunk.startswith(("```", "---", "|")):
            continue
        paragraphs.append(chunk)
        if len(paragraphs) >= 1:
            break
    if paragraphs:
        record["summary"] = paragraphs[0][:1000]

    # Section headings index
    headings = []
    for level, head in RE_HEADING.findall(text_body):
        headings.append({"level": len(level), "text": head.strip()[:200]})
        if len(headings) >= 100:
            break
    if headings:
        record["section_headings_json"] = json.dumps(headings)

    # Tables — capture first table per file
    tables = []
    in_table = False
    cur: list[str] = []
    for line in text_body.splitlines():
        if RE_TABLE_ROW.match(line.rstrip()):
            cur.append(line.strip())
            in_table = True
        else:
            if in_table and cur:
                if len(cur) >= 2:
                    tables.append(cur[:25])
                cur = []
                in_table = False
            if len(tables) >= 5:
                break
    if tables:
        record["tables_json"] = json.dumps(tables)

    return record


def _walk_hardware(obj: Any, depth: int = 0, max_depth: int = 6) -> dict[str, Any]:
    """Walk a nested dict (e.g., resolved_config.json) for hardware fields.
    Returns canonical {gpu_type, n_gpus, provider} when found.
    Looks for keys like:
      kernel.gpu_type / model.gpu_type / device / gpu / gpu_name
      world_size / nproc_per_node / n_gpus / num_gpus
      pod_type / provider / cloud
    """
    out: dict[str, Any] = {}
    if depth > max_depth or not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        kl = str(k).lower()
        if isinstance(v, str):
            # GPU type signals
            if kl in ("gpu_type", "gpu", "gpu_name", "device", "device_name",
                      "accelerator"):
                gt = _detect_gpu_type(v) or v
                if gt:
                    out.setdefault("gpu_type", gt)
            if kl in ("provider", "pod_type", "cloud", "host"):
                p = _detect_provider(v) or v
                if p:
                    out.setdefault("provider", p)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            if kl in ("world_size", "n_gpus", "num_gpus", "nproc_per_node",
                      "ngpus", "gpu_count"):
                if isinstance(v, int) and 1 <= v <= 64:
                    out.setdefault("n_gpus", int(v))
        elif isinstance(v, dict):
            nested = _walk_hardware(v, depth + 1, max_depth)
            for nk, nv in nested.items():
                out.setdefault(nk, nv)
    return out


def handle_json_summary(abs_path: str, size: int, max_bytes: int) -> dict[str, Any]:
    record: dict[str, Any] = {"file_kind": "json"}
    if size > max_bytes:
        record["too_large"] = 1
        return record
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as f:
            obj = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        record["parse_error"] = f"{type(e).__name__}: {e}"
        return record

    if isinstance(obj, dict):
        for tk in ("title", "name", "round", "loop_id", "loopId", "round_id"):
            if tk in obj and isinstance(obj[tk], (str, int, float)):
                record["title"] = str(obj[tk])[:300]
                break
        for sk in ("description", "summary", "status", "verdict", "decision",
                   "blurb"):
            if sk in obj and isinstance(obj[sk], (str, int, float)):
                record["summary"] = str(obj[sk])[:1000]
                break

    metrics = _walk_metrics(obj)
    # Hardware extraction — nested config files (resolved_config.json) carry
    # this in `kernel.gpu_type`, `model.world_size`, etc. Submission JSONs
    # carry it in the `blurb` prose field.
    if isinstance(obj, dict):
        hw = _walk_hardware(obj)
        for k, v in hw.items():
            metrics.setdefault(k, v)
        # Blurb prose — last-resort scan for hardware mentions
        blurb = obj.get("blurb")
        if isinstance(blurb, str):
            if "gpu_type" not in metrics:
                gt = _detect_gpu_type(blurb)
                if gt:
                    metrics["gpu_type"] = gt
            if "provider" not in metrics:
                pv = _detect_provider(blurb)
                if pv:
                    metrics["provider"] = pv
        # Path fallback for provider (runpod_2026_03_30_logs/...)
        if "provider" not in metrics:
            pv = _detect_provider(abs_path)
            if pv:
                metrics["provider"] = pv
        # Tag observed gpu_type so we can distinguish from the inferred fallback
        if "gpu_type" in metrics and "gpu_type_source" not in metrics:
            metrics["gpu_type_source"] = "observed"
        # Binary local/rented inference when no explicit GPU model is found
        if "gpu_type" not in metrics:
            inferred = _infer_gpu_type(metrics.get("provider"), metrics.get("n_gpus"))
            if inferred:
                metrics["gpu_type"] = inferred
                metrics["gpu_type_source"] = "inferred"
        # Tag val_bpb as JSON-derived (most reliable source for submissions)
        if "val_bpb" in metrics:
            metrics.setdefault("val_bpb_source", "json_top_level")
        # Reference-baseline detection. Keep this narrow: dated records/track_*
        # folders can be real user work and must stay visible in daily reports.
        if _is_reference_baseline_path(abs_path):
            metrics["is_reference_baseline"] = True
    if metrics:
        record["metrics_json"] = json.dumps(metrics)
    return record


def handle_python_module(abs_path: str, size: int, max_bytes: int) -> dict[str, Any]:
    record: dict[str, Any] = {"file_kind": "py"}
    if size > max_bytes:
        record["too_large"] = 1
        return record
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except (OSError, UnicodeDecodeError) as e:
        record["parse_error"] = f"read: {type(e).__name__}: {e}"
        return record
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        record["parse_error"] = f"SyntaxError: {e.msg}"
        return record

    docstring = ast.get_docstring(tree)
    if docstring:
        record["docstring"] = docstring[:2000]
        first_line = docstring.strip().splitlines()[0] if docstring.strip() else None
        if first_line:
            record["title"] = first_line[:300]

    # argparse description: look for ArgumentParser(description="...")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "ArgumentParser":
                for kw in node.keywords:
                    if kw.arg == "description" and isinstance(kw.value, ast.Constant) \
                            and isinstance(kw.value.value, str):
                        record["argparse_description"] = kw.value.value[:1000]
                        if not record.get("title"):
                            record["title"] = kw.value.value.splitlines()[0][:300]
                        break
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "ArgumentParser":
            for kw in node.keywords:
                if kw.arg == "description" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    record["argparse_description"] = kw.value.value[:1000]
                    if not record.get("title"):
                        record["title"] = kw.value.value.splitlines()[0][:300]
                    break

    # Lightweight summary = docstring first paragraph if present
    if docstring:
        first_para = docstring.strip().split("\n\n", 1)[0]
        record["summary"] = first_para[:1000]

    return record


def handle_csv_meta(abs_path: str, size: int, max_bytes: int) -> dict[str, Any]:
    record: dict[str, Any] = {"file_kind": "csv"}
    if size > max_bytes:
        record["too_large"] = 1
        return record
    try:
        with open(abs_path, encoding="utf-8", errors="replace", newline="") as f:
            reader = csv_mod.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                record["parse_error"] = "empty"
                return record
            record["csv_columns_json"] = json.dumps(header)
            rows = 0
            numeric_cols: dict[int, list[float]] = {}
            for row in reader:
                rows += 1
                for i, val in enumerate(row):
                    if i >= len(header):
                        continue
                    try:
                        v = float(val)
                    except (TypeError, ValueError):
                        continue
                    numeric_cols.setdefault(i, []).append(v)
                if rows >= 50000:  # cap
                    break
            record["csv_row_count"] = rows
            if numeric_cols:
                summary = {}
                for i, vals in numeric_cols.items():
                    if not vals:
                        continue
                    summary[header[i]] = {
                        "n": len(vals),
                        "min": min(vals),
                        "max": max(vals),
                        "mean": sum(vals) / len(vals),
                    }
                if summary:
                    record["csv_numeric_summary_json"] = json.dumps(summary)
            record["title"] = f"{Path(abs_path).name} ({rows} rows × {len(header)} cols)"
    except (OSError, UnicodeDecodeError, csv_mod.Error) as e:
        record["parse_error"] = f"{type(e).__name__}: {e}"
    return record


def handle_checkpoint_meta(abs_path: str, size: int, max_bytes: int) -> dict[str, Any]:
    # Metadata only — never load the tensor file.
    record: dict[str, Any] = {"file_kind": "ckpt"}
    record["title"] = f"{Path(abs_path).name} ({size / 1e6:.1f} MB)"
    return record


def fallback_summary(rec: dict[str, Any], filename: str, size: int,
                     handler_name: str) -> str:
    """Short deterministic context for records whose handler found no prose.

    The renderer should never have to guess what a record is. Keep this
    intentionally generic; precise measurements belong in metrics_json.
    """
    kind = rec.get("file_kind") or handler_name
    if rec.get("too_large"):
        return f"{kind} artifact indexed as metadata only; file exceeds parser cap ({size} bytes)."
    if rec.get("parse_error"):
        return f"{kind} artifact indexed with parse error: {str(rec['parse_error'])[:180]}"
    if kind == "json":
        return "JSON artifact indexed; canonical numeric metrics were extracted when present."
    if kind == "md":
        return "Markdown artifact indexed; frontmatter, headings, and tables were extracted when present."
    if kind == "py":
        return "Python artifact indexed; docstring and argparse metadata were extracted when present."
    if kind == "csv":
        return "CSV/TSV artifact indexed; columns, row count, and numeric summaries were extracted."
    if kind == "ckpt":
        return "Checkpoint artifact indexed as metadata only; tensor contents were not loaded."
    if kind == "training_log":
        if size == 0:
            return "(empty stub - run launched but output was not captured locally)"
        return "Training log indexed; no canonical val_bpb/val_loss output pattern was found."
    return f"{kind} artifact indexed from {filename}."


# Strict patterns for training logs — accept val_bpb only when in training-output
# format, not random Python source code that happens to mention val_loss.
RE_LOG_STEP = re.compile(
    r"step:\d+(?:/\d+)?\s+val_loss:[\d.]+\s+val_bpb:([\d.]+)"
)
RE_LOG_FINAL = re.compile(
    r"final_(\w+?)\s+val_loss:[\d.]+\s+val_bpb:([\d.]+)"
)
RE_LOG_RANK = re.compile(r"\[rank(\d+)\]")
RE_LOG_TRAIN_TIME = re.compile(r"train_time:(\d+)ms")
RE_LOG_STEP_NUM = re.compile(r"step:(\d+)/")
RE_FILENAME_TS = re.compile(r"_(\d{8})[-_](\d{6})\b")

# Hardware detection patterns. Order matters: most-specific first so 8×H100
# beats H100. Each entry: (regex, canonical-label).
HW_GPU_PATTERNS = [
    (re.compile(r"\bnvidia[\s_-]+h200\b",                   re.I), "H200"),
    (re.compile(r"\bnvidia[\s_-]+h100[\s_-]+(?:sxm[5]?|pcie|nvl)\b", re.I), "H100"),
    (re.compile(r"\bnvidia[\s_-]+h100\b",                   re.I), "H100"),
    (re.compile(r"\bnvidia[\s_-]+a100\b",                   re.I), "A100"),
    (re.compile(r"\bnvidia[\s_-]+l40s?\b",                  re.I), "L40"),
    (re.compile(r"\bnvidia[\s_-]+rtx[\s_-]+5090\b",         re.I), "RTX 5090"),
    (re.compile(r"\bnvidia[\s_-]+rtx[\s_-]+4090\b",         re.I), "RTX 4090"),
    (re.compile(r"\bgeforce[\s_-]+rtx[\s_-]+5090\b",        re.I), "RTX 5090"),
    (re.compile(r"\bgeforce[\s_-]+rtx[\s_-]+4090\b",        re.I), "RTX 4090"),
    (re.compile(r"\bgb10\b",                                re.I), "GB10"),
    (re.compile(r"\bdgx[\s_-]?spark\b",                     re.I), "DGX Spark"),
    # Bare patterns as fallback (lower priority — placed last)
    (re.compile(r"\bh100\b",                                re.I), "H100"),
    (re.compile(r"\ba100\b",                                re.I), "A100"),
    (re.compile(r"\b5090\b",                                re.I), "RTX 5090"),
    (re.compile(r"\b4090\b",                                re.I), "RTX 4090"),
]
# Provider detection from path/text. Matches break at non-alnum (so
# `runpod_2026_03_30_logs` matches; underscore counts as alnum boundary
# since \b is alnum-vs-not so we use lookarounds with non-alnum-or-boundary).
HW_PROVIDER_PATTERNS = [
    (re.compile(r"(?:^|[^a-zA-Z0-9])runpod(?:[^a-zA-Z0-9]|$)", re.I), "runpod"),
    (re.compile(r"(?:^|[^a-zA-Z0-9])vast(?:[\s_.-]?ai)?(?:[^a-zA-Z0-9]|$)", re.I), "vast.ai"),
    (re.compile(r"(?:^|[^a-zA-Z0-9])lambda(?:[\s_.-]?labs)?(?:[^a-zA-Z0-9]|$)", re.I), "lambda"),
    (re.compile(r"(?:^|[^a-zA-Z0-9])coreweave(?:[^a-zA-Z0-9]|$)", re.I), "coreweave"),
    (re.compile(r"(?:^|[^a-zA-Z0-9])dgx[\s_.-]?spark(?:[^a-zA-Z0-9]|$)", re.I), "local"),
    (re.compile(r"(?:^|[^a-zA-Z0-9])spark-2949(?:[^a-zA-Z0-9]|$)", re.I), "local"),
]
# Also extract `world_size:N` from training logs as a fallback for n_gpus.
RE_LOG_WORLD_SIZE = re.compile(r"\bworld_size:\s*(\d+)\b")


def _detect_gpu_type(text: str) -> str | None:
    for pat, label in HW_GPU_PATTERNS:
        if pat.search(text):
            return label
    return None


# Reference-baseline path patterns — files matching these are published
# reference results, not user experiments. Do not treat every
# `records/track_*` run as a reference: those dated run folders are also the
# primary evidence for the user's early daily work.
_RE_REF_BASELINE_PATH = re.compile(
    r"(?:[/_-]NaiveBaseline\b|"
    r"/published_baselines/|"
    r"/_baselines/)",
    re.IGNORECASE,
)


def _is_reference_baseline_path(abs_path: str) -> bool:
    return bool(_RE_REF_BASELINE_PATH.search(abs_path or ""))


def _detect_provider(text: str) -> str | None:
    for pat, label in HW_PROVIDER_PATTERNS:
        if pat.search(text):
            return label
    return None


# Per user 2026-05-05: every training run in this corpus is either
# (a) a small local probe on the DGX Spark = 1×GB10 Blackwell, or
# (b) a rented H100 (single or multi). No A100 / L40 / 5090 / etc. show
# up in real runs. Provider markers win; n_gpus is the tiebreaker.
_CLOUD_PROVIDERS = {"runpod", "vast.ai", "lambda", "coreweave"}


def _infer_gpu_type(provider: str | None, n_gpus: int | None) -> str | None:
    """Binary inference rule: rented = H100, local = GB10. Returns None
    when the signal is too thin (e.g. unknown provider, unknown n_gpus)."""
    if provider in _CLOUD_PROVIDERS:
        return "H100"
    if provider == "local":
        return "GB10"
    # No provider known. Fall back to n_gpus: ≥2 ranks ≈ rented cluster
    # (DGX Spark is single-GPU); 1 rank with no cloud marker ≈ local probe.
    if isinstance(n_gpus, int) and n_gpus >= 2:
        return "H100"
    if n_gpus == 1:
        return "GB10"
    return None


def handle_training_log(abs_path: str, size: int, max_bytes: int) -> dict[str, Any]:
    """Parse a training-run log. STRICT pattern matching: only counts val_bpb
    that appears in 'step:N val_loss:X val_bpb:Y' or 'final_* val_loss:X val_bpb:Y'
    output formats. Loose floats are ignored to avoid false positives from
    .py / .out files that contain training source code."""
    record: dict[str, Any] = {"file_kind": "training_log"}
    fn = os.path.basename(abs_path)
    record["title"] = fn[:300]
    if size == 0:
        record["summary"] = "(empty stub — run launched but output went to cloud)"
        return record
    if size > max_bytes:
        record["too_large"] = 1
        return record
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        record["parse_error"] = f"{type(e).__name__}: {e}"
        return record

    # Pattern matches
    bpbs_during = [float(m.group(1)) for m in RE_LOG_STEP.finditer(text)]
    final_evals: dict[str, float] = {}
    for m in RE_LOG_FINAL.finditer(text):
        eval_kind = m.group(1)
        if eval_kind.endswith("_exact"):
            eval_kind = eval_kind[:-6]
        # Last-write wins (the "_exact" full-precision values overwrite rounded)
        final_evals[f"val_bpb_{eval_kind}"] = float(m.group(2))

    metrics: dict[str, Any] = {}
    # Pick the canonical val_bpb: prefer final eval (post-quantization, what
    # the leaderboard cares about) over best-during-training.
    if "val_bpb_int6_sliding_window" in final_evals:
        metrics["val_bpb"] = final_evals["val_bpb_int6_sliding_window"]
    elif "val_bpb_int8_zlib_roundtrip" in final_evals:
        metrics["val_bpb"] = final_evals["val_bpb_int8_zlib_roundtrip"]
    elif "val_bpb_int6_roundtrip" in final_evals:
        metrics["val_bpb"] = final_evals["val_bpb_int6_roundtrip"]
    elif final_evals:
        metrics["val_bpb"] = min(final_evals.values())
    elif bpbs_during:
        clean = [b for b in bpbs_during if b >= 0.05]
        if clean:
            metrics["val_bpb"] = min(clean)
            metrics["val_bpb_during_run_best"] = min(clean)
    metrics.update(final_evals)
    if bpbs_during:
        clean = [b for b in bpbs_during if b >= 0.05]
        if clean and "val_bpb_during_run_best" not in metrics:
            metrics["val_bpb_during_run_best"] = min(clean)
        metrics["val_bpb_n_step_evals"] = len(bpbs_during)

    # Hardware — three signals, all per-test:
    #   gpu_type    : canonical label (H100, A100, RTX 5090, GB10, ...)
    #   n_gpus      : distinct rank IDs from torch DDP output
    #   provider    : runpod / vast.ai / lambda / coreweave / local
    ranks = {int(m.group(1)) for m in RE_LOG_RANK.finditer(text)}
    if ranks:
        metrics["n_ranks"] = len(ranks)
        metrics["n_gpus"] = len(ranks)
    elif (ws := RE_LOG_WORLD_SIZE.search(text)) is not None:
        # Fallback: many logs print `world_size:N` in their config block but
        # do not emit `[rankN]` lines (single-process launchers, redirected
        # stderr, etc.). Trust that as the GPU count.
        metrics["n_gpus"] = int(ws.group(1))
    # GPU type — search log content first, then path. Most app logs do
    # NOT contain "NVIDIA H100" — that string lives in nvidia-smi prelude
    # which isn't captured here — but we try anyway for the rare ones
    # that do, and tag the source so we can distinguish observation from
    # inference in the renderer.
    gpu_type = _detect_gpu_type(text[:8192]) or _detect_gpu_type(abs_path)
    if gpu_type:
        metrics["gpu_type"] = gpu_type
        metrics["gpu_type_source"] = "observed"
    # Provider — strongest signal is path (runpod_*, lambda_*, etc.)
    provider = _detect_provider(abs_path) or _detect_provider(text[:4096])
    if provider:
        metrics["provider"] = provider
    # If we still don't have a GPU type, fall back to the binary
    # local/rented mapping. Tag as inferred so downstream knows.
    if "gpu_type" not in metrics:
        inferred = _infer_gpu_type(provider, metrics.get("n_gpus"))
        if inferred:
            metrics["gpu_type"] = inferred
            metrics["gpu_type_source"] = "inferred"
    # Tag the source of the val_bpb value so the renderer can prefer
    # log-derived measurements over commit-message claims.
    if "val_bpb" in metrics:
        if final_evals:
            metrics["val_bpb_source"] = "log_final_eval"
        elif "val_bpb_during_run_best" in metrics:
            metrics["val_bpb_source"] = "log_step_best"

    # Train time + step count from last occurrence
    trains = RE_LOG_TRAIN_TIME.findall(text)
    if trains:
        metrics["train_time_seconds"] = int(trains[-1]) / 1000.0
    steps = RE_LOG_STEP_NUM.findall(text)
    if steps:
        metrics["step_final"] = int(steps[-1])

    # Reference-baseline detection. Keep this narrow: dated records/track_*
    # folders can be real user work and must stay visible in daily reports.
    if _is_reference_baseline_path(abs_path):
        metrics["is_reference_baseline"] = True

    # content_sha256 — lets the renderer dedup the same training-log file
    # copied across multiple worktrees / pod-pulls. Hash the bytes we read.
    record["content_sha256"] = hashlib.sha256(
        text.encode("utf-8", errors="replace")
    ).hexdigest()

    if metrics:
        record["metrics_json"] = json.dumps(metrics)

    # Filename-embedded timestamp (run start). Stored as a metric for now;
    # the record's primary mtime stays as filesystem mtime.
    fn_ts = RE_FILENAME_TS.search(fn)
    if fn_ts:
        metrics["filename_run_start"] = f"{fn_ts.group(1)}T{fn_ts.group(2)}"
        record["metrics_json"] = json.dumps(metrics)

    # Summary: best-of-run + final-eval block + GPU count
    summary_parts: list[str] = []
    if "val_bpb" in metrics:
        summary_parts.append(f"val_bpb={metrics['val_bpb']:.4f}")
    if "val_bpb_during_run_best" in metrics:
        summary_parts.append(f"best-during-run={metrics['val_bpb_during_run_best']:.4f}")
    for k, v in final_evals.items():
        if k != "val_bpb":
            summary_parts.append(f"{k.replace('val_bpb_', '')}={v:.4f}")
    if "n_ranks" in metrics:
        summary_parts.append(f"{metrics['n_ranks']} ranks")
    if "train_time_seconds" in metrics:
        summary_parts.append(f"train_time={metrics['train_time_seconds']:.0f}s")
    if "step_final" in metrics:
        summary_parts.append(f"step={metrics['step_final']}")
    if summary_parts:
        record["summary"] = " · ".join(summary_parts)
    else:
        # Pure-text fallback for logs with no recognized patterns
        tail = "\n".join(text.strip().splitlines()[-12:]).strip()
        record["summary"] = tail[:1000]

    return record


HANDLERS = {
    "markdown": handle_markdown,
    "json_summary": handle_json_summary,
    "python_module": handle_python_module,
    "csv_meta": handle_csv_meta,
    "checkpoint_meta": handle_checkpoint_meta,
    "training_log": handle_training_log,
}

MAX_BYTE_KEY = {
    "markdown": "max_md_bytes",
    "json_summary": "max_json_bytes",
    "python_module": "max_py_bytes",
    "csv_meta": "max_csv_bytes",
    "checkpoint_meta": "max_pt_bytes",
    "training_log": "max_log_bytes",
}


# ---------- Walker -------------------------------------------------------------

def walk_root(root_cfg: dict[str, Any], cfg: dict[str, Any], smoke_remaining: int | None,
              counters: dict[str, int]):
    root = root_cfg["path"]
    label = root_cfg["label"]
    excludes = set(cfg["exclude_dir_names"])
    ext_map = cfg["ext_handler_map"]

    if not os.path.isdir(root):
        print(f"  [skip-missing] {root}")
        return []

    out: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        # Mutate dirnames in-place to prune walk
        dirnames[:] = [d for d in dirnames if d not in excludes]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            handler_name = ext_map.get(ext)
            if not handler_name:
                continue
            abs_path = os.path.join(dirpath, fn)
            try:
                st = os.stat(abs_path, follow_symlinks=False)
            except OSError:
                continue
            counters["scanned"] += 1
            handler = HANDLERS[handler_name]
            max_bytes = cfg.get(MAX_BYTE_KEY[handler_name], 0)
            try:
                rec = handler(abs_path, st.st_size, max_bytes)
            except Exception as e:  # noqa: BLE001 — handler isolation
                rec = {"file_kind": "?", "parse_error": f"handler_crash:{type(e).__name__}:{e}"}

            # Filename-fallback title for any record that didn't get one
            if not rec.get("title"):
                stem = os.path.splitext(fn)[0]
                rec["title"] = stem[:300] if stem else fn[:300]
            if not rec.get("summary"):
                rec["summary"] = fallback_summary(rec, fn, st.st_size, handler_name)
            rec.update({
                "source_root": root,
                "source_label": label,
                "rel_path": os.path.relpath(abs_path, root),
                "abs_path": abs_path,
                "file_size_bytes": st.st_size,
                "mtime_iso": dt.datetime.fromtimestamp(st.st_mtime, tz=dt.timezone.utc)
                                .isoformat(timespec="seconds").replace("+00:00", "Z"),
                "extraction_version": EXTRACTION_VERSION,
                "extracted_at_iso": dt.datetime.now(tz=dt.timezone.utc)
                                       .isoformat(timespec="seconds").replace("+00:00", "Z"),
            })
            rec.setdefault("too_large", 0)
            out.append(rec)
            counters["kept"] += 1
            if smoke_remaining is not None:
                smoke_remaining -= 1
                if smoke_remaining <= 0:
                    return out
    return out


def main():
    ap = argparse.ArgumentParser(description="Deterministic research collator stripper.")
    ap.add_argument("--config", default=str(Path(__file__).parent / "config.yaml"))
    ap.add_argument("--smoke", type=int, default=None,
                    help="Cap total files processed across all roots (testing).")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    db_path = cfg["sqlite_path"]
    conn = init_db(db_path)
    counters = {"scanned": 0, "kept": 0}

    started_at = dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    t0 = time.perf_counter()
    smoke_remaining = args.smoke

    print(f"stripper {EXTRACTION_VERSION} -> {db_path}")
    if smoke_remaining is not None:
        print(f"smoke mode: cap {smoke_remaining} files")

    all_records: list[dict[str, Any]] = []
    for root_cfg in cfg["roots"]:
        print(f"-> {root_cfg['label']:30s} {root_cfg['path']}")
        before = counters["kept"]
        records = walk_root(root_cfg, cfg, smoke_remaining, counters)
        all_records.extend(records)
        added = counters["kept"] - before
        print(f"   kept {added} files (running total {counters['kept']}/{counters['scanned']})")
        if smoke_remaining is not None:
            smoke_remaining = max(0, smoke_remaining - added)
            if smoke_remaining == 0:
                break

    # Single bulk write
    with conn:
        for rec in all_records:
            upsert_artifact(conn, rec)

    wall = time.perf_counter() - t0
    finished_at = dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO walk_runs (started_at_iso, finished_at_iso, total_files_scanned, "
        "total_files_kept, wall_seconds, stripper_version, config_snapshot) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (started_at, finished_at, counters["scanned"], counters["kept"], wall,
         EXTRACTION_VERSION, json.dumps({"roots": [r["label"] for r in cfg["roots"]],
                                          "smoke": args.smoke})),
    )
    conn.commit()
    conn.close()

    print(f"\ndone. scanned={counters['scanned']} kept={counters['kept']} wall={wall:.2f}s")
    print(f"index: {db_path}")


if __name__ == "__main__":
    main()
