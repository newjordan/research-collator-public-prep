# Claude Handoff - Audit and Evidence Wiring Loops

Date: 2026-05-09
Repo: `/home/frosty40/research_collator`
Branch: `art/palette-switcher`
Locked starting commit: `a5b576f`

## Assignment

Run focused loops on evidence wiring and report affordances. The current public
document is structurally complete: generated links resolve and the report set
renders, but several rich evidence veins exist on disk without being surfaced
where a reader naturally expects them.

Do not re-litigate page art, intro copy, palette easter eggs, or TOC styling in
this pass. This work is about making the proof-of-work feel less hollow by
connecting existing artifacts to the daily, category, and row-detail surfaces.

## Current State To Preserve

- TOC/intro visual work is committed and pushed through `a5b576f`.
- Hidden palette triggers exist on stamps/flake marks.
- TOC custom scrollbar is outside the palette filter.
- TOC footer wolves mark exists as a bottom-right darken background element.
- Back-to-top control exists on the TOC.
- Construction copy around lazy loading has been removed from TOC, category,
  and daily kernel lazy sections.
- Worktree was clean before this handoff file was added.

## TL;DR

The pipeline is structurally complete, but the issue is join quality and
evidence surfacing. The disk holds 51,716 indexed artifacts and 50,000+ raw
files. Daily reports mostly surface the per-row training-log slice. At least
six high-value evidence veins are already present and reachable by date,
family, or source, but are not consistently exposed as clickable affordances.

## Evidence Veins

### Architecture Run Files

On disk:

- `output/preview/architecture-run-files/`
- 43 of 43 archives
- 147 source files
- Manifest includes sha256s and GitHub raw URLs

Currently surfaced:

- Only families whose row names match exact keys in
  `PUBLIC_ARCH_FAMILY_LABELS` get a download button.

Problem:

- Many rows show `--` even when a real on-disk archive exists.

### Per-row Training Logs

On disk:

- 3,524 indexed `training_log` artifacts
- Full text in `_log[N]_<hash>.html` fragments

Currently surfaced:

- The load details -> load log chain works.

Problem:

- The double disclosure makes the report feel empty until the reader clicks
  twice.

### Conversation / Decision Trail

On disk:

- `output/conversation_architecture/*.summary.json`
- `output/conversation_architecture/*.timeline.md`
- 25,609 `conversation_arch_event` rows
- 571 `claude_session` and 531 `codex_session` indexed rows

Currently surfaced:

- Not surfaced on day pages.

Problem:

- Daily pages lack a clear "what was the thinking" affordance.

### Audit / Data Quality

On disk:

- `output/audit/daily_accuracy.json`
- `AUDIT_FINDINGS_2026-05-07.md`

Currently surfaced:

- Not surfaced.

Problem:

- The report does not visibly explain why numbers should be trusted.

### Ablation Labels

On disk:

- `output/ablation_labels/*.{manifest,prompt,review}.{jsonl,md}`
- 8 studies

Currently surfaced:

- The label string is applied to row evidence through
  `apply_approved_ablation_labels`.

Problem:

- Rows can say "ablation: <label>" without click-through to rationale.

### Git Commits

On disk:

- 4,294 `git_commit` artifacts indexed

Currently surfaced:

- Excluded as supporting evidence through `SUPPORTING_EXCLUDED_KINDS`.

Problem:

- No compact "code that landed this day" timeline exists.

### Per-row Chart Source

On disk:

- Charts render as images.
- Underlying source data exists through SQLite / CSV-capable artifacts.

Currently surfaced:

- Image only.

Problem:

- No download or re-plot affordance exists.

## Root Cause Analysis

1. The architecture join is brittle. `architecture_download_button_html(family)`
   keys into a hand-maintained label dictionary. Use the manifest aliases plus
   `data/architecture_recipes.json` as the source of truth.
2. `conversation_architecture` is staged but not published.
3. Audit files exist but no presenter exists.
4. Row details cascade too deep. Real log content is one more click behind
   metadata, so the first expansion can feel hollow.

## Tier 1 - High-impact, Low-risk

Do this first and re-evaluate.

1. Fix architecture-run-files join.

   Build a normalized family-to-slug index at script start by joining:

   - `data/architecture_recipes.json`
   - `output/preview/architecture-run-files/manifest.json`

   Use aliases, slug, family, and normalized labels. Expected result: most of
   the 43 architecture archives gain working download/view-source buttons
   across the corpus.

   Likely files:

   - `render_day.py`
   - small helper module if needed

2. Promote log content above metadata in row detail.

   Show a first log preview on the first row expansion, then keep "view full
   log" for the rest. One disclosure to meaningful content, not two.

   Likely area:

   - `_row_evidence_panel_html`
   - row log fragment rendering helpers

3. Per-day audit badge.

   Read `output/audit/daily_accuracy.json` and render a compact daily status
   chip in the report header:

   - headline metric
   - raw records
   - render records
   - warnings/fatal

   Click/expand into the day's audit details. If
   `AUDIT_FINDINGS_2026-05-07.md` is stale, do not present stale findings as
   current.

## Tier 2 - Decision Trail Surfacing

4. Conversation timeline link from each day page.

   For date `D`, look up:

   - `output/conversation_architecture/D.timeline.md`
   - matching multi-day windows containing `D`

   Render a compact "decision trail" disclosure. Prefer per-day filtered events
   over serving the full campaign timeline raw.

5. Ablation rationale link.

   Where `apply_approved_ablation_labels` injects a label, surface a link to
   the matching `ablation_labels/<id>.review.md` if it exists. Fragment-load on
   click.

## Tier 3 - Code Provenance

6. "Commits this day" timeline.

   Pull day-local `git_commit` artifacts from SQLite by date and render compact
   subject lines linked to GitHub commit URLs. Do not relax
   `SUPPORTING_EXCLUDED_KINDS` globally. Add a dedicated panel.

## Tier 4 - Deep-link Infrastructure

7. Per-artifact viewer route.

   Add a static viewer that accepts `?artifact=<id>` and renders artifact text
   plus metadata from SQLite. Surface artifact IDs in row-detail metadata.

8. Per-row chart download.

   Emit a small CSV/data link next to each chart image when the underlying
   source data is available.

## Risks And Guardrails

- Family-name normalization can over-map ad-hoc test names. Enumerate distinct
  family values before committing aggressive join logic.
- Conversation timelines can be large. Use per-day filtering, not raw global
  timeline dumps.
- Git commits are noisy. Surface them only through a dedicated compact panel.
- Audit findings must be current. If a file is dated or stale, either regenerate
  or label it explicitly.
- Do not render raw Claude/Codex transcripts directly in public report pages.
- Keep scraper/classifier/renderer deterministic. No LLM calls inside the
  scrape/render path.

## First Milestone Definition

Tier 1 is the milestone. Stop after those three changes and re-evaluate. If the
report still feels hollow after Tier 1, the remaining click paths should reveal
which Tier 2 or Tier 3 vein deserves priority.
