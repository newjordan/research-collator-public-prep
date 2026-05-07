#!/usr/bin/env python3
"""Render every date with artifacts. Generates:

  output/preview/index.html        — front page with journey chart + day list
  output/preview/<DATE>.html       — one page per day
  output/preview/weeks/<WEEK>.html — one page per 7-day research week
  output/preview/weeks/index.html  — weekly report index
  output/days/<DATE>.qmd           — Quarto-ready
  output/assets/<DATE>/*.png       — chart PNGs
  output/weeks/<WEEK>.qmd          — weekly Quarto-ready
  output/assets/journey.png        — front-page arc chart

Usage:
    python3 render_all.py
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import plot as plot_mod
import render_week
from render_day import (
    DB, OUT_ROOT, HTML_DIR, ASSETS_DIR,
    RESEARCH_START_DATE, RESEARCH_END_DATE,
    best_date, fetch_day,
    extract_metric_for_record, render_one_day,
    is_reference_baseline_record, is_research_chronology_record,
    is_research_campaign_date, is_valid_metric_value,
)


def all_dates_with_artifacts(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT abs_path, rel_path, source_label, file_kind, mtime_iso, metrics_json FROM artifacts"
    ).fetchall()
    dates: set[str] = set()
    for r in rows:
        rec = dict(r)
        if not is_research_chronology_record(rec):
            continue
        d = best_date(rec)
        if is_research_campaign_date(d):
            dates.add(d)
    return sorted(dates)


def per_day_best(conn: sqlite3.Connection, date: str, metric: str) -> dict | None:
    records = fetch_day(conn, date)
    best_v = None
    best_title = None
    best_camp = None
    for rec in records:
        if is_reference_baseline_record(rec):
            continue
        vals = extract_metric_for_record(rec.get("metrics_json"), metric)
        for v in vals:
            if not is_valid_metric_value(metric, v):
                continue
            if best_v is None or v < best_v:
                best_v = v
                best_title = rec.get("title") or "(untitled)"
                best_camp = rec.get("camp") or "neural"
    if best_v is None:
        return None
    return {"date": date, "best": best_v, "camp": best_camp, "title": best_title}


def remove_stale_campaign_outputs(active_dates: list[str]) -> int:
    """Remove date-named outputs no longer in the canonical campaign."""
    active = set(active_dates)
    removed = 0
    date_file = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    HTML_DIR.mkdir(parents=True, exist_ok=True)
    for path in HTML_DIR.glob("????-??-??.html"):
        if path.stem not in active:
            path.unlink()
            removed += 1

    days_dir = OUT_ROOT / "days"
    days_dir.mkdir(parents=True, exist_ok=True)
    for path in days_dir.glob("????-??-??.qmd"):
        if path.stem not in active:
            path.unlink()
            removed += 1

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for path in ASSETS_DIR.iterdir():
        if path.is_dir() and date_file.match(path.name) and path.name not in active:
            shutil.rmtree(path)
            removed += 1

    return removed


def render_index(dates_with_results: list[dict],
                 days_summary: list[dict],
                 journey_chart_path: str,
                 week_summaries: list[dict] | None = None) -> str:
    """Build the front index.html."""
    style = """
    body { font-family: -apple-system, system-ui, sans-serif; max-width: 1080px;
           margin: 24px auto; padding: 0 22px; color: #222; line-height: 1.45; }
    h1 { font-size: 1.8em; border-bottom: 2px solid #ddd; padding-bottom: 4px; }
    h2 { font-size: 1.25em; margin-top: 1.6em; border-bottom: 1px solid #eee; padding-bottom: 3px; }
    .muted { color: #888; }
    figure { margin: 18px 0; text-align: center; }
    figure img { max-width: 100%; height: auto; }
    table { border-collapse: collapse; width: 100%; font-size: 0.93em; }
    th, td { padding: 5px 9px; text-align: left; border-bottom: 1px solid #eee;
             vertical-align: top; }
    th { color: #555; font-weight: 600; }
    tr:hover td { background: #f9f9f9; }
    a { color: #1f5fb4; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .badge { display: inline-block; font-size: 0.78em; padding: 1px 6px;
             border-radius: 9px; color: #fff; }
    .badge-kernel { background: #b88724; }
    .badge-neural { background: #1f77b4; }
    .badge-experimental { background: #ff7f0e; }
    .badge-daily_grind { background: #888; }
    .stat { display: inline-block; margin: 0 14px 4px 0; }
    .stat strong { font-size: 1.1em; color: #111; }
    code { background: #f3f3f3; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }
    """
    lines = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Research — Daily Reports</title>",
        f"<style>{style}</style>",
        "</head><body>",
        "<h1>Research — Daily Reports</h1>",
        f"<p class='muted'>Generated {dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes')} UTC. "
        f"Spans {len(days_summary)} research days from {RESEARCH_START_DATE} to {RESEARCH_END_DATE}. "
        "Final submission: Mockingbird.</p>",
    ]

    # Headline stats
    total_records = sum(d["n_records"] for d in days_summary)
    total_kernel = sum(d["by_camp"].get("kernel", 0) for d in days_summary)
    total_neural = sum(d["by_camp"].get("neural", 0) for d in days_summary)
    total_exp = sum(d["by_camp"].get("experimental", 0) for d in days_summary)
    total_visible_support = sum(d.get("n_visible_support_records", 0) for d in days_summary)
    days_with_metric = sum(1 for d in days_summary if d.get("headline_metric"))
    journey_best = min((d["best"] for d in dates_with_results), default=None)

    lines.append("<p>")
    lines.append(f"<span class='stat'><strong>{total_records}</strong> indexed artifacts</span>")
    lines.append(f"<span class='stat'><strong>{total_visible_support}</strong> visible support files/logs</span>")
    lines.append(f"<span class='stat'><strong>{total_kernel}</strong> kernel</span>")
    lines.append(f"<span class='stat'><strong>{total_neural}</strong> neural</span>")
    lines.append(f"<span class='stat'><strong>{total_exp}</strong> experimental</span>")
    lines.append(f"<span class='stat'><strong>{days_with_metric}</strong> days with headline metrics</span>")
    if journey_best is not None:
        lines.append(f"<span class='stat'>best ever: <strong>{journey_best:.4f}</strong></span>")
    lines.append("</p>")

    # Journey chart
    if journey_chart_path:
        rel = os.path.relpath(journey_chart_path, HTML_DIR)
        lines.append("<h2>Journey arc</h2>")
        lines.append("<figure>")
        lines.append(f"<img src='{rel}' alt='journey arc'/>")
        lines.append("<figcaption class='muted'>Journey arc tracks best val_loss/val_bpb per day. "
                     "Kernel days use their own custom/FA3 daily headline metric.</figcaption>")
        lines.append("</figure>")

    if week_summaries:
        lines.append("<h2>Weekly reports</h2>")
        lines.append("<table><thead><tr>")
        lines.append("<th>week</th><th>dates</th><th>days</th><th>primary metric</th>"
                     "<th>datapoints</th><th>classification</th>")
        lines.append("</tr></thead><tbody>")
        for week in week_summaries:
            href = f"weeks/{Path(week['html_path']).name}"
            dates = week["dates"]
            lines.append(
                f"<tr><td><a href='{href}'>Week {int(week['week']):02d}</a></td>"
                f"<td>{html.escape(dates[0])} to {html.escape(dates[-1])}</td>"
                f"<td>{week['n_days']} ({week['n_measured_days']} measured)</td>"
                f"<td>{html.escape(week.get('primary_metric_display') or '')}</td>"
                f"<td>{int(week.get('daily_datapoints') or 0)}</td>"
                f"<td>{html.escape(render_week.format_camp_counts(week.get('by_camp')))}</td></tr>"
            )
        lines.append("</tbody></table>")

    # Day table
    lines.append("<h2>Daily reports</h2>")
    lines.append("<table><thead><tr>")
    lines.append("<th>date</th><th>artifacts</th><th>camps</th><th>visible support</th>"
                 "<th>headline metric</th><th>best of day</th><th>vs baseline</th>")
    lines.append("</tr></thead><tbody>")
    by_date = {d["date"]: d for d in days_summary}
    for d in sorted(by_date.keys()):
        ds = by_date[d]
        camp_badges = []
        for camp in ("kernel", "neural", "experimental", "daily_grind"):
            n = ds["by_camp"].get(camp, 0)
            if n:
                camp_badges.append(
                    f"<span class='badge badge-{camp}'>{camp[:6]}: {n}</span>"
                )
        link = f"<a href='{d}.html'>{d}</a>"
        best_value = ds.get("best_headline_value")
        best_cell = html.escape(ds.get("best_headline_value_display") or "")
        baseline = ds.get("chart_baseline_to_beat")
        if (
            isinstance(best_value, (int, float))
            and isinstance(baseline, (int, float))
            and baseline
        ):
            delta = best_value - baseline
            arrow = "↓" if delta < 0 else "↑"
            vs_cell = f"{arrow} {abs(100.0 * delta / baseline):.1f}%"
        else:
            vs_cell = ""
        lines.append(
            f"<tr><td>{link}</td>"
            f"<td>{ds['n_records']}</td>"
            f"<td>{' '.join(camp_badges)}</td>"
            f"<td><code>{html.escape(ds.get('visible_support_source') or 'no day-local files/logs')}</code></td>"
            f"<td>{html.escape(ds.get('headline_metric_display') or ds.get('headline_metric') or '')}</td>"
            f"<td>{best_cell}</td>"
            f"<td>{vs_cell}</td></tr>"
        )
    lines.append("</tbody></table>")
    lines.append("</body></html>")
    return "\n".join(lines)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    print("[1/5] enumerating dates...")
    dates = all_dates_with_artifacts(conn)
    print(f"      {len(dates)} unique dates")
    stale_removed = remove_stale_campaign_outputs(dates)
    if stale_removed:
        print(f"      removed {stale_removed} stale date outputs outside campaign")

    print("[2/5] rendering each day...")
    days_summary: list[dict] = []
    t0 = time.perf_counter()
    for i, d in enumerate(dates, 1):
        try:
            res = render_one_day(d)
        except SystemExit:
            continue
        days_summary.append(res)
        if i % 10 == 0 or i == len(dates):
            print(f"      {i}/{len(dates)} ({time.perf_counter() - t0:.1f}s)")

    print("[3/5] rendering weekly reports...")
    week_summaries = render_week.render_all_weeks(dates, days_summary)
    print(f"      {len(week_summaries)} weekly reports")

    print("[4/5] computing per-day bests for journey chart...")
    # Pick the metric with broadest coverage across the corpus.
    metric_used = "val_loss"
    per_day = []
    for d in dates:
        b = per_day_best(conn, d, metric_used)
        if b:
            per_day.append(b)
    if not per_day:
        # fallback: try val_bpb
        metric_used = "val_bpb"
        for d in dates:
            b = per_day_best(conn, d, metric_used)
            if b:
                per_day.append(b)

    print(f"      {len(per_day)} days have a best {metric_used}")

    # Render journey chart
    print("[5/5] rendering journey arc + index.html...")
    journey_path = ""
    if per_day:
        journey_path, _ = plot_mod.journey_chart(
            ASSETS_DIR / "journey.png",
            per_day_bests=per_day,
            metric_name=metric_used,
            # The running-min line tells the story; a separate dashed baseline
            # would just clutter the panel.
        )

    index_html = render_index(per_day, days_summary, journey_path, week_summaries)
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    (HTML_DIR / "index.html").write_text(index_html)

    # Copy / link the journey chart into preview/ so the index can serve it
    # as a relative path. We point at the assets dir directly via relative URL.
    print(f"\ndone. {len(days_summary)} day pages, {len(week_summaries)} week pages, {len(per_day)} on journey arc.")
    print(f"front page: {HTML_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
