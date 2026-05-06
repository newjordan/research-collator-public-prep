#!/usr/bin/env python3
"""Mine local Claude/Codex transcripts for model-architecture changes.

This is intentionally deterministic and local-only. It does not call an LLM and
it does not feed chat transcripts into the daily renderer. The output is a
separate review ledger under output/conversation_architecture/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "config.yaml"
DEFAULT_OUT_DIR = REPO_ROOT / "output" / "conversation_architecture"
LOCAL_TZ = ZoneInfo("America/Chicago")

ARCH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("flat_layers", re.compile(r"\b(?:NUM_FLAT_LAYERS|flat[- ]?layers?|n_layer|num_layers|model depth)\b", re.I)),
    ("depth_width", re.compile(r"\b(?:depth[- ]?sweep|width[- ]?sweep|n_embd|hidden(?:_size)?|model width|choke_dim)\b", re.I)),
    ("crawler_loop", re.compile(r"\b(?:crawler|CRAWLER_[A-Z0-9_]+|crawler loops?|loop[- ]?specific|recurren(?:ce|t))\b", re.I)),
    ("attention_rope", re.compile(r"\b(?:(?<!flash[-_])attention|attn_mode|qk|kv|rope|rotary|heads?|n_head|causal horizon)\b", re.I)),
    ("mlp_ffn", re.compile(r"\b(?:MLP|feed[- ]?forward|ffn|choke|pyramid|residual)\b", re.I)),
    ("tap_anchor_gate", re.compile(r"\b(?:CRAWLER_TAP|TAP_DIM|ANCHOR_DIM|encoder tap|anchor_dim|anchor state|smear|FLOW|inst_dim|gated encoder)\b", re.I)),
    ("tokenizer_vocab", re.compile(r"\b(?:model tokenizer|TOKENIZER_PATH|tokenizer_path|vocab|sp\d{3,6}|BPE|sentencepiece)\b", re.I)),
    ("quant_arch", re.compile(r"\b(?:int6|int7|GPTQ|quant(?:ized|ization)?|roundtrip)\b", re.I)),
    ("model_file", re.compile(r"\b(?:train_gpt|run\.py|model\.py|final_model|\.ptz)\b", re.I)),
    ("llm_arch", re.compile(r"\b(?:transformer (?:model|block|layers?)|GPT|LLM|embedding|MoE|experts?|LoRA|SFT|DPO|PPO)\b", re.I)),
]

MODEL_CONTEXT_RE = re.compile(
    r"\b(?:parameter[- ]?golf|train_gpt|val_bpb|val_loss|BPB|int6|int7|"
    r"CRAWLER_[A-Z0-9_]+|NUM_FLAT_LAYERS|TAP_DIM|ANCHOR_DIM|n_layer|n_embd|"
    r"n_head|transformer (?:model|block|layers?)|model tokenizer|TOKENIZER_PATH|tokenizer_path|vocab|MLP|attention|rope|final_model|\.ptz|"
    r"crawler architecture|crawler loops?|flat[- ]?layers?)\b",
    re.I,
)
WEAK_CONTEXT_RE = re.compile(
    r"\b(?:model|architecture|architectural|ablation|baseline|variant|leg|arm|"
    r"parameter[- ]?golf|SOTA|BPB|val_bpb|val_loss|train(?:ing)?)\b",
    re.I,
)
ACTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("add", re.compile(r"\badd(?:ed|ing)?\b", re.I)),
    ("remove", re.compile(r"\bremov(?:e|ed|ing)|drop(?:ped|ping)?\b", re.I)),
    ("change", re.compile(r"\bchang(?:e|ed|ing)|switch(?:ed|ing)?|swap(?:ped|ping)?|replace(?:d|ment)?\b", re.I)),
    ("tune", re.compile(r"\btun(?:e|ed|ing)|sweep|ablat(?:e|ed|ion)|test(?:ed|ing)?|gate(?:d)?\b", re.I)),
    ("set", re.compile(r"\bset(?:ting)?|enable(?:d|ing)?|disable(?:d|ing)?|configure(?:d|ing)?\b", re.I)),
    ("promote", re.compile(r"\bpromot(?:e|ed|ing)|bake(?:d)? in|baseline|champion|winner\b", re.I)),
    ("scale", re.compile(r"\bincreas(?:e|ed|ing)|decreas(?:e|ed|ing)|expand(?:ed|ing)?|shrink(?:ed|ing)?\b", re.I)),
    ("port", re.compile(r"\bport(?:ed|ing)?|copy(?:ing)?|migrat(?:e|ed|ing)\b", re.I)),
    ("implement", re.compile(r"\bimplement(?:ed|ing)?|wire(?:d|ing)?|refactor(?:ed|ing)?\b", re.I)),
]
METRIC_RE = re.compile(r"\b(?:val_bpb|val_loss|BPB|int6_sw_bpb|raw_bpb)\b", re.I)
ASSIGNMENT_RE = re.compile(r"\b[A-Z][A-Z0-9_]{3,}\s*=\s*[-+.\w,]+")
INFRA_NOISE_RE = re.compile(
    r"\b(?:docker|compose|container|tailscale|tunnel|ssh|endpoint|health|backup|"
    r"restore|grafana|prometheus|node\s*22|npm|systemd|desktop|comfyui|comfy ui|"
    r"agent orchestrator|lane\s+[123]|director|network|port|firewall|certificate)\b",
    re.I,
)
RUNTIME_NOISE_RE = re.compile(
    r"\b(?:FA3|flash[-_]?attn|flash[- ]?attention|CUDA|libcudart|PYTHONPATH|"
    r"LD_LIBRARY_PATH|pip install|torch\.distributed|nvidia[-_])\b",
    re.I,
)
STRUCTURAL_TAGS = {
    "flat_layers", "depth_width", "crawler_loop", "attention_rope", "mlp_ffn",
    "tap_anchor_gate", "tokenizer_vocab", "quant_arch", "llm_arch",
}
AUTO_PROMPT_RE = re.compile(r"# AGENTS\.md instructions|base_instructions|permissions instructions", re.I)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Extract local model-architecture timeline events from Claude/Codex transcript JSONLs."
    )
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", action="append", help="Local date to mine, YYYY-MM-DD. Repeatable.")
    group.add_argument("--start", help="Start local date, YYYY-MM-DD. Requires --end unless --days is used.")
    group.add_argument("--all", action="store_true", help="Mine all local transcript dates.")
    ap.add_argument("--end", help="End local date, YYYY-MM-DD, inclusive.")
    ap.add_argument("--days", type=int, default=None, help="Number of days from --start, inclusive of start.")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--min-score", type=int, default=6)
    ap.add_argument("--include-tool-results", action="store_true",
                    help="Also mine tool result/output text. Default mines user/assistant text only.")
    return ap.parse_args()


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def date_window(args: argparse.Namespace) -> tuple[dt.date | None, dt.date | None, str]:
    if args.all:
        return None, None, "all"
    if args.date:
        dates = sorted(parse_date(d) for d in args.date)
        if len(dates) == 1:
            return dates[0], dates[0], dates[0].isoformat()
        return dates[0], dates[-1], f"{dates[0].isoformat()}_to_{dates[-1].isoformat()}"
    start = parse_date(args.start)
    if args.days is not None:
        if args.days < 1:
            raise SystemExit("--days must be >= 1")
        end = start + dt.timedelta(days=args.days - 1)
    elif args.end:
        end = parse_date(args.end)
    else:
        raise SystemExit("--start requires --end or --days")
    if end < start:
        raise SystemExit("--end must be >= --start")
    return start, end, f"{start.isoformat()}_to_{end.isoformat()}"


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def local_parts(ts: dt.datetime) -> tuple[str, str, str]:
    local = ts.astimezone(LOCAL_TZ)
    return local.date().isoformat(), local.strftime("%H:%M:%S"), local.isoformat(timespec="seconds")


def in_window(ts: dt.datetime, start: dt.date | None, end: dt.date | None) -> bool:
    if start is None or end is None:
        return True
    d = ts.astimezone(LOCAL_TZ).date()
    return start <= d <= end


def text_from_content(content: Any, include_tool_results: bool) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(content, str):
        out.append(("message", content))
    elif isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            typ = item.get("type")
            if typ in {"text", "input_text", "output_text"} and isinstance(item.get("text"), str):
                out.append(("message", item["text"]))
            elif typ == "tool_result" and include_tool_results:
                tool_content = item.get("content")
                if isinstance(tool_content, str):
                    out.append(("tool_result", tool_content))
                elif isinstance(tool_content, list):
                    for part in tool_content:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            out.append(("tool_result", part["text"]))
    return out


def normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def snippets_for_text(text: str) -> Iterable[str]:
    clean = normalize_text(text)
    if not clean or AUTO_PROMPT_RE.search(clean):
        return []

    matches: list[re.Match[str]] = []
    for _, pat in ARCH_PATTERNS:
        matches.extend(pat.finditer(clean))
    if not matches:
        return []

    snippets: list[str] = []
    seen: set[tuple[int, int]] = set()
    for m in sorted(matches, key=lambda x: x.start()):
        start = max(0, m.start() - 420)
        end = min(len(clean), m.end() + 520)
        while start > 0 and clean[start - 1] not in ".!?\n":
            start -= 1
            if m.start() - start > 650:
                break
        while end < len(clean) and clean[end] not in ".!?\n":
            end += 1
            if end - m.end() > 750:
                break
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        snippet = re.sub(r"\s+", " ", clean[start:end]).strip()
        if snippet:
            snippets.append(snippet)
    return snippets


def score_snippet(snippet: str) -> tuple[int, list[str], list[str], list[str]]:
    arch_tags = [name for name, pat in ARCH_PATTERNS if pat.search(snippet)]
    action_tags = [name for name, pat in ACTION_PATTERNS if pat.search(snippet)]
    weak = bool(WEAK_CONTEXT_RE.search(snippet))
    metric = bool(METRIC_RE.search(snippet))
    assignment = bool(ASSIGNMENT_RE.search(snippet))
    noisy = bool(INFRA_NOISE_RE.search(snippet))
    runtime_noisy = bool(RUNTIME_NOISE_RE.search(snippet))

    if not arch_tags:
        return 0, [], [], []
    if not (set(arch_tags) & STRUCTURAL_TAGS):
        return 0, arch_tags, action_tags, ["no_structural_tag"]
    if not MODEL_CONTEXT_RE.search(snippet):
        return 0, arch_tags, action_tags, ["no_model_context"]
    if not (action_tags or metric or assignment):
        return 0, arch_tags, action_tags, []
    if noisy and not metric and not assignment:
        return 0, arch_tags, action_tags, ["infra_noise"]
    if runtime_noisy and not re.search(
        r"\b(?:num_heads|num_kv_heads|attention_mode|n_head|n_embd|"
        r"NUM_FLAT_LAYERS|CRAWLER_[A-Z0-9_]+|TAP_DIM|ANCHOR_DIM|"
        r"MLP|mlp=|mlp_kernel|vocab|tokenizer_path)\b",
        snippet,
        re.I,
    ):
        return 0, arch_tags, action_tags, ["runtime_noise"]

    score = 2 + (2 * len(set(arch_tags))) + len(set(action_tags))
    if weak:
        score += 1
    if metric:
        score += 2
    if assignment:
        score += 2
    if noisy:
        score -= 3
    return score, sorted(set(arch_tags)), sorted(set(action_tags)), (["infra_noise"] if noisy else [])


def iter_codex_entries(path: Path, include_tool_results: bool) -> Iterable[dict[str, Any]]:
    session_id = ""
    cwd = ""
    fallback_ts: dt.datetime | None = None
    with path.open(encoding="utf-8", errors="replace") as f:
        for line_no, raw in enumerate(f, start=1):
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ts = parse_ts(ev.get("timestamp"))
            if ts is not None:
                fallback_ts = ts
            typ = ev.get("type")
            payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
            if typ == "session_meta":
                session_id = str(payload.get("id") or session_id)
                cwd = str(payload.get("cwd") or cwd)
                meta_ts = parse_ts(payload.get("timestamp"))
                if meta_ts is not None:
                    fallback_ts = meta_ts
                continue

            texts: list[tuple[str, str, str]] = []
            if typ == "event_msg":
                inner = payload.get("type")
                if inner == "user_message" and isinstance(payload.get("message"), str):
                    texts.append(("user", "message", payload["message"]))
                elif inner == "agent_message" and isinstance(payload.get("message"), str):
                    texts.append(("assistant", "message", payload["message"]))
            elif typ == "response_item":
                ptyp = payload.get("type")
                if ptyp == "message":
                    role = payload.get("role")
                    if role in {"user", "assistant"}:
                        for source, text in text_from_content(payload.get("content"), include_tool_results):
                            texts.append((role, source, text))
                elif ptyp == "function_call_output" and include_tool_results:
                    output = payload.get("output")
                    if isinstance(output, str):
                        texts.append(("tool", "tool_output", output))

            event_ts = ts or fallback_ts
            if event_ts is None:
                continue
            for role, source, text in texts:
                yield {
                    "timestamp": event_ts,
                    "source": "codex",
                    "role": role,
                    "text_source": source,
                    "session_id": session_id or path.stem,
                    "cwd": cwd,
                    "session_path": str(path),
                    "line_no": line_no,
                    "text": text,
                }


def iter_claude_entries(path: Path, include_tool_results: bool) -> Iterable[dict[str, Any]]:
    session_id = path.stem
    cwd = ""
    with path.open(encoding="utf-8", errors="replace") as f:
        for line_no, raw in enumerate(f, start=1):
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ts = parse_ts(ev.get("timestamp"))
            if ts is None:
                continue
            session_id = str(ev.get("sessionId") or session_id)
            cwd = str(ev.get("cwd") or cwd)
            typ = ev.get("type")
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
            role = msg.get("role") or typ
            if typ not in {"user", "assistant"}:
                continue
            for source, text in text_from_content(msg.get("content"), include_tool_results):
                yield {
                    "timestamp": ts,
                    "source": "claude",
                    "role": role if role in {"user", "assistant"} else typ,
                    "text_source": source,
                    "session_id": session_id,
                    "cwd": cwd,
                    "session_path": str(path),
                    "line_no": line_no,
                    "text": text,
                }


def transcript_paths(cfg: dict[str, Any]) -> tuple[list[Path], list[Path]]:
    codex_root = Path(str(cfg.get("codex_sessions_root") or "/home/frosty40/.codex/sessions"))
    claude_root = Path(str(cfg.get("claude_projects_root") or "/home/frosty40/.claude/projects"))
    codex = sorted(codex_root.rglob("*.jsonl")) if codex_root.is_dir() else []
    claude = sorted(claude_root.rglob("*.jsonl")) if claude_root.is_dir() else []
    return codex, claude


def mine(cfg: dict[str, Any], start: dt.date | None, end: dt.date | None,
         min_score: int, include_tool_results: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    codex_paths, claude_paths = transcript_paths(cfg)
    stats: dict[str, Any] = {
        "codex_files_total": len(codex_paths),
        "claude_files_total": len(claude_paths),
        "session_files_with_messages_in_window": {},
        "messages_scanned": 0,
        "messages_scanned_by_source": Counter(),
        "messages_with_arch_terms": 0,
        "candidate_snippets": 0,
        "rejected_snippets": Counter(),
    }
    events: list[dict[str, Any]] = []
    seen_events: set[tuple[str, str, str, str]] = set()
    session_files_in_window: defaultdict[str, set[str]] = defaultdict(set)

    def process(entry: dict[str, Any]) -> None:
        ts = entry["timestamp"]
        if not in_window(ts, start, end):
            return
        session_files_in_window[entry["source"]].add(entry["session_path"])
        stats["messages_scanned"] += 1
        stats["messages_scanned_by_source"][entry["source"]] += 1
        snippets = list(snippets_for_text(entry["text"]))
        if snippets:
            stats["messages_with_arch_terms"] += 1
        for snippet in snippets:
            stats["candidate_snippets"] += 1
            score, arch_tags, action_tags, rejection_tags = score_snippet(snippet)
            if score < min_score:
                key = "low_score"
                if rejection_tags:
                    key = ",".join(rejection_tags)
                stats["rejected_snippets"][key] += 1
                continue
            snippet_hash = hashlib.sha1(snippet.encode("utf-8", errors="replace")).hexdigest()[:16]
            dedupe_key = (entry["session_path"], entry["role"], entry["text_source"], snippet_hash)
            if dedupe_key in seen_events:
                continue
            seen_events.add(dedupe_key)
            local_date, local_time, local_iso = local_parts(ts)
            events.append({
                "local_date": local_date,
                "local_time": local_time,
                "local_iso": local_iso,
                "timestamp_utc": ts.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "source": entry["source"],
                "role": entry["role"],
                "text_source": entry["text_source"],
                "session_id": entry["session_id"],
                "cwd": entry["cwd"],
                "session_path": entry["session_path"],
                "line_no": entry["line_no"],
                "score": score,
                "architecture_tags": arch_tags,
                "action_tags": action_tags,
                "snippet_sha1": snippet_hash,
                "snippet": snippet,
            })

    for path in codex_paths:
        for entry in iter_codex_entries(path, include_tool_results):
            process(entry)
    for path in claude_paths:
        for entry in iter_claude_entries(path, include_tool_results):
            process(entry)

    events.sort(key=lambda e: (e["local_date"], e["local_time"], e["source"], e["session_path"], e["line_no"]))
    stats["events"] = len(events)
    stats["events_by_date"] = dict(Counter(e["local_date"] for e in events))
    stats["events_by_source"] = dict(Counter(e["source"] for e in events))
    stats["messages_scanned_by_source"] = dict(stats["messages_scanned_by_source"])
    stats["session_files_with_messages_in_window"] = {
        source: len(paths) for source, paths in session_files_in_window.items()
    }
    stats["rejected_snippets"] = dict(stats["rejected_snippets"])
    return events, stats


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_markdown(path: Path, events: list[dict[str, Any]], stats: dict[str, Any],
                   start: dt.date | None, end: dt.date | None, min_score: int,
                   include_tool_results: bool) -> None:
    title_window = "all transcript dates" if start is None else (
        start.isoformat() if start == end else f"{start.isoformat()} to {end.isoformat()}"
    )
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_date[event["local_date"]].append(event)

    lines: list[str] = []
    lines.append("# Conversation Architecture Timeline")
    lines.append("")
    lines.append(f"- Window: `{title_window}`")
    lines.append(f"- Strict min score: `{min_score}`")
    lines.append(f"- Tool results included: `{str(include_tool_results).lower()}`")
    lines.append(f"- Codex transcript files available: `{stats['codex_files_total']}`")
    lines.append(f"- Claude transcript files available: `{stats['claude_files_total']}`")
    lines.append(f"- Session files with messages in window: `{stats['session_files_with_messages_in_window']}`")
    lines.append(f"- Messages scanned in window: `{stats['messages_scanned']}`")
    lines.append(f"- Messages by source: `{stats['messages_scanned_by_source']}`")
    lines.append(f"- Candidate snippets: `{stats['candidate_snippets']}`")
    lines.append(f"- Accepted architecture-change events: `{len(events)}`")
    lines.append("")

    if not events:
        lines.append("No strict model-architecture-change events matched this window.")
    else:
        for date_key in sorted(by_date):
            lines.append(f"## {date_key}")
            lines.append("")
            for event in by_date[date_key]:
                tags = ", ".join(event["architecture_tags"])
                actions = ", ".join(event["action_tags"]) or "metric/config evidence"
                source = f"{event['source']} {event['role']}:{event['text_source']}"
                cwd = f" cwd=`{event['cwd']}`" if event.get("cwd") else ""
                lines.append(
                    f"### {event['local_time']} score={event['score']} {source}{cwd}"
                )
                lines.append("")
                lines.append(f"- Tags: `{tags}`")
                lines.append(f"- Actions: `{actions}`")
                lines.append(f"- Session: `{event['session_path']}:{event['line_no']}`")
                lines.append("")
                lines.append("> " + event["snippet"].replace("\n", "\n> "))
                lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    start, end, label = date_window(args)
    cfg = load_config(Path(args.config))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    events, stats = mine(
        cfg=cfg,
        start=start,
        end=end,
        min_score=args.min_score,
        include_tool_results=args.include_tool_results,
    )
    output_label = label + ("_with_tool_results" if args.include_tool_results else "")
    base = out_dir / output_label
    jsonl_path = base.with_suffix(".events.jsonl")
    md_path = base.with_suffix(".timeline.md")
    summary_path = base.with_suffix(".summary.json")
    write_jsonl(jsonl_path, events)
    write_markdown(md_path, events, stats, start, end, args.min_score, args.include_tool_results)
    summary = {
        "window": label,
        "output_label": output_label,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "min_score": args.min_score,
        "include_tool_results": args.include_tool_results,
        "events_path": str(jsonl_path),
        "timeline_path": str(md_path),
        "stats": stats,
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
