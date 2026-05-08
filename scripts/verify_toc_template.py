#!/usr/bin/env python3
"""Verify table-of-contents report page."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import render_day  # noqa: E402
import render_toc  # noqa: E402


LEAK_RE = re.compile(
    r"CONVERSATION-MINED|conversation_architecture|conversation_arch_event|"
    r"claude_session|codex_session",
    re.IGNORECASE,
)


def _require_clean_bottom(text: str, html_path: Path) -> None:
    if "report-footer" in text or "rf-dotgrid" in text or "body::after" in text:
        raise AssertionError(f"removed footer or bottom treatment leaked back into page: {html_path}")


def _require_home_link(text: str, html_path: Path) -> None:
    if 'class="h1-home" href="index.html" aria-label="Open landing page"' not in text:
        raise AssertionError(f"frostmark is not linked to landing page: {html_path}")


def verify_toc(html_path: Path) -> dict:
    if not html_path.exists():
        raise AssertionError(f"missing TOC html: {html_path}")
    text = html_path.read_text(encoding="utf-8", errors="replace")
    if "TABLE OF CONTENTS" not in text:
        raise AssertionError(f"missing TOC h1 marker: {html_path}")
    _require_clean_bottom(text, html_path)
    _require_home_link(text, html_path)
    if text.count("<h2>") != 2:
        raise AssertionError(f"TOC page must have exactly two h2 sections: {html_path}")
    for heading in (
        "SECTION 1.0 — PUBLICATION MAP",
        "SECTION 2.0 — REPORT INDEX",
    ):
        if heading not in text:
            raise AssertionError(f"missing TOC heading {heading!r}: {html_path}")
    for marker in ("report-header", "day-summary", "test-runs-table"):
        if marker not in text:
            raise AssertionError(f"TOC missing locked visual block {marker!r}: {html_path}")
    if 'class="toc-webloader-page2"' not in text:
        raise AssertionError(f"TOC missing page 2 image above the long loader: {html_path}")
    if "Research corpus page above the table of contents" not in text:
        raise AssertionError(f"TOC missing page 2 image alt marker: {html_path}")
    if not render_toc.TOC_BACKGROUND_PATH.exists():
        raise AssertionError(
            f"missing generated TOC background asset: {render_toc.TOC_BACKGROUND_PATH}"
        )
    if "body.toc-page" not in text or "background-image" not in text:
        raise AssertionError(f"TOC missing generated background styling: {html_path}")
    for href in (
        "cover.html",
        "cumulative.html",
        "categories/index.html",
        "weeks/index.html",
        "2026-03-18.html",
        "2026-05-01.html",
    ):
        if href not in text:
            raise AssertionError(f"TOC missing link {href}: {html_path}")
    frames = re.findall(
        r'<iframe class="toc-reader-frame" src="([^"]+)"[^>]*data-reader-kind="([^"]+)"',
        text,
    )
    if not frames:
        raise AssertionError(f"TOC missing connected endless-scroll frames: {html_path}")
    if 'data-connected-reader="true"' not in text or "CONNECTED SCROLL" not in text:
        raise AssertionError(f"TOC missing connected scroll section: {html_path}")
    if text.count('loading="lazy"') != len(frames):
        raise AssertionError(f"TOC reader frames must all be lazy-loaded: {html_path}")
    if text.count('scrolling="no"') != len(frames):
        raise AssertionError(f"TOC reader frames must not expose default iframe scrollbars: {html_path}")
    if "doc.documentElement.style.overflow = 'hidden'" not in text:
        raise AssertionError(f"TOC reader script must hide iframe viewport overflow: {html_path}")
    if 'src="cover.html"' in text or 'src="toc.html"' in text:
        raise AssertionError(f"TOC must not recursively embed cover or itself: {html_path}")
    daily_links = text.count("open day")
    day_frames = [href for href, kind in frames if kind == "day"]
    if len(day_frames) != daily_links:
        raise AssertionError(
            f"TOC day frame count mismatch: frames={len(day_frames)} open-day-links={daily_links}"
        )
    for required_frame in (
        "cumulative.html",
        "categories/index.html",
        "weeks/index.html",
        "2026-03-18.html",
        "2026-05-01.html",
    ):
        if required_frame not in {href for href, _kind in frames}:
            raise AssertionError(f"TOC connected reader missing frame {required_frame}: {html_path}")
    if "cover_sheet_final" in text:
        raise AssertionError(f"TOC embeds or references the cover sheet asset: {html_path}")
    if "MONTHLY" in text.upper():
        raise AssertionError(f"TOC contains monthly marker: {html_path}")
    if LEAK_RE.search(text):
        raise AssertionError(f"conversation/session material leaked into TOC: {html_path}")
    return {
        "html_path": str(html_path),
        "tables": text.count("<table"),
        "daily_links": daily_links,
        "reader_frames": len(frames),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    render_day._daily_template_style()
    checked = verify_toc(render_toc.TOC_HTML_PATH)
    result = {
        "template_standard": render_toc.TOC_TEMPLATE_STANDARD,
        "daily_template_standard": render_day.DAILY_TEMPLATE_STANDARD,
        "template_style_sha256": render_day.LOCKED_TEMPLATE_STYLE_SHA256,
        "checked": checked,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
