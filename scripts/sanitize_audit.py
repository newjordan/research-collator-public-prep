#!/usr/bin/env python3
"""Sanitize audit: scan the public-deploy target for personal-data leaks.

Scope: output/preview/ (the static bundle that will ship to Vercel).
Reports finding counts per category plus up to N example hits per category
to /tmp/sanitize_findings.md and stdout.

Patterns are tuned for this repo's known surface (Tailscale, vast.ai,
dgx-spark, parameter-golf-lab, frosty40 home, the user's email, common API
key shapes). Add to PATTERNS as new categories surface.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCAN_DIR = ROOT / "output" / "preview"
DEFAULT_FINDINGS = Path("/tmp/sanitize_findings.md")
DEFAULT_STATE = Path("/tmp/sanitize_audit_state.json")

# (category, pattern, allowlist) — allowlist suppresses known-benign matches
PATTERNS: list[tuple[str, re.Pattern, re.Pattern | None]] = [
    ("ipv4_private_192", re.compile(rb"\b192\.168\.\d{1,3}\.\d{1,3}\b"), None),
    ("ipv4_private_10", re.compile(rb"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), None),
    ("ipv4_private_172", re.compile(rb"\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"), None),
    ("tailscale_100x", re.compile(rb"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), None),
    ("home_path_frosty40", re.compile(rb"/home/frosty40"), None),
    ("home_path_users", re.compile(rb"/Users/[A-Za-z0-9_.-]+"), None),
    ("hostname_dgxspark", re.compile(rb"dgx[-_]?spark", re.IGNORECASE), None),
    ("vendor_vastai", re.compile(rb"\bvast\.?ai\b", re.IGNORECASE), None),
    ("vendor_runpod", re.compile(rb"\brunpod\b", re.IGNORECASE), None),
    ("user_handle_frosty40", re.compile(rb"\bfrosty40\b"), None),
    ("user_handle_newjordan", re.compile(rb"\bnewjordan\b", re.IGNORECASE), None),
    ("private_repo_paramgolf", re.compile(rb"parameter[-_]golf[-_]lab"), None),
    ("private_tool_mempalace", re.compile(rb"\bmempalace\b", re.IGNORECASE), None),
    ("email_specific", re.compile(rb"newjordan@gmail\.com", re.IGNORECASE), None),
    ("email_generic", re.compile(rb"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), None),
    ("api_key_anthropic", re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{20,}"), None),
    ("api_key_openai", re.compile(rb"\bsk-[A-Za-z0-9]{32,}"), None),
    ("api_key_github_pat", re.compile(rb"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"), None),
    ("api_key_google", re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}"), None),
    ("api_key_aws", re.compile(rb"\bAKIA[0-9A-Z]{16}\b"), None),
    ("api_key_jwt", re.compile(rb"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"), None),
    ("api_key_bearer", re.compile(rb"[Bb]earer\s+[A-Za-z0-9._-]{20,}"), None),
    ("secret_keyword", re.compile(rb"(?i)(api[_-]?key|secret|password|credential)\s*[:=]\s*['\"]?[A-Za-z0-9_-]{12,}"), None),
    ("env_token_assignment", re.compile(rb"(?i)\b(token|access[_-]key|auth[_-]token)\s*=\s*['\"]?[A-Za-z0-9_-]{16,}"), None),
]


def iter_files(scan_dir: Path) -> list[Path]:
    return sorted(p for p in scan_dir.rglob("*") if p.is_file())


def audit_file(path: Path, max_examples_per_cat: int) -> dict[str, list[tuple[int, str]]]:
    hits: dict[str, list[tuple[int, str]]] = {}
    try:
        data = path.read_bytes()
    except (OSError, PermissionError):
        return hits
    if b"\x00" in data[:4096]:  # binary
        return hits
    lines = data.splitlines()
    for cat, pattern, allow in PATTERNS:
        for i, line in enumerate(lines, start=1):
            if pattern.search(line):
                if allow and allow.search(line):
                    continue
                snippet = line.strip().decode("utf-8", errors="replace")[:240]
                hits.setdefault(cat, []).append((i, snippet))
                if len(hits[cat]) >= max_examples_per_cat:
                    break
    return hits


def run(scan_dir: Path, findings_path: Path, state_path: Path,
        max_examples: int = 3) -> dict:
    files = iter_files(scan_dir)
    totals: dict[str, int] = {}
    examples: dict[str, list[tuple[str, int, str]]] = {}
    files_with_hits = 0
    for path in files:
        hits = audit_file(path, max_examples)
        if hits:
            files_with_hits += 1
        for cat, found in hits.items():
            totals[cat] = totals.get(cat, 0) + len(found)
            slot = examples.setdefault(cat, [])
            for line_no, snippet in found:
                if len(slot) < max_examples:
                    rel = str(path.relative_to(ROOT))
                    slot.append((rel, line_no, snippet))

    summary = {
        "scan_dir": str(scan_dir.relative_to(ROOT)),
        "files_scanned": len(files),
        "files_with_hits": files_with_hits,
        "total_findings": sum(totals.values()),
        "by_category": dict(sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
    state_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# Sanitize audit\n")
    lines.append(f"- scan_dir: `{summary['scan_dir']}`")
    lines.append(f"- files_scanned: {summary['files_scanned']}")
    lines.append(f"- files_with_hits: {summary['files_with_hits']}")
    lines.append(f"- total_findings: {summary['total_findings']}\n")
    if not totals:
        lines.append("**No findings.** Public deploy target looks clean against the current pattern set.\n")
    else:
        lines.append("## Findings by category\n")
        for cat, count in summary["by_category"].items():
            lines.append(f"### `{cat}` — {count}")
            for rel, line_no, snippet in examples.get(cat, []):
                lines.append(f"- `{rel}:{line_no}` — `{snippet}`")
            lines.append("")
    findings_path.write_text("\n".join(lines), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-dir", type=Path, default=DEFAULT_SCAN_DIR)
    ap.add_argument("--findings", type=Path, default=DEFAULT_FINDINGS)
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--max-examples", type=int, default=3)
    args = ap.parse_args()
    summary = run(args.scan_dir, args.findings, args.state, args.max_examples)
    json.dump(summary, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
