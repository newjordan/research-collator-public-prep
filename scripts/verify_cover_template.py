#!/usr/bin/env python3
"""Verify publication cover page.

The cover is allowed to display the cover sheet. Other publication pages must
not reuse the cover asset as a decorative element.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import render_cover  # noqa: E402
import render_toc  # noqa: E402


def verify_cover(html_path: Path) -> dict:
    if not html_path.exists():
        raise AssertionError(f"missing cover html: {html_path}")
    text = html_path.read_text(encoding="utf-8", errors="replace")
    if "Parameter Golf Campaign Cover" not in text:
        raise AssertionError(f"missing cover title marker: {html_path}")
    if "Research Corpus cover sheet" not in text:
        raise AssertionError(f"missing cover image alt marker: {html_path}")
    if text.count("<img ") != 1:
        raise AssertionError(f"cover page must render exactly one image: {html_path}")
    if '<a href="intro.html">Enter</a>' not in text:
        raise AssertionError(f"cover page must link into the intro page: {html_path}")
    return {
        "html_path": str(html_path),
        "images": text.count("<img "),
    }


def verify_cover_isolated() -> None:
    toc_path = render_toc.TOC_HTML_PATH
    if not toc_path.exists():
        raise AssertionError(f"missing TOC html for isolation check: {toc_path}")
    toc_text = toc_path.read_text(encoding="utf-8", errors="replace")
    if "cover_sheet_final" in toc_text:
        raise AssertionError(f"TOC references cover sheet asset: {toc_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-render", action="store_true",
                        help="verify existing cover page without refreshing it")
    args = parser.parse_args()

    summary = (
        {
            "html_path": str(render_cover.COVER_HTML_PATH),
            "index_path": str(render_cover.INDEX_HTML_PATH),
            "template_standard": render_cover.COVER_TEMPLATE_STANDARD,
        }
        if args.no_render
        else render_cover.render_cover_page()
    )
    checked = verify_cover(Path(summary["html_path"]))
    index_checked = verify_cover(Path(summary["index_path"]))
    verify_cover_isolated()
    result = {
        "template_standard": render_cover.COVER_TEMPLATE_STANDARD,
        "toc_template_standard": render_toc.TOC_TEMPLATE_STANDARD,
        "checked": checked,
        "index_alias": index_checked,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
