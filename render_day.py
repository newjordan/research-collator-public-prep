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


def extract_test_rows(records: list[dict], metric: str,
                      reference_baseline: float | None) -> list[dict]:
    """One Test Run row per unique title, sorted by RUN TIME (chronological).

    The row number IS the chart number — both reference order is "what got
    tested when". This matches autoresearch trajectory charts: read left to
    right to follow the day's exploration through.
    """
    by_title: dict[str, dict] = {}
    for rec in records:
        vals = extract_metric_for_record(rec.get("metrics_json"), metric)
        if not vals:
            continue
        title = (rec.get("title") or "(untitled)").strip()
        hw_text = " ".join([
            rec.get("title") or "",
            rec.get("summary") or "",
            rec.get("abs_path") or "",
        ])
        wallclock = None
        if rec.get("file_kind") == "json":
            try:
                with open(rec["abs_path"]) as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    wallclock = raw.get("wallclock_seconds") or raw.get("wallclock")
                    if isinstance(raw.get("blurb"), str):
                        hw_text += " " + raw["blurb"]
                    if isinstance(raw.get("name"), str) and len(raw["name"]) > len(title):
                        title = raw["name"][:160]
            except (OSError, json.JSONDecodeError):
                pass

        # Hardware: also pull n_ranks from training_log metrics
        hardware = detect_hardware(hw_text)
        if not hardware and rec.get("file_kind") == "training_log":
            try:
                md = json.loads(rec.get("metrics_json") or "{}")
                n_ranks = md.get("n_ranks")
                if isinstance(n_ranks, int):
                    hardware = f"{n_ranks}× ranks"
            except json.JSONDecodeError:
                pass

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
        if cur is None or best_val < cur["value"]:
            by_title[title] = {
                "title": title,
                "value": best_val,
                "n_runs": len(vals),
                "time": time_str,
                "time_iso": time_iso,
                "hardware": hardware,
                "wallclock_seconds": wallclock,
                "camp": rec["camp"],
                "source_label": rec["source_label"],
                "abs_path": rec["abs_path"],
                "link_label": link_label,
                "link_href": link_href,
                "run_script": run_script,
            }
        else:
            cur["n_runs"] += len(vals)
            if hardware and not cur["hardware"]:
                cur["hardware"] = hardware
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


def compute_day_index(conn: sqlite3.Connection, date: str) -> int | None:
    """Position of `date` in the chronological list of all dates with activity.
    Day 1 = earliest activity in the corpus. Returns None if not found."""
    rows = conn.execute(
        "SELECT abs_path, rel_path, mtime_iso FROM artifacts"
    ).fetchall()
    dates: set[str] = set()
    for r in rows:
        d = best_date(dict(r))
        if d:
            dates.add(d)
    if date not in dates:
        return None
    return sorted(dates).index(date) + 1


def make_report_header_html(fields: list[tuple[str, str]]) -> str:
    """USGC-machine-report-style document header. Dot-leader rows in a
    bordered block, monospace, ALL CAPS keys."""
    rows = []
    for k, v in fields:
        rows.append(
            f'<div class="rh-row"><span class="rh-key">{html.escape(k.upper())}</span>'
            f'<span class="rh-dots"></span>'
            f'<span class="rh-val">{html.escape(v)}</span></div>'
        )
    return '<div class="report-header">' + "".join(rows) + "</div>"


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
    # chart (the red zone) — not a per-day dot-leader field.
    arch_families = detect_arch_families(test_rows)
    header_fields = [
        ("DATE", date),
        ("DAY", f"{day_index:03d}" if day_index else "—"),
        ("CLASSIFICATION", "PARAMETER-GOLF / RESEARCH"),
        ("PRIMARY METRIC", (headline_metric or "—").upper()),
        ("TOP SOURCE", biggest_source.upper()),
        ("TESTS RUN", f"{len(test_rows)} unique  ({valid_count} valid / {invalid_count} below floor)"),
        ("ALLOCATION", alloc),
        ("ARCHITECTURE FAMILY", format_arch_families(arch_families)),
    ]
    report_header = make_report_header_html(header_fields)
    camp_bar = make_camp_bar_html(by_camp)

    # Old-CRT phosphor-green status strip
    n_test = len(test_rows)
    pb_str = (f"PB BAR {chart_baseline:.4f}"
              if chart_baseline is not None else "PB BAR —")
    terminal_bar = (
        '<div class="terminal-bar">'
          '<span class="tb-led"></span>'
          f'<span class="tb-text">SYSTEM ONLINE  ·  '
          f'DAY {day_index:03d}'
          f'  ·  {n_test} TESTS LOGGED  ·  '
          f'{(headline_metric or "—").upper()} '
          f'  ·  {pb_str}</span>'
          '<span class="tb-tail">[READY]</span>'
        '</div>'
    )
    qmd_lines = [
        f"# DAILY RESEARCH REPORT — {date}",
        "",
        terminal_bar,
        "",
        report_header,
        "",
        camp_bar,
        "",
        "## SECTION 1.0 — TRAJECTORY",
        "",
    ]
    if chart_path:
        relp = os.path.relpath(chart_path, QMD_DIR)
        qmd_lines.append(f"![{headline_metric} for {date}]({relp})")
        qmd_lines.append("")
        if chart_baseline is not None:
            qmd_lines.append(
                f"_{chart_n} {headline_metric.upper()} measurements across the day. "
                f"Best before today = {chart_baseline:.4f}. "
                f"Red zone below {INVALID_VAL_BPB_FLOOR:.2f} = known eval errors "
                f"(don't get excited about scores landing in the red)._"
            )
        else:
            qmd_lines.append(f"_{chart_n} {headline_metric.upper()} measurements across the day._")
        qmd_lines.append("")
    else:
        qmd_lines.append("_NO HEADLINE METRIC (VAL_BPB / VAL_LOSS) RECORDED ON THIS DATE._")
        qmd_lines.append("")

    test_record_paths = {r["abs_path"] for r in test_rows}
    qmd_lines += [
        "## SECTION 2.0 — TEST RUNS",
        "",
        test_table_md,
        "",
        "## SECTION 3.0 — DAILY GRIND",
        "",
        grind_md,
        "",
        "## SECTION 4.0 — SUPPORTING FILES",
        "",
        make_supporting_files_md(records, test_record_paths).replace("## Supporting Files\n\n", ""),
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
    /* COHESIVE LATE-80s / EARLY-90s LAB-PROTOCOL PALETTE — DARK CRT MODE
       Strict five-token palette. ONE black, ONE ink, ONE accent (green),
       ONE warning (red), TWO data colors (gold/slate). NO greys. Surface
       differentiation comes from DITHER PATTERNS (45° hatch) on the same BG,
       not subtly-different blacks.                                          */
    :root {
      --mono: "Berkeley Mono", "JetBrains Mono", "IBM Plex Mono",
              ui-monospace, "SF Mono", Consolas, "Cascadia Code",
              "DejaVu Sans Mono", "Liberation Mono", "Courier New", monospace;
      --bg:       #0a0d0a;   /* THE black — used everywhere */
      --ink:      #c8d4c0;   /* paper-white, slightly green */
      --ink-hi:   #f0f4ed;   /* emphasized */
      --accent:   #7dff7d;   /* phosphor green */
      --warn:     #ff5c4a;   /* INVALID red */
      --data-exp: #d8a040;   /* muted gold */
      --data-neu: #6196c4;   /* muted slate */

      /* Dither tokens — repeating diagonal lines for surface differentiation
         without changing the base color. Built from the accent or warn at
         very low alpha. */
      --dither-faint:
        repeating-linear-gradient(45deg,
          transparent 0, transparent 3px,
          rgba(125, 255, 125, 0.04) 3px, rgba(125, 255, 125, 0.04) 4px);
      --dither-soft:
        repeating-linear-gradient(45deg,
          transparent 0, transparent 3px,
          rgba(125, 255, 125, 0.07) 3px, rgba(125, 255, 125, 0.07) 4px);
      --dither-counter:
        repeating-linear-gradient(-45deg,
          transparent 0, transparent 4px,
          rgba(125, 255, 125, 0.05) 4px, rgba(125, 255, 125, 0.05) 5px);
      --dither-warn:
        repeating-linear-gradient(45deg,
          transparent 0, transparent 3px,
          rgba(255, 92, 74, 0.13) 3px, rgba(255, 92, 74, 0.13) 4px);
    }
    * { box-sizing: border-box; }
    html, body { background: var(--bg); }
    body { font-family: var(--mono); font-size: 13px; line-height: 1.45;
           color: var(--ink);
           max-width: 1180px; margin: 0 auto; padding: 28px 28px 48px; }

    /* H1 banner: phosphor-green text on the same BG; differentiated by a
       diagonal dither and a 1px green border. No alternate background. */
    h1 { font-size: 17px; font-weight: 700; letter-spacing: 0.05em;
         text-transform: uppercase; margin: 0;
         padding: 10px 14px;
         border: 1px solid var(--accent);
         border-bottom: none;
         background-color: var(--bg);
         background-image: var(--dither-counter);
         color: var(--accent); }

    /* Phosphor-green CRT status bar */
    .terminal-bar { display: flex; align-items: center;
                    background-color: var(--bg);
                    background-image: var(--dither-soft);
                    border: 1px solid var(--accent);
                    color: var(--accent);
                    padding: 5px 14px;
                    font-size: 11px; font-weight: 700;
                    letter-spacing: 0.12em;
                    text-transform: uppercase;
                    margin: 0 0 16px; }
    .tb-led { display: inline-block; width: 7px; height: 7px;
              background: var(--accent);
              margin-right: 10px; }
    .tb-text { flex: 1; }
    .tb-tail { opacity: 0.78; }

    h2 { font-size: 13px; font-weight: 700; letter-spacing: 0.08em;
         text-transform: uppercase; margin: 28px 0 10px;
         padding: 5px 0 5px 12px;
         border-left: 3px solid var(--accent);
         color: var(--ink-hi); }
    h3 { font-size: 12px; font-weight: 700; letter-spacing: 0.06em;
         text-transform: uppercase; margin: 14px 0 6px; color: var(--ink-hi); }
    p { margin: 6px 0; color: var(--ink); }
    code { font-family: var(--mono); background: var(--bg);
           padding: 0 4px; border: 1px solid var(--accent);
           color: var(--ink-hi); }
    .muted { opacity: 0.55; }
    em, i { font-style: normal; opacity: 0.6; }
    figure { margin: 14px 0; text-align: center;
             border: 1px solid var(--accent);
             padding: 10px;
             background-color: var(--bg); }
    figure img { max-width: 100%; height: auto; display: block; margin: 0 auto; }

    /* Report header — dot-leader rows on dithered surface, no separate bg */
    .report-header { border: 1px solid var(--accent); border-top: none;
                     padding: 12px 16px;
                     margin: 0 0 16px;
                     background-color: var(--bg);
                     background-image: var(--dither-faint); }
    .rh-row { display: flex; align-items: baseline;
              padding: 2px 0; font-size: 12.5px; color: var(--ink); }
    .rh-key { white-space: nowrap; font-weight: 700;
              letter-spacing: 0.05em; text-transform: uppercase;
              min-width: 200px; opacity: 0.55; }
    .rh-dots { flex: 1; min-width: 12px; margin: 0 8px;
               border-bottom: 1px dotted var(--accent); opacity: 0.45;
               transform: translateY(-3px); }
    .rh-val { white-space: nowrap; font-weight: 700; color: var(--ink-hi); }

    /* Camp ratio bar */
    .camp-bar { display: flex; height: 16px; border: 1px solid var(--accent);
                overflow: hidden; margin: 0 0 4px;
                background: var(--bg); }
    .camp-seg-exp { background: var(--data-exp); }
    .camp-seg-neu { background: var(--data-neu); }
    .camp-bar-labels { display: flex; justify-content: space-between;
                       font-size: 11px; margin-bottom: 18px; font-weight: 700;
                       letter-spacing: 0.06em; text-transform: uppercase; }
    .camp-label-exp { color: var(--data-exp); }
    .camp-label-neu { color: var(--data-neu); }

    /* Tables — single bg, accent borders, dither-pattern alt rows. */
    table { border-collapse: collapse; width: 100%; font-size: 11.5px;
            margin: 8px 0 14px;
            border: 1px solid var(--accent);
            background-color: var(--bg); }
    th { text-align: left; color: var(--bg); font-weight: 700;
         text-transform: uppercase; letter-spacing: 0.06em;
         padding: 6px 9px; background: var(--accent);
         border-right: 1px solid var(--bg); }
    th:last-child { border-right: none; }
    td { padding: 5px 9px;
         border-bottom: 1px solid var(--accent);
         border-right: 1px solid var(--accent);
         border-color: rgba(125, 255, 125, 0.18);
         vertical-align: top;
         color: var(--ink);
         background: var(--bg); }
    td:last-child { border-right: none; }
    /* Alt-row diagonal dither — same bg, just a hatch overlay */
    tr:nth-child(even) td { background-image: var(--dither-faint); }
    tr:hover td { background-image: var(--dither-soft); }
    /* INVALID row — warn-color hatch, warn val cell, warn STATUS */
    tr.invalid td { background-image: var(--dither-warn);
                    opacity: 0.85; }
    tr.invalid td:nth-child(5) code { background: var(--bg);
                                       color: var(--warn);
                                       border-color: var(--warn);
                                       font-weight: 700; }
    tr.invalid td:nth-child(6) strong { color: var(--warn); }

    ul { padding-left: 18px; }
    li { margin: 1px 0; font-size: 12px; color: var(--ink); }

    /* Links — accent green, dotted underline, inverts on hover */
    a { color: var(--accent); text-decoration: none;
        border-bottom: 1px dotted var(--accent); }
    a:hover { background: var(--accent); color: var(--bg);
              border-bottom-color: var(--accent); }

    ::selection { background: var(--accent); color: var(--bg); }
    """
    full_html = (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{date} — Research Day</title>"
        f"<style>{style}</style></head><body>"
        + md_to_html("\n".join(qmd_lines))
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
