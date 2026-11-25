#!/usr/bin/env python3
"""Local Nemo3 ablation-label suggestions for daily reports.

This is intentionally a separate, offline lane. It calls only a local
OpenAI-compatible vLLM server, writes review artifacts, and never changes the
daily report unless reviewed labels are promoted into approved.jsonl.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

from pathlib import Path
from typing import Any

import paths
import render_day

DB = Path(render_day.DB)
OUT_DIR = render_day.OUT_ROOT / "ablation_labels"
DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_MODEL = "nemotron_3_nano_omni"


def utc_now_label() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def post_json(url: str, payload: dict[str, Any], timeout: int = 900) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url: str, timeout: int = 30) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def assert_local_nemo3(base_url: str, model: str) -> None:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise SystemExit(f"Unsupported model URL scheme: {base_url}")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(f"Refusing non-local model endpoint: {base_url}")
    if "nemo" not in model.lower() and "nemotron" not in model.lower():
        raise SystemExit(f"Refusing non-Nemo/Nemotron model for ablation labels: {model}")

    try:
        models = get_json(f"{base_url.rstrip('/')}/models")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Cannot reach local Nemo3 vLLM server at {base_url}: {exc}") from exc
    ids = sorted(item.get("id", "") for item in models.get("data", []))
    if model not in ids:
        raise SystemExit(f"Model {model!r} not served locally. Available: {ids}")


def dates_from_args(conn: sqlite3.Connection, args: argparse.Namespace) -> list[str]:
    if args.date:
        return [args.date]
    dates = sorted(render_day.artifact_day_index(conn).keys())
    if args.since:
        dates = [d for d in dates if d >= args.since]
    if args.until:
        dates = [d for d in dates if d <= args.until]
    if not dates:
        raise SystemExit("No dates selected")
    return dates


def row_key(date: str, row: dict[str, Any]) -> str:
    return f"{date}#{int(row['n']):03d}:{render_day.ablation_title_sha(row.get('title') or '')[:16]}"


def status_for(metric: str, value: float) -> str:
    if render_day.is_below_floor(metric, value):
        return "INVALID"
    if render_day.is_crash_value(metric, value):
        return "CRASH"
    return "OK"


def build_rows_for_date(conn: sqlite3.Connection, date: str,
                        metric_override: str | None = None) -> tuple[str | None, list[dict[str, Any]]]:
    records = render_day.fetch_day(conn, date)
    metric = metric_override or render_day.pick_headline_metric(records)
    if not metric:
        return None, []
    baseline = render_day.best_before(conn, date, metric)
    rows = render_day.extract_test_rows(records, metric, baseline)
    return metric, rows


def build_prompt(date: str, metric: str, rows: list[dict[str, Any]]) -> str:
    compact_rows: list[dict[str, Any]] = []
    previous_by_camp: dict[str, str] = {}
    for row in rows:
        camp = row.get("camp", "experimental")
        previous_same_camp = row.get("_previous_same_camp_ablation")
        if previous_same_camp is None:
            previous_same_camp = previous_by_camp.get(camp, "")
        compact_rows.append({
            "row_key": row_key(date, row),
            "n": row["n"],
            "time": row.get("time") or "",
            "camp": camp,
            "hardware": row.get("hardware") or "",
            "raw_ablation": row.get("title") or "",
            "value": round(float(row["value"]), 6),
            "status": status_for(metric, float(row["value"])),
            "source": row.get("source_label") or "",
            "open_label": row.get("link_label") or "",
            "previous_same_camp_ablation": previous_same_camp,
        })
        previous_by_camp[camp] = row.get("title") or ""

    return (
        "You label the ABLATION column for a daily machine-learning research report.\n"
        "This is sensitive provenance work. Use only the supplied rows. Do not invent "
        "unstated mechanisms, outcomes, or causality.\n\n"
        "Goal: replace raw filenames/commit messages with short labels that explain "
        "what changed, using chronology and previous same-camp rows.\n\n"
        "Rules:\n"
        "- Return strict JSON: {\"labels\": [ ... ]}.\n"
        "- Emit exactly one label object for every input row_key.\n"
        "- suggested_ablation: <= 56 chars, plain noun phrase, no markdown.\n"
        "- change_from_previous: <= 100 chars, describe the concrete delta from the previous same-camp row; use 'starting point' if none.\n"
        "- family: architecture/family if evident, otherwise 'unknown'.\n"
        "- confidence: number from 0.0 to 1.0.\n"
        "- needs_review: true for ambiguous filenames, pure metric claims, commit-only rows, or low confidence.\n"
        "- evidence_terms: short list of exact tokens copied from raw_ablation that justify the label.\n"
        "- Preserve important knobs when present: seed, control, EMA, loop/no_loop, pre/post, A/B/C/D, delta, int8/int6, vocab, MLP, quantization, recursion phase.\n"
        "- Do not label a run as better/worse just because of val_bpb. Metrics belong outside the ablation label.\n\n"
        f"DATE: {date}\n"
        f"METRIC: {metric}\n"
        f"ROWS:\n{json.dumps(compact_rows, indent=2)}\n"
    )


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def fallback_label(date: str, metric: str, row: dict[str, Any], reason: str) -> dict[str, Any]:
    raw = re.sub(r"\s+", " ", row.get("title") or "").strip()
    stem = raw.rsplit("/", 1)[-1]
    stem = re.sub(r"\.(log|json|txt|md|py)$", "", stem, flags=re.IGNORECASE)
    return {
        "date": date,
        "metric": metric,
        "row_key": row_key(date, row),
        "n": row["n"],
        "camp": row.get("camp", "experimental"),
        "title_sha256": render_day.ablation_title_sha(row.get("title") or ""),
        "raw_ablation": row.get("title") or "",
        "suggested_ablation": (stem[:56] or "Unlabeled run"),
        "change_from_previous": reason,
        "family": "unknown",
        "confidence": 0.0,
        "needs_review": True,
        "evidence_terms": [],
        "approved": False,
        "model": None,
        "local_only": True,
    }


def normalize_labels(date: str, metric: str, rows: list[dict[str, Any]],
                     response: dict[str, Any], model: str) -> list[dict[str, Any]]:
    raw_labels = [item for item in response.get("labels", []) if isinstance(item, dict)]
    by_key = {str(item.get("row_key")): item for item in raw_labels}
    by_n: dict[int, dict[str, Any]] = {}
    for item in raw_labels:
        try:
            by_n[int(item.get("n"))] = item
        except (TypeError, ValueError):
            continue
    out: list[dict[str, Any]] = []
    positional_ok = len(raw_labels) == len(rows)
    for idx, row in enumerate(rows):
        key = row_key(date, row)
        item = by_key.get(key) or by_n.get(int(row["n"]))
        if item is None and positional_ok:
            item = raw_labels[idx]
        if not isinstance(item, dict):
            out.append(fallback_label(date, metric, row, "model omitted this row"))
            continue
        label = re.sub(r"\s+", " ", str(item.get("suggested_ablation") or "")).strip()
        if not label:
            out.append(fallback_label(date, metric, row, "empty model label"))
            continue
        out.append({
            "date": date,
            "metric": metric,
            "row_key": key,
            "n": row["n"],
            "camp": row.get("camp", "experimental"),
            "title_sha256": render_day.ablation_title_sha(row.get("title") or ""),
            "raw_ablation": row.get("title") or "",
            "suggested_ablation": label[:96],
            "change_from_previous": re.sub(r"\s+", " ", str(item.get("change_from_previous") or "")).strip()[:160],
            "family": re.sub(r"\s+", " ", str(item.get("family") or "unknown")).strip()[:48],
            "confidence": item.get("confidence", 0.0),
            "needs_review": bool(item.get("needs_review", True)),
            "evidence_terms": item.get("evidence_terms") if isinstance(item.get("evidence_terms"), list) else [],
            "approved": False,
            "model": model,
            "local_only": True,
        })
    return out


def call_nemo3(base_url: str, model: str, prompt: str,
               timeout: int, max_tokens: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a careful local-only research provenance labeler. Return JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    response = post_json(f"{base_url.rstrip('/')}/chat/completions", payload, timeout=timeout)
    message = response["choices"][0].get("message") or {}
    content = message.get("content")
    if content is None:
        finish = response["choices"][0].get("finish_reason")
        raise RuntimeError(f"model returned no content; finish_reason={finish}")
    return parse_json_object(content)


def row_chunks(rows: list[dict[str, Any]], chunk_rows: int) -> list[list[dict[str, Any]]]:
    if chunk_rows <= 0 or len(rows) <= chunk_rows:
        return [rows]
    return [rows[i:i + chunk_rows] for i in range(0, len(rows), chunk_rows)]


def annotate_previous_same_camp(rows: list[dict[str, Any]]) -> None:
    previous_by_camp: dict[str, str] = {}
    for row in rows:
        camp = row.get("camp", "experimental")
        row["_previous_same_camp_ablation"] = previous_by_camp.get(camp, "")
        previous_by_camp[camp] = row.get("title") or ""


def write_review_md(path: Path, review_jsonl_path: Path, labels: list[dict[str, Any]]) -> None:
    lines = [
        "# Nemo3 Ablation Label Review",
        "",
        "Edit the JSONL `approved` field to true for rows you accept, then run:",
        "",
        "```bash",
        f"python3 ablation_label_local.py --promote-reviewed {review_jsonl_path}",
        "```",
        "",
        "| DATE | # | CAMP | RAW ABLATION | SUGGESTED | CONF | REVIEW | CHANGE |",
        "|---|---:|---|---|---|---:|---|---|",
    ]
    for item in labels:
        raw = str(item["raw_ablation"]).replace("|", "\\|")
        sug = str(item["suggested_ablation"]).replace("|", "\\|")
        change = str(item.get("change_from_previous") or "").replace("|", "\\|")
        lines.append(
            f"| {item['date']} | {item['n']} | {item['camp']} | {raw[:90]} | "
            f"{sug} | {item.get('confidence', 0.0)} | {item.get('needs_review')} | {change[:100]} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def promote_reviewed(review_path: Path, approved_path: Path) -> int:
    approved_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, Any]] = {}
    if approved_path.exists():
        with approved_path.open(encoding="utf-8") as f:
            for raw in f:
                if not raw.strip():
                    continue
                item = json.loads(raw)
                existing[str(item.get("row_key"))] = item
    promoted = 0
    with review_path.open(encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            item = json.loads(raw)
            if item.get("approved") is not True:
                continue
            item["approved_ablation"] = item.get("approved_ablation") or item.get("suggested_ablation")
            existing[str(item.get("row_key"))] = item
            promoted += 1
    with approved_path.open("w", encoding="utf-8") as f:
        for key in sorted(existing):
            f.write(json.dumps(existing[key], ensure_ascii=False) + "\n")
    print(f"promoted={promoted}")
    print(f"approved={approved_path}")
    return 0


def run(args: argparse.Namespace) -> int:
    if args.promote_reviewed:
        return promote_reviewed(Path(args.promote_reviewed), Path(args.approved_path))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_label = args.run_label or utc_now_label()
    manifest_path = OUT_DIR / f"{run_label}.manifest.json"
    review_jsonl_path = OUT_DIR / f"{run_label}.review.jsonl"
    review_md_path = OUT_DIR / f"{run_label}.review.md"
    prompt_path = OUT_DIR / f"{run_label}.prompt.txt"
    raw_response_path = OUT_DIR / f"{run_label}.raw_response.jsonl"

    conn = paths.open_index(DB)
    try:
        dates = dates_from_args(conn, args)
        all_labels: list[dict[str, Any]] = []
        manifest: dict[str, Any] = {
            "run_label": run_label,
            "model": args.model,
            "base_url": args.base_url,
            "dates": dates,
            "local_only": True,
            "dry_run": args.dry_run,
        }
        if not args.dry_run:
            assert_local_nemo3(args.base_url, args.model)
        with prompt_path.open("w", encoding="utf-8") as prompt_f, raw_response_path.open("w", encoding="utf-8") as raw_f:
            for date in dates:
                metric, rows = build_rows_for_date(conn, date, args.metric)
                if args.limit_rows:
                    rows = rows[:args.limit_rows]
                if not metric or not rows:
                    continue
                annotate_previous_same_camp(rows)
                chunks = row_chunks(rows, args.chunk_rows)
                for chunk_index, chunk in enumerate(chunks, start=1):
                    print(f"labeling {date} chunk {chunk_index}/{len(chunks)} rows={len(chunk)}", flush=True)
                    prompt = build_prompt(date, metric, chunk)
                    prompt_f.write(f"\n\n===== {date} chunk {chunk_index}/{len(chunks)} =====\n{prompt}\n")
                    if args.dry_run:
                        for row in chunk:
                            all_labels.append(fallback_label(date, metric, row, "dry run; no model call"))
                        continue
                    try:
                        response = call_nemo3(args.base_url, args.model, prompt, args.timeout, args.max_tokens)
                    except Exception as exc:
                        raw_f.write(json.dumps({
                            "date": date,
                            "metric": metric,
                            "chunk_index": chunk_index,
                            "chunk_count": len(chunks),
                            "error": str(exc),
                        }, ensure_ascii=False) + "\n")
                        for row in chunk:
                            all_labels.append(fallback_label(date, metric, row, f"model error: {exc}"))
                        continue
                    raw_f.write(json.dumps({
                        "date": date,
                        "metric": metric,
                        "chunk_index": chunk_index,
                        "chunk_count": len(chunks),
                        "response": response,
                    }, ensure_ascii=False) + "\n")
                    all_labels.extend(normalize_labels(date, metric, chunk, response, args.model))
    finally:
        conn.close()

    manifest["labels"] = len(all_labels)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with review_jsonl_path.open("w", encoding="utf-8") as f:
        for item in all_labels:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    write_review_md(review_md_path, review_jsonl_path, all_labels)

    print(f"labels={len(all_labels)}")
    print(f"manifest={manifest_path}")
    print(f"review_jsonl={review_jsonl_path}")
    print(f"review_md={review_md_path}")
    print(f"prompt={prompt_path}")
    print(f"raw_response={raw_response_path}")
    if args.dry_run:
        print("dry_run=true, no model calls made")
    return 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    target = ap.add_mutually_exclusive_group()
    target.add_argument("--date", help="Only label one report date, YYYY-MM-DD")
    target.add_argument("--since", help="Inclusive start date, YYYY-MM-DD")
    ap.add_argument("--until", help="Inclusive end date, YYYY-MM-DD")
    ap.add_argument("--metric", help="Override headline metric")
    ap.add_argument("--limit-rows", type=int, default=0, help="Smoke-test only the first N rows")
    ap.add_argument("--chunk-rows", type=int, default=1,
                    help="Rows per local-model call; 0 sends a full date in one call")
    ap.add_argument("--model", default=os.environ.get("LOCAL_ABLATION_MODEL", DEFAULT_MODEL))
    ap.add_argument("--base-url", default=os.environ.get("LOCAL_ABLATION_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--run-label", help="Output filename stem")
    ap.add_argument("--dry-run", action="store_true", help="Write review scaffolding without model calls")
    ap.add_argument("--promote-reviewed", help="Reviewed JSONL with approved=true rows to merge")
    ap.add_argument("--approved-path", default=str(render_day.ABLATION_LABELS_PATH))
    args = ap.parse_args()
    if not args.promote_reviewed and not (args.date or args.since):
        ap.error("one of --date, --since, or --promote-reviewed is required")
    return args


if __name__ == "__main__":
    sys.exit(run(parse_args()))
