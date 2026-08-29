# -*- coding: utf-8 -*-
"""解密驗證兩個完成的 payload 是否嵌入同一份共同摘要。"""
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "fed-watch" / "scripts"))
sys.path.insert(0, str(HERE))

import cross_watch as C
import fwcrypto


def load_page(directory, password):
    manifest = json.loads((directory / "payload-manifest.json").read_text(encoding="utf-8"))
    box = json.loads("".join((directory / name).read_text(encoding="utf-8")
                             for name in manifest["files"]))
    return fwcrypto.decrypt_from_box(box, password)


def main():
    password = os.environ.get("PAGE_PASSWORD", "").strip()
    if not password:
        sys.exit("PAGE_PASSWORD env is required")
    summary = C.validate_summary(
        fwcrypto.load_store(str(ROOT / ".github" / "data" / "cross_watch.enc"), password)
    )
    summary_id = summary["summary_id"]
    state_label = summary["linkage"]["label"]
    result = {"summary_id": summary_id[:12], "state": summary["linkage"]["key"], "pages": {}}

    for name in ("fed-watch", "bond-watch"):
        page = load_page(ROOT / name, password)
        checks = {
            "summary_id": summary_id in page,
            "state_label": state_label in page,
            "fed_link": "../fed-watch/" in page,
            "bond_link": "../bond-watch/" in page,
            "no_placeholders": "{{" not in page,
        }
        if not all(checks.values()):
            raise AssertionError("%s payload failed: %r" % (name, checks))
        result["pages"][name] = {"chars": len(page), **checks}

    for name, live_url, sibling in (
        ("fed-watch", "https://kidd0368.github.io/fed-watch/", "../bond-watch/"),
        ("bond-watch", "https://kidd0368.github.io/bond-watch/", "../fed-watch/"),
    ):
        shell = (ROOT / name / "index.html").read_text(encoding="utf-8")
        if live_url not in shell or sibling not in shell or 'location.protocol==="file:"' not in shell:
            raise AssertionError("%s login shell lacks local-file guidance or sibling link" % name)

    print("[validate] one encrypted summary verified across both pages")


if __name__ == "__main__":
    main()
