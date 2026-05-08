# Art Challenge Handoff — Palette Switcher + Smooth_Brain Stamp + Radial Wipe

Branch: `art/palette-switcher`
Prototype: `workbench/art_challenge/index.html` (force-added; everything else in `workbench/` is gitignored)

This is a prototype-to-master handoff. The agent picking this up should
**read the prototype as the spec** (it has the full working CSS/JS) and
port the behavior into `render_intro.py` and `render_toc.py` rather
than copy the iframe wrapper as-is. The wrapper structure exists only
to demo two pages stacked without touching the master doc.

---

## What it is, in one paragraph

The user's master research doc has page 2 (intro / parchment art on
near-black background) butting up against the TOC (orange field on
black ink). We turned that surface into a palette-switchable artifact:
**10 color presets** (phosphor green CRT, amber, cyan terminal,
magenta, grey, B&W, sepia, inverted, blueprint, original) retone the
entire page including embedded imagery via a single CSS `filter`
chain. The **`smooth_brain` stamp on the parchment is now an active
button** — clicking it advances to the next palette in cycle order and
animates a **radial color wipe** outward from the click point: the
iframe filter snaps to the new palette, but a `mix-blend-mode: color`
overlay tinted with the OLD palette's representative hue covers the
viewport and is masked away in an expanding circle from the click,
giving the effect of new color spreading outward.

---

## User constraints (do not violate)

1. **Do not modify the parchment image** (`assets/intro_summary_panel.png`).
   The stamp button is a positioned overlay computed from
   `.intro-shell`'s rect — image stays untouched.
2. **Do not touch the user's other in-progress files.** The master doc
   currently has uncommitted edits across templates / render scripts /
   handoffs from prior work. Stay scoped to `render_intro.py` and
   `render_toc.py` for this feature; do not bundle unrelated cleanups.
3. **Don't break either page rendered standalone.** Both intro.html
   and toc.html still need to render correctly when opened directly,
   without the wrapper.

---

## Behavior to port

### A. Palette switching (both intro and TOC)

Each preset is a `{ filter, chrome }` pair:

- `filter` — a CSS `filter` chain applied to the page's outermost
  visible content. In the prototype that's the iframe element. In
  master, apply it to `<html>` or `<body>` of each rendered page
  (verify both work; some browsers behave differently with `filter`
  on `<html>`, prefer `<body>`).
- `chrome` — token colors (`bg`, `fg`, `rule`, `bgSoft`) that any
  switcher UI / stamp affordance should use so wrapper UI stays in
  visual register with the active palette.

**Cycle order**:
`original → phosphor → amber → cyan → magenta → grey → bw → sepia → invert → bluep → (loop)`

**Recipe** (reproduce identically across pages):
`grayscale(1) sepia(1) hue-rotate(<deg>) saturate(<n>) brightness(<n>)`
collapses any source colors to monochrome, then re-tints
predictably. This is why the same chain works for both the orange
parchment and the orange-field TOC.

Exact preset filters and chrome tokens: copy verbatim from
`PRESETS = {...}` in `index.html`. Don't redesign — these have been
tuned together with the user.

**Persistence**: `localStorage.setItem("palette", name)` and read on
each page load. The active palette must survive navigation between
intro and TOC.

### B. Smooth_brain stamp button (intro only)

- Lives only on the intro page. The TOC has no parchment, no stamp.
- Invisible button; clickable. `cursor: pointer; background: transparent;
  border: 0; outline: 0;`.
- Geometry tracks `.intro-shell`'s rect (responsive). Current best
  estimate of the stamp's bounding box, as fractions of `.intro-shell`:
  ```
  STAMP_RECT_PCT = { left: 0.78, top: 0.025, width: 0.17, height: 0.05 }
  ```
  These were eyeballed from the parchment art at the time of handoff.
  **Verify in browser** with the debug outline (see below) and tune.
- Recompute on `resize`, parent `scroll`, and the iframe's own
  internal `scroll` (intro-scroll panel inside parchment can scroll).
  In a non-iframe master integration, only `resize` + `scroll` matter.
- Hide when intro is scrolled out of view (master may not need this
  since intro and TOC are separate pages — the stamp belongs to intro
  only).
- Click handler: cycle palette, run radial wipe from `e.clientX, e.clientY`.

**Debug mode**: query param `?debug=1` should toggle a magenta dashed
outline on the hitbox + reveal any in-page palette chip strip used
for tuning. Same convention as the prototype.

### C. Radial color wipe

When the stamp is clicked:

1. Capture click coords `(cx, cy)`.
2. Capture the OLD palette's `chrome.fg` color.
3. **Apply the NEW palette's filter and chrome tokens immediately**
   (this is the swap; without the overlay the page would just snap).
4. Make the wipe overlay visible:
   - `position: fixed; inset: 0;`
   - `pointer-events: none; z-index: 30;`
   - `background-color: <OLD chrome.fg>;`
   - `mix-blend-mode: color;`
   - `-webkit-mask-image / mask-image: radial-gradient(circle at <cx> <cy>,
     transparent 0, transparent calc(var(--wipe-r) - 8px), #000 var(--wipe-r), #000 100%);`
5. Animate `--wipe-r` from `0px` to
   `maxRadiusFromClick(cx, cy) + 60` over ~750ms with easeOutCubic
   (`1 - (1-t)^3`). Use rAF; CSS custom properties don't interpolate
   without `@property` registration.
6. On animation end, hide the overlay and reset `--wipe-r` to 0.

The 8px feather band at the mask edge is the **slot for a future
dither effect** (SVG turbulence + threshold). It is intentionally a
plain feather right now per the user's request to nail motion first
and layer dither after. Do not add dither in this pass.

### D. Hidden chrome by default

In normal view, no chips / no labels — only the stamp is interactive.
A query-string `?debug=1` should reveal the palette chip strip and a
small status label, both for tuning and for users who want a direct
palette picker. Same gesture as the prototype.

---

## Integration plan (recommended)

The iframe wrapper is a demo scaffold — do not ship it. Instead:

1. **`render_intro.py`** — bake into the generated intro.html:
   - Inline `<style>` block: stamp button + wipe overlay CSS + chrome
     token CSS variables (already present, just route them through
     the palette system).
   - Inline `<script>` block at end of body: `PRESETS` table,
     `applyPreset()`, stamp layout + click handler, wipe runner.
   - On script init: read `localStorage["palette"]` (default
     `"original"`) and apply.
   - Add `<button class="stamp-btn">` and `<div class="wipe-overlay">`
     elements inside `.intro-shell` (or as siblings of `<main>`,
     positioned fixed).
   - Apply the active filter to the iframe's content body via the
     `--tone-filter` CSS variable mechanism already in the prototype.

2. **`render_toc.py`** — bake a thinner version:
   - Same `PRESETS` table (extract to a shared snippet if both
     scripts get it; otherwise duplicate — it's small and stable).
   - Same `applyPreset()` for the filter + chrome tokens.
   - Read `localStorage["palette"]` on load.
   - **No** stamp button, **no** wipe overlay (TOC has no stamp).
   - The transition the user sees when navigating intro → TOC is just
     the loaded TOC already in the right palette; no animation needed
     here.

3. **Verify chrome integration**: the TOC currently uses `--bg`,
   `--ink`, `--rule-hi` etc. Decide whether to map those onto the
   palette `chrome` tokens, or keep TOC's existing tokens fixed and
   only retone via the master `filter`. The simpler and more
   faithful-to-original choice is the latter — let the `filter`
   chain do all the work, leave TOC's source colors alone.

4. **Smoke test**:
   - Load intro standalone → original palette → click stamp →
     phosphor wipes outward from stamp → click stamp → amber wipes
     outward → ... → cycles back to original.
   - Refresh intro → palette persists.
   - Navigate to TOC → TOC rendered in same palette.
   - Refresh TOC → palette persists.
   - Open with `?debug=1` → chip strip + stamp outline visible.
   - Verify all 10 presets retone the embedded base64 art (the
     parchment) correctly, not just text.

---

## Known issues at handoff

1. **Stamp click reported as non-interactive** in the prototype
   wrapper as of last test (post-fix to use poll-until-shell-exists
   pattern). Cause not yet confirmed. Possible suspects, in order of
   likelihood:
   - Shell lookup still racing past load — verify `getIntroShell()`
     returns non-null after `waitForShellThen()`.
   - `position: fixed` button stacking weirdness against the iframe
     in some browsers — try wrapping in a `position: relative;
     z-index: 40` parent.
   - Click-target being clipped by an ancestor with `overflow:
     hidden`. Body has none currently; verify in master.
   When porting to master, the iframe layer goes away, which removes
   most of the suspect surface — try the integration first, then
   debug only if it reproduces.

2. **STAMP_RECT_PCT coordinates are eyeballed** from the parchment
   PNG. In master, verify against the live render with `?debug=1`
   and adjust. The geometry is responsive (scales with `.intro-shell`),
   so the percentages, once correct, should hold across viewport
   sizes.

3. **`mix-blend-mode: color` through iframe boundaries** has had
   browser-version inconsistencies historically. In master we apply
   the overlay over the page itself, not over an iframe, so this
   stops being a concern.

---

## File map

```
workbench/art_challenge/
├── README.md      ← this file
├── index.html     ← the spec — read this for exact CSS/JS to port
├── intro.html     ← gitignored prototype copy of output/preview/intro.html
└── toc.html       ← gitignored prototype copy of output/preview/toc.html
```

Only `README.md` and `index.html` are committed on the
`art/palette-switcher` branch. The intro/toc copies were used for
local iframe rendering and are reproducible from `output/preview/`.

---

## Contact context

User's working day, 2026-05-08. Earlier in this session we built the
two-page wrapper (commit `4161985`), then tried an ambient dither
overlay (rolled back, will revisit), then added the stamp + wipe.
The user asked us to package this up before integrating, so they
could review the design once more and have a separate agent do the
master-doc integration with fresh eyes.
