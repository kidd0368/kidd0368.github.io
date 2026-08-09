# -*- coding: utf-8 -*-
"""把 Claude 每日排程寫入的 annotations.enc（分類＋推演）合併進 store.enc。
annotations 格式（同一套 AES-GCM box）：
{"classifications": {"<quote_id>": {"cls": "hawk|dove|neutral", "w": 1.0}},
 "commentary": [{"date": "YYYY-MM-DD", "text": "...", "author": "claude"}]}
找不到檔案或解不開就靜默跳過，不讓管線失敗。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fwcrypto

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(BASE, "data", "store.enc")
ANN = os.path.join(BASE, "data", "annotations.enc")


def main():
    password = os.environ.get("PAGE_PASSWORD", "").strip()
    if not password:
        sys.exit("PAGE_PASSWORD env is required")
    if not os.path.exists(ANN):
        print("[merge] no annotations, skip")
        return
    try:
        with open(ANN, encoding="utf-8") as f:
            box = json.load(f)
        ann = json.loads(fwcrypto.decrypt_from_box(box, password))
    except Exception as e:
        print("[merge] annotations unreadable, skip:", repr(e))
        return

    store = fwcrypto.load_store(STORE, password)
    cls_map = ann.get("classifications", {}) or {}
    applied = 0
    for q in store["quotes"]:
        c = cls_map.get(q["id"])
        if c and c.get("cls") in ("hawk", "dove", "neutral"):
            if q.get("cls") != c["cls"] or q.get("w") != c.get("w", 1.0):
                q["cls"] = c["cls"]
                q["w"] = float(c.get("w", 1.0))
                applied += 1

    added = 0
    existing_dates = {c["date"]: i for i, c in enumerate(store["commentary"])}
    for c in ann.get("commentary", []) or []:
        if not c.get("date") or not c.get("text"):
            continue
        entry = {"date": c["date"], "text": c["text"][:6000], "author": c.get("author", "claude")}
        if c["date"] in existing_dates:
            store["commentary"][existing_dates[c["date"]]] = entry
        else:
            store["commentary"].append(entry)
            added += 1
    store["commentary"] = store["commentary"][-60:]

    fwcrypto.save_store(STORE, store, password)
    print("[merge] classifications applied=%d commentary added=%d" % (applied, added))


if __name__ == "__main__":
    main()
