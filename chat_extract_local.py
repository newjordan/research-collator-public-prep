#!/usr/bin/env python3
"""Local-only research extraction from Codex/Claude chat logs.

This is intentionally separate from stripper/enrich/classify/render. Daily
reports must not present chat transcripts as supporting research files. This
tool is for later cumulative reconstruction: it uses indexed session JSONLs as
raw material, chunks them, and asks a local Ollama Qwen model for structured,
research-only extraction.

No paid API fallback exists. Cloud Ollama models and non-Qwen models fail
closed unless the caller changes this file.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import socket
import sqlite3
import sys
import urllib.error
import urllib.request

from pathlib import Path
from typing import Any, Iterable

import paths

_CFG = paths.load_config()
DB = Path(_CFG["sqlite_path"])
OUT_DIR = paths.resolve_repo_path("~/research_collator/output", "output") / "chat_extract"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_QWEN_MODEL = "qwen3-coder:30b"
SESSION_KINDS = ("codex_session", "claude_session")
RESEARCH_OUTPUT_SCHEMA = {
    "research_summary": "short research-oriented summary only",
    "files_created_or_modified": ["path or filename plus purpose"],
    "tests_or_runs": ["commands, launches, audits, benchmarks, or checks"],
    "metrics_or_results": ["measured values and source snippets, not claims"],
    "planning_items": ["plans, decisions, next steps tied to research work"],
    "exclude_or_private_dev_notes": ["private/dev/tooling issues to omit"],
    "confidence_notes": ["uncertainties or evidence gaps"],
}
METRIC_OR_LOG_RE = re.compile(
    r"\b(?:val_bpb|val_loss|loss|bpb|metric|score|pass|fail|error|pytest|"
    r"bench|benchmark|audit|render|log|result|checkpoint|launch|run)\b",
    re.IGNORECASE,
)


def utc_now_label() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def post_json(url: str, payload: dict[str, Any], timeout: int = 600) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url: str, timeout: int = 20) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def assert_local_qwen_model(ollama_url: str, model: str) -> None:
    if "qwen" not in model.lower():
        raise SystemExit(f"Refusing non-Qwen model for chat extraction: {model}")
    try:
        tags = get_json(f"{ollama_url.rstrip('/')}/api/tags")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Cannot reach local Ollama at {ollama_url}: {exc}") from exc

    models = tags.get("models") or []
    matched = None
    for item in models:
        if item.get("name") == model or item.get("model") == model:
            matched = item
            break
    if not matched:
        names = ", ".join(sorted(m.get("name", "?") for m in models))
        raise SystemExit(f"Qwen model {model!r} is not installed. Available: {names}")
    if matched.get("remote_host") or ":cloud" in model:
        raise SystemExit(f"Refusing cloud-backed model for chat extraction: {model}")


def select_sessions(db_path: Path,
                    date: str | None,
                    since: str | None,
                    until: str | None,
                    limit: int | None) -> list[dict[str, Any]]:
    sql = (
        "SELECT abs_path, file_kind, source_label, title, summary, mtime_iso "
        "FROM artifacts WHERE file_kind IN (?, ?)"
    )
    args: list[Any] = list(SESSION_KINDS)
    if date:
        sql += " AND substr(mtime_iso, 1, 10) = ?"
        args.append(date)
    if since:
        sql += " AND substr(mtime_iso, 1, 10) >= ?"
        args.append(since)
    if until:
        sql += " AND substr(mtime_iso, 1, 10) <= ?"
        args.append(until)
    sql += " ORDER BY mtime_iso, abs_path"
    if limit:
        sql += " LIMIT ?"
        args.append(limit)

    conn = paths.open_index(db_path)
    try:
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict):
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif item.get("type") == "tool_use":
                name = item.get("name") or "tool"
                inp = item.get("input") if isinstance(item.get("input"), dict) else {}
                file_bits = []
                for key in ("file_path", "path", "filename"):
                    if isinstance(inp.get(key), str):
                        file_bits.append(f"{key}={inp[key]}")
                parts.append(f"TOOL_USE {name} {' '.join(file_bits)}".strip())
    return "\n".join(parts)


def codex_event_line(ev: dict[str, Any]) -> str | None:
    if ev.get("type") != "event_msg":
        return None
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    inner = payload.get("type") or ""
    if inner == "user_message":
        return "USER: " + str(payload.get("message") or "")
    if inner == "agent_message":
        return "AGENT: " + str(payload.get("message") or "")
    if inner == "exec_command_begin":
        cmd = str(payload.get("cmd") or payload.get("command") or "")
        return "COMMAND: " + cmd[:1200]
    if inner == "exec_command_end":
        output = str(payload.get("output") or "")
        if METRIC_OR_LOG_RE.search(output):
            return "COMMAND_OUTPUT_SNIP: " + output[:1600]
    if inner == "patch_apply_end":
        return "PATCH_APPLIED"
    return None


def claude_event_line(ev: dict[str, Any]) -> str | None:
    et = ev.get("type") or ""
    if et not in {"user", "assistant"}:
        return None
    msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
    text = content_text(msg.get("content"))
    if not text:
        return None
    role = "USER" if et == "user" else "ASSISTANT"
    return f"{role}: {text}"


def iter_session_lines(path: Path, kind: str) -> Iterable[str]:
    with path.open(encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            line = codex_event_line(ev) if kind == "codex_session" else claude_event_line(ev)
            if line:
                compact = re.sub(r"\n{3,}", "\n\n", line.strip())
                if compact:
                    yield compact


def chunk_lines(lines: Iterable[str], max_chars: int) -> list[str]:
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in lines:
        if len(line) + 2 > max_chars:
            if cur:
                chunks.append("\n\n".join(cur))
                cur = []
                cur_len = 0
            for start in range(0, len(line), max_chars):
                chunks.append(line[start:start + max_chars])
            continue
        add_len = len(line) + 2
        if cur and cur_len + add_len > max_chars:
            chunks.append("\n\n".join(cur))
            cur = []
            cur_len = 0
        cur.append(line)
        cur_len += add_len
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def build_prompt(session: dict[str, Any], chunk: str, chunk_index: int, chunk_count: int) -> str:
    schema = json.dumps(RESEARCH_OUTPUT_SCHEMA, indent=2)
    metadata = {
        "session_kind": session["file_kind"],
        "session_path": session["abs_path"],
        "source_label": session["source_label"],
        "mtime_iso": session["mtime_iso"],
        "index_title": session["title"],
        "index_summary": session["summary"],
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "host": socket.gethostname(),
    }
    return (
        "You are extracting research history from an agent chat transcript.\n"
        "Use only the supplied transcript chunk. Do not invent facts.\n"
        "Keep only research-relevant items: experiments, plans, tests, logs, "
        "metrics, created files, model/data changes, verification, and blockers "
        "that affect reproducibility.\n"
        "Private development issues, account/auth details, interpersonal content, "
        "tooling drama, and general chat are not research evidence. Put those in "
        "exclude_or_private_dev_notes only if they are necessary to explain why "
        "they were omitted.\n"
        "Return strict JSON with exactly these top-level keys:\n"
        f"{schema}\n\n"
        f"SESSION_METADATA:\n{json.dumps(metadata, indent=2)}\n\n"
        f"TRANSCRIPT_CHUNK:\n{chunk}\n"
    )


def run_extraction(args: argparse.Namespace) -> int:
    paths.announce("chat_extract_local", db=DB, out=OUT_DIR, model=args.model)
    sessions = select_sessions(DB, args.date, args.since, args.until, args.limit)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_label = args.run_label or utc_now_label()
    manifest_path = OUT_DIR / f"{run_label}.manifest.jsonl"
    output_path = OUT_DIR / f"{run_label}.local_qwen.jsonl"

    if not args.dry_run:
        assert_local_qwen_model(args.ollama_url, args.model)

    n_chunks = 0
    output_fh = None if args.dry_run else output_path.open("w", encoding="utf-8")
    try:
        with manifest_path.open("w", encoding="utf-8") as mf:
            of = output_fh
            assert args.dry_run or of is not None
            for session in sessions:
                path = Path(session["abs_path"])
                if not path.exists():
                    continue
                chunks = chunk_lines(iter_session_lines(path, session["file_kind"]), args.max_chars)
                if args.max_chunks_per_session:
                    chunks = chunks[:args.max_chunks_per_session]
                for idx, chunk in enumerate(chunks, start=1):
                    item = {
                        "session_path": session["abs_path"],
                        "session_kind": session["file_kind"],
                        "mtime_iso": session["mtime_iso"],
                        "chunk_index": idx,
                        "chunk_count": len(chunks),
                        "chars": len(chunk),
                        "model": args.model,
                        "local_only": True,
                    }
                    mf.write(json.dumps(item, ensure_ascii=False) + "\n")
                    n_chunks += 1
                    if args.dry_run:
                        continue
                    prompt = build_prompt(session, chunk, idx, len(chunks))
                    response = post_json(
                        f"{args.ollama_url.rstrip('/')}/api/generate",
                        {
                            "model": args.model,
                            "prompt": prompt,
                            "stream": False,
                            "format": "json",
                            "options": {"temperature": 0.0, "num_ctx": args.num_ctx},
                        },
                        timeout=args.timeout,
                    )
                    out = dict(item)
                    out["response"] = response.get("response", "")
                    out["done"] = response.get("done", False)
                    of.write(json.dumps(out, ensure_ascii=False) + "\n")
    finally:
        if output_fh is not None:
            output_fh.close()

    print(f"sessions={len(sessions)} chunks={n_chunks}")
    print(f"manifest={manifest_path}")
    if args.dry_run:
        print("dry_run=true, no model calls made")
    else:
        print(f"output={output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="Only sessions whose indexed date is YYYY-MM-DD")
    ap.add_argument("--since", help="Inclusive indexed start date YYYY-MM-DD")
    ap.add_argument("--until", help="Inclusive indexed end date YYYY-MM-DD")
    ap.add_argument("--limit", type=int, help="Max sessions to process")
    ap.add_argument("--max-chars", type=int, default=24000, help="Max chars per model chunk")
    ap.add_argument("--max-chunks-per-session", type=int, default=0,
                    help="0 means process every chunk")
    ap.add_argument("--model", default=os.environ.get("LOCAL_CHAT_QWEN_MODEL", DEFAULT_QWEN_MODEL))
    ap.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_URL))
    ap.add_argument("--num-ctx", type=int, default=32768)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--run-label", help="Output filename stem")
    ap.add_argument("--dry-run", action="store_true", help="Write manifest without local model calls")
    return ap.parse_args()


if __name__ == "__main__":
    sys.exit(run_extraction(parse_args()))
