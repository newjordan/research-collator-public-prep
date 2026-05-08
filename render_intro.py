#!/usr/bin/env python3
"""Render the public intro letter page."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from render_day import HTML_DIR, OUT_ROOT, preview_asset_src


INTRO_TEMPLATE_STANDARD = "intro-v1.0-scroll-panel"
INTRO_HTML_PATH = HTML_DIR / "intro.html"
INTRO_QMD_DIR = OUT_ROOT / "intro"
INTRO_ART_PATH = Path("assets/intro_summary_panel.png")
INTRO_BR_OVERLAY_PATH = Path("assets/bg_4_br_anchor_overlay.png")
INTRO_CATEGORY_LABELS = {"Experimental", "Neural", "Kernel"}

INTRO_COPY = """From 2026-03-18 to 2026-05-01, this fifty-day record documents a live applied AI research campaign across three technical tracks: novel architecture exploration, competitive neural submissions, and custom-kernel / FA3 performance work.

During this period, the work produced both original experimental architecture ideas and competitive neural submissions. The neural track reached the top of the competition multiple times during the campaign, while the broader research process earned $1,000 in research funding in recognition of performance and daily work quality.

Some ideas and approaches were quickly mirrored by other competitors, which was useful external validation that the work was operating in the right part of the search space.

The work was organized into three categories:

Experimental
Novel architecture experiments intended to explore concepts, generate insight, or test unusual ideas. These included recursive layered transformer concepts, wildcards, megakernel-style ideas, and other theoretical or unconventional designs. Not every experiment was expected to match SOTA; the goal was to test whether the idea exposed something useful.

Neural
Competitive architectures aimed at the highest level of the contest using bpb / score-based evaluation. This track performed strongly, including several jumps into first place during a fast-moving leaderboard environment where competitors were constantly leapfrogging each other.

Kernel
Custom-kernel and FA3-related performance work focused on GPU behavior, hardware-specific results, performance constraints, and submission viability.

The record includes accessible run files, test results, and decision trails showing what was tried, what failed, what was preserved, and why.

The claim is that this kind of research engineering can be repeated and expanded upon in novel directions: operating inside an underdefined problem, under deadline pressure, while producing results that survive inspection.

This work is a signal for people building toward deeper systems: world models, novel architectures, simulation, compression, visual reasoning, and new forms of intelligence that can perceive, model, and generate richer realities. The long-term interest is not limited to solving narrow benchmarks, but to pushing the edge of what computational systems can become — especially where research, engineering, art, and world-building begin to converge.

A twenty-year background in 2D/3D game development also informs the work: systems thinking, optimization, geometry, sculpting, visual reasoning, tooling, debugging, and building complex interactive systems under constraints. As AI systems become more capable and more multimodal, that background becomes increasingly relevant.

The goal is simple: to find like-minded humans to collaborate, dream, and build together."""


def intro_copy_html(text: str) -> str:
    blocks = [block.strip("\n") for block in text.split("\n\n")]
    html_blocks: list[str] = []
    text_blocks = [block for block in blocks if block]
    for index, block in enumerate(text_blocks):
        if not block:
            continue
        if block.startswith("- "):
            items = [
                f"<li>{html.escape(line[2:])}</li>"
                for line in block.splitlines()
                if line.startswith("- ")
            ]
            html_blocks.append("<ul>\n" + "\n".join(items) + "\n</ul>")
        elif "\n" in block and block.splitlines()[0] in INTRO_CATEGORY_LABELS:
            lines = block.splitlines()
            title = html.escape(lines[0])
            body = html.escape("\n".join(lines[1:])).replace(chr(10), "<br>")
            html_blocks.append(
                '<section class="intro-category">'
                f'<div class="intro-category-title">{title}</div>'
                f'<p>{body}</p>'
                '</section>'
            )
        else:
            classes = []
            if index == 0:
                classes.append("intro-lede")
            if index == len(text_blocks) - 1:
                classes.append("intro-close")
            class_attr = f' class="{" ".join(classes)}"' if classes else ""
            html_blocks.append(
                f"<p{class_attr}>{html.escape(block).replace(chr(10), '<br>')}</p>"
            )
    return "\n".join(html_blocks)


def render_intro_page() -> dict:
    if not INTRO_ART_PATH.exists():
        raise SystemExit(f"missing intro artwork: {INTRO_ART_PATH}")
    if not INTRO_BR_OVERLAY_PATH.exists():
        raise SystemExit(f"missing intro bottom-right overlay: {INTRO_BR_OVERLAY_PATH}")

    HTML_DIR.mkdir(parents=True, exist_ok=True)
    INTRO_QMD_DIR.mkdir(parents=True, exist_ok=True)
    art_uri = preview_asset_src(INTRO_ART_PATH)
    br_overlay_uri = preview_asset_src(INTRO_BR_OVERLAY_PATH)
    copy_html = intro_copy_html(INTRO_COPY)

    page = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Address to the Reader</title>
  <style>
    :root {{
      --page-bg: #050605;
      --panel-bg: #050302;
      --orange: #8b3702;
      --orange-hi: #8b3702;
      --muted: #8c3b10;
      --mono: "Berkeley Mono", "JetBrains Mono", "IBM Plex Mono",
              ui-monospace, "SF Mono", Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ min-height: 100%; margin: 0; background: var(--page-bg); }}
    body {{
      display: grid;
      place-items: center;
      padding: clamp(10px, 1.8vw, 24px);
      font-family: var(--mono);
      color: var(--orange);
    }}
    .intro-shell {{
      position: relative;
      width: min(100%, 980px);
      aspect-ratio: 1053 / 1494;
      background: var(--page-bg);
    }}
    body.intro-embed {{
      min-height: 100vh;
      padding: 0;
      place-items: start center;
      overflow: hidden;
    }}
    body.intro-embed .intro-shell {{
      width: 100vw;
      max-width: none;
    }}
    .intro-art {{
      position: absolute;
      inset: 0;
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
      user-select: none;
      pointer-events: none;
    }}
    .intro-br-overlay {{
      position: absolute;
      right: 0;
      bottom: 0;
      width: 57.65%;
      height: auto;
      display: block;
      user-select: none;
      pointer-events: none;
      z-index: 5;
    }}
    .intro-scroll {{
      position: absolute;
      left: 17.85%;
      top: 19.7%;
      width: 74.5%;
      height: 58.0%;
      overflow-y: auto;
      padding: clamp(18px, 2.4vw, 36px) clamp(34px, 4vw, 58px) clamp(18px, 2.4vw, 36px) clamp(22px, 3vw, 44px);
      color: var(--orange);
      background:
        linear-gradient(90deg, rgba(139,55,2,0.46) 0 1px, transparent 1px) left top / 100% 100% no-repeat,
        rgba(5,3,2,0.04);
      border-top: 1px solid rgba(139,55,2,0.42);
      border-bottom: 1px solid rgba(139,55,2,0.34);
      scrollbar-width: none;
      -ms-overflow-style: none;
      z-index: 2;
    }}
    .intro-scroll::-webkit-scrollbar {{
      width: 0;
      height: 0;
    }}
    .intro-scrollbar {{
      position: absolute;
      top: 20.9%;
      right: 8.95%;
      width: 12px;
      height: 55.6%;
      background: #050302;
      border-left: 1px solid rgba(139,55,2,0.72);
      border-right: 1px solid rgba(139,55,2,0.32);
      z-index: 3;
    }}
    .intro-scrollbar-thumb {{
      position: absolute;
      left: 2px;
      top: 0;
      width: 8px;
      height: 36px;
      background: var(--orange);
      border: 1px solid #050302;
    }}
    .intro-scroll h1 {{
      margin: 0 0 16px;
      color: var(--orange-hi);
      font-size: clamp(15px, 1.7vw, 22px);
      line-height: 1.18;
      font-weight: 800;
      letter-spacing: 0.02em;
      text-transform: none;
    }}
    .intro-scroll p {{
      margin: 0 0 14px;
      max-width: 68ch;
      font-size: clamp(10.75px, 1.04vw, 14px);
      line-height: 1.56;
      font-weight: 700;
    }}
    .intro-scroll .intro-lede {{
      margin-bottom: 18px;
      padding-bottom: 14px;
      border-bottom: 1px solid rgba(139,55,2,0.42);
      color: #9c4306;
      font-size: clamp(11.5px, 1.14vw, 15px);
      line-height: 1.5;
      font-weight: 850;
    }}
    .intro-scroll .intro-category {{
      margin: 16px 0 17px;
      max-width: 68ch;
      padding: 9px 11px 10px;
      border-top: 1px solid rgba(139,55,2,0.54);
      border-bottom: 1px solid rgba(139,55,2,0.42);
      border-left: 1px solid rgba(139,55,2,0.34);
      border-right: 1px solid rgba(139,55,2,0.18);
      background:
        linear-gradient(90deg, rgba(139,55,2,0.44) 0 3px, transparent 3px),
        linear-gradient(180deg, rgba(139,55,2,0.18) 0 1px, transparent 1px),
        rgba(8,4,2,0.24);
    }}
    .intro-scroll .intro-category-title {{
      display: block;
      width: fit-content;
      margin: 0 0 7px;
      padding: 2px 8px 3px;
      color: #050302;
      background: #8b3702;
      border: 1px solid #8b3702;
      font-size: clamp(9px, 0.88vw, 11px);
      line-height: 1.1;
      font-weight: 950;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .intro-scroll .intro-category p {{
      margin-bottom: 0;
      max-width: none;
      font-size: clamp(10.25px, 0.98vw, 13.2px);
      line-height: 1.48;
    }}
    .intro-scroll .intro-close {{
      margin-top: 17px;
      padding: 10px 12px;
      border-top: 1px solid rgba(139,55,2,0.52);
      border-bottom: 1px solid rgba(139,55,2,0.52);
      color: #9c4306;
      font-weight: 850;
    }}
    .intro-scroll a {{
      color: var(--orange-hi);
      text-decoration: none;
      border-bottom: 1px solid rgba(223,109,29,0.75);
    }}
    .intro-nav {{
      position: absolute;
      left: 18.3%;
      right: 8.3%;
      bottom: 4.2%;
      display: flex;
      justify-content: flex-end;
      gap: 12px;
      align-items: center;
      font-size: clamp(9px, 0.95vw, 12px);
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .intro-nav a {{
      color: #0b0704;
      background: rgba(184,78,18,0.72);
      border: 1px solid #0b0704;
      padding: 8px 10px;
      text-decoration: none;
      font-weight: 900;
    }}
    @media (max-width: 720px) {{
      body {{ padding: 0; place-items: start center; }}
      .intro-shell {{ width: 100vw; min-width: 360px; }}
      .intro-scroll {{
        padding: 14px 16px;
      }}
      .intro-scrollbar {{
        right: 8.4%;
      }}
      .intro-nav {{
        bottom: 3.8%;
        flex-direction: column;
        align-items: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <script>
    if (new URLSearchParams(window.location.search).get('embed') === '1') {{
      document.body.classList.add('intro-embed');
    }}
  </script>
  <main class="intro-shell" aria-label="Address to the Reader">
    <img class="intro-art" src="{art_uri}" alt="">
    <img class="intro-br-overlay" src="{br_overlay_uri}" alt="">
    <article class="intro-scroll">
      {copy_html}
    </article>
    <div class="intro-scrollbar" aria-hidden="true">
      <div class="intro-scrollbar-thumb"></div>
    </div>
    <nav class="intro-nav" aria-label="Intro navigation">
      <a href="toc.html">Enter Report</a>
    </nav>
  </main>
  <script>
    (function() {{
      var scroller = document.querySelector('.intro-scroll');
      var track = document.querySelector('.intro-scrollbar');
      var thumb = document.querySelector('.intro-scrollbar-thumb');
      if (!scroller || !track || !thumb) return;

      function syncThumb() {{
        var maxScroll = scroller.scrollHeight - scroller.clientHeight;
        var trackHeight = track.clientHeight;
        var ratio = scroller.clientHeight / scroller.scrollHeight;
        var thumbHeight = Math.max(36, Math.floor(trackHeight * ratio));
        var maxTop = trackHeight - thumbHeight;
        var top = maxScroll > 0 ? Math.floor((scroller.scrollTop / maxScroll) * maxTop) : 0;
        thumb.style.height = thumbHeight + 'px';
        thumb.style.transform = 'translateY(' + top + 'px)';
      }}

      scroller.addEventListener('scroll', syncThumb, {{ passive: true }});
      window.addEventListener('resize', syncThumb);
      syncThumb();
    }})();
  </script>
</body>
</html>
"""
    INTRO_HTML_PATH.write_text(page, encoding="utf-8")
    qmd_path = INTRO_QMD_DIR / "intro.qmd"
    qmd_path.write_text("# Address to the Reader\n\n" + INTRO_COPY + "\n", encoding="utf-8")
    return {
        "html_path": str(INTRO_HTML_PATH),
        "qmd_path": str(qmd_path),
        "art_path": str(INTRO_ART_PATH),
        "template_standard": INTRO_TEMPLATE_STANDARD,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(json.dumps(render_intro_page(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
