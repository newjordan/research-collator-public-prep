# Vercel Static Deploy

This report set is a static site once `output/preview/` is rendered.

## Important

`index.sqlite` and `output/` are intentionally ignored by git because they
contain scraped local paths and large generated HTML. A GitHub-connected
Vercel build will only work from an environment that has the local SQLite
index and research corpus available.

The safest deployment path is local static deploy from this machine:

```bash
cd /home/frosty40/research_collator
python3 render_all.py
npx vercel deploy --prod
```

`vercel.json` serves `output/preview` and rewrites `/` to `/cover.html`.
`output/preview/index.html` is also rendered as the cover page, so a direct
static-folder open starts on the cover too.

Primary entry points after deploy:

- `/cover.html` — cover page / first page
- `/toc.html` — long-loader table of contents; starts with page 2 above the TOC
- `/cumulative.html` — campaign cumulative report
- `/categories/index.html` — category reports
- `/weeks/index.html` — weekly reports
- `/2026-03-18.html` through `/2026-05-01.html` — daily reports
