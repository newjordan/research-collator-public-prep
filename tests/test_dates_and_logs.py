"""Day attribution, training-log parsing, and report record filtering."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import render_day
import stripper


def test_impossible_calendar_day_does_not_win_over_mtime() -> None:
    rec = {
        "file_kind": "training_log",
        "abs_path": "/logs/run_20260231.log",
        "rel_path": "run_20260231.log",
        "mtime_iso": "2026-03-18T18:00:00Z",
    }
    assert render_day.best_date(rec) == "2026-03-18"


def test_filename_date_beats_mtime() -> None:
    rec = {
        "file_kind": "training_log",
        "abs_path": "/logs/medusa_20260328_072024.log",
        "rel_path": "medusa_20260328_072024.log",
        "mtime_iso": "2026-03-30T15:00:00Z",
    }
    assert render_day.best_date(rec) == "2026-03-28"


def test_git_commit_ignores_date_like_sha() -> None:
    rec = {
        "file_kind": "git_commit",
        "abs_path": "git://parameter-golf-lab/20260401abcd",
        "rel_path": "20260401abcd",
        "mtime_iso": "2026-03-18T18:00:00Z",
    }
    assert render_day.best_date(rec) == "2026-03-18"


def test_chicago_standard_time_does_not_roll_into_the_next_utc_day() -> None:
    # 23:30 CST on 2026-02-23 is 05:30 UTC on 2026-02-24.
    rec = {
        "file_kind": "md",
        "abs_path": "/notes/scratch.md",
        "rel_path": "scratch.md",
        "mtime_iso": "2026-02-24T05:30:00Z",
    }
    assert render_day.best_date(rec) == "2026-02-23"


def test_chicago_daylight_time_keeps_late_evening_on_the_local_day() -> None:
    # 23:30 CDT on 2026-03-17 is 04:30 UTC on 2026-03-18.
    rec = {
        "file_kind": "md",
        "abs_path": "/notes/scratch.md",
        "rel_path": "scratch.md",
        "mtime_iso": "2026-03-18T04:30:00Z",
    }
    assert render_day.best_date(rec) == "2026-03-17"


def test_fetch_day_uses_chicago_offset_not_only_utc_minus_five() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE artifacts (
            abs_path TEXT, rel_path TEXT, mtime_iso TEXT,
            content_sha256 TEXT, file_kind TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?)",
        ("/notes/scratch.md", "scratch.md", "2026-02-24T05:30:00Z", None, "md"),
    )
    assert len(render_day.fetch_day(conn, "2026-02-23")) == 1
    assert render_day.fetch_day(conn, "2026-02-24") == []


def test_research_days_drop_chat_sessions() -> None:
    records = [
        {"file_kind": "training_log", "source_label": "parameter-golf-lab", "metrics_json": "{}"},
        {"file_kind": "claude_session", "source_label": "parameter-golf-lab", "metrics_json": "{}"},
        {"file_kind": "codex_session", "source_label": "parameter-golf-lab", "metrics_json": "{}"},
    ]
    kept = render_day.report_records_for_date("2026-03-28", records)
    assert [row["file_kind"] for row in kept] == ["training_log"]


def test_validity_floor_is_bpb_only() -> None:
    assert render_day.is_valid_metric_value("val_bpb", 1.06) is True
    assert render_day.is_valid_metric_value("val_bpb", 1.0599) is False
    assert render_day.is_valid_metric_value("val_bpb", 3.0) is True
    assert render_day.is_valid_metric_value("val_bpb", 3.01) is False
    assert render_day.is_valid_metric_value("kernel_fb_ratio", 0.5) is True
    assert render_day.is_valid_metric_value("val_bpb", True) is False


def test_training_log_prefers_final_eval_and_strips_exact_suffix(tmp_path: Path) -> None:
    log = tmp_path / "probe_20260328_010203.log"
    log.write_text(
        "\n".join([
            "step:1/10 val_loss:2.20 val_bpb:1.4000",
            "step:2/10 val_loss:1.10 val_bpb:0.0100",
            "step:3/10 val_loss:1.80 val_bpb:1.2000",
            "final_int6_sliding_window val_loss:1.70 val_bpb:1.0900",
            "final_int6_sliding_window_exact val_loss:1.69 val_bpb:1.0880",
            "train_time:1500ms",
            "[rank0]",
            "[rank1]",
        ]) + "\n",
        encoding="utf-8",
    )
    rec = stripper.handle_training_log(str(log), log.stat().st_size, 1_000_000)
    metrics = __import__("json").loads(rec["metrics_json"])
    assert metrics["val_bpb"] == 1.0880
    assert metrics["val_bpb_source"] == "log_final_eval"
    assert metrics["val_bpb_during_run_best"] == 1.2
    assert metrics["val_bpb_n_step_evals"] == 3
    assert metrics["n_gpus"] == 2
    assert metrics["train_time_seconds"] == 1.5
    assert metrics["step_final"] == 3
    assert metrics["filename_run_start"] == "20260328T010203"


def test_markdown_frontmatter_title(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("---\ntitle: Helix notes\n---\n\nFirst paragraph.\n", encoding="utf-8")
    rec = stripper.handle_markdown(str(note), note.stat().st_size, 100_000)
    assert rec["title"] == "Helix notes"
    assert rec["summary"] == "First paragraph."
    assert rec["file_kind"] == "md"
