#!/usr/bin/env python3
"""Row-level daily-report accuracy audit.

This is the "wrong test on wrong day" gate. It is intentionally deterministic:
SQLite + renderer provenance + regex date evidence. No LLM, no embeddings, no
network. Use RAG later only as a human-facing search surface after this exact
audit has narrowed the suspect rows.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import render_all  # noqa: E402
import render_day  # noqa: E402

DATE_TOKEN_RE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")
OUTPUT_DIR = render_day.OUT_ROOT / "audit"


class Audit:
    def __init__(self, sample_limit: int) -> None:
        self.sample_limit = sample_limit
        self.fatal: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.day_summaries: list[dict[str, Any]] = []
        self.rows_checked = 0

    def issue(self, severity: str, code: str, date: str, message: str,
              row: dict | None = None, source: dict | None = None,
              detail: dict[str, Any] | None = None) -> None:
        item: dict[str, Any] = {
            "severity": severity,
            "code": code,
            "date": date,
            "message": message,
        }
        if row is not None:
            item["row"] = {
                "n": row.get("n"),
                "title": row.get("title"),
                "time_iso": row.get("time_iso"),
                "camp": row.get("camp"),
                "value": row.get("value"),
                "source_label": row.get("source_label"),
                "abs_path": row.get("abs_path"),
            }
        if source is not None:
            item["source"] = {
                "id": source.get("id"),
                "file_kind": source.get("file_kind"),
                "source_label": source.get("source_label"),
                "best_date": source.get("best_date"),
                "time_iso": source.get("time_iso"),
                "mtime_iso": source.get("mtime_iso"),
                "abs_path": source.get("abs_path"),
            }
        if detail:
            item["detail"] = detail
        if severity == "fatal":
            self.fatal.append(item)
        else:
            self.warnings.append(item)


def valid_date(y: str, mo: str, d: str) -> str | None:
    try:
        date = dt.date(int(y), int(mo), int(d))
    except ValueError:
        return None
    if 2024 <= date.year <= 2030:
        return date.isoformat()
    return None


def date_tokens(text: str | None) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in DATE_TOKEN_RE.finditer(text):
        date = valid_date(m.group(1), m.group(2), m.group(3))
        if date and date not in seen:
            out.append(date)
            seen.add(date)
    return out


def iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        if re.match(r"^20\d{2}-\d{2}-\d{2}", value):
            return value[:10]
    return None


def metrics_dict(source: dict) -> dict[str, Any]:
    raw = source.get("metrics_json")
    if raw is None:
        abs_path = source.get("abs_path") or ""
        if abs_path and abs_path.startswith("/") and os.path.isfile(abs_path):
            return {}
    try:
        obj = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def metric_run_start_date(md: dict[str, Any]) -> str | None:
    fs = md.get("filename_run_start")
    if not isinstance(fs, str) or len(fs) != 15 or fs[8] != "T":
        return None
    return valid_date(fs[:4], fs[4:6], fs[6:8])


def source_signals(source: dict) -> dict[str, Any]:
    abs_path = source.get("abs_path") or ""
    rel_path = source.get("rel_path") or ""
    basename_dates = []
    for value in (os.path.basename(abs_path), os.path.basename(rel_path)):
        for date in date_tokens(value):
            if date not in basename_dates:
                basename_dates.append(date)
    path_dates = date_tokens(f"{abs_path} {rel_path}")
    title_dates = date_tokens(source.get("title") or "")
    md = metrics_dict(source)
    return {
        "best_date": source.get("best_date"),
        "time_iso_date": iso_date(source.get("time_iso")),
        "mtime_local_date": render_day._mtime_local_date(source),  # repo-local verifier hook
        "basename_dates": basename_dates,
        "path_dates": path_dates,
        "title_dates": title_dates,
        "metric_run_start_date": metric_run_start_date(md),
        "val_bpb_source": source.get("val_bpb_source") or md.get("val_bpb_source") or "unknown",
    }


def row_source_records(row: dict) -> list[dict]:
    sources = row.get("source_records") or []
    if sources:
        return sources
    return [{
        "id": None,
        "title": row.get("title"),
        "metric": None,
        "metric_values": [row.get("value")],
        "selected_value": row.get("value"),
        "time_iso": row.get("time_iso"),
        "best_date": None,
        "mtime_iso": None,
        "source_label": row.get("source_label"),
        "file_kind": None,
        "camp": row.get("camp"),
        "abs_path": row.get("abs_path"),
        "rel_path": None,
        "val_bpb_source": row.get("val_bpb_source"),
    }]


def is_commit_only(row: dict) -> bool:
    sources = row_source_records(row)
    return bool(sources) and all(s.get("file_kind") == "git_commit" for s in sources)


def count_metric_values(row: dict) -> int:
    total = 0
    for source in row_source_records(row):
        vals = source.get("metric_values") or []
        total += len(vals)
    return total


def audit_source(audit: Audit, date: str, metric: str, row: dict, source: dict) -> None:
    signals = source_signals(source)
    best = signals["best_date"]
    if best != date:
        audit.issue(
            "fatal", "source_best_date_mismatch", date,
            "source record best_date does not match rendered day",
            row=row, source=source, detail=signals,
        )

    strong = signals["metric_run_start_date"]
    if strong and strong != date:
        audit.issue(
            "fatal", "run_start_date_mismatch", date,
            "filename_run_start metric disagrees with rendered day",
            row=row, source=source, detail=signals,
        )

    basename_dates = signals["basename_dates"]
    if basename_dates and date not in basename_dates and source.get("file_kind") != "git_commit":
        audit.issue(
            "fatal", "basename_date_mismatch", date,
            "artifact basename contains a different run date",
            row=row, source=source, detail=signals,
        )

    path_dates = signals["path_dates"]
    if path_dates and date not in path_dates and signals["mtime_local_date"] != date:
        audit.issue(
            "warn", "weak_date_evidence", date,
            "path dates and local mtime do not independently support rendered day",
            row=row, source=source, detail=signals,
        )

    if render_day.is_kernel_metric(metric) and row.get("camp") != render_day.KERNEL_CAMP:
        audit.issue(
            "fatal", "kernel_metric_not_kernel_classified", date,
            "kernel headline metric row is not classified as kernel",
            row=row, source=source, detail=signals,
        )
    if source.get("camp") == "daily_grind":
        audit.issue(
            "fatal", "daily_grind_test_row", date,
            "daily_grind source reached Section 2",
            row=row, source=source, detail=signals,
        )


def audit_row(audit: Audit, date: str, metric: str, row: dict) -> None:
    audit.rows_checked += 1
    row_date = iso_date(row.get("time_iso"))
    if row_date and row_date != date:
        audit.issue(
            "fatal", "row_time_date_mismatch", date,
            "rendered row time_iso disagrees with page date",
            row=row, detail={"row_time_date": row_date},
        )

    n_runs = int(row.get("n_runs") or 0)
    source_metric_count = count_metric_values(row)
    if source_metric_count and n_runs != source_metric_count:
        audit.issue(
            "fatal", "n_runs_source_count_mismatch", date,
            "row n_runs does not equal metric values traced to source records",
            row=row, detail={"n_runs": n_runs, "source_metric_count": source_metric_count},
        )

    for source in row_source_records(row):
        audit_source(audit, date, metric, row, source)

    if is_commit_only(row):
        audit.issue(
            "warn", "commit_only_metric", date,
            "metric row is sourced only from git commit text, not a log/json result",
            row=row,
        )

    if row.get("val_bpb_source") == "unknown" and not render_day.is_kernel_metric(metric):
        audit.issue(
            "warn", "unknown_metric_source", date,
            "non-kernel metric row has unknown metric source",
            row=row,
        )


def audit_day(conn: sqlite3.Connection, audit: Audit, date: str) -> None:
    raw_records = render_day.fetch_day(conn, date)
    leaked = [
        {
            "id": r.get("id"),
            "abs_path": r.get("abs_path"),
            "best_date": render_day.best_date(r),
        }
        for r in raw_records
        if render_day.best_date(r) != date
    ]
    if leaked:
        audit.issue(
            "fatal", "fetch_day_cross_date_leak", date,
            "fetch_day returned records outside the requested day",
            detail={"samples": leaked[:audit.sample_limit]},
        )

    records = render_day.report_records_for_date(date, raw_records)
    metric = render_day.pick_headline_metric(records)
    rows: list[dict] = []
    if metric:
        baseline = render_day.best_before(conn, date, metric)
        rows = render_day.extract_test_rows(records, metric, baseline)
        expected = list(range(1, len(rows) + 1))
        actual = [int(r.get("n") or 0) for r in rows]
        if actual != expected:
            audit.issue(
                "fatal", "row_numbering_gap", date,
                "Section 2 row numbers are not consecutive after render extraction",
                detail={"actual": actual[:50], "expected": expected[:50]},
            )
        for row in rows:
            audit_row(audit, date, metric, row)

    audit.day_summaries.append({
        "date": date,
        "raw_records": len(raw_records),
        "render_records": len(records),
        "headline_metric": metric,
        "test_rows": len(rows),
        "warnings": sum(1 for i in audit.warnings if i["date"] == date),
        "fatal": sum(1 for i in audit.fatal if i["date"] == date),
    })


def issue_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        code = str(item.get("code") or "unknown")
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def trimmed_issues(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    return items[:limit]


def markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Daily Accuracy Audit",
        "",
        f"- status: `{result['status']}`",
        f"- days checked: `{result['days_checked']}`",
        f"- rows checked: `{result['rows_checked']}`",
        f"- fatal issues: `{result['fatal_count']}`",
        f"- warnings: `{result['warning_count']}`",
        "",
        "## Method",
        "",
        "This audit uses exact local evidence: SQLite records, renderer row provenance, "
        "filename/path date tokens, metric `filename_run_start`, local mtime, and metric-source tags. "
        "It does not use an LLM or embeddings.",
        "",
        "## Issue Counts",
        "",
    ]
    if result["fatal_by_code"] or result["warnings_by_code"]:
        lines.append("| severity | code | count |")
        lines.append("|---|---:|---:|")
        for code, n in result["fatal_by_code"].items():
            lines.append(f"| fatal | `{code}` | {n} |")
        for code, n in result["warnings_by_code"].items():
            lines.append(f"| warn | `{code}` | {n} |")
    else:
        lines.append("_No issues detected._")

    shown = result["fatal_samples"] + result["warning_samples"]
    lines.extend(["", "## Samples", ""])
    if not shown:
        lines.append("_No issue samples._")
    else:
        lines.append("| severity | code | date | row | source | message |")
        lines.append("|---|---|---:|---:|---|---|")
        for item in shown:
            row = item.get("row") or {}
            source = item.get("source") or {}
            src = source.get("abs_path") or row.get("abs_path") or ""
            if len(src) > 96:
                src = "..." + src[-93:]
            msg = str(item.get("message") or "").replace("|", "\\|")
            lines.append(
                f"| {item.get('severity')} | `{item.get('code')}` | {item.get('date')} | "
                f"{row.get('n', '')} | `{src}` | {msg} |"
            )

    lines.extend(["", "## Day Summary", ""])
    lines.append("| date | metric | rows | fatal | warn |")
    lines.append("|---:|---|---:|---:|---:|")
    for day in result["day_summaries"]:
        lines.append(
            f"| {day['date']} | `{day.get('headline_metric') or ''}` | "
            f"{day['test_rows']} | {day['fatal']} | {day['warnings']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_reports(result: dict[str, Any]) -> dict[str, str]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "daily_accuracy.json"
    md_path = OUTPUT_DIR / "daily_accuracy.md"
    paths = {"json": str(json_path), "markdown": str(md_path)}
    result["report_paths"] = paths
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(result), encoding="utf-8")
    return paths


def selected_dates(conn: sqlite3.Connection, args: argparse.Namespace) -> list[str]:
    if args.date:
        return [args.date]
    if args.all:
        return render_all.all_dates_with_artifacts(conn)
    return render_all.all_dates_with_artifacts(conn)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(render_day.DB))
    parser.add_argument("--date", help="YYYY-MM-DD to audit")
    parser.add_argument("--all", action="store_true", help="audit all campaign dates")
    parser.add_argument("--sample-limit", type=int, default=25)
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="exit nonzero on warnings as well as fatal issues",
    )
    args = parser.parse_args()

    if args.date:
        try:
            dt.date.fromisoformat(args.date)
        except ValueError:
            raise SystemExit(f"invalid --date {args.date!r}; expected YYYY-MM-DD")

    t0 = time.perf_counter()
    audit = Audit(sample_limit=max(1, args.sample_limit))
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        dates = selected_dates(conn, args)
        for date in dates:
            audit_day(conn, audit, date)
    finally:
        conn.close()

    status = "failed" if audit.fatal else "warning" if audit.warnings else "ok"
    result: dict[str, Any] = {
        "status": status,
        "db": args.db,
        "template_standard": render_day.DAILY_TEMPLATE_STANDARD,
        "template_style_sha256": render_day.LOCKED_TEMPLATE_STYLE_SHA256,
        "wall_seconds": round(time.perf_counter() - t0, 3),
        "days_checked": len(audit.day_summaries),
        "rows_checked": audit.rows_checked,
        "fatal_count": len(audit.fatal),
        "warning_count": len(audit.warnings),
        "fatal_by_code": issue_counts(audit.fatal),
        "warnings_by_code": issue_counts(audit.warnings),
        "fatal_samples": trimmed_issues(audit.fatal, audit.sample_limit),
        "warning_samples": trimmed_issues(audit.warnings, audit.sample_limit),
        "day_summaries": audit.day_summaries,
    }
    if not args.no_write_report:
        result["report_paths"] = write_reports(result)

    print(json.dumps(result, indent=2, sort_keys=True))
    if audit.fatal or (args.strict_warnings and audit.warnings):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
