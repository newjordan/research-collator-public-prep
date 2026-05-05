#!/usr/bin/env python3
"""Render ONE day's research report — re-shaped per user spec:

  HEADER     hours worked · tests-variety % · top source
  CHART      day_chart for headline metric (val_bpb preferred, val_loss fallback)
  TESTS      table: time | hardware | ablation detail | bpb result | Δ vs best
  GRIND      codex_rollouts narrative for the date
  BIB        every artifact contributing to the day, with abs_path

Usage:
    python3 render_day.py --date 2026-04-26
    python3 render_day.py --date 2026-04-26 --metric val_loss
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import os
import re
import sqlite3
import sys

import yaml
from collections import defaultdict
from pathlib import Path

import plot as plot_mod

DB = "/home/frosty40/research_collator/index.sqlite"
OUT_ROOT = Path("/home/frosty40/research_collator/output")
QMD_DIR = OUT_ROOT / "days"
HTML_DIR = OUT_ROOT / "preview"
ASSETS_DIR = OUT_ROOT / "assets"

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

HEADLINE_METRICS = ("val_bpb", "val_loss", "val_bits_per_byte", "bpb", "loss")


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

    # 3. mtime fallback
    if rec.get("mtime_iso"):
        return rec["mtime_iso"][:10]
    return None


def fetch_day(conn: sqlite3.Connection, date: str) -> list[dict]:
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT * FROM artifacts WHERE date(mtime_iso)=? OR rel_path LIKE ? OR abs_path LIKE ?",
        (date, f"%{date.replace('-', '')}%", f"%{date}%"),
    ).fetchall()
    out = []
    for r in rows:
        rec = dict(r)
        if best_date(rec) == date:
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
            if extract_metric_for_record(rec.get("metrics_json"), metric):
                n += 1
                if n >= 2:
                    return metric
    return None


def best_before(conn: sqlite3.Connection, date: str, metric: str) -> float | None:
    """Best (lowest, since loss-style) metric across records strictly before date."""
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
        for v in extract_metric_for_record(rec["metrics_json"], metric):
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
    Returns (unique, total, pct)."""
    titles_per_dp: list[str] = []
    for rec in records:
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
    time; the filename has the actual run timestamp. Prefer that.
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
    return rec.get("mtime_iso")


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
            by_title[title] = {
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
            }
            continue

        cur["n_runs"] += len(vals)
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
    """
    out = []
    for rec in records:
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

def make_supporting_files_md(records: list[dict], test_record_paths: set[str]) -> str:
    """Everything that wasn't a numbered Test Run — supporting docs, codex
    sessions, the leg's checkpoints/configs/etc."""
    out = ["", "## Supporting Files", ""]
    rest = [r for r in records if r["abs_path"] not in test_record_paths]
    if not rest:
        out.append("_No supporting files._")
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
    # Specific compound names (must match before their components)
    ("AR Self-Gen GPTQ",     r"\bar[\s_-]+self[\s_-]+gen[\s_-]+gptq\b"),
    ("Binary U-Net",         r"\bbinary(?:[\s_-]+asymmetric)?[\s_-]+u[\s_-]?net"),
    ("Ternary U-Net",        r"\bternary[\s_-]+u[\s_-]?net"),
    ("Mixed Quant",          r"\bmixed[\s_-]+(?:precision[\s_-]+)?quant"),
    ("Depth Recurrence",     r"\bdepth[\s_-]+recurrence\b"),
    ("Parallel Residuals",   r"\bparallel[\s_-]+residual"),
    ("Sliding Window",       r"\bsliding[\s_-]+window\b"),
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
    # Components / methods (only fall-through if no family matched above)
    ("DeltaNet",             r"\bdeltanet\w*"),
    ("JEPA",                 r"\bjepa\b"),
    ("XSA",                  r"\bxsa(?:[\s_-]\w*)?"),
    ("BigramHash",           r"\bbigram[\s_-]?hash\w*"),
    ("GPTQ",                 r"\bgptq\w*"),
    ("LoRA-TTT",             r"\blora\b.*\bttt\b"),
    ("State-Space (TTT)",    r"\bstate[\s_-]+space\b"),
    ("Modded-nanoGPT",       r"\bmodded[\s_-]?nanogpt\w*"),
]


def detect_arch_families(test_rows: list[dict]) -> list[tuple[str, int]]:
    """For each test row, find the FIRST matching family from ARCH_FAMILIES.
    Returns ordered (family_name, count) descending. Unmatched → 'Other'."""
    counts: dict[str, int] = {}
    unmatched = 0
    for row in test_rows:
        title = (row.get("title") or "")
        matched = False
        for fam_name, pat in ARCH_FAMILIES:
            if re.search(pat, title, re.IGNORECASE):
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


_DAY_EPOCH: dt.date | None = None


def _day_epoch() -> dt.date:
    """Read the day-numbering epoch from config.yaml once. day_index is stable
    relative to this anchor — never drifts as the scraper finds new sources."""
    global _DAY_EPOCH
    if _DAY_EPOCH is None:
        try:
            with open("/home/frosty40/research_collator/config.yaml") as f:
                cfg = yaml.safe_load(f)
            anchor = cfg.get("day_epoch", "2026-03-17")
            _DAY_EPOCH = dt.date.fromisoformat(anchor)
        except (OSError, ValueError):
            _DAY_EPOCH = dt.date(2026, 3, 17)
    return _DAY_EPOCH


def compute_day_index(conn: sqlite3.Connection, date: str) -> int | None:
    """Days since the locked epoch (config.yaml `day_epoch`), 1-indexed.
    Day 1 = epoch. Stable across stripper / enrich / classify re-runs and
    across new sources being added — same date always gets the same number."""
    try:
        target = dt.date.fromisoformat(date)
    except ValueError:
        return None
    delta = (target - _day_epoch()).days
    return delta + 1 if delta >= 0 else None


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


def make_alloc_bar_html(by_camp: dict[str, int]) -> str:
    """Inline 240×30 allocation bar — experimental dark-green block + neural
    striped lighter-green block + a label string after the bar."""
    exp = by_camp.get("experimental", 0)
    neu = by_camp.get("neural", 0)
    total = exp + neu
    if total == 0:
        return ""
    exp_pct = 100.0 * exp / total
    neu_pct = 100.0 * neu / total
    return (
        '<span class="alloc-bar">'
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

    # Allocation tone
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

    para1 = (
        f"Day {day_index:03d} burned {n_tests} runs against <strong>{html.escape(metric)}</strong>, "
        f"with <strong>{valid_count} valid</strong> landings above the {floor:.2f} eval-error floor "
        f"and <strong>{invalid_count} below-floor</strong> readings discarded. "
        f"Allocation {allocation_tone} ({exp_pct:.0f}% / {neu_pct:.0f}% neural) — "
        f"{arch_phrase}."
    )

    # Para 2: best-of-day, PB comparison
    valid_rows = [r for r in test_rows if r["value"] >= floor]
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
    crash_count = sum(1 for r in test_rows if r["value"] > 3.0)
    if crash_count:
        crash_values = sorted([r["value"] for r in test_rows if r["value"] > 3.0],
                              reverse=True)[:2]
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
    valid = [r for r in test_rows if r["value"] >= INVALID_VAL_BPB_FLOOR]
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


INVALID_VAL_BPB_FLOOR = 1.06


def make_test_table_md(rows: list[dict], metric: str,
                       reference_baseline: float | None) -> str:
    if not rows:
        return f"_No tests with measured {metric} on this date._"
    out = []
    out.append(f"| # | TIME | HW | ABLATION | {metric.upper()} | STATUS | Δ % | OPEN |")
    out.append("|---|------|----|----------|-----------------|--------|-----|------|")
    for r in rows:
        ablation = r["title"]
        if r["n_runs"] > 1:
            ablation = f"{ablation} (×{r['n_runs']})"
        if len(ablation) > 80:
            ablation = ablation[:77] + "…"
        is_invalid = r["value"] < INVALID_VAL_BPB_FLOOR
        delta_str = "—"
        if r.get("delta_pct") is not None and not is_invalid:
            arrow = "↓" if r["delta_pct"] < 0 else ("↑" if r["delta_pct"] > 0 else "")
            delta_str = f"{arrow}{abs(r['delta_pct']):.1f}%"
        elif is_invalid:
            delta_str = "—"
        status_str = "**INVALID**" if is_invalid else "OK"
        # Build link cell
        link_cell_parts = []
        if r.get("link_href"):
            link_cell_parts.append(f"[{r.get('link_label') or 'open'}]({r['link_href']})")
        if r.get("run_script"):
            link_cell_parts.append(f"[run.sh]({r['run_script']})")
        link_cell = " · ".join(link_cell_parts) if link_cell_parts else "—"
        # Mark invalid val_bpb cell with class hook (used by HTML CSS)
        val_str = f"{r['value']:.4f}"
        if is_invalid:
            val_str = f"`{val_str}`"  # backtick-wrap renders as <code>, distinct
        out.append(
            f"| **{r['n']}** "
            f"| {r['time'] or '—'} "
            f"| {r['hardware'] or '—'} "
            f"| {ablation} "
            f"| {val_str} "
            f"| {status_str} "
            f"| {delta_str} "
            f"| {link_cell} |"
        )
    return "\n".join(out)


# ---------- main render -----------------------------------------------------

def render_one_day(date: str, metric_override: str | None = None) -> dict:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    records = fetch_day(conn, date)
    if not records:
        sys.exit(f"no artifacts found for {date}")

    by_camp: dict[str, int] = defaultdict(int)
    for r in records:
        by_camp[r["camp"]] += 1

    headline_metric = metric_override or pick_headline_metric(records)
    asset_dir = ASSETS_DIR / date
    asset_dir.mkdir(parents=True, exist_ok=True)

    chart_path = None
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
        chart_path, chart_n = plot_mod.day_chart(
            asset_dir / f"day_chart_{headline_metric}.png",
            date=date,
            records=chart_input,
            metric_name=headline_metric,
            baseline_to_beat=chart_baseline,
            baseline_label="best before today",
        )

    # Header stats — "hours worked" deliberately removed; the chart's time
    # axis already shows the day's exploration trajectory.
    if headline_metric:
        unique_tests, total_dps, variety_pct = tests_variety_pct(records, headline_metric)
    else:
        unique_tests = total_dps = 0
        variety_pct = 0.0

    biggest_source = max(set(r["source_label"] for r in records),
                          key=lambda s: sum(1 for r in records if r["source_label"] == s))

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
    test_table_md = make_test_table_md(test_rows, headline_metric or "metric", chart_baseline)

    # Compute day index across the corpus (Day 1, Day 12, etc.)
    day_index = compute_day_index(conn, date)

    # ---- Report header (USGC machine-report style) ----
    # Allocation summary
    exp_n = by_camp.get("experimental", 0)
    neu_n = by_camp.get("neural", 0)
    alloc = (f"EXPERIMENTAL {100*exp_n/(exp_n+neu_n):.0f}% / "
             f"NEURAL {100*neu_n/(exp_n+neu_n):.0f}%") if (exp_n+neu_n) else "—"
    invalid_count = sum(1 for r in test_rows if r["value"] < INVALID_VAL_BPB_FLOOR)
    valid_count = len(test_rows) - invalid_count
    # NOTE: validity floor is a project-wide convention shown only on the
    # chart (the red zone). TOP SOURCE and the standalone ALLOCATION row were
    # dropped per design feedback — the experimental/neural % is now inline
    # inside the LAST (CLASSIFICATION) row as a 30px allocation bar.
    arch_families = detect_arch_families(test_rows)
    header_fields = [
        ("DATE", date),
        ("DAY", f"{day_index:03d}" if day_index else "—"),
        ("PRIMARY METRIC", (headline_metric or "—").upper()),
        ("TESTS RUN", f"{len(test_rows)} unique  ({valid_count} valid / {invalid_count} below floor)"),
        ("ARCHITECTURE FAMILY", format_arch_families(arch_families)),
        ("CLASSIFICATION", ""),  # placeholder — alloc bar replaces value cell
    ]
    alloc_bar_html = make_alloc_bar_html(by_camp)
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
    if chart_path:
        relp = os.path.relpath(chart_path, QMD_DIR)
        qmd_lines.append(f"![{headline_metric} for {date}]({relp})")
        qmd_lines.append("")
        if spread_table:
            qmd_lines.append(spread_table)
            qmd_lines.append("")
    else:
        qmd_lines.append("_NO HEADLINE METRIC (VAL_BPB / VAL_LOSS) RECORDED ON THIS DATE._")
        qmd_lines.append("")

    test_record_paths = {r["abs_path"] for r in test_rows}
    # Section 3.0 — Daily Grind — removed per design intent (codex sessions
    # still appear in Supporting Files via the camp-stripe list).
    supporting_md = make_supporting_files_md(records, test_record_paths) \
        .replace("## Supporting Files\n\n", "")
    qmd_lines += [
        "## SECTION 2.0 — TEST RUNS",
        "",
        test_table_md,
        "",
        '<div class="supporting-section">',
        "",
        "## SECTION 3.0 — SUPPORTING FILES",
        "",
        supporting_md,
        "",
        '</div>',
        "",
        # JS shim: tag each <li> in supporting-list with data-camp so the CSS
        # pseudo-element renders the right colored stripe. Emitted as a single
        # line so the markdown-to-HTML passthrough doesn't escape the body.
        '<script>(function(){document.querySelectorAll(".supporting-list li")'
        '.forEach(function(li){var s=li.querySelector("strong");'
        'if(!s)return;var t=s.textContent.trim().toLowerCase();'
        'if(t==="experimental"||t==="neural"||t==="daily_grind"){'
        'li.setAttribute("data-camp",t);}});})();</script>',
    ]
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
        s = re.sub(r"_([^_]+)_", r"<em>\1</em>", s)
        return s

    style = """
    /* CLEAN US-GRAPHICS-STYLE DARK MODE
       Charcoal surfaces, neutral whites, single yellow accent. No dither,
       no CRT, no green-tinted ink. Hairline rules; allocation bar inside the
       last header row carries the experimental/neural visual. */
    :root {
      --mono: "Berkeley Mono", "JetBrains Mono", "IBM Plex Mono",
              ui-monospace, "SF Mono", Consolas, "Cascadia Code",
              "DejaVu Sans Mono", "Liberation Mono", "Courier New", monospace;
      --bg:       #111315;
      --surface:  #17191c;
      --rule:     #2a2d31;
      --rule-hi:  #3a3e44;
      --ink:      #d6d8db;
      --ink-hi:   #f4f5f7;
      --ink-mute: #8a8d92;
      --accent:   #e3b341;   /* yellow stripe accent */
      --warn:     #e25a4a;
      --link:     #7ab4ff;
      --data-exp: #3a6e3a;
      --data-neu: #6fbf6f;
    }
    * { box-sizing: border-box; }
    html, body { background: var(--bg); }
    body { font-family: var(--mono); font-size: 13px; line-height: 1.55;
           color: var(--ink);
           max-width: 1180px; margin: 0 auto; padding: 32px 32px 56px; }

    h1 { font-size: 22px; font-weight: 700; letter-spacing: 0.02em;
         text-transform: uppercase; margin: 0 0 18px;
         padding: 0;
         color: var(--ink-hi);
         display: flex; align-items: center; justify-content: space-between;
         gap: 16px; }
    h1 .h1-title { display: inline-flex; align-items: center; gap: 14px; }
    h1 .h1-mark { width: 32px; height: 32px; display: block;
                  opacity: 0.85; filter: brightness(1.1); }
    h1 .h1-date { font-variant-numeric: tabular-nums; color: var(--ink-mute);
                  font-size: 14px; font-weight: 500; letter-spacing: 0.04em; }

    /* Legacy CRT terminal bar — kept in the markup for backwards-compat,
       but suppressed in the clean layout. */
    .terminal-bar { display: none; }

    h2 { font-size: 12px; font-weight: 700; letter-spacing: 0.12em;
         text-transform: uppercase; margin: 36px 0 14px;
         padding: 0 0 8px;
         border-bottom: 1px solid var(--rule-hi);
         color: var(--ink-hi); }
    h3 { font-size: 11.5px; font-weight: 700; letter-spacing: 0.08em;
         text-transform: uppercase; margin: 18px 0 8px; color: var(--ink-hi); }
    p { margin: 8px 0; color: var(--ink); }
    code { font-family: var(--mono); background: transparent;
           padding: 0; border: none;
           color: var(--ink-hi); font-weight: 600; }
    .muted { color: var(--ink-mute); }
    em, i { font-style: normal; color: var(--ink-mute); }
    figure { margin: 16px 0; text-align: center;
             border: 1px solid var(--rule-hi);
             padding: 14px;
             background-color: transparent; }
    figure img { max-width: 100%; height: auto; display: block; margin: 0 auto; }

    /* Report header — flat bordered block, no fill, no dot-leaders. */
    .report-header { border: 1px solid var(--rule-hi);
                     padding: 14px 18px;
                     margin: 0 0 20px;
                     background-color: transparent; }
    .rh-row { display: flex; align-items: baseline;
              padding: 5px 0; font-size: 12.5px; color: var(--ink-hi); }
    .rh-row + .rh-row { border-top: 1px solid var(--rule); }
    .rh-key { white-space: nowrap; font-weight: 500;
              letter-spacing: 0.04em;
              min-width: 220px; color: var(--ink-mute); }
    .rh-dots { display: none; }
    .rh-val { white-space: nowrap; font-weight: 600; color: var(--ink-hi); }

    /* Inline allocation bar inside the CLASSIFICATION row. */
    .rh-row-alloc { align-items: center; padding: 14px 0; }
    .rh-alloc { display: flex; align-items: center; gap: 16px;
                white-space: nowrap; }
    .alloc-bar { display: inline-flex; height: 30px; width: 240px;
                 border: 1px solid var(--rule-hi); background: var(--rule);
                 overflow: hidden; vertical-align: middle; }
    .alloc-seg-exp { background: var(--data-exp); height: 100%; }
    .alloc-seg-neu { background-color: var(--data-neu); height: 100%;
                     background-image: repeating-linear-gradient(
                       45deg,
                       rgba(0,0,0,0.55) 0,
                       rgba(0,0,0,0.55) 3px,
                       transparent 3px,
                       transparent 7px); }
    .alloc-text { display: inline-flex; gap: 10px; font-weight: 600;
                  font-size: 12px; letter-spacing: 0.02em; }
    .alloc-text-exp { color: var(--data-exp); }
    .alloc-text-neu { color: var(--data-neu); }
    .alloc-sep { color: var(--ink-mute); }

    /* Tables — flat bordered, no fill */
    table { border-collapse: collapse; width: 100%; font-size: 12px;
            margin: 10px 0 18px;
            border: 1px solid var(--rule-hi);
            background-color: transparent; }
    th { text-align: left; color: var(--ink-mute); font-weight: 600;
         text-transform: uppercase; letter-spacing: 0.08em;
         padding: 10px 14px;
         background: transparent;
         border-bottom: 1px solid var(--rule-hi);
         font-size: 10.5px; }
    td { padding: 9px 14px;
         border-bottom: 1px solid var(--rule);
         vertical-align: top;
         color: var(--ink);
         background: transparent; }
    tbody tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(255,255,255,0.02); }
    /* INVALID row — clean red tint, no hatch */
    tr.invalid td { color: var(--ink-mute); }
    tr.invalid td:nth-child(5) code { color: var(--warn); font-weight: 700; }
    tr.invalid td:nth-child(6) strong { color: var(--warn); font-weight: 700; }

    /* Lists — wrapped flat bordered block, internal hairlines. */
    ul { padding: 0; list-style: none; margin: 10px 0 18px;
         border: 1px solid var(--rule-hi); }
    li { margin: 0; font-size: 12px; color: var(--ink);
         padding: 9px 14px; border-bottom: 1px solid var(--rule);
         line-height: 1.6; }
    li:last-child { border-bottom: none; }
    li strong { color: var(--ink-hi); font-weight: 600; }

    /* Links — quiet blue, underline on hover */
    a { color: var(--link); text-decoration: none;
        border-bottom: 1px solid transparent; }
    a:hover { border-bottom-color: var(--link); }

    ::selection { background: var(--accent); color: var(--bg); }

    /* Daily summary callout — between section heading and chart */
    .day-summary { display: grid;
        grid-template-columns: 160px 1fr;
        gap: 24px;
        border: 1px solid var(--rule-hi);
        border-left: 4px solid var(--data-exp);
        padding: 18px 22px;
        margin: 14px 0 22px;
        background: rgba(125,255,125,0.03); }
    .day-summary .ds-key {
        font-size: 10.5px; letter-spacing: 0.10em;
        text-transform: uppercase; font-weight: 700;
        color: var(--ink-mute); padding-top: 2px; }
    .day-summary .ds-body p { margin: 0 0 10px; }
    .day-summary .ds-body p:last-child { margin-bottom: 0; }
    .day-summary strong { color: var(--ink-hi); font-weight: 600; }

    /* val_bpb spread per family table */
    .bpb-table { width: auto; min-width: 480px; }
    .bpb-table td { font-variant-numeric: tabular-nums; }
    .bpb-table td:first-child { font-weight: 600; color: var(--ink-hi); }
    .bpb-table td:not(:first-child),
    .bpb-table th:not(:first-child) { text-align: right; }

    /* Supporting files — left camp indicator stripe + vertical guideline */
    .supporting-section { position: relative; padding-left: 22px; }
    .supporting-section::before {
        content: ""; position: absolute;
        left: 3px; top: 0; bottom: 0;
        width: 1px;
        background: var(--rule-hi); opacity: 0.5;
    }
    .supporting-section > h2 { margin-left: 0; }
    .supporting-list { list-style: none; padding-left: 0; margin-left: 0;
                       border: 1px solid var(--rule-hi); }
    .supporting-list li {
        position: relative;
        padding: 9px 14px 9px 36px;
        border-left: none;
        border-bottom: 1px solid var(--rule);
        margin: 0;
        list-style: none;
    }
    .supporting-list li:last-child { border-bottom: none; }
    .supporting-list li::before {
        content: ""; position: absolute;
        left: 6px; top: 7px; bottom: 7px;
        width: 8px;
        background: var(--ink-mute);
    }
    .supporting-list li[data-camp="experimental"]::before {
        background: var(--data-exp);
    }
    .supporting-list li[data-camp="neural"]::before {
        background: var(--data-neu);
        background-image: repeating-linear-gradient(
            45deg,
            rgba(0,0,0,0.55) 0,
            rgba(0,0,0,0.55) 2px,
            transparent 2px,
            transparent 5px);
    }
    """
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
        + "</body></html>"
    )
    html_path.write_text(full_html)

    return {
        "date": date,
        "qmd_path": str(qmd_path),
        "html_path": str(html_path),
        "asset_dir": str(asset_dir),
        "n_records": len(records),
        "by_camp": dict(by_camp),
        "biggest_source": biggest_source,
        "headline_metric": headline_metric,
        "chart_n_points": chart_n,
        "chart_baseline_to_beat": chart_baseline,
        "unique_tests": unique_tests,
        "total_datapoints": total_dps,
        "variety_pct": variety_pct,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--metric", default=None, help="Override headline metric")
    args = ap.parse_args()
    print(json.dumps(render_one_day(args.date, metric_override=args.metric), indent=2))


if __name__ == "__main__":
    main()
