"""Fail if credential-shaped secrets are committed."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}
PATTERNS = {
    "anthropic": re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}"),
    "openai": re.compile(rb"sk-[A-Za-z0-9]{32,}"),
    "github": re.compile(rb"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    "google": re.compile(rb"AIza[0-9A-Za-z_-]{30,}"),
    "aws": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PRIVATE KEY)"),
    "slack": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}"),
}


def test_repository_has_no_credential_literals() -> None:
    hits: list[str] = []
    scanned = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpeg", ".jpg", ".webp", ".zip", ".pyc"}:
            continue
        scanned += 1
        data = path.read_bytes()
        if b"\x00" in data[:4096]:
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(data):
                hits.append(f"{name}: {path.relative_to(ROOT)}")
                break
    assert scanned > 0
    assert hits == []
