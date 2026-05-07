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
import base64
import datetime as dt
import hashlib
import html
import json
import os
import re
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
ABLATION_LABELS_PATH = Path(os.environ.get(
    "ABLATION_LABELS_PATH",
    str(OUT_ROOT / "ablation_labels" / "approved.jsonl"),
))
LOCKED_TEMPLATE_HTML = Path(__file__).parent / "templates" / "daily_report_locked.html"
LOCKED_TEMPLATE_STYLE_SHA256 = "10bdc54d95a899ae2d60a669c18807f86538ea8105482bd226e51366f070dc4e"
DAILY_TEMPLATE_STANDARD = "daily-report-v2.0-wide-log-panel"
RESEARCH_START_DATE = "2026-03-18"
RESEARCH_END_DATE = "2026-05-01"
TRAINING_LOG_EMBED_CACHE: dict[str, str] = {}

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

HEADLINE_METRICS = ("val_bpb", "val_loss", "val_bits_per_byte", "bpb")
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
    "experimental": "experimental",
    "neural": "neural",
    "daily_grind": "daily grind",
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


def is_below_floor(metric: str | None, value: float) -> bool:
    return is_bpb_metric(metric) and value < INVALID_VAL_BPB_FLOOR


def is_crash_value(metric: str | None, value: float) -> bool:
    return is_bpb_metric(metric) and value > CRASH_VAL_BPB_THRESHOLD


def is_valid_metric_value(metric: str | None, value: float) -> bool:
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
    out = []
    for k, v in md.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        leaf = k.split("[")[0].split(".")[-1]
        if leaf == metric_name:
            out.append(float(v))
    return out


def pick_headline_metric(records: list[dict]) -> str | None:
    for metric in HEADLINE_METRICS:
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
        # Reference baselines aren't user tests — exclude them from the
        # Test Runs view (they still appear in supporting files).
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
        cur = by_title.get(title)
        if cur is None:
            row = {
                "title": title,
                "value": best_val,
                "n_runs": len(vals),
                "time": time_str,
                "time_iso": time_iso,
                "hardware": hardware,
                "hardware_priority": hw_priority if hardware else 99,
                "wallclock_seconds": wallclock,
                "camp": rec["camp"],
                "source_label": rec["source_label"],
                "abs_path": rec["abs_path"],
                "link_label": link_label,
                "link_href": link_href,
                "run_script": run_script,
                "val_bpb_source": bpb_source,
                "val_bpb_priority": bpb_priority,
                "training_logs": [],
            }
            _append_training_log_ref(row, rec)
            by_title[title] = row
            continue

        cur["n_runs"] += len(vals)
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
                "camp": rec.get("camp", "experimental"),
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
    """True for artifacts allowed to appear as report support evidence."""
    return (
        rec.get("camp") != "daily_grind"
        and not is_reference_baseline_record(rec)
        and rec.get("file_kind") in SUPPORTING_FILE_KINDS
        and rec.get("file_kind") not in SUPPORTING_EXCLUDED_KINDS
    )


def make_supporting_files_md(records: list[dict], test_record_paths: set[str]) -> str:
    """Files that directly support the day.

    Section 3 is not a cross-day artifact dump. When measured Test Runs exist,
    include sibling/child artifacts from those run directories. When the day
    has no measured runs, include a small day-local list of created files,
    logs, plans, summaries, and test-adjacent artifacts. Chat transcripts and
    commits are indexed elsewhere, but never rendered as research support.
    """
    out = ["", "## Supporting Files", ""]
    if not test_record_paths:
        priority = {
            "training_log": 0,
            "md": 1,
            "py": 2,
            "json": 3,
            "csv": 4,
            "ckpt": 5,
        }
        rest = [
            r for r in records
            if is_rendered_support_record(r)
        ]
        rest = sorted(
            rest,
            key=lambda r: (
                0 if SUPPORTING_RELEVANCE_RE.search(
                    " ".join([
                        r.get("abs_path") or "",
                        r.get("source_label") or "",
                        r.get("title") or "",
                    ])
                ) else 1,
                priority.get(r.get("file_kind"), 9),
                r.get("mtime_iso") or "",
                r.get("source_label") or "",
            ),
        )[:12]
        if not rest:
            out.append("_No supporting files: no day-local created files, logs, plans, or test artifacts were detected._")
            return "\n".join(out)
        for r in rest:
            rel = r["abs_path"].replace("/home/frosty40/", "~/")
            title = r["title"] or "(untitled)"
            link_label, link_href = _build_link(r)
            link_md = f" — [{link_label}]({link_href})" if link_href else ""
            out.append(f"- **{r['camp']}** · `{r['source_label']}` · {r['file_kind']} · "
                       f"`{rel}` — {title}{link_md}")
        return "\n".join(out)

    test_dirs = {
        os.path.abspath(str(Path(p).parent))
        for p in test_record_paths
        if p.startswith(HOME + "/")
    }
    rest = [
        r for r in records
        if r["abs_path"] not in test_record_paths
        and _is_in_any_dir(r.get("abs_path") or "", test_dirs)
        and is_rendered_support_record(r)
    ]
    if not rest:
        out.append("_No supporting files: no sibling artifacts were found for the detected test runs._")
        return "\n".join(out)
    for r in sorted(rest, key=lambda r: (r["camp"], r["source_label"], r["mtime_iso"])):
        rel = r["abs_path"].replace("/home/frosty40/", "~/")
        title = r["title"] or "(untitled)"
        link_label, link_href = _build_link(r)
        link_md = f" — [{link_label}]({link_href})" if link_href else ""
        out.append(f"- **{r['camp']}** · `{r['source_label']}` · {r['file_kind']} · "
                   f"`{rel}` — {title}{link_md}")
    return "\n".join(out)


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
    # Architecture / experiment family stems — match any suffix
    ("Medusa",               r"\bmedusa\w*"),
    ("ClownCar",             r"\bclown[\s_-]?car\w*"),
    ("Bandit",               r"\bbandit\w*"),
    ("Shroud",               r"\bshroud\w*"),
    ("Midnight",             r"\bmidnight\w*"),
    ("Rascal",               r"\brascal\w*"),
    ("Whale",                r"\b(?:blessed[\s_-]+)?whale\w*"),
    ("Megahelix",            r"\bmegahelix\w*"),
    ("Helix",                r"\bhelix\w*"),
    ("Ouroboros",            r"\bouroboros\w*"),
    ("Nitrust",              r"\bnitrust\w*"),
    ("Frugendorff",          r"\bfrugendorff\w*"),
    ("Mikey",                r"\bmikey\w*"),
    ("X-Wing",               r"\b[axfp][\s_-]?wing\w*"),
    ("Fartmagic",            r"\bfartmagic\w*"),
    ("Megakernel",           r"\bmegakernel\w*"),
    # Note: avoid trailing `\b` — "y" followed by "_" has no word-boundary
    # because `_` counts as a word character in Python regex. End matches
    # with `\w*` instead (matches the rest of the slug).
    ("Nightcrawler",         r"\bnightcrawler\w*"),
    ("SOTA Crawler",         r"\bsota[\s_-]+crawler\w*"),
    ("SOTA v2 TTT",          r"\bsota[\s_-]?v2[\s_-]+tttonly\w*"),
    ("Exp-D TTT8 Stride32",  r"\bexp[\s_-]?d[\s_-]+ttt8\w*"),
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
            if re.search(pat, title, re.IGNORECASE):
                counts[fam_name] = counts.get(fam_name, 0) + 1
                matched = True
                break
        if not matched:
            # Fallback: check the full path for the family name. Catches
            # generic-named logs (run_s1337.log) that live in dirs like
            # `.../sota_v2_tttonly_*/` or `.../nightcrawler_cubed/`.
            for fam_name, pat in ARCH_FAMILIES:
                if re.search(pat, path, re.IGNORECASE):
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
    parts = [f"{name.upper()} (×{n})" for name, n in families[:cap]]
    if len(families) > cap:
        more = sum(n for _, n in families[cap:])
        parts.append(f"+{len(families) - cap} MORE (×{more})")
    return "  ·  ".join(parts)


_FROSTED_FLAKE_PATH = "/home/frosty40/research_collator/assets/frosted_flake.png"
_FROSTED_FLAKE_DATA_URI: str | None = None


def _frosted_flake_data_uri() -> str:
    """Inline the H1 mark image as base64 so the HTML stays self-contained."""
    global _FROSTED_FLAKE_DATA_URI
    if _FROSTED_FLAKE_DATA_URI is None:
        try:
            with open(_FROSTED_FLAKE_PATH, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            _FROSTED_FLAKE_DATA_URI = f"data:image/png;base64,{b64}"
        except OSError:
            _FROSTED_FLAKE_DATA_URI = ""
    return _FROSTED_FLAKE_DATA_URI


_BASELINE_STYLE: str | None = None
_ARTIFACT_DAY_INDEX: dict[str, int] | None = None


def _embedded_log_style() -> str:
    return """
    /* Embedded training logs: compact toggle in OPEN, full-width panel below. */
    .test-runs-table td.open-cell { min-width: 150px; }
    .log-toggle { margin: 0; }
    .log-toggle + .log-toggle { margin-top: 6px; }
    .log-toggle summary {
        cursor: pointer;
        color: var(--link);
        font-weight: 600;
        white-space: nowrap;
    }
    .log-detail-row { display: none; }
    .test-runs-table tr:has(details.log-toggle[open]) + tr.log-detail-row,
    .log-detail-row.is-open { display: table-row; }
    .log-detail-row td {
        padding: 0 14px 14px;
        border-top: none;
        color: var(--ink);
    }
    .log-panel {
        border-top: 1px solid var(--rule);
        padding-top: 9px;
    }
    .log-panel + .log-panel { margin-top: 14px; }
    .log-meta {
        color: var(--ink-mute);
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
        color: var(--ink);
        background: transparent;
    }
    .open-extra {
        margin-top: 6px;
        color: var(--ink-mute);
        font-size: 11px;
    }
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
        "document.querySelectorAll('details.log-toggle').forEach(function(d){"
        "d.addEventListener('toggle',function(){sync(d);});"
        "sync(d);"
        "});"
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
        ".supporting-section",
        ".bpb-table",
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

    expected_header = (
        f"| # | TIME | HW | ABLATION | {metric.upper()} | STATUS | Δ % | OPEN |"
    )
    expected_html_header = (
        "<thead><tr>"
        + "".join(
            f"<th>{html.escape(c)}</th>"
            for c in ["#", "TIME", "HW", "ABLATION", metric.upper(), "STATUS", "Δ %", "OPEN"]
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
    elif n_tests and expected_html_header not in test_table_md:
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
    exp = by_camp.get("experimental", 0)
    neu = by_camp.get("neural", 0)
    total = exp + neu
    if total == 0:
        return ""
    exp_pct = 100.0 * exp / total
    neu_pct = 100.0 * neu / total
    label = f"EXPERIMENTAL {exp_pct:.0f}% ({exp}) / NEURAL {neu_pct:.0f}% ({neu})"
    return (
        f'<span class="alloc-bar" aria-label="{html.escape(label)}">'
          f'<span class="alloc-seg-exp" style="width:{exp_pct:.2f}%"></span>'
          f'<span class="alloc-seg-neu" style="width:{neu_pct:.2f}%"></span>'
        '</span>'
        '<span class="alloc-text">'
          f'<span class="alloc-text-exp">EXPERIMENTAL {exp_pct:.0f}% ({exp})</span>'
          '<span class="alloc-sep">/</span>'
          f'<span class="alloc-text-neu">NEURAL {neu_pct:.0f}% ({neu})</span>'
        '</span>'
    )


def make_daily_summary_html(date: str, day_index: int | None,
                            n_tests: int, valid_count: int,
                            invalid_count: int, headline_metric: str,
                            chart_baseline: float | None,
                            test_rows: list[dict],
                            arch_families: list[tuple[str, int]],
                            by_camp: dict[str, int]) -> str:
    """Two-paragraph callout that sits between SECTION 1.0 and the chart.
    Generated deterministically from the day's numbers — no LLM."""
    metric = (headline_metric or "metric").upper()
    floor = INVALID_VAL_BPB_FLOOR
    exp = by_camp.get("experimental", 0)
    neu = by_camp.get("neural", 0)
    total = max(exp + neu, 1)
    exp_pct = 100.0 * exp / total
    neu_pct = 100.0 * neu / total
    day_label = format_day_index(day_index)
    day_ref = f"Day {day_label}" if day_label != "—" else "Unindexed day"

    # Zero measured validation rows — don't fabricate "allocation skew" or
    # "the day was about hammering X variants" when the day has support files
    # but no explicit val_bpb/val_loss output. Common causes: infra/studio
    # days, kernel-benchmark days, and session-only days.
    if n_tests == 0:
        return (
            '<aside class="day-summary">'
              '<div class="ds-key">DAILY SUMMARY</div>'
              f'<div class="ds-body"><p>{day_ref} — '
              f'<strong>no explicit validation metric</strong> was captured '
              'on this date.</p></div>'
            '</aside>'
        )

    # Allocation tone — only when we actually have runs to talk about.
    if exp_pct >= 80:
        allocation_tone = "skewed hard experimental"
    elif neu_pct >= 80:
        allocation_tone = "skewed hard neural"
    elif abs(exp_pct - neu_pct) < 15:
        allocation_tone = "balanced experimental/neural"
    else:
        side = "experimental" if exp_pct > neu_pct else "neural"
        allocation_tone = f"{side}-leaning"

    # Top architectures
    top_arch_names = [name for name, _ in arch_families[:2] if name != "Other"]
    if top_arch_names:
        arch_phrase = (f"the day was about hammering "
                       f"{' + '.join(name.upper() for name in top_arch_names)} variants")
    else:
        arch_phrase = "the day was a mixed-architecture sweep"

    if is_bpb_metric(headline_metric):
        validity_phrase = (
            f"with <strong>{valid_count} valid</strong> landings above the {floor:.2f} "
            f"eval-error floor and <strong>{invalid_count} below-floor</strong> "
            "readings discarded"
        )
    else:
        validity_phrase = f"with <strong>{valid_count}</strong> measured rows"

    para1 = (
        f"{day_ref} burned {n_tests} runs against <strong>{html.escape(metric)}</strong>, "
        f"{validity_phrase}. "
        f"Allocation {allocation_tone} ({exp_pct:.0f}% / {neu_pct:.0f}% neural) — "
        f"{arch_phrase}."
    )

    # Para 2: best-of-day, PB comparison
    valid_rows = [
        r for r in test_rows
        if is_valid_metric_value(headline_metric, r["value"])
    ]
    if valid_rows:
        best = min(valid_rows, key=lambda r: r["value"])
        best_value = best["value"]
        best_title = best.get("title", "(unknown)")
        if chart_baseline is not None and best_value < chart_baseline:
            pb_line = (f"<strong>NEW PERSONAL BEST.</strong> Best valid "
                       f"<strong>{best_value:.4f}</strong> beats prior bar "
                       f"<strong>{chart_baseline:.4f}</strong>.")
        elif chart_baseline is not None:
            pb_line = (f"No new personal best. Best valid of the day = "
                       f"<strong>{best_value:.4f}</strong> "
                       f"({html.escape(best_title[:60])}); "
                       f"best-before-today = <strong>{chart_baseline:.4f}</strong> still stands.")
        else:
            pb_line = (f"Best valid of the day = <strong>{best_value:.4f}</strong> "
                       f"({html.escape(best_title[:60])}). "
                       f"No prior baseline to compare against.")
    else:
        pb_line = "<strong>No valid runs.</strong> Every measurement landed below the eval-error floor."

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
          f'<div class="ds-body"><p>{para1}</p><p>{pb_line}</p></div>'
        '</aside>'
    )


def make_bpb_spread_table_md(test_rows: list[dict], headline_metric: str,
                             arch_families: list[tuple[str, int]]) -> str:
    """VAL_BPB spread per architecture family — n / min / median / max,
    valid runs only. Returns rendered HTML directly (custom .bpb-table class)."""
    valid = [
        r for r in test_rows
        if is_valid_metric_value(headline_metric, r["value"])
    ]
    if not valid:
        return ""

    def family_of(title: str) -> str:
        for fam_name, pat in ARCH_FAMILIES:
            if re.search(pat, title or "", re.IGNORECASE):
                return fam_name
        return "Other"

    by_fam: dict[str, list[float]] = {}
    for r in valid:
        fam = family_of(r.get("title", ""))
        by_fam.setdefault(fam, []).append(r["value"])
    # Order rows by overall arch_families ranking (count descending)
    ordered_fams = [f for f, _ in arch_families if f in by_fam]
    for f in by_fam:
        if f not in ordered_fams:
            ordered_fams.append(f)

    metric = (headline_metric or "metric").upper()
    rows = [f'<table class="bpb-table"><thead><tr>'
            f'<th>{metric} SPREAD</th><th>n</th><th>min</th>'
            f'<th>median</th><th>max</th></tr></thead><tbody>']
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
            f'<tr><td>{html.escape(fam.upper())}</td>'
            f'<td>{n}</td><td>{mn:.4f}</td>'
            f'<td>{med:.4f}</td><td>{mx:.4f}</td></tr>'
        )
    # All-valid row
    all_vals = sorted(v for vs in by_fam.values() for v in vs)
    n = len(all_vals)
    if n:
        med = all_vals[n // 2] if n % 2 == 1 else (all_vals[n // 2 - 1] + all_vals[n // 2]) / 2.0
        rows.append(
            f'<tr><td>ALL VALID</td>'
            f'<td>{n}</td><td>{all_vals[0]:.4f}</td>'
            f'<td>{med:.4f}</td><td>{all_vals[-1]:.4f}</td></tr>'
        )
    rows.append('</tbody></table>')
    return "\n".join(rows)


def make_camp_bar_html(by_camp: dict[str, int]) -> str:
    """Horizontal %-stacked bar showing experimental vs neural work for the day.
    Tiny inline HTML (no extra deps) that survives both Quarto rendering and
    the custom md_to_html passthrough."""
    exp = by_camp.get("experimental", 0)
    neu = by_camp.get("neural", 0)
    total = exp + neu
    if total == 0:
        return ""
    exp_pct = 100.0 * exp / total
    neu_pct = 100.0 * neu / total
    return (
        '<div class="camp-bar">'
          f'<div class="camp-seg camp-seg-exp" style="width: {exp_pct:.2f}%" '
          f'title="experimental: {exp} ({exp_pct:.0f}%)"></div>'
          f'<div class="camp-seg camp-seg-neu" style="width: {neu_pct:.2f}%" '
          f'title="neural: {neu} ({neu_pct:.0f}%)"></div>'
        '</div>'
        '<div class="camp-bar-labels">'
          f'<span class="camp-label-exp">experimental · {exp} ({exp_pct:.0f}%)</span>'
          f'<span class="camp-label-neu">{neu_pct:.0f}% ({neu}) · neural</span>'
        '</div>'
    )


def make_grind_md(records: list[dict]) -> str:
    """Daily Grind = the narrative trail of the day:
       - codex_rollouts (camp=daily_grind) — daily session summaries
       - codex_session / claude_session — actual collaboration transcripts
    Both go here because they're 'how the day went' not 'what got tested'."""
    grind = [r for r in records
             if r["camp"] == "daily_grind"
             or r.get("file_kind") in ("codex_session", "claude_session")]
    if not grind:
        return "_No codex/claude sessions or rollups recorded for this date._"
    chunks = []
    # Sessions first (longest), then rollups
    sessions = [r for r in grind if r.get("file_kind") in ("codex_session", "claude_session")]
    rollups = [r for r in grind if r.get("file_kind") not in ("codex_session", "claude_session")]
    if sessions:
        # Compute total session-time signal
        total_hours = 0.0
        for r in sessions:
            try:
                md = json.loads(r.get("metrics_json") or "{}")
                d = md.get("session_duration_seconds")
                if isinstance(d, (int, float)):
                    total_hours += d / 3600.0
            except json.JSONDecodeError:
                pass
        chunks.append(
            f"**{len(sessions)} sessions logged** "
            f"(~{total_hours:.1f}h cumulative, may overlap):\n"
        )
        for r in sorted(sessions, key=lambda r: r["mtime_iso"]):
            t = r["title"] or "(untitled session)"
            s = (r["summary"] or "").strip()
            kind = "claude" if r.get("file_kind") == "claude_session" else "codex"
            chunks.append(f"- **[{kind}]** {t[:90]} — {s}")
        if rollups:
            chunks.append("")
    for r in sorted(rollups, key=lambda r: r["mtime_iso"]):
        t = r["title"] or "(untitled rollup)"
        s = (r["summary"] or "").strip()
        chunks.append(f"- **[rollup]** {t}" + (f" — {s}" if s else ""))
    return "\n".join(chunks)


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
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "\uFFFD")
    return html.escape(normalized).replace("\n", "&#10;")


def _anchor_html(label: str, href: str) -> str:
    return (
        f"<a href='{html.escape(href, quote=True)}' target='_blank' "
        f"rel='noopener'>{html.escape(label)}</a>"
    )


def _training_log_summary_label(idx: int, total: int) -> str:
    return "training_log" if total == 1 else f"training_log {idx}"


def _training_log_toggle_html(idx: int, total: int) -> str:
    summary = _training_log_summary_label(idx, total)
    return (
        "<details class='log-toggle'>"
        f"<summary>{html.escape(summary)}</summary>"
        "</details>"
    )


def _training_log_panel_html(ref: dict, idx: int, total: int) -> str:
    abs_path = ref.get("abs_path") or ""
    basename = ref.get("basename") or "training_log"
    text = _read_training_log_text(abs_path)
    size = _format_bytes(ref.get("size"))
    meta_parts = [html.escape(_training_log_summary_label(idx, total)), html.escape(basename)]
    if size:
        meta_parts.append(html.escape(size))
    if ref.get("href"):
        meta_parts.append(_anchor_html(ref.get("href_label") or "open file", ref["href"]))
    meta = " · ".join(meta_parts)
    return (
        "<div class='log-panel'>"
        f"<div class='log-meta'>{meta}</div>"
        f"<pre class='log-text'>{_pre_text_one_line(text)}</pre>"
        "</div>"
    )


def make_open_cell_html(row: dict) -> str:
    parts: list[str] = []
    logs = row.get("training_logs") or []
    for idx, ref in enumerate(logs, start=1):
        parts.append(_training_log_toggle_html(idx, len(logs)))

    extra_links: list[str] = []
    if not logs and row.get("link_href"):
        extra_links.append(_anchor_html(row.get("link_label") or "open", row["link_href"]))
    elif row.get("link_href") and all(ref.get("href") != row["link_href"] for ref in logs):
        extra_links.append(_anchor_html(row.get("link_label") or "open", row["link_href"]))
    if row.get("run_script"):
        extra_links.append(_anchor_html("run.sh", row["run_script"]))
    if extra_links:
        parts.append("<div class='open-extra'>" + " · ".join(extra_links) + "</div>")
    return "".join(parts) if parts else "—"


def make_log_detail_row_html(row: dict) -> str:
    logs = row.get("training_logs") or []
    if not logs:
        return ""
    panels = "".join(
        _training_log_panel_html(ref, idx, len(logs))
        for idx, ref in enumerate(logs, start=1)
    )
    return f"<tr class='log-detail-row'><td colspan='8'>{panels}</td></tr>"


def _td_html(value: str, class_name: str | None = None) -> str:
    cls = f" class='{html.escape(class_name, quote=True)}'" if class_name else ""
    return f"<td{cls}>{value}</td>"


def make_test_table_md(rows: list[dict], metric: str,
                       reference_baseline: float | None) -> str:
    if not rows:
        return (
            f'<p class="muted">No tests with measured {html.escape(metric)} '
            "on this date.</p>"
        )
    out = []
    headers = ["#", "TIME", "HW", "ABLATION", metric.upper(), "STATUS", "Δ %", "OPEN"]
    out.append(
        "<table class='test-runs-table'><thead><tr>"
        + "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        + "</tr></thead><tbody>"
    )
    for r in rows:
        ablation = r.get("display_ablation") or r["title"]
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
        val_str = f"{r['value']:.4f}"
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
        log_detail_row = make_log_detail_row_html(r)
        if log_detail_row:
            out.append(log_detail_row)
    out.append("</tbody></table>")
    return "\n".join(out)


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
                             reference_baseline: float | None) -> str:
    if not rows:
        return make_test_table_md(rows, metric, reference_baseline)

    sections: list[str] = []
    camp_order = ["experimental", "neural"]
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
        sections.append(make_test_table_md(camp_rows, metric, reference_baseline))
        sections.append("")
    return "\n".join(sections).strip()


# ---------- main render -----------------------------------------------------

def render_one_day(date: str, metric_override: str | None = None) -> dict:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    records = report_records_for_date(date, fetch_day(conn, date))
    if not records:
        sys.exit(f"no artifacts found for {date}")

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
            metric_name=headline_metric,
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

    grind_md = make_grind_md(records)
    approved_ablation_labels = apply_approved_ablation_labels(test_rows, date)
    test_table_md = make_camp_test_tables_md(test_rows, headline_metric or "metric", chart_baseline)

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
    test_count_text = f"{len(test_rows)} unique  ({valid_count} valid / {invalid_count} below floor)"
    header_fields = [
        ("DATE", date),
        ("DAY", format_day_index(day_index)),
        ("PRIMARY METRIC", (headline_metric or "—").upper()),
        ("TESTS RUN", test_count_text),
        ("ARCHITECTURE FAMILY", format_arch_families(arch_families)),
        ("CLASSIFICATION", "—"),  # replaced by alloc bar when measured tests exist
    ]
    alloc_bar_html = make_alloc_bar_html(by_camp) if test_rows else None
    report_header = make_report_header_html(header_fields, alloc_bar=alloc_bar_html)

    # H1 with frosted-flake mark + date pinned right
    h1_html = (
        '<h1>'
          '<span class="h1-title">'
            '<img class="h1-mark" src="' + _frosted_flake_data_uri() + '" alt="">'
            '<span>DAILY RESEARCH REPORT</span>'
          '</span>'
          f'<span class="h1-date">{html.escape(date)}</span>'
        '</h1>'
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

    # VAL_BPB SPREAD per family (small table after the chart)
    spread_table = make_bpb_spread_table_md(test_rows,
                                            headline_metric or "metric",
                                            arch_families)

    qmd_lines = [
        h1_html,
        "",
        report_header,
        "",
        "## SECTION 1.0 — TRAJECTORY",
        "",
        daily_summary,
        "",
    ]
    if chart_paths:
        for idx, chart_path in enumerate(chart_paths, start=1):
            relp = os.path.relpath(chart_path, QMD_DIR)
            if len(chart_paths) == 1:
                alt = f"{headline_metric} for {date}"
            else:
                alt = f"{headline_metric} for {date} panel {idx} of {len(chart_paths)}"
            qmd_lines.append(f"![{alt}]({relp})")
            qmd_lines.append("")
        if spread_table:
            qmd_lines.append(spread_table)
            qmd_lines.append("")
    else:
        qmd_lines.append(
            '<p class="muted">NO HEADLINE METRIC (VAL_BPB / VAL_LOSS) '
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
                    try:
                        with open(full, "rb") as f:
                            b64 = base64.b64encode(f.read()).decode("ascii")
                        out.append(
                            f"<figure><img src='data:image/png;base64,{b64}' "
                            f"alt='{html.escape(alt)}'/></figure>"
                        )
                    except OSError:
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
