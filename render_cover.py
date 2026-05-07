#!/usr/bin/env python3
"""Render the publication cover page.

The cover sheet appears here only. It is the first page of the static site,
not a decorative asset for the TOC or report pages.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from render_day import HTML_DIR, OUT_ROOT, RESEARCH_END_DATE, RESEARCH_START_DATE


COVER_TEMPLATE_STANDARD = "cover-v1.0-first-page"
COVER_HTML_PATH = HTML_DIR / "cover.html"
INDEX_HTML_PATH = HTML_DIR / "index.html"
COVER_QMD_DIR = OUT_ROOT / "cover"
COVER_CANDIDATES = (
    Path("assets/cover_sheet_final.jpeg"),
    Path("assets/cover_sheet_final.jpg"),
    Path("assets/cover_sheet_final.png"),
)


def image_data_uri(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")


def find_cover_image() -> Path:
    for path in COVER_CANDIDATES:
        if path.exists():
            return path
    raise SystemExit(
        "missing cover image; expected one of: "
        + ", ".join(str(p) for p in COVER_CANDIDATES)
    )


def render_cover_page() -> dict:
    cover_path = find_cover_image()
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    COVER_QMD_DIR.mkdir(parents=True, exist_ok=True)
    cover_uri = image_data_uri(cover_path)
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Parameter Golf Campaign Cover</title>
  <style>
    :root {{
      --bg: #050605;
      --ink: #f4f0e9;
      --muted: #89380e;
      --accent: #89380e;
      --rule: rgba(5,6,5,0.85);
      --mono: "Berkeley Mono", "JetBrains Mono", "IBM Plex Mono",
              ui-monospace, "SF Mono", Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ min-height: 100%; margin: 0; background: var(--bg); }}
    body {{
      font-family: var(--mono);
      color: var(--ink);
      display: grid;
      place-items: center;
      padding: clamp(12px, 2.2vw, 28px);
    }}
    .cover-shell {{
      width: min(100%, 920px);
      min-height: calc(100vh - clamp(24px, 4.4vw, 56px));
      display: grid;
      grid-template-rows: 1fr auto;
      gap: 14px;
      align-items: center;
    }}
    .cover-frame {{
      width: 100%;
      display: grid;
      place-items: center;
    }}
    .cover-frame img {{
      display: block;
      max-width: 100%;
      max-height: calc(100vh - 92px);
      width: auto;
      height: auto;
      border: 1px solid var(--rule);
      box-shadow: 0 0 0 1px rgba(5,6,5,0.65), 0 28px 90px rgba(5,6,5,0.78);
      background: #050605;
    }}
    .enter-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 18px;
      width: 100%;
      color: var(--muted);
      font-size: 11px;
      letter-spacing: 0.13em;
      text-transform: uppercase;
      padding: 8px 2px 0;
    }}
    .enter-row a {{
      color: var(--ink);
      text-decoration: none;
      border: 1px solid var(--rule);
      padding: 9px 12px;
      background: rgba(5,6,5,0.10);
    }}
    .enter-row a:hover {{
      border-color: var(--accent);
      color: #f4f0e9;
    }}
    @media (max-width: 640px) {{
      .enter-row {{ flex-direction: column; align-items: stretch; }}
      .enter-row a {{ text-align: center; }}
    }}
  </style>
</head>
<body>
  <main class="cover-shell">
    <div class="cover-frame">
      <img src="{cover_uri}" alt="Research Corpus cover sheet">
    </div>
    <div class="enter-row">
      <span>{RESEARCH_START_DATE} / {RESEARCH_END_DATE}</span>
      <a href="toc.html">Enter Table of Contents</a>
    </div>
  </main>
</body>
</html>
"""
    COVER_HTML_PATH.write_text(html, encoding="utf-8")
    INDEX_HTML_PATH.write_text(html, encoding="utf-8")
    qmd_path = COVER_QMD_DIR / "cover.qmd"
    qmd_path.write_text(
        "\n".join([
            "# Parameter Golf Campaign Cover",
            "",
            f"Cover image: `{cover_path}`",
            "",
            "[Enter Table of Contents](../preview/toc.html)",
            "",
        ]),
        encoding="utf-8",
    )
    return {
        "html_path": str(COVER_HTML_PATH),
        "index_path": str(INDEX_HTML_PATH),
        "qmd_path": str(qmd_path),
        "cover_path": str(cover_path),
        "template_standard": COVER_TEMPLATE_STANDARD,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(json.dumps(render_cover_page(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
