#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Idempotently load review-semantics.js from the Industry Intelligence Hub page."""
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parents[1]
APP_HTML = HUB_ROOT / "app.html"
TAG = '  <script src="review-semantics.js?v=1.0.0" defer></script>'


def main() -> int:
    text = APP_HTML.read_text(encoding="utf-8")
    if TAG in text:
        print("review semantics script already installed")
        return 0
    anchor = '  <script src="completion-gate.js?v=1.0.0" defer></script>'
    if anchor in text:
        text = text.replace(anchor, f"{anchor}\n{TAG}", 1)
    elif "</body>" in text:
        text = text.replace("</body>", f"{TAG}\n</body>", 1)
    else:
        raise RuntimeError("app.html has no supported script anchor or </body>")
    APP_HTML.write_text(text, encoding="utf-8")
    print("installed review semantics script")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
