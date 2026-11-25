"""Path expansion and index-open behavior."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import paths
import stripper


def test_tilde_research_root_expands(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(paths, "REPO_ROOT", tmp_path / "repo")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "sqlite_path: index.sqlite\n"
        "roots:\n"
        "  - {path: ~/llm_research/parameter-golf-lab, label: parameter-golf-lab}\n"
        "claude_projects_root: ~/.claude/projects\n"
        "exclude_path_substrings:\n"
        "  - ~/workspace/projects/cache/\n",
        encoding="utf-8",
    )
    cfg = paths.load_config(cfg_path)
    assert cfg["sqlite_path"] == str((tmp_path / "repo" / "index.sqlite").resolve())
    assert cfg["roots"][0]["path"] == str(home / "llm_research" / "parameter-golf-lab")
    assert cfg["claude_projects_root"] == str(home / ".claude" / "projects")
    assert cfg["exclude_path_substrings"] == [str(home / "workspace/projects/cache/")]


def test_legacy_checkout_follows_the_running_repo(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "research_collator").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "moved"
    repo.mkdir()
    monkeypatch.setattr(paths, "REPO_ROOT", repo)
    resolved = paths.resolve_repo_path("~/research_collator/output", "output")
    assert resolved == (repo / "output").resolve()
    assert not (home / "research_collator" / "output").exists()


def test_legacy_file_is_kept_when_checkout_has_no_copy(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    legacy = home / "research_collator" / "index.sqlite"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("existing", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "moved"
    repo.mkdir()
    monkeypatch.setattr(paths, "REPO_ROOT", repo)
    resolved = paths.resolve_repo_path("~/research_collator/index.sqlite", "index.sqlite")
    assert resolved == legacy.resolve()


def test_checked_in_config_resolves_inside_this_repo() -> None:
    cfg = paths.load_config()
    assert Path(cfg["sqlite_path"]) == (paths.REPO_ROOT / "index.sqlite").resolve()
    assert cfg["roots"]
    assert all(not str(item["path"]).startswith("~") for item in cfg["roots"])
    assert all(Path(item["path"]).is_absolute() for item in cfg["roots"])


def test_open_index_does_not_create_a_database(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(SystemExit, match="SQLite index not found"):
        paths.open_index(missing)
    assert not missing.exists()


def test_open_index_rejects_empty_database(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite"
    sqlite3.connect(db).close()
    with pytest.raises(SystemExit, match="no artifacts table"):
        paths.open_index(db)


def test_init_db_creates_parent_and_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "index.sqlite"
    conn = stripper.init_db(db)
    conn.close()
    assert db.exists()
    conn = stripper.init_db(db)
    count = conn.execute("SELECT count(*) FROM artifacts").fetchone()[0]
    conn.close()
    assert count == 0
