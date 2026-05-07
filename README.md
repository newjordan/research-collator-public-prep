# research-collator

Pure-Python deterministic scraper + Karpathy-style daily report renderer for
parameter-golf research. Walks local research dirs + git history + agent
session JSONLs, extracts metrics with strict regex (no LLM at scrape/render
time), and renders one self-contained HTML report per work day in a late-80s
lab-protocol aesthetic.

## What's here

| File | Role |
|---|---|
| `stripper.py` | File walker → SQLite. Handlers for `.md`, `.json`, `.py`, `.csv`, `.tsv`, `.log`, `.out`, `.pt` (metadata only). Strict patterns; no LLM. |
| `enrich.py` | Adds git commits + Claude session JSONLs + Codex session JSONLs to the index. Pulls val_bpb / val_loss out of commit messages with delta-vs-absolute classification + sanity floor. |
| `classify.py` | Two-camp classifier (`experimental` vs `neural`) + a third `daily_grind` camp for codex rollouts. Path / source / keyword rules, no LLM. |
| `render_day.py` | Builds one daily HTML report. Header dot-leader fields, classification bar, Karpathy-style time-axis chart, test-runs table with embedded training-log disclosures and clickable links. Kernel-heavy days can headline custom-kernel/FA3 timing ratios and render as their own kernel classification. Chat sessions are never rendered as supporting research files. |
| `render_all.py` | Batch-renders every date with activity + a journey-arc front page. |
| `plot.py` | Matplotlib helpers. `day_chart` (per-day trajectory) and `journey_chart` (50-day arc). |
| `templates/daily_report_locked.html` | Locked base HTML/CSS template. `render_day.py` validates the style hash before rendering. |
| `scripts/verify_scraper_contract.py` | Fail-closed scraper/index gate for template-critical fields, metrics, day attribution, training-log embeds, and retrieval indexes. |
| `scripts/verify_daily_template.py` | Structural gate for the locked daily-page standard. Verifies the CSS lock, two-section layout, full-width log disclosures, and no Section 3 leakage. |
| `scripts/audit_daily_accuracy.py` | Row-level daily accuracy harness for wrong-test/wrong-day detection and evidence provenance. |
| `ACCURACY_HARNESS.md` | Accuracy workflow: exact audit first, targeted grep review second, RAG only as a non-authoritative search layer. |
| `chat_extract_local.py` | Separate, optional cumulative chat-log extractor. Uses only local Ollama Qwen and fails closed on cloud/non-Qwen models. Not part of scrape/render. |
| `ablation_label_local.py` | Separate, optional Nemo3 ablation-label suggestion lane. Calls only local vLLM, writes review artifacts, and only approved JSONL labels affect rendering. |
| `scripts/mine_conversation_architecture.py` | Deterministic Claude/Codex transcript miner for offline audit only. No LLM. Its artifacts are never rendered into daily report pages. |
| `config.yaml` | Roots to walk, exclusion list, file-extension → handler map. |

## Template lock

Daily pages are locked to the `daily-report-v2.0-wide-log-panel` standard:

- base visual lock: `templates/daily_report_locked.html`
- executable spec: `TEMPLATE.md`
- renderer gate: `LOCKED_TEMPLATE_STYLE_SHA256` in `render_day.py`
- verification gate: `python3 scripts/verify_daily_template.py --all`

## Research chronology

Daily numbering starts at the first proven personal parameter-golf research
event: `2026-03-18 = DAY 001` and ends at the final submission afternoon on
`2026-05-01`. Mockingbird is the final campaign submission. Earlier
DGX/studio/agent/ml-lab bootstrap artifacts, public upstream competition launch
records, and post-final-submission artifacts may still be indexed and rendered
by explicit date, but they do not count toward the research-day ordinal.

## Validity floor

Project convention: any `val_bpb < 1.06` is a known eval error, plotted
inside a quiet invalid zone on the chart and excluded from the running-min
`BEST VALID` line. Marked `INVALID` in the test-runs table. This rule is
BPB-only; custom-kernel/FA3 ratio charts do not render the invalid BPB zone.

## Camp axis

The scraper stores two top-level test camps plus a daily-grind narrative track:

- **experimental** — crawler / megakernel / ouroboros / helix / clowncar /
  jepa / shroud / hypothesis / ablation / etc.
- **neural** — strict baselines, leaderboard submissions, racing legs,
  competitive sources (SOTA_FINAL, sota_rascal).
- **daily_grind** — codex rollouts (narrative summaries of session work).

Daily rendering adds one presentation-only classification:

- **kernel** — custom-kernel/FA3 timing work. When a day headlines
  `CUSTOM/FA3 FB RATIO` or `CUSTOM/FA3 FWD RATIO`, its Test Runs and
  classification bar render as kernel instead of burying that work under
  experimental.

The daily header classification bar is active-only: it does not print
zero-count labels for classifications that were not worked on that day.

Section 2.0 rows always use the locked dropdown pattern in `OPEN`: training-log
rows expand to full log text, and non-log rows expand to recovered source/run
metadata.

Daily reports do not present Codex/Claude conversations as research evidence.
There is no Section 3 in the canonical daily page. Conversation-derived
artifacts may be indexed for offline audit, but they must never render in the
daily HTML body.

## How to run end-to-end

```bash
python3 stripper.py            # walk research roots → index.sqlite
python3 enrich.py              # +git commits, +claude/codex sessions
python3 scripts/mine_conversation_architecture.py --start 2026-03-18 --end 2026-05-01 --index
python3 classify.py            # tag every record with camp
python3 scripts/verify_scraper_contract.py
python3 render_day.py --day 1              # research DAY 001 = 2026-03-18
python3 render_day.py --date 2026-03-28   # one day
python3 render_all.py          # all days + journey arc + index page
python3 scripts/verify_daily_template.py --all
python3 scripts/audit_daily_accuracy.py --all
```

Output lands in `output/preview/<DATE>.html` (self-contained, base64 PNGs
embedded, with training logs in full-width disclosure rows — works offline).

Optional local chat extraction, no paid API:

```bash
python3 chat_extract_local.py --date 2026-03-28 --dry-run
python3 chat_extract_local.py --date 2026-03-28 --model qwen3-coder:30b
```

Outputs land in `output/chat_extract/`. The first command writes only the
chunk manifest; the second calls local Ollama Qwen. These raw extracts are
inputs for a final research-oriented accuracy pass, not daily-report evidence.

Optional local conversation architecture mining, no LLM:

```bash
python3 scripts/mine_conversation_architecture.py --date 2026-03-28
python3 scripts/mine_conversation_architecture.py --start 2026-03-02 --end 2026-03-03
```

Outputs land in `output/conversation_architecture/` as JSONL, Markdown, and a
summary JSON. This miner reads raw Claude/Codex JSONLs at message granularity,
filters infra/UI chatter out, and emits only strict model-architecture-change
signals. Add `--index` only when you want those signals in SQLite for offline
audit. They are not rendered into daily pages.

Optional local ablation-label suggestions, no paid API:

```bash
python3 ablation_label_local.py --date 2026-03-28 --dry-run
python3 ablation_label_local.py --date 2026-03-28
python3 ablation_label_local.py --promote-reviewed output/ablation_labels/<run>.review.jsonl
python3 render_day.py --date 2026-03-28
```

The labeler calls local Nemo3 through `http://127.0.0.1:8000/v1` with model
`nemotron_3_nano_omni`. Suggestions land in `output/ablation_labels/` with
`approved: false`; the renderer only uses rows promoted into
`output/ablation_labels/approved.jsonl`, keyed by date, row number, and raw
title hash.

## License

Private working tree.

## Master template

[`TEMPLATE.md`](TEMPLATE.md) is the canonical specification: locked palette,
layout, chart contract, scraper contract, invariants, and the current template
standard id. Any change to the per-day report must update `TEMPLATE.md`, the
locked template hash, and the verifier in the same patch.
