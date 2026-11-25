# research-collator

Deterministic scraper and report renderer for a parameter-golf research corpus.
It walks local research directories, git history, and agent session logs, stores
structured records in SQLite, and renders a static HTML report set. Scraping
and rendering do not call a language model.

The configured research chronology is `2026-03-18` (day 001) through
`2026-05-01`. Those bounds live in `render_day.py` as `RESEARCH_START_DATE`
and `RESEARCH_END_DATE`.

## Requirements

- Python 3.11 or newer
- [PyYAML](https://pypi.org/project/PyYAML/) and [Matplotlib](https://matplotlib.org/)

`adjustText` is optional. Charts render without it.

The automated suite in this checkout was run with Python 3.12.3: 35 tests
passed.

## Setup

```bash
python3 -m pip install -e ".[dev]"
```

`config.yaml` lists the research roots, git repos, session directories, and
the SQLite path. `~` is expanded. Paths written as `~/research_collator/...`
follow this checkout when that historical directory is not already on disk.
Relative paths, including the default `sqlite_path: index.sqlite`, are
resolved from the repository root.

Roots that are not present are skipped. A machine without the research
corpus can still run the test suite.

## Index and classify

```bash
python3 stripper.py            # walk roots into index.sqlite
python3 enrich.py              # git commits and Claude/Codex session JSONLs
python3 classify.py            # experimental, neural, or daily_grind
```

`stripper.py --smoke N` stops after N kept files. `enrich.py` and
`classify.py` refuse to create an empty database; build the index with
`stripper.py` first.

Handlers cover Markdown, JSON, Python, CSV/TSV, text, training logs
(`.log` and `.out`), and metadata-only checkpoints and media. Training-log
`val_bpb` is accepted only from `step:N val_loss:X val_bpb:Y` and
`final_* val_loss:X val_bpb:Y` lines.

## Render

```bash
python3 render_day.py --date 2026-03-28
python3 render_day.py --day 1
python3 render_week.py --week 1
python3 render_category.py --all
python3 render_campaign.py
python3 render_cover.py
python3 render_toc.py
python3 render_all.py
```

Rendered pages are written under `output/preview/`. The tracked tree there is
the static site. `output/` is listed in `.gitignore` for new generated files;
the preview pages already in git stay tracked so the site can be served
without the private corpus.

| Path | Page |
|---|---|
| `output/preview/report_144.html` | Table of contents and reader. Site entry. |
| `output/preview/cover.html` | Cover |
| `output/preview/intro.html` | Address to the reader |
| `output/preview/<DATE>.html` | One research day |
| `output/preview/weeks/` | Weekly rollups |
| `output/preview/categories/` | Experimental, neural, and kernel rollups |
| `output/preview/cumulative.html` | Campaign overlay |
| `output/preview/ai/` | Machine-readable manifest and short index |

`vercel.json` serves `output/preview`, rewrites `/` to `/report_144.html`,
and sends `X-Robots-Tag: noindex`.

## Classification and validity

`classify.py` stores one camp per artifact:

- **experimental** — architecture and exploration families such as crawler, megakernel, ouroboros, helix, and clowncar
- **neural** — racing legs, submissions, baselines, and the competitive sources
- **daily_grind** — Codex rollout narratives

Daily pages can present a **kernel** classification when the headline metric
is a custom-kernel/FA3 timing ratio. That label is display-only; it is not a
fourth stored camp.

`val_bpb` below `1.06` is treated as an invalid evaluation and is excluded
from the running-best line. `val_bpb` above `3.0` is treated as a crash.
Those thresholds are BPB-only.

Chat sessions and conversation-mined architecture events can be indexed.
They are not rendered in the daily report body.

Day attribution uses a real calendar date from the filename or path, then
the UTC `mtime` converted to `America/Chicago`. Central Standard Time and
Central Daylight Time are both honored. Git commits are dated from the
commit timestamp, not from hex that happens to look like a date.

## Template

Daily pages follow `daily-report-v2.6-architecture-recipes`. The locked CSS
is `templates/daily_report_locked.html`, checked against
`LOCKED_TEMPLATE_STYLE_SHA256` in `render_day.py`. `TEMPLATE.md` is the
layout contract. Architecture recipes come from
`data/architecture_recipes.json`.

Weekly pages use `weekly-report-v1.0-daily-rollup`. Category pages use
`category-report-v1.0-biweekly-course`. The campaign page uses
`campaign-cumulative-v1.0-classification-overlay`. The cover uses
`cover-v1.0-first-page`. The table of contents uses `toc-v1.2-page2-webloader`.

Structural checks live in `scripts/verify_*_template.py`. They read the
rendered HTML and, where noted, the SQLite index. `scripts/verify_scraper_contract.py`
checks the index against `TEMPLATE.md`.

## Optional local tools

These are separate from scrape and render. They do not download model
weights. Each one refuses a non-local or wrong-family model.

```bash
python3 chat_extract_local.py --date 2026-03-28 --dry-run
python3 ablation_label_local.py --date 2026-03-28 --dry-run
python3 scripts/mine_conversation_architecture.py --date 2026-03-28
```

`chat_extract_local.py` talks only to local Ollama and only to a model
whose name contains `qwen`. `ablation_label_local.py` talks only to a
local vLLM server (`127.0.0.1`, `localhost`, or `::1`) and only to a
Nemo or Nemotron model. Approved ablation labels are the only ones the
renderer reads, from `output/ablation_labels/approved.jsonl`.
`mine_conversation_architecture.py` is regex-only. Its output stays in
`output/conversation_architecture/` unless `--index` is passed, and those
rows are still not rendered into daily pages.

## Tests

```bash
python3 -m pytest
```

GitHub Actions runs that command on Ubuntu with Python 3.12 (`.github/workflows/ci.yml`).
The suite covers path expansion, camp rules, commit-message metrics,
training-log parsing, Chicago day attribution, a temporary strip plus
classify run, button colors, and a credential scan of the tree.

`scripts/sanitize_audit.py` is a separate content scan of a directory
(default `output/preview`) for home paths, private addresses, handles, and
key shapes. A relative `--scan-dir` is resolved before it is reported.

## Deploy

See [VERCEL_DEPLOY.md](VERCEL_DEPLOY.md). The static deploy uses the
tracked `output/preview` tree. Rebuilding every page requires the local
research roots and an index produced by the commands above.

## License

Private working tree.
