#!/usr/bin/env python3
"""Verify weekly report pages.

This checks the weekly wrapper around the locked daily visual system. It does
not judge scientific correctness; `audit_daily_accuracy.py` remains the row
provenance gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import render_day  # noqa: E402
import render_week  # noqa: E402


LEAK_RE = re.compile(
    r"CONVERSATION-MINED|conversation_architecture|conversation_arch_event|"
    r"claude_session|codex_session",
    re.IGNORECASE,
)


def _require_clean_bottom(text: str, html_path: Path) -> None:
    if "report-footer" in text or "rf-dotgrid" in text or "body::after" in text:
        raise AssertionError(f"removed footer or bottom treatment leaked back into page: {html_path}")


def _require_home_link(text: str, html_path: Path) -> None:
    if 'class="h1-home" href="../index.html" aria-label="Open landing page"' not in text:
        raise AssertionError(f"frostmark is not linked to landing page: {html_path}")


def _verify_index(html_path: Path) -> dict:
    if not html_path.exists():
        raise AssertionError(f"missing weekly index html: {html_path}")
    text = html_path.read_text(encoding="utf-8", errors="replace")
    _require_clean_bottom(text, html_path)
    _require_home_link(text, html_path)
    if "WEEKLY RESEARCH REPORTS" not in text:
        raise AssertionError(f"missing weekly index h1 marker: {html_path}")
    if LEAK_RE.search(text):
        raise AssertionError(f"conversation/session material leaked into weekly index: {html_path}")
    return {"html_path": str(html_path)}


def verify_week(summary: dict) -> dict:
    html_path = Path(summary["html_path"])
    if not html_path.exists():
        raise AssertionError(f"missing weekly html: {html_path}")
    text = html_path.read_text(encoding="utf-8", errors="replace")
    if "WEEKLY RESEARCH REPORT" not in text:
        raise AssertionError(f"missing weekly h1 marker: {html_path}")
    _require_clean_bottom(text, html_path)
    _require_home_link(text, html_path)
    if text.count("<h2>") != 2:
        raise AssertionError(f"weekly page must have exactly two h2 sections: {html_path}")
    for heading in ("SECTION 1.0 — WEEK TRAJECTORY", "SECTION 2.0 — DAILY REPORTS"):
        if heading not in text:
            raise AssertionError(f"missing weekly heading {heading!r}: {html_path}")
    if "Architectures tested:" not in text:
        raise AssertionError(f"weekly summary must lead with architecture reference text: {html_path}")
    if "report-header" not in text or "day-summary" not in text:
        raise AssertionError(f"weekly page missing locked daily visual blocks: {html_path}")
    for forbidden in ("BEST DAY", "DAILY METRIC SPREAD", "<th>median</th>", "PRIOR WEEK"):
        if forbidden in text:
            raise AssertionError(f"weekly page contains non-local aggregate marker {forbidden!r}: {html_path}")
    if LEAK_RE.search(text):
        raise AssertionError(f"conversation/session material leaked into weekly page: {html_path}")
    details = text.count("details class='log-toggle'")
    detail_rows = text.count("class='log-detail-row'")
    if details != summary["n_days"] or detail_rows != summary["n_days"]:
        raise AssertionError(
            f"weekly dropdown count mismatch for {html_path}: "
            f"details={details} detail_rows={detail_rows} n_days={summary['n_days']}"
        )
    figures = text.count("<figure>")
    if figures != summary["chart_panels"]:
        raise AssertionError(
            f"weekly chart count mismatch for {html_path}: "
            f"figures={figures} chart_panels={summary['chart_panels']}"
        )
    if "2026-05-01" in summary["dates"]:
        if "10K-VOCAB CASEOPS LOOP BODY (×4)" not in text:
            raise AssertionError(f"final week lost final-submission marker: {html_path}")
        if re.search(r"MIDNIGHT|open_parameter_golf_junkyard", text, re.IGNORECASE):
            raise AssertionError(f"final week contains stale final-day wrong attribution: {html_path}")
    return {
        "week": summary["week"],
        "html_path": str(html_path),
        "days": summary["n_days"],
        "chart_panels": summary["chart_panels"],
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--week", type=int, help="1-based research week")
    target.add_argument("--all", action="store_true", help="render and verify all weeks")
    args = parser.parse_args()

    render_day._daily_template_style()
    conn = sqlite3.connect(render_day.DB)
    conn.row_factory = sqlite3.Row
    try:
        dates = render_week.all_campaign_dates(conn)
    finally:
        conn.close()

    windows = render_week.week_windows(dates)
    if args.week:
        if args.week < 1 or args.week > len(windows):
            raise SystemExit(f"--week must be 1..{len(windows)}")
        summaries = [render_week.render_week(windows[args.week - 1], args.week)]
    else:
        summaries = render_week.render_all_weeks(dates)

    checked = [verify_week(summary) for summary in summaries]
    index_check = _verify_index(render_week.WEEK_HTML_DIR / "index.html")
    result = {
        "template_standard": render_week.WEEKLY_TEMPLATE_STANDARD,
        "daily_template_standard": render_day.DAILY_TEMPLATE_STANDARD,
        "template_style_sha256": render_day.LOCKED_TEMPLATE_STYLE_SHA256,
        "checked_weeks": len(checked),
        "index_path": str(render_week.WEEK_HTML_DIR / "index.html"),
        "index": index_check,
        "sample": checked[:3],
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
