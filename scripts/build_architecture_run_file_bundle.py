#!/usr/bin/env python3
"""Build the public architecture run-file download bundle.

The source of truth is ARCHITECTURE_FAMILY_MASTER_SHEET.md. This script copies
the evidence anchor for each architecture/test-family row into a repo-local
public bundle and writes machine-readable plus reviewer-readable indexes.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MASTER_SHEET = ROOT / "ARCHITECTURE_FAMILY_MASTER_SHEET.md"
OUT_ROOT = ROOT / "public" / "architecture-run-files"
FILES_ROOT = OUT_ROOT / "files"
MANIFEST_JSON = OUT_ROOT / "manifest.json"
MANIFEST_MD = ROOT / "ARCHITECTURE_RUN_FILE_DOWNLOADS.md"
RAW_BASE = (
    "https://raw.githubusercontent.com/newjordan/research-collator/"
    "art/palette-switcher"
)
BLOB_BASE = (
    "https://github.com/newjordan/research-collator/blob/"
    "art/palette-switcher"
)
SEARCH_ROOTS = [
    Path("/home/frosty40/llm_research"),
    Path("/home/frosty40"),
]


def slugify(text: str) -> str:
    text = text.lower().replace("/", " ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80] or "unnamed"


def parse_master_sheet(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| #"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        rows.append({
            "number": cells[0],
            "family": cells[1],
            "type": cells[2],
            "aliases": cells[3],
            "evidence_anchor": cells[4].strip("`"),
            "notes": cells[5],
        })
    return rows


def resolve_anchor(anchor: str) -> tuple[Path | None, str]:
    path = Path(anchor)
    if not path.is_absolute():
        path = ROOT / path
    if path.exists():
        return path, "exact"

    basename = Path(anchor).name
    if not basename:
        return None, "missing"
    for search_root in SEARCH_ROOTS:
        if not search_root.exists():
            continue
        try:
            hits = sorted(search_root.rglob(basename))
        except OSError:
            hits = []
        for hit in hits:
            if hit.is_file():
                return hit, "basename-search"
    return None, "missing"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_file(src: Path, dst: Path) -> dict[str, Any]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    repo_rel = dst.relative_to(ROOT).as_posix()
    return {
        "name": src.name,
        "repo_path": repo_rel,
        "size_bytes": dst.stat().st_size,
        "sha256": file_sha256(dst),
        "download_url": f"{RAW_BASE}/{repo_rel}",
        "view_url": f"{BLOB_BASE}/{repo_rel}",
    }


def copy_anchor(src: Path, dst_dir: Path) -> list[dict[str, Any]]:
    if src.is_file():
        return [copy_file(src, dst_dir / src.name)]

    copied: list[dict[str, Any]] = []
    for item in sorted(src.rglob("*")):
        if not item.is_file():
            continue
        rel_parts = item.relative_to(src).parts
        if any(part in {".git", "__pycache__", ".pytest_cache", ".mypy_cache"} for part in rel_parts):
            continue
        copied.append(copy_file(item, dst_dir / src.name / Path(*rel_parts)))
    return copied


def write_markdown(entries: list[dict[str, Any]]) -> None:
    lines = [
        "# Architecture Run File Downloads",
        "",
        "This index is generated from `ARCHITECTURE_FAMILY_MASTER_SHEET.md`.",
        "Each row copies the master-sheet evidence anchor into this repository so public report readers can download the referenced run/build evidence directly.",
        "",
        "| # | Family / lane | Type | Files | Download |",
        "|---:|---|---|---:|---|",
    ]
    for entry in entries:
        files = entry.get("files") or []
        if files:
            if len(files) == 1:
                download = f"[download]({files[0]['download_url']})"
            else:
                download = f"[folder]({entry['view_url']})"
        else:
            download = "missing"
        lines.append(
            "| {number} | {family} | {type} | {n_files} | {download} |".format(
                number=entry["number"],
                family=html.escape(entry["family"]),
                type=html.escape(entry["type"]),
                n_files=len(files),
                download=download,
            )
        )
    lines.append("")
    MANIFEST_MD.write_text("\n".join(lines), encoding="utf-8")


def build(clean: bool = True) -> list[dict[str, Any]]:
    if clean and OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    FILES_ROOT.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    for row in parse_master_sheet(MASTER_SHEET):
        number = int(row["number"])
        slug = f"{number:02d}_{slugify(row['family'])}"
        dst_dir = FILES_ROOT / slug
        src, resolution = resolve_anchor(row["evidence_anchor"])
        files: list[dict[str, Any]] = []
        status = "missing"
        if src:
            files = copy_anchor(src, dst_dir)
            status = "copied" if files else "empty"
        repo_folder = dst_dir.relative_to(ROOT).as_posix()
        entries.append({
            "number": number,
            "family": row["family"],
            "type": row["type"],
            "aliases": row["aliases"],
            "slug": slug,
            "status": status,
            "resolution": resolution,
            "source_anchor_name": Path(row["evidence_anchor"]).name,
            "repo_folder": repo_folder,
            "view_url": f"{BLOB_BASE}/{repo_folder}",
            "files": files,
        })

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_JSON.write_text(
        json.dumps({
            "source_sheet": "ARCHITECTURE_FAMILY_MASTER_SHEET.md",
            "entry_count": len(entries),
            "copied_entry_count": sum(1 for e in entries if e["status"] == "copied"),
            "file_count": sum(len(e["files"]) for e in entries),
            "entries": entries,
        }, indent=2),
        encoding="utf-8",
    )
    write_markdown(entries)
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-clean", action="store_true")
    args = parser.parse_args()
    entries = build(clean=not args.no_clean)
    copied = sum(1 for e in entries if e["status"] == "copied")
    files = sum(len(e["files"]) for e in entries)
    missing = [e for e in entries if e["status"] != "copied"]
    print({
        "entries": len(entries),
        "copied": copied,
        "files": files,
        "missing": [e["number"] for e in missing],
        "manifest": str(MANIFEST_JSON),
        "markdown": str(MANIFEST_MD),
    })


if __name__ == "__main__":
    main()
