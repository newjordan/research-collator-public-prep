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


def verify_html(
    date: str,
    html_path: Path,
    expect_tests: bool,
    expect_logs: bool,
    expected_recipe_names: list[str] | None = None,
) -> dict:
    expected_recipe_names = expected_recipe_names or []
    raw = html_path.read_text(encoding="utf-8")
    body = raw
    if "</style></head><body>" in raw:
        body = raw.split("</style></head><body>", 1)[1]
    if "</body></html>" in body:
        body = body.rsplit("</body></html>", 1)[0]
    upper = body.upper()

    require("SECTION 1.0 — TRAJECTORY" in body, f"{date}: missing Section 1.0")
    require("SECTION 2.0 — TEST RUNS" in body, f"{date}: missing Section 2.0")
    require("Architecture tested:" in body,
            f"{date}: daily summary must lead with architecture reference text")
    require("SECTION 3.0" not in upper, f"{date}: Section 3.0 leaked into body")
    require("SUPPORTING FILES" not in upper, f"{date}: supporting files leaked into body")
    require("CONVERSATION-MINED" not in upper, f"{date}: conversation-mined section leaked into body")
    require("ARCH-EVENTS-TABLE" not in body, f"{date}: conversation event table leaked into body")
    require("CONVERSATION_ARCHITECTURE" not in upper, f"{date}: conversation ledger path leaked into body")
    require("CLAUDE_SESSION" not in upper and "CODEX_SESSION" not in upper,
            f"{date}: raw chat-session kind leaked into body")
    require("report-footer" not in raw and "rf-dotgrid" not in raw and "body::after" not in raw,
            f"{date}: removed footer or bottom treatment leaked back into page")
    require('class="h1-home" href="index.html" aria-label="Open landing page"' in body,
            f"{date}: frostmark is not linked to landing page")
    require('class="h1-master" href="toc.html"' in body and "BACK TO MASTER SHEET" in body,
            f"{date}: missing daily back link to master sheet")
    recipe_match = re.search(
        r'<section class="architecture-recipe".*?</section>',
        body,
        flags=re.DOTALL,
    )
    if expected_recipe_names:
        require(recipe_match is not None, f"{date}: missing architecture recipe block")
        require("ARCHITECTURE RECIPE" in body, f"{date}: missing architecture recipe label")
        recipe_text = recipe_match.group(0).upper() if recipe_match else ""
        for name in expected_recipe_names:
            require(name.upper() in recipe_text,
                    f"{date}: missing architecture recipe for {name}")
        for forbidden in ("PROVENANCE", "LINEAGE", "SOURCE", "PARENT", "SHA256"):
            require(forbidden not in recipe_text,
                    f"{date}: architecture recipe leaked {forbidden}")
        section_1_pos = body.find("SECTION 1.0 — TRAJECTORY")
        require(section_1_pos >= 0 and recipe_match.start() < section_1_pos,
                f"{date}: architecture recipe must render before Section 1.0")
    if date == render_day.RESEARCH_END_DATE:
        require(recipe_match is not None, f"{date}: final day missing architecture recipe")
        recipe_text = recipe_match.group(0).upper() if recipe_match else ""
        for needle in (
            "10K-VOCAB CASEOPS LOOP BODY",
            "MLP_MULT=3.75",
            "SP10240",
            "PHASED LORA TTT",
            "CHUNK=48",
        ):
            require(needle in recipe_text,
                    f"{date}: final submission recipe missing {needle}")
    for forbidden in (
        "figure::before",
        "figure::after",
        ".report-header::before",
        ".report-header::after",
        ".day-summary::before",
        ".day-summary::after",
        ".log-panel::before",
        ".log-panel::after",
    ):
        require(forbidden not in raw,
                f"{date}: noisy corner micrographic selector leaked back: {forbidden}")
    if expect_tests:
        require("class='test-runs-table'" in body, f"{date}: missing canonical test table")
        require("details class='log-toggle'" in body, f"{date}: missing Section 2 dropdown toggle")
        require("tr class='log-detail-row'><td colspan='8'>" in body,
                f"{date}: Section 2 dropdown panel is not full-table-width")
        data_rows = re.findall(
            r"<tr(?: class=\"invalid\")?><td><strong>\d+</strong></td>.*?</tr>",
            body,
            flags=re.DOTALL,
        )
        detail_rows = body.count("tr class='log-detail-row'><td colspan='8'>")
        require(detail_rows == len(data_rows),
                f"{date}: every Section 2 row must have a full-width dropdown panel")
    require(body.count("<h2>SECTION ") == 2, f"{date}: expected exactly two top sections")

    if expect_logs:
        require("details class='log-toggle'" in body, f"{date}: missing training-log toggle")
        require("tr class='log-detail-row'><td colspan='8'>" in body,
                f"{date}: training log panel is not full-table-width")
        require("<script>(function(){function sync(d)" in body,
                f"{date}: missing disclosure sync script")

        require("<pre class='log-text'>" in body,
                f"{date}: no full training-log text found in dropdown panels")

    return {
        "date": date,
        "html_path": str(html_path),
        "tests_expected": expect_tests,
        "logs_expected": expect_logs,
        "architecture_recipes": expected_recipe_names,
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
        recipe_book = render_day.load_architecture_recipes()
        expected_recipe_names = []
        for family in result.get("arch_families", []):
            name = family.get("name")
            recipe = recipe_book.get(name)
            if not recipe:
                continue
            expected_recipe_names.append(
                str(recipe.get("display") or render_day.public_arch_label(name))
            )
        checked.append(verify_html(
            date,
            html_path,
            expect_tests=bool(result.get("unique_tests", 0)),
            expect_logs=bool(result.get("n_training_log_rows", 0)),
            expected_recipe_names=expected_recipe_names,
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
