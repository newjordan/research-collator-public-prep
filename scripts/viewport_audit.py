#!/usr/bin/env python3
"""Check generated report pages at mobile and desktop viewports."""

from __future__ import annotations

import os
from playwright.sync_api import sync_playwright


BASE = os.environ.get("PREVIEW_BASE", "http://127.0.0.1:8777")
PAGES = [
    "/report_144.html",
    "/intro.html",
    "/2026-05-01.html",
    "/weeks/index.html",
    "/categories/index.html",
]
VIEWPORTS = [
    ("mobile", 375, 812),
    ("desktop", 1440, 1000),
]


def main() -> None:
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, width, height in VIEWPORTS:
            page = browser.new_page(viewport={"width": width, "height": height})
            for path in PAGES:
                page.goto(f"{BASE}{path}", wait_until="load")
                result = page.evaluate(
                    """() => {
                      const root = document.documentElement;
                      const body = document.body;
                      const meta = document.querySelector('meta[name="viewport"]');
                      return {
                        meta: meta ? meta.getAttribute('content') : '',
                        rootOverflow: root.scrollWidth - root.clientWidth,
                        bodyOverflow: body ? body.scrollWidth - body.clientWidth : 0,
                        rootClientWidth: root.clientWidth,
                        rootScrollWidth: root.scrollWidth,
                        bodyClientWidth: body ? body.clientWidth : 0,
                        bodyScrollWidth: body ? body.scrollWidth : 0,
                      };
                    }"""
                )
                overflow = result["rootOverflow"]
                print(
                    f"{label:7} {path:24} "
                    f"meta={bool(result['meta'])} overflow={overflow}"
                )
                if "width=device-width" not in result["meta"]:
                    failures.append(f"{label} {path}: missing viewport metadata")
                if overflow > 2:
                    failures.append(
                        f"{label} {path}: page horizontal overflow {overflow}px "
                        f"(root {result['rootScrollWidth']}/{result['rootClientWidth']}, "
                        f"body {result['bodyScrollWidth']}/{result['bodyClientWidth']})"
                    )
            page.close()
        browser.close()
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
