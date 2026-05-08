# Proof of Work Intro Letter

To whoever is reviewing this:

This is a fifty-day record of applied AI research, not a retrospective sales pitch.

From 2026-03-18 to 2026-05-01, I worked through a live parameter-golf campaign across three technical tracks: model-compression experiments, neural submission work, and custom-kernel/FA3 performance work. The work involved proposing changes, running tests, reading failures honestly, rejecting bad signals, tracking evaluation validity, and deciding what to try next under contest constraints.

What was hard was staying useful while the answer was not known yet. The campaign had false starts, invalid-looking wins, metric splits, hardware-specific results, submission constraints, and changing hypotheses. I had to keep separating real progress from noise instead of forcing every promising number into a success story.

The through-line is work ethic: find the next measurable weakness, test it, fix it or reject it, then come back the next day and do it again. A representative day was standing up a 10k-vocab SP10240 CaseOps variant, running three 8xH100 seeds, and getting it to 1.06243460 BPB under the 16 MB cap. That was not a victory lap; it was another iteration in a campaign built on daily improvement.

What I can now do that most people cannot is operate inside uncertain AI research without losing the thread. I can move between model architecture ideas, compression tradeoffs, benchmark validity, GPU/kernel performance, and final submission pressure. I can build, test, reject, preserve, and explain the work in a way that survives inspection.

The next thing someone should trust me with is applied AI research engineering where correctness matters more than presentation. I am useful when the problem is underdefined, the deadline is real, and the result has to survive contact with actual experiments: benchmark systems, model-compression evaluations, GPU/kernel performance work, submission engineering, and evidence-grounded research operations.

The short version of the evidence is:

- Campaign span: 2026-03-18 to 2026-05-01.
- Public research surface: 45 daily reports, 7 weekly reports, 3 category reports, 1 cumulative campaign report.
- Campaign datapoints: 64 category-local daily datapoints.
- Classification split: experimental 33, neural 22, kernel 9.
- Metrics separated by validity: 55 VAL_BPB datapoints and 9 CUSTOM/FA3 FB RATIO datapoints.
- Best observed category minima in the cumulative report: experimental 1.0672 BPB, neural 1.0620 BPB, kernel 0.748x custom/FA3 FB ratio.
- Architecture/test surface: 30+ architecture, compression, crawler, TTT, and kernel-performance families catalogued; public review groups them by technical surface: recursive weight sharing, cubric n-gram mixing, looped GQA bodies, long-context mechanisms, state-space recurrence, crawler stacks, quantization/TTT packaging, and custom FA3 kernel benchmarking.
- Estimated work cadence: 460.6 activity hours across 45 campaign days, averaging 10.2 hours per day.
- Commit volume: 1,701 distinct non-reference commit hashes, 1,954 distinct total commit hashes indexed across tracked research repos.
- Test volume: 3,572 measured test rows across 41 test-active days.
- Peak measured day: 1,289 kernel benchmark rows on 2026-04-19.
- Evidence volume: 3,485 training logs and 5,923 JSON artifacts in the campaign window.

You do not have to read everything first. Start with:

- `output/preview/cumulative.html` for the campaign-level summary.
- `output/preview/categories/experimental.html` for the experimental BPB track.
- `output/preview/categories/neural.html` for the neural BPB track.
- `output/preview/categories/kernel.html` for the custom-kernel/FA3 ratio track.
- `output/audit/daily_accuracy.md` for the row-level accuracy audit.
- `ARCHITECTURE_TEST_SURFACE_PUBLIC.md` for the sanitized architecture/test-surface index.

The work should speak first. My claim is simply that I can do this kind of research engineering again, under pressure, for a harder problem.
