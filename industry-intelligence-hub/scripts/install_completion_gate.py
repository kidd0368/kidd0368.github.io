#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Idempotently install the completion-gate browser script into app.html."""
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parents[1]
APP_HTML = HUB_ROOT / "app.html"
SCRIPT_TAG = '  <script src="completion-gate.js?v=1.0.0" defer></script>\n'
APP_TAG = '  <script src="app.js" defer></script>\n'


def main() -> int:
    text = APP_HTML.read_text(encoding="utf-8")
    if text.count(SCRIPT_TAG.strip()) > 1:
        raise SystemExit("completion-gate script tag appears more than once")
    if SCRIPT_TAG.strip() in text:
        print("completion-gate script already installed")
        return 0
    if APP_TAG not in text:
        raise SystemExit("app.js script tag not found; refusing unsafe patch")
    APP_HTML.write_text(text.replace(APP_TAG, APP_TAG + SCRIPT_TAG, 1), encoding="utf-8")
    print("completion-gate script installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
