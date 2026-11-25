"""End-to-end stripper plus classifier on a temporary corpus."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_stripper_expands_home_and_classify_tags_rows(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    corpus = home / "corpus"
    (corpus / "legs" / "ouroboros").mkdir(parents=True)
    (corpus / "legs").joinpath("baseline.log").write_text(
        "step:4/10 val_loss:1.90 val_bpb:1.2200\n",
        encoding="utf-8",
    )
    (corpus / "legs" / "ouroboros" / "run.log").write_text(
        "step:8/10 val_loss:1.70 val_bpb:1.1500\n",
        encoding="utf-8",
    )
    (corpus / "hello.md").write_text("# Hello\n\nA note.\n", encoding="utf-8")
    db_path = tmp_path / "index.sqlite"
    config = tmp_path / "config.yaml"
    config.write_text(
        "\n".join([
            f"sqlite_path: {db_path}",
            "roots:",
            "  - path: ~/corpus",
            "    label: parameter-golf-lab",
            "exclude_dir_names:",
            "  - .git",
            "ext_handler_map:",
            '  ".md": markdown',
            '  ".log": training_log',
            "max_md_bytes: 100000",
            "max_log_bytes: 100000",
            "",
        ]),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["HOME"] = str(home)
    repo = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "stripper.py", "--config", str(config), "--smoke", "10"],
        cwd=repo,
        env=env,
        check=True,
    )
    subprocess.run(
        [sys.executable, "classify.py", "--config", str(config), "--db", str(db_path)],
        cwd=repo,
        env=env,
        check=True,
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = {
        row["rel_path"]: row
        for row in conn.execute("SELECT rel_path, file_kind, camp, classification_rule, metrics_json, title FROM artifacts")
    }
    assert set(rows) == {"hello.md", "legs/baseline.log", "legs/ouroboros/run.log"}
    assert rows["hello.md"]["title"] == "Hello"
    assert rows["hello.md"]["camp"] == "experimental"
    assert rows["legs/baseline.log"]["camp"] == "neural"
    assert rows["legs/baseline.log"]["classification_rule"] == "path_legs"
    assert rows["legs/ouroboros/run.log"]["camp"] == "experimental"
    metrics = json.loads(rows["legs/ouroboros/run.log"]["metrics_json"])
    assert metrics["val_bpb"] == 1.15
    assert metrics["val_bpb_source"] == "log_step_best"
