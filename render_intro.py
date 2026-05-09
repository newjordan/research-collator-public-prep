#!/usr/bin/env python3
"""Render the public intro letter page."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from render_day import HTML_DIR, OUT_ROOT, preview_asset_src


INTRO_TEMPLATE_STANDARD = "intro-v1.1-palette-stamp"
INTRO_HTML_PATH = HTML_DIR / "intro.html"
INTRO_QMD_DIR = OUT_ROOT / "intro"
INTRO_ART_PATH = Path("assets/intro_summary_panel.png")
INTRO_BR_OVERLAY_PATH = Path("assets/bg_4_br_anchor_overlay.png")
INTRO_CATEGORY_LABELS = {"Experimental", "Neural", "Kernel"}

INTRO_COPY = """From 2026-03-18 to 2026-05-01, this fifty-day record documents a live applied AI research campaign across three technical tracks: novel architecture exploration, competitive neural submissions, and custom-kernel / FA3 performance work.

During this period, the work produced both original experimental architecture ideas and competitive neural submissions. The neural track reached the top of the competition multiple times during the campaign, while the broader research process earned $1,000 in research funding in recognition of performance and daily work quality.

Some ideas and approaches were quickly mirrored by other competitors, which was useful external validation that the work was operating in the right part of the search space. In the end, my best submission was a hybrid variant where my main contribution was a larger vocabulary. My goal was knowledge and progress through daily work.

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


def palette_easter_egg_style() -> str:
    return """
    :root {
      --tone-filter: none;
      --chrome-bg: #050605;
      --chrome-fg: #8b3702;
      --chrome-rule: #8b3702;
      --chrome-bg-soft: #0c0907;
      --wipe-tint: transparent;
      --wipe-r: 0px;
      --wipe-cx: 50%;
      --wipe-cy: 50%;
      --wipe-feather: 8px;
    }
    .intro-toned {
      position: absolute;
      inset: 0;
      filter: var(--tone-filter);
      transition: filter 220ms ease;
    }
    body.palette-nofilter .intro-toned {
      filter: none;
    }
    .stamp-btn {
      position: absolute;
      left: 78%;
      top: 2.5%;
      width: 17%;
      height: 5%;
      z-index: 40;
      margin: 0;
      padding: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      cursor: pointer;
      outline: 0;
    }
    .stamp-btn:focus-visible {
      outline: 1px dashed var(--chrome-fg);
      outline-offset: 2px;
    }
    body.debug .stamp-btn {
      background: rgba(255, 0, 255, 0.12);
      outline: 1px dashed magenta;
    }
    .wipe-overlay {
      position: fixed;
      inset: 0;
      z-index: 60;
      pointer-events: none;
      background-color: var(--wipe-tint);
      mix-blend-mode: color;
      opacity: 0;
      transition: opacity 180ms ease;
      -webkit-mask-image: radial-gradient(circle at var(--wipe-cx) var(--wipe-cy),
        transparent 0,
        transparent calc(var(--wipe-r) - var(--wipe-feather)),
        #000 var(--wipe-r),
        #000 100%);
      mask-image: radial-gradient(circle at var(--wipe-cx) var(--wipe-cy),
        transparent 0,
        transparent calc(var(--wipe-r) - var(--wipe-feather)),
        #000 var(--wipe-r),
        #000 100%);
    }
    .wipe-overlay.is-running {
      opacity: 1;
    }
    .palette-label {
      position: fixed;
      top: 8px;
      left: 8px;
      z-index: 70;
      display: none;
      align-items: center;
      padding: 4px 8px;
      background: var(--chrome-bg);
      color: var(--chrome-fg);
      border: 1px solid var(--chrome-rule);
      font-family: var(--mono);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      pointer-events: none;
    }
    .palette-switcher {
      position: fixed;
      top: 8px;
      right: 8px;
      z-index: 70;
      display: none;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 6px;
      max-width: min(80vw, 720px);
      padding: 6px;
      background: var(--chrome-bg);
      border: 1px solid var(--chrome-rule);
      font-family: var(--mono);
    }
    body.debug .palette-label,
    body.debug .palette-switcher {
      display: flex;
    }
    .palette-switcher span {
      align-self: center;
      padding: 0 4px 0 2px;
      color: var(--chrome-fg);
      font-size: 9px;
      font-weight: 800;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      opacity: 0.7;
    }
    .palette-switcher button {
      padding: 5px 9px;
      background: var(--chrome-bg-soft);
      color: var(--chrome-fg);
      border: 1px solid var(--chrome-rule);
      border-radius: 0;
      font: inherit;
      font-size: 10px;
      font-weight: 800;
      line-height: 1;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      cursor: pointer;
    }
    .palette-switcher button:hover,
    .palette-switcher button:focus-visible,
    .palette-switcher button[aria-pressed="true"] {
      background: var(--chrome-fg);
      color: var(--chrome-bg);
      outline: 0;
    }
    """


def palette_easter_egg_controls() -> str:
    return """
  <div class="palette-label" aria-hidden="true">palette: original</div>
  <nav class="palette-switcher" aria-label="Palette switcher">
    <span>palette</span>
    <button type="button" data-preset="original" aria-pressed="true">Original</button>
    <button type="button" data-preset="phosphor">Phosphor</button>
    <button type="button" data-preset="amber">Amber</button>
    <button type="button" data-preset="cyan">Cyan</button>
    <button type="button" data-preset="magenta">Magenta</button>
    <button type="button" data-preset="grey">Grey</button>
    <button type="button" data-preset="bw">B&amp;W</button>
    <button type="button" data-preset="sepia">Sepia</button>
    <button type="button" data-preset="invert">Invert</button>
    <button type="button" data-preset="bluep">Blueprint</button>
  </nav>
    """


def palette_easter_egg_script(include_stamp: bool = True, include_wipe: bool | None = None) -> str:
    if include_wipe is None:
        include_wipe = include_stamp
    stamp_block = """
  var wipeEl = document.querySelector('.wipe-overlay');
  var wipeRunning = false;
  var WIPE_DURATION_MS = 750;
  var WIPE_OVERSHOOT_PX = 60;

  function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function maxRadiusFrom(cx, cy) {
    var w = window.innerWidth;
    var h = window.innerHeight;
    return Math.max(
      Math.hypot(cx, cy),
      Math.hypot(w - cx, cy),
      Math.hypot(cx, h - cy),
      Math.hypot(w - cx, h - cy)
    );
  }

  function runWipe(cx, cy, oldPaletteName, newPaletteName) {
    if (!wipeEl || wipeRunning) {
      applyPreset(newPaletteName, true);
      return;
    }
    wipeRunning = true;
    var oldPreset = PRESETS[oldPaletteName] || PRESETS.original;
    var targetR = maxRadiusFrom(cx, cy) + WIPE_OVERSHOOT_PX;
    root.style.setProperty('--wipe-tint', oldPreset.chrome.fg);
    root.style.setProperty('--wipe-cx', cx + 'px');
    root.style.setProperty('--wipe-cy', cy + 'px');
    root.style.setProperty('--wipe-r', '0px');
    wipeEl.classList.add('is-running');
    applyPreset(newPaletteName, true);

    var start = performance.now();
    function step(now) {
      var t = Math.min(1, (now - start) / WIPE_DURATION_MS);
      root.style.setProperty('--wipe-r', (easeOutCubic(t) * targetR) + 'px');
      if (t < 1) {
        requestAnimationFrame(step);
      } else {
        wipeEl.classList.remove('is-running');
        setTimeout(function() {
          root.style.setProperty('--wipe-r', '0px');
          wipeRunning = false;
        }, 200);
      }
    }
    requestAnimationFrame(step);
  }

  function cycleFromEvent(event) {
    runWipe(event.clientX, event.clientY, currentPalette, nextPalette(currentPalette));
  }

  Array.prototype.slice.call(document.querySelectorAll('[data-palette-cycle]')).forEach(function(trigger) {
    trigger.addEventListener('click', function(event) {
      event.preventDefault();
      cycleFromEvent(event);
    });
  });

    """ if include_wipe else """
  function cycleFromEvent(event) {
    event.preventDefault();
    applyPreset(nextPalette(currentPalette), true);
  }

  Array.prototype.slice.call(document.querySelectorAll('[data-palette-cycle]')).forEach(function(trigger) {
    trigger.addEventListener('click', cycleFromEvent);
  });

    """
    stamp_block += """
  var stampBtn = document.querySelector('.stamp-btn');
  if (stampBtn) {
    stampBtn.addEventListener('click', function(event) {
      event.preventDefault();
      cycleFromEvent(event);
    });
  }
    """ if include_stamp else ""

    return f"""
<script>
(function() {{
  var PRESETS = {{
    original: {{
      label: 'Original',
      filter: 'none',
      chrome: {{ bg:'#050605', fg:'#8b3702', rule:'#8b3702', bgSoft:'#0c0907' }}
    }},
    phosphor: {{
      label: 'Phosphor Green (CRT)',
      filter: 'grayscale(1) sepia(1) hue-rotate(65deg) saturate(7) brightness(0.95)',
      chrome: {{ bg:'#000800', fg:'#33ff66', rule:'#33ff66', bgSoft:'#031003' }}
    }},
    amber: {{
      label: 'Amber CRT',
      filter: 'grayscale(1) sepia(1) hue-rotate(-12deg) saturate(3.6) brightness(1.05)',
      chrome: {{ bg:'#0a0500', fg:'#ffb000', rule:'#ffb000', bgSoft:'#160c00' }}
    }},
    cyan: {{
      label: 'Cyan Terminal',
      filter: 'grayscale(1) sepia(1) hue-rotate(170deg) saturate(4) brightness(1.0)',
      chrome: {{ bg:'#001218', fg:'#3fe6ff', rule:'#3fe6ff', bgSoft:'#02181f' }}
    }},
    magenta: {{
      label: 'Magenta',
      filter: 'grayscale(1) sepia(1) hue-rotate(255deg) saturate(4) brightness(1.0)',
      chrome: {{ bg:'#150018', fg:'#ff5cd2', rule:'#ff5cd2', bgSoft:'#1d0220' }}
    }},
    grey: {{
      label: 'Grey',
      filter: 'grayscale(1) brightness(1.0) contrast(1.0)',
      chrome: {{ bg:'#0c0c0c', fg:'#cfcfcf', rule:'#cfcfcf', bgSoft:'#161616' }}
    }},
    bw: {{
      label: 'High Contrast B&W',
      filter: 'grayscale(1) contrast(1.6) brightness(1.0)',
      chrome: {{ bg:'#000000', fg:'#ffffff', rule:'#ffffff', bgSoft:'#0a0a0a' }}
    }},
    sepia: {{
      label: 'Sepia',
      filter: 'sepia(1) saturate(1.3) brightness(1.0)',
      chrome: {{ bg:'#1a0f06', fg:'#d8a866', rule:'#d8a866', bgSoft:'#221409' }}
    }},
    invert: {{
      label: 'Inverted',
      filter: 'invert(1) hue-rotate(180deg)',
      chrome: {{ bg:'#f4f4f4', fg:'#1a1a1a', rule:'#1a1a1a', bgSoft:'#e6e6e6' }}
    }},
    bluep: {{
      label: 'Blueprint',
      filter: 'grayscale(1) sepia(1) hue-rotate(195deg) saturate(5) brightness(0.9) contrast(1.15)',
      chrome: {{ bg:'#011024', fg:'#7ec8ff', rule:'#7ec8ff', bgSoft:'#021833' }}
    }}
  }};
  var PALETTE_CYCLE = [
    'original', 'phosphor', 'amber', 'cyan', 'magenta',
    'grey', 'bw', 'sepia', 'invert', 'bluep'
  ];
  var params = new URLSearchParams(window.location.search);
  var root = document.documentElement;
  var buttons = Array.prototype.slice.call(document.querySelectorAll('.palette-switcher button[data-preset]'));
  var labelEl = document.querySelector('.palette-label');
  var noFilter = params.get('nofilter') === '1';
  var currentPalette = 'original';

  if (params.get('debug') === '1') {{
    document.body.classList.add('debug');
  }}
  if (noFilter) {{
    document.body.classList.add('palette-nofilter');
  }}

  function validPalette(name) {{
    return PRESETS[name] ? name : 'original';
  }}

  function applyPreset(name, persist) {{
    name = validPalette(name);
    var p = PRESETS[name];
    root.style.setProperty('--tone-filter', noFilter ? 'none' : p.filter);
    root.style.setProperty('--chrome-bg', p.chrome.bg);
    root.style.setProperty('--chrome-fg', p.chrome.fg);
    root.style.setProperty('--chrome-rule', p.chrome.rule);
    root.style.setProperty('--chrome-bg-soft', p.chrome.bgSoft);
    if (labelEl) labelEl.textContent = 'palette: ' + p.label.toLowerCase();
    buttons.forEach(function(button) {{
      button.setAttribute('aria-pressed', button.dataset.preset === name ? 'true' : 'false');
    }});
    currentPalette = name;
    if (persist !== false) {{
      try {{ localStorage.setItem('palette', name); }} catch (e) {{}}
    }}
  }}

  function nextPalette(name) {{
    var index = PALETTE_CYCLE.indexOf(name);
    return PALETTE_CYCLE[(index < 0 ? 1 : index + 1) % PALETTE_CYCLE.length];
  }}

  buttons.forEach(function(button) {{
    button.addEventListener('click', function() {{
      applyPreset(button.dataset.preset, true);
    }});
  }});

  var initial = 'original';
  try {{
    var saved = localStorage.getItem('palette');
    if (saved && PRESETS[saved]) initial = saved;
  }} catch (e) {{}}
  applyPreset(initial, false);

  window.addEventListener('storage', function(event) {{
    if (event.key === 'palette' && event.newValue && PRESETS[event.newValue]) {{
      applyPreset(event.newValue, false);
    }}
  }});
{stamp_block}
}})();
</script>
"""


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
{palette_easter_egg_style()}
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
      .intro-shell {{ width: 100vw; min-width: 0; }}
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
{palette_easter_egg_controls()}
  <main class="intro-shell" aria-label="Address to the Reader">
    <div class="intro-toned">
      <img class="intro-art" src="{art_uri}" alt="">
      <img class="intro-br-overlay" src="{br_overlay_uri}" alt="">
      <article class="intro-scroll">
        {copy_html}
      </article>
      <div class="intro-scrollbar" aria-hidden="true">
        <div class="intro-scrollbar-thumb"></div>
      </div>
      <nav class="intro-nav" aria-label="Intro navigation">
        <a href="report_144.html">Enter Report</a>
      </nav>
    </div>
    <button class="stamp-btn" type="button" aria-label="Cycle palette via smooth brain stamp"></button>
    <div class="wipe-overlay" aria-hidden="true"></div>
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
{palette_easter_egg_script(include_stamp=True)}
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
