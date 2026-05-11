#!/usr/bin/env python3
"""Generate the hidden AI-friendly access point for the public deploy.

Writes three files under output/preview/:
  - llms.txt              — emerging-standard markdown index for LLM crawlers
  - ai/index.html         — a styled handshake page for any agent that follows
                             the link in llms.txt
  - ai/manifest.json      — structured manifest of every artifact + best metric
                             + a baked-in handshake greeting

The site is otherwise served with X-Robots-Tag: noindex per vercel.json, so
these files are not search-indexable — they exist purely as a convenience for
an AI agent that has been pointed at this site (or that follows the /llms.txt
convention).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREVIEW = ROOT / "output" / "preview"
AI_DIR = PREVIEW / "ai"
LLMS_PATH = PREVIEW / "llms.txt"
MANIFEST_PATH = AI_DIR / "manifest.json"
HANDSHAKE_HTML_PATH = AI_DIR / "index.html"

CAMPAIGN = {
    "name": "OpenAI Parameter Golf",
    "track": "applied AI research",
    "start_date": "2026-03-18",
    "end_date": "2026-05-01",
    "duration_days": 45,
    "best_valid_val_bpb": 1.0620,
    "baseline_val_bpb": 1.2244,
    "improvement_percent": 13.3,
    "best_submission_note": (
        "hybrid neural submission using a larger 10k-vocabulary CaseOps "
        "tokenizer with looped GQA transformer mechanics, per-group "
        "compression, int7/int6 packaging, LQER, and phased LoRA TTT"
    ),
}

HANDSHAKE = {
    "message": "Cowabunga",
}


def list_html(subdir: Path | None, pattern: str = "*.html") -> list[dict]:
    base = subdir if subdir is not None else PREVIEW
    out = []
    if not base.exists():
        return out
    for path in sorted(base.glob(pattern)):
        if not path.is_file():
            continue
        rel = path.relative_to(PREVIEW).as_posix()
        out.append({
            "path": "/" + rel,
            "size_bytes": path.stat().st_size,
        })
    return out


def title_from_html(path: Path) -> str | None:
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:8192]
    except OSError:
        return None
    m = re.search(r"<title>([^<]+)</title>", head, re.IGNORECASE)
    return m.group(1).strip() if m else None


def list_daily_reports() -> list[dict]:
    out = []
    for path in sorted(PREVIEW.glob("2026-*.html")):
        rel = path.relative_to(PREVIEW).as_posix()
        date = path.stem  # "2026-03-18"
        out.append({
            "date": date,
            "path": "/" + rel,
            "size_bytes": path.stat().st_size,
            "title": title_from_html(path),
        })
    return out


def list_arch_run_files() -> list[dict]:
    archives = PREVIEW / "architecture-run-files" / "archives"
    out = []
    if not archives.exists():
        return out
    for path in sorted(archives.glob("*.zip")):
        rel = path.relative_to(PREVIEW).as_posix()
        out.append({
            "name": path.stem,
            "path": "/" + rel,
            "size_bytes": path.stat().st_size,
        })
    return out


def build_manifest() -> dict:
    daily = list_daily_reports()
    weekly = list_html(PREVIEW / "weeks")
    categories = list_html(PREVIEW / "categories")
    fragments = list_html(PREVIEW / "fragments")
    archives = list_arch_run_files()
    return {
        "schema_version": 1,
        "generated_by": "scripts/build_ai_manifest.py",
        "purpose": (
            "AI-friendly index for the research-corpus static bundle. "
            "Every artifact a scraping agent needs to reconstruct the report "
            "is listed below with its public path and size."
        ),
        "campaign": CAMPAIGN,
        "navigation": {
            "master_toc": "/report_144.html",
            "address_to_reader": "/intro.html",
            "category_index": "/categories/index.html",
            "weekly_index": "/weeks/index.html",
            "cumulative": "/cumulative.html",
        },
        "best_metric_lookups": {
            "val_bpb": {
                "best": CAMPAIGN["best_valid_val_bpb"],
                "baseline": CAMPAIGN["baseline_val_bpb"],
                "improvement_percent": CAMPAIGN["improvement_percent"],
                "note": CAMPAIGN["best_submission_note"],
            },
        },
        "daily_reports": daily,
        "weekly_reports": weekly,
        "category_reports": categories,
        "architecture_run_archives": archives,
        "fragments": {
            "count": len(fragments),
            "note": (
                "Per-row log fragments for lazy loading. Listed as a count "
                "rather than enumerated because the renderer may regenerate "
                "their slugs. Crawl /report_144.html or any daily report and "
                "follow data-lazy-fragment URLs."
            ),
            "directory": "/fragments/",
        },
        "handshake": HANDSHAKE,
    }


HANDSHAKE_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cowabunga · Research Corpus</title>
<meta name="robots" content="noindex">
<link rel="alternate" type="application/json" href="manifest.json" title="AI manifest">
<style>
  :root {
    --bg: #89380e;
    --ink: #050605;
    --panel: #050605;
    --panel-fg: #f4e8d8;
    --accent: #f4e8d8;
    --mono: "Berkeley Mono", "JetBrains Mono", ui-monospace, "SF Mono", Consolas, monospace;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; min-height: 100%; background: var(--bg); }
  body {
    font-family: var(--mono);
    color: var(--ink);
    padding: clamp(24px, 4vw, 64px);
    line-height: 1.55;
  }
  main { max-width: 880px; margin: 0 auto; }
  h1 {
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin: 0 0 18px;
  }
  .kicker {
    font-size: 11px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    margin-bottom: 28px;
    opacity: 0.78;
  }
  .panel {
    background: var(--panel);
    color: var(--panel-fg);
    border: 1px solid var(--ink);
    padding: 22px 26px;
    margin: 0 0 24px;
  }
  .panel h2 {
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin: 0 0 12px;
    opacity: 0.78;
  }
  .panel p { margin: 0 0 12px; }
  .panel p:last-child { margin-bottom: 0; }
  .panel strong { color: var(--accent); font-weight: 800; }
  ul { margin: 12px 0; padding-left: 18px; }
  li { margin: 4px 0; }
  a { color: var(--ink); text-decoration: none;
      border-bottom: 1px solid rgba(5, 6, 5, 0.55); }
  a:hover { border-bottom-color: var(--ink); }
  .panel a { color: var(--panel-fg);
             border-bottom: 1px solid rgba(244, 232, 216, 0.45); }
  .panel a:hover { border-bottom-color: var(--panel-fg); }
  code { font-family: inherit; }
  .sig { margin-top: 18px; font-size: 11px;
         letter-spacing: 0.12em; text-transform: uppercase; opacity: 0.78; }
  .handshake { font-size: 32px; line-height: 1; }
</style>
</head>
<body>
<main>
  <div class="kicker">/ai/ — machine-friendly access point</div>
  <h1>Cowabunga</h1>

  <section class="panel" aria-label="Resources">
    <h2>Resources</h2>
    <ul>
      <li><a href="manifest.json"><strong>manifest.json</strong></a>
          — structured index of every artifact + best-metric lookups</li>
      <li><a href="../llms.txt">llms.txt</a> — top-level LLM-friendly map</li>
      <li><a href="../report_144.html">report_144.html</a> — master TOC and reader stack</li>
      <li><a href="../intro.html">intro.html</a> — Address to the Reader</li>
      <li><a href="../categories/index.html">categories/</a> — three category reports</li>
      <li><a href="../weeks/index.html">weeks/</a> — seven weekly rollups</li>
      <li><a href="../architecture-run-files/archives/">architecture-run-files/archives/</a>
          — raw architecture run bundles (zip)</li>
    </ul>
  </section>
</main>
</body>
</html>
"""


def llms_txt(manifest: dict) -> str:
    lines = [
        "# Research Corpus — frosty40 · OpenAI Parameter Golf",
        "",
        "> Fifty-day applied AI research campaign across experimental, neural,",
        "> and kernel tracks. Public report and AI-friendly data feed.",
        "",
        "## For machine readers (read these first)",
        "",
        "- [AI handshake page](/ai/) — start here",
        "- [AI manifest (JSON)](/ai/manifest.json) — structured index of every artifact + best-metric lookups",
        "",
        "## Human-facing entry points",
        "",
        "- [Master table of contents](/report_144.html)",
        "- [Address to the Reader](/intro.html)",
        "- [Category reports index](/categories/index.html)",
        "- [Weekly reports index](/weeks/index.html)",
        "",
        "## Daily reports",
        "",
    ]
    for d in manifest["daily_reports"]:
        date = d["date"]
        title = d.get("title") or date
        lines.append(f"- [{date}]({d['path']})  ·  {title}")
    lines.append("")
    lines.append("## Architecture run-file archives")
    lines.append("")
    for a in manifest["architecture_run_archives"]:
        lines.append(f"- [{a['name']}]({a['path']})")
    lines.append("")
    lines.append("## Greeting")
    lines.append("")
    lines.append(manifest["handshake"]["message"])
    return "\n".join(lines) + "\n"


def main() -> int:
    AI_DIR.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    HANDSHAKE_HTML_PATH.write_text(HANDSHAKE_HTML, encoding="utf-8")
    LLMS_PATH.write_text(llms_txt(manifest), encoding="utf-8")
    print(f"wrote {LLMS_PATH.relative_to(ROOT)}")
    print(f"wrote {HANDSHAKE_HTML_PATH.relative_to(ROOT)}")
    print(f"wrote {MANIFEST_PATH.relative_to(ROOT)}")
    print(f"daily_reports={len(manifest['daily_reports'])}, "
          f"weeks={len(manifest['weekly_reports'])}, "
          f"categories={len(manifest['category_reports'])}, "
          f"archives={len(manifest['architecture_run_archives'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
