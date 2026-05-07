# Daily Accuracy Harness

This repo now has three deterministic gates:

1. `scripts/verify_scraper_contract.py`
   Checks the SQLite/index contract: schema, parser outputs, metric typing,
   indexes, and coarse `fetch_day()` date attribution.

2. `scripts/verify_daily_template.py --all`
   Checks rendered pages against the locked visual/HTML contract: two sections,
   no chat leaks, Section 2 dropdowns, full-width detail rows, and embedded log
   text when logs exist.

3. `scripts/audit_daily_accuracy.py --all`
   Checks row-level accuracy for daily reports. This is the main harness for
   "wrong tests on wrong days."

## Why Not RAG First

RAG is useful for human review after we know what to inspect. It is not the
right authority for date attribution. The first-pass system should be exact:

- SQLite for canonical indexed artifacts.
- Renderer provenance for each Section 2 row.
- Regex date evidence from filenames, paths, titles, and metric metadata.
- Local mtime converted to the campaign timezone.
- Metric-source tags such as `log_final_eval`, `json_top_level`, and
  `commit_message`.
- `rg` for targeted follow-up once a suspect row is identified.

Embeddings can help search notes later, but they should never decide which day
a test belongs to.

## Run It

Full campaign:

```bash
python3 scripts/audit_daily_accuracy.py --all
```

Single day:

```bash
python3 scripts/audit_daily_accuracy.py --date 2026-04-17
```

Treat warnings as CI failures:

```bash
python3 scripts/audit_daily_accuracy.py --all --strict-warnings
```

Outputs are written here by default:

- `output/audit/daily_accuracy.json`
- `output/audit/daily_accuracy.md`

## What It Fails On

Fatal issues mean the renderer is probably wrong:

- `source_best_date_mismatch`: a source record rendered on a day different
  from `best_date()`.
- `run_start_date_mismatch`: `filename_run_start` says the run happened on a
  different date.
- `basename_date_mismatch`: the artifact filename contains a different run
  date.
- `row_time_date_mismatch`: rendered row time disagrees with the page date.
- `n_runs_source_count_mismatch`: row replication count no longer matches
  traced metric values.
- `daily_grind_test_row`: narrative/session material reached Section 2.
- `final_submission_missing`: the final campaign day has no rendered
  Mockingbird test rows.
- `final_submission_not_neural`: the final campaign day rendered a non-neural
  Section 2 row.
- `final_submission_not_mockingbird`: the final campaign day rendered a
  Section 2 row outside the Mockingbird final-submission record.

Warnings mean the row is weaker evidence or needs review:

- `commit_only_metric`: metric came only from git commit text, not a log/json
  result.
- `unknown_metric_source`: non-kernel metric source could not be classified.
- `weak_date_evidence`: path dates and local mtime do not independently support
  the rendered date.

## Triage Loop

1. Run `python3 scripts/audit_daily_accuracy.py --all`.
2. Open `output/audit/daily_accuracy.md`.
3. For any fatal issue, inspect the exact source path listed in the sample.
4. Use `rg` on that path/date/title to find the raw evidence.
5. Fix the deterministic parser/date/classification rule.
6. Rebuild with `python3 render_all.py`.
7. Re-run all three gates.

The target is not "ask an LLM to judge the day." The target is a repeatable
evidence ledger where every daily row can defend why it is on that date.
