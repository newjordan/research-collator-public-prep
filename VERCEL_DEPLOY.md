# Vercel static deploy

`vercel.json` publishes `output/preview` as a static site.

- `/` is rewritten to `/report_144.html`.
- Every response sets `X-Robots-Tag: noindex`.

`output/preview` is already tracked so a connected Git deployment can serve
the report set without the private research corpus. `.gitignore` ignores
`output/` for newly generated files; it does not untrack pages that are
already in git. `index.sqlite` is ignored and is not part of the deploy.

Rebuild the pages locally when the corpus or renderers change:

```bash
python3 -m pip install -e .
python3 stripper.py
python3 enrich.py
python3 classify.py
python3 render_all.py
```

`stripper.py` skips configured roots that are not on this machine. A full
rebuild needs those directories.

Primary URLs after deploy:

- `/` and `/report_144.html` — table of contents and reader
- `/cover.html` — cover
- `/intro.html` — address to the reader
- `/cumulative.html` — campaign report
- `/categories/index.html` — category reports
- `/weeks/index.html` — weekly reports
- `/2026-03-18.html` through `/2026-05-01.html` — daily reports
- `/ai/` — short machine-readable index
