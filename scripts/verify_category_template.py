#!/usr/bin/env python3
"""Verify category cumulative report pages.

This guards the wrapper around the locked daily visual system: each category
page must keep two main sections, locked daily CSS blocks, no global-aggregate
markers, no conversation/session leaks, and the canonical biweekly windowing.
Scientific row provenance lives in `audit_daily_accuracy.py`.
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

import render_category  # noqa: E402
import render_day  # noqa: E402
import render_week  # noqa: E402


LEAK_RE = re.compile(
    r"CONVERSATION-MINED|conversation_architecture|conversation_arch_event|"
    r"claude_session|codex_session",
    re.IGNORECASE,
)

FORBIDDEN_GLOBAL_MARKERS = (
    "MONTHLY",
    "BEST EVER",
    "RUNNING BEST",
    "PRIOR WEEK",
    "<th>median</th>",
)


def _require_clean_bottom(text: str, html_path: Path) -> None:
    if "report-footer" in text or "rf-dotgrid" in text or "body::after" in text:
        raise AssertionError(f"removed footer or bottom treatment leaked back into page: {html_path}")


def _require_home_link(text: str, html_path: Path) -> None:
    if 'class="h1-home" href="../index.html" aria-label="Open landing page"' not in text:
        raise AssertionError(f"frostmark is not linked to landing page: {html_path}")


def _require_native_controls(text: str, html_path: Path) -> None:
    required = (
        "scrollbar-color: var(--rule-hi) var(--bg);",
        "::-webkit-scrollbar-thumb",
        ".log-toggle summary::-webkit-details-marker { display: none; }",
        ".log-toggle summary::before",
    )
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise AssertionError(
            f"native controls are missing flat locked styling in {html_path}: {missing}"
        )


def _verify_index(html_path: Path) -> dict:
    if not html_path.exists():
        raise AssertionError(f"missing category index html: {html_path}")
    text = html_path.read_text(encoding="utf-8", errors="replace")
    if "CATEGORY RESEARCH REPORTS" not in text:
        raise AssertionError(f"missing category index h1 marker: {html_path}")
    _require_clean_bottom(text, html_path)
    _require_home_link(text, html_path)
    _require_native_controls(text, html_path)
    if text.count("<h2>") != 2:
        raise AssertionError(
            f"category index must have exactly two h2 sections: {html_path}"
        )
    for heading in (
        "SECTION 1.0 — CATEGORY INDEX",
        "SECTION 2.0 — CATEGORY REPORTS",
    ):
        if heading not in text:
            raise AssertionError(
                f"missing category index heading {heading!r}: {html_path}"
            )
    if "report-header" not in text or "test-runs-table" not in text:
        raise AssertionError(
            f"category index missing locked daily visual blocks: {html_path}"
        )
    for forbidden in FORBIDDEN_GLOBAL_MARKERS:
        if forbidden in text:
            raise AssertionError(
                f"category index contains forbidden global marker {forbidden!r}: {html_path}"
            )
    if LEAK_RE.search(text):
        raise AssertionError(
            f"conversation/session material leaked into category index: {html_path}"
        )
    if "MONTHLY" in text.upper():
        raise AssertionError(
            f"category index contains forbidden monthly marker: {html_path}"
        )
    return {"html_path": str(html_path)}


def _verify_category(summary: dict) -> dict:
    html_path = Path(summary["html_path"])
    if not html_path.exists():
        raise AssertionError(f"missing category html: {html_path}")
    text = html_path.read_text(encoding="utf-8", errors="replace")

    if "RESEARCH REPORT" not in text:
        raise AssertionError(f"missing category h1 marker: {html_path}")
    _require_clean_bottom(text, html_path)
    _require_home_link(text, html_path)
    _require_native_controls(text, html_path)
    if text.count("<h2>") != 2:
        raise AssertionError(
            f"category page must have exactly two h2 sections: {html_path}"
        )
    for heading in (
        "SECTION 1.0 — BI-WEEKLY TRAJECTORY",
        "SECTION 2.0 — CATEGORY DAILY DATAPOINTS",
    ):
        if heading not in text:
            raise AssertionError(
                f"missing category heading {heading!r}: {html_path}"
            )
    if "report-header" not in text:
        raise AssertionError(
            f"category page missing locked report-header block: {html_path}"
        )
    if "day-summary" not in text:
        raise AssertionError(
            f"category page missing locked day-summary block: {html_path}"
        )
    if "test-runs-table" not in text:
        raise AssertionError(
            f"category page missing locked test-runs-table block: {html_path}"
        )

    for forbidden in FORBIDDEN_GLOBAL_MARKERS:
        if forbidden in text:
            raise AssertionError(
                f"category page contains forbidden global marker "
                f"{forbidden!r}: {html_path}"
            )
    if LEAK_RE.search(text):
        raise AssertionError(
            f"conversation/session material leaked into category page: {html_path}"
        )

    # Section structure: one window subsection per active window. Each active
    # window must produce ≥1 chart figure.
    figures = text.count("<figure>")
    if figures != int(summary.get("chart_panels") or 0):
        raise AssertionError(
            f"category page chart-panel count mismatch for {html_path}: "
            f"figures={figures} chart_panels={summary['chart_panels']}"
        )

    # Provenance dropdowns are required for measured datapoints. Each datapoint
    # surfaces in BOTH the per-window table and the SECTION-2 master table, so
    # a measured day generates two log-toggle dropdowns.
    if int(summary.get("n_points") or 0) > 0:
        if "details class='log-toggle'" not in text:
            raise AssertionError(
                f"category page missing provenance dropdowns: {html_path}"
            )
        if "log-detail-row" not in text:
            raise AssertionError(
                f"category page missing log-detail-row dropdowns: {html_path}"
            )

    # Hard rule: kernel category never blends BPB metric labels.
    if summary["category"] == "kernel" and "VAL_BPB" in text:
        raise AssertionError(
            f"kernel category page must not blend BPB y-axis: {html_path}"
        )

    return {
        "category": summary["category"],
        "html_path": str(html_path),
        "datapoints": int(summary.get("n_points") or 0),
        "windows_active": int(summary.get("windows_active") or 0),
        "chart_panels": int(summary.get("chart_panels") or 0),
    }


def _no_monthly_outputs() -> None:
    out = render_day.OUT_ROOT
    forbidden_globs = [
        "preview/months",
        "months",
        "preview/monthly",
        "monthly",
    ]
    leaks = [str(out / g) for g in forbidden_globs if (out / g).exists()]
    if leaks:
        raise AssertionError(f"monthly outputs are not allowed; found: {leaks}")


def main() -> None:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--category",
                        choices=render_category.CATEGORIES,
                        help="render and verify a single category")
    target.add_argument("--all", action="store_true",
                        help="render and verify all categories")
    args = parser.parse_args()

    render_day._daily_template_style()
    conn = sqlite3.connect(render_day.DB)
    conn.row_factory = sqlite3.Row
    try:
        dates = render_category.all_campaign_dates(conn)
    finally:
        conn.close()

    if args.category:
        windows = render_category.biweekly_windows(dates)
        conn2 = sqlite3.connect(render_day.DB)
        conn2.row_factory = sqlite3.Row
        try:
            summary = render_category.render_category(
                conn2, args.category, dates, windows
            )
        finally:
            conn2.close()
        summaries = [summary]
        # Even single-category runs must keep the index in sync.
        render_category.render_category_index(summaries, windows)
    else:
        summaries = render_category.render_all_categories(dates)

    _no_monthly_outputs()

    checked = [_verify_category(summary) for summary in summaries]
    index_check = _verify_index(render_category.CATEGORY_HTML_DIR / "index.html")

    result = {
        "template_standard": render_category.CATEGORY_TEMPLATE_STANDARD,
        "daily_template_standard": render_day.DAILY_TEMPLATE_STANDARD,
        "weekly_template_standard": render_week.WEEKLY_TEMPLATE_STANDARD,
        "template_style_sha256": render_day.LOCKED_TEMPLATE_STYLE_SHA256,
        "checked_categories": len(checked),
        "index": index_check,
        "categories": checked,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
