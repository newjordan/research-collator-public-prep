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
    make_report_h1_html,
    make_report_header_html,
)


TOC_TEMPLATE_STANDARD = "toc-v1.1-connected-scroll"
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
    bg_css = ""
    if bg:
        bg_css = f"""
    body.toc-page {{
      max-width: 1280px;
      background-image:
        linear-gradient(rgba(137,56,14,0.74), rgba(137,56,14,0.82)),
        url('{bg}');
      background-size: cover;
      background-position: center top;
      background-attachment: fixed;
    }}
    """
    return f"""
    {bg_css}
    body.toc-page .toc-kicker {{
      margin: -6px 0 18px;
      color: var(--accent);
      font-size: 10.5px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      font-weight: 700;
    }}
    body.toc-page .toc-reader {{
      display: grid;
      gap: 26px;
      margin: 18px 0 0;
    }}
    body.toc-page .toc-reader-entry {{
      border-top: 1px solid var(--rule-hi);
      padding-top: 14px;
    }}
    body.toc-page .toc-reader-topline {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 9px 12px;
      background: var(--rule-hi);
      color: var(--bg);
      font-size: 10.5px;
      line-height: 1.4;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    body.toc-page .toc-reader-topline strong,
    body.toc-page .toc-reader-topline a {{
      color: var(--bg);
    }}
    body.toc-page .toc-reader-open {{
      white-space: nowrap;
      border-bottom-color: var(--bg);
    }}
    body.toc-page .toc-reader-frame {{
      display: block;
      width: 100%;
      min-height: 720px;
      border: 1px solid var(--rule-hi);
      border-top: none;
      background: var(--bg);
    }}
    @media (max-width: 760px) {{
      body.toc-page .toc-reader-topline {{
        align-items: flex-start;
        flex-direction: column;
      }}
      body.toc-page .toc-reader-frame {{
        min-height: 560px;
      }}
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
        ("TABLE OF CONTENTS", "1", "toc.html", "navigation, reading order, and connected scroll"),
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


def connected_reader_items(dates: list[str],
                           week_summaries: list[dict[str, Any]],
                           category_summaries: list[dict[str, Any]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = [
        {
            "kind": "campaign",
            "label": "CAMPAIGN CUMULATIVE",
            "href": "cumulative.html",
        },
        {
            "kind": "category-index",
            "label": "CATEGORY INDEX",
            "href": "categories/index.html",
        },
    ]
    for category in category_summaries:
        items.append({
            "kind": "category",
            "label": f"CATEGORY · {category['label']}",
            "href": f"categories/{Path(category['html_path']).name}",
        })
    items.append({
        "kind": "week-index",
        "label": "WEEKLY INDEX",
        "href": "weeks/index.html",
    })
    for week in week_summaries:
        items.append({
            "kind": "week",
            "label": f"WEEK {int(week['week']):02d} · {week['dates'][0]} TO {week['dates'][-1]}",
            "href": f"weeks/{Path(week['html_path']).name}",
        })
    for idx, date in enumerate(dates, start=1):
        items.append({
            "kind": "day",
            "label": f"DAY {idx:03d} · {date}",
            "href": f"{date}.html",
        })
    return items


def make_connected_reader_html(dates: list[str],
                               week_summaries: list[dict[str, Any]],
                               category_summaries: list[dict[str, Any]]) -> str:
    parts = ["<div class=\"toc-reader\" data-connected-reader=\"true\">"]
    for idx, item in enumerate(
        connected_reader_items(dates, week_summaries, category_summaries),
        start=1,
    ):
        kind = html.escape(item["kind"], quote=True)
        label = html.escape(item["label"])
        href = html.escape(item["href"], quote=True)
        parts.append(
            f'<section class="toc-reader-entry" data-reader-kind="{kind}">'
            f'<div class="toc-reader-topline">'
            f'<strong>{idx:02d} / {label}</strong>'
            f'<a class="toc-reader-open" href="{href}">open standalone</a>'
            f'</div>'
            f'<iframe class="toc-reader-frame" src="{href}" title="{label}" '
            f'loading="lazy" data-reader-href="{href}" data-reader-kind="{kind}"></iframe>'
            f'</section>'
        )
    parts.append("</div>")
    return "\n".join(parts)


def connected_reader_script() -> str:
    return """
<script>
(function(){
  function resizeFrame(frame) {
    try {
      var doc = frame.contentDocument;
      if (!doc) return;
      doc.querySelectorAll('a').forEach(function(a){ a.target = '_top'; });
      var size = function() {
        var body = doc.body;
        var root = doc.documentElement;
        var height = Math.max(
          body ? body.scrollHeight : 0,
          root ? root.scrollHeight : 0,
          560
        );
        frame.style.height = (height + 8) + 'px';
      };
      size();
      if (frame._tocResizeObserver) frame._tocResizeObserver.disconnect();
      if (window.ResizeObserver && doc.documentElement) {
        frame._tocResizeObserver = new ResizeObserver(size);
        frame._tocResizeObserver.observe(doc.documentElement);
        if (doc.body) frame._tocResizeObserver.observe(doc.body);
      }
      doc.addEventListener('toggle', size, true);
      doc.defaultView && doc.defaultView.addEventListener('load', size);
    } catch (e) {
      frame.style.height = '900px';
    }
  }
  document.querySelectorAll('.toc-reader-frame').forEach(function(frame){
    frame.addEventListener('load', function(){ resizeFrame(frame); });
    if (frame.contentDocument && frame.contentDocument.readyState === 'complete') {
      resizeFrame(frame);
    }
  });
})();
</script>
"""


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
    h1_html = make_report_h1_html("TABLE OF CONTENTS", "CAMPAIGN")
    report_header = make_report_header_html(header_fields)
    summary_html = make_summary_html(
        dates, week_summaries, category_summaries, campaign_summary
    )
    layer_table = make_layer_table(dates, week_summaries, category_summaries, campaign_summary)
    category_table = make_category_table(category_summaries)
    week_table = make_week_table(week_summaries)
    daily_table = make_daily_table(dates, days_summary)
    connected_reader = make_connected_reader_html(
        dates, week_summaries, category_summaries
    )

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
        "<h3>CONNECTED SCROLL</h3>",
        connected_reader,
    ])

    full_html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Table of Contents</title>"
        f"<style>{_daily_template_style()}{toc_extra_style()}</style></head><body class='toc-page'>"
        + "\n".join(body_parts)
        + connected_reader_script()
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
        "### CONNECTED SCROLL",
        "",
        connected_reader,
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
