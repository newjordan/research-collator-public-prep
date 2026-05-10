#!/usr/bin/env python3
"""Render the campaign table of contents."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import render_week
from render_intro import palette_easter_egg_controls, palette_easter_egg_script
from render_day import (
    DAILY_TEMPLATE_STANDARD,
    FRAGMENTS_DIR,
    HTML_DIR,
    INVALID_VAL_BPB_FLOOR,
    LOCKED_TEMPLATE_STYLE_SHA256,
    OUT_ROOT,
    RESEARCH_END_DATE,
    RESEARCH_START_DATE,
    _daily_template_style,
    _embedded_log_script,
    make_report_h1_html,
    make_report_header_html,
    preview_asset_src,
)


TOC_TEMPLATE_STANDARD = "toc-v1.3-palette-sync"
TOC_QMD_DIR = OUT_ROOT / "toc"
TOC_HTML_PATH = HTML_DIR / "report_144.html"
TOC_COMPAT_HTML_PATH = HTML_DIR / "toc.html"
TOC_BACKGROUND_PATH = Path("assets/toc_background_generated.png")
TOC_WEBLOADER_COVER_PATH = Path("assets/cover_sheet_final.jpeg")
TOC_WEBLOADER_PAGE2_PATH = Path("assets/page_2_above_toc.jpeg")
TOC_FOOTER_BACKGROUND_PATH = Path("assets/toc_footer_background.png")


def toc_extra_style() -> str:
    bg = preview_asset_src(TOC_BACKGROUND_PATH) if TOC_BACKGROUND_PATH.exists() else ""
    bg_css = ""
    if bg:
        bg_css = f"""
    body.toc-page {{
      position: relative;
      isolation: isolate;
      max-width: 1280px;
      background: #050605;
    }}
    body.toc-page::before {{
      content: "";
      position: fixed;
      inset: 0;
      z-index: -1;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(137,56,14,0.74), rgba(137,56,14,0.82)),
        url('{bg}');
      background-size: cover;
      background-position: center top;
      background-attachment: fixed;
      filter: var(--tone-filter);
      transition: filter 220ms ease;
    }}
    """
    return f"""
    {bg_css}
    :root {{
      --tone-filter: none;
      --chrome-bg: #050605;
      --chrome-fg: #8b3702;
      --chrome-rule: #8b3702;
      --chrome-bg-soft: #0c0907;
    }}
    body.toc-page {{
      transform-origin: top center;
    }}
    body.toc-page .toc-filtered {{
      position: relative;
      z-index: 1;
      filter: var(--tone-filter);
      transition: filter 220ms ease;
      transform-origin: top center;
    }}
    body.toc-page .toc-footer-background {{
      position: fixed;
      right: 0;
      bottom: 0;
      z-index: 0;
      width: min(42vw, 456px);
      max-width: 58vh;
      height: auto;
      opacity: 0.85;
      mix-blend-mode: darken;
      pointer-events: none;
      user-select: none;
      filter: var(--tone-filter);
      transition: filter 220ms ease;
    }}
    body.toc-page .toc-back-top {{
      position: fixed;
      left: 0;
      bottom: 22px;
      z-index: 10000;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 25px;
      min-height: 76px;
      padding: 8px 3px;
      border: 1px solid var(--chrome-rule);
      border-left: 0;
      border-radius: 0;
      background: var(--chrome-bg);
      color: var(--chrome-fg);
      font-family: var(--mono);
      font-size: 10px;
      font-weight: 950;
      line-height: 1;
      letter-spacing: 0.08em;
      writing-mode: vertical-rl;
      text-orientation: upright;
      text-decoration: none;
      cursor: pointer;
      user-select: none;
    }}
    body.toc-page .toc-back-top:hover,
    body.toc-page .toc-back-top:focus-visible {{
      background: var(--chrome-fg);
      color: var(--chrome-bg);
      outline: 1px solid var(--chrome-rule);
      outline-offset: 2px;
    }}
    body.toc-page .toc-latin-footer {{
      position: fixed;
      left: 32px;
      bottom: 7px;
      z-index: 10000;
      color: var(--rule-hi);
      font-family: var(--mono);
      font-size: 9px;
      font-weight: 850;
      line-height: 1;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      pointer-events: none;
      user-select: none;
      opacity: 0;
      transform: translateY(3px);
      transition: opacity 160ms linear, transform 160ms linear;
    }}
    body.toc-page .toc-latin-footer.is-decoded {{
      opacity: 1;
      transform: translateY(0);
    }}
    body.toc-page .palette-label {{
      position: fixed;
      top: 8px;
      left: 8px;
      z-index: 10000;
      display: none;
      align-items: center;
      padding: 4px 8px;
      background: var(--chrome-bg);
      color: var(--chrome-fg);
      border: 1px solid var(--chrome-rule);
      font-family: var(--mono);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      pointer-events: none;
    }}
    body.toc-page .palette-switcher {{
      position: fixed;
      top: 8px;
      right: 24px;
      z-index: 10000;
      display: none;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 6px;
      max-width: min(80vw, 720px);
      padding: 6px;
      background: var(--chrome-bg);
      border: 1px solid var(--chrome-rule);
      font-family: var(--mono);
    }}
    body.toc-page.debug .palette-label,
    body.toc-page.debug .palette-switcher {{
      display: flex;
    }}
    body.toc-page .palette-switcher span {{
      align-self: center;
      padding: 0 4px 0 2px;
      color: var(--chrome-fg);
      font-size: 9px;
      font-weight: 800;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      opacity: 0.7;
    }}
    body.toc-page .palette-switcher button {{
      padding: 5px 9px;
      background: var(--chrome-bg-soft);
      color: var(--chrome-fg);
      border: 1px solid var(--chrome-rule);
      border-radius: 0;
      font: inherit;
      font-size: 10px;
      font-weight: 800;
      line-height: 1;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      cursor: pointer;
    }}
    body.toc-page .palette-switcher button:hover,
    body.toc-page .palette-switcher button:focus-visible,
    body.toc-page .palette-switcher button[aria-pressed="true"] {{
      background: var(--chrome-fg);
      color: var(--chrome-bg);
      outline: 0;
    }}
    html,
    body.toc-page,
    body.toc-page * {{
      scrollbar-width: none !important;
      -ms-overflow-style: none !important;
    }}
    html::-webkit-scrollbar,
    body.toc-page::-webkit-scrollbar,
    body.toc-page *::-webkit-scrollbar {{
      width: 0 !important;
      height: 0 !important;
      display: none !important;
    }}
    body.toc-page .toc-page-scrollbar {{
      position: fixed;
      top: 0;
      right: 0;
      width: 16px;
      height: 100vh;
      background: var(--chrome-bg);
      border-left: 1px solid var(--chrome-rule);
      z-index: 9999;
      pointer-events: auto;
      cursor: pointer;
      border-radius: 0 !important;
      overflow: hidden;
    }}
    body.toc-page .toc-page-scrollbar-thumb {{
      position: absolute;
      left: 2px;
      top: 0;
      width: 12px;
      height: 48px;
      background: var(--chrome-fg);
      border: 1px solid var(--chrome-bg);
      border-radius: 0 !important;
      clip-path: inset(0 0 0 0);
      appearance: none;
      cursor: grab;
      user-select: none;
      touch-action: none;
    }}
    body.toc-page .toc-page-scrollbar-thumb.is-dragging {{
      cursor: grabbing;
    }}
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
    body.toc-page .toc-reader-entry.is-collapsed .toc-reader-frame {{
      display: none;
    }}
    body.toc-page .toc-reader-entry.is-collapsed .toc-reader-day-list {{
      display: none;
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
    body.toc-page .toc-reader-topline strong {{
      color: var(--bg);
    }}
    body.toc-page .toc-action,
    body.toc-page .test-runs-table td a,
    body.toc-page .toc-reader-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 24px;
      padding: 4px 8px;
      border: 1px solid var(--rule-hi);
      background: var(--rule-hi);
      color: var(--bg);
      cursor: pointer;
      font-size: 10.5px;
      font-weight: 700;
      line-height: 1;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      text-decoration: none;
      white-space: nowrap;
      list-style: none;
      user-select: none;
      border-radius: 0;
    }}
    body.toc-page .toc-action::before,
    body.toc-page .test-runs-table td a::before,
    body.toc-page .toc-reader-toggle::before {{
      content: "";
      width: 8px;
      height: 8px;
      flex: 0 0 auto;
      background: var(--bg);
    }}
    body.toc-page .toc-action:hover,
    body.toc-page .toc-action:focus-visible,
    body.toc-page .test-runs-table td a:hover,
    body.toc-page .test-runs-table td a:focus-visible,
    body.toc-page .toc-reader-toggle:hover,
    body.toc-page .toc-reader-toggle:focus-visible {{
      background: var(--rule-hi);
      color: var(--bg);
      border-bottom-color: var(--rule-hi);
      outline: 1px solid var(--rule-hi);
      outline-offset: 2px;
    }}
    body.toc-page .test-runs-table th:last-child,
    body.toc-page .test-runs-table td:last-child,
    body.toc-page .test-runs-table .toc-action-cell {{
      text-align: right;
      white-space: nowrap;
    }}
    body.toc-page .test-runs-table td:last-child .toc-action,
    body.toc-page .test-runs-table .toc-action-cell .toc-action {{
      justify-content: flex-start;
    }}
    body.toc-page .toc-inline-action {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 20px;
      margin: 0 3px;
      padding: 3px 7px;
      border: 1px solid var(--rule-hi);
      border-radius: 0;
      background: var(--bg);
      color: var(--rule-hi);
      font-size: 10px;
      font-weight: 850;
      line-height: 1;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      text-decoration: none;
      white-space: nowrap;
      vertical-align: middle;
    }}
    body.toc-page .toc-inline-action::before {{
      content: "";
      width: 7px;
      height: 7px;
      flex: 0 0 auto;
      background: var(--rule-hi);
    }}
    body.toc-page .toc-inline-action:hover,
    body.toc-page .toc-inline-action:focus-visible {{
      background: var(--rule-hi);
      color: var(--bg);
      outline: 1px solid var(--rule-hi);
      outline-offset: 2px;
    }}
    body.toc-page .toc-inline-action:hover::before,
    body.toc-page .toc-inline-action:focus-visible::before {{
      background: var(--bg);
    }}
    body.toc-page .toc-calibration {{
      display: block;
      margin: 14px 0 18px;
      padding: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      box-shadow: none;
    }}
    body.toc-page .report-header + .toc-calibration {{
      margin-top: 0;
    }}
    body.toc-page .report-header:has(+ .toc-calibration) {{
      margin-bottom: 0;
    }}
    body.toc-page .toc-calibration > summary {{
      display: flex;
      align-items: center;
      gap: 0;
      min-height: 32px;
      padding: 8px 10px;
      border: 2px solid var(--rule-hi);
      border-radius: 0;
      background: transparent;
      color: var(--chrome-fg);
      cursor: pointer;
      font-size: 11px;
      font-weight: 900;
      line-height: 1;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      list-style: none;
      user-select: none;
      box-shadow: inset 0 0 0 1px var(--chrome-fg);
      overflow: hidden;
      opacity: 1;
    }}
    body.toc-page .toc-calibration > summary::-webkit-details-marker {{
      display: none;
    }}
    body.toc-page .toc-calibration > summary::marker {{
      content: "";
    }}
    body.toc-page .toc-calibration > summary::before {{
      display: none;
    }}
    body.toc-page .toc-calibration .toc-calibration-label {{
      display: inline-flex;
      align-items: center;
      gap: 9px;
      flex: 0 0 auto;
      padding-right: 14px;
      background: transparent;
      color: var(--rule-hi);
    }}
    body.toc-page .toc-calibration .toc-calibration-label::before {{
      content: "";
      width: 10px;
      height: 10px;
      flex: 0 0 auto;
      background: var(--rule-hi);
    }}
    body.toc-page .toc-calibration .toc-calibration-stripes {{
      display: block;
      flex: 1 1 auto;
      align-self: stretch;
      min-width: 140px;
      margin: -6px 14px;
      border-left: 1px solid var(--chrome-fg);
      border-right: 1px solid var(--chrome-fg);
      background: repeating-linear-gradient(
        135deg,
        transparent 0 18px,
        var(--rule-hi) 18px 36px
      );
    }}
    body.toc-page .toc-calibration > summary::after {{
      content: "expand rules";
      margin-left: auto;
      color: var(--rule-hi);
      background: transparent;
      padding-left: 14px;
      font-size: 9.5px;
      font-weight: 800;
      letter-spacing: 0.08em;
    }}
    body.toc-page .toc-calibration[open] > summary::after {{
      content: "collapse rules";
    }}
    body.toc-page .toc-calibration > summary:hover,
    body.toc-page .toc-calibration > summary:focus-visible {{
      outline: 1px solid var(--rule-hi);
      outline-offset: 2px;
    }}
    body.toc-page .toc-calibration .ds-body {{
      display: block;
      grid-column: 1 / -1;
      margin-top: 8px;
      padding: 12px 14px;
      border: 1px solid var(--rule-hi);
      background: var(--rule-hi);
      color: var(--chrome-fg);
    }}
    body.toc-page .toc-calibration .ds-body p,
    body.toc-page .toc-calibration .ds-body strong {{
      color: var(--chrome-fg);
    }}
    body.toc-page .toc-calibration:not([open]) .ds-body {{
      display: none;
    }}
    body.toc-page .toc-reader-actions {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex: 0 0 auto;
      justify-content: flex-end;
    }}
    body.toc-page .toc-reader-frame {{
      display: block;
      width: 100%;
      min-height: 720px;
      border: 1px solid var(--rule-hi);
      border-top: none;
      background: var(--bg);
    }}
    body.toc-page .toc-reader-day-list {{
      border: 1px solid var(--rule-hi);
      border-top: none;
      padding: 10px;
      background: var(--bg);
    }}
    body.toc-page .toc-webloader-intro {{
      min-height: 100vh;
      width: 100vw;
      display: grid;
      place-items: start center;
      margin: -32px calc(50% - 50vw) 0;
      padding: 0;
      border-bottom: 0;
      overflow: visible;
      background: #050605;
    }}
    body.toc-page .toc-webloader-intro iframe {{
      display: block;
      width: 85vw;
      max-width: none;
      aspect-ratio: 1053 / 1494;
      height: auto;
      border: 0;
      background: #050605;
    }}
    body.toc-page .toc-webloader-cover,
    body.toc-page .toc-webloader-page2 {{
      min-height: 100vh;
      width: 100vw;
      display: grid;
      place-items: start center;
      margin: 0 calc(50% - 50vw) 36px;
      padding: 0;
      border-bottom: 1px solid var(--rule-hi);
      overflow: visible;
      background: #050605;
    }}
    body.toc-page .toc-image-stage {{
      position: relative;
      width: 85vw;
      max-width: none;
      margin: 0;
      padding: 0;
      line-height: 0;
    }}
    body.toc-page .toc-webloader-cover {{
      margin-top: -32px;
      border-bottom: 0;
    }}
    body.toc-page .toc-webloader-cover img,
    body.toc-page .toc-webloader-page2 img {{
      display: block;
      width: 100%;
      max-width: none;
      height: auto;
      border: 1px solid var(--rule-hi);
      background: var(--rule-hi);
      box-shadow: 0 24px 80px rgba(5,6,5,0.35);
    }}
    body.toc-page .toc-palette-hotspot {{
      position: absolute;
      z-index: 5;
      display: block;
      margin: 0;
      padding: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      cursor: pointer;
      outline: 0;
      line-height: 0;
    }}
    body.toc-page .toc-palette-hotspot:focus-visible {{
      outline: 1px dashed var(--chrome-fg);
      outline-offset: 2px;
    }}
    body.toc-page.debug .toc-palette-hotspot {{
      background: var(--chrome-fg);
      opacity: 0.18;
      outline: 1px dashed var(--chrome-rule);
    }}
    body.toc-page .wipe-overlay {{
      position: fixed;
      inset: 0;
      z-index: 10001;
      pointer-events: none;
      background-color: var(--wipe-tint, transparent);
      mix-blend-mode: color;
      opacity: 0;
      transition: opacity 180ms ease;
      --wipe-r: 0px;
      --wipe-cx: 50%;
      --wipe-cy: 50%;
      --wipe-feather: 8px;
      -webkit-mask-image: radial-gradient(circle at var(--wipe-cx) var(--wipe-cy),
        transparent 0,
        transparent calc(var(--wipe-r) - var(--wipe-feather)),
        #000 var(--wipe-r),
        #000 100%);
      mask-image: radial-gradient(circle at var(--wipe-cx) var(--wipe-cy),
        transparent 0,
        transparent calc(var(--wipe-r) - var(--wipe-feather)),
        #000 var(--wipe-r),
        #000 100%);
    }}
    body.toc-page .wipe-overlay.is-running {{
      opacity: 1;
    }}
    @media (max-width: 760px) {{
      body.toc-page .toc-reader-topline {{
        align-items: flex-start;
        flex-direction: column;
      }}
      body.toc-page .toc-reader-actions {{
        flex-wrap: wrap;
        width: 100%;
      }}
      body.toc-page .toc-reader-frame {{
        min-height: 560px;
      }}
      body.toc-page .toc-webloader-intro iframe,
      body.toc-page .toc-image-stage {{
        width: calc(100vw - 2px);
      }}
      body.toc-page .toc-webloader-page2 {{
        min-height: auto;
      }}
      body.toc-page .toc-webloader-cover {{
        min-height: auto;
      }}
      body.toc-page .toc-webloader-intro {{
        min-height: auto;
      }}
    }}
    """


def make_layer_table(dates: list[str],
                     week_summaries: list[dict[str, Any]],
                     category_summaries: list[dict[str, Any]],
                     campaign_summary: dict | None) -> str:
    rows = [
        "<table class='test-runs-table'><thead><tr>"
        "<th>LAYER</th><th>COUNT</th><th>FUNCTION</th><th class='toc-action-cell'>OPEN</th>"
        "</tr></thead><tbody>"
    ]
    layers = [
        ("ADDRESS TO THE READER", "1", "#address-to-reader", "Stellae creationem esse donum divinum nostrum postulant."),
        ("TABLE OF CONTENTS", "1", "report_144.html", "navigation, report calibration, and report reader"),
        ("CATEGORY REPORTS", str(len(category_summaries)), "categories/index.html", "experimental, neural, and kernel drilldowns"),
        ("WEEKLY REPORTS", str(len(week_summaries)), "weeks/index.html", "7-day daily-report rollups"),
        ("DAILY REPORTS", str(len(dates)), f"{dates[0]}.html", "one locked evidence page per campaign day"),
    ]
    for label, count, href, function in layers:
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(label)}</strong></td>"
            f"<td>{html.escape(str(count))}</td>"
            f"<td>{html.escape(function)}</td>"
            f"<td class='toc-action-cell'><a class='toc-action' href='{html.escape(href)}'>open</a></td>"
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
            f"<td><a class='toc-action' href='weeks/{html.escape(Path(week['html_path']).name)}'>open week</a></td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def make_category_table(category_summaries: list[dict[str, Any]]) -> str:
    rows = [
        "<table class='test-runs-table toc-category-index'><thead><tr>"
        "<th>CATEGORY</th><th>ACTIVE DAYS</th><th>DATAPOINTS</th>"
        "<th>WINDOWS</th><th>CHART PANELS</th><th>OPEN</th>"
        "</tr></thead><tbody>"
    ]
    for category in category_summaries:
        href = f"categories/{Path(category['html_path']).name}"
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(category['label'])}</strong></td>"
            f"<td>{int(category.get('active_days') or 0)}</td>"
            f"<td>{int(category.get('n_points') or 0)}</td>"
            f"<td>{int(category.get('windows_active') or 0)} / {int(category.get('windows_total') or 0)}</td>"
            f"<td>{int(category.get('chart_panels') or 0)}</td>"
            f"<td><a class='toc-action toc-reader-jump' href='{html.escape(href)}' "
            f"data-reader-jump='true' data-reader-href='{html.escape(href)}'>open</a></td>"
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
            f"<td><a class='toc-action' href='{html.escape(date)}.html'>open day</a></td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def make_lazy_daily_table(dates: list[str], days_summary: list[dict[str, Any]]) -> str:
    FRAGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    fragment_path = FRAGMENTS_DIR / "toc_daily_reports.html"
    fragment_path.write_text(make_daily_table(dates, days_summary), encoding="utf-8")
    return (
        '<section class="toc-reader-entry is-collapsed" data-reader-kind="daily-index">'
        '<div class="toc-reader-topline">'
        f'<strong>DAILY REPORTS · {len(dates)} DAYS</strong>'
        '<span class="toc-reader-actions">'
        '<button class="toc-reader-toggle" type="button" aria-expanded="false">expand</button>'
        '</span>'
        '</div>'
        '<div class="toc-reader-day-list">'
        "<div class='lazy-test-card'>"
        "<p><strong>DAILY REPORTS</strong></p>"
        "<button class='lazy-test-load' type='button' "
        "data-lazy-fragment='fragments/toc_daily_reports.html' "
        "data-target='toc-daily-reports-table' "
        "data-load-label='load daily reports' data-hide-label='hide daily reports' "
        "data-loading-label='loading daily reports' data-error-label='daily reports load failed'>"
        "load daily reports</button>"
        "<div id='toc-daily-reports-table' class='lazy-test-target' hidden></div>"
        "</div>"
        "</div>"
        "</section>"
    )


def connected_reader_items(dates: list[str],
                           week_summaries: list[dict[str, Any]],
                           category_summaries: list[dict[str, Any]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = [
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
    parts = ["<div id=\"table-of-contents\" class=\"toc-reader\" data-connected-reader=\"true\">"]
    idx = 1
    day_items: list[dict[str, str]] = []
    for item in connected_reader_items(dates, week_summaries, category_summaries):
        if item["kind"] == "day":
            day_items.append(item)
            continue
        kind = html.escape(item["kind"], quote=True)
        label = html.escape(item["label"])
        href = html.escape(item["href"], quote=True)
        collapsed_class = " is-collapsed"
        expanded_attr = "false"
        toggle_label = "expand"
        parts.append(
            f'<section class="toc-reader-entry{collapsed_class}" data-reader-kind="{kind}">'
            f'<div class="toc-reader-topline">'
            f'<strong>{idx:02d} / {label}</strong>'
            f'<span class="toc-reader-actions">'
            f'<button class="toc-reader-toggle" type="button" aria-expanded="{expanded_attr}">{toggle_label}</button>'
            f'</span>'
            f'</div>'
            f'<iframe class="toc-reader-frame" src="{href}" title="{label}" '
            f'loading="lazy" scrolling="no" data-reader-href="{href}" '
            f'data-reader-kind="{kind}"></iframe>'
            f'</section>'
        )
        idx += 1
    if day_items:
        day_rows = [
            "<table class='test-runs-table'><thead><tr>"
            "<th>DAY</th><th>DATE</th><th>OPEN</th></tr></thead><tbody>"
        ]
        for day in day_items:
            day_href = html.escape(day["href"], quote=True)
            day_label = html.escape(day["label"])
            day_date = html.escape(day["href"].replace(".html", ""))
            day_rows.append(
                "<tr "
                f"data-reader-href='{day_href}'>"
                f"<td><strong>{day_label}</strong></td>"
                f"<td>{day_date}</td>"
                f"<td><a class='toc-action' href='{day_href}'>open day</a></td>"
                "</tr>"
            )
        day_rows.append("</tbody></table>")
        parts.append(
            '<section class="toc-reader-entry toc-reader-day-group is-collapsed" '
            'data-reader-kind="day-group">'
            '<div class="toc-reader-topline">'
            f'<strong>{idx:02d} / DAILY REPORTS · {len(day_items)} DAYS</strong>'
            '<span class="toc-reader-actions">'
            '<button class="toc-reader-toggle" type="button" aria-expanded="false">expand</button>'
            '</span>'
            '</div>'
            '<div class="toc-reader-day-list">'
            + "".join(day_rows) +
            '</div>'
            '</section>'
        )
    parts.append("</div>")
    return "\n".join(parts)


def make_webloader_page2_html() -> str:
    if not TOC_WEBLOADER_PAGE2_PATH.exists():
        return ""
    image_uri = preview_asset_src(TOC_WEBLOADER_PAGE2_PATH)
    return (
        '<section class="toc-webloader-page2" aria-label="Publication page 2">'
        '<div class="toc-image-stage">'
        f'<img src="{image_uri}" alt="Research corpus page above the table of contents">'
        '<button class="toc-palette-hotspot" type="button" data-palette-cycle="true" '
        'aria-label="Cycle palette from page 2 smooth brain stamp" '
        'style="left:81.5%;top:2.4%;width:15.0%;height:14.5%"></button>'
        '<button class="toc-palette-hotspot" type="button" data-palette-cycle="true" '
        'aria-label="Cycle palette from page 2 flake stamp" '
        'style="left:2.0%;top:1.5%;width:9.0%;height:7.6%"></button>'
        '</div>'
        "</section>"
    )


def make_webloader_cover_html() -> str:
    if not TOC_WEBLOADER_COVER_PATH.exists():
        return ""
    image_uri = preview_asset_src(TOC_WEBLOADER_COVER_PATH)
    return (
        '<section class="toc-webloader-cover" aria-label="Publication landing page">'
        '<div class="toc-image-stage">'
        f'<img src="{image_uri}" alt="Research corpus landing page">'
        '<button class="toc-palette-hotspot" type="button" data-palette-cycle="true" '
        'aria-label="Cycle palette from cover smooth brain stamp" '
        'style="left:80.4%;top:3.1%;width:15.4%;height:13.3%"></button>'
        '<button class="toc-palette-hotspot" type="button" data-palette-cycle="true" '
        'aria-label="Cycle palette from cover flake stamp" '
        'style="left:1.8%;top:1.2%;width:9.2%;height:7.0%"></button>'
        '</div>'
        "</section>"
    )


def make_webloader_intro_html() -> str:
    return (
        '<section id="address-to-reader" class="toc-webloader-intro" aria-label="Address to the Reader">'
        '<iframe src="intro.html?embed=1&amp;nofilter=1" title="Address to the Reader" loading="eager"></iframe>'
        "</section>"
    )


def connected_reader_script() -> str:
    return """
<script>
(function(){
  if ('scrollRestoration' in window.history) {
    window.history.scrollRestoration = 'manual';
  }
  var userInteracted = false;
  ['pointerdown', 'wheel', 'touchstart', 'keydown'].forEach(function(type) {
    window.addEventListener(type, function(){ userInteracted = true; }, {
      capture: true,
      passive: true
    });
  });
  function isReloadNavigation() {
    try {
      if (window.performance && performance.getEntriesByType) {
        var nav = performance.getEntriesByType('navigation')[0];
        if (nav && nav.type === 'reload') return true;
      }
      if (window.performance && performance.navigation && performance.navigation.type === 1) {
        return true;
      }
    } catch (e) {}
    return false;
  }
  if (isReloadNavigation() && String(window.location.hash || '').match(/^#reader=(.+)$/)) {
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
    }
  }
  function decodeHashValue(value) {
    try { return decodeURIComponent(value); } catch (e) { return value; }
  }
  function normalizeHref(value) {
    return String(value || '').replace(/^\\.\\//, '');
  }
  function readerEntryForHref(href) {
    var target = normalizeHref(href);
    var entries = Array.prototype.slice.call(document.querySelectorAll('.toc-reader-entry'));
    for (var i = 0; i < entries.length; i++) {
      var frame = entries[i].querySelector('.toc-reader-frame');
      if (frame && normalizeHref(frame.getAttribute('data-reader-href')) === target) {
        return entries[i];
      }
      var linked = entries[i].querySelector('[data-reader-href="' + target.replace(/"/g, '\\"') + '"]');
      if (linked) return entries[i];
    }
    return null;
  }
  function setEntryCollapsed(entry, collapsed) {
    if (!entry) return;
    entry.classList.toggle('is-collapsed', collapsed);
    var button = entry.querySelector('.toc-reader-toggle');
    if (button) {
      button.textContent = collapsed ? 'expand' : 'collapse';
      button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }
    if (!collapsed) {
      var frame = entry.querySelector('.toc-reader-frame');
      if (frame) setTimeout(function(){ resizeFrame(frame); }, 50);
    }
  }
  function scrollToReaderHref(href, updateHash) {
    var entry = readerEntryForHref(href);
    if (!entry) return false;
    setEntryCollapsed(entry, false);
    entry.scrollIntoView({ block: 'start' });
    if (updateHash && window.history && window.history.replaceState) {
      window.history.replaceState(null, '', '#reader=' + encodeURIComponent(normalizeHref(href)));
    }
    return true;
  }
  function restoreReaderHash() {
    var match = String(window.location.hash || '').match(/^#reader=(.+)$/);
    if (!match) return false;
    var href = decodeHashValue(match[1]);
    if (!href) return false;
    requestAnimationFrame(function(){ scrollToReaderHref(href, false); });
    setTimeout(function(){ scrollToReaderHref(href, false); }, 350);
    setTimeout(function(){ scrollToReaderHref(href, false); }, 1200);
    return true;
  }
  function tocStartTarget() {
    return document.getElementById('toc-start') || document.getElementById('table-of-contents');
  }
  function scrollToTocStart() {
    var target = tocStartTarget();
    var top = target ? target.getBoundingClientRect().top + window.pageYOffset : 0;
    window.scrollTo(0, Math.max(0, top));
  }
  function resetReaderScrollIfNoHash() {
    if (String(window.location.hash || '').match(/^#reader=(.+)$/)) return;
    function resetIfIdle() {
      if (!userInteracted) scrollToTocStart();
    }
    resetIfIdle();
    requestAnimationFrame(resetIfIdle);
    setTimeout(resetIfIdle, 250);
    setTimeout(resetIfIdle, 900);
  }
  document.querySelectorAll('[data-reader-jump="true"]').forEach(function(link) {
    link.addEventListener('click', function(event) {
      var href = link.getAttribute('data-reader-href') || link.getAttribute('href');
      if (!href) return;
      if (scrollToReaderHref(href, true)) {
        event.preventDefault();
      }
    });
  });
  document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
    anchor.addEventListener('click', function(event) {
      var target = document.querySelector(anchor.getAttribute('href'));
      if (!target) return;
      event.preventDefault();
      target.scrollIntoView({ block: 'start', behavior: 'smooth' });
      if (window.history && window.history.replaceState) {
        window.history.replaceState(null, '', window.location.pathname + window.location.search);
      }
    });
  });
  function resizeFrame(frame) {
    try {
      var doc = frame.contentDocument;
      if (!doc) return;
      doc.querySelectorAll('a').forEach(function(a){ a.target = '_top'; });
      if (!doc._tocMasterReturnBound) {
        doc._tocMasterReturnBound = true;
        doc.addEventListener('click', function(event) {
          var a = event.target && event.target.closest ? event.target.closest('a') : null;
          if (!a || !a.classList || !a.classList.contains('h1-master')) return;
          var href = a.getAttribute('href') || '';
          if (href.indexOf('report_144.html') === -1) return;
          event.preventDefault();
          scrollToReaderHref(frame.getAttribute('data-reader-href'), true);
        }, true);
      }
      if (doc.documentElement) doc.documentElement.style.overflow = 'hidden';
      if (doc.body) doc.body.style.overflow = 'hidden';
      var size = function() {
        var body = doc.body;
        var root = doc.documentElement;
        // Prefer body.scrollHeight (auto-height body reflects true content size).
        // Avoid root.scrollHeight: with overflow:hidden on root, it stays at
        // the iframe's allocated viewport height even after content shrinks,
        // leaving a blank area below collapsed content.
        var height = Math.max(
          body ? body.scrollHeight : (root ? root.scrollHeight : 0),
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
  document.querySelectorAll('.toc-reader-toggle').forEach(function(button){
    button.addEventListener('click', function(){
      var entry = button.closest('.toc-reader-entry');
      setEntryCollapsed(entry, !(entry && entry.classList.contains('is-collapsed')));
    });
  });
  window.addEventListener('hashchange', restoreReaderHash);
  window.addEventListener('load', function(){
    if (!restoreReaderHash()) resetReaderScrollIfNoHash();
  });
  if (!restoreReaderHash()) resetReaderScrollIfNoHash();
})();
</script>
"""


def page_scrollbar_html() -> str:
    return (
        '<div class="toc-page-scrollbar" aria-hidden="true">'
        '<div class="toc-page-scrollbar-thumb"></div>'
        '</div>'
    )


def footer_background_html() -> str:
    if not TOC_FOOTER_BACKGROUND_PATH.exists():
        return ""
    image_uri = preview_asset_src(TOC_FOOTER_BACKGROUND_PATH)
    return (
        '<img class="toc-footer-background" '
        f'src="{html.escape(image_uri, quote=True)}" alt="" aria-hidden="true">'
    )


def back_to_top_html() -> str:
    return (
        '<button class="toc-back-top" type="button" '
        'aria-label="Back to table of contents">TOC</button>'
        '<div class="toc-latin-footer" aria-hidden="true" '
        'data-latin-message="Deus ex machina; machina ex corde amante populorum; cor populorum ex sapientia.">'
        'XXXX XX XXXXXXX X XXXXXXX XXXXXXX</div>'
    )


def page_scrollbar_script() -> str:
    return """
<script>
(function(){
  var track = document.querySelector('.toc-page-scrollbar');
  var thumb = document.querySelector('.toc-page-scrollbar-thumb');
  if (!track || !thumb) return;
  var drag = null;

  function metrics() {
    var root = document.documentElement;
    var body = document.body;
    var scrollHeight = Math.max(
      root ? root.scrollHeight : 0,
      body ? body.scrollHeight : 0
    );
    var clientHeight = window.innerHeight || (root ? root.clientHeight : 0) || 1;
    var maxScroll = Math.max(0, scrollHeight - clientHeight);
    var trackHeight = track.clientHeight;
    var ratio = clientHeight / Math.max(scrollHeight, clientHeight);
    var thumbHeight = Math.max(48, Math.floor(trackHeight * ratio));
    var maxTop = Math.max(0, trackHeight - thumbHeight);
    return {
      root: root,
      body: body,
      clientHeight: clientHeight,
      maxScroll: maxScroll,
      trackHeight: trackHeight,
      thumbHeight: thumbHeight,
      maxTop: maxTop
    };
  }

  function scrollToTopValue(value) {
    window.scrollTo(0, Math.max(0, value));
  }

  function syncPageThumb() {
    var m = metrics();
    var scrollTop = window.pageYOffset || m.root.scrollTop || (m.body ? m.body.scrollTop : 0) || 0;
    var top = m.maxScroll > 0 ? Math.floor((scrollTop / m.maxScroll) * m.maxTop) : 0;
    thumb.style.height = m.thumbHeight + 'px';
    thumb.style.transform = 'translateY(' + top + 'px)';
  }

  function pageYToScroll(pageY, offset) {
    var rect = track.getBoundingClientRect();
    var m = metrics();
    var top = Math.max(0, Math.min(m.maxTop, pageY - rect.top - offset));
    return m.maxTop > 0 ? (top / m.maxTop) * m.maxScroll : 0;
  }

  thumb.addEventListener('pointerdown', function(event) {
    var rect = thumb.getBoundingClientRect();
    drag = { offset: event.clientY - rect.top };
    thumb.classList.add('is-dragging');
    thumb.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  thumb.addEventListener('pointermove', function(event) {
    if (!drag) return;
    scrollToTopValue(pageYToScroll(event.clientY, drag.offset));
    event.preventDefault();
  });

  function stopDrag(event) {
    if (!drag) return;
    drag = null;
    thumb.classList.remove('is-dragging');
    try { thumb.releasePointerCapture(event.pointerId); } catch (e) {}
  }

  thumb.addEventListener('pointerup', stopDrag);
  thumb.addEventListener('pointercancel', stopDrag);

  track.addEventListener('pointerdown', function(event) {
    if (event.target === thumb) return;
    var m = metrics();
    scrollToTopValue(pageYToScroll(event.clientY, m.thumbHeight / 2));
    event.preventDefault();
  });

  window.addEventListener('scroll', syncPageThumb, { passive: true });
  window.addEventListener('resize', syncPageThumb);
  syncPageThumb();
})();
</script>
"""


def back_to_top_script() -> str:
    return """
<script>
(function(){
  var button = document.querySelector('.toc-back-top');
  if (!button) return;
  button.addEventListener('click', function(event) {
    event.preventDefault();
    var target = document.getElementById('toc-start') || document.getElementById('table-of-contents');
    var top = target ? target.getBoundingClientRect().top + window.pageYOffset : 0;
    window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
  });
})();
</script>
"""


def latin_footer_script() -> str:
    return """
<script>
(function(){
  var footer = document.querySelector('.toc-latin-footer');
  if (!footer) return;
  var decoded = footer.getAttribute('data-latin-message') || '';
  var encoded = 'XXXX XX XXXXXXX X XXXXXXX XXXXXXX';
  function isAtPageBottom() {
    var root = document.documentElement;
    var body = document.body;
    var scrollHeight = Math.max(
      root ? root.scrollHeight : 0,
      body ? body.scrollHeight : 0
    );
    var scrollTop = window.pageYOffset || (root ? root.scrollTop : 0) || 0;
    var viewport = window.innerHeight || (root ? root.clientHeight : 0) || 0;
    return scrollHeight - (scrollTop + viewport) <= 24;
  }
  function syncLatinFooter() {
    var atBottom = isAtPageBottom();
    footer.textContent = atBottom ? decoded : encoded;
    footer.classList.toggle('is-decoded', atBottom);
  }
  window.addEventListener('scroll', syncLatinFooter, { passive: true });
  window.addEventListener('resize', syncLatinFooter);
  window.addEventListener('load', syncLatinFooter);
  syncLatinFooter();
})();
</script>
"""


def make_summary_html(dates: list[str],
                      week_summaries: list[dict[str, Any]],
                      category_summaries: list[dict[str, Any]],
                      campaign_summary: dict | None) -> str:
    body = (
        "<p><strong>Competition / task:</strong> OpenAI Parameter Golf: build "
        "a compressed language-model submission under contest constraints and "
        "minimize validation bits per byte.</p>"
        "<p><strong>Public competition context:</strong> the competition and "
        "pull requests were public "
        "<a class='toc-inline-action' "
        "href='https://github.com/openai/parameter-golf/pulls' "
        "target='_blank' rel='noopener'>OpenAI Parameter Golf PRs</a>. "
        "Adapting to public SOTA, comparing against public submissions, and "
        "incorporating the best available techniques were part of the "
        "competition. All work included in this report is mine, built within "
        "that collaborative public field.</p>"
        "<p><strong>Track calibration:</strong> the experimental branch was "
        "the non-record unified transformer / recursion research lane. It "
        "contains architecture probes and recurrence ideas tested for insight; "
        "the neural branch is the competitive leaderboard-submission track.</p>"
        "<p><strong>BPB:</strong> bits per byte. Lower is better; this report "
        "separates BPB model scores from custom-kernel / FA3 timing ratios.</p>"
        "<p><strong>Valid submission:</strong> a BPB submission counts only "
        "when it follows the three-seed contest standard: artifact under the "
        "16 MB cap, a 10-minute training run on 8xH100, a 10-minute maximum "
        "evaluation period on 8xH100, and no test-data leakage.</p>"
        f"<p><strong>Invalid scores:</strong> BPB values below "
        f"<strong>{INVALID_VAL_BPB_FLOOR:.2f}</strong> are treated as "
        "TTT test-data leakage and excluded from valid competition "
        "comparisons.</p>"
        "<p><strong>Excluded / non-comparable:</strong> artifacts over 16 MB, "
        "runs outside the 8xH100 / 10-minute train / 10-minute eval / "
        "three-seed standard, crash rows, loader failures, and kernel ratio "
        "measurements are not counted as valid BPB submissions.</p>"
        "<p><strong>Best valid score:</strong>&nbsp;<strong>1.0620 VAL_BPB</strong>."
        "</p>"
        "<p><strong>Baseline:</strong> the tracked Naive Baseline reference was "
        "<strong>1.2244 VAL_BPB</strong>; the best valid result is a "
        "<strong>0.1624 BPB</strong> reduction, about <strong>13.3%</strong> "
        "lower than that baseline.</p>"
        "<p><strong>Improvement:</strong> the strongest line was a hybrid "
        "neural submission using a larger 10k-vocabulary CaseOps tokenizer "
        "with looped GQA transformer mechanics, per-group compression, "
        "int7/int6 packaging, LQER, and phased LoRA TTT.</p>"
        "<p><strong>Evidence:</strong> all files and logs provided for review "
        "or reproduction.</p>"
    )
    return (
        '<details class="day-summary toc-calibration">'
        '<summary class="ds-key"><span class="toc-calibration-label">'
        'READER CALIBRATION / RULES</span>'
        '<span class="toc-calibration-stripes" aria-hidden="true"></span>'
        '</summary>'
        f'<div class="ds-body">{body}</div></details>'
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
        ("DOCUMENT", "COMPETITION DATA LOGS"),
        ("COMPETITION", "OPENAI PARAMETER GOLF"),
        ("DATES", f"{RESEARCH_START_DATE} TO {RESEARCH_END_DATE}"),
        ("CATEGORY REPORTS", str(len(category_summaries))),
        ("WEEKLY REPORTS", str(len(week_summaries))),
        ("DAILY REPORTS", str(len(dates))),
    ]
    h1_html = make_report_h1_html("TABLE OF CONTENTS", "CAMPAIGN").replace(
        'class="h1-home"',
        'class="h1-home" data-palette-cycle="true"',
        1,
    ).replace(
        "<h1>",
        '<h1 id="toc-start" tabindex="-1">',
        1,
    )
    report_header = make_report_header_html(header_fields)
    summary_html = make_summary_html(
        dates, week_summaries, category_summaries, campaign_summary
    )
    layer_table = make_layer_table(dates, week_summaries, category_summaries, campaign_summary)
    category_table = make_category_table(category_summaries)
    week_table = make_week_table(week_summaries)
    daily_table = make_lazy_daily_table(dates, days_summary)
    connected_reader = make_connected_reader_html(
        dates, week_summaries, category_summaries
    )
    webloader_cover = make_webloader_cover_html()
    webloader_intro = make_webloader_intro_html()
    webloader_page2 = make_webloader_page2_html()

    body_parts = [
        palette_easter_egg_controls(),
        page_scrollbar_html(),
        footer_background_html(),
        back_to_top_html(),
        '<div class="toc-filtered">',
        webloader_cover,
        webloader_intro,
        webloader_page2,
        h1_html,
        "<div class='toc-kicker'>PARAMETER GOLF CAMPAIGN / NAVIGATION INDEX</div>",
        report_header,
        summary_html,
        "<h2>SECTION 1.0 — PUBLICATION MAP</h2>",
    ]
    body_parts.extend([
        layer_table,
        "<h2>SECTION 2.0 — REPORT INDEX</h2>",
        "<h3>CATEGORY INDEX</h3>",
        category_table,
        "<h3>WEEKLY REPORTS</h3>",
        week_table,
        "<h3>DAILY REPORTS</h3>",
        daily_table,
        connected_reader,
        "</div>",
        '<div class="wipe-overlay" aria-hidden="true"></div>',
    ])

    full_html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Table of Contents</title>"
        f"<style>{_daily_template_style()}{toc_extra_style()}</style></head><body class='toc-page'>"
        + "\n".join(body_parts)
        + connected_reader_script()
        + _embedded_log_script()
        + page_scrollbar_script()
        + back_to_top_script()
        + latin_footer_script()
        + palette_easter_egg_script(include_stamp=False, include_wipe=True)
        + "</body></html>"
    )
    TOC_HTML_PATH.write_text(full_html, encoding="utf-8")
    TOC_COMPAT_HTML_PATH.write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta http-equiv='refresh' content='0; url=report_144.html'>"
        "<title>Report 144</title></head>"
        "<body><a href='report_144.html'>open report 144</a></body></html>",
        encoding="utf-8",
    )

    qmd_lines = [
        webloader_cover,
        "",
        webloader_intro,
        "",
        webloader_page2,
        "",
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
        "### CATEGORY INDEX",
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
