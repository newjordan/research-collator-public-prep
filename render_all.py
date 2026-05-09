#!/usr/bin/env python3
"""Render every date with artifacts. Generates:

  output/preview/index.html             — publication cover page alias
  output/preview/cover.html             — publication cover page
  output/preview/journey.html           — legacy journey chart + day list
  output/preview/report_144.html        — table of contents
  output/preview/<DATE>.html            — one page per day
  output/preview/weeks/<WEEK>.html      — one page per 7-day research week
  output/preview/weeks/index.html       — weekly report index
  output/preview/categories/index.html  — category report index
  output/preview/categories/<CAT>.html  — one page per category cumulative report
  output/preview/cumulative.html        — campaign cumulative overlay report
  output/days/<DATE>.qmd                — Quarto-ready
  output/assets/<DATE>/*.png            — daily chart PNGs
  output/weeks/<WEEK>.qmd               — weekly Quarto-ready
  output/categories/<CAT>.qmd           — category Quarto-ready
  output/campaign/cumulative.qmd        — campaign cumulative Quarto-ready
  output/assets/journey.png             — legacy journey arc chart

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
import render_campaign
import render_category
import render_cover
import render_intro
import render_toc
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


def minify_preview_html(root: Path = HTML_DIR) -> dict[str, int]:
    """Conservatively minify generated HTML without touching text node content."""
    before = 0
    after = 0
    count = 0
    for path in root.rglob("*.html"):
        raw = path.read_text(encoding="utf-8")
        minified = re.sub(r">\s+<", "><", raw).strip()
        if not minified:
            continue
        before += len(raw.encode("utf-8"))
        after += len(minified.encode("utf-8"))
        count += 1
        if minified != raw:
            path.write_text(minified, encoding="utf-8")
    return {"files": count, "before": before, "after": after, "saved": before - after}


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


def sync_architecture_run_files() -> None:
    """Make repo-published run-file downloads available in the static output."""
    src = Path(__file__).parent / "public" / "architecture-run-files"
    if not src.exists():
        return
    dst = HTML_DIR / "architecture-run-files"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def render_index(dates_with_results: list[dict],
                 days_summary: list[dict],
                 journey_chart_path: str,
                 week_summaries: list[dict] | None = None,
                 category_summaries: list[dict] | None = None,
                 campaign_summary: dict | None = None,
                 toc_summary: dict | None = None) -> str:
    """Build the legacy journey.html page."""
    style = """
    body { font-family: -apple-system, system-ui, sans-serif; max-width: 1080px;
           margin: 24px auto; padding: 0 22px; color: #050605; line-height: 1.45;
           background: #89380e; }
    html { background: #89380e; }
    h1 { font-size: 1.8em; border-bottom: 2px solid #050605; padding-bottom: 4px; }
    h2 { font-size: 1.25em; margin-top: 1.6em; border-bottom: 1px solid #050605; padding-bottom: 3px; }
    .muted { color: #1b0f08; }
    figure { margin: 18px 0; text-align: center; }
    figure img { max-width: 100%; height: auto; }
    table { border-collapse: collapse; width: 100%; font-size: 0.93em; }
    th, td { padding: 5px 9px; text-align: left; border-bottom: 1px solid #050605;
             vertical-align: top; }
    th { color: #1b0f08; font-weight: 600; }
    tr:hover td { background: rgba(5,6,5,0.08); }
    a { color: #050605; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .badge { display: inline-block; font-size: 0.78em; padding: 1px 6px;
             border-radius: 9px; color: #89380e; }
    .badge-kernel { background: #050605; }
    .badge-neural { background: #2b1607; }
    .badge-experimental { background: #130a04; }
    .badge-daily_grind { background: #3b1b08; }
    .stat { display: inline-block; margin: 0 14px 4px 0; }
    .stat strong { font-size: 1.1em; color: #050605; }
    code { background: rgba(5,6,5,0.10); padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }
    """
    lines = [
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Research — Daily Reports</title>",
        f"<style>{style}</style>",
        "</head><body>",
        "<h1>Research — Daily Reports</h1>",
        f"<p class='muted'>Generated {dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes')} UTC. "
        f"Spans {len(days_summary)} research days from {RESEARCH_START_DATE} to {RESEARCH_END_DATE}. "
        "Final submission: 10k-vocabulary CaseOps loop-body submission.</p>",
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

    if campaign_summary:
        if toc_summary:
            lines.append("<h2>Table of contents</h2>")
            lines.append("<table><thead><tr>")
            lines.append("<th>report</th><th>daily</th><th>weekly</th><th>categories</th><th>open</th>")
            lines.append("</tr></thead><tbody>")
            lines.append(
                f"<tr><td>Publication map</td>"
                f"<td>{int(toc_summary.get('n_days') or 0)}</td>"
                f"<td>{int(toc_summary.get('n_weeks') or 0)}</td>"
                f"<td>{int(toc_summary.get('n_categories') or 0)}</td>"
                "<td><a href='report_144.html'>open report 144</a></td></tr>"
            )
            lines.append("</tbody></table>")

        lines.append("<h2>Campaign cumulative report</h2>")
        lines.append("<table><thead><tr>")
        lines.append("<th>report</th><th>days</th><th>categories</th><th>datapoints</th>"
                     "<th>chart panels</th><th>metrics</th>")
        lines.append("</tr></thead><tbody>")
        href = Path(campaign_summary["html_path"]).name
        metrics_blurb = campaign_summary.get("metric_text") or "—"
        lines.append(
            f"<tr><td><a href='{html.escape(href)}'>Campaign cumulative</a></td>"
            f"<td>{int(campaign_summary.get('n_days') or 0)}</td>"
            f"<td>{int(campaign_summary.get('n_categories') or 0)}</td>"
            f"<td>{int(campaign_summary.get('n_points') or 0)}</td>"
            f"<td>{int(campaign_summary.get('chart_panels') or 0)}</td>"
            f"<td>{html.escape(metrics_blurb)}</td></tr>"
        )
        lines.append("</tbody></table>")

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
        lines.append(
            "<p class='muted'>Index: "
            "<a href='weeks/index.html'>weeks/index.html</a></p>"
        )
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

    if category_summaries:
        lines.append("<h2>Category cumulative reports</h2>")
        lines.append(
            "<p class='muted'>Two-week non-overlapping windows. Index: "
            "<a href='categories/index.html'>categories/index.html</a></p>"
        )
        lines.append("<table><thead><tr>")
        lines.append("<th>category</th><th>active days</th><th>datapoints</th>"
                     "<th>windows (active / total)</th><th>chart panels</th>"
                     "<th>metrics</th>")
        lines.append("</tr></thead><tbody>")
        for cat in category_summaries:
            href = f"categories/{Path(cat['html_path']).name}"
            metrics_blurb = ", ".join(cat.get("metrics_used") or []) or "—"
            lines.append(
                f"<tr><td><a href='{href}'>{html.escape(cat['label'].title())}</a></td>"
                f"<td>{int(cat.get('active_days') or 0)}</td>"
                f"<td>{int(cat.get('n_points') or 0)}</td>"
                f"<td>{int(cat.get('windows_active') or 0)} / {int(cat.get('windows_total') or 0)}</td>"
                f"<td>{int(cat.get('chart_panels') or 0)}</td>"
                f"<td>{html.escape(metrics_blurb)}</td></tr>"
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

    print("[1/9] enumerating dates...")
    dates = all_dates_with_artifacts(conn)
    print(f"      {len(dates)} unique dates")
    stale_removed = remove_stale_campaign_outputs(dates)
    if stale_removed:
        print(f"      removed {stale_removed} stale date outputs outside campaign")
    sync_architecture_run_files()

    print("[2/9] rendering each day...")
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

    print("[3/9] rendering weekly reports...")
    week_summaries = render_week.render_all_weeks(dates, days_summary)
    print(f"      {len(week_summaries)} weekly reports")

    print("[4/9] rendering category cumulative reports...")
    category_summaries = render_category.render_all_categories(dates)
    print(
        f"      {len(category_summaries)} category reports"
        f" ({sum(c.get('chart_panels') or 0 for c in category_summaries)}"
        f" chart panels)"
    )

    print("[5/9] rendering campaign cumulative report...")
    campaign_summary = render_campaign.render_campaign_report(
        dates, week_summaries, category_summaries
    )
    print(
        f"      {campaign_summary.get('chart_panels', 0)} overlay panels, "
        f"{campaign_summary.get('n_points', 0)} category datapoints"
    )

    print("[6/9] rendering publication cover...")
    cover_summary = render_cover.render_cover_page()
    print(f"      cover page: {cover_summary.get('html_path')}")
    intro_summary = render_intro.render_intro_page()
    print(f"      intro page: {intro_summary.get('html_path')}")

    print("[7/9] rendering table of contents...")
    toc_summary = render_toc.render_toc_report(
        dates, days_summary, week_summaries, category_summaries,
        campaign_summary,
    )
    print(f"      report 144 page: {toc_summary.get('html_path')}")

    print("[8/9] computing per-day bests for journey chart...")
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
    print("[9/9] rendering journey arc + journey.html...")
    journey_path = ""
    if per_day:
        journey_path, _ = plot_mod.journey_chart(
            ASSETS_DIR / "journey.png",
            per_day_bests=per_day,
            metric_name=metric_used,
            # The running-min line tells the story; a separate dashed baseline
            # would just clutter the panel.
        )

    journey_html = render_index(
        per_day, days_summary, journey_path, week_summaries,
        category_summaries, campaign_summary, toc_summary
    )
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    (HTML_DIR / "journey.html").write_text(journey_html)

    minify_summary = minify_preview_html()
    print(
        f"      minified {minify_summary['files']} HTML files, "
        f"saved {minify_summary['saved'] / 1024:.1f} KiB"
    )

    # The legacy journey page points at the assets dir directly via relative URL.
    print(
        f"\ndone. {len(days_summary)} day pages, "
        f"{len(week_summaries)} week pages, "
        f"{len(category_summaries)} category pages, "
        f"1 campaign cumulative page, "
        f"1 cover page, "
        f"1 report 144 page, "
        f"{len(per_day)} on journey arc."
    )
    print(f"front page: {HTML_DIR / 'cover.html'}")
    print(f"journey page: {HTML_DIR / 'journey.html'}")


if __name__ == "__main__":
    main()
