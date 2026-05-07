#!/usr/bin/env python3
"""Render the campaign table of contents."""

from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path
from typing import Any

import render_week
from render_day import (
    DAILY_TEMPLATE_STANDARD,
    HTML_DIR,
    LOCKED_TEMPLATE_STYLE_SHA256,
    OUT_ROOT,
    RESEARCH_END_DATE,
    RESEARCH_START_DATE,
    _daily_template_style,
    _frosted_flake_data_uri,
    make_report_header_html,
)


TOC_TEMPLATE_STANDARD = "toc-v1.0-campaign-navigation"
TOC_QMD_DIR = OUT_ROOT / "toc"
TOC_HTML_PATH = HTML_DIR / "toc.html"
TOC_BACKGROUND_PATH = Path("assets/toc_background_generated.png")


def image_data_uri(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")


def toc_extra_style() -> str:
    bg = image_data_uri(TOC_BACKGROUND_PATH) if TOC_BACKGROUND_PATH.exists() else ""
    if not bg:
        return ""
    return f"""
    body.toc-page {{
      max-width: 1280px;
      background-image:
        linear-gradient(rgba(137,56,14,0.74), rgba(137,56,14,0.82)),
        url('{bg}');
      background-size: cover;
      background-position: center top;
      background-attachment: fixed;
    }}
    body.toc-page .report-header,
    body.toc-page table,
    body.toc-page .day-summary {{
      background: rgba(137,56,14,0.88);
      backdrop-filter: none;
    }}
    body.toc-page .toc-kicker {{
      margin: -6px 0 18px;
      color: var(--accent);
      font-size: 10.5px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      font-weight: 700;
    }}
    """


def make_layer_table(dates: list[str],
                     week_summaries: list[dict[str, Any]],
                     category_summaries: list[dict[str, Any]],
                     campaign_summary: dict | None) -> str:
    rows = [
        "<table class='test-runs-table'><thead><tr>"
        "<th>LAYER</th><th>COUNT</th><th>OPEN</th><th>FUNCTION</th>"
        "</tr></thead><tbody>"
    ]
    campaign_layer = (
        "CAMPAIGN CUMULATIVE",
        "1",
        "cumulative.html",
        "classification overlay plus campaign facts",
    )
    if campaign_summary:
        campaign_layer = (
            "CAMPAIGN CUMULATIVE",
            f"{campaign_summary.get('chart_panels', 0)} panels",
            "cumulative.html",
            f"{campaign_summary.get('n_points', 0)} category datapoints overlaid by metric",
        )
    layers = [
        ("PUBLICATION COVER", "1", "cover.html", "first page; cover image appears there only"),
        ("TABLE OF CONTENTS", "1", "toc.html", "navigation and reading order"),
        campaign_layer,
        ("CATEGORY REPORTS", str(len(category_summaries)), "categories/index.html", "experimental, neural, and kernel drilldowns"),
        ("WEEKLY REPORTS", str(len(week_summaries)), "weeks/index.html", "7-day daily-report rollups"),
        ("DAILY REPORTS", str(len(dates)), f"{dates[0]}.html", "one locked evidence page per campaign day"),
        ("FINAL SUBMISSION", "MOCKINGBIRD", f"{RESEARCH_END_DATE}.html", "final campaign day and submitted Mockingbird evidence"),
    ]
    for label, count, href, function in layers:
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(label)}</strong></td>"
            f"<td>{html.escape(str(count))}</td>"
            f"<td><a href='{html.escape(href)}'>open</a></td>"
            f"<td>{html.escape(function)}</td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def make_week_table(week_summaries: list[dict[str, Any]]) -> str:
    rows = [
        "<table class='test-runs-table'><thead><tr>"
        "<th>WEEK</th><th>DATES</th><th>DAYS</th><th>METRIC</th>"
        "<th>CLASSIFICATION</th><th>OPEN</th>"
        "</tr></thead><tbody>"
    ]
    for week in week_summaries:
        dates = week["dates"]
        rows.append(
            "<tr>"
            f"<td><strong>WEEK {int(week['week']):02d}</strong></td>"
            f"<td>{html.escape(dates[0])} to {html.escape(dates[-1])}</td>"
            f"<td>{int(week['n_days'])} ({int(week['n_measured_days'])} measured)</td>"
            f"<td>{html.escape(week.get('primary_metric_display') or '—')}</td>"
            f"<td>{html.escape(render_week.format_camp_counts(week.get('by_camp')))}</td>"
            f"<td><a href='weeks/{html.escape(Path(week['html_path']).name)}'>open week</a></td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def make_category_table(category_summaries: list[dict[str, Any]]) -> str:
    rows = [
        "<table class='test-runs-table'><thead><tr>"
        "<th>CATEGORY</th><th>ACTIVE DAYS</th><th>DATAPOINTS</th>"
        "<th>WINDOWS</th><th>CHART PANELS</th><th>OPEN</th>"
        "</tr></thead><tbody>"
    ]
    for category in category_summaries:
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(category['label'])}</strong></td>"
            f"<td>{int(category.get('active_days') or 0)}</td>"
            f"<td>{int(category.get('n_points') or 0)}</td>"
            f"<td>{int(category.get('windows_active') or 0)} / {int(category.get('windows_total') or 0)}</td>"
            f"<td>{int(category.get('chart_panels') or 0)}</td>"
            f"<td><a href='categories/{html.escape(Path(category['html_path']).name)}'>open category</a></td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def make_daily_table(dates: list[str], days_summary: list[dict[str, Any]]) -> str:
    by_date = {d["date"]: d for d in days_summary}
    rows = [
        "<table class='test-runs-table'><thead><tr>"
        "<th>DAY</th><th>DATE</th><th>PRIMARY METRIC</th><th>VALUE</th>"
        "<th>CLASSIFICATION</th><th>OPEN</th>"
        "</tr></thead><tbody>"
    ]
    for idx, date in enumerate(dates, start=1):
        day = by_date.get(date, {})
        camps = render_week.format_camp_counts(day.get("by_camp"))
        rows.append(
            "<tr>"
            f"<td><strong>{idx:03d}</strong></td>"
            f"<td>{html.escape(date)}</td>"
            f"<td>{html.escape(day.get('headline_metric_display') or '—')}</td>"
            f"<td>{html.escape(day.get('best_headline_value_display') or '—')}</td>"
            f"<td>{html.escape(camps)}</td>"
            f"<td><a href='{html.escape(date)}.html'>open day</a></td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def make_summary_html(dates: list[str],
                      week_summaries: list[dict[str, Any]],
                      category_summaries: list[dict[str, Any]],
                      campaign_summary: dict | None) -> str:
    category_points = sum(int(c.get("n_points") or 0) for c in category_summaries)
    campaign_points = int(campaign_summary.get("n_points") or 0) if campaign_summary else category_points
    body = (
        f"<p>This table of contents maps the full campaign publication: "
        f"<strong>{len(dates)} daily reports</strong>, "
        f"<strong>{len(week_summaries)} weekly reports</strong>, "
        f"<strong>{len(category_summaries)} category reports</strong>, and "
        f"<strong>1 campaign cumulative report</strong>.</p>"
        f"<p>The report set spans <strong>{RESEARCH_START_DATE}</strong> through "
        f"<strong>{RESEARCH_END_DATE}</strong>, ending with "
        f"<strong>Mockingbird</strong>. The cumulative layer carries "
        f"<strong>{campaign_points}</strong> category-local datapoints.</p>"
        f"<p>The cover page is first in the sequence. The cover image is "
        f"reserved for <strong>cover.html</strong> only; this TOC uses a "
        f"separate generated dossier background for navigation.</p>"
    )
    return (
        '<aside class="day-summary">'
        '<div class="ds-key">READING ORDER</div>'
        f'<div class="ds-body">{body}</div></aside>'
    )


def render_toc_report(dates: list[str],
                      days_summary: list[dict[str, Any]],
                      week_summaries: list[dict[str, Any]],
                      category_summaries: list[dict[str, Any]],
                      campaign_summary: dict | None = None) -> dict[str, Any]:
    if not dates:
        raise SystemExit("cannot render TOC without campaign dates")
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    TOC_QMD_DIR.mkdir(parents=True, exist_ok=True)
    header_fields = [
        ("DOCUMENT", "PARAMETER GOLF CAMPAIGN"),
        ("DATES", f"{RESEARCH_START_DATE} TO {RESEARCH_END_DATE}"),
        ("DAILY REPORTS", str(len(dates))),
        ("WEEKLY REPORTS", str(len(week_summaries))),
        ("CATEGORY REPORTS", str(len(category_summaries))),
        ("FINAL", "MOCKINGBIRD"),
    ]
    h1_html = (
        '<h1>'
        '<span class="h1-title">'
        '<img class="h1-mark" src="' + _frosted_flake_data_uri() + '" alt="">'
        '<span>TABLE OF CONTENTS</span>'
        '</span>'
        '<span class="h1-date">CAMPAIGN</span>'
        '</h1>'
    )
    report_header = make_report_header_html(header_fields)
    summary_html = make_summary_html(
        dates, week_summaries, category_summaries, campaign_summary
    )
    layer_table = make_layer_table(dates, week_summaries, category_summaries, campaign_summary)
    category_table = make_category_table(category_summaries)
    week_table = make_week_table(week_summaries)
    daily_table = make_daily_table(dates, days_summary)

    body_parts = [
        h1_html,
        "<div class='toc-kicker'>PARAMETER GOLF CAMPAIGN / NAVIGATION INDEX</div>",
        report_header,
        "<h2>SECTION 1.0 — PUBLICATION MAP</h2>",
        summary_html,
    ]
    body_parts.extend([
        layer_table,
        "<h2>SECTION 2.0 — REPORT INDEX</h2>",
        "<h3>CAMPAIGN AND CATEGORY REPORTS</h3>",
        category_table,
        "<h3>WEEKLY REPORTS</h3>",
        week_table,
        "<h3>DAILY REPORTS</h3>",
        daily_table,
    ])

    full_html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Table of Contents</title>"
        f"<style>{_daily_template_style()}{toc_extra_style()}</style></head><body class='toc-page'>"
        + "\n".join(body_parts)
        + "</body></html>"
    )
    TOC_HTML_PATH.write_text(full_html, encoding="utf-8")

    qmd_lines = [
        h1_html,
        "",
        report_header,
        "",
        "## SECTION 1.0 — PUBLICATION MAP",
        "",
        summary_html,
        "",
        layer_table,
        "",
        "## SECTION 2.0 — REPORT INDEX",
        "",
        "### CAMPAIGN AND CATEGORY REPORTS",
        "",
        category_table,
        "",
        "### WEEKLY REPORTS",
        "",
        week_table,
        "",
        "### DAILY REPORTS",
        "",
        daily_table,
        "",
    ]
    qmd_path = TOC_QMD_DIR / "toc.qmd"
    qmd_path.write_text("\n".join(qmd_lines), encoding="utf-8")

    return {
        "html_path": str(TOC_HTML_PATH),
        "qmd_path": str(qmd_path),
        "template_standard": TOC_TEMPLATE_STANDARD,
        "daily_template_standard": DAILY_TEMPLATE_STANDARD,
        "template_style_sha256": LOCKED_TEMPLATE_STYLE_SHA256,
        "background_path": str(TOC_BACKGROUND_PATH) if TOC_BACKGROUND_PATH.exists() else "",
        "n_days": len(dates),
        "n_weeks": len(week_summaries),
        "n_categories": len(category_summaries),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    import render_all
    import render_campaign
    import render_category as render_category_mod

    conn = render_all.sqlite3.connect(render_all.DB)
    conn.row_factory = render_all.sqlite3.Row
    try:
        dates = render_all.all_dates_with_artifacts(conn)
    finally:
        conn.close()
    days_summary = []
    for date in dates:
        # Avoid re-rendering in standalone mode when possible; render_all is
        # the canonical path. Standalone mode keeps a light summary table.
        days_summary.append({"date": date, "by_camp": {}})
    week_summaries = render_week.render_all_weeks(dates)
    category_summaries = render_category_mod.render_all_categories(dates)
    campaign_summary = render_campaign.render_campaign_report(
        dates, week_summaries, category_summaries
    )
    print(json.dumps(
        render_toc_report(
            dates, days_summary, week_summaries, category_summaries,
            campaign_summary,
        ),
        indent=2,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
