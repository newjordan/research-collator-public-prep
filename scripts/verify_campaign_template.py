#!/usr/bin/env python3
"""Verify campaign cumulative report page."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import render_campaign  # noqa: E402
import render_category  # noqa: E402
import render_day  # noqa: E402


LEAK_RE = re.compile(
    r"CONVERSATION-MINED|conversation_architecture|conversation_arch_event|"
    r"claude_session|codex_session",
    re.IGNORECASE,
)


def _require_footer(text: str, html_path: Path) -> None:
    if text.count('class="report-footer"') != 1:
        raise AssertionError(f"missing canonical black report footer: {html_path}")
    for marker in ("rf-dotgrid", "rf-eye", "rf-bars"):
        if marker not in text:
            raise AssertionError(f"footer micro-graphic {marker!r} missing: {html_path}")


def verify_campaign(summary: dict) -> dict:
    html_path = Path(summary["html_path"])
    if not html_path.exists():
        raise AssertionError(f"missing campaign cumulative html: {html_path}")
    text = html_path.read_text(encoding="utf-8", errors="replace")

    if "CAMPAIGN CUMULATIVE REPORT" not in text:
        raise AssertionError(f"missing campaign h1 marker: {html_path}")
    _require_footer(text, html_path)
    if text.count("<h2>") != 2:
        raise AssertionError(
            f"campaign page must have exactly two h2 sections: {html_path}"
        )
    for heading in (
        "SECTION 1.0 — CLASSIFICATION OVERLAY",
        "SECTION 2.0 — CAMPAIGN INDEX",
    ):
        if heading not in text:
            raise AssertionError(f"missing campaign heading {heading!r}: {html_path}")
    for marker in ("report-header", "day-summary", "test-runs-table"):
        if marker not in text:
            raise AssertionError(
                f"campaign page missing locked visual block {marker!r}: {html_path}"
            )
    for label in ("EXPERIMENTAL", "NEURAL", "KERNEL"):
        if label not in text:
            raise AssertionError(
                f"campaign page missing classification label {label}: {html_path}"
            )
    for href in ("weeks/index.html", "categories/index.html", "2026-05-01.html"):
        if href not in text:
            raise AssertionError(
                f"campaign page missing report link {href}: {html_path}"
            )
    if "MONTHLY" in text.upper():
        raise AssertionError(f"campaign page contains monthly marker: {html_path}")
    if LEAK_RE.search(text):
        raise AssertionError(
            f"conversation/session material leaked into campaign page: {html_path}"
        )

    figures = text.count("<figure>")
    if figures != int(summary.get("chart_panels") or 0):
        raise AssertionError(
            f"campaign chart count mismatch for {html_path}: "
            f"figures={figures} chart_panels={summary['chart_panels']}"
        )
    if int(summary.get("chart_panels") or 0) < 1:
        raise AssertionError(f"campaign page must render at least one overlay chart: {html_path}")
    if int(summary.get("n_points") or 0) < 1:
        raise AssertionError(f"campaign page has no category datapoints: {html_path}")
    return {
        "html_path": str(html_path),
        "chart_panels": figures,
        "datapoints": int(summary.get("n_points") or 0),
        "metrics": summary.get("metrics_used") or [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-render", action="store_true",
                        help="verify existing campaign page without refreshing it")
    args = parser.parse_args()

    render_day._daily_template_style()
    if args.no_render:
        summary = {
            "html_path": str(render_campaign.CAMPAIGN_HTML_PATH),
            "chart_panels": render_campaign.CAMPAIGN_HTML_PATH.read_text(
                encoding="utf-8", errors="replace"
            ).count("<figure>"),
            "n_points": 1,
            "metrics_used": [],
        }
    else:
        conn = sqlite3.connect(render_day.DB)
        conn.row_factory = sqlite3.Row
        try:
            dates = render_campaign.all_campaign_dates(conn)
        finally:
            conn.close()
        summary = render_campaign.render_campaign_report(dates)

    checked = verify_campaign(summary)
    result = {
        "template_standard": render_campaign.CAMPAIGN_TEMPLATE_STANDARD,
        "category_template_standard": render_category.CATEGORY_TEMPLATE_STANDARD,
        "daily_template_standard": render_day.DAILY_TEMPLATE_STANDARD,
        "template_style_sha256": render_day.LOCKED_TEMPLATE_STYLE_SHA256,
        "checked": checked,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
