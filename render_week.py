#!/usr/bin/env python3
"""Render weekly report pages.

Weekly pages deliberately reuse the locked daily visual language. The data
unit changes: each point/row is one daily report, not one training run.

Usage:
    python3 render_week.py --week 1
    python3 render_week.py --all
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import plot as plot_mod
from render_day import (
    ASSETS_DIR,
    DB,
    HTML_DIR,
    LOCKED_TEMPLATE_STYLE_SHA256,
    OUT_ROOT,
    QMD_DIR,
    RESEARCH_END_DATE,
    RESEARCH_START_DATE,
    DAILY_TEMPLATE_STANDARD,
    compute_day_index,
    fetch_day,
    format_arch_families,
    format_day_index,
    format_metric_value,
    is_research_campaign_date,
    is_research_chronology_record,
    metric_display_name,
    render_one_day,
    _daily_template_style,
    _embedded_log_script,
    _frosted_flake_data_uri,
    make_alloc_bar_html,
    make_report_header_html,
    best_date,
)


WEEKLY_TEMPLATE_STANDARD = "weekly-report-v1.0-daily-rollup"
WEEK_QMD_DIR = OUT_ROOT / "weeks"
WEEK_HTML_DIR = HTML_DIR / "weeks"
WEEK_ASSETS_DIR = ASSETS_DIR / "weeks"
WEEK_SIZE_DAYS = 7


def all_campaign_dates(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT abs_path, rel_path, source_label, file_kind, mtime_iso, metrics_json FROM artifacts"
    ).fetchall()
    dates: set[str] = set()
    for row in rows:
        rec = dict(row)
        if not is_research_chronology_record(rec):
            continue
        date = best_date(rec)
        if is_research_campaign_date(date):
            dates.add(date)
    return sorted(dates)


def week_windows(dates: list[str], size: int = WEEK_SIZE_DAYS) -> list[list[str]]:
    dates = sorted(d for d in dates if RESEARCH_START_DATE <= d <= RESEARCH_END_DATE)
    return [dates[i:i + size] for i in range(0, len(dates), size)]


def week_slug(week_number: int, week_dates: list[str]) -> str:
    return f"week-{week_number:02d}_{week_dates[0]}_to_{week_dates[-1]}"


def dominant_camp(by_camp: dict[str, int] | None) -> str:
    counts = by_camp or {}
    if not counts:
        return "daily_grind"
    return max(sorted(counts), key=lambda camp: counts[camp])


def format_camp_counts(by_camp: dict[str, int] | None) -> str:
    counts = by_camp or {}
    parts = []
    for camp in ("kernel", "neural", "experimental", "daily_grind"):
        n = counts.get(camp, 0)
        if n:
            parts.append(f"{camp.upper()} {n}")
    return " · ".join(parts) if parts else "—"


def weekly_metric_counts(days: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for day in days:
        metric = day.get("headline_metric")
        if metric:
            counts[str(metric)] += 1
    return counts


def weekly_metrics_chrono(days: list[dict[str, Any]]) -> list[str]:
    """Metrics ordered by the date of their first daily datapoint.

    Stacked weekly charts read top-to-bottom as oldest-to-newest so the panel
    order matches the chronology of the daily listing.
    """
    seen: list[str] = []
    for day in sorted(days, key=lambda d: d.get("date") or ""):
        metric = day.get("headline_metric")
        if metric and metric not in seen:
            seen.append(str(metric))
    return seen


def primary_week_metric(days: list[dict[str, Any]]) -> str | None:
    counts = weekly_metric_counts(days)
    if not counts:
        return None
    priority = {"val_bpb": 0, "kernel_fb_ratio": 1, "kernel_fwd_ratio": 2, "val_loss": 3}
    return sorted(counts, key=lambda m: (-counts[m], priority.get(m, 99), m))[0]


def metric_points(days: list[dict[str, Any]], metric: str) -> list[dict[str, Any]]:
    points = []
    for idx, day in enumerate(days, start=1):
        value = day.get("best_headline_value")
        if day.get("headline_metric") != metric or not isinstance(value, (int, float)):
            continue
        points.append({
            "n": idx,
            "date": day["date"],
            "value": value,
            "camp": dominant_camp(day.get("by_camp")),
            "title": day.get("best_headline_title") or day.get("date"),
        })
    return points


def metric_counts_display(days: list[dict[str, Any]]) -> str:
    counts = weekly_metric_counts(days)
    if not counts:
        return "—"
    return "  ·  ".join(
        f"{metric_display_name(metric)} (×{count})"
        for metric, count in counts.most_common()
    )


def image_data_uri(path: str | Path) -> str:
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


def make_week_summary_html(week_number: int,
                           week_dates: list[str],
                           days: list[dict[str, Any]],
                           primary_metric: str | None,
                           by_camp: dict[str, int]) -> str:
    measured_days = [d for d in days if d.get("headline_metric")]
    metric_text = metric_counts_display(days)
    allocation = format_camp_counts(by_camp).lower()
    return (
        '<aside class="day-summary">'
        '<div class="ds-key">WEEK SUMMARY</div>'
        '<div class="ds-body">'
        f"<p>Week {week_number:02d} rolls up <strong>{len(days)} daily reports</strong> "
        f"from <strong>{html.escape(week_dates[0])}</strong> through "
        f"<strong>{html.escape(week_dates[-1])}</strong>. "
        f"It carries <strong>{len(measured_days)} measured daily datapoints</strong> "
        f"across {html.escape(metric_text)}.</p>"
        f"<p>Classification across the week: "
        f"<strong>{html.escape(allocation)}</strong>.</p>"
        "</div></aside>"
    )


def make_week_daily_table_html(conn: sqlite3.Connection,
                               week_number: int,
                               days: list[dict[str, Any]]) -> str:
    rows = [
        "<table class='test-runs-table'><thead><tr>"
        "<th>#</th><th>DAY</th><th>DATE</th><th>CLASS</th>"
        "<th>METRIC</th><th>DAY VALUE</th><th>TESTS</th><th>OPEN</th>"
        "</tr></thead><tbody>"
    ]
    for idx, day in enumerate(days, start=1):
        date = day["date"]
        day_num = format_day_index(compute_day_index(conn, date))
        metric = day.get("headline_metric") or ""
        metric_label = metric_display_name(metric) if metric else "—"
        day_value = day.get("best_headline_value_display") or "—"
        tests = day.get("n_test_rows") or day.get("chart_n_points") or 0
        rows.append(
            "<tr>"
            f"<td><strong>{idx}</strong></td>"
            f"<td>{html.escape(day_num)}</td>"
            f"<td>{html.escape(date)}</td>"
            f"<td>{html.escape(format_camp_counts(day.get('by_camp')))}</td>"
            f"<td>{html.escape(metric_label)}</td>"
            f"<td>{html.escape(day_value)}</td>"
            f"<td>{tests}</td>"
            "<td class='open-cell'><details class='log-toggle'>"
            "<summary>daily</summary></details></td>"
            "</tr>"
        )
        rows.append(
            "<tr class='log-detail-row'><td colspan='8'>"
            "<div class='log-panel'>"
            "<div class='log-meta'><strong>daily report evidence</strong></div>"
            f"<div class='log-meta'><strong>week</strong>: {week_number:02d}</div>"
            f"<div class='log-meta'><strong>date</strong>: {html.escape(date)} "
            f"(<a href='../{html.escape(date)}.html'>open daily report</a>)</div>"
            f"<div class='log-meta'><strong>day source row</strong>: "
            f"{html.escape(day.get('best_headline_title') or '—')}</div>"
            f"<div class='log-meta'><strong>architecture family</strong>: "
            f"{html.escape(day.get('arch_families_display') or '—')}</div>"
            f"<div class='log-meta'><strong>source</strong>: "
            f"{html.escape(day.get('biggest_source') or '—')}</div>"
            f"<div class='log-meta'><strong>visible support</strong>: "
            f"{html.escape(day.get('visible_support_source') or '—')} "
            f"({int(day.get('n_visible_support_records') or 0)} files/logs)</div>"
            f"<div class='log-meta'><strong>output</strong>: "
            f"{html.escape(day.get('html_path') or '')}</div>"
            "</div></td></tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def aggregate_camps(days: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for day in days:
        for camp, count in (day.get("by_camp") or {}).items():
            out[camp] += int(count)
    return dict(out)


def render_week(week_dates: list[str],
                week_number: int,
                daily_summaries: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    if not week_dates:
        raise SystemExit("empty week")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        days = []
        daily_summaries = daily_summaries or {}
        for date in week_dates:
            day = daily_summaries.get(date)
            if day is None:
                day = render_one_day(date)
            days.append(day)

        slug = week_slug(week_number, week_dates)
        asset_dir = WEEK_ASSETS_DIR / slug
        asset_dir.mkdir(parents=True, exist_ok=True)
        WEEK_QMD_DIR.mkdir(parents=True, exist_ok=True)
        WEEK_HTML_DIR.mkdir(parents=True, exist_ok=True)

        by_camp = aggregate_camps(days)
        primary_metric = primary_week_metric(days)
        chart_panels: list[dict[str, Any]] = []
        chart_points = 0
        for metric in weekly_metrics_chrono(days):
            points = metric_points(days, metric)
            if not points:
                continue
            chart_path, n = plot_mod.week_chart(
                asset_dir / f"week_chart_{metric}.png",
                week_label=f"WEEK {week_number:02d} · {week_dates[0]} TO {week_dates[-1]}",
                daily_points=points,
                metric_name=metric_display_name(metric),
            )
            chart_panels.append({"metric": metric, "path": chart_path, "n": n})
            chart_points += n
        chart_paths = [panel["path"] for panel in chart_panels]

        measured_points = sum(1 for d in days if d.get("headline_metric"))
        header_fields = [
            ("WEEK", f"{week_number:02d}"),
            ("DATES", f"{week_dates[0]} TO {week_dates[-1]}"),
            ("DAILY REPORTS", f"{len(days)} days  ({sum(1 for d in days if d.get('headline_metric'))} measured)"),
            ("HEADLINE METRICS", metric_counts_display(days)),
            ("DAILY DATAPOINTS", str(measured_points)),
            ("CLASSIFICATION", "—"),
        ]
        report_header = make_report_header_html(
            header_fields,
            alloc_bar=make_alloc_bar_html(by_camp) if by_camp else None,
        )
        h1_html = (
            '<h1>'
              '<span class="h1-title">'
                '<img class="h1-mark" src="' + _frosted_flake_data_uri() + '" alt="">'
                '<span>WEEKLY RESEARCH REPORT</span>'
              '</span>'
              f'<span class="h1-date">WEEK {week_number:02d}</span>'
            '</h1>'
        )
        summary = make_week_summary_html(
            week_number, week_dates, days, primary_metric, by_camp
        )
        daily_table = make_week_daily_table_html(conn, week_number, days)

        qmd_lines = [
            h1_html,
            "",
            report_header,
            "",
            "## SECTION 1.0 — WEEK TRAJECTORY",
            "",
            summary,
            "",
        ]
        if chart_panels:
            for panel in chart_panels:
                relp = os.path.relpath(panel["path"], WEEK_QMD_DIR)
                metric_label = metric_display_name(panel["metric"])
                qmd_lines.append(
                    f"![Week {week_number:02d} daily trajectory · {metric_label}]({relp})"
                )
                qmd_lines.append("")
        else:
            qmd_lines.append('<p class="muted">NO DAILY HEADLINE METRIC RECORDED THIS WEEK.</p>')
            qmd_lines.append("")
        qmd_lines += [
            "## SECTION 2.0 — DAILY REPORTS",
            "",
            daily_table,
            "",
        ]

        qmd_path = WEEK_QMD_DIR / f"{slug}.qmd"
        qmd_path.write_text("\n".join(qmd_lines), encoding="utf-8")

        body_parts = [
            h1_html,
            report_header,
            "<h2>SECTION 1.0 — WEEK TRAJECTORY</h2>",
            summary,
        ]
        for panel in chart_panels:
            metric_label = metric_display_name(panel["metric"])
            body_parts.append(
                "<figure>"
                f"<img src='{image_data_uri(panel['path'])}' "
                f"alt='Week {week_number:02d} daily trajectory · {html.escape(metric_label)}'/>"
                "</figure>"
            )
        if not chart_panels:
            body_parts.append('<p class="muted">NO DAILY HEADLINE METRIC RECORDED THIS WEEK.</p>')
        body_parts.extend([
            "<h2>SECTION 2.0 — DAILY REPORTS</h2>",
            daily_table,
        ])
        html_path = WEEK_HTML_DIR / f"{slug}.html"
        full_html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>Week {week_number:02d} - Research Weekly</title>"
            f"<style>{_daily_template_style()}</style></head><body>"
            + "\n".join(body_parts)
            + _embedded_log_script()
            + "</body></html>"
        )
        html_path.write_text(full_html, encoding="utf-8")

        return {
            "week": week_number,
            "slug": slug,
            "dates": week_dates,
            "qmd_path": str(qmd_path),
            "html_path": str(html_path),
            "asset_dir": str(asset_dir),
            "template_standard": WEEKLY_TEMPLATE_STANDARD,
            "daily_template_standard": DAILY_TEMPLATE_STANDARD,
            "template_style_sha256": LOCKED_TEMPLATE_STYLE_SHA256,
            "n_days": len(days),
            "n_measured_days": sum(1 for d in days if d.get("headline_metric")),
            "chart_points": chart_points,
            "chart_panels": len(chart_paths),
            "by_camp": by_camp,
            "primary_metric": primary_metric,
            "primary_metric_display": metric_display_name(primary_metric) if primary_metric else "",
            "daily_datapoints": measured_points,
        }
    finally:
        conn.close()


def render_week_index(week_summaries: list[dict[str, Any]]) -> str:
    WEEK_HTML_DIR.mkdir(parents=True, exist_ok=True)
    h1_html = (
        '<h1><span class="h1-title">'
        '<img class="h1-mark" src="' + _frosted_flake_data_uri() + '" alt="">'
        '<span>WEEKLY RESEARCH REPORTS</span></span>'
        '<span class="h1-date">INDEX</span></h1>'
    )
    rows = [
        "<table class='test-runs-table'><thead><tr>"
        "<th>WEEK</th><th>DATES</th><th>DAYS</th><th>METRIC</th>"
        "<th>DATAPOINTS</th><th>CLASS</th><th>OPEN</th>"
        "</tr></thead><tbody>"
    ]
    for w in week_summaries:
        dates = w["dates"]
        rows.append(
            "<tr>"
            f"<td><strong>{int(w['week']):02d}</strong></td>"
            f"<td>{html.escape(dates[0])} to {html.escape(dates[-1])}</td>"
            f"<td>{w['n_days']} ({w['n_measured_days']} measured)</td>"
            f"<td>{html.escape(w.get('primary_metric_display') or '—')}</td>"
            f"<td>{int(w.get('daily_datapoints') or 0)}</td>"
            f"<td>{html.escape(format_camp_counts(w.get('by_camp')))}</td>"
            f"<td><a href='{html.escape(Path(w['html_path']).name)}'>open week</a></td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    body = "\n".join([
        h1_html,
        make_report_header_html([
            ("WEEKS", str(len(week_summaries))),
            ("DATES", f"{RESEARCH_START_DATE} TO {RESEARCH_END_DATE}"),
            ("TEMPLATE", WEEKLY_TEMPLATE_STANDARD),
            ("DAILY STANDARD", DAILY_TEMPLATE_STANDARD),
        ]),
        "<h2>SECTION 1.0 — WEEK INDEX</h2>",
        "<aside class='day-summary'><div class='ds-key'>WEEK INDEX</div>"
        "<div class='ds-body'><p>Each row opens one weekly report. "
        "Each weekly report uses rendered daily reports as its datapoints.</p></div></aside>",
        "<h2>SECTION 2.0 — WEEKLY REPORTS</h2>",
        "\n".join(rows),
    ])
    html_path = WEEK_HTML_DIR / "index.html"
    html_path.write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Weekly Research Reports</title>"
        f"<style>{_daily_template_style()}</style></head><body>"
        + body
        + "</body></html>",
        encoding="utf-8",
    )
    return str(html_path)


def render_all_weeks(dates: list[str],
                     daily_summaries: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    summaries_by_date = {d["date"]: d for d in (daily_summaries or [])}
    weeks = []
    for week_number, week_dates in enumerate(week_windows(dates), start=1):
        weeks.append(render_week(week_dates, week_number, summaries_by_date))
    render_week_index(weeks)
    return weeks


def main() -> None:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--week", type=int, help="1-based research week")
    target.add_argument("--all", action="store_true", help="render every research week")
    args = parser.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        dates = all_campaign_dates(conn)
    finally:
        conn.close()
    windows = week_windows(dates)
    if args.all:
        result = render_all_weeks(dates)
        print({"weeks": len(result), "index": str(WEEK_HTML_DIR / "index.html")})
        return
    if args.week < 1 or args.week > len(windows):
        raise SystemExit(f"--week must be 1..{len(windows)}")
    print(render_week(windows[args.week - 1], args.week))


if __name__ == "__main__":
    main()
