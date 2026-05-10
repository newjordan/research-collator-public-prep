# Wiring depth — out-of-scope notes

Observations spotted during loop iterations that don't fit the current task.
Add one-liners only; address in a follow-up plan.

## From T4.2

- Spec asked to resolve the chart's CSV via SQLite (`csv_row_count > 0 AND date + camp match`). The 740 CSV artifacts in `index.sqlite` are mostly sidelane `summary.tsv` files from `parameter-golf-lab/neural/test_lab/...` — they're not the chart's source data. Implementation deviates: emits the chart's actual underlying `test_rows` as a fresh per-day CSV under `output/preview/csv/<date>_test_rows.csv` (15 columns: n, title, display_ablation, family, camp, time_iso, hardware, wallclock_seconds, val_bpb + source, kernel_fb_ratio + source, n_runs, source_label). Single CSV per day backs every chart panel on that day.
- Follow-up: a separate "associated artifacts" panel could surface the SQLite `csv_row_count > 0` artifacts (sidelane summaries etc.) for the day, since they're useful but not the chart source.

## From T3.1

- Spec asked for subject lines to link to GitHub commit URLs "using repo URL from manifest.json", but `manifest.json` only carries the URL of the research-collator repo (where architecture run files live), not the multiple source repos that produced the commits in `index.sqlite` (`git:dotagents_mono`, `git:parameter-golf-lab`, `git:sota_crawler`, `git:sota_rascal`, `git:sota_nueral`, etc.). Subjects render as plain text. Follow-up: a small per-source-label → GitHub URL map (probably 5–8 entries) would unlock the links.
- The `artifacts` schema doesn't extract a commit author column, so the panel shows hash · time · repo · subject (no author). Adding author would require either a schema extension during indexing or a per-row Python git lookup at render time (slow).
- Commit-count discrepancies between `date(mtime_iso)` and `best_date()`: `date(mtime_iso)` is UTC, `best_date()` applies a CDT/local conversion. 2026-03-22 had 552 commits by raw UTC date, 479 by best_date — both correct, just different definitions. The panel uses best_date to match how the rest of the page is dated.

## From T2.1

- Multi-day-window timeline slices for high-density days were 5–6 MB each before truncation. Capped to ~300KB source chars (the HTML expansion lands closer to ~340KB). 25 of 41 emitted panels truncate at the cap. Follow-up: serve the raw `.timeline.md` from a path under `output/preview/` so the truncation footer can carry a working "view full" link, or paginate the fragment.

## From T1.2

- Inline preview shows the first 40 lines verbatim (per spec). On `train_seed*.log` files those leading lines are the training-script source code, not training metrics — visually less informative than expected. Follow-up: smarter preview slice (e.g., grep for the first `step:` line and show ±20 lines around it, or pair head + final-eval tail).

## From T1.1

- 13 unresolved family strings in row data are **categorical / aggregation labels** with no architecture run-file bundle by design: `Compact Transformer Recipe`, `Compression Packaging`, `Crawler Ablation`, `Cubric Racing Variant`, `Leaderboard Transformer Variants`, `Mixed Quant`, `Other`, `Parallel Residuals`, `Progressive MLP / Fractal`, `SLOT Tuned Body`, `Sliding Window`, `State-Space (TTT)`, `XSA`. Either (a) accept `—` as correct for these, or (b) author umbrella manifest entries that point to a category index page rather than a single archive.
- Spread tables only reference ~21 of the 43 manifest architectures across the corpus; the remaining 22 are reachable only from category / week pages. The "≥40 of 43" goal in the task acceptance was structurally unreachable from row data alone — current join is correct, the surface itself is narrow.
