#!/usr/bin/env python3
"""Render category cumulative reports.

Three categories: experimental, neural, kernel. Each page covers the whole
campaign but splits its trajectory into non-overlapping two-week windows so no
single chart panel becomes a campaign-wide blob. The page reuses the locked
daily visual language. Each category-day datapoint is the best valid row for
that category on that date for its preferred metric.

Usage:
    python3 render_category.py --category neural
    python3 render_category.py --all
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import plot as plot_mod
import render_day
import render_week
from render_day import (
    ASSETS_DIR,
    DAILY_TEMPLATE_STANDARD,
    DB,
    FRAGMENTS_DIR,
    HTML_DIR,
    KERNEL_CAMP,
    KERNEL_FB_RATIO_METRIC,
    KERNEL_FWD_RATIO_METRIC,
    LOCKED_TEMPLATE_STYLE_SHA256,
    OUT_ROOT,
    RESEARCH_END_DATE,
    RESEARCH_START_DATE,
    GITHUB_REMOTES,
    _daily_template_style,
    _embedded_log_script,
    compute_day_index,
    extract_test_rows,
    fetch_day,
    final_submission_records_for_day,
    format_day_index,
    format_metric_value,
    is_valid_metric_value,
    make_alloc_bar_html,
    make_report_h1_html,
    make_report_header_html,
    metric_display_name,
    preview_chart_src,
    report_records_for_date,
    sanitize_public_text,
)


CATEGORY_TEMPLATE_STANDARD = "category-report-v1.0-biweekly-course"
CATEGORIES = ("experimental", "neural", "kernel")
CATEGORY_LABEL = {
    "experimental": "EXPERIMENTAL",
    "neural": "NEURAL",
    "kernel": "KERNEL",
}
CATEGORY_METRIC_PRIORITY: dict[str, tuple[str, ...]] = {
    "kernel": (KERNEL_FB_RATIO_METRIC, KERNEL_FWD_RATIO_METRIC),
    "neural": ("val_bpb", "val_loss"),
    "experimental": ("val_bpb", "val_loss"),
}
CATEGORY_QMD_DIR = OUT_ROOT / "categories"
CATEGORY_HTML_DIR = HTML_DIR / "categories"
CATEGORY_ASSETS_DIR = ASSETS_DIR / "categories"
BIWEEKLY_WINDOW_WEEKS = 2
LOCAL_TO_GIT_SOURCE = {
    "parameter-golf-lab": "git:parameter-golf-lab",
    "open_parameter_golf_junkyard": "git:parameter-golf-lab",
    "parameter-golf-cross-repo": "git:parameter-golf-lab",
    "sota_crawler": "git:sota_crawler",
    "SOTA_FINAL": "git:SOTA_FINAL",
    "sota_rascal": "git:sota_rascal",
    "sota_nueral": "git:sota_nueral",
    "pg_whale": "git:pg_whale",
    "rascal-private": "git:rascal-private",
}
PUBLIC_SOURCE_ROOTS = {
    "parameter-golf-lab": "/home/frosty40/llm_research/parameter-golf-lab",
    "open_parameter_golf_junkyard": "/home/frosty40/llm_research/parameter-golf-lab",
    "parameter-golf-cross-repo": "/home/frosty40/llm_research/parameter-golf-cross-repo",
    "sota_crawler": "/home/frosty40/llm_research/sota_crawler",
    "SOTA_FINAL": "/home/frosty40/llm_research/SOTA_FINAL",
    "sota_rascal": "/home/frosty40/llm_research/sota_rascal",
    "sota_nueral": "/home/frosty40/llm_research/sota_nueral",
    "pg_whale": "/home/frosty40/llm_research/pg_whale",
    "rascal-private": "/home/frosty40/llm_research/rascal-private",
}
PUBLIC_URL_CHECK_CACHE: dict[str, bool] = {}


# ---------- data --------------------------------------------------------------

def all_campaign_dates(conn: sqlite3.Connection) -> list[str]:
    return render_week.all_campaign_dates(conn)


def biweekly_windows(dates: list[str]) -> list[dict[str, Any]]:
    """Pair consecutive research-week windows. Final window may be a single
    week if the campaign ends on an odd week."""
    weekly = render_week.week_windows(dates)
    out: list[dict[str, Any]] = []
    n = 1
    i = 0
    while i < len(weekly):
        merged: list[str] = list(weekly[i])
        weeks = [i + 1]
        if i + 1 < len(weekly):
            merged += list(weekly[i + 1])
            weeks.append(i + 2)
        out.append({
            "window": n,
            "weeks": weeks,
            "dates": merged,
            "start": merged[0],
            "end": merged[-1],
        })
        i += BIWEEKLY_WINDOW_WEEKS
        n += 1
    return out


def window_for_date(windows: list[dict[str, Any]], date: str) -> dict[str, Any] | None:
    for w in windows:
        if w["start"] <= date <= w["end"]:
            return w
    return None


def window_slug(window: dict[str, Any], metric: str | None = None) -> str:
    base = f"window-{window['window']:02d}_{window['start']}_to_{window['end']}"
    if metric:
        return f"{base}_{metric}"
    return base


def _repo_raw_root(github_base: str) -> str:
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/?$", github_base)
    if not m:
        return ""
    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}"


def public_url_exists(url: str) -> bool:
    if not url:
        return False
    if url in PUBLIC_URL_CHECK_CACHE:
        return PUBLIC_URL_CHECK_CACHE[url]
    req = Request(url, method="HEAD", headers={"User-Agent": "research-collator"})
    try:
        with urlopen(req, timeout=4) as resp:
            ok = 200 <= int(resp.status) < 400
    except Exception:
        ok = False
    PUBLIC_URL_CHECK_CACHE[url] = ok
    return ok


def _public_rel_path(source_label: str, abs_path: str, rel_path: str) -> str:
    if rel_path:
        return rel_path.strip("/")
    root = PUBLIC_SOURCE_ROOTS.get(source_label)
    if root and abs_path.startswith(root.rstrip("/") + "/"):
        return abs_path[len(root.rstrip("/")) + 1:]
    return ""


def tracked_commit_for_path(source_label: str, public_rel: str) -> dict[str, str]:
    root = PUBLIC_SOURCE_ROOTS.get(source_label)
    git_label = LOCAL_TO_GIT_SOURCE.get(source_label)
    base = GITHUB_REMOTES.get(git_label or "", "")
    if not root or not git_label or not base or not public_rel:
        return {}
    try:
        sha = subprocess.check_output(
            ["git", "-C", root, "rev-list", "-n", "1", "--all", "--", public_rel],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return {}
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return {}
    try:
        title = subprocess.check_output(
            ["git", "-C", root, "log", "-1", "--format=%s", sha],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        title = ""
    return {
        "sha": sha,
        "short_sha": sha[:7],
        "title": title,
        "url": f"{base}/commit/{sha}",
        "base": base,
        "rel_path": public_rel,
    }


def nearest_public_commit(conn: sqlite3.Connection,
                          source_label: str,
                          mtime_iso: str) -> dict[str, str]:
    git_label = LOCAL_TO_GIT_SOURCE.get(source_label)
    if not git_label or not mtime_iso:
        return {}
    row = conn.execute(
        """
        SELECT rel_path, title, mtime_iso
        FROM artifacts
        WHERE source_label = ?
          AND file_kind = 'git_commit'
          AND ABS(julianday(mtime_iso) - julianday(?)) <= 2.0
        ORDER BY ABS(julianday(mtime_iso) - julianday(?)) ASC
        LIMIT 1
        """,
        (git_label, mtime_iso, mtime_iso),
    ).fetchone()
    if not row:
        return {}
    sha = str(row["rel_path"] or "").strip()
    base = GITHUB_REMOTES.get(git_label, "")
    if not sha or not base:
        return {}
    return {
        "sha": sha,
        "short_sha": sha[:7],
        "title": str(row["title"] or ""),
        "time": str(row["mtime_iso"] or ""),
        "url": f"{base}/commit/{sha}",
        "base": base,
    }


def public_artifact_links(conn: sqlite3.Connection,
                          source_label: str,
                          abs_path: str,
                          rel_path: str,
                          mtime_iso: str) -> dict[str, str]:
    if source_label.startswith("git:"):
        sha = rel_path.strip() or abs_path.rsplit("/", 1)[-1].strip()
        base = GITHUB_REMOTES.get(source_label, "")
        if re.fullmatch(r"[0-9a-f]{40}", sha) and base:
            return {
                "sha": sha,
                "short_sha": sha[:7],
                "title": "",
                "time": mtime_iso,
                "url": f"{base}/commit/{sha}",
                "base": base,
            }
        return {}
    public_rel = _public_rel_path(source_label, abs_path, rel_path)
    exact = tracked_commit_for_path(source_label, public_rel)
    if exact:
        encoded_path = quote(public_rel, safe="/")
        raw_root = _repo_raw_root(exact["base"])
        if raw_root:
            raw_url = f"{raw_root}/{exact['sha']}/{encoded_path}"
            if public_url_exists(raw_url):
                exact["blob_url"] = f"{exact['base']}/blob/{exact['sha']}/{encoded_path}"
                exact["raw_url"] = raw_url
        return exact
    commit = nearest_public_commit(conn, source_label, mtime_iso)
    if not commit or not public_rel:
        return commit
    commit["rel_path"] = public_rel
    return commit


def condition_text_for_path(abs_path: str) -> str:
    if not abs_path:
        return ""
    path = Path(abs_path)
    search_dirs = [path.parent, *list(path.parents)[:6]]
    seen: set[Path] = set()
    for directory in search_dirs:
        if directory in seen:
            continue
        seen.add(directory)
        for name in ("RESOLVED_CONDITION.txt", "CONDITION.md"):
            candidate = directory / name
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            text = sanitize_public_text(text)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                return text[:420]
    return ""


def _category_rows_for_day(conn: sqlite3.Connection,
                           date: str,
                           category: str,
                           metric: str) -> list[dict[str, Any]]:
    raw = fetch_day(conn, date)
    records = report_records_for_date(date, raw)
    if date == RESEARCH_END_DATE:
        final = final_submission_records_for_day(date, records)
        if final:
            records = final
    rows = extract_test_rows(records, metric, None)
    out = []
    for r in rows:
        if r.get("camp") != category:
            continue
        if not is_valid_metric_value(metric, r.get("value")):
            continue
        out.append(r)
    return out


def build_category_datapoints(conn: sqlite3.Connection,
                              dates: list[str],
                              category: str,
                              windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One datapoint per (category, date) where this category has a valid row.

    The metric is chosen by priority: first metric in
    CATEGORY_METRIC_PRIORITY[category] that yields ≥1 valid row. If none
    qualify on a date, that date contributes no datapoint to this category."""
    points: list[dict[str, Any]] = []
    metrics = CATEGORY_METRIC_PRIORITY[category]
    for date in dates:
        chosen: tuple[str, list[dict[str, Any]]] | None = None
        for metric in metrics:
            cat_rows = _category_rows_for_day(conn, date, category, metric)
            if cat_rows:
                chosen = (metric, cat_rows)
                break
        if not chosen:
            continue
        metric, cat_rows = chosen
        cat_rows.sort(key=lambda r: r["value"])
        best = cat_rows[0]
        source_records = best.get("source_records") or []
        source_ref = source_records[0] if source_records else {}
        public_source = public_artifact_links(
            conn,
            source_label=best.get("source_label") or "",
            abs_path=best.get("abs_path") or "",
            rel_path=source_ref.get("rel_path") or "",
            mtime_iso=source_ref.get("mtime_iso") or "",
        )
        win = window_for_date(windows, date)
        points.append({
            "date": date,
            "category": category,
            "metric": metric,
            "metric_display": metric_display_name(metric),
            "value": float(best["value"]),
            "value_display": format_metric_value(metric, best["value"]),
            "title": (best.get("title") or "").strip(),
            "abs_path": best.get("abs_path") or "",
            "rel_path": source_ref.get("rel_path") or "",
            "source_label": best.get("source_label") or "",
            "public_source": public_source,
            "condition_text": condition_text_for_path(best.get("abs_path") or ""),
            "n_category_rows": len(cat_rows),
            "n_runs": int(best.get("n_runs") or 1),
            "window": win["window"] if win else None,
            "window_start": win["start"] if win else None,
            "window_end": win["end"] if win else None,
        })
    return points


def family_of_row(row: dict[str, Any]) -> str:
    title = row.get("title") or ""
    path = row.get("abs_path") or ""
    for fam_name, pat in render_day.ARCH_FAMILIES:
        if render_day._arch_family_matches(pat, title, path):
            return fam_name
    return "Other"


def category_family_rows(conn: sqlite3.Connection,
                         dates: list[str],
                         category: str) -> tuple[list[dict[str, Any]], str | None]:
    """All valid measured rows for a category on each date's chosen metric.

    This keeps the category report's scale contract: families are compared on
    the same metric that the category datapoint would use for that date.
    """
    out: list[dict[str, Any]] = []
    metric_counts: Counter[str] = Counter()
    for date in dates:
        chosen: tuple[str, list[dict[str, Any]]] | None = None
        for metric in CATEGORY_METRIC_PRIORITY[category]:
            rows = _category_rows_for_day(conn, date, category, metric)
            if rows:
                chosen = (metric, rows)
                break
        if not chosen:
            continue
        metric, rows = chosen
        metric_counts[metric] += len(rows)
        for row in rows:
            item = dict(row)
            item["date"] = date
            item["metric"] = metric
            item["family"] = family_of_row(item)
            out.append(item)
    primary_metric = metric_counts.most_common(1)[0][0] if metric_counts else None
    return out, primary_metric


def make_category_family_table_html(rows: list[dict[str, Any]],
                                    primary_metric: str | None) -> str:
    if not rows or not primary_metric:
        return (
            "<p class='muted'>NO ARCHITECTURE FAMILY ROWS WERE AVAILABLE "
            "FOR THIS CATEGORY.</p>"
        )
    by_family: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_family.setdefault(str(row.get("family") or "Other"), []).append(row)

    def family_sort(item: tuple[str, list[dict[str, Any]]]) -> tuple[int, str]:
        name, fam_rows = item
        return (-len(fam_rows), render_day.public_arch_label(name))

    table = [
        "<table class='bpb-table'><thead><tr>"
        "<th>architecture / test surface</th><th>rows</th><th>days</th>"
        f"<th>best {html.escape(metric_display_name(primary_metric))}</th>"
        "<th>median</th><th>range</th><th>first</th><th>last</th>"
        "</tr></thead><tbody>"
    ]
    for family, fam_rows in sorted(by_family.items(), key=family_sort):
        metric_rows = [
            r for r in fam_rows
            if r.get("metric") == primary_metric
            and is_valid_metric_value(primary_metric, r.get("value"))
        ]
        if not metric_rows:
            continue
        vals = sorted(float(r["value"]) for r in metric_rows)
        n = len(vals)
        med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
        dates = sorted({str(r.get("date") or "") for r in fam_rows if r.get("date")})
        date_href = f"../{html.escape(dates[0])}.html" if dates else "#"
        last_href = f"../{html.escape(dates[-1])}.html" if dates else "#"
        table.append(
            "<tr>"
            f"<td>{html.escape(render_day.public_arch_label(family).upper())}</td>"
            f"<td>{len(fam_rows)}</td>"
            f"<td>{len(dates)}</td>"
            f"<td>{format_metric_value(primary_metric, vals[0])}</td>"
            f"<td>{format_metric_value(primary_metric, med)}</td>"
            f"<td>{format_metric_value(primary_metric, vals[0])} - "
            f"{format_metric_value(primary_metric, vals[-1])}</td>"
            f"<td><a class='category-action' href='{date_href}'>{html.escape(dates[0]) if dates else '—'}</a></td>"
            f"<td><a class='category-action' href='{last_href}'>{html.escape(dates[-1]) if dates else '—'}</a></td>"
            "</tr>"
        )
    table.append("</tbody></table>")
    return "\n".join(table)


# ---------- rendering helpers -------------------------------------------------

def category_action_style() -> str:
    return """
    .category-action,
    .test-runs-table td a {
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
        user-select: none;
        border-radius: 0;
    }
    .category-action::before,
    .test-runs-table td a::before {
        content: "";
        width: 8px;
        height: 8px;
        flex: 0 0 auto;
        background: var(--bg);
    }
    .category-action:hover,
    .category-action:focus-visible,
    .test-runs-table td a:hover,
    .test-runs-table td a:focus-visible {
        background: var(--rule-hi);
        color: var(--bg);
        border-bottom-color: var(--rule-hi);
        outline: 1px solid var(--rule-hi);
        outline-offset: 2px;
    }
    .log-panel a,
    .log-panel a.category-action {
        border-color: var(--bg);
        background: var(--bg);
        color: var(--rule-hi);
    }
    .log-panel a::before,
    .log-panel a.category-action::before {
        background: var(--rule-hi);
    }
    .log-panel a:hover,
    .log-panel a:focus-visible,
    .log-panel a.category-action:hover,
    .log-panel a.category-action:focus-visible {
        border-bottom-color: var(--bg);
        background: var(--bg);
        color: var(--rule-hi);
        outline: 1px solid var(--bg);
        outline-offset: 2px;
    }
    """


def public_source_buttons_html(point: dict[str, Any]) -> str:
    source = point.get("public_source") or {}
    buttons: list[str] = []
    if source.get("raw_url"):
        buttons.append(
            f"<a class='category-action' href='{html.escape(source['raw_url'], quote=True)}' download>"
            "download file</a>",
        )
    if not buttons:
        return ""
    return (
        "<div class='log-meta'><strong>public evidence</strong>: "
        + " ".join(buttons)
        + "</div>"
    )


def public_source_meta_html(point: dict[str, Any]) -> str:
    source = point.get("public_source") or {}
    lines: list[str] = []
    if source.get("short_sha"):
        title = sanitize_public_text(source.get("title") or "")
        lines.append(
            f"<div class='log-meta'><strong>commit</strong>: "
            f"<code>{html.escape(source['short_sha'])}</code>"
            + (f" - {html.escape(title[:180])}" if title else "")
            + "</div>"
        )
    if source.get("blob_url") and point.get("rel_path"):
        lines.append(
            f"<div class='log-meta'><strong>file path</strong>: "
            f"<code>{html.escape(point['rel_path'])}</code></div>"
        )
    if point.get("condition_text"):
        lines.append(
            f"<div class='log-meta'><strong>condition</strong>: "
            f"{html.escape(point['condition_text'])}</div>"
        )
    return "".join(lines)


def points_for_window(points: list[dict[str, Any]],
                      window: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in points if window["start"] <= p["date"] <= window["end"]]


def metrics_in_window(points: list[dict[str, Any]]) -> list[str]:
    """Metrics ordered by the date of their first datapoint in the window.

    Stacked charts read top-to-bottom as oldest-to-newest so the panel order
    matches the chronology of the listing below them. Assumes `points` is
    already sorted by date ascending.
    """
    seen: list[str] = []
    for p in points:
        m = p["metric"]
        if m not in seen:
            seen.append(m)
    return seen


def make_category_summary_html(category: str,
                               points: list[dict[str, Any]],
                               windows: list[dict[str, Any]]) -> str:
    if not points:
        body = (
            f"<p>No measured {CATEGORY_LABEL[category].lower()} datapoints "
            f"landed across the campaign window.</p>"
        )
    else:
        active_days = len({p["date"] for p in points})
        metric_counter = Counter(p["metric"] for p in points)
        metric_blurb = "  ·  ".join(
            f"{metric_display_name(m)} (×{n})"
            for m, n in metric_counter.most_common()
        )
        first_date = min(p["date"] for p in points)
        last_date = max(p["date"] for p in points)
        active_windows = len({p["window"] for p in points if p["window"]})
        body = (
            f"<p>This page rolls up "
            f"<strong>{len(points)} {CATEGORY_LABEL[category].lower()} "
            f"category datapoints</strong> across "
            f"<strong>{active_days} active research days</strong> "
            f"({html.escape(first_date)} → {html.escape(last_date)}), grouped "
            f"into <strong>{active_windows} of {len(windows)} two-week "
            f"windows</strong>. Each datapoint is the best valid "
            f"{CATEGORY_LABEL[category].lower()} row for its date on that "
            f"day's preferred metric.</p>"
            f"<p>Metrics used: <strong>{html.escape(metric_blurb)}</strong>. "
            f"BPB-style and kernel-ratio metrics are never plotted on the "
            f"same y-axis. Each window's chart panel covers at most two "
            f"research weeks so progress stays readable inside the panel.</p>"
        )
        if category == "neural":
            body += (
                f"<p>Neural BPB validity convention: values below "
                f"<strong>{render_day.INVALID_VAL_BPB_FLOOR:.2f}</strong> "
                f"are treated as eval/loader-error readings.</p>"
            )
    return (
        '<aside class="day-summary">'
        '<div class="ds-key">CATEGORY SUMMARY</div>'
        f'<div class="ds-body">{body}</div></aside>'
    )


def render_window_section(conn: sqlite3.Connection,
                          category: str,
                          window: dict[str, Any],
                          window_points: list[dict[str, Any]],
                          asset_dir: Path) -> dict[str, Any]:
    metrics = metrics_in_window(window_points)
    chart_paths: list[str] = []
    chart_panel_meta: list[dict[str, Any]] = []
    for metric in metrics:
        metric_points = [p for p in window_points if p["metric"] == metric]
        if not metric_points:
            continue
        chart_input = []
        for idx, p in enumerate(metric_points, start=1):
            chart_input.append({
                "date": p["date"],
                "value": p["value"],
                "camp": category,
                "title": sanitize_public_text(p["title"] or p["date"]),
                "n": idx,
            })
        slug = window_slug(window, metric)
        out_path = asset_dir / f"{slug}.png"
        path, n = plot_mod.week_chart(
            out_path,
            week_label=(
                f"{CATEGORY_LABEL[category]} · WINDOW "
                f"{window['window']:02d} · {window['start']} TO {window['end']}"
            ),
            daily_points=chart_input,
            metric_name=metric_display_name(metric),
        )
        chart_paths.append(path)
        chart_panel_meta.append({"metric": metric, "path": path, "n": n})

    return {
        "window": window,
        "metrics": metrics,
        "chart_paths": chart_paths,
        "chart_panels": chart_panel_meta,
        "n_points": len(window_points),
        "active_days": len({p["date"] for p in window_points}),
    }


def make_window_table_html(category: str,
                           window: dict[str, Any],
                           window_points: list[dict[str, Any]]) -> str:
    if not window_points:
        return (
            f"<p class='muted'>NO {CATEGORY_LABEL[category]} DATAPOINTS "
            f"INSIDE WINDOW {window['window']:02d}.</p>"
        )
    rows = [
        "<table class='test-runs-table'><thead><tr>"
        "<th>#</th><th>DATE</th><th>METRIC</th><th>BEST</th>"
        "<th>ROWS</th><th>TITLE</th><th>OPEN</th>"
        "</tr></thead><tbody>"
    ]
    for idx, p in enumerate(window_points, start=1):
        title = sanitize_public_text(p["title"] or "(untitled)")
        rows.append(
            "<tr>"
            f"<td><strong>{idx}</strong></td>"
            f"<td>{html.escape(p['date'])}</td>"
            f"<td>{html.escape(p['metric_display'])}</td>"
            f"<td>{html.escape(p['value_display'])}</td>"
            f"<td>{int(p['n_category_rows'])}</td>"
            f"<td>{html.escape(title[:120])}</td>"
            "<td class='open-cell'><details class='log-toggle'>"
            "<summary>provenance</summary></details></td>"
            "</tr>"
        )
        rows.append(
            "<tr class='log-detail-row'><td colspan='7'>"
            "<div class='log-panel'>"
            "<div class='log-meta'><strong>category datapoint</strong></div>"
            f"<div class='log-meta'><strong>category</strong>: "
            f"{html.escape(CATEGORY_LABEL[category].lower())}</div>"
            f"<div class='log-meta'><strong>window</strong>: "
            f"{window['window']:02d} · {html.escape(window['start'])} → "
            f"{html.escape(window['end'])}</div>"
            f"<div class='log-meta'><strong>date</strong>: "
            f"{html.escape(p['date'])} "
            f"<a class='category-action' href='../{html.escape(p['date'])}.html'>open daily report</a>"
            f"</div>"
            f"<div class='log-meta'><strong>metric</strong>: "
            f"{html.escape(p['metric_display'])} "
            f"(<code>{html.escape(p['metric'])}</code>)</div>"
            f"<div class='log-meta'><strong>best valid value</strong>: "
            f"{html.escape(p['value_display'])}</div>"
            f"<div class='log-meta'><strong>category rows on date</strong>: "
            f"{int(p['n_category_rows'])} (best value shown above)</div>"
            f"<div class='log-meta'><strong>row title</strong>: "
            f"{html.escape(sanitize_public_text(p['title'] or '—')[:200])}</div>"
            f"<div class='log-meta'><strong>source</strong>: "
            f"{html.escape(p['source_label'] or '—')}</div>"
            f"{public_source_buttons_html(p)}"
            f"{public_source_meta_html(p)}"
            "</div></td></tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def make_full_table_html(category: str,
                         points: list[dict[str, Any]]) -> str:
    if not points:
        return (
            f"<p class='muted'>NO {CATEGORY_LABEL[category]} DATAPOINTS "
            f"ACROSS THE CAMPAIGN.</p>"
        )
    rows = [
        "<table class='test-runs-table'><thead><tr>"
        "<th>#</th><th>DATE</th><th>WINDOW</th><th>METRIC</th>"
        "<th>BEST</th><th>ROWS</th><th>TITLE</th><th>OPEN</th>"
        "</tr></thead><tbody>"
    ]
    for idx, p in enumerate(points, start=1):
        win_label = f"{p['window']:02d}" if p["window"] else "—"
        title = sanitize_public_text(p["title"] or "(untitled)")
        rows.append(
            "<tr>"
            f"<td><strong>{idx}</strong></td>"
            f"<td>{html.escape(p['date'])}</td>"
            f"<td>{html.escape(win_label)}</td>"
            f"<td>{html.escape(p['metric_display'])}</td>"
            f"<td>{html.escape(p['value_display'])}</td>"
            f"<td>{int(p['n_category_rows'])}</td>"
            f"<td>{html.escape(title[:120])}</td>"
            "<td class='open-cell'><details class='log-toggle'>"
            "<summary>provenance</summary></details></td>"
            "</tr>"
        )
        rows.append(
            "<tr class='log-detail-row'><td colspan='8'>"
            "<div class='log-panel'>"
            "<div class='log-meta'><strong>category datapoint</strong></div>"
            f"<div class='log-meta'><strong>category</strong>: "
            f"{html.escape(CATEGORY_LABEL[category].lower())}</div>"
            f"<div class='log-meta'><strong>window</strong>: "
            f"{html.escape(win_label)} ("
            f"{html.escape(p['window_start'] or '—')} → "
            f"{html.escape(p['window_end'] or '—')})</div>"
            f"<div class='log-meta'><strong>date</strong>: "
            f"{html.escape(p['date'])} "
            f"<a class='category-action' href='../{html.escape(p['date'])}.html'>open daily report</a>"
            f"</div>"
            f"<div class='log-meta'><strong>metric</strong>: "
            f"{html.escape(p['metric_display'])} "
            f"(<code>{html.escape(p['metric'])}</code>)</div>"
            f"<div class='log-meta'><strong>best valid value</strong>: "
            f"{html.escape(p['value_display'])}</div>"
            f"<div class='log-meta'><strong>category rows on date</strong>: "
            f"{int(p['n_category_rows'])}</div>"
            f"<div class='log-meta'><strong>row title</strong>: "
            f"{html.escape(sanitize_public_text(p['title'] or '—')[:200])}</div>"
            f"<div class='log-meta'><strong>source</strong>: "
            f"{html.escape(p['source_label'] or '—')}</div>"
            f"{public_source_buttons_html(p)}"
            f"{public_source_meta_html(p)}"
            "</div></td></tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def make_lazy_full_table_html(category: str,
                              points: list[dict[str, Any]]) -> str:
    if not points:
        return make_full_table_html(category, points)
    FRAGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    fragment_path = FRAGMENTS_DIR / f"category_{category}_full_table.html"
    fragment_path.write_text(make_full_table_html(category, points), encoding="utf-8")
    fragment_href = f"../fragments/{fragment_path.name}"
    target_id = f"category-{category}-full-table"
    return (
        "<div class='lazy-test-shell'>"
        "<button class='lazy-test-load' type='button' "
        f"data-lazy-fragment='{html.escape(fragment_href, quote=True)}' "
        f"data-target='{html.escape(target_id, quote=True)}' "
        "data-load-label='load full table' data-hide-label='hide full table' "
        "data-loading-label='loading full table' data-error-label='table load failed'>load full table</button>"
        f"<div id='{html.escape(target_id, quote=True)}' class='lazy-test-target' hidden></div>"
        "</div>"
    )


# ---------- per-category render ----------------------------------------------

def render_category(conn: sqlite3.Connection,
                    category: str,
                    dates: list[str],
                    windows: list[dict[str, Any]]) -> dict[str, Any]:
    if category not in CATEGORIES:
        raise SystemExit(f"unknown category: {category}")

    CATEGORY_QMD_DIR.mkdir(parents=True, exist_ok=True)
    CATEGORY_HTML_DIR.mkdir(parents=True, exist_ok=True)
    asset_dir = CATEGORY_ASSETS_DIR / category
    asset_dir.mkdir(parents=True, exist_ok=True)

    points = build_category_datapoints(conn, dates, category, windows)
    points.sort(key=lambda p: p["date"])
    family_rows, family_metric = category_family_rows(conn, dates, category)
    family_counts = Counter(str(r.get("family") or "Other") for r in family_rows)
    arch_families = sorted(family_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    architecture_recipe_html, rendered_architecture_recipes = (
        render_day.make_architecture_recipe_html(arch_families)
    )

    summary_html = make_category_summary_html(category, points, windows)

    window_sections: list[dict[str, Any]] = []
    total_chart_panels = 0
    for window in windows:
        wp = points_for_window(points, window)
        if not wp:
            continue
        section = render_window_section(conn, category, window, wp, asset_dir)
        section["table_html"] = make_window_table_html(category, window, wp)
        section["points"] = wp
        window_sections.append(section)
        total_chart_panels += len(section["chart_panels"])

    metric_counter = Counter(p["metric"] for p in points)
    metric_text = "  ·  ".join(
        f"{metric_display_name(m)} (×{n})" for m, n in metric_counter.most_common()
    ) or "—"
    active_dates = sorted({p["date"] for p in points})
    header_fields = [
        ("CATEGORY", CATEGORY_LABEL[category]),
        ("DATES", f"{RESEARCH_START_DATE} TO {RESEARCH_END_DATE}"),
        ("WINDOWS", f"{len(window_sections)} ACTIVE / {len(windows)} TOTAL"),
        ("ACTIVE DAYS", str(len(active_dates))),
        ("DATAPOINTS", str(len(points))),
        ("PRIMARY METRICS", metric_text),
    ]
    by_camp_for_alloc = {category: len(points)} if points else {}
    report_header = make_report_header_html(
        header_fields,
        alloc_bar=make_alloc_bar_html(by_camp_for_alloc) if by_camp_for_alloc else None,
    )

    h1_html = make_report_h1_html(
        f"{CATEGORY_LABEL[category]} RESEARCH REPORT",
        "CAMPAIGN",
        home_href="../index.html",
        master_href=f"../report_144.html#reader=categories/{category}.html",
    )

    # ----- HTML body -----
    body_parts = [h1_html, report_header,
                  "<h2>SECTION 1.0 — BI-WEEKLY TRAJECTORY</h2>",
                  summary_html]
    if family_rows:
        body_parts.extend([
            "<h2>SECTION 1.5 — ARCHITECTURE / TEST SURFACES</h2>",
            make_category_family_table_html(family_rows, family_metric),
        ])
        if architecture_recipe_html:
            body_parts.append(architecture_recipe_html)
    if not window_sections:
        body_parts.append(
            f"<p class='muted'>NO {CATEGORY_LABEL[category]} DATAPOINTS "
            f"WERE PRODUCED IN ANY TWO-WEEK WINDOW.</p>"
        )
    for section in window_sections:
        win = section["window"]
        body_parts.append(
            f"<h3>WINDOW {win['window']:02d} · {html.escape(win['start'])} "
            f"TO {html.escape(win['end'])}</h3>"
        )
        for panel in section["chart_panels"]:
            chart_src = preview_chart_src(panel["path"], "../index.html")
            body_parts.append(
                "<figure>"
                f"<img src='{html.escape(chart_src, quote=True)}' "
                f"alt='{html.escape(CATEGORY_LABEL[category])} window "
                f"{win['window']:02d} {panel['metric']}'/>"
                "</figure>"
            )
        body_parts.append(section["table_html"])

    body_parts.extend([
        "<h2>SECTION 2.0 — CATEGORY DAILY DATAPOINTS</h2>",
        make_lazy_full_table_html(category, points),
    ])

    full_html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{CATEGORY_LABEL[category].title()} Research Report</title>"
        f"<style>{_daily_template_style()}{category_action_style()}</style></head><body>"
        + "\n".join(body_parts)
        + _embedded_log_script()
        + "</body></html>"
    )
    html_path = CATEGORY_HTML_DIR / f"{category}.html"
    html_path.write_text(full_html, encoding="utf-8")

    # ----- QMD mirror (markdown / image refs only) -----
    qmd_lines = [
        h1_html,
        "",
        report_header,
        "",
        "## SECTION 1.0 — BI-WEEKLY TRAJECTORY",
        "",
        summary_html,
        "",
    ]
    if family_rows:
        qmd_lines += [
            "## SECTION 1.5 — ARCHITECTURE / TEST SURFACES",
            "",
            make_category_family_table_html(family_rows, family_metric),
            "",
        ]
        if architecture_recipe_html:
            qmd_lines += [architecture_recipe_html, ""]
    if not window_sections:
        qmd_lines.append(
            f"<p class='muted'>NO {CATEGORY_LABEL[category]} DATAPOINTS "
            f"WERE PRODUCED IN ANY TWO-WEEK WINDOW.</p>"
        )
        qmd_lines.append("")
    for section in window_sections:
        win = section["window"]
        qmd_lines.append(
            f"### WINDOW {win['window']:02d} — {win['start']} to {win['end']}"
        )
        qmd_lines.append("")
        for panel in section["chart_panels"]:
            relp = os.path.relpath(panel["path"], CATEGORY_QMD_DIR)
            qmd_lines.append(
                f"![{CATEGORY_LABEL[category]} window {win['window']:02d} "
                f"{panel['metric']}]({relp})"
            )
            qmd_lines.append("")
        qmd_lines.append(section["table_html"])
        qmd_lines.append("")
    qmd_lines += [
        "## SECTION 2.0 — CATEGORY DAILY DATAPOINTS",
        "",
        make_full_table_html(category, points),
        "",
    ]
    qmd_path = CATEGORY_QMD_DIR / f"{category}.qmd"
    qmd_path.write_text("\n".join(qmd_lines), encoding="utf-8")

    return {
        "category": category,
        "label": CATEGORY_LABEL[category],
        "html_path": str(html_path),
        "qmd_path": str(qmd_path),
        "asset_dir": str(asset_dir),
        "n_points": len(points),
        "active_days": len(active_dates),
        "windows_total": len(windows),
        "windows_active": len(window_sections),
        "chart_panels": total_chart_panels,
        "metrics_used": list(metric_counter.keys()),
        "architecture_recipes_rendered": rendered_architecture_recipes,
        "architecture_families": [
            {"name": name, "label": render_day.public_arch_label(name), "count": count}
            for name, count in arch_families
        ],
        "template_standard": CATEGORY_TEMPLATE_STANDARD,
        "daily_template_standard": DAILY_TEMPLATE_STANDARD,
        "template_style_sha256": LOCKED_TEMPLATE_STYLE_SHA256,
    }


# ---------- index -------------------------------------------------------------

def render_category_index(summaries: list[dict[str, Any]],
                          windows: list[dict[str, Any]]) -> str:
    CATEGORY_HTML_DIR.mkdir(parents=True, exist_ok=True)
    rows = [
        "<table class='test-runs-table'><thead><tr>"
        "<th>CATEGORY</th><th>ACTIVE DAYS</th><th>DATAPOINTS</th>"
        "<th>WINDOWS (ACTIVE / TOTAL)</th><th>CHART PANELS</th>"
        "<th>METRICS</th><th>OPEN</th>"
        "</tr></thead><tbody>"
    ]
    for s in summaries:
        metric_blurb = "  ·  ".join(
            metric_display_name(m) for m in s.get("metrics_used", [])
        ) or "—"
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(s['label'])}</strong></td>"
            f"<td>{int(s['active_days'])}</td>"
            f"<td>{int(s['n_points'])}</td>"
            f"<td>{int(s['windows_active'])} / {int(s['windows_total'])}</td>"
            f"<td>{int(s['chart_panels'])}</td>"
            f"<td>{html.escape(metric_blurb)}</td>"
            f"<td><a class='category-action' href='{html.escape(Path(s['html_path']).name)}'>"
            f"open category</a></td>"
            "</tr>"
        )
    rows.append("</tbody></table>")

    h1_html = make_report_h1_html(
        "CATEGORY RESEARCH REPORTS",
        "INDEX",
        home_href="../index.html",
        master_href="../report_144.html#reader=categories/index.html",
    )
    header_fields = [
        ("CATEGORIES", str(len(summaries))),
        ("DATES", f"{RESEARCH_START_DATE} TO {RESEARCH_END_DATE}"),
        ("WINDOWS", f"{len(windows)} TWO-WEEK"),
        ("TEMPLATE", CATEGORY_TEMPLATE_STANDARD),
        ("DAILY STANDARD", DAILY_TEMPLATE_STANDARD),
        ("WEEKLY STANDARD", render_week.WEEKLY_TEMPLATE_STANDARD),
    ]
    body = "\n".join([
        h1_html,
        make_report_header_html(header_fields),
        "<h2>SECTION 1.0 — CATEGORY INDEX</h2>",
        "<aside class='day-summary'><div class='ds-key'>CATEGORY INDEX</div>"
        "<div class='ds-body'><p>Each row opens one category cumulative "
        "report. Each category page splits the campaign into non-overlapping "
        "two-week windows so chart panels stay readable.</p></div></aside>",
        "<h2>SECTION 2.0 — CATEGORY REPORTS</h2>",
        "\n".join(rows),
    ])
    html_path = CATEGORY_HTML_DIR / "index.html"
    html_path.write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Category Research Reports</title>"
        f"<style>{_daily_template_style()}{category_action_style()}</style></head><body>"
        + body
        + "</body></html>",
        encoding="utf-8",
    )
    return str(html_path)


def render_all_categories(dates: list[str]) -> list[dict[str, Any]]:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        windows = biweekly_windows(dates)
        summaries: list[dict[str, Any]] = []
        for category in CATEGORIES:
            summaries.append(render_category(conn, category, dates, windows))
        render_category_index(summaries, windows)
        return summaries
    finally:
        conn.close()


# ---------- CLI ---------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--category", choices=CATEGORIES,
                        help="render a single category")
    target.add_argument("--all", action="store_true",
                        help="render every category and refresh the index")
    args = parser.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        dates = all_campaign_dates(conn)
    finally:
        conn.close()

    if args.all:
        summaries = render_all_categories(dates)
        print(json.dumps({
            "categories": [s["category"] for s in summaries],
            "index": str(CATEGORY_HTML_DIR / "index.html"),
            "datapoints": {s["category"]: s["n_points"] for s in summaries},
        }, indent=2))
        return

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        windows = biweekly_windows(dates)
        summary = render_category(conn, args.category, dates, windows)
    finally:
        conn.close()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
