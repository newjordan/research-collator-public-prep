"""Resolve config paths for the research collator.

Python does not expand ``~`` inside ordinary strings. This repo stored
``~/research_collator/...`` and ``~/llm_research/...`` in config and in
script constants, so sqlite, the config file, and the research roots all
pointed at a literal tilde directory. Load config through this module and
use :func:`resolve_repo_path` for files that belong to the checkout.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = REPO_ROOT / "config.yaml"


def legacy_repo_root() -> Path:
    """Historical checkout location used by older config files."""
    return Path.home() / "research_collator"


def expand_user_path(value: str | os.PathLike[str]) -> Path:
    """Expand ``~`` and ``~user``. Relative paths stay relative."""
    return Path(os.path.expanduser(str(value)))


def resolve_repo_path(value: str | os.PathLike[str] | None,
                      default_relative: str) -> Path:
    """Resolve a checkout path.

    Relative paths are rooted at this repository. A legacy
    ``~/research_collator/...`` path follows the repository that is
    actually running when that historical directory is absent. An existing
    legacy file is kept when the checkout itself does not have that file yet.
    """
    if value is None or str(value).strip() == "":
        return (REPO_ROOT / default_relative).resolve()

    expanded = expand_user_path(value)
    legacy_root = legacy_repo_root()
    if expanded.is_absolute():
        try:
            legacy_rel = expanded.relative_to(legacy_root)
        except ValueError:
            legacy_rel = None
        if legacy_rel is not None:
            legacy_target = legacy_root / legacy_rel
            repo_target = (REPO_ROOT / legacy_rel).resolve()
            if legacy_target.exists() and not repo_target.exists():
                return legacy_target.resolve()
            return repo_target
        return expanded.resolve()
    return (REPO_ROOT / expanded).resolve()


def resolve_config_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path is None or str(path).strip() == "":
        return CONFIG_PATH
    candidate = expand_user_path(path)
    if candidate.is_absolute():
        return candidate
    cwd_candidate = (Path.cwd() / candidate).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    return (REPO_ROOT / candidate).resolve()


def _expand_known_paths(cfg: dict) -> None:
    sqlite_path = cfg.get("sqlite_path")
    cfg["sqlite_path"] = str(resolve_repo_path(sqlite_path, "index.sqlite"))

    for key in ("roots", "git_repos"):
        for item in cfg.get(key) or []:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                item["path"] = str(expand_user_path(item["path"]))

    for key in ("claude_projects_root", "codex_sessions_root"):
        if isinstance(cfg.get(key), str):
            cfg[key] = str(expand_user_path(cfg[key]))

    excludes = cfg.get("exclude_path_substrings")
    if isinstance(excludes, list):
        cfg["exclude_path_substrings"] = [
            str(expand_user_path(item)) if isinstance(item, str) else item
            for item in excludes
        ]


def load_config(path: str | os.PathLike[str] | None = None) -> dict:
    """Load YAML config and expand user and repository paths."""
    import yaml

    config_path = resolve_config_path(path)
    if not config_path.exists():
        raise SystemExit(f"config not found: {config_path}")
    with config_path.open(encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    if not isinstance(cfg, dict):
        raise SystemExit(f"config must be a mapping: {config_path}")
    _expand_known_paths(cfg)
    cfg["_config_path"] = str(config_path)
    return cfg


def announce(tool: str, **fields: object) -> None:
    """One readable status line for command-line tools."""
    parts = [tool]
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    print(" · ".join(parts))


def open_index(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open an existing stripper index. Do not create an empty database."""
    if path is None:
        db_path = resolve_repo_path(load_config().get("sqlite_path"), "index.sqlite")
    else:
        db_path = resolve_repo_path(path, "index.sqlite")
    if not db_path.exists():
        raise SystemExit(
            f"SQLite index not found: {db_path}\n"
            "Build it from this repository with:\n"
            "  python3 stripper.py\n"
            "  python3 enrich.py\n"
            "  python3 classify.py"
        )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='artifacts'"
    ).fetchone()
    if row is None:
        conn.close()
        raise SystemExit(
            f"SQLite index has no artifacts table: {db_path}\n"
            "Run python3 stripper.py before enrich, classify, or render."
        )
    return conn
