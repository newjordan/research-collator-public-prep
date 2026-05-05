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

### 2.1 Palette (single source of truth)

| Token         | Value      | Purpose                                          |
|---------------|------------|--------------------------------------------------|
| `--bg`        | `#111315`  | Page background. The ONLY black.                 |
| `--surface`   | `#17191c`  | (reserved; currently unused — no card fills)     |
| `--rule`      | `#2a2d31`  | Hairline dividers (table rows, section seps).    |
| `--rule-hi`   | `#3a3e44`  | Stronger borders (panels, table outline, axes).  |
| `--ink`       | `#d6d8db`  | Primary body text.                               |
| `--ink-hi`    | `#f4f5f7`  | Emphasized values, headings.                     |
| `--ink-mute`  | `#8a8d92`  | Labels, dot-leader keys, footnotes.              |
| `--accent`    | `#e3b341`  | Yellow stripe accent — used SPARINGLY.           |
| `--warn`      | `#e25a4a`  | INVALID-row red. Used only for invalidity.       |
| `--link`      | `#7ab4ff`  | Quiet blue. Underline on hover only.             |
| `--data-exp`  | `#3a6e3a`  | Dark green. Experimental camp (DATA color).      |
| `--data-neu`  | `#6fbf6f`  | Lighter green + 45° diagonal stripes. Neural.    |

Total: 12 tokens. No greys outside this set, no off-palette accents, no
phosphor green outside the legacy CRT mode (which is deprecated).

### 2.2 Typography

`Berkeley Mono` first; falls back through `JetBrains Mono → IBM Plex Mono →
ui-monospace → SF Mono → Consolas → DejaVu Sans Mono → Liberation Mono →
Courier New → monospace`. No proportional fonts anywhere.

Body 13px, line-height 1.55. Tabular numerics (`font-variant-numeric:
tabular-nums`) on every value column.

### 2.3 Surface treatment

Single-rule, no fills. Every panel (header block, table, supporting list,
day summary, figure frame) is enclosed by exactly one `1px solid var(--rule-hi)`
border. No box-shadows, no gradients (except the 45° diagonal stripes on the
neural data segment), no card-style background tints.

### 2.4 Section anchors (vertical rhythm)

H1: 22px, top of page, no border, mark + title left, date right.
H2: 12px ALL-CAPS with `border-bottom: 1px solid --rule-hi`. Margins
36px above / 14px below.

---

## 3. CANONICAL LAYOUT

The order is fixed. New sections may be added; existing sections may not be
re-ordered without a spec revision.

```text
1. H1                       DAILY RESEARCH REPORT  ⨂  YYYY-MM-DD
                            ↑ frosted_flake mark (32×32)         ↑ right-pinned

2. REPORT HEADER            Flat bordered block, 6 dot-leader rows:
                              DATE
                              DAY                  (3-digit zero-padded index)
                              PRIMARY METRIC
                              TESTS RUN            "N unique  (V valid / I below floor)"
                              ARCHITECTURE FAMILY  "FAM (×N)  ·  FAM (×N)  ·  ..."
                              CLASSIFICATION       ← inline allocation bar (240×30)

3. SECTION 1.0  TRAJECTORY
3.1   DAILY SUMMARY         2-col callout (160px label | 1fr body),
                            dark-green left rule, two short paragraphs:
                              ¶1 — runs · valid/invalid · allocation tone · top archs
                              ¶2 — best valid + PB comparison + crash flag
3.2   CHART                 PNG, framed in a 1px-bordered figure block.
3.3   VAL_BPB SPREAD        Compact tabular-num table, n / min / median / max
                            per architecture family + ALL VALID row.

4. SECTION 2.0  TEST RUNS   8-column table:
                              # | TIME | HW | ABLATION | VAL_BPB | STATUS | Δ % | OPEN
                            INVALID rows: muted text, red val_bpb cell, red STATUS.

5. SECTION 3.0  SUPPORTING FILES
                            Wrapped in `.supporting-section` with vertical
                            guideline. Each `<li>` carries a left camp-stripe
                            (solid dark green for experimental, hatched
                            lighter green for neural, neutral for other).
```

DAILY GRIND — explicitly **not** in the canonical layout. Codex/Claude
session entries appear in SUPPORTING FILES (with their camp stripes), not
as their own section.

---

## 4. CHART (TRAJECTORY) — DETAILED CONTRACT

The chart is the page's headline image. Renderer: `plot.py::day_chart`.

### 4.1 Axes

- X-axis: time of day, UTC. Locator picks 1h / 2h / 3h ticks based on span.
- Y-axis: primary metric (`val_bpb` preferred, `val_loss` fallback).

### 4.2 Y-axis range

```
y_lo  = max(0.4, min(invalid_values) - 0.08)
        OR INVALID_VAL_BPB_FLOOR - 0.15 if no invalids
data_max = max value in [INVALID_VAL_BPB_FLOOR, CRASH_THRESHOLD]
data_range = max(0.4, data_max - y_lo)
label_gutter = 0.22 * data_range
y_hi  = data_max + 0.05 + label_gutter
```

The top 22% of the y-axis is reserved as a **label gutter** — no data
points may render there.

### 4.3 Validity zones

- `val_bpb < INVALID_VAL_BPB_FLOOR` (= **1.06**): red zone, hatched 45°,
  dotted floor line. Project-wide convention (don't get excited about
  scores in the red — known eval errors).
- `INVALID_VAL_BPB_FLOOR ≤ val_bpb ≤ CRASH_THRESHOLD` (= 3.0): valid range.
- `val_bpb > CRASH_THRESHOLD`: crashed-early runs. Off-scale, summarized
  by a single bottom-right indicator (`▲ N CRASH RUNS OFF-SCALE  (max=…)`).
  These points are **not plotted** but their count + max are surfaced.

### 4.4 Marks

| Element           | Style                                                       |
|-------------------|-------------------------------------------------------------|
| Camp scatter      | `s=140`, `linewidths=0.9`, edge = page bg.                  |
| Journey line      | Light grey, alpha 0.55, lw 0.7, connects pts in time order. |
| Best-valid step   | White (`--ink-hi`), lw 1.6, where='post'. Excludes invalids.|
| Validity floor    | Solid red lw 0.7, alpha 0.65.                               |
| Red zone          | `axhspan(0, FLOOR)`, alpha 0.10, hatch `///`, edge red.     |
| PB-baseline ref   | White dashed, lw 0.9, alpha 0.50.                           |
| Crash indicator   | Bottom-right, yellow border + yellow text on bg.            |

### 4.5 Numbered badges (the contract)

Each test run gets a numbered badge in the **gutter**, packed left→right
with a min-gap rule. Badges that would otherwise overlap a neighbor are
pushed right; if pressure persists, every other badge alternates to a
second sub-row. A thin grey leader line connects each badge to its
anchor dot.

Constraints:
- Badge font: 9pt bold, white text on bg with grey border, `pad=0.30`.
- Min horizontal gap: `xspan / 30` (≈ 30 badges fit in a single row).
- Two sub-rows: `y_top = ymax - 0.05·yspan`, `y_alt = ymax - 0.12·yspan`.
- Leader line: `--rule-hi`, lw 0.5, alpha 0.75.
- Badge number = its row in the Test Runs table (1-indexed by run-time).

---

## 5. INVARIANTS

Renderers MUST maintain these. Tests live in `render_day.py` itself; if any
of these break, the page is wrong.

1. **Five colors only.** No element introduces a color outside §2.1.
2. **One black.** All surfaces use `--bg`. No alternate backgrounds.
3. **Single border per panel.** No card fills, no shadows, no double-rules.
4. **Numbered badge ↔ table row #** is always 1-indexed by run time and
   matches across the chart and the Test Runs table.
5. **INVALID rows are always muted** (text), with red on the val_bpb cell
   and red on the STATUS strong tag.
6. **The validity floor is never a header field.** It's a project-wide
   convention shown only on the chart.
7. **Self-contained.** The HTML embeds chart + frosted-flake mark as base64;
   no external requests. Opens offline in any browser.

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
| `file_kind`              | TEXT     | `md`/`json`/`py`/`csv`/`pt`/`training_log`/`git_commit`/`claude_session`/`codex_session` |
| `source_label`           | TEXT     | Short label used in supporting-files row.              |
| `title`                  | TEXT     | Display title — never empty (filename fallback OK).    |
| `summary`                | TEXT     | One-line context. Never includes the val_bpb number.   |
| `metrics_json`           | TEXT     | JSON dict of extracted metrics (see §6.3).             |
| `camp`                   | TEXT     | `experimental` \| `neural` \| `daily_grind`            |

### 6.2 Required per-day computables (derived in render)

The renderer derives these from the records and a target date:

- **`day_index`** — 1-based index of this date in the sorted list of dates
  that have any artifact (used for `DAY 022`).
- **`headline_metric`** — first of `["val_bpb", "val_loss", …]` that
  appears in ≥2 records.
- **`chart_baseline`** — best (lowest) `headline_metric` value across all
  records strictly before this date.
- **`test_rows`** — one row per unique title (collapsing seed replicas),
  sorted by run-time ascending. Each row: `n, time, hardware, title,
  value, n_runs, link_label, link_href, run_script, time_iso, camp,
  delta_pct`.
- **`arch_families`** — list of `(family_name, count)` tuples, ordered by
  count descending; first match wins per `ARCH_FAMILIES` regex table.
- **`valid_count` / `invalid_count`** — `value ≥/< INVALID_VAL_BPB_FLOOR`.

### 6.3 Required metric keys (when present in source)

The metric extractors in `stripper.py` and `enrich.py` MUST map to these
canonical keys:

| Key                      | Source-of-truth                                          |
|--------------------------|----------------------------------------------------------|
| `val_bpb`                | bits-per-byte. Sanity floor: ≥ 0.1.                     |
| `val_loss`               | natural-log loss.                                        |
| `val_bpb_int6_*`         | per-quantization variant from `final_*` lines.           |
| `n_ranks`                | distinct rank IDs in training-log output (HW signal).    |
| `train_time_seconds`     | last `train_time:Nms` in log content.                    |
| `step_final`             | last `step:N/M` in log content.                          |
| `filename_run_start`     | `YYYYMMDD_HHMMSS` parsed from training-log filename.     |
| `n_user_turns`           | codex/claude session: `event_msg`/`user_message` count.  |
| `n_agent_turns`          | codex/claude session: `agent_message` count.             |
| `n_exec_commands`        | codex/claude session: `exec_command_end` count.          |
| `n_patches`              | codex/claude session: `patch_apply_end` count.           |
| `session_duration_seconds` | last_event_ts − first_event_ts                         |

### 6.4 Architecture-family detection

The `ARCH_FAMILIES` list in `render_day.py` is the source of truth for
canonical family names and their detection regex. New family codenames
go there. Order matters: more-specific patterns first.

### 6.5 Camp classifier

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

The renderer (`render_day.py`) is the only consumer of the scraper output
that's allowed to write the canonical HTML. Other tools (e.g.
`render_all.py`) call `render_one_day` and treat its return value as
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

---

## 8. WHAT IS DELIBERATELY NOT IN THE TEMPLATE

To avoid feature creep, these are **rejected proposals**:

- A "Daily Grind" section that summarizes session activity. Sessions
  appear in Supporting Files; their stripe color encodes camp.
- Additional accent colors. The five-token palette is the lock.
- Card-fill backgrounds, drop shadows, gradients (except the neural
  diagonal-stripe pattern).
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
4. Re-render Day 12 (`2026-03-28`) as the canonical regression check —
   if anything in §5 (invariants) breaks, the change is rejected.

---

_This template is locked at the visual+structural level. The source data
behind any rendered instance is the live SQLite index produced by the
scraper for that date._
