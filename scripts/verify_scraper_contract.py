#!/usr/bin/env python3
"""Fail-closed scraper/index checks for the locked daily report template.

This verifies the data contract that TEMPLATE.md requires before render_all
turns the corpus into daily pages. It is intentionally local and deterministic:
no LLM calls, no network, no browser.
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

import paths

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import render_all  # noqa: E402
import render_day  # noqa: E402

ALLOWED_CAMPS = {"experimental", "neural", "daily_grind"}
ALLOWED_FILE_KINDS = {
    "md", "text", "asset", "json", "py", "csv", "ckpt", "training_log",
    "git_commit", "claude_session", "codex_session", "conversation_arch_event",
}
REQUIRED_ARTIFACT_COLUMNS = {
    "id", "source_root", "source_label", "rel_path", "abs_path",
    "file_kind", "file_size_bytes", "mtime_iso", "content_sha256",
    "title", "summary", "metrics_json", "too_large", "parse_error",
    "extraction_version", "extracted_at_iso", "camp",
    "classification_rule", "camp_override",
}
NONEMPTY_TEXT_COLUMNS = (
    "source_root", "source_label", "rel_path", "abs_path", "file_kind",
    "mtime_iso", "title", "summary", "extraction_version",
    "extracted_at_iso", "camp", "classification_rule",
)
REQUIRED_INDEXES = {
    "idx_label", "idx_kind", "idx_mtime", "idx_title",
    "idx_kind_mtime", "idx_source_kind", "idx_content_sha",
    "idx_camp", "idx_rule", "idx_camp_kind", "idx_camp_mtime",
}
RE_FILENAME_RUN_START = re.compile(r"^20\d{6}T\d{6}$")
RE_ISO_DATE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")


class ContractReport:
    def __init__(self, sample_limit: int) -> None:
        self.sample_limit = sample_limit
        self.fatal: list[str] = []
        self.warnings: list[str] = []
        self.stats: dict[str, Any] = {}

    def fail(self, message: str) -> None:
        self.fatal.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"scraper contract failed: missing SQLite index {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def count(conn: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, args).fetchone()
    if row is None:
        return 0
    return int(row[0] or 0)


def samples(conn: sqlite3.Connection, sql: str, limit: int,
            args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    rows = conn.execute(sql + " LIMIT ?", (*args, limit)).fetchall()
    return [dict(r) for r in rows]


def metric_dict(raw: str | None, abs_path: str, report: ContractReport) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        report.fail(f"invalid metrics_json for {abs_path}: {exc}")
        return {}
    if not isinstance(obj, dict):
        report.fail(f"metrics_json must be an object for {abs_path}")
        return {}
    return obj


def verify_config(config_path: Path, db_path: Path, report: ContractReport) -> None:
    if not config_path.exists():
        report.fail(f"missing config file: {config_path}")
        return
    cfg = paths.load_config(config_path)

    configured_db = Path(str(cfg.get("sqlite_path", "")))
    checked_db = paths.resolve_repo_path(db_path, "index.sqlite")
    if configured_db and configured_db.resolve() != checked_db.resolve():
        report.fail(f"config sqlite_path {configured_db} does not match checked DB {checked_db}")

    roots = cfg.get("roots") or []
    if not roots:
        report.fail("config.yaml has no scrape roots")
    missing_roots = [
        f"{r.get('label', '?')}={r.get('path', '')}"
        for r in roots
        if not os.path.isdir(str(r.get("path", "")))
    ]
    if missing_roots:
        report.fail(f"configured scrape roots are missing: {missing_roots[:report.sample_limit]}")

    git_repos = cfg.get("git_repos") or []
    missing_git = [
        f"{r.get('label', '?')}={r.get('path', '')}"
        for r in git_repos
        if not os.path.isdir(os.path.join(str(r.get("path", "")), ".git"))
    ]
    if missing_git:
        report.warn(f"configured git repos without .git metadata: {missing_git[:report.sample_limit]}")

    ext_map = cfg.get("ext_handler_map") or {}
    for ext, handler in {
        ".log": "training_log",
        ".out": "training_log",
        ".txt": "text_summary",
        ".sh": "text_summary",
        ".yaml": "text_summary",
        ".yml": "text_summary",
        ".mp4": "asset_meta",
        ".png": "asset_meta",
        ".tgz": "asset_meta",
        ".json": "json_summary",
        ".py": "python_module",
        ".md": "markdown",
        ".csv": "csv_meta",
        ".tsv": "csv_meta",
    }.items():
        if ext_map.get(ext) != handler:
            report.fail(f"config ext_handler_map must route {ext} to {handler}")
    if int(cfg.get("max_log_bytes") or 0) <= 0:
        report.fail("config max_log_bytes must be positive")

    report.stats["config"] = {
        "roots": len(roots),
        "git_repos": len(git_repos),
        "sqlite_path": str(configured_db),
    }


def verify_schema(conn: sqlite3.Connection, report: ContractReport) -> None:
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if "artifacts" not in tables:
        report.fail("missing artifacts table")
        return
    if "walk_runs" not in tables:
        report.fail("missing walk_runs table")

    columns = {r["name"] for r in conn.execute("PRAGMA table_info(artifacts)")}
    missing = sorted(REQUIRED_ARTIFACT_COLUMNS - columns)
    if missing:
        report.fail(f"artifacts table missing required columns: {missing}")
        return

    row_count = count(conn, "SELECT count(*) FROM artifacts")
    report.stats["row_count"] = row_count
    if row_count == 0:
        report.fail("artifacts table is empty")

    by_kind = {
        r["file_kind"]: r["n"]
        for r in conn.execute(
            "SELECT file_kind, count(*) AS n FROM artifacts GROUP BY file_kind"
        )
    }
    by_camp = {
        r["camp"]: r["n"]
        for r in conn.execute(
            "SELECT camp, count(*) AS n FROM artifacts GROUP BY camp"
        )
    }
    report.stats["by_kind"] = dict(sorted(by_kind.items()))
    report.stats["by_camp"] = dict(sorted(by_camp.items()))

    unknown_kinds = sorted(set(by_kind) - ALLOWED_FILE_KINDS)
    if unknown_kinds:
        report.fail(f"unknown file_kind values: {unknown_kinds}")
    unknown_camps = sorted(set(by_camp) - ALLOWED_CAMPS)
    if unknown_camps:
        report.fail(f"unknown camp values: {unknown_camps}")

    for col in NONEMPTY_TEXT_COLUMNS:
        n_bad = count(
            conn,
            f"SELECT count(*) FROM artifacts WHERE {col} IS NULL OR trim({col})=''",
        )
        if n_bad:
            bad = samples(
                conn,
                f"SELECT id, abs_path, file_kind FROM artifacts "
                f"WHERE {col} IS NULL OR trim({col})='' ORDER BY id",
                report.sample_limit,
            )
            report.fail(f"{n_bad} artifacts have empty {col}; samples={bad}")

    n_bad_size = count(conn, "SELECT count(*) FROM artifacts WHERE file_size_bytes IS NULL OR file_size_bytes < 0")
    if n_bad_size:
        report.fail(f"{n_bad_size} artifacts have invalid file_size_bytes")
    n_bad_large = count(conn, "SELECT count(*) FROM artifacts WHERE too_large NOT IN (0, 1)")
    if n_bad_large:
        report.fail(f"{n_bad_large} artifacts have too_large outside 0/1")

    index_names = {
        r["name"]
        for r in conn.execute("PRAGMA index_list('artifacts')")
        if r["name"]
    }
    missing_indexes = sorted(REQUIRED_INDEXES - index_names)
    report.stats["indexes"] = sorted(index_names)
    if missing_indexes:
        report.fail(f"missing required retrieval indexes: {missing_indexes}")


def verify_metrics(conn: sqlite3.Connection, report: ContractReport) -> None:
    rows = conn.execute(
        "SELECT id, abs_path, file_kind, metrics_json FROM artifacts "
        "WHERE metrics_json IS NOT NULL AND trim(metrics_json)!=''"
    ).fetchall()
    report.stats["metrics_rows"] = len(rows)

    metric_key_counts: dict[str, int] = {}
    bad_numeric: list[dict[str, Any]] = []
    bad_training_sources: list[dict[str, Any]] = []
    bad_filename_ts: list[dict[str, Any]] = []
    bad_gpu_counts: list[dict[str, Any]] = []

    for row in rows:
        md = metric_dict(row["metrics_json"], row["abs_path"], report)
        for key in md:
            metric_key_counts[key] = metric_key_counts.get(key, 0) + 1

        for key in ("val_bpb", "val_loss"):
            if key not in md:
                continue
            value = md.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                bad_numeric.append({"id": row["id"], "abs_path": row["abs_path"], key: value})

        if row["file_kind"] == "training_log" and "val_bpb" in md:
            source = md.get("val_bpb_source")
            if source not in {"log_final_eval", "log_step_best"}:
                bad_training_sources.append({
                    "id": row["id"],
                    "abs_path": row["abs_path"],
                    "val_bpb_source": source,
                })

        filename_run_start = md.get("filename_run_start")
        if filename_run_start is not None:
            if not isinstance(filename_run_start, str) or not RE_FILENAME_RUN_START.match(filename_run_start):
                bad_filename_ts.append({
                    "id": row["id"],
                    "abs_path": row["abs_path"],
                    "filename_run_start": filename_run_start,
                })

        n_gpus = md.get("n_gpus")
        if n_gpus is not None:
            valid_int = (
                isinstance(n_gpus, int)
                or (isinstance(n_gpus, float) and n_gpus.is_integer())
            )
            if not valid_int or int(n_gpus) < 1 or int(n_gpus) > 64:
                bad_gpu_counts.append({
                    "id": row["id"],
                    "abs_path": row["abs_path"],
                    "n_gpus": n_gpus,
                })

    if bad_numeric:
        report.fail(f"non-numeric headline metrics: {bad_numeric[:report.sample_limit]}")
    if bad_training_sources:
        report.fail(
            "training logs with val_bpb must tag val_bpb_source as "
            f"log_final_eval/log_step_best; samples={bad_training_sources[:report.sample_limit]}"
        )
    if bad_filename_ts:
        report.fail(f"bad filename_run_start values: {bad_filename_ts[:report.sample_limit]}")
    if bad_gpu_counts:
        report.fail(f"bad n_gpus values: {bad_gpu_counts[:report.sample_limit]}")

    # Count through the renderer extractor, not only literal JSON keys. Kernel
    # headline metrics are derived from custom/FA3 timing pairs.
    headline_counts = {key: 0 for key in render_day.HEADLINE_METRICS}
    for row in rows:
        for key in headline_counts:
            headline_counts[key] += len(render_day.extract_metric_for_record(row["metrics_json"], key))
    report.stats["headline_metric_counts"] = headline_counts


def classify_missing_log_metrics(row: sqlite3.Row) -> str:
    if int(row["too_large"] or 0):
        return "too_large"
    if row["parse_error"]:
        return "parse_error"
    if int(row["file_size_bytes"] or 0) == 0:
        return "empty_stub"
    return "no_canonical_metric"


def verify_training_logs(conn: sqlite3.Connection, report: ContractReport) -> None:
    rows = conn.execute(
        "SELECT id, abs_path, file_size_bytes, too_large, parse_error, "
        "content_sha256, metrics_json FROM artifacts WHERE file_kind='training_log'"
    ).fetchall()

    missing_metrics_by_reason: dict[str, int] = {}
    measured_logs = 0
    missing_measured_files: list[dict[str, Any]] = []
    missing_hash: list[dict[str, Any]] = []

    for row in rows:
        md = metric_dict(row["metrics_json"], row["abs_path"], report)
        if "val_bpb" in md or "val_loss" in md:
            measured_logs += 1
            if row["abs_path"].startswith("/"):
                if not os.path.isfile(row["abs_path"]):
                    missing_measured_files.append({"id": row["id"], "abs_path": row["abs_path"]})
            if int(row["file_size_bytes"] or 0) > 0 and not row["content_sha256"]:
                missing_hash.append({"id": row["id"], "abs_path": row["abs_path"]})
            continue
        if not row["metrics_json"]:
            reason = classify_missing_log_metrics(row)
            missing_metrics_by_reason[reason] = missing_metrics_by_reason.get(reason, 0) + 1

    if missing_measured_files:
        report.fail(f"measured training logs missing on disk: {missing_measured_files[:report.sample_limit]}")
    if missing_hash:
        report.fail(f"measured training logs missing content_sha256: {missing_hash[:report.sample_limit]}")
    if missing_metrics_by_reason.get("no_canonical_metric", 0):
        no_metric = samples(
            conn,
            "SELECT id, abs_path, file_size_bytes FROM artifacts "
            "WHERE file_kind='training_log' AND metrics_json IS NULL "
            "AND too_large=0 AND file_size_bytes>0 ORDER BY file_size_bytes DESC",
            report.sample_limit,
        )
        report.warn(
            f"{missing_metrics_by_reason['no_canonical_metric']} nonempty training logs "
            f"had no canonical metric pattern; samples={no_metric}"
        )

    report.stats["training_logs"] = {
        "total": len(rows),
        "measured": measured_logs,
        "missing_metrics_by_reason": dict(sorted(missing_metrics_by_reason.items())),
    }


def verify_date_attribution(conn: sqlite3.Connection, report: ContractReport,
                            target_date: str | None) -> None:
    all_rows = conn.execute("SELECT abs_path, rel_path, mtime_iso FROM artifacts").fetchall()
    bad_dates: list[dict[str, Any]] = []
    dates: set[str] = set()
    for row in all_rows:
        rec = dict(row)
        try:
            bd = render_day.best_date(rec)
        except Exception as exc:  # noqa: BLE001 - verifier must report path
            bad_dates.append({"abs_path": row["abs_path"], "error": repr(exc)})
            continue
        if not bd or not RE_ISO_DATE.match(bd):
            bad_dates.append({"abs_path": row["abs_path"], "best_date": bd})
            continue
        try:
            dt.date.fromisoformat(bd)
        except ValueError:
            bad_dates.append({"abs_path": row["abs_path"], "best_date": bd})
            continue
        dates.add(bd)
    if bad_dates:
        report.fail(f"records with invalid day attribution: {bad_dates[:report.sample_limit]}")

    render_dates = [target_date] if target_date else sorted(dates)
    measured_days = 0
    test_rows_total = 0
    daily_grind_tests: list[dict[str, Any]] = []
    bad_row_numbers: list[dict[str, Any]] = []

    for date in render_dates:
        if date not in dates:
            report.fail(f"requested date {date} is not attributable from artifacts")
            continue
        day_records = render_day.fetch_day(conn, date)
        leaks = [
            {"abs_path": r.get("abs_path"), "best_date": render_day.best_date(r)}
            for r in day_records
            if render_day.best_date(r) != date
        ]
        if leaks:
            report.fail(f"fetch_day leaked records outside {date}: {leaks[:report.sample_limit]}")
        metric = render_day.pick_headline_metric(day_records)
        if not metric:
            continue
        measured_days += 1
        baseline = render_day.best_before(conn, date, metric)
        rows = render_day.extract_test_rows(day_records, metric, baseline)
        test_rows_total += len(rows)
        expected = list(range(1, len(rows) + 1))
        actual = [int(r.get("n") or 0) for r in rows]
        if actual != expected:
            bad_row_numbers.append({"date": date, "actual": actual[:20], "expected": expected[:20]})
        for r in rows:
            if r.get("camp") == "daily_grind":
                daily_grind_tests.append({
                    "date": date,
                    "n": r.get("n"),
                    "title": r.get("title"),
                    "abs_path": r.get("abs_path"),
                })

    if bad_row_numbers:
        report.fail(f"test row numbering is not consecutive: {bad_row_numbers[:report.sample_limit]}")
    if daily_grind_tests:
        report.fail(f"daily_grind records reached Section 2 test rows: {daily_grind_tests[:report.sample_limit]}")

    report.stats["date_attribution"] = {
        "artifact_dates": len(dates),
        "checked_dates": len(render_dates),
        "measured_days": measured_days,
        "test_rows_total": test_rows_total,
    }


def verify_explain_plans(conn: sqlite3.Connection, report: ContractReport) -> None:
    plans = {
        "training_logs_by_time": (
            "EXPLAIN QUERY PLAN SELECT * FROM artifacts "
            "WHERE file_kind='training_log' ORDER BY mtime_iso"
        ),
        "camp_kind_slice": (
            "EXPLAIN QUERY PLAN SELECT * FROM artifacts "
            "WHERE camp='experimental' AND file_kind='training_log'"
        ),
        "source_kind_slice": (
            "EXPLAIN QUERY PLAN SELECT * FROM artifacts "
            "WHERE source_label='SOTA_FINAL' AND file_kind='json'"
        ),
    }
    plan_text: dict[str, list[str]] = {}
    for name, sql in plans.items():
        rows = conn.execute(sql).fetchall()
        details = [str(r["detail"]) for r in rows]
        plan_text[name] = details
        if not any("INDEX" in d.upper() for d in details):
            report.fail(f"retrieval query does not use an index: {name}: {details}")
    report.stats["query_plans"] = plan_text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(render_day.DB), help="SQLite index to verify")
    parser.add_argument("--config", default=str(REPO_ROOT / "config.yaml"))
    parser.add_argument("--date", default=None, help="Optionally restrict day-surface checks to YYYY-MM-DD")
    parser.add_argument("--sample-limit", type=int, default=5)
    args = parser.parse_args()

    t0 = time.perf_counter()
    report = ContractReport(sample_limit=max(1, args.sample_limit))
    db_path = Path(args.db)
    config_path = Path(args.config)

    if args.date:
        try:
            dt.date.fromisoformat(args.date)
        except ValueError:
            raise SystemExit(f"invalid --date {args.date!r}; expected YYYY-MM-DD")

    verify_config(config_path, db_path, report)
    conn = connect(db_path)
    try:
        verify_schema(conn, report)
        if not report.fatal:
            verify_metrics(conn, report)
            verify_training_logs(conn, report)
            verify_date_attribution(conn, report, args.date)
            verify_explain_plans(conn, report)
    finally:
        conn.close()

    result = {
        "status": "failed" if report.fatal else "ok",
        "db": str(db_path),
        "config": str(config_path),
        "template_standard": render_day.DAILY_TEMPLATE_STANDARD,
        "template_style_sha256": render_day.LOCKED_TEMPLATE_STYLE_SHA256,
        "wall_seconds": round(time.perf_counter() - t0, 3),
        "fatal_count": len(report.fatal),
        "warning_count": len(report.warnings),
        "fatal_errors": report.fatal,
        "warnings": report.warnings,
        "stats": report.stats,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if report.fatal:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
