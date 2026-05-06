#!/usr/bin/env python3
"""Fail-closed checks for the canonical daily report template.

This is intentionally structural and local. Browser layout audits are still
useful during design work, but this script is the repo-level gate that future
scrape-all-days runs can execute without needing Playwright.
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
import render_all  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"template verification failed: {message}")


def verify_html(date: str, html_path: Path, expect_tests: bool, expect_logs: bool) -> dict:
    raw = html_path.read_text(encoding="utf-8")
    body = raw
    if "</style></head><body>" in raw:
        body = raw.split("</style></head><body>", 1)[1]
    if "</body></html>" in body:
        body = body.rsplit("</body></html>", 1)[0]
    upper = body.upper()

    require("SECTION 1.0 — TRAJECTORY" in body, f"{date}: missing Section 1.0")
    require("SECTION 2.0 — TEST RUNS" in body, f"{date}: missing Section 2.0")
    require("SECTION 3.0" not in upper, f"{date}: Section 3.0 leaked into body")
    require("SUPPORTING FILES" not in upper, f"{date}: supporting files leaked into body")
    if expect_tests:
        require("class='test-runs-table'" in body, f"{date}: missing canonical test table")
    require(body.count("<h2>SECTION ") == 2, f"{date}: expected exactly two top sections")

    if expect_logs:
        require("details class='log-toggle'" in body, f"{date}: missing training-log toggle")
        require("tr class='log-detail-row'><td colspan='8'>" in body,
                f"{date}: training log panel is not full-table-width")
        require("<script>(function(){function sync(d)" in body,
                f"{date}: missing disclosure sync script")

        first_detail = re.search(
            r"<tr class='log-detail-row'><td colspan='8'>(.*?)</td></tr>",
            body,
            flags=re.DOTALL,
        )
        require(first_detail is not None, f"{date}: no detail row body found")
        require("<pre class='log-text'>" in first_detail.group(1),
                f"{date}: full-width detail row does not contain log text")

    return {
        "date": date,
        "html_path": str(html_path),
        "tests_expected": expect_tests,
        "logs_expected": expect_logs,
        "log_toggles": body.count("details class='log-toggle'"),
        "log_detail_rows": body.count("tr class='log-detail-row'"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--date", help="YYYY-MM-DD to render and verify")
    target.add_argument("--all", action="store_true", help="render and verify every artifact date")
    args = parser.parse_args()

    # Forces the locked CSS hash check in render_day.py.
    render_day._daily_template_style()

    if args.all:
        conn = sqlite3.connect(render_day.DB)
        conn.row_factory = sqlite3.Row
        dates = render_all.all_dates_with_artifacts(conn)
        conn.close()
    else:
        dates = [args.date or "2026-03-28"]

    checked: list[dict] = []
    for date in dates:
        try:
            result = render_day.render_one_day(date)
        except SystemExit:
            continue
        html_path = Path(result["html_path"])
        checked.append(verify_html(
            date,
            html_path,
            expect_tests=bool(result.get("unique_tests", 0)),
            expect_logs=bool(result.get("n_training_log_rows", 0)),
        ))

    require(checked, "no daily pages were verified")
    print(json.dumps({
        "template_standard": render_day.DAILY_TEMPLATE_STANDARD,
        "template_style_sha256": render_day.LOCKED_TEMPLATE_STYLE_SHA256,
        "checked_pages": len(checked),
        "sample": checked[:3],
    }, indent=2))


if __name__ == "__main__":
    main()
