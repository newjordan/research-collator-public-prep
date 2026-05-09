# Wiring depth — out-of-scope notes

Observations spotted during loop iterations that don't fit the current task.
Add one-liners only; address in a follow-up plan.

## From T2.1

- Multi-day-window timeline slices for high-density days were 5–6 MB each before truncation. Capped to ~300KB source chars (the HTML expansion lands closer to ~340KB). 25 of 41 emitted panels truncate at the cap. Follow-up: serve the raw `.timeline.md` from a path under `output/preview/` so the truncation footer can carry a working "view full" link, or paginate the fragment.

## From T1.2

- Inline preview shows the first 40 lines verbatim (per spec). On `train_seed*.log` files those leading lines are the training-script source code, not training metrics — visually less informative than expected. Follow-up: smarter preview slice (e.g., grep for the first `step:` line and show ±20 lines around it, or pair head + final-eval tail).

## From T1.1

- 13 unresolved family strings in row data are **categorical / aggregation labels** with no architecture run-file bundle by design: `Compact Transformer Recipe`, `Compression Packaging`, `Crawler Ablation`, `Cubric Racing Variant`, `Leaderboard Transformer Variants`, `Mixed Quant`, `Other`, `Parallel Residuals`, `Progressive MLP / Fractal`, `SLOT Tuned Body`, `Sliding Window`, `State-Space (TTT)`, `XSA`. Either (a) accept `—` as correct for these, or (b) author umbrella manifest entries that point to a category index page rather than a single archive.
- Spread tables only reference ~21 of the 43 manifest architectures across the corpus; the remaining 22 are reachable only from category / week pages. The "≥40 of 43" goal in the task acceptance was structurally unreachable from row data alone — current join is correct, the surface itself is narrow.
