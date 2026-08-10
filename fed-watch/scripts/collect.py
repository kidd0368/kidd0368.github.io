# -*- coding: utf-8 -*-
"""FED 升降息機率儀表板：資料收集器。
來源：Kalshi(公開API) / Polymarket Gamma(公開API) / FRED fredgraph.csv(免金鑰) / 金十MCP(需token)。
所有結果寫入加密資料庫 fed-watch/data/store.enc。
用法：PAGE_PASSWORD=... [JIN10_MCP_TOKEN=...] python collect.py
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fwcrypto

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # fed-watch/
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
STORE_PATH = os.path.join(BASE, "data", "store.enc")
UA = {"User-Agent": "fed-watch-dashboard/1.0 (personal research)"}
BUCKETS = CFG["buckets"]


def log(*a):
    print("[collect]", *a, flush=True)


def norm(d):
    """把 bucket dict 正規化成總和 1；缺的補 0。"""
    out = {b: max(0.0, float(d.get(b, 0.0))) for b in BUCKETS}
    s = sum(out.values())
    if s <= 0:
        return None
    return {b: round(v / s, 4) for b, v in out.items()}


# ---------------- Kalshi ----------------

def fetch_kalshi():
    out = {}
    for m in CFG["meetings"]:
        try:
            r = requests.get(
                "https://api.elections.kalshi.com/trade-api/v2/markets",
                params={"event_ticker": m["kalshi_event"]}, headers=UA, timeout=25)
            r.raise_for_status()
            probs = {}
            for mk in r.json().get("markets", []):
                strike = mk.get("custom_strike", {})
                last = mk.get("last_price_dollars")
                bid, ask = mk.get("yes_bid_dollars"), mk.get("yes_ask_dollars")
                if bid is not None and ask is not None and float(ask) > 0:
                    px = (float(bid) + float(ask)) / 2.0
                elif last is not None:
                    px = float(last)
                else:
                    continue
                if "Hike" in strike:
                    v = strike["Hike"]
                    probs["hold" if v == "0" else ("hike25" if v == "25" else "hike50p")] = px
                elif "Cut" in strike:
                    v = strike["Cut"]
                    probs["cut25" if v == "25" else "cut50p"] = px
            n = norm(probs)
            if n:
                out[m["key"]] = n
            time.sleep(0.5)
        except Exception as e:
            log("kalshi", m["key"], "failed:", repr(e))
    return out


# ---------------- Polymarket ----------------

PM_MAP = [
    (re.compile(r"50\+?\s*bps?\s*(rate\s*)?decrease|decrease.*50", re.I), "cut50p"),
    (re.compile(r"25\s*bps?\s*(rate\s*)?decrease|decrease.*25", re.I), "cut25"),
    (re.compile(r"no\s*change|unchanged|maintain", re.I), "hold"),
    (re.compile(r"50\+?\s*bps?\s*(rate\s*)?increase|increase.*50", re.I), "hike50p"),
    (re.compile(r"25\s*bps?\s*(rate\s*)?increase|increase.*25", re.I), "hike25"),
]


def _pm_bucket(title):
    for rx, b in PM_MAP:
        if rx.search(title or ""):
            return b
    return None


def fetch_polymarket():
    out = {}
    try:
        r = requests.get("https://gamma-api.polymarket.com/events",
                         params={"closed": "false", "limit": 100, "tag_slug": "fed-rates"},
                         headers=UA, timeout=25)
        r.raise_for_status()
        events = r.json()
        for m in CFG["meetings"]:
            best = None
            for ev in events:
                t = ((ev.get("title") or "") + " " + (ev.get("slug") or "")).lower()
                if "fed" in t and m["pm_month"] in t and (m["pm_year"] in t or True):
                    best = ev
                    if m["pm_year"] in t:
                        break
            if not best:
                continue
            probs = {}
            for mk in best.get("markets", []):
                title = mk.get("groupItemTitle") or mk.get("question") or ""
                b = _pm_bucket(title)
                if not b:
                    continue
                try:
                    prices = mk.get("outcomePrices")
                    if isinstance(prices, str):
                        prices = json.loads(prices)
                    px = float(prices[0])
                except Exception:
                    continue
                probs[b] = probs.get(b, 0.0) + px
            n = norm(probs)
            if n:
                out[m["key"]] = n
    except Exception as e:
        log("polymarket failed:", repr(e))
    return out


# ---------------- FRED ----------------

def _fred_csv(series):
    key = os.environ.get("FRED_API_KEY", "").strip()
    if key:
        # 官方 API（有 key 就走這條，雲端 IP 不會被擋）
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": series, "api_key": key, "file_type": "json"},
                         headers=UA, timeout=25)
        r.raise_for_status()
        rows = []
        for o in r.json().get("observations", []):
            v = o.get("value")
            if v not in (".", "", None):
                try:
                    rows.append((o["date"], float(v)))
                except ValueError:
                    pass
        return rows
    # 無 key 退回 fredgraph.csv（雲端 IP 可能被限流，timeout 縮短避免拖時間）
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                     params={"id": series}, headers=UA, timeout=12)
    r.raise_for_status()
    rows = []
    for line in r.text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 2 and parts[1].strip() not in (".", ""):
            try:
                rows.append((parts[0].strip(), float(parts[1])))
            except ValueError:
                pass
    return rows


def fetch_fred():
    macro = {}
    hist = {}
    for sid, meta in CFG["fred_series"].items():
        try:
            rows = _fred_csv(sid)
            if not rows:
                continue
            date, val = rows[-1]
            m = {"name": meta["name"], "date": date, "value": round(val, 3)}
            calc = meta["calc"]
            if "yoy" in calc and len(rows) >= 13:
                m["yoy"] = round((rows[-1][1] / rows[-13][1] - 1) * 100, 2)
                hist[sid + "_yoy"] = [[d[:7], round((rows[i][1] / rows[i - 12][1] - 1) * 100, 2)]
                                      for i, (d, _) in enumerate(rows) if i >= 12][-36:]
            if "m3ann" in calc and len(rows) >= 4:
                m["m3ann"] = round(((rows[-1][1] / rows[-4][1]) ** 4 - 1) * 100, 2)
            if "chg3m" in calc and len(rows) >= 4:
                m["chg3m"] = round(rows[-1][1] - rows[-4][1], 2)
            if "diff" in calc and len(rows) >= 2:
                m["diff"] = round(rows[-1][1] - rows[-2][1], 1)  # FRED 原始單位已是千人
            if "diff3avg" in calc and len(rows) >= 4:
                m["diff3avg"] = round((rows[-1][1] - rows[-4][1]) / 3, 1)
            if "chg60d" in calc and len(rows) >= 45:
                m["chg60d"] = round((rows[-1][1] / rows[-45][1] - 1) * 100, 1)  # 日資料約45筆=60個日曆天
            macro[sid] = m
            time.sleep(0.4)
        except Exception as e:
            log("fred", sid, "failed:", repr(e))
    if hist:
        macro["_history"] = hist
    return macro


# ---------------- 金十 MCP ----------------

class Jin10MCP:
    URL = "https://mcp.jin10.com/mcp"

    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })
        self.sid = None
        self._id = 0

    def _post(self, method, params, notify=False):
        self._id += 1
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            body["id"] = self._id
        h = {}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        r = self.s.post(self.URL, json=body, headers=h, timeout=25)
        if "Mcp-Session-Id" in r.headers:
            self.sid = r.headers["Mcp-Session-Id"]
        r.encoding = "utf-8"  # 金十回應無 charset 標頭，強制 UTF-8 防亂碼
        if notify or not r.text.strip():
            return None
        txt = r.text
        if "text/event-stream" in r.headers.get("Content-Type", ""):
            datas = [ln[5:].strip() for ln in txt.splitlines() if ln.startswith("data:")]
            txt = datas[-1] if datas else "{}"
        try:
            return json.loads(txt)
        except Exception:
            return {"_raw": txt[:500]}

    def start(self):
        res = self._post("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "fed-watch", "version": "1.0"}})
        self._post("notifications/initialized", {}, notify=True)
        return res

    def tool_names(self):
        res = self._post("tools/list", {}) or {}
        return {t["name"]: t for t in res.get("result", {}).get("tools", [])}

    def call(self, name, args):
        res = self._post("tools/call", {"name": name, "arguments": args}) or {}
        content = res.get("result", {}).get("content", [])
        for c in content:
            if c.get("type") == "text":
                try:
                    return json.loads(c["text"])
                except Exception:
                    return {"_text": c["text"]}
        return res


def _flash_items(payload):
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    items = data.get("items", []) if isinstance(data, dict) else []
    return items if isinstance(items, list) else []


def fetch_jin10(existing_ids):
    token = os.environ.get("JIN10_MCP_TOKEN", "").strip()
    if not token:
        log("jin10: no token, skip")
        return []
    quotes = []
    try:
        cli = Jin10MCP(token)
        init_res = cli.start()
        log("jin10 init:", json.dumps(init_res, ensure_ascii=False)[:250] if init_res else "None")
        tools = cli.tool_names()
        if tools:
            log("jin10 tools:", list(tools)[:12])
        search = "search_flash" if "search_flash" in tools else ("list_flash" if "list_flash" in tools else None)
        props = {}
        if search:
            props = tools[search].get("inputSchema", {}).get("properties", {})
        else:
            # tools/list 拿不到就按官方文件盲呼叫
            log("jin10: tools/list empty, fallback to blind search_flash")
            search = "search_flash"
        kw_param = next((p for p in ("keyword", "query", "q", "search", "keywords") if p in props), "keyword")
        markers = CFG["institution_markers"]
        first_kw = True
        for kw in CFG["jin10_keywords"]:
            args = {kw_param: kw}
            if props:
                for lim in ("limit", "size", "count"):
                    if lim in props:
                        args[lim] = 30
                        break
            # 盲呼叫模式：金十 search_flash 只收 keyword，不加其他參數
            payload = cli.call(search, args)
            items = _flash_items(payload)
            if first_kw:
                if items:
                    log("jin10 sample item:", json.dumps(items[0], ensure_ascii=False)[:300])
                else:
                    log("jin10 raw payload:", json.dumps(payload, ensure_ascii=False)[:350])
            first_kw = False
            for it in items:
                text = (it.get("content") or "") + (it.get("title") or "")
                qid = str(it.get("id", ""))
                if not qid and it.get("url"):
                    qid = it["url"].rstrip("/").split("/")[-1]
                if not qid and text:
                    qid = hashlib.md5(text.encode("utf-8")).hexdigest()[:16]
                if not qid or qid in existing_ids or not text:
                    continue
                relevant = ("美联储" in text or "FOMC" in text or "联储" in text)
                marked = any(mk in text for mk in markers)
                if relevant and (marked or "概率" in text or "机率" in text):
                    quotes.append({
                        "id": qid,
                        "time": it.get("time", ""),
                        "text": text[:1200],
                        "url": it.get("url", ""),
                        "cls": None, "stated": None,
                        "fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    })
                    existing_ids.add(qid)
            time.sleep(0.8)
    except Exception as e:
        log("jin10 failed:", repr(e))
    log("jin10: %d new quotes" % len(quotes))
    return quotes


# CME FedWatch 數字常出現在金十快訊，例如：
# 「据CME"美联储观察"：美联储9月维持利率不变的概率为66%，加息25个基点的概率为34%」
FW_PAT = re.compile(r"(维持利率不变|按兵不动|不变|加息|升息|降息).{0,15}?概率[为為]\s*(\d+(?:\.\d+)?)\s*%")
FW_SIZE = re.compile(r"(加息|升息|降息)\s*(\d+)\s*个?基点")


def extract_fedwatch(quotes, meetings):
    """從新快訊裡萃取 CME FedWatch 引用數字（只抓下一場會議的直述句）。"""
    nxt = meetings[0]
    zh = nxt["zh_month"]
    best = None
    cands = []
    now = dt.datetime.now(dt.timezone.utc)
    for q in quotes:
        t = q["text"]
        if "美联储观察" not in t or zh not in t:
            continue
        try:
            qt = dt.datetime.fromisoformat(str(q.get("time", "")).replace("Z", "+00:00"))
            if qt.tzinfo is None:
                qt = qt.replace(tzinfo=dt.timezone.utc)
            if (now - qt).days > 3:
                continue  # 搜尋會撈出歷史舊聞，只收 3 天內的引用
        except Exception:
            continue
        probs = {}
        cur = "target" if t.startswith("【") and zh in t.split("】")[0] else None
        for seg in re.split(r"[，。；,;]", t):
            # 追蹤段落屬於哪個月份，避免 10 月／12 月的數字混進目標會議
            others = [m2["zh_month"] for m2 in meetings[1:]]
            if any(om in seg for om in others):
                cur = "other"
            elif zh in seg:
                cur = "target"
            mm = FW_PAT.search(seg)
            if not mm or cur != "target":
                continue
            action, pct = mm.group(1), float(mm.group(2)) / 100.0
            size = FW_SIZE.search(seg)
            bp = int(size.group(2)) if size else 25
            if action in ("维持利率不变", "按兵不动", "不变"):
                probs["hold"] = probs.get("hold", 0) + pct
            elif action in ("加息", "升息"):
                probs["hike25" if bp <= 25 else "hike50p"] = pct
            elif action == "降息":
                probs["cut25" if bp <= 25 else "cut50p"] = pct
        n = norm(probs)
        # 至少要解析出兩個桶才算完整引用（避免只提「不變」的殘句變成 100%）
        if n and len(probs) >= 2 and n.get("hold", 0) + n.get("hike25", 0) + n.get("cut25", 0) > 0.5:
            cands.append((q["time"], len(probs),
                          {"meeting": nxt["key"], "probs": n, "src": q["url"], "time": q["time"], "raw": t[:300]}))
    if cands:
        cands.sort(key=lambda c: (c[0], c[1]))  # 時間最新、桶數最多者勝
        best = cands[-1][2]
    return best


# ---------------- 主流程 ----------------

def main():
    password = os.environ.get("PAGE_PASSWORD", "").strip()
    if not password:
        sys.exit("PAGE_PASSWORD env is required")
    store = fwcrypto.load_store(STORE_PATH, password)

    kalshi = fetch_kalshi()
    pm = fetch_polymarket()
    macro = fetch_fred()

    existing = {q["id"] for q in store["quotes"]}
    new_quotes = fetch_jin10(existing)
    store["quotes"].extend(new_quotes)
    store["quotes"] = store["quotes"][-CFG["max_quotes_stored"]:]

    # 用全部庫存 quotes 掃（不只 new），時間過濾在 extract 內做
    fw = extract_fedwatch(store["quotes"], CFG["meetings"])
    if not fw:
        for snap in reversed(store["snapshots"]):
            if snap.get("fedwatch"):
                try:
                    ft = dt.datetime.fromisoformat(str(snap["fedwatch"].get("time", "")).replace("Z", "+00:00"))
                    if ft.tzinfo is None:
                        ft = ft.replace(tzinfo=dt.timezone.utc)
                    if (dt.datetime.now(dt.timezone.utc) - ft).days <= 3:
                        fw = snap["fedwatch"]
                except Exception:
                    pass
                break

    if macro:
        old_hist = store["macro"].get("_history", {})
        new_hist = macro.get("_history", {})
        merged = dict(old_hist)
        merged.update(new_hist)
        macro["_history"] = merged
        store["macro"] = macro

    snap = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "kalshi": kalshi, "polymarket": pm, "fedwatch": fw,
    }
    store["snapshots"].append(snap)
    store["snapshots"] = store["snapshots"][-CFG["snapshot_keep"]:]

    fwcrypto.save_store(STORE_PATH, store, password)
    log("done: kalshi=%d pm=%d fred=%d newquotes=%d fedwatch=%s"
        % (len(kalshi), len(pm), len([k for k in store["macro"] if not k.startswith("_")]),
           len(new_quotes), "yes" if fw else "no"))


if __name__ == "__main__":
    main()









