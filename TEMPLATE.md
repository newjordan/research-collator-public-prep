# DAILY RESEARCH REPORT — MASTER TEMPLATE

This document is the canonical specification for the daily research report.
Every per-day HTML page is rendered as an instance of this template; every
new field, section, or visual element must be added here first. The scraper
contract (what data the scraper must produce per day) is defined in §6.

This is a living spec — but the only person who writes to it is the renderer
author. If a question about layout, tokens, or data shape isn't answered
here, the answer doesn't exist yet.

---

## 1. PURPOSE

A self-contained HTML artifact (one file, one day) that demonstrates 24h of
parameter-golf research as evidence — credible to a peer evaluator, dense
enough that nothing real is hidden behind summaries, dry enough that the
data does the talking.

Audience: the user (archive), a research lab evaluator, the parameter-golf
community, future-you. Read time target: ≤3 minutes skim, ≤10 minutes deep.

---

## 2. AESTHETIC LOCK

The visual system is fixed. Renderers must not introduce additional colors,
fonts, or surface treatments without first updating this section.

The locked base CSS source is `templates/daily_report_locked.html`. The
renderer refuses to run if that file's `<style>` block does not match
`LOCKED_TEMPLATE_STYLE_SHA256` in `render_day.py`. The current standard id is
`daily-report-v2.3-clean-bottom`.

### 2.1 Palette (single source of truth)

| Token         | Value      | Purpose                                          |
|---------------|------------|--------------------------------------------------|
| `--bg`        | `#89380e`  | Cover-orange/grunge page field.                  |
| `--surface`   | `#89380e`  | Reserved; no separate grey-black fill.           |
| `--rule`      | `#050605`  | Dark-black hairline dividers.                    |
| `--rule-hi`   | `#050605`  | Dark-black stronger rules.                       |
| `--ink`       | `#050605`  | Primary body text.                               |
| `--ink-hi`    | `#050605`  | Emphasized text.                                 |
| `--ink-mute`  | `#1b0f08`  | Muted cover-black labels and footnotes.          |
| `--accent`    | `#050605`  | Dark-black accent.                               |
| `--warn`      | `#2b0000`  | INVALID dark red. Used only for invalidity.      |
| `--link`      | `#050605`  | Dark-black link text. Underline on hover only.   |
| `--data-exp`  | `#050605`  | Dark-black experimental.                         |
| `--data-neu`  | `#2b1607`  | Cover-brown + dark-black diagonal stripes.       |
| `--data-kernel` | `#050605` | Dark-black kernel classification.              |

Total: 13 tokens. No grey-black surfaces and no off-palette accents. The
orange and black are sampled from `assets/cover_sheet_final.jpeg`: orange
median `#89380e`, black median `#050605`.

### 2.2 Typography

`Berkeley Mono` first; falls back through `JetBrains Mono → IBM Plex Mono →
ui-monospace → SF Mono → Consolas → DejaVu Sans Mono → Liberation Mono →
Courier New → monospace`. No proportional fonts anywhere.

Body 13px, line-height 1.55. Tabular numerics (`font-variant-numeric:
tabular-nums`) on every value column.

### 2.3 Surface treatment

Cover-orange field with a subtle dark-black grunge texture. Primary reading
zones are intentionally inverted: report header, section anchors, daily
summary, chart frame, table headers, and training-log expansion panels use
`--rule-hi` as a black field with `--bg` text/detailing.
Tables and lists keep orange body rows for scan density. Key frames use small
black/orange register marks and corner ticks; these are CSS-only
micro-graphics, not content fields. There is no footer and no decorative
bottom edge treatment.
No grey-black fills, no shadows, and no off-palette gradients. The only
allowed gradients are the low-opacity black grunge texture on the page field
and the 45° diagonal stripes on the neural data segment.

### 2.4 Section anchors (vertical rhythm)

H1: 22px, top of page, no border, mark + title left, date right.
The H1 frostmark is rendered through CSS as dark black; do not edit the
source PNG to recolor it.
H2: 12px ALL-CAPS with `border-bottom: 1px solid --rule-hi`. Margins
36px above / 14px below.

---

## 3. CANONICAL LAYOUT

The order is fixed. New sections may be added; existing sections may not be
re-ordered without a spec revision.

```text
1. H1                       DAILY RESEARCH REPORT  ⨂  YYYY-MM-DD
                            ↑ frosted_flake mark (32×32)         ↑ right-pinned

2. REPORT HEADER            Inverted black evidence block, 6 rows:
                              DATE
                              DAY                  (3-digit zero-padded index)
                              PRIMARY METRIC
                              TESTS RUN            BPB: "N unique  (V valid / I below floor)"
                                                   kernel: "N kernel benchmarks"
                              ARCHITECTURE FAMILY  "FAM (×N)  ·  FAM (×N)  ·  ..."
                              CLASSIFICATION       ← inline allocation bar (240×30)

3. SECTION 1.0  TRAJECTORY
3.1   DAILY SUMMARY         Inverted 2-col callout (160px label | 1fr body),
                            black field, orange text, two short paragraphs:
                              ¶1 — runs · valid/invalid · allocation tone · top archs
                              ¶2 — best valid + PB comparison + crash flag
3.2   CHART                 PNG, framed in an inverted black figure block.
3.3   METRIC SPREAD         Compact tabular-num table, n / min / median / max
                            per architecture family + ALL VALID row.

4. SECTION 2.0  TEST RUNS   Classification-isolated 8-column tables:
                              # | TIME | HW | ABLATION | <PRIMARY METRIC> | STATUS | Δ % | OPEN
                            KERNEL, EXPERIMENTAL, and NEURAL render as
                            separate tables when present. The header
                            classification bar lists only classes active on
                            that day; zero-count classes are omitted.
                            ABLATION defaults to deterministic raw title.
                            Optional local Nemo3 labels may replace it only
                            after promotion into approved ablation-label JSONL
                            keyed by date, row number, and raw-title hash.
                            OPEN renders a compact `<details>` toggle on every
                            test row. Opening it reveals a full-table-width
                            detail row beneath that run. Rows with training
                            logs include escaped full log text plus the
                            original file link; rows without logs expose the
                            recovered source/run metadata in the same dropdown
                            pattern.
                            INVALID rows: BPB-only muted text, red metric cell,
                            red STATUS.
                            Conversation-derived events never render in the
                            canonical daily page. Conversation mining may exist
                            as an offline audit lane only.

```

DAILY GRIND — explicitly **not** in the canonical layout. Codex/Claude
session entries are indexed only for the separate local-summary lane. They
MUST NOT render as report body research support.

---

## 4. CHART (TRAJECTORY) — DETAILED CONTRACT

The chart is the page's headline image. Renderer: `plot.py::day_charts`.
Long trajectories render as multiple figure blocks.

### 4.1 Axes

- X-axis: time of day, UTC. No rendered panel may span more than 12 hours.
  If a day's measured points cover more than 12 hours, the renderer splits
  the trajectory into multiple chronological panels. Sparse recovered records
  are split by occupied run-time clusters instead of inserting empty half-day
  panels. Locator picks 1h / 2h / 3h ticks based on each panel span.
- Y-axis: primary metric. Kernel-heavy whale/crawler days use
  `CUSTOM/FA3 FB RATIO` when comparable custom-vs-FA3 timing rows exist;
  otherwise `val_bpb` is preferred with `val_loss` fallback.

### 4.2 Y-axis range

For BPB charts:

```text
y_lo       = max(0.4, min(invalid_values) - 0.08)
             OR INVALID_VAL_BPB_FLOOR - 0.15 if no invalids
data_max   = max value in [INVALID_VAL_BPB_FLOOR, CRASH_THRESHOLD]
data_range = max(0.4, data_max - y_lo)
y_hi       = data_max + 0.12 * data_range
```

For non-BPB charts, including custom-kernel/FA3 ratios, the axis is a tight
finite-data range with no invalid zone.

### 4.3 Validity zones

- BPB only: `val_bpb < INVALID_VAL_BPB_FLOOR` (= **1.06**): quiet invalid zone,
  slightly different background, subtle solid floor line. Project-wide
  convention (don't get excited about scores in the quiet zone — known eval
  errors).
- BPB only: `INVALID_VAL_BPB_FLOOR ≤ val_bpb ≤ CRASH_THRESHOLD` (= 3.0):
  valid range.
- BPB only: `val_bpb > CRASH_THRESHOLD`: crashed-early runs. Off-scale, summarized
  by a single top-right indicator (`▲ N CRASH RUNS OFF-SCALE  (max=…)`).
  These points are **not plotted** but their count + max are surfaced.
- Non-BPB metrics: every finite value is valid; no invalid zone, no crash
  indicator.

### 4.4 Marks

| Element           | Style                                                       |
|-------------------|-------------------------------------------------------------|
| Camp scatter      | Compact circular dots (`s=42`, invalid `s=38`) with page-bg edge and a tiny center pin at the exact `(time, value)` coordinate. |
| Journey line      | Dark-black, alpha 0.55, lw 0.7, connects in-scale valid segments only. |
| Best-valid step   | Dark-black accent, lw 1.2, where='post'. Excludes invalids/crashes.|
| Validity floor    | Subtle solid rule, lw 0.65, alpha 0.55.                     |
| Invalid zone      | Quiet background shift only; below-floor points are 50% desaturated. |
| PB-baseline ref   | White dashed, lw 0.9, alpha 0.50.                           |
| Crash indicator   | Top-right above grid, accent border + accent text on bg.    |
| Legend            | Centered below the time axis, outside the data grid.         |
| Prior-day marker  | Top-right title: `PRIOR DAY <METRIC> · <value>`; kernel ratios render with `×`. No inline label on dashed line. |

### 4.5 Run identity labels

The chart does **not** draw every run label. Run identity is preserved in
Section 2 where row numbers and embedded logs are readable. The chart labels
only the best valid point as `BEST #N`, where `N` is the Test Runs table row.

---

## 5. INVARIANTS

Renderers MUST maintain these. Tests live in `render_day.py` itself; if any
of these break, the page is wrong.

1. **Palette locked.** No page element introduces a color outside §2.1.
2. **Inversion is intentional and limited.** Only report header, section
   anchors, daily summary, chart frame, table headers, and log expansion panels
   use black fields. Body rows/lists remain orange.
3. **Micro-graphics are CSS-only.** Register marks and corner ticks use `--bg`
   and `--rule-hi`; no bitmap embeds and no extra data fields.
4. **Numbered badge ↔ table row #** is always 1-indexed by run time and
   matches across the chart and the Test Runs table.
5. **INVALID rows are BPB-only** and always muted (text), with red on the
   metric cell and red on the STATUS strong tag.
6. **The validity floor is never a header field.** It's a project-wide
   convention shown only on the chart.
7. **Self-contained.** The HTML embeds chart + frosted-flake mark as base64
   and embeds training-log text in Section 2 disclosures; no external
   requests are required for review. Opens offline in any browser.
8. **Template hash locked.** `render_day.py` must refuse to render if
   `templates/daily_report_locked.html` CSS drifts without an intentional hash
   update.
9. **No conversations in research pages.** Claude/Codex sessions and
   conversation-derived artifacts may exist in offline indexes, but they must
   never render in the daily HTML body.

---

## 6. SCRAPER CONTRACT

The scraper (stripper.py + enrich.py + classify.py) must produce, for any
date the renderer is asked to render, an SQLite index where the following
queries return non-empty results:

### 6.1 Required per-record fields

For every artifact attributable to the day:

| Column                   | Type     | Notes                                                  |
|--------------------------|----------|--------------------------------------------------------|
| `abs_path`               | TEXT PK  | Stable identity (file path, or `git://repo/sha`).      |
| `mtime_iso`              | TEXT     | ISO8601 UTC. Authoritative timestamp.                  |
| `file_kind`              | TEXT     | `md`/`json`/`py`/`csv`/`ckpt`/`training_log`/`git_commit`/`claude_session`/`codex_session`/`conversation_arch_event` |
| `source_label`           | TEXT     | Short label used in supporting-files row.              |
| `title`                  | TEXT     | Display title — never empty (filename fallback OK).    |
| `summary`                | TEXT     | One-line context. Never empty; renderer never parses metrics from it. |
| `metrics_json`           | TEXT     | JSON dict of extracted metrics (see §6.3).             |
| `camp`                   | TEXT     | `experimental` \| `neural` \| `daily_grind`            |

### 6.2 Required per-day computables (derived in render)

The renderer derives these from the records and a target date:

- **`day_index`** — 1-based index of this date in the sorted list of user
  research dates with artifacts, starting at `2026-03-18` and ending at
  `2026-05-01`. Prelude/bootstrap artifacts, public upstream competition
  records, and post-final-submission artifacts can be rendered by explicit
  date, but are not counted in the research-day ordinal. This fixes
  `2026-03-18 = DAY 001`; Mockingbird on `2026-05-01` is the final
  campaign submission.
- **`headline_metric`** — first metric with enough evidence. Kernel ratio
  metrics (`kernel_fb_ratio`, then `kernel_fwd_ratio`) win when ≥2 comparable
  custom-kernel-vs-FA3 timing rows exist; otherwise fall back through
  `val_bpb`, `val_loss`, `val_bits_per_byte`, `bpb`.
- **`chart_baseline`** — best (lowest) `headline_metric` value across all
  records strictly before this date.
- **`test_rows`** — one row per unique title (collapsing seed replicas),
  sorted by run-time ascending. Each row: `n, time, hardware, title,
  value, n_runs, link_label, link_href, run_script, training_logs,
  time_iso, camp, delta_pct`. Kernel headline metrics normalize rendered row
  `camp` to `kernel` so the classification bar and Section 2 do not hide
  custom-kernel work under experimental.
- **Conversation-derived artifacts** — may be indexed for offline audit, but
  are not renderer inputs and must never appear in daily-page body content.
- **`arch_families`** — list of `(family_name, count)` tuples, ordered by
  count descending; first match wins per `ARCH_FAMILIES` regex table.
- **`valid_count` / `invalid_count`** — BPB uses the
  `INVALID_VAL_BPB_FLOOR`; non-BPB metrics count every finite value as valid.

### 6.3 Required metric keys (when present in source)

The metric extractors in `stripper.py` and `enrich.py` MUST map to these
canonical keys:

| Key                      | Source-of-truth                                          |
|--------------------------|----------------------------------------------------------|
| `val_bpb`                | bits-per-byte. Sanity floor: ≥ 0.1.                     |
| `val_loss`               | natural-log loss.                                        |
| `val_bpb_int6_*`         | per-quantization variant from `final_*` lines.           |
| `source_metrics.whale_*_mean_ms` + `source_metrics.fa3_*_mean_ms` | source timing pairs used to derive custom/FA3 ratio metrics. |
| `results[*].backends.<custom>.{fb,fwd}_mean_ms` + `results[*].backends.fa3.{fb,fwd}_mean_ms` | flattened benchmark timing pairs used to derive custom/FA3 ratio metrics. Custom backend names include `whale_fast`, `whale`, `custom`, `kernel`, and `blessed_whale`. |
| `n_ranks`                | distinct rank IDs in training-log output (HW signal).    |
| `train_time_seconds`     | last `train_time:Nms` in log content.                    |
| `step_final`             | last `step:N/M` in log content.                          |
| `filename_run_start`     | `YYYYMMDDTHHMMSS` parsed from training-log filename.     |
| `n_user_turns`           | codex/claude session: `event_msg`/`user_message` count.  |
| `n_agent_turns`          | codex/claude session: `agent_message` count.             |
| `n_exec_commands`        | codex/claude session: `exec_command_end` count.          |
| `n_patches`              | codex/claude session: `patch_apply_end` count.           |
| `session_duration_seconds` | last_event_ts − first_event_ts                         |

### 6.4 Verification gate

The canonical scrape/render pipeline MUST pass:

```bash
python3 stripper.py
python3 enrich.py
python3 classify.py
python3 scripts/verify_scraper_contract.py
python3 render_all.py
python3 scripts/verify_daily_template.py --all
python3 scripts/verify_weekly_template.py --all
python3 scripts/verify_category_template.py --all
python3 scripts/verify_campaign_template.py
python3 scripts/verify_cover_template.py
python3 scripts/verify_toc_template.py
```

`scripts/verify_scraper_contract.py` is the executable gate for §6. It
checks:

- required columns and non-empty display fields (`title`, `summary`,
  `camp`, `classification_rule`, timestamps, paths);
- JSON-parseable `metrics_json` with numeric headline metrics;
- training-log `val_bpb_source` provenance (`log_final_eval` or
  `log_step_best`);
- `filename_run_start` and `n_gpus` sanity;
- readable measured training-log files plus `content_sha256`;
- day attribution via `best_date()` / `fetch_day()`;
- Section 2 row numbering and camp isolation (`daily_grind` cannot become
  a test row);
- retrieval indexes: `idx_label`, `idx_kind`, `idx_mtime`, `idx_title`,
  `idx_kind_mtime`, `idx_source_kind`, `idx_content_sha`, `idx_camp`,
  `idx_rule`, `idx_camp_kind`, `idx_camp_mtime`.

Non-empty training logs without canonical metric patterns are warnings, not
fatal errors: they are preserved as indexed evidence but do not create Test
Runs rows.

### 6.5 Architecture-family detection

The `ARCH_FAMILIES` list in `render_day.py` is the source of truth for
canonical family names and their detection regex. New family codenames
go there. Order matters: more-specific patterns first.

### 6.6 Camp classifier

The `classify.py` rule order:
1. `source == "codex_rollouts"` → `daily_grind`
2. `path` strong markers (`/legs/`, `/crawler/`, `/concepts/`,
   `/ablations/`, `/submissions/`, `/baselines/`, `/experiments/`)
3. STRONG_EXP_KW match → `experimental`
4. Source `SOTA_FINAL` or `sota_rascal` → `neural` (competitive lane)
5. WEAK_EXP_KW → `experimental`
6. NEURAL_KW → `neural`
7. Source default

---

## 7. RENDERER CONTRACT

The daily renderer (`render_day.py`) is the only consumer of the scraper
output that's allowed to write the canonical daily HTML. Weekly pages
(`render_week.py`) are rollups of rendered daily summaries: their datapoints
are daily reports, not raw training logs. Category pages
(`render_category.py`) are cumulative classification drilldowns built from
category-local daily datapoints. The campaign page (`render_campaign.py`) is
the cumulative overlay for the whole campaign. The cover page
(`render_cover.py`) is the static site's first page and is the only renderer
allowed to display the cover sheet. The table-of-contents page
(`render_toc.py`) follows the cover as the navigation entry point.
`render_all.py` calls these renderers and treats their return values as
opaque.

`render_one_day(date: str, metric_override: str | None) -> dict` must
produce:

- `output/days/<DATE>.qmd` — Quarto-compatible markdown source.
- `output/preview/<DATE>.html` — Self-contained HTML with embedded chart
  PNG + frosted-flake mark (base64). The artifact this spec describes.
- `output/assets/<DATE>/day_chart_<METRIC>.png` — PNG referenced by the
  qmd.

The `.html` file is the canonical rendered template instance. The `.qmd`
exists for future Quarto book assembly; it must NOT be the source of
truth for layout (the HTML is).

`render_week.py` must produce:

- `output/weeks/week-<NN>_<START>_to_<END>.qmd` — Quarto-compatible weekly
  source.
- `output/preview/weeks/week-<NN>_<START>_to_<END>.html` — Self-contained
  weekly HTML using the locked daily CSS.
- `output/assets/weeks/week-<NN>_<START>_to_<END>/week_chart_<METRIC>.png`
  — one weekly trajectory chart per headline metric in that week.

Weekly pages keep the same two-section shape:

- `SECTION 1.0 — WEEK TRAJECTORY`
- `SECTION 2.0 — DAILY REPORTS`

Every Section 2 row is one daily report with an `OPEN` dropdown. Mixed-metric
weeks never plot unlike metrics on a shared y-axis; they render separate
weekly trajectory panels. Weekly pages must keep each plotted value local to
its source day/week: no weekly median/best/worst spread table, no carried
prior-best baseline line, and no "best day" headline.

`render_category.py` must produce:

- `output/categories/<CATEGORY>.qmd` — Quarto-compatible category source.
- `output/preview/categories/<CATEGORY>.html` — Self-contained category HTML
  using the locked daily CSS.
- `output/assets/categories/<CATEGORY>/window-<NN>_<START>_to_<END>_<METRIC>.png`
  — one chart per metric inside each active two-week window.

Category pages keep the same two-section shape:

- `SECTION 1.0 — BI-WEEKLY TRAJECTORY`
- `SECTION 2.0 — CATEGORY DAILY DATAPOINTS`

Every category datapoint is the best valid row for that classification on
that date for the category's preferred metric. Experimental and neural prefer
BPB then loss; kernel prefers custom/FA3 FB ratio then FWD ratio. Mixed metrics
never share a y-axis.

`render_campaign.py` must produce:

- `output/campaign/cumulative.qmd` — Quarto-compatible campaign source.
- `output/preview/cumulative.html` — Self-contained campaign cumulative HTML
  using the locked daily CSS.
- `output/assets/campaign/cumulative_overlay_<METRIC>.png` — one campaign
  overlay chart per metric.

The campaign page keeps the same two-section shape:

- `SECTION 1.0 — CLASSIFICATION OVERLAY`
- `SECTION 2.0 — CAMPAIGN INDEX`

The campaign overlay may span the full campaign. It may overlay
classifications only when the metric/y-axis is shared. BPB/loss panels and
custom-kernel/FA3 ratio panels remain separate.

`render_cover.py` must produce:

- `output/cover/cover.qmd` — Quarto-compatible cover source.
- `output/preview/cover.html` — Self-contained publication cover HTML.
- `output/preview/index.html` — Exact first-page alias for static hosting.

The cover sheet is a page, not a decorative element. It must appear only on
`cover.html` / `index.html`. TOC, campaign, category, weekly, and daily pages
must not embed or reference `assets/cover_sheet_final.*`.

`render_toc.py` must produce:

- `output/toc/toc.qmd` — Quarto-compatible TOC source.
- `output/preview/toc.html` — Self-contained table-of-contents HTML using the
  locked daily CSS.

The TOC page keeps the same two-section shape:

- `SECTION 1.0 — PUBLICATION MAP`
- `SECTION 2.0 — REPORT INDEX`

The TOC is the second page after the publication cover. It links back to the
cover, then the campaign cumulative report, category reports, weekly reports,
every daily report, and the Mockingbird final day. If
`assets/toc_background_generated.png` is present, the TOC may use it as a
generated navigation background. It must never embed or reference the cover
sheet.

---

## 8. WHAT IS DELIBERATELY NOT IN THE TEMPLATE

To avoid feature creep, these are **rejected proposals**:

- A "Daily Grind" section that summarizes session activity. Sessions
  appear in Supporting Files; their stripe color encodes camp.
- Additional accent colors. The five-token palette is the lock.
- Card-fill backgrounds, drop shadows, off-palette gradients. The only
  gradients allowed are the subtle cover-field grunge texture and the neural
  diagonal-stripe pattern.
- Cyan, amber, lime, pastels. No.
- A floating side-panel / sticky nav. The page is a printed-document
  metaphor. Scroll is the only navigation.
- Automatic layout shifts (animation, transition). Static rendering only.
- Per-day color theming. Every day uses the exact same palette.

---

## 9. EXTENSION PROCEDURE

When a renderer change is proposed:

1. Update §3 (canonical layout) or §4 (chart contract) **first** in this
   document with the new section/element specification.
2. If new data is required, update §6 (scraper contract).
3. THEN implement in code. Code must match this doc; this doc is
   authoritative.
4. Re-render the canonical regression date (`2026-03-28`) —
   if anything in §5 (invariants) breaks, the change is rejected.

---

_This template is locked at the visual+structural level. The source data
behind any rendered instance is the live SQLite index produced by the
scraper for that date._
