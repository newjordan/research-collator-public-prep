#!/usr/bin/env python3
"""Apply known-safe sanitization replacements to the public deploy bundle.

Scope: output/preview/ only. Source code (render_*.py etc.) is not touched —
the deploy bundle is what ships to Vercel; sources stay in the private repo.

Replacements (kept narrow on purpose — anything not on this list is left alone):
  - "/home/frosty40/" → "~/"
  - exact Tailscale IPs in TAILSCALE_IPS  → "<tailnet-ip>"

Idempotent: replacement strings do not match any input pattern, so re-running
is a no-op once clean. Reports per-file change counts to stdout.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCAN_DIR = ROOT / "output" / "preview"

TAILSCALE_IPS = ["100.65.33.110", "100.65.33.119", "100.65.33.140"]
PUBLIC_IPS = ["35.192.20.187"]  # Real SSH endpoints surfaced by audit.

# (search, replace) — applied as raw bytes so binary-safe and encoding-agnostic.
REPLACEMENTS: list[tuple[bytes, bytes]] = [
    (b"/home/frosty40/", b"~/"),
] + [(ip.encode(), b"<tailnet-ip>") for ip in TAILSCALE_IPS] \
  + [(ip.encode(), b"<redacted-ip>") for ip in PUBLIC_IPS]


def sanitize_file(path: Path, dry_run: bool) -> dict[str, int]:
    try:
        data = path.read_bytes()
    except (OSError, PermissionError):
        return {}
    if b"\x00" in data[:4096]:  # binary
        return {}
    counts: dict[str, int] = {}
    new = data
    for needle, replacement in REPLACEMENTS:
        n = new.count(needle)
        if n:
            counts[needle.decode()] = n
            new = new.replace(needle, replacement)
    if counts and not dry_run and new != data:
        path.write_bytes(new)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-dir", type=Path, default=DEFAULT_SCAN_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    totals: dict[str, int] = {}
    files_changed = 0
    for path in sorted(args.scan_dir.rglob("*")):
        if not path.is_file():
            continue
        per = sanitize_file(path, args.dry_run)
        if per:
            files_changed += 1
            for k, v in per.items():
                totals[k] = totals.get(k, 0) + v

    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    print(f"[{mode}] scan_dir={args.scan_dir.relative_to(ROOT)}")
    print(f"[{mode}] files_changed={files_changed}")
    for k, v in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"[{mode}]   {k!r} → {v} replacements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
