# research-collator

Pure-Python deterministic scraper + Karpathy-style daily report renderer for
parameter-golf research. Walks local research dirs + git history + agent
session JSONLs, extracts metrics with strict regex (no LLM at runtime), and
renders one self-contained HTML report per work day in a late-80s lab-protocol
aesthetic.

## What's here

| File | Role |
|---|---|
| `stripper.py` | File walker → SQLite. Handlers for `.md`, `.json`, `.py`, `.csv`, `.tsv`, `.log`, `.out`, `.pt` (metadata only). Strict patterns; no LLM. |
| `enrich.py` | Adds git commits + Claude session JSONLs + Codex session JSONLs to the index. Pulls val_bpb / val_loss out of commit messages with delta-vs-absolute classification + sanity floor. |
| `classify.py` | Two-camp classifier (`experimental` vs `neural`) + a third `daily_grind` camp for codex rollouts. Path / source / keyword rules, no LLM. |
| `render_day.py` | Builds one daily HTML report. Header dot-leader fields, camp ratio bar, Karpathy-style time-axis chart, test-runs table with clickable links. |
| `render_all.py` | Batch-renders every date with activity + a journey-arc front page. |
| `plot.py` | Matplotlib helpers. `day_chart` (per-day trajectory) and `journey_chart` (50-day arc). |
| `config.yaml` | Roots to walk, exclusion list, file-extension → handler map. |

## Design palette (cohesive, late-80s lab-protocol / dark CRT)

Five colors total:

```
BG       #0a0d0a   THE black, used everywhere
INK      #c8d4c0   paper-white, slightly green
ACCENT   #7dff7d   phosphor green — ALL semantic emphasis
WARN     #ff5c4a   INVALID-only red, used sparingly
DATA     #d8a040 (gold) + #6196c4 (slate) — categorical only
```

No greys. Surface differentiation comes from 45° dither hatching on the same
black background, not subtly-different blacks.

## Validity floor

Project convention: any `val_bpb < 1.06` is a known eval error, plotted
inside a red-hatched zone on the chart and excluded from the running-min
"best valid" line. Marked `INVALID` in the test-runs table.

## Camp axis

Two top-level test camps + a daily-grind narrative track:

- **experimental** — crawler / megakernel / ouroboros / helix / clowncar /
  jepa / shroud / hypothesis / ablation / etc.
- **neural** — strict baselines, leaderboard submissions, racing legs,
  competitive sources (SOTA_FINAL, sota_rascal).
- **daily_grind** — codex rollouts (narrative summaries of session work).

## How to run end-to-end

```bash
python3 stripper.py            # walk research roots → index.sqlite
python3 enrich.py              # +git commits, +claude/codex sessions
python3 classify.py            # tag every record with camp
python3 render_day.py --date 2026-03-28   # one day
python3 render_all.py          # all days + journey arc + index page
```

Output lands in `output/preview/<DATE>.html` (self-contained, base64 PNGs
embedded — works offline).

## License

Private working tree.

## Master template

[`TEMPLATE.md`](TEMPLATE.md) is the canonical specification: locked
palette, layout, chart contract, scraper contract, invariants. Any
change to the per-day report must update `TEMPLATE.md` first; code is
downstream of the spec.
