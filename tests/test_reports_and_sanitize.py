"""Report helpers, button contrast, and the sanitize audit."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import render_category
import render_week

_AUDIT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sanitize_audit.py"
_SPEC = importlib.util.spec_from_file_location("sanitize_audit", _AUDIT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
sanitize_audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sanitize_audit)


def test_week_windows_are_seven_day_slices() -> None:
    dates = [f"2026-03-{day:02d}" for day in range(18, 26)]
    windows = render_week.week_windows(dates)
    assert [len(window) for window in windows] == [7, 1]
    assert windows[0][0] == "2026-03-18"
    assert windows[0][-1] == "2026-03-24"
    assert windows[1] == ["2026-03-25"]


def test_weekly_metrics_follow_first_seen_order() -> None:
    days = [
        {"date": "2026-04-16", "headline_metric": "kernel_fb_ratio"},
        {"date": "2026-04-15", "headline_metric": "val_bpb"},
        {"date": "2026-04-17", "headline_metric": "val_bpb"},
    ]
    assert render_week.weekly_metrics_chrono(days) == ["val_bpb", "kernel_fb_ratio"]


def test_action_styles_use_the_measured_cream_on_black_pair() -> None:
    weekly = render_week.weekly_action_style()
    category = render_category.category_action_style()
    assert "#f4e8d8" in weekly
    assert "#8b3702" not in weekly
    assert "#f4e8d8" in category
    assert "color: var(--bg)" not in category


def test_published_week_page_matches_the_button_style() -> None:
    html = Path("output/preview/weeks/index.html").read_text(encoding="utf-8")
    assert "color: #f4e8d8 !important;" in html
    assert "#8b3702" not in html


def test_public_source_roots_are_expanded() -> None:
    root = render_category.PUBLIC_SOURCE_ROOTS["parameter-golf-lab"]
    assert root == str(Path.home() / "llm_research" / "parameter-golf-lab")
    assert not root.startswith("~")


def test_sanitize_counts_every_hit_and_ignores_matrix_multiply(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text(
        "\n".join([
            "for _ in range(steps): X=a*X+B@X",
            "contact person@example.com once",
            "again person@example.com",
            "third person@example.com",
            "fourth person@example.com",
            "fifth person@example.com",
        ]) + "\n",
        encoding="utf-8",
    )
    counts, examples = sanitize_audit.audit_file(sample, max_examples_per_cat=2)
    assert counts["email_generic"] == 5
    assert len(examples["email_generic"]) == 2
    assert "api_key_openai" not in counts


def test_relative_scan_dir_does_not_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.txt").write_text("plain text\n", encoding="utf-8")
    summary = sanitize_audit.run(
        Path("."),
        tmp_path / "findings.md",
        tmp_path / "state.json",
        max_examples=2,
    )
    assert summary["files_scanned"] == 1
    assert summary["total_findings"] == 0
