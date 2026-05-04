#!/usr/bin/env python3
"""Forensic enrichment pass — adds git commits, Claude sessions, Codex sessions
to the SQLite index that the v1 file-extension walker missed.

Each new artifact gets a synthetic abs_path so it slots into the same table:
    git_commit       abs_path = "git://<repo_label>/<sha>"
    claude_session   abs_path = path to the .jsonl file (real path)
    codex_session    abs_path = path to the .jsonl file (real path)

Re-runnable. Idempotent (UNIQUE on abs_path).

Usage:
    python3 enrich.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import yaml

EXTRACTION_VERSION = "enrich_v1"

# Patterns to fish numeric metrics out of commit messages (BPB / val_loss)
RE_BPB = re.compile(r"\b(\d+\.\d{2,5})\s*BPB\b", re.IGNORECASE)
RE_VAL_LOSS = re.compile(r"val_loss[ =:]+\s*(\d+\.\d{2,5})", re.IGNORECASE)
RE_VAL_BPB = re.compile(r"val_bpb[ =:]+\s*(\d+\.\d{2,5})", re.IGNORECASE)

# Context words that signal a number is a DELTA / regression / cost,
# not an absolute val_bpb measurement.
DELTA_CONTEXT_WORDS = (
    # Deltas / regressions / costs
    "cost", "costing", "costed", "regression", "degraded", "degrading",
    "degrade", "lagging", "drop of", "drops", "dropping",
    "improvement of", "gain of", "delta", "gap", "diff",
    "→", " by ", "lost ", "lose ", "destroyed", "destroying",
    # Targets / aspirations / not-yet-achieved (filter out planned numbers)
    "target", "targeting", "targets", "aim ", "aspire", "goal of",
    "sub-", "below", "beat ", "beating", "above ", "less than",
    "aiming", "expected", "hope to", "should ",
)


def _classify_bpb_match(text: str, m: re.Match) -> str:
    """absolute | delta — based on surrounding 80-char window."""
    start = max(0, m.start() - 80)
    end = min(len(text), m.end() + 20)
    window = text[start:end].lower()
    if any(d in window for d in DELTA_CONTEXT_WORDS):
        return "delta"
    return "absolute"


def upsert(conn: sqlite3.Connection, row: dict):
    cols = list(row.keys())
    placeholders = ",".join(["?"] * len(cols))
    update_clause = ",".join(f"{c}=excluded.{c}" for c in cols if c != "abs_path")
    sql = (f"INSERT INTO artifacts ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT(abs_path) DO UPDATE SET {update_clause}")
    conn.execute(sql, [row[c] for c in cols])


# ---------- git commits ------------------------------------------------------

def walk_git_repo(repo: dict) -> list[dict]:
    """Run `git log` on a repo and emit one record per commit.
    Author date is the timestamp; committer date is ignored."""
    repo_path = repo["path"]
    label = repo["label"]
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        return []

    fmt = "%H%x1f%aI%x1f%an%x1f%s%x1f%b%x1e"
    try:
        out = subprocess.check_output(
            ["git", "-C", repo_path, "log", "--no-merges",
             f"--pretty=format:{fmt}", "-z"],
            text=True, errors="replace",
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  git failed for {label}: {e}")
        return []

    records = []
    # Records are separated by RS (0x1e); fields by US (0x1f)
    for blob in out.split("\x1e"):
        blob = blob.strip("\x00\n ")
        if not blob:
            continue
        parts = blob.split("\x1f")
        if len(parts) < 4:
            continue
        sha, author_iso, author_name, subject = parts[:4]
        body = parts[4] if len(parts) > 4 else ""

        # Pull file count + lines changed quickly
        try:
            stat_out = subprocess.check_output(
                ["git", "-C", repo_path, "show", "--shortstat", "--oneline", sha],
                text=True, errors="replace",
            )
            # last line of shortstat: " N files changed, X insertions(+), Y deletions(-)"
            shortstat = ""
            for line in stat_out.splitlines()[::-1]:
                if " file" in line and ("change" in line or "changed" in line):
                    shortstat = line.strip()
                    break
        except subprocess.CalledProcessError:
            shortstat = ""

        # Pull metrics from commit message. Sanity floor at 0.1: parameter-golf
        # val_bpb has never gone below ~0.3 (Will DePue's championship-era
        # numbers); anything <0.1 is noise / a delta the context-classifier
        # missed.
        # Prefer explicit `val_bpb=X` form over plain `X BPB` since the
        # explicit-prefix form is unambiguously a labeled measurement.
        metrics: dict[str, float] = {}
        text = f"{subject}\n{body}"
        SANITY_FLOOR = 0.1
        explicit_abs: list[float] = []   # val_bpb=X
        implicit_abs: list[float] = []   # "X BPB" without delta context
        deltas: list[float] = []
        for m in RE_BPB.finditer(text):
            v = float(m.group(1))
            if v < SANITY_FLOOR:
                continue
            if _classify_bpb_match(text, m) == "delta":
                deltas.append(v)
            else:
                implicit_abs.append(v)
        for m in RE_VAL_BPB.finditer(text):
            v = float(m.group(1))
            if v >= SANITY_FLOOR:
                explicit_abs.append(v)
        chosen = explicit_abs or implicit_abs
        if chosen:
            metrics["val_bpb"] = min(chosen)
            if len(chosen) > 1:
                metrics["val_bpb_n_measurements"] = len(chosen)
                metrics["val_bpb_max"] = max(chosen)
        if deltas:
            metrics["val_bpb_delta"] = max(deltas, key=abs)
        for m in RE_VAL_LOSS.finditer(text):
            metrics["val_loss"] = float(m.group(1))
            break

        # mtime from author date (ISO with tz). Convert to UTC ISO.
        try:
            ad = dt.datetime.fromisoformat(author_iso)
            mtime_iso = ad.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except ValueError:
            mtime_iso = author_iso

        rec = {
            "source_root": repo_path,
            "source_label": label,
            "rel_path": f"{sha}",
            "abs_path": f"git://{label}/{sha}",
            "file_kind": "git_commit",
            "file_size_bytes": len(blob),
            "mtime_iso": mtime_iso,
            "title": subject[:300],
            "summary": (body[:1000] if body else shortstat) or shortstat,
            "metrics_json": json.dumps(metrics) if metrics else None,
            "extraction_version": EXTRACTION_VERSION,
            "extracted_at_iso": dt.datetime.now(tz=dt.timezone.utc)
                                  .isoformat(timespec="seconds").replace("+00:00", "Z"),
            "too_large": 0,
        }
        records.append(rec)
    return records


# ---------- Claude session JSONLs --------------------------------------------

def walk_claude_session(session_path: str) -> dict | None:
    """Parse a Claude Code session .jsonl, returning one summary record."""
    try:
        with open(session_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None
    if not lines:
        return None

    n_user_turns = 0
    n_assistant_turns = 0
    tool_uses: dict[str, int] = {}
    files_touched: set[str] = set()
    first_user_text: str | None = None
    start_iso: str | None = None
    end_iso: str | None = None

    for raw in lines:
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        ts = ev.get("timestamp")
        if isinstance(ts, str):
            if start_iso is None:
                start_iso = ts
            end_iso = ts

        et = ev.get("type") or ""
        if et == "user":
            n_user_turns += 1
            msg = ev.get("message") or {}
            content = msg.get("content")
            if isinstance(content, str) and first_user_text is None:
                first_user_text = content
            elif isinstance(content, list) and first_user_text is None:
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        first_user_text = c.get("text") or ""
                        break
        elif et == "assistant":
            n_assistant_turns += 1
            msg = ev.get("message") or {}
            content = msg.get("content")
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        tname = c.get("name") or "?"
                        tool_uses[tname] = tool_uses.get(tname, 0) + 1
                        inp = c.get("input") or {}
                        for fld in ("file_path", "path", "filename"):
                            if isinstance(inp.get(fld), str):
                                files_touched.add(inp[fld])
                        # Bash command file mentions are too noisy to enumerate.

    # Pick the timestamp to assign this session to (earliest event).
    mtime_iso = start_iso or ""
    if mtime_iso and "+" in mtime_iso:
        try:
            t = dt.datetime.fromisoformat(mtime_iso)
            mtime_iso = t.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except ValueError:
            pass
    if not mtime_iso:
        try:
            mt = os.path.getmtime(session_path)
            mtime_iso = dt.datetime.fromtimestamp(mt, tz=dt.timezone.utc) \
                          .isoformat(timespec="seconds").replace("+00:00", "Z")
        except OSError:
            mtime_iso = ""

    title = (first_user_text or Path(session_path).stem)[:240].replace("\n", " ").strip()
    if not title:
        title = Path(session_path).stem

    project_label = Path(session_path).parent.name
    summary = (
        f"{n_user_turns} user turns · {n_assistant_turns} assistant turns · "
        f"{sum(tool_uses.values())} tool uses ({', '.join(f'{k}:{v}' for k,v in sorted(tool_uses.items(), key=lambda x: -x[1])[:5])}) · "
        f"{len(files_touched)} files touched"
    )

    metrics = {
        "n_user_turns": n_user_turns,
        "n_assistant_turns": n_assistant_turns,
        "n_tool_uses": sum(tool_uses.values()),
        "n_files_touched": len(files_touched),
    }

    try:
        size = os.path.getsize(session_path)
    except OSError:
        size = len("".join(lines).encode("utf-8", errors="replace"))

    return {
        "source_root": str(Path(session_path).parents[1]),
        "source_label": f"claude:{project_label}",
        "rel_path": Path(session_path).name,
        "abs_path": session_path,
        "file_kind": "claude_session",
        "file_size_bytes": size,
        "mtime_iso": mtime_iso,
        "title": title,
        "summary": summary,
        "metrics_json": json.dumps(metrics),
        "extraction_version": EXTRACTION_VERSION,
        "extracted_at_iso": dt.datetime.now(tz=dt.timezone.utc)
                              .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "too_large": 0,
    }


# ---------- Codex session JSONLs ---------------------------------------------

def walk_codex_session(session_path: str) -> dict | None:
    """Parse a Codex rollout .jsonl. Codex schema differs from Claude:
    events are wrapped as `{timestamp, type, payload}`; the conversation
    lives in `type=event_msg` events whose `payload.type` is the actual
    inner kind (user_message, agent_message, exec_command_begin, ...)."""
    try:
        with open(session_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None
    if not lines:
        return None

    n_user_turns = 0
    n_agent_turns = 0
    n_exec_commands = 0
    n_patches = 0
    n_tasks_started = 0
    n_tasks_completed = 0
    first_user_text: str | None = None
    last_agent_text: str | None = None
    start_iso: str | None = None
    end_iso: str | None = None
    cwd: str | None = None

    for raw in lines:
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        ts = ev.get("timestamp")
        if isinstance(ts, str):
            if start_iso is None:
                start_iso = ts
            end_iso = ts
        et = ev.get("type") or ""
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        if et == "session_meta":
            cwd = payload.get("cwd") or cwd
            continue
        if et != "event_msg":
            continue
        inner = payload.get("type") or ""
        if inner == "user_message":
            n_user_turns += 1
            msg = payload.get("message")
            if isinstance(msg, str) and first_user_text is None:
                first_user_text = msg
        elif inner == "agent_message":
            n_agent_turns += 1
            msg = payload.get("message")
            if isinstance(msg, str):
                last_agent_text = msg
        elif inner in ("exec_command_begin", "exec_command_end"):
            # Codex only emits _end events most of the time; count those.
            if inner == "exec_command_end":
                n_exec_commands += 1
        elif inner in ("patch_apply_begin", "patch_apply_end"):
            if inner == "patch_apply_end":
                n_patches += 1
        elif inner == "task_started":
            n_tasks_started += 1
        elif inner == "task_complete":
            n_tasks_completed += 1

    # Compute session duration
    duration_seconds: float | None = None
    if start_iso and end_iso:
        try:
            s = dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            e = dt.datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
            duration_seconds = (e - s).total_seconds()
        except ValueError:
            duration_seconds = None

    mtime_iso = start_iso or ""
    if mtime_iso and "+" in mtime_iso:
        try:
            t = dt.datetime.fromisoformat(mtime_iso)
            mtime_iso = t.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except ValueError:
            pass
    if not mtime_iso:
        try:
            mt = os.path.getmtime(session_path)
            mtime_iso = dt.datetime.fromtimestamp(mt, tz=dt.timezone.utc) \
                          .isoformat(timespec="seconds").replace("+00:00", "Z")
        except OSError:
            mtime_iso = ""

    title = (first_user_text or Path(session_path).stem)[:240].replace("\n", " ").strip()
    if not title:
        title = Path(session_path).stem

    summary_bits = [
        f"{n_user_turns} user turns",
        f"{n_agent_turns} agent turns",
        f"{n_exec_commands} bash execs",
        f"{n_patches} patches",
        f"{n_tasks_started} tasks",
    ]
    if duration_seconds is not None and duration_seconds > 0:
        summary_bits.append(f"~{duration_seconds / 3600.0:.1f}h session")
    if cwd:
        summary_bits.append(f"cwd={Path(cwd).name}")
    summary = " · ".join(summary_bits)

    metrics = {
        "n_user_turns": n_user_turns,
        "n_agent_turns": n_agent_turns,
        "n_exec_commands": n_exec_commands,
        "n_patches": n_patches,
        "n_tasks_started": n_tasks_started,
        "n_tasks_completed": n_tasks_completed,
    }
    if duration_seconds is not None:
        metrics["session_duration_seconds"] = duration_seconds

    try:
        size = os.path.getsize(session_path)
    except OSError:
        size = sum(len(line.encode("utf-8", errors="replace")) for line in lines)

    return {
        "source_root": str(Path(session_path).parents[1]),
        "source_label": "codex_session",
        "rel_path": Path(session_path).name,
        "abs_path": session_path,
        "file_kind": "codex_session",
        "file_size_bytes": size,
        "mtime_iso": mtime_iso,
        "title": title,
        "summary": summary,
        "metrics_json": json.dumps(metrics),
        "extraction_version": EXTRACTION_VERSION,
        "extracted_at_iso": dt.datetime.now(tz=dt.timezone.utc)
                              .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "too_large": 0,
    }


# ---------- main -------------------------------------------------------------

def main():
    cfg = yaml.safe_load(open("/home/frosty40/research_collator/config.yaml"))
    db = cfg["sqlite_path"]
    conn = sqlite3.connect(db)

    t0 = time.perf_counter()

    print("[1/3] git commits across configured repos...")
    git_total = 0
    for repo in cfg.get("git_repos", []):
        recs = walk_git_repo(repo)
        with conn:
            for r in recs:
                upsert(conn, r)
        git_total += len(recs)
        print(f"  {repo['label']:30s} {len(recs)} commits")

    print()
    print("[2/3] Claude session jsonls...")
    claude_root = cfg.get("claude_projects_root")
    claude_total = 0
    if claude_root and os.path.isdir(claude_root):
        for jsonl in Path(claude_root).rglob("*.jsonl"):
            rec = walk_claude_session(str(jsonl))
            if rec:
                with conn:
                    upsert(conn, rec)
                claude_total += 1
        print(f"  {claude_total} sessions indexed")

    print()
    print("[3/3] Codex session jsonls...")
    codex_root = cfg.get("codex_sessions_root")
    codex_total = 0
    if codex_root and os.path.isdir(codex_root):
        for jsonl in Path(codex_root).rglob("*.jsonl"):
            rec = walk_codex_session(str(jsonl))
            if rec:
                with conn:
                    upsert(conn, rec)
                codex_total += 1
        print(f"  {codex_total} sessions indexed")

    conn.commit()
    conn.close()
    print()
    print(f"done. git={git_total}, claude={claude_total}, codex={codex_total}, "
          f"wall={time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
