# Claude Handoff - Category Cumulative Reports

Date: 2026-05-07
Repo: `/home/frosty40/research_collator`

## Assignment

Stop the month-report plan. Keep daily reports and weekly reports, then add
category cumulative reports:

- experimental report
- neural report
- kernel report

Each category report should show the course of that category across the full
campaign, compressed into two-week graph windows. The goal is not a final
global summary yet. The hierarchy is:

```text
daily reports -> weekly reports -> category cumulative reports -> final summary later
```

Do not build monthly pages.

## User Intent

The user still likes the graphs. The problem was that global best/median style
rollups were carrying too much history into every sheet and making progress
harder to read. Keep history/progress relatively local in daily and weekly
pages. Category reports may span the campaign, but their graphs must be split
into two-week chunks so each panel remains readable.

## Current Worktree State

There are uncommitted changes already present. Do not revert them.

Current files changed/untracked before this handoff:

- modified: `README.md`
- modified: `TEMPLATE.md`
- modified: `plot.py`
- modified: `render_all.py`
- modified: `render_day.py`
- untracked: `render_week.py`
- untracked: `scripts/verify_weekly_template.py`

Those changes implement the weekly layer:

- weekly standard id: `weekly-report-v1.0-daily-rollup`
- weekly outputs:
  - `output/preview/weeks/<WEEK>.html`
  - `output/preview/weeks/index.html`
  - `output/weeks/<WEEK>.qmd`
  - `output/assets/weeks/<WEEK>/week_chart_<METRIC>.png`
- weekly pages use the locked daily CSS and have exactly:
  - `SECTION 1.0 - WEEK TRAJECTORY`
  - `SECTION 2.0 - DAILY REPORTS`
- weekly pages already removed:
  - weekly median/best/worst spread table
  - prior-week baseline overlays
  - carried running-best overlays
  - separate `BEST DAY` header

Do not undo those weekly changes.

## Hard Rules

- No LLM calls inside scraper, classifier, renderer, or verifiers.
- Raw Claude/Codex conversations must never render in report HTML.
- Daily template remains locked to `daily-report-v2.0-wide-log-panel`.
- Weekly template remains locked to `weekly-report-v1.0-daily-rollup`.
- Category reports should reuse the locked daily visual language and CSS.
- No chart panel should become a giant campaign-wide plot. Split category
  trajectories into two-week windows.
- Do not add monthly pages.
- Do not move back to Section 3.0. Daily pages stay two-section.
- Do not silently classify kernel work as experimental on category report
  surfaces. Kernel gets its own report.

## Proposed Implementation

Add a new deterministic renderer:

- `render_category.py`

Suggested outputs:

- `output/preview/categories/index.html`
- `output/preview/categories/experimental.html`
- `output/preview/categories/neural.html`
- `output/preview/categories/kernel.html`
- `output/categories/experimental.qmd`
- `output/categories/neural.qmd`
- `output/categories/kernel.qmd`
- `output/assets/categories/<category>/window-<NN>_<START>_to_<END>_<METRIC>.png`

Suggested standard id:

- `category-report-v1.0-biweekly-course`

Wire it into `render_all.py` after weekly reports:

```text
[1/6] enumerate dates
[2/6] render days
[3/6] render weekly reports
[4/6] render category reports
[5/6] compute final-summary/journey input
[6/6] render index
```

If you also move the campaign-wide journey chart out of the front index, put
it behind an explicit final-summary page, not on every rollup. The user has
not asked for final summary implementation in this handoff, so keep that
surgical unless it is required to keep the index clean.

## Data Model Guidance

Do not rely only on each day's headline metric for category reports. A day can
have mixed work, and the daily headline can hide a category that was active.

Build category datapoints from day-local records/test rows:

1. For each campaign date, fetch and scope records the same way
   `render_day.render_one_day()` does:
   - `fetch_day(conn, date)`
   - `report_records_for_date(date, records)`
   - on final day, apply `final_submission_records_for_day()`
2. For kernel:
   - prefer `kernel_fb_ratio`
   - fallback to `kernel_fwd_ratio`
   - category camp is `kernel`
   - these are custom-kernel/FA3 timing metrics
3. For neural and experimental:
   - prefer `val_bpb`
   - fallback to `val_loss`
   - filter `extract_test_rows()` rows by `row["camp"] == category`
4. For every category/date/metric combination, choose the best valid row for
   that category on that date.
5. Preserve provenance in the table/dropdown:
   - date
   - week number
   - metric
   - value
   - row title
   - architecture family if available
   - source path/link
   - number of valid/invalid/crash rows for that category/date

Use existing helpers where possible:

- `render_day.fetch_day`
- `render_day.report_records_for_date`
- `render_day.final_submission_records_for_day`
- `render_day.extract_test_rows`
- `render_day.best_before`
- `render_day.pick_headline_metric` only for fallback, not as the sole source
- `render_day.metric_display_name`
- `render_day.format_metric_value`
- `render_day.is_valid_metric_value`
- `render_day.compute_day_index`
- `render_day.format_day_index`
- `render_week.week_windows`
- `render_week.format_camp_counts`
- `plot.week_chart` or a renamed generic wrapper

## Two-Week Graph Windows

Default interpretation: non-overlapping pairs of the existing research-week
windows:

- window 01: week 01 + week 02
- window 02: week 03 + week 04
- window 03: week 05 + week 06
- window 04: week 07 partial/final

If a category has mixed metrics inside a two-week window, render one chart per
metric in that window. Do not put BPB and kernel ratios on the same y-axis.

Each chart point should be one category-local daily datapoint, not one raw
training run. The row/table beneath the graph can expose the underlying run
metadata through dropdowns.

## Page Shape

Each category page should keep the same two-section feel:

```text
H1: <CATEGORY> RESEARCH REPORT
report header:
  CATEGORY
  DATES
  WINDOWS
  ACTIVE DAYS
  DATAPOINTS
  PRIMARY METRICS

SECTION 1.0 - BI-WEEKLY TRAJECTORY
  one subsection/table per two-week window
  one chart per metric inside the window

SECTION 2.0 - CATEGORY DAILY DATAPOINTS
  one row per category/date datapoint
  OPEN dropdown exposes provenance
```

Do not add global median/best summaries to these pages. If a "best" is shown,
it must be clearly local to the row/window, not a carried campaign-wide
running-best line.

## Index Changes

Update `output/preview/index.html` to link:

- daily reports
- weekly reports
- category reports
- final summary placeholder or future link only if implemented

The front index should behave as navigation, not as the final research
summary. Avoid adding big prose summaries there.

## Verification

Add a verifier:

- `scripts/verify_category_template.py`

Minimum checks:

- category index exists
- three category pages exist: experimental, neural, kernel
- each page uses locked daily visual blocks (`report-header`, `day-summary`
  or equivalent, `test-runs-table`)
- each page has exactly two main sections
- no `claude_session`, `codex_session`, `conversation_arch_event`, or raw
  transcript labels leak into category HTML
- no monthly output is generated
- no category page contains forbidden global-summary markers:
  - `MONTHLY`
  - `BEST EVER`
  - `RUNNING BEST`
  - `PRIOR WEEK`
  - `<th>median</th>`

Run after implementation:

```bash
python3 -m py_compile render_category.py render_week.py render_all.py plot.py scripts/verify_category_template.py scripts/verify_weekly_template.py scripts/verify_daily_template.py
python3 render_all.py
python3 scripts/verify_daily_template.py --all
python3 scripts/verify_weekly_template.py --all
python3 scripts/verify_category_template.py --all
python3 scripts/verify_scraper_contract.py
```

Also scan generated outputs:

```bash
rg -n "CONVERSATION-MINED|conversation_architecture|conversation_arch_event|claude_session|codex_session" output/preview output/days output/weeks output/categories
rg -n "MONTHLY|BEST EVER|RUNNING BEST|PRIOR WEEK|<th>median</th>" output/preview/categories output/categories
```

Both scans should return no matches.

## Links To Return

After rendering, return direct links:

- weekly index:
  `http://dgx-spark:8765/research_collator/output/preview/weeks/index.html`
- category index:
  `http://dgx-spark:8765/research_collator/output/preview/categories/index.html`
- experimental:
  `http://dgx-spark:8765/research_collator/output/preview/categories/experimental.html`
- neural:
  `http://dgx-spark:8765/research_collator/output/preview/categories/neural.html`
- kernel:
  `http://dgx-spark:8765/research_collator/output/preview/categories/kernel.html`

Keep the final response evidence-first: files changed, generated page counts,
verifier exits, and links.
