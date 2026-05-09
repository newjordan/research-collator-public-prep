# Wiring Plan — Surfacing depth on the daily research report

The rendering pipeline emits no broken links, but the daily reports feel
hollow because most of the on-disk material isn't reachable through the
UI. This file is the work plan to fix that. Iterate top to bottom; each
task has files to touch, acceptance criteria, and verification steps.

**Status legend**: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked (must include reason)

## Working rules (apply to every task)

- Do not modify parchment art or any image asset.
- One task per loop iteration. Verify, mark `[x]`, commit, stop.
- Stay on branch `art/palette-switcher` unless told otherwise.
- Each task ends with re-rendering the affected days and confirming via the running preview server on port 8767 (`http://localhost:8767/`).
- Don't bundle unrelated cleanups, refactors, or shims. If you spot something out of scope, note it in `WIRING_DEPTH_NOTES.md` (create if missing) and move on.
- Don't relax existing exclusion lists (e.g. `SUPPORTING_EXCLUDED_KINDS`) globally; add new query paths instead.

## Background pointers (don't re-research)

- `data/architecture_recipes.json` (14 KB, added 2026-05-08) is the new canonical recipe table.
- `output/preview/architecture-run-files/manifest.json` covers all 43 architectures with `aliases`, `slug`, `download_url`, `view_url`, `sha256`.
- `output/audit/daily_accuracy.json` has per-day `headline_metric, raw_records, render_records, test_rows, fatal, warnings`.
- `output/audit/AUDIT_FINDINGS_2026-05-07.md` (11 KB) — narrative findings.
- `output/conversation_architecture/<date>.timeline.md` (per-day) and `<start>_to_<end>.timeline.md` (windows) — decision trails.
- `output/conversation_architecture/<label>.summary.json` — counts/stats for a window.
- `output/ablation_labels/<id>.review.md` — rationale for an applied ablation label.
- `index.sqlite` — `artifacts` table (51,716 rows). Schema includes `abs_path, file_kind, mtime_iso, camp, classification_rule, metrics_json, csv_row_count`. `walk_runs` tracks indexing runs.
- Preview server: already running on `0.0.0.0:8767` serving `output/preview/`.

---

## Tier 1 — high impact, low risk

### [x] T1.1 — Fix the architecture-run-files family join

**Why**: 43/43 architecture archives exist on disk; only families whose row name exact-matches `PUBLIC_ARCH_FAMILY_LABELS` get a download button. The rest show `—` next to a real archive. Manifest carries `aliases` already; `data/architecture_recipes.json` carries canonical mappings — never joined.

**Files**: `render_day.py:1064-1176` (`PUBLIC_ARCH_FAMILY_LABELS`, `load_architecture_run_file_manifest`, `architecture_download_button_html`); `data/architecture_recipes.json`; `output/preview/architecture-run-files/manifest.json`.

**Acceptance**:
- New `resolve_architecture_family(family_name) -> manifest_entry | None` that resolves in order: exact slug → manifest `aliases` → `architecture_recipes.json` mapping → normalized fuzzy match (lowercase, strip whitespace, treat `-`/`_`/space as equivalent).
- `architecture_download_button_html` calls the resolver; emits both download zip + view source links from the manifest entry.
- Console summary at end of render run lists any unresolved family names so the gap is visible.

**Verify**:
```bash
python render_all.py 2>&1 | tee /tmp/render.log
grep -c "architecture_download" output/preview/2026-04-24.html  # should be much higher than baseline (was effectively 1)
grep -i "unresolved.*architecture" /tmp/render.log              # should list any remaining gaps
```
Open `http://localhost:8767/2026-04-24.html` and confirm multiple architecture rows now have working download buttons.

---

### [x] T1.2 — Inline log preview in row-detail fragment

**Why**: Row-detail fragment currently shows only metadata + a `load log` button — two clicks deep before substantive content. The "hollow" feeling lives here.

**Files**: `render_day.py:2566-2620` (`_write_training_log_fragment`, `_training_log_panel_html`, `_row_evidence_panel_html`).

**Acceptance**:
- Row-detail fragment renders the first ~40 lines of the training log inline (above the fold). Use the head of the existing log text — no extra fetch.
- Row evidence (ablation, time, hardware, source, classification, metric_source) renders BELOW the inline log preview.
- Existing "view full log" lazy-load disclosure remains for the rest of the log.
- Don't break the kernel-tests path or non-training rows; their fragments shouldn't change shape.

**Verify**:
- `python render_all.py` rebuilds fragments. Pick `2026-04-15_row0001_details_*.html` and confirm log lines are visible at the top.
- Browser test: open `http://localhost:8767/2026-04-15.html`, click "load details" on row 1, see log preview without extra clicks.

---

### [x] T1.3 — Per-day audit badge in header

**Why**: `output/audit/daily_accuracy.json` carries per-day quality metadata. Surfacing it gives the report a verifiable spine and lets the user trust the headline numbers.

**Files**: `render_day.py` (header section + new `audit_panel_html(date)` helper); possibly `templates/daily_report_locked.html` if header markup needs a slot.

**Acceptance**:
- Header chip: `headline_metric · render_records / raw_records · N warnings`. Color: red if `fatal > 0`, amber if `warnings > 0`, green otherwise. Style consistent with existing chrome (use `--rule-hi` / `--ink-hi`).
- Click expands a panel showing the day's section from `AUDIT_FINDINGS_2026-05-07.md` if a section keyed by the date exists; else show the day's `daily_accuracy.json` entry as a small data block.
- If `daily_accuracy.json` has no entry for the date, render `audit pending` (greyed) — never break.

**Verify**:
- `2026-04-15` chip shows `val_bpb · M / N · K warnings` matching the JSON.
- Click expand renders content.
- A date with no entry (or a deliberate stale path) renders the pending state.

---

## Tier 2 — decision-trail surfacing

### [x] T2.1 — Decision trail panel per day

**Why**: `output/conversation_architecture/` holds the actual reasoning trail (per-day and multi-day timelines + summary stats). Daily report has zero "what was the thinking" affordance today.

**Files**: `render_day.py` (new `decision_trail_panel_html(date)`).

**Acceptance**:
- For each date `D`:
  - Prefer `conversation_architecture/D.timeline.md` if present.
  - Otherwise, find the smallest enclosing window file `<start>_to_<end>.timeline.md` containing `D`.
  - If neither, omit the panel entirely (don't render an empty disclosure).
- Render a one-line teaser from the matching `.summary.json` (e.g. `events_by_source.codex` count, `messages_scanned`) above the disclosure.
- Lazy-load the timeline markdown as HTML on click; convert markdown via the existing rendering path used elsewhere in the report.

**Verify**:
- `2026-03-31`: single-day file exists; panel renders with teaser, click loads timeline.
- `2026-04-15`: no single-day file; should resolve to the smallest enclosing window (e.g. `2026-03-18_to_2026-05-01` if no smaller window covers it).
- A date with no matching files: panel absent.

---

### [x] T2.2 — Ablation rationale click-through

**Why**: `apply_approved_ablation_labels` injects a label string into row evidence; the matching `.review.md` is on disk but never linked.

**Files**: `render_day.py:2589-2620` (`_row_evidence_panel_html`); `render_day.py:2812` (`apply_approved_ablation_labels`).

**Acceptance**:
- Where a row carries an ablation label, render the label as a link that lazy-loads a fragment of the matching `output/ablation_labels/<id>.review.md` rendered as HTML.
- If multiple matching `.review.md` files exist for a label, prefer the most recent by mtime.
- If no review file exists, render the label as plain text (no link, no broken affordance).

**Verify**:
- Find a row with an ablation label on a recent day; the label is now clickable and the review renders.
- Pick a label with no review file; remains plain text.

---

## Tier 3 — code/commits provenance

### [ ] T3.1 — "Commits this day" panel

**Why**: 4,294 `git_commit` artifacts indexed in SQLite, currently excluded from row evidence as noise (`SUPPORTING_EXCLUDED_KINDS`). They belong on the day, not on the row.

**Files**: `render_day.py` (new `commits_panel_html(date)`); reads from `index.sqlite` via existing connection helper.

**Acceptance**:
- Per-day disclosure listing commits with: short hash, author, time, subject line. Sorted by time ascending.
- Subject line linkable to the GitHub commit URL — derive repo from `architecture-run-files/manifest.json` (which has full GitHub raw + view URLs).
- If no commits exist for the date, omit the panel entirely (no empty disclosure).
- DO NOT remove or relax `SUPPORTING_EXCLUDED_KINDS`; add a separate query path that pulls commits where `mtime_iso` matches the day.

**Verify**:
- A day with commits (pick from `sqlite3 index.sqlite "SELECT date(mtime_iso), count(*) FROM artifacts WHERE file_kind='git_commit' GROUP BY 1 ORDER BY 2 DESC LIMIT 5"`) renders the panel.
- A day with zero commits renders nothing in that slot.

---

## Tier 4 — deep-link infrastructure

### [ ] T4.1 — Per-artifact viewer route

**Why**: 51,716 indexed artifacts; nothing is URL-addressable. Sharing a specific log/csv requires copy-paste, not a link.

**Files**: New `render_artifact_viewer.py`; new `output/preview/artifact.html` plus query-param routing.

**Acceptance**:
- `/artifact.html?id=<rowid>` (or `?path=<abs_path>`) renders artifact metadata + text content from `index.sqlite`.
- Text kinds (`training_log, json, md, py, csv, text`) render content inline with appropriate formatting (code/csv table/markdown).
- Binary kinds render a metadata header + "download" link to the raw file.
- Linked from row-detail metadata where the artifact's primary file is identifiable (artifact ID column in evidence).

**Verify**:
- Visit `http://localhost:8767/artifact.html?id=<known-id>` for one of each kind; each renders correctly.
- Click an artifact ID link from a row-detail; lands on the viewer.

---

### [ ] T4.2 — Per-chart CSV download

**Why**: Charts embedded as `<img>` with no source-data link. Verifying numbers requires going to disk.

**Files**: `render_day.py:1351-1360` (`preview_chart_src`); new `csv_download_link(date, camp)` helper.

**Acceptance**:
- Each `<figure>` containing a chart gets a small `csv` link immediately below the image.
- Resolves via SQLite: `artifacts` where `csv_row_count > 0` AND `date(mtime_iso) = date` AND `camp = chart_camp`.
- If multiple match, link to the most recent.
- If none match, omit the link (don't render a broken affordance).

**Verify**:
- A 2026-04-15 chart shows a `csv` link below it; clicking downloads the file.
- A chart for a date/camp pair with no CSV omits the link.

---

## Done conditions

All Tier 1 and Tier 2 tasks complete. Tier 3 and 4 may be deferred to a follow-up plan. After Tier 1, re-walk a recent day end-to-end (header → architecture row → row detail → log → audit badge expand) and confirm the surface no longer reads hollow. After Tier 2, the same walk should also yield a decision-trail panel and clickable ablation rationale.
