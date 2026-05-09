#!/usr/bin/env python3
"""Render ONE day's locked daily research report.

The visual and structural contract lives in TEMPLATE.md. This file turns
scraper/enrich/classify records into that template instance; it should repair
data attribution, not invent a new report shape.

Usage:
    python3 render_day.py --date 2026-04-26
    python3 render_day.py --day 1
    python3 render_day.py --date 2026-04-26 --metric val_loss
"""

from __future__ import annotations

import argparse
import atexit
import datetime as dt
import hashlib
import html
import json
import math
import os
import re
import shutil
import sqlite3
import sys

from collections import defaultdict
from pathlib import Path

import plot as plot_mod

DB = "/home/frosty40/research_collator/index.sqlite"
OUT_ROOT = Path("/home/frosty40/research_collator/output")
QMD_DIR = OUT_ROOT / "days"
HTML_DIR = OUT_ROOT / "preview"
ASSETS_DIR = OUT_ROOT / "assets"
FRAGMENTS_DIR = HTML_DIR / "fragments"
ABLATION_LABELS_PATH = Path(os.environ.get(
    "ABLATION_LABELS_PATH",
    str(OUT_ROOT / "ablation_labels" / "approved.jsonl"),
))
AUDIT_FINDINGS_PATH = OUT_ROOT / "audit" / "AUDIT_FINDINGS_2026-05-07.md"
DAILY_ACCURACY_PATH = OUT_ROOT / "audit" / "daily_accuracy.json"
LOCKED_TEMPLATE_HTML = Path(__file__).parent / "templates" / "daily_report_locked.html"
ARCHITECTURE_RECIPES_PATH = Path(__file__).parent / "data" / "architecture_recipes.json"
ARCHITECTURE_RUN_FILE_MANIFEST_PATH = (
    Path(__file__).parent / "public" / "architecture-run-files" / "manifest.json"
)
LOCKED_TEMPLATE_STYLE_SHA256 = "d7e5221bc1da151d6ae918a5fb5cab8653274d6336f638c7d051202b5284abdf"
DAILY_TEMPLATE_STANDARD = "daily-report-v2.6-architecture-recipes"
RESEARCH_START_DATE = "2026-03-18"
RESEARCH_END_DATE = "2026-05-01"
FINAL_SUBMISSION_NAME = "Mockingbird"
FINAL_SUBMISSION_DIR_TOKEN = "2026-05-01_Mockingbird_8xH100"
FINAL_SUBMISSION_PUBLIC_LABEL = "10k-vocabulary CaseOps loop-body submission"
TRAINING_LOG_EMBED_CACHE: dict[str, str] = {}
ARCHITECTURE_RECIPE_CACHE: dict[str, dict] | None = None
ARCHITECTURE_RUN_FILE_CACHE: dict[str, dict] | None = None

DATE_FROM_FILENAME = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")
HARDWARE_PATTERNS = (
    # GPU mentions in title/path/blurb. Lowercased before match.
    # More specific patterns FIRST so "8xh100" beats "h100".
    (r"\b8x[\s_-]*h100\b",  "8×H100"),
    (r"\b4x[\s_-]*h100\b",  "4×H100"),
    (r"\b2x[\s_-]*h100\b",  "2×H100"),
    (r"\b1x[\s_-]*h100\b",  "1×H100"),
    (r"\b8x[\s_-]*a100\b",  "8×A100"),
    (r"\b8gpu\b",          "8 GPU"),
    (r"\b4gpu\b",          "4 GPU"),
    (r"\b2gpu\b",          "2 GPU"),
    (r"\bh200\b",          "H200"),
    (r"\bh100\b",          "H100"),
    (r"\ba100\b",          "A100"),
    (r"\b5090\b",          "RTX 5090"),
    (r"\b4090\b",          "RTX 4090"),
    (r"\bdgx[-_ ]?spark\b","DGX Spark"),
    (r"\bgb10\b",          "GB10"),
    (r"\b8[\s_-]*x\b",     "8 GPU"),  # weak fallback if context says "8x"
    (r"\b4[\s_-]*x\b",     "4 GPU"),
)

KERNEL_CAMP = "kernel"
KERNEL_FB_RATIO_METRIC = "kernel_fb_ratio"
KERNEL_FWD_RATIO_METRIC = "kernel_fwd_ratio"
KERNEL_METRICS = (KERNEL_FB_RATIO_METRIC, KERNEL_FWD_RATIO_METRIC)
HEADLINE_METRICS = (
    KERNEL_FB_RATIO_METRIC,
    KERNEL_FWD_RATIO_METRIC,
    "val_bpb",
    "val_loss",
    "val_bits_per_byte",
    "bpb",
)
BPB_METRICS = {"val_bpb", "val_bits_per_byte", "bpb"}
INVALID_VAL_BPB_FLOOR = 1.06
CRASH_VAL_BPB_THRESHOLD = 3.0
CHAT_SESSION_KINDS = {"codex_session", "claude_session"}
PRESENTATION_EXCLUDED_KINDS = CHAT_SESSION_KINDS | {"conversation_arch_event"}
SUPPORTING_FILE_KINDS = {
    "training_log", "md", "text", "asset", "py", "json", "csv", "ckpt",
}
SUPPORTING_EXCLUDED_KINDS = CHAT_SESSION_KINDS | {"git_commit"}
SUPPORTING_RELEVANCE_RE = re.compile(
    r"(?:^|/)(?:logs?|runs?|results?|outputs?|artifacts?|checkpoints?|reports?|"
    r"plans?|planning|notes?|analysis|eval|tests?|bench|scripts?)(?:/|$)|"
    r"(?:log|launcher|run|result|metric|eval|bench|test|plan|handoff|summary|"
    r"readme|todo|notes?)",
    re.IGNORECASE,
)
CAMP_DISPLAY_LABEL = {
    KERNEL_CAMP: "kernel",
    "experimental": "experimental",
    "neural": "neural",
    "daily_grind": "daily grind",
}
CLASSIFICATION_CAMP_ORDER = (KERNEL_CAMP, "experimental", "neural")
CLASSIFICATION_SEG_CLASS = {
    KERNEL_CAMP: "alloc-seg-kernel",
    "experimental": "alloc-seg-exp",
    "neural": "alloc-seg-neu",
}
CLASSIFICATION_TEXT_CLASS = {
    KERNEL_CAMP: "alloc-text-kernel",
    "experimental": "alloc-text-exp",
    "neural": "alloc-text-neu",
}
METRIC_DISPLAY_LABEL = {
    KERNEL_FB_RATIO_METRIC: "CUSTOM/FA3 FB RATIO",
    KERNEL_FWD_RATIO_METRIC: "CUSTOM/FA3 FWD RATIO",
    "val_bpb": "VAL_BPB",
    "val_loss": "VAL_LOSS",
    "val_bits_per_byte": "VAL_BITS_PER_BYTE",
    "bpb": "BPB",
}
RESEARCH_CHRONOLOGY_SOURCE_LABELS = {
    "parameter-golf-lab", "git:parameter-golf-lab",
    "open_parameter_golf_junkyard",
    "parameter-golf-cross-repo",
    "sota_crawler", "git:sota_crawler",
    "sota_nueral", "git:sota_nueral",
    "sota_nueral_archive",
    "SOTA_FINAL", "git:SOTA_FINAL",
    "sota_rascal", "git:sota_rascal",
    "pg_whale", "git:pg_whale",
    "rascal-private", "git:rascal-private",
    "sota_rascal_pod_saves",
    "conversation_architecture",
}


def is_bpb_metric(metric: str | None) -> bool:
    if not metric:
        return False
    return metric in BPB_METRICS or metric.startswith("val_bpb")


def is_kernel_metric(metric: str | None) -> bool:
    return metric in KERNEL_METRICS


def metric_display_name(metric: str | None) -> str:
    if not metric:
        return "METRIC"
    return METRIC_DISPLAY_LABEL.get(metric, metric.upper())


def format_metric_value(metric: str | None, value: float) -> str:
    if is_kernel_metric(metric):
        return f"{value:.3f}×"
    return f"{value:.4f}"


def is_below_floor(metric: str | None, value: float) -> bool:
    return is_bpb_metric(metric) and value < INVALID_VAL_BPB_FLOOR


def is_crash_value(metric: str | None, value: float) -> bool:
    return is_bpb_metric(metric) and value > CRASH_VAL_BPB_THRESHOLD


def is_valid_metric_value(metric: str | None, value: float) -> bool:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        return False
    if not is_bpb_metric(metric):
        return True
    return INVALID_VAL_BPB_FLOOR <= value <= CRASH_VAL_BPB_THRESHOLD


def metrics_dict(rec: dict) -> dict:
    try:
        md = json.loads(rec.get("metrics_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        md = {}
    return md if isinstance(md, dict) else {}


def is_reference_baseline_record(rec: dict) -> bool:
    return bool(metrics_dict(rec).get("is_reference_baseline"))


def is_research_chronology_record(rec: dict) -> bool:
    """True when a record should create/count a daily research date.

    Public upstream competition records are still indexable reference corpus,
    but they do not define the user's day numbering or journey.
    """
    if is_reference_baseline_record(rec):
        return False
    return (rec.get("source_label") or "") in RESEARCH_CHRONOLOGY_SOURCE_LABELS


def is_research_campaign_date(date: str | None) -> bool:
    return bool(date and RESEARCH_START_DATE <= date <= RESEARCH_END_DATE)


def is_final_submission_record(rec: dict) -> bool:
    path = (rec.get("abs_path") or "").lower()
    return FINAL_SUBMISSION_DIR_TOKEN.lower() in path


def final_submission_records_for_day(date: str, records: list[dict]) -> list[dict]:
    if date != RESEARCH_END_DATE:
        return []
    return [r for r in records if is_final_submission_record(r)]


def report_records_for_date(date: str, records: list[dict]) -> list[dict]:
    """Keep daily reports aligned with the research chronology contract.

    Dates before the research start remain inspectable as raw/prelude pages.
    Research days use the same source/reference filter as day numbering, then
    drop chat/session-derived artifacts so conversations never surface in the
    report body.
    """
    if date < RESEARCH_START_DATE:
        scoped = records
    else:
        scoped = [r for r in records if is_research_chronology_record(r)]
    scoped = [r for r in scoped if r.get("file_kind") not in PRESENTATION_EXCLUDED_KINDS]
    if date < RESEARCH_START_DATE:
        return scoped
    return scoped


def ablation_title_sha(title: str) -> str:
    return hashlib.sha256(title.encode("utf-8", errors="replace")).hexdigest()


def format_day_index(day_index: int | None) -> str:
    return f"{day_index:03d}" if isinstance(day_index, int) else "—"


def best_date(rec: dict) -> str | None:
    """Prefer date embedded in FILENAME (most specific to the artifact),
    then path parent, then mtime. Calendar-validated.

    Why filename first: a runpod log might live at
    `.../runpod_2026_03_30_logs/logs/medusa6_..._20260328_072024.log` —
    the parent dir is the dump date (when it got pulled), but the filename
    is the actual run date. We want the run date.
    """
    abs_path = rec.get("abs_path") or ""
    rel_path = rec.get("rel_path") or ""

    # Git commit identities are SHA strings; their hex can accidentally contain
    # calendar-looking substrings. Commit rows must date by commit mtime only.
    if rec.get("file_kind") == "git_commit":
        return _mtime_local_date(rec)

    # 1. Filename only (basename)
    for src in (abs_path, rel_path):
        if not src:
            continue
        fn = os.path.basename(src)
        m = DATE_FROM_FILENAME.search(fn)
        if m:
            y, mo, d = m.group(1), m.group(2), m.group(3)
            try:
                if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31 and 2024 <= int(y) <= 2030:
                    return f"{y}-{mo}-{d}"
            except ValueError:
                pass

    # 2. Full path (catches dir-named-by-date conventions like legs/2026-04-15_*)
    for src in (abs_path, rel_path):
        m = DATE_FROM_FILENAME.search(src)
        if m:
            y, mo, d = m.group(1), m.group(2), m.group(3)
            try:
                if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31 and 2024 <= int(y) <= 2030:
                    return f"{y}-{mo}-{d}"
            except ValueError:
                pass

    # 3. mtime fallback — convert UTC mtime to user's local TZ before
    # extracting the date. The stripper records mtime in UTC; the user
    # thinks in CDT (UTC-5). Without this, late-evening runs roll into
    # the next day's report (e.g. Apr 20 23:30 local → Apr 21 UTC).
    return _mtime_local_date(rec)


def _mtime_local_date(rec: dict) -> str | None:
    if not rec.get("mtime_iso"):
        return None
    try:
        utc = dt.datetime.fromisoformat(rec["mtime_iso"].replace("Z", "+00:00"))
        local = utc - dt.timedelta(hours=5)  # CDT
        return local.date().isoformat()
    except (ValueError, TypeError):
        return rec["mtime_iso"][:10]


def fetch_day(conn: sqlite3.Connection, date: str) -> list[dict]:
    """Records belonging to `date` in the user's local TZ (CDT).

    We over-fetch (date(mtime, '-5h') OR path-LIKE for date-named dirs)
    then refine with best_date(). Dedup by content_sha256 so the same
    training-log file copied across worktrees collapses to one record.
    """
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT * FROM artifacts WHERE "
        "date(mtime_iso, '-5 hours')=? OR rel_path LIKE ? OR abs_path LIKE ?",
        (date, f"%{date.replace('-', '')}%", f"%{date}%"),
    ).fetchall()
    out = []
    seen_sha: set[str] = set()
    for r in rows:
        rec = dict(r)
        if best_date(rec) != date:
            continue
        sha = rec.get("content_sha256")
        if sha:
            if sha in seen_sha:
                continue
            seen_sha.add(sha)
        out.append(rec)
    return out


def extract_metric_for_record(metrics_json: str | None, metric_name: str) -> list[float]:
    if not metrics_json:
        return []
    try:
        md = json.loads(metrics_json)
    except json.JSONDecodeError:
        return []
    if metric_name in KERNEL_METRICS:
        return extract_kernel_ratio_metrics(md, metric_name)
    direct = md.get(metric_name)
    if isinstance(direct, (int, float)) and not isinstance(direct, bool):
        return [float(direct)]
    out = []
    for k, v in md.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        leaf = k.split("[")[0].split(".")[-1]
        if leaf == metric_name:
            out.append(float(v))
    return out


def extract_kernel_ratio_metrics(md: dict, metric_name: str) -> list[float]:
    """Derived custom-kernel/FA3 timing ratio. Lower means custom is faster."""
    if not isinstance(md, dict):
        return []
    mode = "fb" if metric_name == KERNEL_FB_RATIO_METRIC else "fwd"
    values: list[float] = []

    source_custom = md.get(f"source_metrics.whale_{mode}_mean_ms")
    source_fa3 = md.get(f"source_metrics.fa3_{mode}_mean_ms")
    if _positive_number(source_custom) and _positive_number(source_fa3):
        values.append(float(source_custom) / float(source_fa3))

    custom_by_idx: dict[str, float] = {}
    fa3_by_idx: dict[str, float] = {}
    pattern = re.compile(
        rf"^results\[(\d+)\]\.backends\.(whale_fast|whale|custom|kernel|blessed_whale)\.{mode}_mean_ms$"
    )
    fa3_pattern = re.compile(
        rf"^results\[(\d+)\]\.backends\.fa3\.{mode}_mean_ms$"
    )
    for key, value in md.items():
        if not _positive_number(value):
            continue
        m = pattern.match(str(key))
        if m:
            custom_by_idx.setdefault(m.group(1), float(value))
            continue
        fm = fa3_pattern.match(str(key))
        if fm:
            fa3_by_idx.setdefault(fm.group(1), float(value))
    for idx in sorted(set(custom_by_idx) & set(fa3_by_idx), key=int):
        values.append(custom_by_idx[idx] / fa3_by_idx[idx])
    return values


def _positive_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def metric_count(records: list[dict], metric: str) -> int:
    n = 0
    for rec in records:
        if is_reference_baseline_record(rec):
            continue
        n += len(extract_metric_for_record(rec.get("metrics_json"), metric))
    return n


def pick_headline_metric(records: list[dict]) -> str | None:
    # Kernel-heavy whale/crawler days are about custom kernel vs FA3 timing,
    # even when adjacent files also contain validation BPB. Treat those timing
    # ratios as the primary metric whenever at least two comparable benchmarks
    # are present.
    for metric in KERNEL_METRICS:
        if metric_count(records, metric) >= 2:
            return metric
    for metric in HEADLINE_METRICS:
        if metric in KERNEL_METRICS:
            continue
        n = 0
        for rec in records:
            if is_reference_baseline_record(rec):
                continue
            if extract_metric_for_record(rec.get("metrics_json"), metric):
                n += 1
                if n >= 2:
                    return metric
    return None


def best_before(conn: sqlite3.Connection, date: str, metric: str) -> float | None:
    """Best valid prior metric across records strictly before date.

    For BPB-style metrics, below-floor values are known eval/loader errors and
    crash-class values are not personal-best candidates. They still remain in
    their daily report; they just cannot become the baseline-to-beat.
    """
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT abs_path, rel_path, mtime_iso, metrics_json FROM artifacts "
        "WHERE metrics_json IS NOT NULL"
    ).fetchall()
    best = None
    for r in rows:
        rec = dict(r)
        bd = best_date(rec)
        if not bd or bd >= date:
            continue
        if is_reference_baseline_record(rec):
            continue
        for v in extract_metric_for_record(rec["metrics_json"], metric):
            if not is_valid_metric_value(metric, v):
                continue
            if best is None or v < best:
                best = v
    return best


# ---------- header stats ----------------------------------------------------

def hours_worked(records: list[dict], report_date: str,
                 gap_minutes: float = 30.0) -> float:
    """Estimated hours of actual file activity on the report date.

    File mtimes get clustered with a `gap_minutes`-minute threshold — gaps
    longer than that split a work session. Returns the sum of session
    durations, which is much closer to "hours actually working" than a
    naive (max - min) span.

    Rationale: a researcher who worked 5am–10am, took a break, then 6pm–10pm
    has ~9 hours of activity, not 17."""
    if not records:
        return 0.0
    parsed = []
    for r in records:
        t = r.get("mtime_iso") or ""
        if not t.startswith(report_date):
            continue
        try:
            parsed.append(dt.datetime.fromisoformat(t.replace("Z", "+00:00")))
        except ValueError:
            continue
    if len(parsed) < 2:
        return 0.0
    parsed.sort()
    clusters: list[tuple[dt.datetime, dt.datetime]] = []
    start = end = parsed[0]
    gap = dt.timedelta(minutes=gap_minutes)
    for t in parsed[1:]:
        if t - end > gap:
            clusters.append((start, end))
            start = end = t
        else:
            end = t
    clusters.append((start, end))
    total = sum((e - s).total_seconds() for s, e in clusters)
    return total / 3600.0


def tests_variety_pct(records: list[dict], metric: str) -> tuple[int, int, float]:
    """unique-test-titles, total-datapoints, variety percentage.
    Returns (unique, total, pct). Reference-baseline records are excluded
    so the count matches the Test Runs table."""
    titles_per_dp: list[str] = []
    for rec in records:
        if is_reference_baseline_record(rec):
            continue
        title = (rec.get("title") or "").strip()
        for _v in extract_metric_for_record(rec.get("metrics_json"), metric):
            titles_per_dp.append(title)
    total = len(titles_per_dp)
    if total == 0:
        return (0, 0, 0.0)
    unique = len(set(titles_per_dp))
    return (unique, total, 100.0 * unique / total)


# ---------- per-record extraction for the test table ------------------------

def detect_hardware(text: str) -> str:
    """Pattern-match a known GPU / hardware family in arbitrary text."""
    if not text:
        return ""
    low = text.lower()
    for pat, label in HARDWARE_PATTERNS:
        if re.search(pat, low):
            return label
    return ""


# Map of repo-label → GitHub HTTPS root, used to build clickable commit URLs.
GITHUB_REMOTES = {
    "git:parameter-golf-lab": "https://github.com/newjordan/parameter-golf",
    "git:sota_crawler":       "https://github.com/newjordan/parameter-golf",
    "git:SOTA_FINAL":         "https://github.com/newjordan/Fartmagic",
    "git:sota_rascal":        "https://github.com/newjordan/rascal",
    "git:ml-lab":             "https://github.com/newjordan/ml-lab",
    "git:sota_nueral":        "https://github.com/newjordan/sota_nueral",
    "git:dotagents_mono":     "https://github.com/newjordan/GR44",
    "git:qwen_agent":         "https://github.com/QwenLM/Qwen-Agent",
    "git:pg_whale":           "https://github.com/newjordan/blessed_whale",
    "git:rascal-private":     "https://github.com/newjordan/rascal",
}
HOME = "/home/frosty40"
SERVE_BASE = "http://dgx-spark:8765"   # HTTP server now serves $HOME at this base


def _build_link(rec: dict) -> tuple[str, str]:
    """Return (label, href) for one artifact's clickable link."""
    abs_path = rec.get("abs_path") or ""
    kind = rec.get("file_kind") or ""
    if kind == "git_commit":
        # abs_path is "git://<repo_label>/<sha>"
        m = re.match(r"git://([^/]+)/([0-9a-f]{40})$", abs_path)
        if m:
            label, sha = m.group(1), m.group(2)
            base = GITHUB_REMOTES.get(label)
            if base:
                return ("commit", f"{base}/commit/{sha}")
            return ("commit", "")
        return ("commit", "")
    if abs_path.startswith(HOME + "/"):
        rel = abs_path[len(HOME) + 1:]
        # http server is rooted at HOME so this URL is fetchable from the tailnet
        return (kind or "file", f"{SERVE_BASE}/{rel}")
    return (kind or "file", "")


def _file_href(abs_path: str, label: str = "file") -> tuple[str, str]:
    """Return a served file URL for a local absolute path."""
    if abs_path.startswith(HOME + "/"):
        rel = abs_path[len(HOME) + 1:]
        return (label, f"{SERVE_BASE}/{rel}")
    return (label, "")


def _training_log_ref(rec: dict) -> dict | None:
    if rec.get("file_kind") != "training_log":
        return None
    abs_path = rec.get("abs_path") or ""
    if not abs_path:
        return None
    label, href = _file_href(abs_path, "open file")
    return {
        "abs_path": abs_path,
        "basename": os.path.basename(abs_path) or "training_log",
        "href": href,
        "href_label": label,
        "size": rec.get("file_size_bytes"),
    }


def _append_training_log_ref(row: dict, rec: dict) -> None:
    ref = _training_log_ref(rec)
    if not ref:
        return
    logs = row.setdefault("training_logs", [])
    if all(existing.get("abs_path") != ref["abs_path"] for existing in logs):
        logs.append(ref)


def _find_run_script(rec: dict) -> str | None:
    """For a JSON test result inside a leg dir, find the launcher .sh next to it.
    Returns a SERVE_BASE URL or None."""
    abs_path = rec.get("abs_path") or ""
    if not abs_path.startswith(HOME + "/"):
        return None
    p = Path(abs_path)
    # Walk up to 3 parents looking for any *.sh
    for parent in [p.parent, p.parent.parent, p.parent.parent.parent]:
        if not parent.exists():
            continue
        sh = sorted(parent.glob("*.sh"))
        if sh:
            rel = str(sh[0])[len(HOME) + 1:]
            return f"{SERVE_BASE}/{rel}"
    return None


def _record_run_time_iso(rec: dict) -> str | None:
    """The TIME a test actually ran (not when its file was touched on disk).
    For training logs that were copied off a runpod later, mtime is the copy
    time; the filename has the actual run timestamp. Prefer that. If only
    mtime exists and the record date came from a dated run folder, preserve the
    recovered research date and use mtime only for the clock time.
    """
    md_str = rec.get("metrics_json") or ""
    if md_str:
        try:
            md = json.loads(md_str)
            fs = md.get("filename_run_start")
            # Format: "20260328T072024" → ISO with implicit-UTC suffix
            if isinstance(fs, str) and len(fs) == 15 and fs[8] == "T":
                y, mo, d, h, mi, s = fs[:4], fs[4:6], fs[6:8], fs[9:11], fs[11:13], fs[13:15]
                return f"{y}-{mo}-{d}T{h}:{mi}:{s}+00:00"
        except (json.JSONDecodeError, KeyError):
            pass
    mtime_iso = rec.get("mtime_iso")
    if not mtime_iso:
        return None
    bd = best_date(rec)
    try:
        mtime = dt.datetime.fromisoformat(mtime_iso.replace("Z", "+00:00"))
    except ValueError:
        return mtime_iso
    if bd and mtime.date().isoformat() != bd:
        return f"{bd}T{mtime.strftime('%H:%M:%S')}+00:00"
    return mtime_iso


def _hardware_from_record(rec: dict) -> str:
    """Compose a per-test hardware label from whatever signals the scraper
    extracted into metrics_json. Returns canonical strings like "8×H100",
    "1×RTX 5090 (runpod)", "DGX Spark (local)", or "" if unknown."""
    md_str = rec.get("metrics_json") or ""
    if not md_str:
        # Last-ditch path scan for provider+gpu strings
        path = rec.get("abs_path") or ""
        title = rec.get("title") or ""
        text = f"{path} {title}"
        gt = None
        for pat, label in (
            (re.compile(r"\bH100\b", re.I), "H100"),
            (re.compile(r"\bA100\b", re.I), "A100"),
            (re.compile(r"\b5090\b"), "RTX 5090"),
            (re.compile(r"\b4090\b"), "RTX 4090"),
            (re.compile(r"\bgb10\b|\bdgx[\s_-]?spark\b", re.I), "DGX Spark"),
        ):
            if pat.search(text):
                gt = label
                break
        return gt or ""

    try:
        md = json.loads(md_str)
    except json.JSONDecodeError:
        return ""

    gpu_type = md.get("gpu_type") or ""
    n_gpus = md.get("n_gpus") or md.get("n_ranks")
    provider = md.get("provider") or ""

    parts: list[str] = []
    if isinstance(n_gpus, int) and n_gpus > 0 and gpu_type:
        parts.append(f"{n_gpus}×{gpu_type}")
    elif gpu_type:
        parts.append(gpu_type)
    elif isinstance(n_gpus, int) and n_gpus > 0:
        parts.append(f"{n_gpus}× GPU")
    if provider and provider != "local":
        parts.append(f"({provider})")
    return " ".join(parts)


def _hardware_priority_key(rec: dict) -> int:
    """Hardware signals from training_log content > resolved_config JSON >
    submission JSON > anything else. Used to pick the most reliable
    per-test hardware label when multiple records contribute to one title."""
    kind = rec.get("file_kind")
    if kind == "training_log":
        return 0  # most reliable — actual rank prints + GPU init lines
    if kind == "json":
        return 1
    return 2


def _val_bpb_source(rec: dict) -> str:
    """Tag the source of a val_bpb value: log_final_eval > log_step_best >
    json_top_level > commit_message > unknown."""
    md_str = rec.get("metrics_json") or ""
    if not md_str:
        return "unknown"
    try:
        md = json.loads(md_str)
    except json.JSONDecodeError:
        return "unknown"
    return md.get("val_bpb_source") or "unknown"


_VAL_BPB_SOURCE_RANK = {
    "log_final_eval":   0,
    "log_step_best":    1,
    "json_top_level":   2,
    "commit_message":   3,
    "unknown":          4,
}


def _test_row_source_ref(rec: dict, metric: str, vals: list[float],
                         title: str, time_iso: str | None,
                         bpb_source: str) -> dict:
    return {
        "id": rec.get("id"),
        "title": title,
        "metric": metric,
        "metric_values": list(vals),
        "selected_value": min(vals) if vals else None,
        "time_iso": time_iso,
        "best_date": best_date(rec),
        "mtime_iso": rec.get("mtime_iso"),
        "source_label": rec.get("source_label"),
        "file_kind": rec.get("file_kind"),
        "camp": rec.get("camp"),
        "abs_path": rec.get("abs_path"),
        "rel_path": rec.get("rel_path"),
        "metrics_json": rec.get("metrics_json"),
        "val_bpb_source": bpb_source,
    }


def extract_test_rows(records: list[dict], metric: str,
                      reference_baseline: float | None) -> list[dict]:
    """One Test Run row per unique title, sorted by RUN TIME (chronological).

    Per-test fields are merged across ALL records sharing the title:
      - hardware: take the highest-priority signal (log > json > path)
      - value:    prefer the lower (better) value, AND prefer log-derived
                  values over commit-message claims when both exist.
      - source:   tag every row with where its val_bpb came from.
    """
    by_title: dict[str, dict] = {}
    for rec in records:
        vals = extract_metric_for_record(rec.get("metrics_json"), metric)
        if not vals:
            continue
        # Reference baselines aren't user tests, so exclude them from the
        # Test Runs view. They remain indexed for audit queries.
        if is_reference_baseline_record(rec):
            continue
        title = (rec.get("title") or "(untitled)").strip()
        wallclock = None
        if rec.get("file_kind") == "json":
            try:
                with open(rec["abs_path"]) as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    wallclock = raw.get("wallclock_seconds") or raw.get("wallclock")
                    if isinstance(raw.get("name"), str) and len(raw["name"]) > len(title):
                        title = raw["name"][:160]
            except (OSError, json.JSONDecodeError):
                pass

        hardware = _hardware_from_record(rec)
        hw_priority = _hardware_priority_key(rec)
        bpb_source = _val_bpb_source(rec)
        bpb_priority = _VAL_BPB_SOURCE_RANK.get(bpb_source, 9)

        time_iso = _record_run_time_iso(rec)
        time_str = ""
        if time_iso:
            try:
                t = dt.datetime.fromisoformat(time_iso.replace("Z", "+00:00"))
                time_str = t.strftime("%H:%M")
            except ValueError:
                pass

        link_label, link_href = _build_link(rec)
        run_script = _find_run_script(rec)

        best_val = min(vals)
        row_camp = KERNEL_CAMP if is_kernel_metric(metric) else rec["camp"]
        source_ref = _test_row_source_ref(rec, metric, vals, title, time_iso, bpb_source)
        cur = by_title.get(title)
        if cur is None:
            row = {
                "title": title,
                "metric": metric,
                "metric_display": metric_display_name(metric),
                "value": best_val,
                "n_runs": len(vals),
                "time": time_str,
                "time_iso": time_iso,
                "hardware": hardware,
                "hardware_priority": hw_priority if hardware else 99,
                "wallclock_seconds": wallclock,
                "camp": row_camp,
                "source_label": rec["source_label"],
                "abs_path": rec["abs_path"],
                "link_label": link_label,
                "link_href": link_href,
                "run_script": run_script,
                "val_bpb_source": bpb_source,
                "val_bpb_priority": bpb_priority,
                "training_logs": [],
                "source_records": [source_ref],
            }
            _append_training_log_ref(row, rec)
            by_title[title] = row
            continue

        cur["n_runs"] += len(vals)
        cur.setdefault("source_records", []).append(source_ref)
        _append_training_log_ref(cur, rec)
        # Hardware: prefer the highest-priority source we've seen.
        if hardware and hw_priority < cur.get("hardware_priority", 99):
            cur["hardware"] = hardware
            cur["hardware_priority"] = hw_priority
        # Value: prefer the more-reliable source. If sources tie, prefer the
        # lower (better) measurement. This is the verification path —
        # log-derived numbers override commit-message claims for the same
        # title.
        if bpb_priority < cur["val_bpb_priority"]:
            cur["value"] = best_val
            cur["val_bpb_source"] = bpb_source
            cur["val_bpb_priority"] = bpb_priority
        elif bpb_priority == cur["val_bpb_priority"] and best_val < cur["value"]:
            cur["value"] = best_val
        if wallclock and not cur["wallclock_seconds"]:
            cur["wallclock_seconds"] = wallclock

    # Sort by RUN TIME (chronological — the journey through the day)
    rows = sorted(by_title.values(), key=lambda r: r.get("time_iso") or "")
    for i, r in enumerate(rows, start=1):
        r["n"] = i
    if reference_baseline is not None and reference_baseline > 0:
        for r in rows:
            r["delta_vs_baseline"] = r["value"] - reference_baseline
            r["delta_pct"] = 100.0 * (r["value"] - reference_baseline) / reference_baseline
    else:
        for r in rows:
            r["delta_vs_baseline"] = None
            r["delta_pct"] = None
    return rows


def _category_metric_priority(camp: str | None) -> tuple[str, ...]:
    if camp == KERNEL_CAMP:
        return KERNEL_METRICS
    return ("val_bpb", "val_loss", "val_bits_per_byte", "bpb")


def _chosen_category_metric(rec: dict) -> str | None:
    camp = rec.get("camp")
    for metric in _category_metric_priority(camp):
        if extract_metric_for_record(rec.get("metrics_json"), metric):
            return metric
    return None


def extract_category_local_test_rows(records: list[dict]) -> list[dict]:
    """Measured rows using each record's category-local metric scale."""
    rows: list[dict] = []
    metrics = (
        KERNEL_FB_RATIO_METRIC,
        KERNEL_FWD_RATIO_METRIC,
        "val_bpb",
        "val_loss",
        "val_bits_per_byte",
        "bpb",
    )
    for metric in metrics:
        metric_records = [
            rec for rec in records
            if not is_reference_baseline_record(rec)
            and _chosen_category_metric(rec) == metric
        ]
        if not metric_records:
            continue
        rows.extend(extract_test_rows(metric_records, metric, None))

    rows.sort(key=lambda r: (r.get("time_iso") or "", r.get("camp") or "", r.get("title") or ""))
    for idx, row in enumerate(rows, start=1):
        row["n"] = idx
        row["delta_vs_baseline"] = None
        row["delta_pct"] = None
    return rows


def category_focus_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        camp = row.get("camp") or "experimental"
        if camp in (KERNEL_CAMP, "experimental", "neural"):
            counts[camp] += 1
    return dict(counts)


def week_focus_rows(conn: sqlite3.Connection, week_dates: list[str]) -> list[dict]:
    focus: list[dict] = []
    for week_date in week_dates:
        day_records = report_records_for_date(week_date, fetch_day(conn, week_date))
        final_records = final_submission_records_for_day(week_date, day_records)
        if final_records:
            day_records = final_records
        rows = extract_category_local_test_rows(day_records)
        focus.append({"date": week_date, "counts": category_focus_counts(rows)})
    return focus


def build_day_chart_records(records: list[dict], metric: str) -> list[dict]:
    """One chart entry per measured-metric occurrence, with run-time.
    For chart input — preserves time_iso so the trajectory plots correctly.
    Reference baselines are excluded — they're not user trajectory."""
    out = []
    for rec in records:
        if is_reference_baseline_record(rec):
            continue
        vals = extract_metric_for_record(rec.get("metrics_json"), metric)
        time_iso = _record_run_time_iso(rec)
        for v in vals:
            out.append({
                "value": v,
                "camp": KERNEL_CAMP if is_kernel_metric(metric) else rec.get("camp", "experimental"),
                "title": rec.get("title") or "(untitled)",
                "time_iso": time_iso,
            })
    return out


# ---------- bibliography ----------------------------------------------------

def _is_in_any_dir(abs_path: str, dirs: set[str]) -> bool:
    """True when abs_path is inside one of the detected test-run directories."""
    if not abs_path.startswith(HOME + "/"):
        return False
    norm_path = os.path.abspath(abs_path)
    for d in dirs:
        try:
            if os.path.commonpath([norm_path, d]) == d:
                return True
        except ValueError:
            continue
    return False


def is_rendered_support_record(rec: dict) -> bool:
    """True for day-local files/logs allowed to count as visible support stats."""
    return (
        rec.get("camp") != "daily_grind"
        and not is_reference_baseline_record(rec)
        and rec.get("file_kind") in SUPPORTING_FILE_KINDS
        and rec.get("file_kind") not in SUPPORTING_EXCLUDED_KINDS
    )


# Architecture family detection — inferred per-test from title patterns.
# Order matters: more-specific patterns come first.  Patterns are anchored on
# the family STEM and allow any trailing word characters / variants
# (medusa2, medusa_a_post_ema, ClownCar_IV, clowncar4 all match).
ARCH_FAMILIES = [
    # Reference / baseline runs (not user experiments — usually pre-labeled
    # via is_reference_baseline, but pattern-match as a fallback)
    ("NaiveBaseline",        r"\bnaive[\s_-]?baseline\w*|_NaiveBaseline\b"),
    # Specific compound names (must match before their components)
    ("AR Self-Gen GPTQ",     r"\bar[\s_-]+self[\s_-]+gen[\s_-]+gptq\b"),
    ("Binary U-Net",         r"\bbinary(?:[\s_-]+asymmetric)?[\s_-]+u[\s_-]?net"),
    ("Ternary U-Net",        r"\bternary[\s_-]+u[\s_-]?net"),
    ("Mixed Quant",          r"\bmixed[\s_-]+(?:precision[\s_-]+)?quant"),
    ("Depth Recurrence",     r"\bdepth[\s_-]+recurrence\b"),
    ("Parallel Residuals",   r"\bparallel[\s_-]+residual"),
    ("Sliding Window",       r"\bsliding[\s_-]+window\b"),
    ("Staged Hybrid Bench",  r"\bstaged[\s_-]+(?:primary|fallback)\b|\bhybrid[AB]\b"),
    ("Watch / Handoff",      r"\b(?:watch|handoff)(?:_daemon|_nohup|_logs|[\s_-]?\d{8})\b"),
    ("Spark Smoke Kit",      r"\b(?:SMK|spark[\s_-]?smoke)(?:[\s_-]\w*)?"),
    ("Cambrian Bio Seam",    r"\bcambrian\w*|\bbio[\s_-]+local\w*|\bmyelin\w*|\bcircadian\w*|\bastrocyte\w*|\bclonal[\s_-]+selection\w*"),
    ("Rat Rod",              r"\brat[\s_-]?rod\w*|\bjunkyard[\s_-]+rat\w*|\bgreen[\s_-]?v\d+\b|\bcomplement[\s_-]?alpha\b"),
    ("GreenRod",             r"\bgreen[\s_-]?rod\w*"),
    ("Crawler Ablation",     r"\bab[\s_-]+(?:rope\d*|vr[\s_-]+\w+|siphon[\s_-]+\w+)|\bbaseline(?:[\s_-]\w*)?"),
    ("Schedule Sweep",       r"\bsweep[\s_-]+(?:warmdown|swa)[\s_-]+\w*"),
    ("Tornado / Theta",      r"\btornado\w*|\btheta[\s_-]?gamma\w*|arm\d+[\s_-]+baseline[\s_-]+no[\s_-]+tornado\w*"),
    ("Compact Transformer Recipe", r"\bkiller\w*|\bstinky[\s_-]+frost\w*|\brecord[\s_-]+v\d+\b"),
    ("Progressive MLP / Fractal", r"\bfractal\w*|\bprogressive[\s_-]+mlp\w*|\babc[\s_-]+progressive\w*"),
    ("Leaderboard Transformer Variants", r"\bsubmit[\s_-]+s\d+\w*|\bf1[\s_-]\w*|\bcar\d+\w*|\bthree[\s_-]+breadsticks\w*|\bPR[\s_-]?#?\d+\w*|\bpr\d+\w*|\bleapfrog\w*|\bself[\s_-]+distillation\w*|\badd[\s_-]+seed[\s_-]?\d+\w*|\bD\+SAM\w*|\benchilada\w*|\bmtp\w*|\bswiglu\w*|\bvocab\d+\w*|\bclone\b"),
    ("Compression Packaging", r"\bbrotli\w*|\bmixedint\w*|\bmixed[\s_-]?int\w*"),
    ("SLOT Tuned Body",      r"\blucky\w*|\bslot[\s_-]\w*"),
    ("Cubric Racing Variant", r"\bpodracer\w*|\bracing[\s_-]+cubric\w*"),
    ("B-Wing",               r"\bb[\s_-]?wing\w*"),
    # Architecture / experiment family stems — match any suffix
    ("Medusa",               r"\bmedusa\w*"),
    ("ClownCar",             r"\bclown[\s_-]?car\w*"),
    ("Bandit",               r"\bbandit\w*"),
    ("Shroud",               r"\bshroud\w*"),
    ("Midnight",             r"\bmidnight\w*"),
    ("Rascal",               r"\brascal\w*"),
    ("Whale",                r"\b(?:blessed[\s_-]+)?whale\w*"),
    ("Megahelix",            r"\bmegahelix\w*"),
    ("Mockingbird",          r"\bmockingb[ir]rd\w*"),
    ("Helix",                r"\bhelix\w*"),
    ("Ouroboros",            r"\bouroboros\w*"),
    ("Nitrust",              r"\bnitrust\w*"),
    ("Frugendorff",          r"\bfrugendorff\w*"),
    ("Mikey",                r"\bmikey\w*"),
    ("X-Wing",               r"\b(?:[axfp][\s_-]?wing|fx[\s_-]?wing|fxwdelta|fawing)\w*"),
    ("Fartmagic",            r"\bfartmagic\w*"),
    ("Megakernel",           r"\bmegakernel\w*"),
    # Note: avoid trailing `\b` — "y" followed by "_" has no word-boundary
    # because `_` counts as a word character in Python regex. End matches
    # with `\w*` instead (matches the rest of the slug).
    ("Nightcrawler",         r"\bnightcrawler\w*"),
    ("SOTA Crawler",         r"\bsota[\s_-]+crawler\w*|\bcrawler(?:[\s_/-]+\w*)?|\bA\d+[\s_-]+screen\w*"),
    ("SOTA v2 TTT",          r"\bsota[\s_-]?v2[\s_-]+tttonly\w*"),
    ("Exp-D TTT8 Stride32",  r"\bexp[\s_-]?d(?:[\s_-]+ttt8\w*)?"),
    ("FP16 Tied Embed",      r"\bfp16[\s_-]+(?:tied[\s_-]+)?embed\w*"),
    ("Long Context",         r"\blong[\s_-]?context[\s_-]?seq\d+\w*|\bseq2048\w*"),
    ("Mixed Precision",      r"\bmixed[\s_-]+precision\w*"),
    ("Quasi-10B",            r"\bquasi[\s_-]?10[\s_-]?b\w*"),
    ("Lower LR",             r"\blower[\s_-]+lr\w*"),
    ("SwiGLU + Warmdown",    r"\bswiglu\w*.*\bwarmdown\w*"),
    ("Int6 QAT",             r"\bint6[\s_-]+(?:qat|sliding|middle)\w*|\bste[\s_-]+int6\w*"),
    ("SmearGate / MuonWD",   r"\bsmeargate\w*|\bmuon[\s_-]?wd\w*"),
    ("PGUT",                 r"\bpgut\w*"),
    # Components / methods (only fall-through if no family matched above)
    ("DeltaNet",             r"\bdeltanet\w*"),
    ("JEPA",                 r"\bjepa\b"),
    ("XSA",                  r"\bxsa(?:[\s_-]\w*)?"),
    ("BigramHash",           r"\bbigram[\s_-]?hash\w*"),
    ("GPTQ",                 r"\bgptq\w*"),
    ("LoRA-TTT",             r"\blora\b.*\bttt\b"),
    ("State-Space (TTT)",    r"\bstate[\s_-]+space\b|\bttt(?:[\s_-]?\w+)?\b"),
    ("Modded-nanoGPT",       r"\bmodded[\s_-]?nanogpt\w*"),
]

PUBLIC_ARCH_FAMILY_LABELS = {
    "A-Wing": "legal n-gram GPU mixer",
    "AR Self-Gen GPTQ": "autoregressive GPTQ calibration",
    "B-Wing": "entropy-shifted n-gram weighting",
    "Bandit": "crawler plus cubric n-gram stack",
    "Cambrian Bio Seam": "biology-inspired DeltaNet seam sweep",
    "ClownCar": "crawler-only ngram export body",
    "Compact Transformer Recipe": "compact transformer recipe",
    "Compression Packaging": "compression packaging experiment",
    "Cobra": "controlled A/B quality harness",
    "Crawler Ablation": "crawler ablation control set",
    "Cubric Racing Variant": "cubric racing variant",
    "DeltaNet": "Gated DeltaNet memory branch",
    "Exp-D TTT8 Stride32": "TTT8 stride-32 test family",
    "Fartmagic": "data/runtime workspace",
    "Frugendorff": "recursive weight-sharing transformer",
    "GPTQ": "post-training quantization calibration",
    "GreenRod": "hybrid GatedDeltaNet-attention body",
    "Helix": "split-head crawler scale gate",
    "Medusa": "loop-instructed DeltaNet crawler body",
    "Megahelix": "fused recurrence megakernel",
    "Mikey": "looped tokenizer body",
    "Midnight": "12L GQA mixed-bit tower",
    "Mockingbird": "10k-vocab CaseOps loop body",
    "NaiveBaseline": "reference baseline",
    "Nightcrawler": "widened crawler bottleneck",
    "Nitrust": "kernel preflight suite",
    "Ouroboros": "9-flat plus 1-crawler loop body",
    "Rascal": "11L GQA U-Net body",
    "Rat Rod": "recurrent green-branch prototype",
    "Schedule Sweep": "training schedule sweep",
    "Shroud": "trace and flow-capture wrapper",
    "SOTA Crawler": "crawler-safe train/eval surface",
    "SOTA v2 TTT": "TTT-only model test",
    "Staged Hybrid Bench": "staged attention-kernel bench",
    "Megakernel": "fused kernel implementation",
    "Mixed Quant": "mixed-precision quantization variant",
    "Parallel Residuals": "parallel residual transformer variant",
    "Sliding Window": "sliding-window evaluation variant",
    "State-Space (TTT)": "state-space TTT variant",
    "Tornado / Theta": "regularization/control sweep",
    "Leaderboard Transformer Variants": "leaderboard transformer variants",
    "Progressive MLP / Fractal": "progressive MLP and fractal cadence tests",
    "SLOT Tuned Body": "SLOT-tuned transformer body",
    "Whale": "dim-576 attention-kernel body",
    "X-Wing": "instructed crawler recurrence family",
    "XSA": "cross-sequence attention variant",
}

ARCH_RUN_FILE_FAMILY_ALIASES = {
    "Binary U-Net": "Binary / Ternary U-Net",
    "Ternary U-Net": "Binary / Ternary U-Net",
    "DeltaNet": "DeltaNet Crawler",
    "Megahelix": "VortexHelix / Megahelix",
    "Exp-D TTT8 Stride32": "SOTA v2 TTT",
    "Tornado / Theta": "Tornado",
    "GPTQ": "AR Self-Gen GPTQ",
}


def public_arch_label(name: str) -> str:
    """Reviewer-facing architecture label; internal nicknames stay in paths only."""
    return PUBLIC_ARCH_FAMILY_LABELS.get(name, name)


def load_architecture_run_file_manifest() -> dict[str, dict]:
    global ARCHITECTURE_RUN_FILE_CACHE
    if ARCHITECTURE_RUN_FILE_CACHE is not None:
        return ARCHITECTURE_RUN_FILE_CACHE
    try:
        raw = json.loads(ARCHITECTURE_RUN_FILE_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        ARCHITECTURE_RUN_FILE_CACHE = {}
        return ARCHITECTURE_RUN_FILE_CACHE
    entries = raw.get("entries") or []
    out: dict[str, dict] = {}
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            family = str(entry.get("family") or "").strip()
            if family:
                out[family] = entry
    ARCHITECTURE_RUN_FILE_CACHE = out
    return out


_ARCH_FAMILY_INDEX_CACHE: dict[str, dict] | None = None
_UNRESOLVED_ARCH_FAMILIES: set[str] = set()


def _normalize_family_key(name: str) -> str:
    """Normalized lookup key: lowercase, strip, collapse runs of -/_/whitespace
    into a single space. Lets 'A-Wing', 'a wing', 'AWING' all resolve together."""
    s = (name or "").strip().lower()
    out: list[str] = []
    last_sep = False
    for ch in s:
        if ch in "-_ \t\n/":
            if not last_sep:
                out.append(" ")
                last_sep = True
        else:
            out.append(ch)
            last_sep = False
    return "".join(out).strip()


def _build_architecture_family_index() -> dict[str, dict]:
    """Build a normalized-key -> manifest entry index for resolve_architecture_family.
    Folds in: each manifest entry's 'family', 'slug', 'slug-without-NN_-prefix',
    and comma-split 'aliases' field; the existing ARCH_RUN_FILE_FAMILY_ALIASES
    overrides; and any extra recipe keys from data/architecture_recipes.json."""
    global _ARCH_FAMILY_INDEX_CACHE
    if _ARCH_FAMILY_INDEX_CACHE is not None:
        return _ARCH_FAMILY_INDEX_CACHE
    manifest = load_architecture_run_file_manifest()
    index: dict[str, dict] = {}

    def _add(key: str, entry: dict) -> None:
        if not key or not entry:
            return
        norm = _normalize_family_key(key)
        if norm:
            index.setdefault(norm, entry)

    for fam, entry in manifest.items():
        _add(fam, entry)
        slug = str(entry.get("slug") or "")
        if slug:
            _add(slug, entry)
            if "_" in slug:
                # Slug like "01_a-wing" -> also index under "a-wing".
                _add(slug.split("_", 1)[1], entry)
        aliases_field = entry.get("aliases")
        if isinstance(aliases_field, str):
            for alias in aliases_field.split(","):
                _add(alias, entry)
        elif isinstance(aliases_field, (list, tuple)):
            for alias in aliases_field:
                _add(str(alias), entry)

    # Hand-curated overrides take precedence for known mismatches.
    for src, dest in ARCH_RUN_FILE_FAMILY_ALIASES.items():
        target = manifest.get(dest)
        if target:
            _add(src, target)

    # Recipe keys may carry display names that match a manifest entry only by
    # normalized form; index them too where they resolve.
    try:
        recipes_raw = json.loads(ARCHITECTURE_RECIPES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        recipes_raw = {}
    for recipe_name in (recipes_raw.get("recipes") or {}).keys():
        target = index.get(_normalize_family_key(recipe_name))
        if target:
            _add(recipe_name, target)

    _ARCH_FAMILY_INDEX_CACHE = index
    return index


def resolve_architecture_family(family: str) -> dict | None:
    """Resolve a row's family string to a manifest entry, or None.
    Order: exact / alias / slug / recipe-keyed match after normalization
    (lowercase, '-'/'_'/space equivalence). Misses are tracked for the
    end-of-run summary printed via atexit."""
    if not family:
        return None
    index = _build_architecture_family_index()
    return index.get(_normalize_family_key(family))


def _strip_public_prefix(p: str) -> str:
    return p[len("public/"):] if p.startswith("public/") else p


def architecture_download_button_html(family: str) -> str:
    entry = resolve_architecture_family(family)
    if not entry:
        if family:
            _UNRESOLVED_ARCH_FAMILIES.add(family)
        return "<span class='bpb-download-missing'>—</span>"
    parts: list[str] = []
    archive = entry.get("archive") or {}
    archive_path = _strip_public_prefix(str(archive.get("repo_path") or ""))
    if archive_path:
        parts.append(
            f"<a class='bpb-download-action' "
            f"href='{html.escape(archive_path, quote=True)}' download>download</a>"
        )
    repo_folder = _strip_public_prefix(str(entry.get("repo_folder") or ""))
    if not repo_folder:
        files = entry.get("files") or []
        if files and isinstance(files[0], dict):
            first = _strip_public_prefix(str(files[0].get("repo_path") or ""))
            if first:
                repo_folder = first
    if repo_folder:
        if not repo_folder.endswith("/") and "." not in repo_folder.rsplit("/", 1)[-1]:
            repo_folder = repo_folder + "/"
        parts.append(
            f"<a class='bpb-download-action' "
            f"href='{html.escape(repo_folder, quote=True)}'>source</a>"
        )
    if not parts:
        if family:
            _UNRESOLVED_ARCH_FAMILIES.add(family)
        return "<span class='bpb-download-missing'>—</span>"
    return "".join(parts)


def _print_unresolved_arch_summary() -> None:
    """End-of-run console summary listing family strings the resolver
    couldn't map to a manifest entry. Printed via atexit so it surfaces
    after the full corpus render completes regardless of entry point."""
    if not _UNRESOLVED_ARCH_FAMILIES:
        return
    print(
        f"[architecture] unresolved families ({len(_UNRESOLVED_ARCH_FAMILIES)}):",
        file=sys.stderr,
    )
    for fam in sorted(_UNRESOLVED_ARCH_FAMILIES):
        print(f"  - {fam!r}", file=sys.stderr)


atexit.register(_print_unresolved_arch_summary)


PUBLIC_TEXT_REPLACEMENTS = [
    (r"\bFrugendorff[\s_-]+Squared\w*", "recursive weight-sharing depth variant"),
    (r"\bThe[\s_-]+Frugendorff\w*", "recursive weight-sharing transformer"),
    (r"\bFrugendorff\w*", "recursive weight-sharing transformer"),
    (r"\bFX[\s_-]?Wing\w*", "instructed-recurrence crawler"),
    (r"\bFA[\s_-]?Wing\w*", "flow-instruction crawler hybrid"),
    (r"\bFXWDelta\w*", "DeltaNet crawler recurrence variant"),
    (r"\bF[\s_-]?Wing\w*", "crawler recurrence family"),
    (r"\bX[\s_-]?Wing\w*", "cubric n-gram mixer"),
    (r"\bA[\s_-]?Wing\w*", "legal n-gram GPU mixer"),
    (r"\bB[\s_-]?Wing\w*", "entropy-shifted n-gram weighting"),
    (r"\bBandit[\s_-]+Wagon\w*", "flat+crawler tap-off body"),
    (r"\bBandit\w*", "crawler plus cubric n-gram stack"),
    (r"\brat[\s_-]?rod\w*", "recurrent green-branch prototype"),
    (r"\bjunkyard[\s_-]+rat\w*", "recurrent green-branch prototype"),
    (r"\bgreen[\s_-]?v\d+\w*", "recurrent green-branch prototype variant"),
    (r"\bCOMPLEMENT_ALPHA\b", "complement-mix alpha"),
    (r"\bgreen[\s_-]?rod\w*", "hybrid GatedDeltaNet-attention body"),
    (r"\bkiller\w*", "compact transformer recipe"),
    (r"\bstinky[\s_-]+frost\w*", "compact transformer recipe"),
    (r"\bfractal\w*", "fractal cadence test"),
    (r"\bprogressive[\s_-]+mlp\w*", "progressive MLP test"),
    (r"\benchilada\w*", "12L/2KV/2.75xMLP experiment"),
    (r"\bthree[\s_-]+breadsticks\w*", "three-seed leaderboard variant"),
    (r"\bpodracer\w*", "cubric racing variant"),
    (r"\blucky\w*", "SLOT-tuned transformer body"),
    (r"\bbrotli\w*", "Brotli compression packaging"),
    (r"\bmixedint\w*", "mixed-int compression packaging"),
    (r"\bab[\s_-]+rope\d*\w*", "RoPE ablation arm"),
    (r"\bab[\s_-]+vr[\s_-]+on\w*", "value-residual ablation on arm"),
    (r"\bab[\s_-]+vr[\s_-]+off\w*", "value-residual ablation off arm"),
    (r"\bab[\s_-]+siphon[\s_-]+on\w*", "siphon ablation on arm"),
    (r"\bab[\s_-]+siphon[\s_-]+off\w*", "siphon ablation off arm"),
    (r"\bsweep[\s_-]+warmdown[\s_-]+\d+\w*", "warmdown schedule sweep arm"),
    (r"\bsweep[\s_-]+swa[\s_-]+\d+\w*", "SWA schedule sweep arm"),
    (r"\btheta[\s_-]?gamma\w*", "theta-gamma regularization arm"),
    (r"\bcambrian(?:[\s_-]+bio[\s_-]+sweep)?(?:[\s_-]+agent[\s_-]+final)?\w*", "biology-inspired DeltaNet seam sweep"),
    (r"\bbio[\s_-]+local[\s_-]+myelin\w*", "local chunk-bridge seam arm"),
    (r"\bbio[\s_-]+local[\s_-]+circadian\w*", "local state-flow seam arm"),
    (r"\bbio[\s_-]+local[\s_-]+astrocyte\w*", "local erase-gate seam arm"),
    (r"\bbio[\s_-]+local[\s_-]+clonal[\s_-]+selection\w*", "local state-amplification seam arm"),
    (r"\bgdn[\s_-]+myelin\w*", "GDN chunk-bridge seam arm"),
    (r"\bgdn[\s_-]+circadian\w*", "GDN state-flow seam arm"),
    (r"\bgdn[\s_-]+astrocyte\w*", "GDN erase-gate seam arm"),
    (r"\bgdn[\s_-]+clonal\w*", "GDN state-amplification seam arm"),
    (r"\bgdn[\s_-]+all\w*", "GDN all-controller arm"),
    (r"\bFartmagic\w*", "data/runtime workspace"),
    (r"\bThe[\s_-]+Stinky[\s_-]+Frost[\s_-]+Recipe\w*", "compression recipe"),
    (r"\bStinky[\s_-]+Frost[\s_-]+Recipe\w*", "compression recipe"),
    (r"\bSponge[\s_-]+Bath\w*", "TTT stride-32 eval-only experiment"),
    (r"\benchilada\w*", "12L/2KV/2.75xMLP experiment"),
    (r"\bkiller[\s_-]+v\d+\w*", "candidate run"),
    (r"\bJunkyard[\s_-]+Rat\w*", "Triton/model co-design body"),
    (r"\bRat[\s_-]+Rod\w*", "11L Parallel-Muon/XSA body"),
    (r"\bNightcrawler[\s_-]+Cubed\w*", "multi-crawler descendant"),
    (r"\bNightcrawler\w*", "widened crawler bottleneck"),
    (r"\bClown[\s_-]?Car\w*", "crawler-only ngram export body"),
    (r"\bMedusa\w*", "loop-instructed DeltaNet crawler body"),
    (r"\bRascal\w*", "11L GQA U-Net body"),
    (r"\bMidnight\w*", "12L GQA mixed-bit tower"),
    (r"\bMockingb[ir]rd\w*", "10k-vocab CaseOps loop body"),
    (r"\bWhale\w*", "dim-576 attention-kernel body"),
    (r"\bOuroboros\w*", "9-flat plus 1-crawler loop body"),
    (r"\bMikey\w*", "looped tokenizer body"),
    (r"\bRaphe\w*", "compact tokenizer body"),
    (r"\bDonnie\w*", "loop+TTT compact body"),
    (r"\bLucky\w*", "neural body variant"),
    (r"\bLongworm\w*", "long-context causal tap mechanism"),
    (r"\bGametriome\w*", "long-context bridge body"),
    (r"\bMoonshot\w*", "RWKV-style recurrence body"),
    (r"\bTON[\s_-]?E\w*", "rhythm recurrence"),
    (r"\bton_e\w*", "rhythm recurrence"),
    (r"\bPurple[\s_-]?\d+\w*", "phrase-cache variant"),
    (r"\bBW\d+\w*", "crawler variant"),
    (r"\bTrapper[\s_-]+Keeper\w*", "multi-crawler descendant"),
    (r"\bSmokestack\w*", "crawler test body"),
    (r"\bTornado\w*", "EMA teacher/student integration"),
    (r"\bCobra\w*", "controlled A/B quality harness"),
    (r"\bGreenRod\w*", "hybrid GatedDeltaNet-attention body"),
    (r"\bMegahelix\w*", "fused recurrence megakernel"),
    (r"\bVortexHelix\w*", "fused recurrence megakernel"),
    (r"\bHelix\w*", "split-head crawler scale gate"),
    (r"\bShroud\w*", "trace and flow-capture wrapper"),
]


def sanitize_public_text(text: object) -> str:
    """Replace internal nicknames in visible report text with technical labels."""
    value = str(text or "")
    for pattern, replacement in PUBLIC_TEXT_REPLACEMENTS:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
        if pattern.startswith(r"\b"):
            slug_pattern = r"(?<![A-Za-z])" + pattern[2:]
            value = re.sub(slug_pattern, replacement, value, flags=re.IGNORECASE)
    return value


def _arch_family_matches(pattern: str, *values: str | None) -> bool:
    for value in values:
        if not value:
            continue
        if re.search(pattern, value, re.IGNORECASE):
            return True
        normalized = re.sub(r"[^A-Za-z0-9]+", " ", value)
        if re.search(pattern, normalized, re.IGNORECASE):
            return True
    return False


def detect_arch_families(test_rows: list[dict]) -> list[tuple[str, int]]:
    """For each test row, find the FIRST matching family from ARCH_FAMILIES.
    Searches title FIRST, then falls back to abs_path so generic-named log
    files (run_s1337.log, train_seed444.log) still get classified by the
    architecture-named directory they live in. Unmatched → 'Other'."""
    counts: dict[str, int] = {}
    unmatched = 0
    for row in test_rows:
        title = (row.get("title") or "")
        path = (row.get("abs_path") or "")
        matched = False
        for fam_name, pat in ARCH_FAMILIES:
            if _arch_family_matches(pat, title):
                counts[fam_name] = counts.get(fam_name, 0) + 1
                matched = True
                break
        if not matched:
            # Fallback: check the full path for the family name. Catches
            # generic-named logs (run_s1337.log) that live in dirs like
            # `.../sota_v2_tttonly_*/` or `.../nightcrawler_cubed/`.
            for fam_name, pat in ARCH_FAMILIES:
                if _arch_family_matches(pat, path):
                    counts[fam_name] = counts.get(fam_name, 0) + 1
                    matched = True
                    break
        if not matched:
            unmatched += 1
    if unmatched > 0:
        counts["Other"] = unmatched
    return sorted(counts.items(), key=lambda kv: -kv[1])


def format_arch_families(families: list[tuple[str, int]], cap: int = 6) -> str:
    if not families:
        return "—"
    parts = [f"{public_arch_label(name).upper()} (×{n})" for name, n in families[:cap]]
    if len(families) > cap:
        more = sum(n for _, n in families[cap:])
        parts.append(f"+{len(families) - cap} MORE (×{more})")
    return "  ·  ".join(parts)


_FROSTED_FLAKE_PATH = "/home/frosty40/research_collator/assets/frosted_flake.png"


def preview_asset_src(path: str | Path, home_href: str = "", asset_name: str | None = None) -> str:
    """Copy a source asset into preview/assets and return the page-relative URL."""
    src = Path(path)
    dst = HTML_DIR / "assets" / (asset_name or src.name)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if (
            not dst.exists()
            or src.stat().st_mtime_ns != dst.stat().st_mtime_ns
            or src.stat().st_size != dst.stat().st_size
        ):
            shutil.copy2(src, dst)
    except OSError:
        return ""
    prefix = "../" if home_href.startswith("../") else ""
    return f"{prefix}assets/{dst.name}"


def preview_chart_src(path: str | Path, home_href: str = "") -> str:
    """Copy a generated chart into preview/assets with a collision-safe name."""
    src = Path(path)
    try:
        rel = src.resolve().relative_to(OUT_ROOT.resolve())
        name_basis = str(rel)
    except ValueError:
        name_basis = src.name
    asset_name = "chart_" + re.sub(r"[^A-Za-z0-9._-]+", "_", name_basis)
    return preview_asset_src(src, home_href, asset_name)


def _frosted_flake_src(home_href: str) -> str:
    """Use one shared static mark instead of base64-inlining it per page."""
    return preview_asset_src(_FROSTED_FLAKE_PATH, home_href)


def make_report_h1_html(
    title: str,
    right_label: str,
    home_href: str = "index.html",
    master_href: str | None = None,
    master_label: str = "BACK TO MASTER SHEET",
) -> str:
    """Report title with the frostmark wired back to the publication landing page."""
    if master_href:
        right_html = (
            '<span class="h1-right">'
            f'<a class="h1-master" href="{html.escape(master_href, quote=True)}">'
            f'{html.escape(master_label)}</a>'
            f'<span class="h1-date">{html.escape(right_label)}</span>'
            '</span>'
        )
    else:
        right_html = f'<span class="h1-date">{html.escape(right_label)}</span>'
    return (
        '<h1>'
        '<span class="h1-title">'
        f'<a class="h1-home" href="{html.escape(home_href, quote=True)}" aria-label="Open landing page">'
        '<img class="h1-mark" src="' + html.escape(_frosted_flake_src(home_href), quote=True) + '" alt="">'
        '</a>'
        f'<span>{html.escape(title)}</span>'
        '</span>'
        f'{right_html}'
        '</h1>'
    )


_BASELINE_STYLE: str | None = None
_ARTIFACT_DAY_INDEX: dict[str, int] | None = None


def _embedded_log_style() -> str:
    return """
    /* Section 2 details: compact toggle in OPEN, full-width panel below. */
    .test-runs-table td.open-cell { min-width: 150px; }
    .log-toggle { margin: 0; }
    .log-toggle + .log-toggle { margin-top: 6px; }
    .log-toggle summary {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        min-height: 24px;
        padding: 4px 8px;
        border: 1px solid var(--rule-hi);
        background: var(--rule-hi);
        color: var(--bg);
        cursor: pointer;
        font-size: 10.5px;
        font-weight: 700;
        line-height: 1;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        white-space: nowrap;
        list-style: none;
        user-select: none;
    }
    .log-toggle summary::-webkit-details-marker { display: none; }
    .log-toggle summary::marker { content: ""; }
    .log-toggle summary::before {
        content: "";
        width: 8px;
        height: 8px;
        flex: 0 0 auto;
        background: var(--bg);
    }
    .log-toggle[open] summary::before {
        background: transparent;
        outline: 1px solid var(--bg);
        outline-offset: -1px;
    }
    .log-toggle summary:hover,
    .log-toggle summary:focus-visible {
        border-bottom-color: var(--rule-hi);
        outline: 1px solid var(--rule-hi);
        outline-offset: 2px;
    }
    .log-detail-row { display: none; }
    .test-runs-table tr:has(details.log-toggle[open]) + tr.log-detail-row,
    .log-detail-row.is-open { display: table-row; }
    .log-detail-row td {
        padding: 12px 14px 16px;
        border-top: none;
        color: var(--bg);
        background: var(--rule-hi);
    }
    .log-panel {
        position: relative;
        border: 1px solid var(--bg);
        padding: 12px 14px;
        background: var(--rule-hi);
    }
    .log-panel + .log-panel { margin-top: 14px; }
    .log-meta {
        color: var(--bg);
        font-size: 10.5px;
        line-height: 1.4;
        margin: 0 0 7px;
        overflow-wrap: anywhere;
    }
    .log-text {
        max-height: 520px;
        overflow: auto;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        padding: 0;
        margin: 0;
        font-family: var(--mono);
        font-size: 11px;
        line-height: 1.45;
        color: var(--bg);
        background: transparent;
    }
    .log-panel strong,
    .log-panel code {
        color: var(--bg);
    }
    .log-panel a {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        min-height: 24px;
        padding: 4px 8px;
        border: 1px solid var(--bg);
        background: var(--bg);
        color: var(--rule-hi);
        cursor: pointer;
        font-size: 10.5px;
        font-weight: 700;
        line-height: 1;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        text-decoration: none;
        white-space: nowrap;
        user-select: none;
        border-radius: 0;
        vertical-align: middle;
    }
    .log-panel a::before {
        content: "";
        width: 8px;
        height: 8px;
        flex: 0 0 auto;
        background: var(--rule-hi);
    }
    .log-panel a:hover,
    .log-panel a:focus-visible {
        border-bottom-color: var(--bg);
        outline: 1px solid var(--bg);
        outline-offset: 2px;
    }
    .open-extra {
        margin-top: 6px;
        color: var(--ink-mute);
        font-size: 11px;
    }
    .bpb-download-action {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 24px;
        padding: 4px 8px;
        border: 1px solid var(--rule-hi);
        border-radius: 0;
        background: var(--rule-hi);
        color: var(--bg) !important;
        font-size: 10px;
        font-weight: 900;
        letter-spacing: 0;
        line-height: 1;
        text-transform: uppercase;
        text-decoration: none !important;
        white-space: nowrap;
    }
    .bpb-download-action::before {
        content: "+";
        display: inline-block;
        margin-right: 6px;
        color: var(--bg);
        font-weight: 900;
    }
    .bpb-download-action:hover,
    .bpb-download-action:focus-visible {
        background: var(--bg);
        color: var(--rule-hi) !important;
        outline: 1px solid var(--rule-hi);
        outline-offset: 1px;
    }
    .bpb-download-action:hover::before,
    .bpb-download-action:focus-visible::before {
        color: var(--rule-hi);
    }
    .bpb-download-missing {
        color: var(--muted);
        font-size: 10px;
    }
    .lazy-test-card {
        border: 1px solid var(--rule-hi);
        padding: 12px 14px;
        margin: 12px 0 18px;
        background: transparent;
    }
    .lazy-test-card p {
        margin: 0 0 10px;
        color: var(--ink);
    }
    .lazy-test-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 0 0 10px;
        color: var(--ink-mute);
        font-size: 10.5px;
        text-transform: uppercase;
    }
    .lazy-test-load {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 28px;
        padding: 5px 10px;
        border: 1px solid var(--rule-hi);
        border-radius: 0;
        background: var(--rule-hi);
        color: var(--bg);
        cursor: pointer;
        font-family: var(--mono);
        font-size: 10.5px;
        font-weight: 900;
        line-height: 1;
        letter-spacing: 0;
        text-transform: uppercase;
    }
    .lazy-test-load::before {
        content: "+";
        display: inline-block;
        margin-right: 7px;
        color: var(--bg);
        font-weight: 900;
    }
    .lazy-test-load:hover,
    .lazy-test-load:focus-visible {
        background: var(--bg);
        color: var(--rule-hi);
        outline: 1px solid var(--rule-hi);
        outline-offset: 1px;
    }
    .lazy-test-load:hover::before,
    .lazy-test-load:focus-visible::before {
        color: var(--rule-hi);
    }
    .lazy-test-target {
        margin-top: 12px;
    }
    /* Per-day audit chip + expanded panel. Lives between the report H1 and
       the report-header block. Color comes from the day's audit state. */
    .audit-badge {
        margin: 0 0 14px;
        display: block;
    }
    .audit-badge[open] .audit-chip::after { content: " ▾"; }
    .audit-badge:not([open]) .audit-chip::after { content: " ▸"; }
    .audit-chip {
        display: inline-flex;
        align-items: center;
        padding: 5px 9px;
        border: 1px solid var(--rule-hi);
        font-family: var(--mono);
        font-size: 10.5px;
        font-weight: 800;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        cursor: pointer;
        list-style: none;
    }
    .audit-chip::-webkit-details-marker { display: none; }
    .audit-chip.audit-clean   { background: var(--bg);      color: var(--ink-hi);   border-color: var(--rule-hi); }
    .audit-chip.audit-warn    { background: var(--rule-hi); color: var(--bg); }
    .audit-chip.audit-fatal   { background: var(--warn);    color: var(--bg);       border-color: var(--warn); }
    .audit-chip.audit-pending { background: var(--bg);      color: var(--muted);    border-style: dashed; }
    .audit-body {
        margin-top: 8px;
        padding: 10px 12px;
        border: 1px solid var(--rule-hi);
        background: var(--bg);
        font-size: 11px;
    }
    .audit-section-label {
        font-size: 9.5px;
        font-weight: 800;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--ink-mute);
        margin: 0 0 4px;
    }
    .audit-section-label + * { margin-bottom: 10px; }
    .audit-findings, .audit-json {
        margin: 0 0 6px;
        white-space: pre-wrap;
        font-family: var(--mono);
        font-size: 10.5px;
        line-height: 1.4;
        color: var(--ink);
        max-height: 320px;
        overflow: auto;
    }
    /* Per-day decision trail panel: lazy-loaded slice of the conversation
       architecture timeline that covers this date. */
    .decision-trail-panel { margin: 0 0 14px; }
    .decision-trail-teaser {
        font-size: 10.5px;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--ink-mute);
        margin-bottom: 6px;
    }
    .decision-trail-doc {
        max-height: 480px;
        overflow: auto;
        padding: 12px 14px;
        border: 1px solid var(--rule-hi);
        background: var(--bg);
        font-family: var(--mono);
        font-size: 11px;
        line-height: 1.5;
    }
    .decision-trail-doc h2 { font-size: 13px; font-weight: 800; margin: 14px 0 6px; text-transform: none; letter-spacing: 0; }
    .decision-trail-doc h3 { font-size: 12px; font-weight: 700; margin: 12px 0 5px; text-transform: none; letter-spacing: 0; }
    .decision-trail-doc h4 { font-size: 11.5px; font-weight: 700; color: var(--ink-mute); margin: 10px 0 4px; text-transform: none; letter-spacing: 0; }
    .decision-trail-doc h5 { font-size: 11px; font-weight: 700; color: var(--ink-mute); margin: 8px 0 4px; text-transform: none; letter-spacing: 0; }
    .decision-trail-doc ul { margin: 6px 0 10px 18px; padding: 0; }
    .decision-trail-doc li { margin: 3px 0; }
    .decision-trail-doc code { background: transparent; padding: 0; font-weight: 600; }
    /* Ablation rationale: row evidence's ablation label is wrapped in a
       lazy-load button when the day's labeling pass produced a review.md.
       Styled inline so it reads as a clickable label, not a chunky button. */
    .lazy-ablation-label {
        background: transparent;
        color: inherit;
        border: 0;
        border-bottom: 1px dashed var(--rule-hi);
        padding: 0;
        margin: 0;
        font: inherit;
        text-transform: none;
        letter-spacing: 0;
        cursor: pointer;
        text-align: left;
        line-height: inherit;
        min-height: 0;
    }
    .lazy-ablation-label::before { content: ""; margin: 0; }
    .lazy-ablation-label:hover, .lazy-ablation-label:focus-visible {
        background: transparent;
        color: var(--ink-hi);
        border-bottom-color: var(--ink-hi);
    }
    .ablation-review-doc {
        max-height: 480px;
        overflow: auto;
        padding: 12px 14px;
        margin-top: 8px;
        border: 1px solid var(--rule-hi);
        background: var(--bg);
        font-family: var(--mono);
        font-size: 11px;
        line-height: 1.5;
    }
    .ablation-review-doc h2 { font-size: 13px; font-weight: 800; margin: 14px 0 6px; text-transform: none; letter-spacing: 0; }
    .ablation-review-doc h3 { font-size: 12px; font-weight: 700; margin: 12px 0 5px; text-transform: none; letter-spacing: 0; }
    .ablation-review-doc table.md-table {
        border-collapse: collapse;
        width: 100%;
        margin: 8px 0;
        font-size: 10.5px;
    }
    .ablation-review-doc table.md-table th,
    .ablation-review-doc table.md-table td {
        padding: 4px 6px;
        border: 1px solid var(--rule-hi);
        text-align: left;
        vertical-align: top;
    }
    .ablation-review-doc pre.codeblock {
        background: var(--bg);
        border: 1px solid var(--rule-hi);
        padding: 8px 10px;
        font-size: 10.5px;
        white-space: pre;
        overflow: auto;
    }
    /* Per-day commits disclosure: short_hash · time · repo · subject. */
    .commits-panel { margin: 0 0 14px; }
    .commits-summary {
        display: inline-flex;
        align-items: center;
        padding: 5px 9px;
        border: 1px solid var(--rule-hi);
        font-family: var(--mono);
        font-size: 10.5px;
        font-weight: 800;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        cursor: pointer;
        list-style: none;
        background: var(--bg);
        color: var(--ink-hi);
    }
    .commits-summary::-webkit-details-marker { display: none; }
    .commits-panel[open] .commits-summary::after { content: " ▾"; }
    .commits-panel:not([open]) .commits-summary::after { content: " ▸"; }
    .commits-list {
        margin: 8px 0 0;
        padding: 10px 14px;
        border: 1px solid var(--rule-hi);
        background: var(--bg);
        list-style-type: decimal;
        list-style-position: outside;
        max-height: 360px;
        overflow: auto;
    }
    .commits-list .commit-item {
        margin: 0 0 4px 22px;
        padding: 0;
        font-family: var(--mono);
        font-size: 10.5px;
        line-height: 1.4;
    }
    .commits-list .commit-hash { color: var(--ink-mute); font-weight: 700; }
    .commits-list .commit-time { color: var(--ink-mute); }
    .commits-list .commit-repo {
        color: var(--ink-mute);
        font-size: 10px;
        padding: 1px 4px;
        border: 1px solid var(--rule-hi);
        margin-right: 4px;
    }
    .commits-list .commit-subject { color: var(--ink); }
    """


def _embedded_log_script() -> str:
    return (
        "<script>(function(){"
        "function sync(d){"
        "var tr=d.closest('tr');"
        "var row=tr&&tr.nextElementSibling;"
        "if(!row||!row.classList.contains('log-detail-row'))return;"
        "var open=Array.prototype.some.call("
        "tr.querySelectorAll('details.log-toggle'),function(x){return x.open;});"
        "row.classList.toggle('is-open',open);"
        "}"
        "function bind(root){"
        "(root||document).querySelectorAll('details.log-toggle').forEach(function(d){"
        "if(d.dataset.bound)return;"
        "d.dataset.bound='1';"
        "d.addEventListener('toggle',function(){sync(d);});"
        "sync(d);"
        "});"
        "(root||document).querySelectorAll('[data-lazy-fragment]').forEach(function(btn){"
        "if(btn.dataset.lazyBound)return;"
        "btn.dataset.lazyBound='1';"
        "btn.addEventListener('click',function(){"
        "var target=document.getElementById(btn.getAttribute('data-target'));"
        "var url=btn.getAttribute('data-lazy-fragment');"
        "if(!target||!url)return;"
        "var loadLabel=btn.getAttribute('data-load-label')||'load';"
        "var hideLabel=btn.getAttribute('data-hide-label')||'hide';"
        "var loadingLabel=btn.getAttribute('data-loading-label')||'loading';"
        "var errorLabel=btn.getAttribute('data-error-label')||'load failed';"
        "if(btn.dataset.loaded==='1'){"
        "target.hidden=!target.hidden;"
        "btn.textContent=target.hidden?loadLabel:hideLabel;"
        "return;"
        "}"
        "btn.disabled=true;"
        "btn.textContent=loadingLabel;"
        "fetch(url).then(function(r){if(!r.ok)throw new Error(r.status);return r.text();})"
        ".then(function(html){"
        "target.innerHTML=html;"
        "target.hidden=false;"
        "btn.dataset.loaded='1';"
        "btn.disabled=false;"
        "btn.textContent=hideLabel;"
        "bind(target);"
        "})"
        ".catch(function(err){"
        "btn.disabled=false;"
        "btn.textContent=errorLabel;"
        "target.hidden=false;"
        "target.innerHTML='<p class=\"muted\">Unable to load fragment: '+err.message+'</p>';"
        "});"
        "});"
        "});"
        "}"
        "bind(document);"
        "})();</script>"
    )


def _daily_template_style() -> str:
    """Load CSS from the locked daily report standard.

    The renderer is allowed to be smart about data. It is not allowed to carry
    a second visual design that drifts from the user's daily template. The
    source file and its CSS hash are the repo-level lock for the base visual
    system; any intentional visual change must update TEMPLATE.md and this
    hash in the same patch.
    """
    global _BASELINE_STYLE
    if _BASELINE_STYLE is not None:
        return _BASELINE_STYLE
    try:
        raw = LOCKED_TEMPLATE_HTML.read_text(encoding="utf-8")
    except OSError as e:
        raise TemplateContractError(
            f"missing locked daily template CSS source: {LOCKED_TEMPLATE_HTML}"
        ) from e
    m = re.search(r"<style>(.*?)</style>", raw, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        raise TemplateContractError(
            f"locked daily template has no <style> block: {LOCKED_TEMPLATE_HTML}"
        )
    style = m.group(1).strip()
    style_sha = hashlib.sha256(style.encode("utf-8")).hexdigest()
    if style_sha != LOCKED_TEMPLATE_STYLE_SHA256:
        raise TemplateContractError(
            "locked daily template CSS hash drifted: "
            f"expected {LOCKED_TEMPLATE_STYLE_SHA256}, got {style_sha}; "
            "update TEMPLATE.md and LOCKED_TEMPLATE_STYLE_SHA256 if this was intentional"
        )
    required = [
        ".alloc-bar { display: inline-flex; height: 30px; width: 240px;",
        ".rh-row-alloc { align-items: center; padding: 14px 0; }",
        ".alloc-seg-kernel",
        ".supporting-section",
        ".bpb-table",
        ".h1-home",
        ".h1-master",
        ".architecture-recipe",
        "scrollbar-color: var(--rule-hi) var(--bg);",
        "::-webkit-scrollbar-thumb",
    ]
    missing = [needle for needle in required if needle not in style]
    if missing:
        raise TemplateContractError(
            f"locked daily template CSS missing required rules: {missing}"
        )
    _BASELINE_STYLE = style + "\n" + _embedded_log_style().strip()
    return _BASELINE_STYLE


def artifact_day_index(conn: sqlite3.Connection) -> dict[str, int]:
    """1-based index in the sorted set of research dates with artifacts.

    Prelude/bootstrap artifacts before RESEARCH_START_DATE and post-final
    submission artifacts after RESEARCH_END_DATE can still be rendered by
    explicit date, but they are not counted as research days.
    """
    global _ARTIFACT_DAY_INDEX
    if _ARTIFACT_DAY_INDEX is None:
        rows = conn.execute(
            "SELECT abs_path, rel_path, source_label, file_kind, mtime_iso, metrics_json FROM artifacts"
        ).fetchall()
        dates = sorted({
            bd
            for r in rows
            if is_research_chronology_record(dict(r))
            for bd in [best_date(dict(r))]
            if bd is not None
        })
        dates = [d for d in dates if is_research_campaign_date(d)]
        _ARTIFACT_DAY_INDEX = {d: i for i, d in enumerate(dates, start=1)}
    return _ARTIFACT_DAY_INDEX


def compute_day_index(conn: sqlite3.Connection, date: str) -> int | None:
    return artifact_day_index(conn).get(date)


def date_for_day_index(conn: sqlite3.Connection, day_index: int) -> str | None:
    for date, idx in artifact_day_index(conn).items():
        if idx == day_index:
            return date
    return None


def make_report_header_html(fields: list[tuple[str, str]],
                            alloc_bar: str | None = None) -> str:
    """Flat bordered block of key/value rows. If `alloc_bar` is given, the
    LAST field's value is replaced with an inline allocation bar (the
    CLASSIFICATION row). Dot-leader spans are emitted but display:none in CSS."""
    rows: list[str] = []
    for i, (k, v) in enumerate(fields):
        is_last_alloc = (alloc_bar is not None and i == len(fields) - 1)
        if is_last_alloc:
            rows.append(
                f'<div class="rh-row rh-row-alloc">'
                f'<span class="rh-key">{html.escape(k.upper())}</span>'
                f'<span class="rh-dots"></span>'
                f'<span class="rh-val rh-alloc">{alloc_bar}</span></div>'
            )
        else:
            rows.append(
                f'<div class="rh-row">'
                f'<span class="rh-key">{html.escape(k.upper())}</span>'
                f'<span class="rh-dots"></span>'
                f'<span class="rh-val">{html.escape(v)}</span></div>'
            )
    return '<div class="report-header">' + "".join(rows) + "</div>"


TEMPLATE_HEADER_KEYS = [
    "DATE",
    "DAY",
    "PRIMARY METRIC",
    "TESTS RUN",
    "ARCHITECTURE FAMILY",
    "CLASSIFICATION",
]

TEMPLATE_SECTION_LINES = [
    "## SECTION 1.0 — TRAJECTORY",
    "## SECTION 2.0 — TEST RUNS",
]


class TemplateContractError(RuntimeError):
    """Raised when render_day would emit a page outside TEMPLATE.md."""


def load_architecture_recipes() -> dict[str, dict]:
    """Load deterministic copy recipes for detected architecture families."""
    global ARCHITECTURE_RECIPE_CACHE
    if ARCHITECTURE_RECIPE_CACHE is not None:
        return ARCHITECTURE_RECIPE_CACHE
    try:
        raw = json.loads(ARCHITECTURE_RECIPES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        ARCHITECTURE_RECIPE_CACHE = {}
        return ARCHITECTURE_RECIPE_CACHE
    except json.JSONDecodeError as e:
        raise TemplateContractError(f"invalid architecture recipe JSON: {e}") from e

    if not isinstance(raw, dict):
        raise TemplateContractError("architecture recipes must be a JSON object")
    recipes = raw.get("recipes", raw)
    if not isinstance(recipes, dict):
        raise TemplateContractError("architecture recipes must be a JSON object")
    for family, recipe in recipes.items():
        if not isinstance(recipe, dict):
            raise TemplateContractError(
                f"architecture recipe for {family!r} must be an object"
            )
        sections = recipe.get("sections")
        if not isinstance(sections, list):
            raise TemplateContractError(
                f"architecture recipe for {family!r} missing sections list"
            )
        visible_chunks = [
            str(recipe.get("display") or ""),
            str(recipe.get("summary") or ""),
        ]
        for section in sections:
            if not isinstance(section, dict):
                raise TemplateContractError(
                    f"architecture recipe section for {family!r} must be an object"
                )
            visible_chunks.append(str(section.get("label") or ""))
            items = section.get("items")
            if not isinstance(items, list):
                raise TemplateContractError(
                    f"architecture recipe section for {family!r} missing items list"
                )
            visible_chunks.extend(str(item) for item in items)
        visible_text = " ".join(visible_chunks).upper()
        for forbidden in ("PROVENANCE", "LINEAGE", "SOURCE", "PARENT", "SHA256"):
            if forbidden in visible_text:
                raise TemplateContractError(
                    f"architecture recipe for {family!r} contains forbidden term: {forbidden}"
                )
    ARCHITECTURE_RECIPE_CACHE = recipes
    return ARCHITECTURE_RECIPE_CACHE


def make_architecture_recipe_html(families: list[tuple[str, int]]) -> tuple[str, list[str]]:
    """Render copyable architecture recipes for active, known families only."""
    recipes = load_architecture_recipes()
    cards: list[str] = []
    rendered: list[str] = []
    for name, count in families:
        if name == "Other":
            continue
        recipe = recipes.get(name)
        if not recipe:
            continue
        display = str(recipe.get("display") or public_arch_label(name)).upper()
        summary = str(recipe.get("summary") or "")
        lines: list[str] = []
        for section in recipe.get("sections") or []:
            if not isinstance(section, dict):
                continue
            label = str(section.get("label") or "").strip()
            items = section.get("items") or []
            if not label or not isinstance(items, list):
                continue
            value = " · ".join(
                html.escape(str(item))
                for item in items
                if str(item).strip()
            )
            if not value:
                continue
            lines.append(
                '<div class="ar-line">'
                f'<span class="ar-key">{html.escape(label.upper())}</span>'
                f'<span class="ar-val">{value}</span>'
                "</div>"
            )
        if not lines:
            continue
        rendered.append(name)
        cards.append(
            '<article class="ar-card">'
            '<div class="ar-head">'
            f'<span class="ar-name">{html.escape(display)}</span>'
            f'<span class="ar-count">x{int(count)}</span>'
            "</div>"
            f'<p class="ar-summary">{html.escape(summary)}</p>'
            + "".join(lines) +
            "</article>"
        )
    if not cards:
        return "", []
    return (
        '<section class="architecture-recipe" aria-label="Architecture recipe">'
        '<div class="ar-kicker">ARCHITECTURE RECIPE</div>'
        '<div class="ar-cards">'
        + "".join(cards) +
        "</div></section>",
        rendered,
    )


def all_campaign_dates(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT abs_path, rel_path, source_label, file_kind, mtime_iso, metrics_json FROM artifacts"
    ).fetchall()
    dates: set[str] = set()
    for row in rows:
        rec = dict(row)
        if not is_research_chronology_record(rec):
            continue
        date = best_date(rec)
        if is_research_campaign_date(date):
            dates.add(date)
    return sorted(dates)


def week_dates_for_date(conn: sqlite3.Connection, date: str) -> list[str]:
    dates = all_campaign_dates(conn)
    for idx in range(0, len(dates), 7):
        window = dates[idx:idx + 7]
        if date in window:
            return window
    return [date]


def _recipe_reference_specs(recipe: dict, max_specs: int = 7) -> list[str]:
    """Short, copyable deterministic specs for the black summary callout."""
    priority = (
        "num_layers", "model_dim", "embedding_dim", "vocab_size",
        "num_heads", "num_kv_heads", "head_dim", "mlp_mult",
        "matrix_bits", "num_loops", "loop_start", "loop_end",
        "rope_dims", "eval_seq_len", "train_seq_len",
    )
    sections = recipe.get("sections") or []
    items: list[str] = []
    freeform: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        label = str(section.get("label") or "").lower()
        section_items = section.get("items") or []
        if not isinstance(section_items, list):
            continue
        for item in section_items:
            text = str(item).strip()
            if not text:
                continue
            low = text.lower()
            if any(low.startswith(key.lower() + "=") for key in priority):
                items.append(text)
            elif any(token in label for token in ("token", "quant", "eval", "loop", "feature", "kernel")):
                freeform.append(text)
    ordered: list[str] = []
    for key in priority:
        for item in items:
            if item.lower().startswith(key.lower() + "=") and item not in ordered:
                ordered.append(item)
                break
    for item in freeform:
        if item not in ordered:
            ordered.append(item)
    return ordered[:max_specs]


def architecture_reference_fragments(families: list[tuple[str, int]],
                                     max_families: int = 3,
                                     max_specs: int = 6) -> list[str]:
    """Plain-text architecture references derived only from deterministic data."""
    recipes = load_architecture_recipes()
    fragments: list[str] = []
    for name, count in families:
        if name == "Other" or len(fragments) >= max_families:
            continue
        recipe = recipes.get(name)
        display = str((recipe or {}).get("display") or public_arch_label(name)).upper()
        if recipe:
            specs = _recipe_reference_specs(recipe, max_specs=max_specs)
            spec_text = "; ".join(specs)
            summary = str(recipe.get("summary") or "").strip()
            body = summary
            if spec_text:
                body = f"{body} Specs: {spec_text}." if body else f"Specs: {spec_text}."
        else:
            body = (
                "architecture family detected in measured rows; exact flags "
                "are preserved in the row details."
            )
        fragments.append(f"{display} (x{int(count)}): {body}")
    return fragments


def architecture_technique_terms(families: list[tuple[str, int]],
                                 max_terms: int = 10) -> list[str]:
    """Technique vocabulary for summaries, sourced from recipe section items."""
    recipes = load_architecture_recipes()
    terms: list[str] = []
    for name, _count in families:
        recipe = recipes.get(name)
        if not recipe:
            continue
        for section in recipe.get("sections") or []:
            if not isinstance(section, dict):
                continue
            label = str(section.get("label") or "").lower()
            if not any(token in label for token in (
                "token", "position", "loop", "quant", "eval",
                "feature", "kernel", "crawler", "packaging",
            )):
                continue
            items = section.get("items") or []
            if not isinstance(items, list):
                continue
            for item in items:
                text = str(item).strip()
                if not text or "=" in text:
                    continue
                if text not in terms:
                    terms.append(text)
                if len(terms) >= max_terms:
                    return terms
    return terms


def assert_daily_template_contract(date: str,
                                   records: list[dict],
                                   header_fields: list[tuple[str, str]],
                                   qmd_lines: list[str],
                                   test_table_md: str,
                                   metric: str,
                                   n_tests: int) -> None:
    """Small render-time guardrail for the locked daily template.

    This keeps TEMPLATE.md executable without changing the user's visual
    design: if section order, header rows, table columns, or day-local
    attribution drift, rendering fails loudly.
    """
    header_keys = [k for k, _v in header_fields]
    if header_keys != TEMPLATE_HEADER_KEYS:
        raise TemplateContractError(
            f"header rows drifted: expected {TEMPLATE_HEADER_KEYS}, got {header_keys}"
        )

    qmd_text = "\n".join(qmd_lines)
    positions: list[int] = []
    for section in TEMPLATE_SECTION_LINES:
        pos = qmd_text.find(section)
        if pos < 0:
            raise TemplateContractError(f"missing template section: {section}")
        positions.append(pos)
    if positions != sorted(positions):
        raise TemplateContractError("daily sections are out of canonical order")
    recipe_pos = qmd_text.find('class="architecture-recipe"')
    if recipe_pos >= 0 and recipe_pos > positions[0]:
        raise TemplateContractError("architecture recipe must render before Section 1.0")
    if recipe_pos >= 0:
        recipe_match = re.search(
            r'<section class="architecture-recipe".*?</section>',
            qmd_text,
            flags=re.DOTALL,
        )
        recipe_text = (recipe_match.group(0) if recipe_match else "").upper()
        for forbidden in ("PROVENANCE", "LINEAGE", "SOURCE", "PARENT", "SHA256"):
            if forbidden in recipe_text:
                raise TemplateContractError(
                    f"architecture recipe leaked provenance term: {forbidden}"
                )
    if "DAILY GRIND" in qmd_text.upper():
        raise TemplateContractError("DAILY GRIND section is not in the canonical layout")
    if "SECTION 3.0" in qmd_text.upper() or "SUPPORTING FILES" in qmd_text.upper():
        raise TemplateContractError("supporting-files section is not in the canonical layout")
    bad_dates = [
        (r.get("abs_path") or "", best_date(r))
        for r in records
        if best_date(r) != date
    ]
    if bad_dates:
        sample = bad_dates[:3]
        raise TemplateContractError(
            f"daily report day-local contract failed for {date}: {sample}"
        )

    metric_header = metric_display_name(metric)
    expected_header = (
        f"| # | TIME | HW | ABLATION | {metric_header} | STATUS | Δ % | OPEN |"
    )
    expected_html_header = (
        "<thead><tr>"
        + "".join(
            f"<th>{html.escape(c)}</th>"
            for c in ["#", "TIME", "HW", "ABLATION", metric_header, "STATUS", "Δ %", "OPEN"]
        )
        + "</tr></thead>"
    )
    table_headers = [
        line for line in test_table_md.splitlines()
        if line.startswith("| # | TIME | HW | ABLATION |")
    ]
    if table_headers:
        bad_headers = [line for line in table_headers if line != expected_header]
        if bad_headers:
            raise TemplateContractError(
                f"test table header drifted: expected {expected_header!r}, got {bad_headers[0]!r}"
            )
    elif (
        n_tests
        and expected_html_header not in test_table_md
        and "data-lazy-fragment" not in test_table_md
    ):
        raise TemplateContractError(
            f"test table header drifted: expected HTML header {expected_html_header!r}"
        )
    if "details class='log-toggle'" in test_table_md:
        if "tr class='log-detail-row'><td colspan='8'>" not in test_table_md:
            raise TemplateContractError(
                "training log disclosures must expand into full-width detail rows"
            )
        if "details class='log-embed'" in test_table_md:
            raise TemplateContractError(
                "training log disclosures cannot be embedded inside the narrow OPEN cell"
            )


def make_alloc_bar_html(by_camp: dict[str, int]) -> str:
    """Inline allocation bar for the CLASSIFICATION row.

    Keep this markup aligned with the locked baseline: 240x30 bar first, text
    second, both on the same header row.
    """
    order = _classification_display_order(by_camp)
    total = sum(by_camp.get(camp, 0) for camp in order)
    if total == 0:
        return ""

    segments: list[str] = []
    labels: list[str] = []
    text_parts: list[str] = []
    for camp in order:
        n = by_camp.get(camp, 0)
        pct = 100.0 * n / total
        label = CAMP_DISPLAY_LABEL.get(camp, camp).upper()
        seg_class = CLASSIFICATION_SEG_CLASS.get(camp, "alloc-seg-exp")
        text_class = CLASSIFICATION_TEXT_CLASS.get(camp, "alloc-text-exp")
        labels.append(f"{label} {pct:.0f}% ({n})")
        segments.append(
            f'<span class="{seg_class}" style="width:{pct:.2f}%"></span>'
        )
        text_parts.append(
            f'<span class="{text_class}">{label} {pct:.0f}% ({n})</span>'
        )

    return (
        f'<span class="alloc-bar" aria-label="{html.escape(" / ".join(labels))}">'
          + "".join(segments) +
        '</span>'
        '<span class="alloc-text">'
          + '<span class="alloc-sep">/</span>'.join(text_parts) +
        '</span>'
    )


def _classification_display_order(by_camp: dict[str, int]) -> tuple[str, ...]:
    active = [
        camp for camp in CLASSIFICATION_CAMP_ORDER
        if by_camp.get(camp, 0) > 0
    ]
    active.extend(
        camp for camp, n in sorted(by_camp.items())
        if n > 0 and camp not in CLASSIFICATION_CAMP_ORDER
    )
    return tuple(active)


def _classification_distribution_text(by_camp: dict[str, int]) -> str:
    order = _classification_display_order(by_camp)
    total = sum(by_camp.get(camp, 0) for camp in order)
    if total <= 0:
        return "unclassified"
    parts = []
    for camp in order:
        n = by_camp.get(camp, 0)
        pct = 100.0 * n / total
        parts.append(f"{pct:.0f}% {CAMP_DISPLAY_LABEL.get(camp, camp)}")
    return " / ".join(parts)


def _classification_tone(by_camp: dict[str, int]) -> str:
    order = _classification_display_order(by_camp)
    total = sum(by_camp.get(camp, 0) for camp in order)
    if total <= 0:
        return "unclassified"
    active = [
        (camp, 100.0 * by_camp.get(camp, 0) / total)
        for camp in order
        if by_camp.get(camp, 0)
    ]
    if not active:
        return "unclassified"
    top_camp, top_pct = max(active, key=lambda item: item[1])
    top_label = CAMP_DISPLAY_LABEL.get(top_camp, top_camp)
    if top_pct >= 80:
        return f"skewed hard {top_label}"
    if len(active) >= 2 and max(pct for _camp, pct in active) - min(pct for _camp, pct in active) < 15:
        return "balanced " + "/".join(CAMP_DISPLAY_LABEL.get(camp, camp) for camp, _pct in active)
    return f"{top_label}-leaning"


def make_daily_summary_html(date: str, day_index: int | None,
                            n_tests: int, valid_count: int,
                            invalid_count: int, headline_metric: str,
                            chart_baseline: float | None,
                            test_rows: list[dict],
                            arch_families: list[tuple[str, int]],
                            by_camp: dict[str, int]) -> str:
    """Two-paragraph callout that sits between SECTION 1.0 and the chart.
    Generated deterministically from the day's numbers — no LLM."""
    metric = metric_display_name(headline_metric)
    day_label = format_day_index(day_index)
    day_ref = f"Day {day_label}" if day_label != "—" else "Unindexed day"
    architecture_refs = architecture_reference_fragments(
        arch_families,
        max_families=3,
        max_specs=6,
    )
    technique_terms = architecture_technique_terms(arch_families, max_terms=8)
    if architecture_refs:
        architecture_text = " ".join(
            f"<span>{html.escape(fragment)}</span>"
            for fragment in architecture_refs
        )
    else:
        architecture_text = (
            "Measured rows did not match a named architecture recipe; exact "
            "architecture flags are preserved in the run table."
        )

    # Zero measured validation rows: report the absence of metrics and keep any
    # architecture note tied to deterministic family/recipe data.
    if n_tests == 0:
        if not architecture_refs:
            architecture_text = "No measured architecture/test rows were captured on this date."
        return (
            '<aside class="day-summary">'
              '<div class="ds-key">DAILY SUMMARY</div>'
              f'<div class="ds-body"><p><strong>Architecture tested:</strong> '
              f'{architecture_text}</p>'
              f'<p>{day_ref} — '
              f'<strong>no explicit validation metric</strong> was captured '
              'on this date.</p></div>'
            '</aside>'
        )

    if is_bpb_metric(headline_metric):
        if date == RESEARCH_END_DATE:
            validity_phrase = (
                f"with <strong>{valid_count} valid</strong> landings above the "
                f"{INVALID_VAL_BPB_FLOOR:.2f} BPB validity floor and "
                f"<strong>{invalid_count} eval/loader-error</strong> readings excluded"
            )
        else:
            validity_phrase = (
                f"with <strong>{valid_count} valid</strong> rows and "
                f"<strong>{invalid_count} eval/loader-error</strong> readings excluded"
            )
    elif is_kernel_metric(headline_metric):
        validity_phrase = (
            f"with <strong>{valid_count}</strong> custom-kernel-vs-FA3 timing rows"
        )
    else:
        validity_phrase = f"with <strong>{valid_count}</strong> measured rows"

    technique_text = ""
    if technique_terms:
        technique_text = (
            " Techniques to copy/reference: "
            f"<strong>{html.escape('; '.join(technique_terms))}</strong>."
        )

    if is_kernel_metric(headline_metric):
        para1 = (
            f"{day_ref} measured <strong>{n_tests} kernel benchmarks</strong> "
            f"against <strong>{html.escape(metric)}</strong>, {validity_phrase}."
            f"{technique_text}"
        )
    else:
        para1 = (
            f"{day_ref} measured <strong>{n_tests} architecture/test rows</strong> "
            f"against <strong>{html.escape(metric)}</strong>, {validity_phrase}."
            f"{technique_text}"
        )

    # Para 2: best-of-day, PB comparison
    valid_rows = [
        r for r in test_rows
        if is_valid_metric_value(headline_metric, r["value"])
    ]
    if valid_rows:
        best = min(valid_rows, key=lambda r: r["value"])
        best_value = best["value"]
        best_title = sanitize_public_text(best.get("title", "(unknown)"))
        best_phrase = "Best valid" if is_bpb_metric(headline_metric) else "Best"
        if chart_baseline is not None and best_value < chart_baseline:
            pb_line = (f"<strong>NEW PERSONAL BEST.</strong> {best_phrase} "
                       f"<strong>{format_metric_value(headline_metric, best_value)}</strong> "
                       "beats prior bar "
                       f"<strong>{format_metric_value(headline_metric, chart_baseline)}</strong>.")
        elif chart_baseline is not None:
            pb_line = (f"No new personal best. {best_phrase} of the day = "
                       f"<strong>{format_metric_value(headline_metric, best_value)}</strong> "
                       f"({html.escape(best_title[:60])}); "
                       "best-before-today = "
                       f"<strong>{format_metric_value(headline_metric, chart_baseline)}</strong> still stands.")
        else:
            pb_line = (f"{best_phrase} of the day = "
                       f"<strong>{format_metric_value(headline_metric, best_value)}</strong> "
                       f"({html.escape(best_title[:60])}). "
                       f"No prior baseline to compare against.")
    else:
        if is_bpb_metric(headline_metric):
            pb_line = "<strong>No valid runs.</strong> Every measurement was excluded as an eval/loader-error reading."
        else:
            pb_line = "<strong>No measured rows.</strong> No finite metric values were available."

    # Crash flag
    crash_count = sum(
        1 for r in test_rows
        if is_crash_value(headline_metric, r["value"])
    )
    if crash_count:
        crash_values = sorted(
            [r["value"] for r in test_rows if is_crash_value(headline_metric, r["value"])],
            reverse=True,
        )[:2]
        crash_str = ", ".join(f"{v:.2f}" for v in crash_values)
        pb_line += (f" {crash_count} crash-class outlier{'s' if crash_count > 1 else ''} "
                    f"({crash_str}) excluded.")

    return (
        '<aside class="day-summary">'
          '<div class="ds-key">DAILY SUMMARY</div>'
          f'<div class="ds-body"><p><strong>Architecture tested:</strong> '
          f'{architecture_text}</p><p>{para1}</p><p>{pb_line}</p></div>'
        '</aside>'
    )


def make_metric_spread_table_md(test_rows: list[dict], headline_metric: str,
                                arch_families: list[tuple[str, int]]) -> str:
    """Primary-metric spread per architecture family — n/min/median/max."""
    valid = [
        r for r in test_rows
        if is_valid_metric_value(headline_metric, r["value"])
    ]
    if not valid:
        return ""

    def family_of(row: dict) -> str:
        title = row.get("title") or ""
        path = row.get("abs_path") or ""
        for fam_name, pat in ARCH_FAMILIES:
            if _arch_family_matches(pat, title, path):
                return fam_name
        return "Other"

    by_fam: dict[str, list[float]] = {}
    for r in valid:
        fam = family_of(r)
        by_fam.setdefault(fam, []).append(r["value"])
    # Order rows by overall arch_families ranking (count descending)
    ordered_fams = [f for f, _ in arch_families if f in by_fam]
    for f in by_fam:
        if f not in ordered_fams:
            ordered_fams.append(f)

    metric = metric_display_name(headline_metric)
    rows = [f'<table class="bpb-table"><thead><tr>'
            f'<th>{metric} SPREAD</th><th>n</th><th>min</th>'
            f'<th>median</th><th>max</th><th>download</th></tr></thead><tbody>']
    for fam in ordered_fams:
        vals = sorted(by_fam[fam])
        n = len(vals)
        if n == 0:
            continue
        mn = vals[0]
        mx = vals[-1]
        if n % 2 == 1:
            med = vals[n // 2]
        else:
            med = (vals[n // 2 - 1] + vals[n // 2]) / 2.0
        rows.append(
            f'<tr><td>{html.escape(public_arch_label(fam).upper())}</td>'
            f'<td>{n}</td><td>{format_metric_value(headline_metric, mn)}</td>'
            f'<td>{format_metric_value(headline_metric, med)}</td>'
            f'<td>{format_metric_value(headline_metric, mx)}</td>'
            f'<td>{architecture_download_button_html(fam)}</td></tr>'
        )
    # All-valid row
    all_vals = sorted(v for vs in by_fam.values() for v in vs)
    n = len(all_vals)
    if n:
        med = all_vals[n // 2] if n % 2 == 1 else (all_vals[n // 2 - 1] + all_vals[n // 2]) / 2.0
        rows.append(
            f'<tr><td>ALL VALID</td>'
            f'<td>{n}</td><td>{format_metric_value(headline_metric, all_vals[0])}</td>'
            f'<td>{format_metric_value(headline_metric, med)}</td>'
            f'<td>{format_metric_value(headline_metric, all_vals[-1])}</td>'
            "<td><span class='bpb-download-missing'>—</span></td></tr>"
        )
    rows.append('</tbody></table>')
    return "\n".join(rows)


def make_camp_bar_html(by_camp: dict[str, int]) -> str:
    """Horizontal %-stacked bar showing rendered classifications for the day.
    Tiny inline HTML (no extra deps) that survives both Quarto rendering and
    the custom md_to_html passthrough."""
    order = _classification_display_order(by_camp)
    total = sum(by_camp.get(camp, 0) for camp in order)
    if total == 0:
        return ""
    segments = []
    labels = []
    for camp in order:
        n = by_camp.get(camp, 0)
        pct = 100.0 * n / total
        label = CAMP_DISPLAY_LABEL.get(camp, camp)
        seg_suffix = "kernel" if camp == KERNEL_CAMP else ("exp" if camp == "experimental" else "neu")
        segments.append(
            f'<div class="camp-seg camp-seg-{seg_suffix}" style="width: {pct:.2f}%" '
            f'title="{html.escape(label)}: {n} ({pct:.0f}%)"></div>'
        )
        labels.append(f"{label} · {n} ({pct:.0f}%)")
    return (
        '<div class="camp-bar">'
          + "".join(segments) +
        '</div>'
        '<div class="camp-bar-labels">'
          + '<span class="camp-label-sep">/</span>'.join(
              f'<span>{html.escape(label)}</span>' for label in labels
          ) +
        '</div>'
    )


def _format_bytes(n: object) -> str:
    try:
        value = int(n)
    except (TypeError, ValueError):
        return ""
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value / (1024 * 1024):.1f} MiB"


def _read_training_log_text(abs_path: str) -> str:
    if abs_path in TRAINING_LOG_EMBED_CACHE:
        return TRAINING_LOG_EMBED_CACHE[abs_path]
    try:
        text = Path(abs_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        text = f"[unable to read training log: {type(exc).__name__}: {exc}]"
    TRAINING_LOG_EMBED_CACHE[abs_path] = text
    return text


def _pre_text_one_line(text: str) -> str:
    """Escape text for a <pre> while keeping the generated HTML one-line.

    md_to_html passes raw HTML through line-by-line, so embedded logs must not
    introduce literal newlines into the table markup.
    """
    normalized = sanitize_public_text(text).replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "\uFFFD")
    return html.escape(normalized).replace("\n", "&#10;")


def _anchor_html(label: str, href: str) -> str:
    return (
        f"<a href='{html.escape(href, quote=True)}' target='_blank' "
        f"rel='noopener'>{html.escape(label)}</a>"
    )


def _training_log_summary_label(idx: int, total: int) -> str:
    return "training_log" if total == 1 else f"training_log {idx}"


def _detail_toggle_html(summary: str) -> str:
    return (
        "<details class='log-toggle'>"
        f"<summary>{html.escape(summary)}</summary>"
        "</details>"
    )


def _training_log_toggle_html(idx: int, total: int) -> str:
    return _detail_toggle_html(_training_log_summary_label(idx, total))


def _training_log_fragment_path(date: str, row_n: int, idx: int, abs_path: str) -> Path:
    key = hashlib.sha256(abs_path.encode("utf-8", errors="replace")).hexdigest()[:12]
    safe_date = re.sub(r"[^0-9-]+", "-", date or "unknown").strip("-") or "unknown"
    return FRAGMENTS_DIR / f"{safe_date}_row{row_n:04d}_log{idx}_{key}.html"


def _row_detail_fragment_path(date: str, row: dict) -> Path:
    row_n = int(row.get("n") or 0)
    key_basis = f"{row.get('abs_path') or ''}:{row.get('title') or ''}:{row.get('time_iso') or ''}"
    key = hashlib.sha256(key_basis.encode("utf-8", errors="replace")).hexdigest()[:12]
    safe_date = re.sub(r"[^0-9-]+", "-", date or "unknown").strip("-") or "unknown"
    return FRAGMENTS_DIR / f"{safe_date}_row{row_n:04d}_details_{key}.html"


def clear_day_fragments(date: str) -> None:
    if not FRAGMENTS_DIR.exists():
        return
    safe_date = re.sub(r"[^0-9-]+", "-", date or "unknown").strip("-") or "unknown"
    for path in FRAGMENTS_DIR.glob(f"{safe_date}_*.html"):
        try:
            path.unlink()
        except OSError:
            pass


def _write_training_log_fragment(date: str, row_n: int, ref: dict, idx: int) -> str:
    abs_path = ref.get("abs_path") or ""
    FRAGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    fragment_path = _training_log_fragment_path(date, row_n, idx, abs_path)
    text = _read_training_log_text(abs_path)
    fragment_path.write_text(
        f"<pre class='log-text'>{_pre_text_one_line(text)}</pre>",
        encoding="utf-8",
    )
    return f"fragments/{fragment_path.name}"


TRAINING_LOG_PREVIEW_LINES = 40


def _training_log_panel_html(ref: dict, idx: int, total: int, date: str, row_n: int) -> str:
    abs_path = ref.get("abs_path") or ""
    basename = sanitize_public_text(ref.get("basename") or "training_log")
    size = _format_bytes(ref.get("size"))
    meta_parts = [html.escape(_training_log_summary_label(idx, total)), html.escape(basename)]
    if size:
        meta_parts.append(html.escape(size))
    meta = " · ".join(meta_parts)

    # Inline the head of the log so the user sees real signal on the first
    # disclosure instead of a second "load" button. The full body stays in
    # a lazy-loaded fragment, and we omit the fragment button entirely when
    # the preview already covers the whole log.
    full_text = _read_training_log_text(abs_path)
    lines = full_text.split("\n")
    preview_lines = lines[:TRAINING_LOG_PREVIEW_LINES]
    has_more = len(lines) > TRAINING_LOG_PREVIEW_LINES
    preview_text = "\n".join(preview_lines)
    if has_more:
        preview_text = preview_text + f"\n… ({len(lines) - TRAINING_LOG_PREVIEW_LINES} more lines)"
    preview_html = (
        "<pre class='log-text log-text-preview'>"
        f"{_pre_text_one_line(preview_text)}"
        "</pre>"
    )

    if has_more:
        fragment_href = _write_training_log_fragment(date, row_n, ref, idx)
        target_id = f"log-text-{date}-{row_n}-{idx}".replace("_", "-")
        full_button_html = (
            f"<button class='lazy-test-load' type='button' "
            f"data-lazy-fragment='{html.escape(fragment_href, quote=True)}' "
            f"data-target='{html.escape(target_id, quote=True)}' "
            "data-load-label='view full log' data-hide-label='hide full log' "
            "data-loading-label='loading log' data-error-label='log load failed'>view full log</button>"
            f"<div id='{html.escape(target_id, quote=True)}' class='lazy-test-target' hidden></div>"
        )
    else:
        full_button_html = ""

    return (
        "<div class='log-panel'>"
        f"<div class='log-meta'>{meta}</div>"
        f"{preview_html}"
        f"{full_button_html}"
        "</div>"
    )


_REVIEW_MD_INDEX_CACHE: dict[str, Path] | None = None
_REVIEW_MD_FRAGMENT_HREF_CACHE: dict[Path, str] = {}
_GIT_COMMITS_CACHE: list[dict] | None = None


def _fetch_git_commits(conn: sqlite3.Connection) -> list[dict]:
    """Pull all git_commit artifacts once. Used by commits_panel_html.
    Separate query path; does not relax SUPPORTING_EXCLUDED_KINDS."""
    global _GIT_COMMITS_CACHE
    if _GIT_COMMITS_CACHE is not None:
        return _GIT_COMMITS_CACHE
    rows = conn.execute(
        "SELECT rel_path, source_label, mtime_iso, title, summary, abs_path, "
        "       file_kind, metrics_json "
        "FROM artifacts WHERE file_kind='git_commit' "
        "ORDER BY mtime_iso"
    ).fetchall()
    out = [dict(r) for r in rows]
    _GIT_COMMITS_CACHE = out
    return out


def commits_panel_html(conn: sqlite3.Connection, date: str) -> str:
    """Per-day disclosure listing git_commit artifacts whose best_date
    matches the page date. Empty days omit the panel entirely. Author info
    isn't extracted into the schema, so each item shows short_hash · time ·
    repo · subject. No GitHub link is emitted because the index spans
    multiple repos and we have no per-source URL mapping (logged as a
    follow-up note)."""
    commits = _fetch_git_commits(conn)
    matching = [c for c in commits if best_date(c) == date]
    if not matching:
        return ""
    matching.sort(key=lambda c: c.get("mtime_iso") or "")

    items: list[str] = []
    for c in matching:
        rel_path = str(c.get("rel_path") or "")
        short_hash = rel_path[:8] if rel_path else "?"
        ts_iso = str(c.get("mtime_iso") or "")
        ts = ts_iso[11:19] if len(ts_iso) >= 19 else ts_iso  # HH:MM:SS
        source_label = str(c.get("source_label") or "")
        if source_label.startswith("git:"):
            source_label = source_label[4:]
        title = sanitize_public_text(c.get("title") or "(no subject)")
        if len(title) > 160:
            title = title[:157] + "…"
        items.append(
            "<li class='commit-item'>"
            f"<span class='commit-hash'>{html.escape(short_hash)}</span> "
            f"<span class='commit-time'>{html.escape(ts)}</span> "
            f"<span class='commit-repo'>{html.escape(source_label)}</span> "
            f"<span class='commit-subject'>{html.escape(title)}</span>"
            "</li>"
        )
    teaser = f"{len(matching)} commits on {date}"
    return (
        "<details class='commits-panel'>"
        f"<summary class='commits-summary'>{html.escape(teaser)}</summary>"
        f"<ol class='commits-list'>{''.join(items)}</ol>"
        "</details>"
    )


def _build_review_md_index() -> dict[str, Path]:
    """date -> most recent .review.md (by mtime) whose .manifest.json's
    `dates` array covers that date. Lets a row's ablation label resolve to
    the labeling pass's rationale doc."""
    global _REVIEW_MD_INDEX_CACHE
    if _REVIEW_MD_INDEX_CACHE is not None:
        return _REVIEW_MD_INDEX_CACHE
    out: dict[str, list[tuple[float, Path]]] = defaultdict(list)
    labels_dir = OUT_ROOT / "ablation_labels"
    if not labels_dir.exists():
        _REVIEW_MD_INDEX_CACHE = {}
        return _REVIEW_MD_INDEX_CACHE
    for manifest_path in labels_dir.glob("*.manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        dates = manifest.get("dates")
        if not isinstance(dates, list):
            continue
        run_label = manifest_path.name[: -len(".manifest.json")]
        review_path = labels_dir / f"{run_label}.review.md"
        if not review_path.exists():
            continue
        try:
            mtime = review_path.stat().st_mtime
        except OSError:
            continue
        for d in dates:
            if isinstance(d, str):
                out[d].append((mtime, review_path))
    index: dict[str, Path] = {}
    for d, candidates in out.items():
        candidates.sort(reverse=True)
        index[d] = candidates[0][1]
    _REVIEW_MD_INDEX_CACHE = index
    return index


def _review_md_fragment_href(date: str) -> str | None:
    """Return the relative href of a fragment showing the review.md that
    covers `date`, or None if no review file applies. One fragment per
    review.md, shared across all rows on dates the manifest covers."""
    index = _build_review_md_index()
    review_path = index.get(date)
    if not review_path:
        return None
    if review_path in _REVIEW_MD_FRAGMENT_HREF_CACHE:
        return _REVIEW_MD_FRAGMENT_HREF_CACHE[review_path]
    FRAGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^0-9a-zA-Z_-]+", "-", review_path.stem)
    fragment_path = FRAGMENTS_DIR / f"ablation_review_{safe_label}.html"
    try:
        md_text = review_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        md_text = f"# (unable to read review: {type(exc).__name__}: {exc})"
    fragment_path.write_text(
        f"<div class='ablation-review-doc'>{_md_to_html_minimal(md_text)}</div>",
        encoding="utf-8",
    )
    href = f"fragments/{fragment_path.name}"
    _REVIEW_MD_FRAGMENT_HREF_CACHE[review_path] = href
    return href


def _row_evidence_panel_html(row: dict, date: str = "") -> str:
    facts: list[tuple[str, str]] = [
        ("source", sanitize_public_text(row.get("source_label") or "unknown")),
        ("classification", CAMP_DISPLAY_LABEL.get(row.get("camp"), str(row.get("camp") or "unknown"))),
        ("metric_source", str(row.get("val_bpb_source") or "unknown")),
    ]
    if row.get("time_iso"):
        facts.insert(0, ("time", str(row["time_iso"])))
    if row.get("hardware"):
        facts.insert(1, ("hardware", str(row["hardware"])))
    if row.get("wallclock_seconds"):
        try:
            facts.insert(2, ("wallclock_s", f"{float(row['wallclock_seconds']):.1f}"))
        except (TypeError, ValueError):
            facts.insert(2, ("wallclock_s", str(row["wallclock_seconds"])))

    fact_html = "".join(
        "<div class='log-meta'>"
        f"<strong>{html.escape(k)}</strong>: {html.escape(v)}"
        "</div>"
        for k, v in facts
    )
    raw_title = sanitize_public_text(row.get("title") or "(untitled)")
    label_text = sanitize_public_text(row.get("display_ablation") or raw_title)
    review_href = _review_md_fragment_href(date) if date else None
    has_label = bool(row.get("display_ablation"))
    if review_href and has_label:
        target_id = f"ablation-rationale-{date}-{row.get('n', 0)}".replace("_", "-")
        ablation_field = (
            "<div class='log-meta'><strong>ablation</strong>: "
            f"<button class='lazy-test-load lazy-ablation-label' type='button' "
            f"data-lazy-fragment='{html.escape(review_href, quote=True)}' "
            f"data-target='{html.escape(target_id, quote=True)}' "
            f"data-load-label='{html.escape(label_text)}' "
            f"data-hide-label='hide review' data-loading-label='loading review' "
            f"data-error-label='review load failed'>{html.escape(label_text)}</button>"
            f"<div id='{html.escape(target_id, quote=True)}' class='lazy-test-target' hidden></div>"
            "</div>"
        )
    else:
        ablation_field = (
            f"<div class='log-meta'><strong>ablation</strong>: {html.escape(label_text)}</div>"
        )
    return (
        "<div class='log-panel'>"
        "<div class='log-meta'><strong>row evidence</strong></div>"
        f"{ablation_field}"
        f"{fact_html}"
        "</div>"
    )


_DAILY_ACCURACY_CACHE: dict[str, dict] | None = None
_AUDIT_FINDINGS_CACHE: str | None = None
_CONV_ARCH_FILES_CACHE: list[tuple[str, str, Path]] | None = None
_CONV_ARCH_TEXT_CACHE: dict[Path, str] = {}


def _load_daily_accuracy() -> dict[str, dict]:
    """Per-date dict of audit summaries from output/audit/daily_accuracy.json."""
    global _DAILY_ACCURACY_CACHE
    if _DAILY_ACCURACY_CACHE is not None:
        return _DAILY_ACCURACY_CACHE
    try:
        raw = json.loads(DAILY_ACCURACY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _DAILY_ACCURACY_CACHE = {}
        return _DAILY_ACCURACY_CACHE
    out: dict[str, dict] = {}
    for entry in (raw.get("day_summaries") or []):
        date = entry.get("date") if isinstance(entry, dict) else None
        if date:
            out[str(date)] = entry
    _DAILY_ACCURACY_CACHE = out
    return out


def _audit_findings_text() -> str:
    global _AUDIT_FINDINGS_CACHE
    if _AUDIT_FINDINGS_CACHE is not None:
        return _AUDIT_FINDINGS_CACHE
    try:
        _AUDIT_FINDINGS_CACHE = AUDIT_FINDINGS_PATH.read_text(encoding="utf-8")
    except OSError:
        _AUDIT_FINDINGS_CACHE = ""
    return _AUDIT_FINDINGS_CACHE


def _audit_findings_lines_for_date(date: str) -> list[str]:
    """Pull lines mentioning this date out of AUDIT_FINDINGS as a per-date
    narrative excerpt. The doc has no section heads keyed by date, so we
    surface any matching line (table rows, '**date:**' markers, callouts)."""
    text = _audit_findings_text()
    if not text or not date:
        return []
    return [line for line in text.splitlines() if date in line]


def audit_panel_html(date: str) -> str:
    """Per-day audit chip (collapsed by default). Color: green when no
    warnings, amber when warnings>0, red when fatal>0; 'audit pending' when
    daily_accuracy.json has no entry for the date. Click expands to show
    any AUDIT_FINDINGS lines mentioning the date plus the day's JSON entry."""
    by_date = _load_daily_accuracy()
    entry = by_date.get(date)
    if not entry:
        return (
            "<div class='audit-badge audit-badge-pending'>"
            "<span class='audit-chip audit-pending'>audit pending</span>"
            "</div>"
        )
    fatal = int(entry.get("fatal") or 0)
    warnings_n = int(entry.get("warnings") or 0)
    headline = str(entry.get("headline_metric") or "—")
    raw = int(entry.get("raw_records") or 0)
    rendered = int(entry.get("render_records") or 0)
    if fatal > 0:
        chip_state = "audit-fatal"
    elif warnings_n > 0:
        chip_state = "audit-warn"
    else:
        chip_state = "audit-clean"
    chip_label_parts = [
        headline,
        f"{rendered} of {raw}",
        f"{warnings_n} warnings",
    ]
    if fatal > 0:
        chip_label_parts.append(f"{fatal} fatal")
    chip_label = " · ".join(chip_label_parts)

    # Pandoc treats a raw HTML block as ending at the first blank line, so
    # we have to keep <pre> contents on a single source line. Use &#10; for
    # the visible newlines, mirroring _pre_text_one_line's strategy.
    def _one_line_pre(text: str) -> str:
        return html.escape(text).replace("\n", "&#10;")

    matching_lines = _audit_findings_lines_for_date(date)
    findings_html = ""
    if matching_lines:
        findings_html = (
            "<div class='audit-section-label'>findings mentioning this date</div>"
            "<pre class='audit-findings'>"
            f"{_one_line_pre(chr(10).join(matching_lines))}"
            "</pre>"
        )
    json_block = (
        "<div class='audit-section-label'>audit summary</div>"
        "<pre class='audit-json'>"
        f"{_one_line_pre(json.dumps(entry, indent=2, sort_keys=True))}"
        "</pre>"
    )
    return (
        "<details class='audit-badge'>"
        f"<summary class='audit-chip {chip_state}'>{html.escape(chip_label)}</summary>"
        f"<div class='audit-body'>{findings_html}{json_block}</div>"
        "</details>"
    )


def _conversation_arch_dir() -> Path:
    return OUT_ROOT / "conversation_architecture"


def _conversation_arch_files() -> list[tuple[str, str, Path]]:
    """Index of available timeline files as (start_date, end_date, path).
    Skips the noisier _with_tool_results variants."""
    global _CONV_ARCH_FILES_CACHE
    if _CONV_ARCH_FILES_CACHE is not None:
        return _CONV_ARCH_FILES_CACHE
    out: list[tuple[str, str, Path]] = []
    d = _conversation_arch_dir()
    if d.exists():
        for path in sorted(d.glob("*.timeline.md")):
            stem = path.name[: -len(".timeline.md")]
            if stem.endswith("_with_tool_results"):
                continue
            if "_to_" in stem:
                start, end = stem.split("_to_", 1)
            else:
                start = end = stem
            out.append((start, end, path))
    _CONV_ARCH_FILES_CACHE = out
    return out


def _find_decision_trail_for_date(date: str) -> tuple[Path, str, str] | None:
    """Prefer single-day timeline; otherwise smallest enclosing window."""
    files = _conversation_arch_files()
    for start, end, path in files:
        if start == end == date:
            return (path, start, end)

    def _span_days(s: str, e: str) -> int:
        try:
            return (dt.date.fromisoformat(e) - dt.date.fromisoformat(s)).days
        except ValueError:
            return 99999

    candidates = [
        (start, end, path) for start, end, path in files
        if start <= date <= end
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: _span_days(c[0], c[1]))
    start, end, path = candidates[0]
    return (path, start, end)


def _load_decision_summary(timeline_path: Path) -> dict:
    summary_path = timeline_path.parent / (
        timeline_path.name[: -len(".timeline.md")] + ".summary.json"
    )
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_timeline_text(path: Path) -> str:
    if path in _CONV_ARCH_TEXT_CACHE:
        return _CONV_ARCH_TEXT_CACHE[path]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        text = f"# (unable to read timeline: {type(exc).__name__}: {exc})"
    _CONV_ARCH_TEXT_CACHE[path] = text
    return text


def _extract_day_from_timeline(md_text: str, date: str) -> str:
    """Slice out the '## YYYY-MM-DD' section from a multi-day timeline.
    Returns the section including its heading, ending at the next '## ' or
    end of file. Empty string if no matching section."""
    lines = md_text.splitlines()
    out: list[str] = []
    in_section = False
    target_heading = f"## {date}"
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if stripped == target_heading:
                in_section = True
                out.append(line)
                continue
            if in_section:
                break
        elif in_section:
            out.append(line)
    return "\n".join(out)


def _md_to_html_minimal(md_text: str) -> str:
    """Tiny markdown-to-HTML converter for lazy-loaded fragments. Handles
    headings (#-####), bullet lists, markdown tables, inline backticks,
    fenced code blocks, blank-line paragraphs. Not a full engine; sufficient
    for the timeline.md and review.md shapes we ship."""
    out: list[str] = []
    in_ul = False
    in_table: str | bool = False  # False, "header", or True (in body)
    in_code = False

    def _close_list() -> None:
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    def _close_table() -> None:
        nonlocal in_table
        if in_table:
            out.append("</tbody></table>")
            in_table = False

    def _inline(text: str) -> str:
        escaped = html.escape(text)
        return re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", escaped)

    for raw_line in md_text.splitlines():
        line = raw_line.rstrip()
        # Fenced code block toggle.
        if line.startswith("```"):
            _close_list(); _close_table()
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                out.append("<pre class='codeblock'>")
                in_code = True
            continue
        if in_code:
            out.append(html.escape(raw_line))
            continue
        # Markdown table row.
        if line.startswith("|") and line.endswith("|"):
            _close_list()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not in_table:
                out.append(
                    "<table class='md-table'><thead><tr>"
                    + "".join(f"<th>{_inline(c)}</th>" for c in cells)
                    + "</tr></thead><tbody>"
                )
                in_table = "header"
            elif in_table == "header" and all(set(c) <= set("-: ") for c in cells):
                pass  # alignment separator
            else:
                in_table = True
                out.append(
                    "<tr>"
                    + "".join(f"<td>{_inline(c)}</td>" for c in cells)
                    + "</tr>"
                )
            continue
        elif in_table:
            _close_table()
        if line.startswith("# "):
            _close_list()
            out.append(f"<h2>{_inline(line[2:])}</h2>")
        elif line.startswith("## "):
            _close_list()
            out.append(f"<h3>{_inline(line[3:])}</h3>")
        elif line.startswith("### "):
            _close_list()
            out.append(f"<h4>{_inline(line[4:])}</h4>")
        elif line.startswith("#### "):
            _close_list()
            out.append(f"<h5>{_inline(line[5:])}</h5>")
        elif line.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(line[2:])}</li>")
        elif line.strip() == "":
            _close_list()
            out.append("")
        else:
            _close_list()
            out.append(f"<p>{_inline(line)}</p>")
    _close_list()
    _close_table()
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


DECISION_TRAIL_FRAGMENT_MAX_CHARS = 300_000


def _write_decision_trail_fragment(date: str, timeline_path: Path, is_window: bool) -> str:
    FRAGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_date = re.sub(r"[^0-9-]+", "-", date or "unknown").strip("-") or "unknown"
    fragment_path = FRAGMENTS_DIR / f"{safe_date}_decision_trail.html"
    full = _read_timeline_text(timeline_path)
    section = _extract_day_from_timeline(full, date) if is_window else full
    if not section.strip():
        section = (
            f"## {date}\n\n"
            "_no architecture-change events recorded for this date in the available timelines._"
        )
    truncated = False
    if len(section) > DECISION_TRAIL_FRAGMENT_MAX_CHARS:
        head = section[:DECISION_TRAIL_FRAGMENT_MAX_CHARS]
        # Trim to the last complete event boundary so we don't end mid-line.
        last_event = head.rfind("\n### ")
        if last_event > DECISION_TRAIL_FRAGMENT_MAX_CHARS // 2:
            head = head[:last_event]
        section = head + (
            f"\n\n_… additional events truncated; full source: `{timeline_path.name}`._\n"
        )
        truncated = True
    fragment_path.write_text(
        # No need for &#10; here — fragment is loaded via fetch + innerHTML,
        # not parsed by Pandoc.
        f"<div class='decision-trail-doc'>{_md_to_html_minimal(section)}</div>",
        encoding="utf-8",
    )
    return f"fragments/{fragment_path.name}"


def decision_trail_panel_html(date: str) -> str:
    """Per-day decision-trail disclosure. Prefers a single-day timeline file
    and falls back to a slice of the smallest enclosing multi-day window.
    Omits the panel entirely when no timeline covers this date or when the
    matching window has zero events for it."""
    found = _find_decision_trail_for_date(date)
    if not found:
        return ""
    timeline_path, start, end = found
    is_window = (start != end)
    summary = _load_decision_summary(timeline_path)
    stats = summary.get("stats") if isinstance(summary, dict) else None
    stats = stats if isinstance(stats, dict) else {}

    if is_window:
        events_for_day = (stats.get("events_by_date") or {}).get(date, 0)
    else:
        events_for_day = stats.get("events", 0) or 0
    try:
        events_for_day = int(events_for_day)
    except (TypeError, ValueError):
        events_for_day = 0
    if events_for_day <= 0:
        return ""

    teaser_parts: list[str] = [f"{events_for_day} events on {date}"]
    if is_window:
        teaser_parts.append(f"window {start} → {end}")
    by_source = stats.get("events_by_source") or {}
    if isinstance(by_source, dict) and not is_window:
        per_source = ", ".join(
            f"{k}:{v}" for k, v in sorted(by_source.items()) if isinstance(v, int)
        )
        if per_source:
            teaser_parts.append(per_source)
    msg_total = stats.get("messages_scanned")
    if isinstance(msg_total, int) and not is_window:
        teaser_parts.append(f"{msg_total} msgs scanned")
    teaser = " · ".join(teaser_parts)

    fragment_href = _write_decision_trail_fragment(date, timeline_path, is_window)
    target_id = f"decision-trail-{date}".replace("_", "-")
    return (
        "<div class='decision-trail-panel'>"
        f"<div class='decision-trail-teaser'>{html.escape(teaser)}</div>"
        f"<button class='lazy-test-load' type='button' "
        f"data-lazy-fragment='{html.escape(fragment_href, quote=True)}' "
        f"data-target='{html.escape(target_id, quote=True)}' "
        "data-load-label='view decision trail' data-hide-label='hide decision trail' "
        "data-loading-label='loading trail' data-error-label='trail load failed'>view decision trail</button>"
        f"<div id='{html.escape(target_id, quote=True)}' class='lazy-test-target' hidden></div>"
        "</div>"
    )


def make_open_cell_html(row: dict) -> str:
    parts: list[str] = []
    logs = row.get("training_logs") or []
    for idx, ref in enumerate(logs, start=1):
        parts.append(_training_log_toggle_html(idx, len(logs)))

    if not logs:
        parts.append(_detail_toggle_html("details"))
    return "".join(parts) if parts else "—"


def make_log_detail_row_html(row: dict, date: str) -> str:
    logs = row.get("training_logs") or []
    row_n = int(row.get("n") or 0)
    panels = "".join(
        _training_log_panel_html(ref, idx, len(logs), date, row_n)
        for idx, ref in enumerate(logs, start=1)
    )
    panels += _row_evidence_panel_html(row, date)
    FRAGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    fragment_path = _row_detail_fragment_path(date, row)
    fragment_path.write_text(panels, encoding="utf-8")
    fragment_href = f"fragments/{fragment_path.name}"
    target_id = f"row-detail-{date}-{row_n}".replace("_", "-")
    return (
        "<tr class='log-detail-row'><td colspan='8'>"
        "<button class='lazy-test-load' type='button' "
        f"data-lazy-fragment='{html.escape(fragment_href, quote=True)}' "
        f"data-target='{html.escape(target_id, quote=True)}' "
        "data-load-label='load details' data-hide-label='hide details' "
        "data-loading-label='loading details' data-error-label='details load failed'>load details</button>"
        f"<div id='{html.escape(target_id, quote=True)}' class='lazy-test-target' hidden></div>"
        "</td></tr>"
    )


def _td_html(value: str, class_name: str | None = None) -> str:
    cls = f" class='{html.escape(class_name, quote=True)}'" if class_name else ""
    return f"<td{cls}>{value}</td>"


def make_test_table_md(rows: list[dict], metric: str,
                       date: str,
                       reference_baseline: float | None) -> str:
    if not rows:
        return (
            f'<p class="muted">No tests with measured {html.escape(metric_display_name(metric))} '
            "on this date.</p>"
        )
    out = []
    headers = ["#", "TIME", "HW", "ABLATION", metric_display_name(metric), "STATUS", "Δ %", "OPEN"]
    out.append(
        "<table class='test-runs-table'><thead><tr>"
        + "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        + "</tr></thead><tbody>"
    )
    for r in rows:
        ablation = sanitize_public_text(r.get("display_ablation") or r["title"])
        if r["n_runs"] > 1:
            ablation = f"{ablation} (×{r['n_runs']})"
        if len(ablation) > 80:
            ablation = ablation[:77] + "…"
        is_invalid = is_below_floor(metric, r["value"])
        is_crash = is_crash_value(metric, r["value"])
        delta_str = "—"
        if r.get("delta_pct") is not None and not is_invalid and not is_crash:
            arrow = "↓" if r["delta_pct"] < 0 else ("↑" if r["delta_pct"] > 0 else "")
            delta_str = f"{arrow}{abs(r['delta_pct']):.1f}%"
        elif is_invalid or is_crash:
            delta_str = "—"
        status_str = "<strong>INVALID</strong>" if is_invalid else ("CRASH" if is_crash else "OK")
        # Mark invalid val_bpb cell with class hook (used by HTML CSS)
        val_str = format_metric_value(metric, r["value"])
        if is_invalid:
            val_str = f"<code>{html.escape(val_str)}</code>"
        tr_class = ' class="invalid"' if is_invalid else ""
        out.append(
            f"<tr{tr_class}>"
            + _td_html(f"<strong>{int(r['n'])}</strong>")
            + _td_html(html.escape(r["time"] or "—"))
            + _td_html(html.escape(r["hardware"] or "—"))
            + _td_html(html.escape(ablation))
            + _td_html(val_str)
            + _td_html(status_str)
            + _td_html(html.escape(delta_str))
            + _td_html(make_open_cell_html(r), "open-cell")
            + "</tr>"
        )
        out.append(make_log_detail_row_html(r, date))
    out.append("</tbody></table>")
    return "\n".join(out)


def _kernel_lazy_summary_html(rows: list[dict], metric: str) -> str:
    valid = [
        r for r in rows
        if is_valid_metric_value(metric, r["value"])
    ]
    values = sorted(r["value"] for r in valid)
    if values:
        med = values[len(values) // 2] if len(values) % 2 else (
            values[len(values) // 2 - 1] + values[len(values) // 2]
        ) / 2.0
        metric_text = (
            f"min {format_metric_value(metric, values[0])} / "
            f"median {format_metric_value(metric, med)} / "
            f"max {format_metric_value(metric, values[-1])}"
        )
    else:
        metric_text = "no finite kernel metric rows"
    sources = sorted({sanitize_public_text(r.get("source_label") or "") for r in rows if r.get("source_label")})
    hardware = sorted({str(r.get("hardware") or "") for r in rows if r.get("hardware")})
    return (
        "<div class='lazy-test-meta'>"
        f"<span>{len(rows)} kernel rows</span>"
        f"<span>{len(valid)} measured</span>"
        f"<span>{html.escape(metric_text)}</span>"
        f"<span>{html.escape(', '.join(hardware[:3]) or 'hardware mixed')}</span>"
        f"<span>{html.escape(', '.join(sources[:3]) or 'sources mixed')}</span>"
        "</div>"
    )


def make_lazy_kernel_test_table_md(date: str, rows: list[dict], metric: str,
                                   reference_baseline: float | None) -> str:
    FRAGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    fragment_name = f"{date}_{metric}_kernel_tests.html"
    fragment_path = FRAGMENTS_DIR / fragment_name
    fragment_path.write_text(
        make_test_table_md(rows, metric, date, reference_baseline),
        encoding="utf-8",
    )
    target_id = f"kernel-tests-{date}-{metric}".replace("_", "-")
    return (
        "<div class='lazy-test-card'>"
        "<p><strong>KERNEL TEST RUNS</strong></p>"
        f"{_kernel_lazy_summary_html(rows, metric)}"
        f"<button class='lazy-test-load' type='button' "
        f"data-lazy-fragment='fragments/{html.escape(fragment_name, quote=True)}' "
        f"data-target='{html.escape(target_id, quote=True)}' "
        "data-load-label='load kernel tests' data-hide-label='hide kernel tests' "
        "data-loading-label='loading kernel tests' data-error-label='load failed'>load kernel tests</button>"
        f"<div id='{html.escape(target_id, quote=True)}' class='lazy-test-target' hidden></div>"
        "</div>"
    )


def load_approved_ablation_labels(path: Path = ABLATION_LABELS_PATH) -> dict[tuple[str, int, str], str]:
    """Load human-approved local-model labels.

    The key includes the raw title hash so stale approvals fail closed when row
    order or source titles change.
    """
    if not path.exists():
        return {}
    labels: dict[tuple[str, int, str], str] = {}
    with path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise TemplateContractError(
                    f"invalid ablation label JSON at {path}:{lineno}: {exc}"
                ) from exc
            if item.get("approved") is not True:
                continue
            try:
                date = str(item["date"])
                n = int(item["n"])
                title_sha = str(item["title_sha256"])
            except (KeyError, TypeError, ValueError) as exc:
                raise TemplateContractError(
                    f"approved ablation label missing date/n/title_sha256 at {path}:{lineno}"
                ) from exc
            label = str(item.get("approved_ablation") or item.get("suggested_ablation") or "").strip()
            label = re.sub(r"\s+", " ", label)
            if not label:
                continue
            if "\n" in label or "|" in label:
                raise TemplateContractError(
                    f"unsafe ablation label at {path}:{lineno}: {label!r}"
                )
            labels[(date, n, title_sha)] = label[:96]
    return labels


def apply_approved_ablation_labels(rows: list[dict], date: str,
                                  path: Path = ABLATION_LABELS_PATH) -> int:
    labels = load_approved_ablation_labels(path)
    if not labels:
        return 0
    applied = 0
    for r in rows:
        title_sha = ablation_title_sha(r.get("title") or "")
        label = labels.get((date, int(r["n"]), title_sha))
        if not label:
            continue
        r["display_ablation"] = label
        applied += 1
    return applied


def make_camp_test_tables_md(rows: list[dict], metric: str,
                             date: str,
                             reference_baseline: float | None) -> str:
    if not rows:
        return make_test_table_md(rows, metric, date, reference_baseline)

    sections: list[str] = []
    camp_order = [KERNEL_CAMP, "experimental", "neural"]
    known_camps = {r.get("camp", "experimental") for r in rows}
    ordered_camps = [c for c in camp_order if c in known_camps]
    ordered_camps.extend(sorted(known_camps - set(camp_order)))

    for camp in ordered_camps:
        camp_rows = [r for r in rows if r.get("camp", "experimental") == camp]
        if not camp_rows:
            continue
        label = CAMP_DISPLAY_LABEL.get(camp, camp).upper()
        sections.append(f"### {label} TEST RUNS — {len(camp_rows)}")
        sections.append("")
        if camp == KERNEL_CAMP and is_kernel_metric(metric):
            sections.append(
                make_lazy_kernel_test_table_md(date, camp_rows, metric, reference_baseline)
            )
        else:
            sections.append(make_test_table_md(camp_rows, metric, date, reference_baseline))
        sections.append("")
    return "\n".join(sections).strip()


# ---------- main render -----------------------------------------------------

def render_one_day(date: str, metric_override: str | None = None) -> dict:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    clear_day_fragments(date)
    records = report_records_for_date(date, fetch_day(conn, date))
    if not records:
        sys.exit(f"no artifacts found for {date}")
    final_submission_records = final_submission_records_for_day(date, records)
    if final_submission_records:
        records = final_submission_records

    # CLASSIFICATION % must reflect research output, not file-tree mass.
    # Count training-log records (excluding reference baselines) per camp;
    # this matches the Test Runs table's universe. Sister files (.json,
    # .md, .py supporting artifacts) inflated the prior denominator with
    # work-day file-touches that didn't represent test runs.
    by_camp: dict[str, int] = defaultdict(int)
    for r in records:
        if r.get("file_kind") != "training_log":
            continue
        if is_reference_baseline_record(r):
            continue
        by_camp[r["camp"]] += 1
    # If the day had no training_logs at all (commit-only / session-only days),
    # fall back to counting all records so the bar still renders something.
    if not by_camp:
        for r in records:
            by_camp[r["camp"]] += 1

    headline_metric = metric_override or pick_headline_metric(records)
    asset_dir = ASSETS_DIR / date
    asset_dir.mkdir(parents=True, exist_ok=True)

    chart_paths: list[str] = []
    chart_n = 0
    chart_baseline = None
    test_rows: list[dict] = []
    if headline_metric:
        chart_baseline = best_before(conn, date, headline_metric)
        # Build test_rows FIRST (gives us chronological # numbers); feed into
        # the chart so chart-dot # = table-row # (1:1 cross-reference).
        test_rows = extract_test_rows(records, headline_metric, chart_baseline)
        chart_input = [
            {"value": r["value"], "camp": r["camp"],
             "title": r["title"], "time_iso": r.get("time_iso"),
             "n": r["n"]}
            for r in test_rows
        ]
        chart_paths, chart_n = plot_mod.day_charts(
            asset_dir / f"day_chart_{headline_metric}.png",
            date=date,
            records=chart_input,
            metric_name=metric_display_name(headline_metric),
            baseline_to_beat=chart_baseline,
            baseline_label="best before today",
        )

    # Once test rows exist, CLASSIFICATION should describe the same universe as
    # SECTION 2.0 and the chart legend: collapsed daily test rows, not raw file
    # tree mass. If there are no tests, leave classification empty rather than
    # turning same-date file volume into a fake allocation signal.
    if test_rows:
        by_camp = defaultdict(int)
        for row in test_rows:
            by_camp[row.get("camp", "experimental")] += 1
    else:
        by_camp = defaultdict(int)

    # Header stats — "hours worked" deliberately removed; the chart's time
    # axis already shows the day's exploration trajectory.
    if headline_metric:
        unique_tests, total_dps, variety_pct = tests_variety_pct(records, headline_metric)
    else:
        unique_tests = total_dps = 0
        variety_pct = 0.0

    biggest_source = max(set(r["source_label"] for r in records),
                          key=lambda s: sum(1 for r in records if r["source_label"] == s))
    visible_support_records = [r for r in records if is_rendered_support_record(r)]
    if visible_support_records:
        visible_support_source = max(
            set(r["source_label"] for r in visible_support_records),
            key=lambda s: sum(1 for r in visible_support_records if r["source_label"] == s),
        )
    else:
        visible_support_source = "no day-local files/logs"

    headline_bits: list[str] = []
    if total_dps:
        headline_bits.append(
            f"{unique_tests} unique tests / {total_dps} datapoints "
            f"({variety_pct:.0f}% variety)"
        )
    headline_bits.append(f"top source: {biggest_source}")
    headline_bits.append(
        f"{by_camp.get('experimental', 0)} exp · "
        f"{by_camp.get('neural', 0)} neural"
    )
    headline_text = " · ".join(headline_bits)

    approved_ablation_labels = apply_approved_ablation_labels(test_rows, date)
    test_table_md = make_camp_test_tables_md(
        test_rows, headline_metric or "metric", date, chart_baseline
    )

    # Compute day index across the corpus (Day 1, Day 12, etc.)
    day_index = compute_day_index(conn, date)

    # ---- Report header (USGC machine-report style) ----
    exp_n = by_camp.get("experimental", 0)
    neu_n = by_camp.get("neural", 0)
    invalid_count = sum(
        1 for r in test_rows
        if is_below_floor(headline_metric, r["value"])
    )
    crash_count = sum(1 for r in test_rows if is_crash_value(headline_metric, r["value"]))
    valid_count = len(test_rows) - invalid_count - crash_count
    # NOTE: validity floor is a project-wide convention shown only on the
    # chart (the red zone). TOP SOURCE and the standalone ALLOCATION row were
    # dropped per design feedback — the experimental/neural % is now inline
    # inside the LAST (CLASSIFICATION) row as a 30px allocation bar.
    arch_families = detect_arch_families(test_rows)
    if is_bpb_metric(headline_metric):
        test_count_text = f"{len(test_rows)} unique  ({valid_count} valid / {invalid_count} below floor)"
    elif is_kernel_metric(headline_metric):
        test_count_text = f"{len(test_rows)} kernel benchmarks"
    else:
        test_count_text = f"{len(test_rows)} measured rows"
    best_headline_value = min(
        (r["value"] for r in test_rows if is_valid_metric_value(headline_metric, r["value"])),
        default=None,
    )
    header_fields = [
        ("DATE", date),
        ("DAY", format_day_index(day_index)),
        ("PRIMARY METRIC", metric_display_name(headline_metric) if headline_metric else "—"),
        ("TESTS RUN", test_count_text),
        ("ARCHITECTURE FAMILY", format_arch_families(arch_families)),
        ("CLASSIFICATION", "—"),  # replaced by alloc bar when measured tests exist
    ]
    alloc_bar_html = make_alloc_bar_html(by_camp) if test_rows else None
    report_header = make_report_header_html(header_fields, alloc_bar=alloc_bar_html)
    architecture_recipe_html, rendered_architecture_recipes = make_architecture_recipe_html(arch_families)

    h1_html = make_report_h1_html(
        "DAILY RESEARCH REPORT",
        date,
        master_href=f"report_144.html#reader={date}.html",
    )

    # Daily summary callout (between SECTION 1.0 and the chart)
    daily_summary = make_daily_summary_html(
        date=date, day_index=day_index, n_tests=len(test_rows),
        valid_count=valid_count, invalid_count=invalid_count,
        headline_metric=headline_metric or "metric",
        chart_baseline=chart_baseline,
        test_rows=test_rows, arch_families=arch_families,
        by_camp=by_camp,
    )

    # Primary-metric spread per family (small table after the chart)
    spread_table = make_metric_spread_table_md(test_rows,
                                               headline_metric or "metric",
                                               arch_families)

    qmd_lines = [
        h1_html,
        "",
        audit_panel_html(date),
        "",
    ]
    decision_trail_block = decision_trail_panel_html(date)
    if decision_trail_block:
        qmd_lines += [decision_trail_block, ""]
    commits_block = commits_panel_html(conn, date)
    if commits_block:
        qmd_lines += [commits_block, ""]
    qmd_lines += [
        report_header,
        "",
    ]
    if architecture_recipe_html:
        qmd_lines += [architecture_recipe_html, ""]
    qmd_lines += [
        "## SECTION 1.0 — TRAJECTORY",
        "",
        daily_summary,
        "",
    ]
    if chart_paths:
        for idx, chart_path in enumerate(chart_paths, start=1):
            relp = os.path.relpath(chart_path, QMD_DIR)
            if len(chart_paths) == 1:
                alt = f"{metric_display_name(headline_metric)} for {date}"
            else:
                alt = f"{metric_display_name(headline_metric)} for {date} panel {idx} of {len(chart_paths)}"
            qmd_lines.append(f"![{alt}]({relp})")
            qmd_lines.append("")
        if spread_table:
            qmd_lines.append(spread_table)
            qmd_lines.append("")
    else:
        qmd_lines.append(
            '<p class="muted">NO HEADLINE METRIC (VAL_BPB / VAL_LOSS / KERNEL RATIO) '
            "RECORDED ON THIS DATE.</p>"
        )
        qmd_lines.append("")

    qmd_lines += [
        "## SECTION 2.0 — TEST RUNS",
        "",
        test_table_md,
        "",
    ]
    assert_daily_template_contract(
        date=date,
        records=records,
        header_fields=header_fields,
        qmd_lines=qmd_lines,
        test_table_md=test_table_md,
        metric=headline_metric or "metric",
        n_tests=len(test_rows),
    )
    QMD_DIR.mkdir(parents=True, exist_ok=True)
    qmd_path = QMD_DIR / f"{date}.qmd"
    qmd_path.write_text("\n".join(qmd_lines))

    # Self-contained HTML preview
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    html_path = HTML_DIR / f"{date}.html"

    def md_to_html(md_text: str) -> str:
        out = []
        in_ul = False
        in_table = False
        for line in md_text.splitlines():
            if line.startswith("|") and line.rstrip().endswith("|"):
                # Markdown table row
                if in_ul:
                    out.append("</ul>"); in_ul = False
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if not in_table:
                    out.append("<table><thead><tr>" +
                               "".join(f"<th>{html.escape(c)}</th>" for c in cells) +
                               "</tr></thead><tbody>")
                    in_table = "header"
                elif in_table == "header" and all(set(c) <= set("-: ") for c in cells):
                    # separator row
                    pass
                else:
                    # If any cell contains the literal "**INVALID**" marker,
                    # tag the row so CSS can highlight it.
                    is_invalid = any("**INVALID**" in c for c in cells)
                    tr_class = " class='invalid'" if is_invalid else ""
                    out.append(f"<tr{tr_class}>" +
                               "".join(f"<td>{format_cell(c)}</td>" for c in cells) +
                               "</tr>")
                continue
            elif in_table:
                out.append("</tbody></table>")
                in_table = False
            if line.lstrip().startswith("<") and line.rstrip().endswith(">"):
                # Raw HTML line — pass through verbatim (used for the
                # experimental/neural ratio bar, etc.)
                if in_ul: out.append("</ul>"); in_ul = False
                out.append(line)
            elif line.startswith("## "):
                if in_ul: out.append("</ul>"); in_ul = False
                out.append(f"<h2>{html.escape(line[3:])}</h2>")
            elif line.startswith("### "):
                if in_ul: out.append("</ul>"); in_ul = False
                out.append(f"<h3>{html.escape(line[4:])}</h3>")
            elif line.startswith("- "):
                if not in_ul: out.append("<ul>"); in_ul = True
                inner = format_cell(line[2:])
                out.append(f"<li>{inner}</li>")
            elif line.strip() == "":
                if in_ul: out.append("</ul>"); in_ul = False
                out.append("")
            else:
                if in_ul: out.append("</ul>"); in_ul = False
                if line.startswith("# "):
                    out.append(f"<h1>{html.escape(line[2:])}</h1>")
                elif line.startswith("![") and "](" in line and line.endswith(")"):
                    alt_end = line.index("](")
                    alt = line[2:alt_end]
                    img_path = line[alt_end + 2:-1]
                    full = (QMD_DIR / img_path).resolve()
                    img_src = preview_chart_src(full)
                    if img_src:
                        out.append(
                            f"<figure><img src='{html.escape(img_src, quote=True)}' "
                            f"alt='{html.escape(alt)}'/></figure>"
                        )
                    else:
                        out.append(f"<p class='muted'>[missing image: {html.escape(img_path)}]</p>")
                else:
                    out.append(f"<p>{format_cell(line)}</p>")
        if in_ul:
            out.append("</ul>")
        if in_table:
            out.append("</tbody></table>")
        return "\n".join(out)

    def format_cell(s: str) -> str:
        s = html.escape(s)
        # Markdown links [label](url) → real anchors. Run BEFORE escape-aware
        # transforms so URLs aren't munged.
        s = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            lambda m: f"<a href='{m.group(2)}' target='_blank' rel='noopener'>{m.group(1)}</a>",
            s,
        )
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        # Only treat underscores as emphasis delimiters when they are not
        # inside identifiers. This preserves labels like training_log and
        # daily_grind exactly as the scraper emitted them.
        s = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", s)
        return s

    style = _daily_template_style()
    body_html = md_to_html("\n".join(qmd_lines))
    # Tag the auto-generated <ul> inside .supporting-section so the CSS
    # `.supporting-list li::before` stripe rules match it.
    body_html = re.sub(
        r'(<div class="supporting-section">.*?)<ul>',
        r'\1<ul class="supporting-list">',
        body_html, count=1, flags=re.DOTALL,
    )
    full_html = (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{date} — Research Day</title>"
        f"<style>{style}</style></head><body>"
        + body_html
        + _embedded_log_script()
        + "</body></html>"
    )
    html_path.write_text(full_html)

    return {
        "date": date,
        "qmd_path": str(qmd_path),
        "html_path": str(html_path),
        "asset_dir": str(asset_dir),
        "template_standard": DAILY_TEMPLATE_STANDARD,
        "template_style_sha256": LOCKED_TEMPLATE_STYLE_SHA256,
        "n_records": len(records),
        "by_camp": dict(by_camp),
        "biggest_source": biggest_source,
        "visible_support_source": visible_support_source,
        "n_visible_support_records": len(visible_support_records),
        "headline_metric": headline_metric,
        "headline_metric_display": metric_display_name(headline_metric) if headline_metric else "",
        "best_headline_value": best_headline_value,
        "best_headline_value_display": (
            format_metric_value(headline_metric, best_headline_value)
            if best_headline_value is not None else ""
        ),
        "best_headline_title": (
            min(
                (
                    r for r in test_rows
                    if is_valid_metric_value(headline_metric, r["value"])
                ),
                key=lambda r: r["value"],
                default={},
            ).get("title", "")
            if headline_metric else ""
        ),
        "n_test_rows": len(test_rows),
        "valid_test_rows": valid_count,
        "invalid_test_rows": invalid_count,
        "crash_test_rows": crash_count,
        "arch_families": [
            {"name": name, "count": count}
            for name, count in arch_families
        ],
        "arch_families_display": format_arch_families(arch_families),
        "architecture_recipes_rendered": rendered_architecture_recipes,
        "chart_n_points": chart_n,
        "chart_panels": len(chart_paths),
        "chart_baseline_to_beat": chart_baseline,
        "unique_tests": unique_tests,
        "n_training_log_rows": sum(1 for row in test_rows if row.get("training_logs")),
        "total_datapoints": total_dps,
        "variety_pct": variety_pct,
        "approved_ablation_labels": approved_ablation_labels,
    }


def main():
    ap = argparse.ArgumentParser()
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--date", help="YYYY-MM-DD")
    target.add_argument("--day", type=int, help="1-based corpus day index, e.g. 22")
    ap.add_argument("--metric", default=None, help="Override headline metric")
    args = ap.parse_args()
    date = args.date
    if args.day is not None:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        date = date_for_day_index(conn, args.day)
        conn.close()
        if date is None:
            sys.exit(f"no artifact date found for DAY {args.day:03d}")
    print(json.dumps(render_one_day(date, metric_override=args.metric), indent=2))


if __name__ == "__main__":
    main()
