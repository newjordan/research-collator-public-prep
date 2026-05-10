#!/usr/bin/env python3
"""Render the campaign cumulative report.

This is the rollup above daily, weekly, and category reports. It overlays
classification tracks on homogeneous metric charts, then presents the basic
campaign index/facts in the locked daily visual language.

Usage:
    python3 render_campaign.py
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import plot as plot_mod
import render_category
import render_week
from render_day import (
    ASSETS_DIR,
    DAILY_TEMPLATE_STANDARD,
    DB,
    HTML_DIR,
    LOCKED_TEMPLATE_STYLE_SHA256,
    OUT_ROOT,
    RESEARCH_END_DATE,
    RESEARCH_START_DATE,
    _daily_template_style,
    _embedded_log_script,
    format_metric_value,
    make_alloc_bar_html,
    make_report_h1_html,
    make_report_header_html,
    metric_display_name,
    preview_chart_src,
)


CAMPAIGN_TEMPLATE_STANDARD = "campaign-cumulative-v1.0-classification-overlay"
CAMPAIGN_QMD_DIR = OUT_ROOT / "campaign"
CAMPAIGN_HTML_PATH = HTML_DIR / "cumulative.html"
CAMPAIGN_ASSETS_DIR = ASSETS_DIR / "campaign"


def all_campaign_dates(conn: sqlite3.Connection) -> list[str]:
    return render_week.all_campaign_dates(conn)


def collect_category_points(conn: sqlite3.Connection,
                            dates: list[str]) -> tuple[dict[str, list[dict[str, Any]]],
                                                        list[dict[str, Any]],
                                                        list[dict[str, Any]]]:
    windows = render_category.biweekly_windows(dates)
    by_category: dict[str, list[dict[str, Any]]] = {}
    all_points: list[dict[str, Any]] = []
    for category in render_category.CATEGORIES:
        points = render_category.build_category_datapoints(
            conn, dates, category, windows
        )
        points.sort(key=lambda p: p["date"])
        by_category[category] = points
        all_points.extend(points)
    all_points.sort(key=lambda p: (p["date"], p["category"], p["metric"]))
    return by_category, all_points, windows


def metrics_chrono(points: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    priority = {
        "val_bpb": 0,
        "val_loss": 1,
        "kernel_fb_ratio": 2,
        "kernel_fwd_ratio": 3,
    }
    for p in sorted(points, key=lambda p: (priority.get(p["metric"], 99), p["date"])):
        metric = p["metric"]
        if metric not in seen:
            seen.append(metric)
    return seen


def points_for_metric(points: list[dict[str, Any]],
                      metric: str) -> list[dict[str, Any]]:
    out = []
    for idx, p in enumerate([p for p in points if p["metric"] == metric], start=1):
        out.append({
            "date": p["date"],
            "value": p["value"],
            "camp": p["category"],
            "title": p.get("title") or p["date"],
            "n": idx,
        })
    return out


def render_overlay_charts(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    CAMPAIGN_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    panels: list[dict[str, Any]] = []
    for metric in metrics_chrono(points):
        metric_points = points_for_metric(points, metric)
        if not metric_points:
            continue
        path, n = plot_mod.campaign_overlay_chart(
            CAMPAIGN_ASSETS_DIR / f"cumulative_overlay_{metric}.png",
            campaign_label=f"CAMPAIGN · {RESEARCH_START_DATE} TO {RESEARCH_END_DATE}",
            category_points=metric_points,
            metric_name=metric_display_name(metric),
        )
        panels.append({
            "metric": metric,
            "metric_display": metric_display_name(metric),
            "path": path,
            "n": n,
            "categories": sorted({p["camp"] for p in metric_points}),
        })
    return panels


def category_label(category: str) -> str:
    return render_category.CATEGORY_LABEL.get(category, category.upper())


def make_campaign_summary_html(dates: list[str],
                               by_category: dict[str, list[dict[str, Any]]],
                               points: list[dict[str, Any]],
                               windows: list[dict[str, Any]],
                               chart_panels: list[dict[str, Any]]) -> str:
    active_categories = [
        category for category in render_category.CATEGORIES
        if by_category.get(category)
    ]
    metric_counter = Counter(p["metric"] for p in points)
    metric_text = "  ·  ".join(
        f"{metric_display_name(metric)} (×{count})"
        for metric, count in metric_counter.most_common()
    ) or "—"
    category_text = "  ·  ".join(
        f"{category_label(category)} (×{len(by_category.get(category, []))})"
        for category in active_categories
    ) or "—"
    body = (
        f"<p>This cumulative report covers <strong>{len(dates)} campaign "
        f"days</strong> from <strong>{RESEARCH_START_DATE}</strong> through "
        f"<strong>{RESEARCH_END_DATE}</strong>, with "
        f"<strong>{len(points)} category-local daily datapoints</strong> "
        f"across <strong>{len(active_categories)} active classifications</strong>. "
        f"The graph panels overlay classifications only when the underlying "
        f"metric is shared.</p>"
        f"<p>Classifications: <strong>{html.escape(category_text)}</strong>. "
        f"Metrics: <strong>{html.escape(metric_text)}</strong>. "
        f"Source layers below this page remain daily reports, weekly reports, "
        f"and category reports; this page is the campaign meta layer.</p>"
        f"<p>Rendered graph panels: <strong>{len(chart_panels)}</strong>. "
        f"Two-week category reports remain available for detailed inspection "
        f"while this page shows the whole campaign in one place.</p>"
    )
    return (
        '<aside class="day-summary">'
        '<div class="ds-key">CAMPAIGN SUMMARY</div>'
        f'<div class="ds-body">{body}</div></aside>'
    )


def make_metric_table_html(chart_panels: list[dict[str, Any]],
                           points: list[dict[str, Any]]) -> str:
    rows = [
        "<table class='test-runs-table'><thead><tr>"
        "<th>METRIC</th><th>CLASSIFICATIONS</th><th>DATAPOINTS</th>"
        "<th>DATE RANGE</th><th>MIN OBSERVED BY CLASS</th>"
        "</tr></thead><tbody>"
    ]
    by_metric: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in points:
        by_metric[p["metric"]].append(p)
    for panel in chart_panels:
        metric = panel["metric"]
        metric_points = sorted(by_metric[metric], key=lambda p: p["date"])
        categories = sorted({p["category"] for p in metric_points})
        mins = []
        for category in categories:
            c_points = [p for p in metric_points if p["category"] == category]
            if not c_points:
                continue
            best = min(c_points, key=lambda p: p["value"])
            mins.append(
                f"{category_label(category)} {format_metric_value(metric, best['value'])}"
            )
        rows.append(
            "<tr>"
            f"<td>{html.escape(metric_display_name(metric))}</td>"
            f"<td>{html.escape(' · '.join(category_label(c) for c in categories) or '—')}</td>"
            f"<td>{len(metric_points)}</td>"
            f"<td>{html.escape(metric_points[0]['date'])} to {html.escape(metric_points[-1]['date'])}</td>"
            f"<td>{html.escape(' · '.join(mins) or '—')}</td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def make_campaign_index_table_html(dates: list[str],
                                   by_category: dict[str, list[dict[str, Any]]],
                                   windows: list[dict[str, Any]],
                                   category_summaries: list[dict[str, Any]] | None = None,
                                   week_summaries: list[dict[str, Any]] | None = None) -> str:
    category_summary_by_cat = {
        s.get("category"): s for s in (category_summaries or [])
    }
    report_rows = [
        ("DAILY REPORTS", f"{len(dates)}", "index.html", "one locked page per campaign day"),
        ("WEEKLY REPORTS", f"{len(week_summaries or render_week.week_windows(dates))}",
         "weeks/index.html", "7-day rollups with daily datapoints"),
        ("CATEGORY REPORTS", str(len(render_category.CATEGORIES)),
         "categories/index.html", "experimental / neural / kernel drilldowns"),
        ("FINAL SUBMISSION", "MOCKINGBIRD", f"{RESEARCH_END_DATE}.html",
         f"campaign final day: {RESEARCH_END_DATE}"),
    ]
    rows = [
        "<table class='test-runs-table'><thead><tr>"
        "<th>LAYER</th><th>COUNT</th><th>OPEN</th><th>NOTES</th>"
        "</tr></thead><tbody>"
    ]
    for layer, count, href, notes in report_rows:
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(layer)}</strong></td>"
            f"<td>{html.escape(count)}</td>"
            f"<td><a href='{html.escape(href)}'>open</a></td>"
            f"<td>{html.escape(notes)}</td>"
            "</tr>"
        )
    rows.append("</tbody></table>")

    rows.append(
        "<table class='test-runs-table'><thead><tr>"
        "<th>CLASSIFICATION</th><th>ACTIVE DAYS</th><th>DATAPOINTS</th>"
        "<th>METRICS</th><th>OPEN</th>"
        "</tr></thead><tbody>"
    )
    for category in render_category.CATEGORIES:
        points = by_category.get(category, [])
        metrics = "  ·  ".join(
            metric_display_name(m) for m in Counter(p["metric"] for p in points)
        ) or "—"
        summary = category_summary_by_cat.get(category)
        href = (
            f"categories/{Path(summary['html_path']).name}"
            if summary else f"categories/{category}.html"
        )
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(category_label(category))}</strong></td>"
            f"<td>{len({p['date'] for p in points})}</td>"
            f"<td>{len(points)}</td>"
            f"<td>{html.escape(metrics)}</td>"
            f"<td><a href='{html.escape(href)}'>open category</a></td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def render_campaign_report(dates: list[str] | None = None,
                           week_summaries: list[dict[str, Any]] | None = None,
                           category_summaries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        if dates is None:
            dates = all_campaign_dates(conn)
        by_category, points, windows = collect_category_points(conn, dates)
    finally:
        conn.close()

    CAMPAIGN_QMD_DIR.mkdir(parents=True, exist_ok=True)
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    chart_panels = render_overlay_charts(points)
    by_camp_for_alloc = {
        category: len(points_for_category)
        for category, points_for_category in by_category.items()
        if points_for_category
    }
    metric_counter = Counter(p["metric"] for p in points)
    metric_text = "  ·  ".join(
        f"{metric_display_name(metric)} (×{count})"
        for metric, count in metric_counter.most_common()
    ) or "—"
    header_fields = [
        ("DATES", f"{RESEARCH_START_DATE} TO {RESEARCH_END_DATE}"),
        ("DAILY REPORTS", str(len(dates))),
        ("WEEKLY REPORTS", str(len(week_summaries or render_week.week_windows(dates)))),
        ("CATEGORY REPORTS", str(len(render_category.CATEGORIES))),
        ("DATAPOINTS", str(len(points))),
        ("CLASSIFICATION", "—"),
    ]
    report_header = make_report_header_html(
        header_fields,
        alloc_bar=make_alloc_bar_html(by_camp_for_alloc) if by_camp_for_alloc else None,
    )
    h1_html = make_report_h1_html("CAMPAIGN CUMULATIVE REPORT", "CAMPAIGN")
    summary_html = make_campaign_summary_html(
        dates, by_category, points, windows, chart_panels
    )
    metric_table = make_metric_table_html(chart_panels, points)
    campaign_index_table = make_campaign_index_table_html(
        dates, by_category, windows, category_summaries, week_summaries
    )

    body_parts = [
        h1_html,
        report_header,
        "<h2>SECTION 1.0 — CLASSIFICATION OVERLAY</h2>",
        summary_html,
    ]
    if chart_panels:
        for panel in chart_panels:
            chart_src = preview_chart_src(panel["path"])
            body_parts.append(
                "<figure>"
                f"<img src='{html.escape(chart_src, quote=True)}' "
                f"alt='Campaign classification overlay · "
                f"{html.escape(panel['metric_display'])}'/>"
                "</figure>"
            )
        body_parts.append(metric_table)
    else:
        body_parts.append("<p class='muted'>NO CAMPAIGN DATAPOINTS AVAILABLE.</p>")
    body_parts.extend([
        "<h2>SECTION 2.0 — CAMPAIGN INDEX</h2>",
        campaign_index_table,
    ])

    full_html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Campaign Cumulative Report</title>"
        f"<style>{_daily_template_style()}</style></head><body>"
        + "\n".join(body_parts)
        + _embedded_log_script()
        + "</body></html>"
    )
    CAMPAIGN_HTML_PATH.write_text(full_html, encoding="utf-8")

    qmd_lines = [
        h1_html,
        "",
        report_header,
        "",
        "## SECTION 1.0 — CLASSIFICATION OVERLAY",
        "",
        summary_html,
        "",
    ]
    if chart_panels:
        for panel in chart_panels:
            relp = os.path.relpath(panel["path"], CAMPAIGN_QMD_DIR)
            qmd_lines.append(
                f"![Campaign classification overlay · {panel['metric_display']}]({relp})"
            )
            qmd_lines.append("")
        qmd_lines.append(metric_table)
        qmd_lines.append("")
    else:
        qmd_lines.append("<p class='muted'>NO CAMPAIGN DATAPOINTS AVAILABLE.</p>")
        qmd_lines.append("")
    qmd_lines += [
        "## SECTION 2.0 — CAMPAIGN INDEX",
        "",
        campaign_index_table,
        "",
    ]
    qmd_path = CAMPAIGN_QMD_DIR / "cumulative.qmd"
    qmd_path.write_text("\n".join(qmd_lines), encoding="utf-8")

    return {
        "html_path": str(CAMPAIGN_HTML_PATH),
        "qmd_path": str(qmd_path),
        "asset_dir": str(CAMPAIGN_ASSETS_DIR),
        "template_standard": CAMPAIGN_TEMPLATE_STANDARD,
        "daily_template_standard": DAILY_TEMPLATE_STANDARD,
        "template_style_sha256": LOCKED_TEMPLATE_STYLE_SHA256,
        "n_days": len(dates),
        "n_weeks": len(week_summaries or render_week.week_windows(dates)),
        "n_categories": len(render_category.CATEGORIES),
        "n_points": len(points),
        "chart_panels": len(chart_panels),
        "metrics_used": list(metric_counter.keys()),
        "metric_text": metric_text,
        "by_category": {
            category: {
                "points": len(category_points),
                "active_days": len({p["date"] for p in category_points}),
                "metrics": list(Counter(p["metric"] for p in category_points).keys()),
            }
            for category, category_points in by_category.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    summary = render_campaign_report()
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
