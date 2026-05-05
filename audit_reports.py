#!/usr/bin/env python3
"""Deterministic forensic audit for rendered research days.

This checks the same SQLite/render helpers used by the reports. It does not
call an LLM and does not trust visual claims.

Usage:
    python3 audit_reports.py 2026-03-17 2026-03-28 2026-04-20
    python3 audit_reports.py --all
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

import render_day as rd
from render_all import all_dates_with_artifacts


DATE_TOKEN = re.compile(r"20\d{2}[-_]?\d{2}[-_]?\d{2}")


def _normalize_date_token(tok: str) -> str:
    tok = tok.replace("_", "-")
    if "-" not in tok:
        return f"{tok[:4]}-{tok[4:6]}-{tok[6:8]}"
    return tok


def _path_other_dates(path: str, date: str) -> list[str]:
    out = []
    for tok in DATE_TOKEN.findall(path):
        nd = _normalize_date_token(tok)
        if nd != date:
            out.append(nd)
    return sorted(set(out))


def audit_date(conn: sqlite3.Connection, date: str) -> dict:
    records = [dict(r) for r in rd.fetch_day(conn, date)]
    metric = rd.pick_headline_metric(records)
    baseline = rd.best_before(conn, date, metric) if metric else None
    test_rows = rd.extract_test_rows(records, metric, baseline) if metric else []

    test_paths: set[str] = set()
    for row in test_rows:
        paths = row.get("record_paths")
        if isinstance(paths, set):
            test_paths.update(paths)
        elif row.get("abs_path"):
            test_paths.add(row["abs_path"])

    support = [
        r for r in records
        if r["abs_path"] not in test_paths and rd.best_date(r) == date
    ]

    support_other_date_tokens = []
    for r in support:
        others = _path_other_dates(r["abs_path"], date)
        if others:
            support_other_date_tokens.append({
                "kind": r["file_kind"],
                "source": r["source_label"],
                "best_date": rd.best_date(r),
                "other_date_tokens": others[:6],
                "path": r["abs_path"].replace("/home/frosty40/", "~/"),
            })

    status_counts = Counter(row.get("status", "OK") for row in test_rows)
    verify_counts = Counter((row.get("verify") or "UNKNOWN").split(" / ", 1)[0]
                            for row in test_rows)
    kind_counts = Counter(r["file_kind"] for r in records)
    support_kind_counts = Counter(r["file_kind"] for r in support)

    return {
        "date": date,
        "headline_metric": metric,
        "records": len(records),
        "records_by_kind": dict(sorted(kind_counts.items())),
        "test_rows": len(test_rows),
        "test_status": dict(sorted(status_counts.items())),
        "verify": dict(sorted(verify_counts.items())),
        "supporting_files": len(support),
        "supporting_by_kind": dict(sorted(support_kind_counts.items())),
        "best_before": baseline,
        "best_before_valid": (
            None if baseline is None or metric is None
            else rd.is_valid_metric_value(metric, baseline)
        ),
        "support_other_date_token_examples": support_other_date_tokens[:12],
        "html_exists": Path(rd.HTML_DIR / f"{date}.html").exists(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dates", nargs="*", help="YYYY-MM-DD dates to audit")
    ap.add_argument("--all", action="store_true", help="audit every date in the index")
    args = ap.parse_args()

    conn = sqlite3.connect(rd.DB)
    conn.row_factory = sqlite3.Row
    dates = args.dates
    if args.all:
        dates = all_dates_with_artifacts(conn)
    if not dates:
        ap.error("pass one or more dates, or --all")

    print(json.dumps([audit_date(conn, d) for d in dates], indent=2))


if __name__ == "__main__":
    main()
