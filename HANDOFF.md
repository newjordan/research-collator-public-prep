# Research Collator — Session Handoff (2026-05-05)

## Active Claude Work Order (2026-05-07)

For the current rollup work, use
[`CLAUDE_CATEGORY_REPORTS_HANDOFF.md`](CLAUDE_CATEGORY_REPORTS_HANDOFF.md).

That document supersedes the month-report idea. Keep the weekly reports, then
build cumulative category reports for experimental, neural, and kernel work
using two-week graph windows.

## Prior Claude Work Order (2026-05-06)

For the current bookkeeping-heavy campaign rebuild, use
[`CLAUDE_DAILY_REPORTS_HANDOFF.md`](CLAUDE_DAILY_REPORTS_HANDOFF.md).

That document supersedes the command/status details below for this exact task.
The current local SQLite index should be treated as partial state: start from a
clean `index.sqlite`, then run the full deterministic scrape, enrich,
conversation-architecture mining, classify, render, and verification pipeline.

## What this is

A deterministic per-day report generator for ~50 days of LLM/parameter-golf
research. Pipeline:

```
~/{ml-lab, parameter-golf-lab, sota_*, SOTA_FINAL}    git repos      ~/.claude / ~/.codex sessions
                  │                                       │                       │
                  └──────── stripper.py (pure Python) ────┴────── enrich.py ──────┘
                                              │
                                            classify.py
                                              │
                                       index.sqlite  (~13.7K rows)
                                              │
                                        render_day.py  ──▶  output/preview/<date>.html
                                              │
                                            plot.py    ──▶  output/assets/<date>/day_chart.png
```

**Hard rule (do not violate):** the stripper does NOT call any LLM. Pure
regex / AST / file-format parsers. The user burned full Claude usage in 30s
on a previous attempt with LLM-per-file scraping.

`TEMPLATE.md` is the canonical layout spec; the renderer follows it.
`README.md` points to TEMPLATE.md as the design lock.

## Correction Pass (2026-05-06)

The 2026-05-05 handoff below contains rules that were wrong and have been
superseded in code:

- DAY numbering now starts at the first proven parameter-golf research date:
  `2026-03-18 = DAY 001`. Prelude/bootstrap artifacts before that date remain
  renderable by explicit date, but are not counted in the research-day ordinal.
  `day_epoch` is legacy-only.
- The campaign ends on `2026-05-01`; the user's final submission was
  Mockingbird on the afternoon of that date. Post-final-submission artifacts
  can stay indexed for auditability, but they do not create campaign days.
- `records/track_*` is mostly public upstream competition/reference material,
  not the user's chronology. The stripper now marks `records/track_*` record
  folders as `is_reference_baseline=true` unless `submission.json` identifies
  a user-owned GitHub id/author. This prevents OpenAI launch records and
  external PR records from becoming fake user test runs.
- The missing early personal work is recovered through deterministic local
  conversation mining. `scripts/mine_conversation_architecture.py --index`
  writes structured `conversation_arch_event` rows into SQLite. The daily page
  can render those events in Section 2, while raw Claude/Codex transcripts
  remain out of the report body.
- The smart renderer now reads CSS from the recovered `Research Day.html`
  baseline so data rendering can change without creating a second visual
  style.
- SECTION 3.0 no longer presents Codex/Claude chat sessions or git commits
  as research support. It is limited to day-local created files, logs,
  planning/testing artifacts, summaries, scripts, CSV/JSON outputs, and
  checkpoints.
- Cumulative chat-log extraction is a separate lane in `chat_extract_local.py`.
  It uses local Ollama Qwen on `spark-2949`, fails closed on cloud/non-Qwen
  models, and is not part of scrape/render. Treat its JSONL as raw extraction
  input for a later research-oriented accuracy pass, not as report evidence.

## Session 1 (prior session) summary

- Built the stripper / enrich / classify / render skeleton.
- Locked the dark-charcoal US-Graphics-style aesthetic (5-token palette).
- Originally settled on Day 12 (2026-03-28) as the foundation block; keep the
  date as a regression sample, but do not trust the old ordinal blindly after
  the 2026-05-06 chronology correction.
- Applied Claude Design handoff layout (header dot-leaders, 3 sections,
  Test Runs table, supporting files, base64-embedded chart).
- Originally anchored DAY numbering to `day_epoch: 2026-03-17`; superseded by
  the 2026-05-06 correction pass above.
- Hardware extraction from training-log content, nested resolved_config
  JSON, and path strings; binary local/rented inference rule
  (runpod = H100, local DGX Spark = GB10 Blackwell).
- Type-weight scaled back to 400 everywhere except H1.

## This session (2026-05-05) — what I did

User asked for a Day-1 review with playwright. The audit surfaced
systemic data-accuracy bugs that were corrupting test counts across the
entire corpus, not just Day 1. Fixed in one pass:

### Bugs fixed (commit `4f4e5c1`)

1. **Cross-worktree duplicate counting.** The same `train.log` content
   was indexed up to 7× across multiple repo checkouts.
   - Fix: stripper computes `content_sha256` for every training_log;
     `fetch_day` dedups by sha. Result: 3467 → 2328 distinct training-log
     contents (1139 duplicates eliminated).

2. **Reference baselines counted as user tests.** Files inside
   `records/track_*/` are the parameter-golf repo's PUBLISHED canonical
   baselines (NaiveBaseline, FP16Embed_WD3600, LongContextSeq2048, etc.),
   not user experiments. Day 1 was showing the published NaiveBaseline as
   the user's only "test".
   - Fix: stripper tags `is_reference_baseline=true` on any path matching
     `records/track_*/`, `_NaiveBaseline*`, `published_baselines/`,
     `_baselines/`. Applied in BOTH `handle_training_log` and
     `handle_json_summary`. 748 records correctly tagged. Renderer skips
     them in 5 places: `extract_test_rows`, `tests_variety_pct`,
     `build_day_chart_records`, `pick_headline_metric`, `best_before`.

3. **UTC date bucketing rolled late-evening runs to the next day.** User
   is CDT (UTC-5); a run started 11:30 PM local appeared on next day's
   report.
   - Fix: `fetch_day` uses `date(mtime_iso, '-5 hours')`; `best_date()`
     mtime fallback applies the same -5h shift before extracting the
     date. Filename-encoded dates (the dominant signal for training_log
     files) are timezone-independent and unaffected.

4. **CLASSIFICATION % was "files-on-day mass", not research output.**
   Day 1 showed EXP 43% / NEU 57% with 21 records — but 0 actual tests.
   The 21 were sister files in baseline directories.
   - Fix: `by_camp` counts training_log records per camp (excluding
     reference baselines). Falls back to all-records on commit/session-
     only days.

5. **Architecture-family classifier blind on most days.** Days 1, 2, 25,
   35, 47 all showed `OTHER (×N)` because the pattern list was narrow
   and only checked the title.
   - Fix: extended `ARCH_FAMILIES` with 17 new families
     (NaiveBaseline, Staged Hybrid Bench, Watch/Handoff, Spark Smoke
     Kit, Nightcrawler, SOTA Crawler, SOTA v2 TTT, Exp-D TTT8 Stride32,
     FP16 Tied Embed, Long Context, Mixed Precision, Quasi-10B,
     Lower LR, SwiGLU+Warmdown, Int6 QAT, SmearGate/MuonWD, PGUT).
     `detect_arch_families` falls back to abs_path matching when title
     doesn't match — catches `run_s1337.log` style logs whose architecture
     is in the parent directory name.
   - Note: trailing `\b` removed from new patterns; `_` is a word char in
     Python regex so `\b` between letter and `_` doesn't match.

6. **Auto-blurb fabrication on 0-tests days.** Day 1 was claiming
   "allocation neural-leaning, the day was a mixed-architecture sweep"
   on a day with zero training runs.
   - Fix: `make_daily_summary_html` short-circuits when `n_tests == 0`
     to "no training runs launched on this date".

### Historical audit trail (pre-2026-05-06 chronology correction)

Cross-day verification spread (one playwright + SQL pass per fix):

| Day | Date       | Before | After | Notes                                  |
|-----|-----------|-------:|------:|----------------------------------------|
| 1   | 2026-03-17|   1    |   0   | NaiveBaseline correctly filtered       |
| 3   | 2026-03-19|   ?    |  17   | First real research day, all classified|
| 6   | 2026-03-22|   9    |   5   | 4 ref baselines purged                 |
| 12  | 2026-03-28|  35    |  33   | Heavy day, 2 baselines purged          |
| 25  | 2026-04-10|  13    |   6   | NIGHTCRAWLER family via path           |
| 35  | 2026-04-20|   0    |   0   | Kernel-bench day, no val_bpb (correct) |
| 47  | 2026-05-02|   0    |   0   | Sessions-only day (correct)            |

## What works now

- **Per-day HTML report.** Self-contained (base64 PNG chart embedded).
  3-section layout: Trajectory, Test Runs, Supporting Files.
- **Test Runs table.** One row per unique test title, deduped across
  worktrees by content sha. Hardware column populates as `8×H100 (runpod)`
  / `1×GB10` etc. via the local/rented inference rule.
- **Trajectory chart.** Time-axis Karpathy-style scatter with running-min
  step line, validity-floor red zone at 1.06 val_bpb.
- **Architecture-family classification.** Title-or-path matching against
  35+ families covers most of the corpus.
- **DAY numbering stable.** Anchored to the first proven personal
  parameter-golf research date: `2026-03-18 = DAY 001`, ending on
  `2026-05-01` with Mockingbird as the final submission. External/public
  upstream records and post-final-submission artifacts do not advance the
  research-day ordinal.
- **Conversation-mined architecture events.** The local transcript miner can
  inject structured `conversation_arch_event` rows into SQLite. These events
  appear in Section 2 when a day has architecture-change evidence but sparse
  training logs.

## Outstanding gaps (next-session priorities)

### S1 — high value, not done yet

1. **Val_bpb verification cross-check.** When a commit message claims
   `val_bpb=1.18` and the linked log shows `val_bpb=1.21`, the renderer
   prefers log-derived (correct). But we don't surface the disagreement.
   A "discrepancy" column on commit-message-only rows would let the user
   spot misclaims.

2. **Kernel-benchmark days surface as "0 tests".** Day 35 (Apr 20) had
   175 whale-microbenchmark JSONs measuring `fwd_mean_ms` — real work
   but invisible because the system is val_bpb-centric. Need a
   per-day-mode classifier: training day vs kernel-bench day vs
   session-only day. Each mode renders its own trajectory.

### S2 — quality-of-life

3. **Architecture name → "type" mapping.** User's eventual ask: replace
   architecture *names* (MEDUSA, CLOWNCAR, NIGHTCRAWLER) with their
   *type* (e.g. "speculative decoder", "MoE-routed", "self-distillation
   loop"). Deferred per user: "EVENTUALLY the architecture names will
   be replaced with the type, but that will be in the final pass of
   document cleanup."

4. **Hardware GPU type is inferred, not observed.** Application logs
   don't contain "NVIDIA H100" strings — that's in nvidia-smi prelude
   that's not captured. Inference rule (runpod → H100, local → GB10)
   is reasonable but can miss edge cases (e.g. one-off A100 rentals).
   A `hardware_overrides.yaml` keyed by run-prefix would cover the
   exceptions cleanly without false certainty in the per-row label.

5. **Daily summary blurb gating.** Para 1 still describes "allocation
   skew" deterministically based on supporting-file camp counts even
   on days with very few tests (e.g. 1-3). Could gate the allocation
   sentence on N≥5 tests.

### S3 — known limitations (probably fine)

- **Render-all path exists.** `python3 render_all.py` rebuilds all date pages
  plus `output/preview/index.html`.
- **Chart label overflow on dense days.** Day 11 has 59 tests; the
  trajectory chart may visually crowd at the right edge. Acceptable
  for now since on-chart numbered labels were dropped in commit
  `0d949f8` — Test Runs table is the source-of-truth for run identity.

## Useful commands

```bash
cd ~/research_collator

# Full pipeline rebuild (when stripper changes):
rm -f index.sqlite
python3 stripper.py     # ~30s scan, ~13.7K rows
python3 enrich.py       # +972 git, +643 claude, +515 codex sessions
python3 scripts/mine_conversation_architecture.py --start 2026-03-18 --end 2026-05-01 --index
python3 classify.py     # camp tagging

# Render one day or all days:
python3 render_day.py --date 2026-03-28
python3 render_all.py

# Playwright audit of the spread:
node _pw_audit_spread.mjs 2026-03-18 2026-03-19 2026-03-22 \
                          2026-03-28 2026-04-10 2026-04-20 2026-05-02

# Single-day playwright review (saves screenshot to /tmp):
node _pw_day_review.mjs http://rig-host:8765/research_collator/output/preview/2026-03-28.html /tmp/day12.png

# Local HTTP server (already running on background):
# python3 -m http.server 8765 --bind 0.0.0.0  (cwd: ~)
# URLs: http://rig-host:8765/research_collator/output/preview/<date>.html
```

## Live URL spread (current state)

- Day 1   `2026-03-18`  — http://rig-host:8765/research_collator/output/preview/2026-03-18.html
- Day 2   `2026-03-19`  — http://rig-host:8765/research_collator/output/preview/2026-03-19.html
- Canonical regression date `2026-03-28` — http://rig-host:8765/research_collator/output/preview/2026-03-28.html
- Day 25  `2026-04-10`  — http://rig-host:8765/research_collator/output/preview/2026-04-10.html
- Day 35  `2026-04-20`  — http://rig-host:8765/research_collator/output/preview/2026-04-20.html

## Repo

`https://github.com/newjordan/research-collator` (private). Latest commit
`4f4e5c1`. Branch: `master`.

## Working principles for next session

- **Don't ask permission to fix bugs you've identified.** The user has
  flagged this twice. Identify, patch, verify, push.
- **Stripper stays pure-Python.** Do not introduce any LLM-call-per-file
  flow. Templates + deterministic extraction.
- **One perfect unit before replication.** Verify the canonical regression
  date (`2026-03-28`) renders cleanly
  before scaling a new feature across all 47 days.
- **Don't dress up marginal work as progress.** If a fix didn't move the
  needle, say so plainly.
- **Verify hardware/metric values via the scraper, not by visual claim.**
  When the user says "the val_bpb on this run looks wrong", check the log
  content via SQL — don't accept a commit-message claim.
