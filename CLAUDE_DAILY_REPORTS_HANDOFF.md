# Claude Handoff — Daily Report Campaign Build

Date: 2026-05-06
Repo: `/home/frosty40/research_collator`
Remote: `https://github.com/newjordan/research-collator.git`
Branch: `master`

## Assignment

Run the bookkeeping-heavy scrape/render job and build one locked-template daily
report for each research campaign day.

The user explicitly does not want Codex burning compute on this pass. Claude
should own the full pipeline, diagnose any data gaps, and return the exact page
links plus any actionable failures.

## Hard Rules

- Do not use any LLM inside the scraper, classifier, or renderer.
- Keep `stripper.py`, `enrich.py`, `classify.py`, `render_day.py`,
  `render_all.py`, and template verification deterministic.
- Daily pages must strictly follow `daily-report-v2.2-bottom-dither`.
- `TEMPLATE.md` is authoritative. If code and `TEMPLATE.md` disagree, fix code
  or update both deliberately in the same patch.
- Do not add a Section 3.0 or supporting-files body section. The canonical daily
  page has only:
  - `SECTION 1.0 — TRAJECTORY`
  - `SECTION 2.0 — TEST RUNS`
- Raw Claude/Codex transcripts must not render directly in daily pages.
  `conversation_arch_event` rows are allowed only when produced by
  `scripts/mine_conversation_architecture.py --index`.
- Do not treat public upstream `records/track_*` baselines as the user's test
  runs unless `submission.json` identifies a user-owned author/GitHub id.
- Research chronology is bounded:
  - first campaign day: `2026-03-18`
  - final campaign day: `2026-05-01`
  - `2026-03-18 = DAY 001`
  - final submission: Mockingbird on the afternoon of `2026-05-01`
- Do not create campaign pages after `2026-05-01`.
- No chart panel may span more than 12 hours. Split crowded days into multiple
  chronological panels when needed.

## Current Local State

Codex stopped before the expensive bookkeeping pass.

Observed on 2026-05-06:

- No `stripper.py`, `enrich.py`, `classify.py`, conversation-miner, or
  `render_all.py` process is running.
- Git worktree was clean before this handoff document was added.
- `index.sqlite` exists but should be treated as partial/intermediate state.
- Current `index.sqlite` has `22,895` artifacts and includes enriched
  `git_commit`, `claude_session`, and `codex_session` rows.
- `classify.py` has not been run on the current DB: the `artifacts` table has
  no `camp` column.
- `scripts/mine_conversation_architecture.py --index` has not been run on the
  current DB: `conversation_arch_event` count is `0`.
- `output/` contains prior rendered artifacts and should be considered stale
  until `render_all.py` and `scripts/verify_daily_template.py --all` pass.

Because the DB is partial, start from a clean index instead of trying to
continue from the current one.

## Canonical Source Roots

Primary copied research corpus:

- `/home/frosty40/llm_research/parameter-golf-lab`
- `/home/frosty40/llm_research/parameter-golf-lab/junkyard`
- `/home/frosty40/llm_research/parameter-golf-cross-repo`
- `/home/frosty40/llm_research/sota_nueral`
- `/home/frosty40/llm_research/sota_nueral_archive`
- `/home/frosty40/llm_research/sota_crawler`
- `/home/frosty40/llm_research/SOTA_FINAL`
- `/home/frosty40/llm_research/sota_rascal`
- `/home/frosty40/llm_research/pg_whale`
- `/home/frosty40/llm_research/rascal-private`
- `/home/frosty40/llm_research/sota_rascal_pod_saves`

Other prelude/audit roots are listed in `config.yaml`. Keep them indexed for
auditability, but do not let pre-March-18 bootstrap work advance campaign day
numbering.

## Required Pipeline

Run from repo root:

```bash
cd /home/frosty40/research_collator
python3 -m py_compile stripper.py enrich.py classify.py render_day.py render_all.py scripts/mine_conversation_architecture.py scripts/verify_scraper_contract.py scripts/verify_daily_template.py
rm -f index.sqlite index.sqlite-wal index.sqlite-shm
python3 stripper.py
python3 enrich.py
python3 scripts/mine_conversation_architecture.py --start 2026-03-18 --end 2026-05-01 --index
python3 classify.py
python3 scripts/verify_scraper_contract.py
python3 render_all.py
python3 scripts/verify_daily_template.py --all
```

Target render scope:

- `45` calendar campaign days from `2026-03-18` through `2026-05-01`,
  inclusive.
- Prior code has sometimes emitted only `44` artifact-backed pages. Do not
  accept that silently. If the pipeline emits fewer than `45`, identify the
  missing date(s), mine the configured local roots/conversations, and either
  fix the scraper attribution or return the exact evidence that proves the date
  is genuinely empty.
- `output/preview/<DATE>.html`
- `output/days/<DATE>.qmd`
- `output/assets/<DATE>/...`
- stale post-campaign date outputs removed

Check for stale campaign leaks:

```bash
find output/preview output/days output/assets -maxdepth 1 \( -name '2026-05-0[2-9]*' -o -name '2029-08-09*' \) -print
```

Expected output: nothing.

## Verification Checklist

Report these exact checks back:

- `python3 scripts/verify_scraper_contract.py` passes.
- `python3 scripts/verify_daily_template.py --all` passes.
- Number of generated daily pages.
- First generated page is `2026-03-18.html`.
- Last generated page is `2026-05-01.html`.
- Any missing calendar date between `2026-03-18` and `2026-05-01` has been
  investigated and either fixed or reported with exact evidence.
- No stale post-campaign date pages remain.
- HTTP links open:
  - `http://dgx-spark:8765/research_collator/output/preview/2026-03-18.html`
  - `http://dgx-spark:8765/research_collator/output/preview/2026-03-19.html`
  - `http://dgx-spark:8765/research_collator/output/preview/2026-05-01.html`

## Data-Gap Handling

If any campaign day has no tests/logs, do not summarize around it. Treat it as
a scraper or attribution failure until proven otherwise.

Use this order:

1. Check day-local training logs in `/home/frosty40/llm_research`.
2. Check `/home/frosty40/llm_research/parameter-golf-lab/junkyard`.
3. Check git commits from the configured `git_repos`.
4. Check deterministic Claude/Codex architecture events through
   `scripts/mine_conversation_architecture.py`.
5. Only after those are exhausted, mark the day as session-only or no-run and
   explain the evidence.

Do not pull ComfyUI or unrelated studio files into the campaign body.

## User-Facing Deliverable

Do not give the user a prose summary page in place of daily reports. The user
asked for individual daily pages, strictly following the locked template.

Return:

- the generated page count
- the first/last campaign dates
- direct links for Day 1, Day 2, and final day
- any failed dates with exact reason and source path/query checked
- the commit hash if you make scraper/template fixes

Keep the response terse and evidence-first.
