# -*- coding: utf-8 -*-
"""bond-watch 資料收集：FRED 完整殖利率曲線 + 拆解序列 + 金十債市事件。
用法：PAGE_PASSWORD=... [FRED_API_KEY=...] [JIN10_MCP_TOKEN=...] python collect.py
"""
import datetime as dt
import hashlib
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fwcrypto

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
STORE_PATH = os.path.join(BASE, "data", "store.enc")
UA = {"User-Agent": "bond-watch-dashboard/1.0 (personal research)"}
DAYS = CFG["history_days"]


def log(*a):
    print("[bond]", *a, flush=True)


# ---------------- FRED ----------------

def fred_series(sid):
    """回傳 [[date, value], ...]（升冪）。有 key 走官方 API，否則 fredgraph.csv。"""
    key = os.environ.get("FRED_API_KEY", "").strip()
    if key:
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": sid, "api_key": key, "file_type": "json"},
                         headers=UA, timeout=25)
        r.raise_for_status()
        rows = []
        for o in r.json().get("observations", []):
            v = o.get("value")
            if v not in (".", "", None):
                try:
                    rows.append([o["date"], float(v)])
                except ValueError:
                    pass
        return rows
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                     params={"id": sid}, headers=UA, timeout=15)
    r.raise_for_status()
    rows = []
    for line in r.text.strip().splitlines()[1:]:
        p = line.split(",")
        if len(p) >= 2 and p[1].strip() not in (".", ""):
            try:
                rows.append([p[0].strip(), float(p[1])])
            except ValueError:
                pass
    return rows


def collect_fred():
    series, latest = {}, {}
    ids = [c["id"] for c in CFG["curve"]] + list(CFG["decomp"].keys())
    for sid in ids:
        try:
            rows = fred_series(sid)
            if not rows:
                log(sid, "empty")
                continue
            series[sid] = rows[-DAYS:]
            latest[sid] = rows[-1]
            time.sleep(0.25)
        except Exception as e:
            log(sid, "failed:", type(e).__name__)
    return series, latest


def value_on_or_before(rows, target):
    """取 target 日期（含）之前最近一筆值。"""
    best = None
    for d, v in rows:
        if d <= target:
            best = v
        else:
            break
    return best


def change_bp_on_aligned_date(rows, current_date, current_value, trading_days):
    """用共同曆日對齊近似交易日回看，避免週頻序列把 20 筆誤當成 20 日。"""
    try:
        current = dt.date.fromisoformat(current_date)
    except Exception:
        return None
    calendar_days = max(1, round(trading_days * 7 / 5))
    target = (current - dt.timedelta(days=calendar_days)).isoformat()
    previous = value_on_or_before(rows, target)
    return round((current_value - previous) * 100, 1) if previous is not None else None


def aligned_change_block(series, fields, lookbacks):
    """讓不同頻率序列使用同一個截至日與同一個回看窗。

    fields: [(series_id, output_key), ...]
    """
    rows_by_key = {}
    for series_id, output_key in fields:
        rows = series.get(series_id)
        if not rows:
            return None
        rows_by_key[output_key] = rows

    common_date = min(rows[-1][0] for rows in rows_by_key.values())
    current_values = {
        key: value_on_or_before(rows, common_date)
        for key, rows in rows_by_key.items()
    }
    if any(value is None for value in current_values.values()):
        return None

    changes = {}
    for lookback in lookbacks:
        row = {}
        for key, rows in rows_by_key.items():
            change = change_bp_on_aligned_date(
                rows, common_date, current_values[key], lookback,
            )
            if change is None:
                row = {}
                break
            row[key] = change
        if row:
            changes[str(lookback)] = row

    return {
        "date": common_date,
        "values": current_values,
        "chg": changes,
    }


def build_snapshot(series):
    """組出當日曲線、利差、拆解、各回看期變化。"""
    curve, asof = [], None
    for c in CFG["curve"]:
        rows = series.get(c["id"])
        if not rows:
            continue
        d, v = rows[-1]
        asof = max(asof, d) if asof else d
        item = {"label": c["label"], "years": c["years"], "id": c["id"],
                "value": v, "date": d, "chg": {}}
        for k in CFG["lookbacks"]:
            change = change_bp_on_aligned_date(rows, d, v, k)
            if change is not None:
                item["chg"][str(k)] = change
        curve.append(item)

    decomp = {}
    for sid, name in CFG["decomp"].items():
        rows = series.get(sid)
        if not rows:
            continue
        d, v = rows[-1]
        e = {"name": name, "value": v, "date": d, "chg": {}}
        for k in CFG["lookbacks"]:
            change = change_bp_on_aligned_date(rows, d, v, k)
            if change is not None:
                e["chg"][str(k)] = change
        decomp[sid] = e

    spreads = {}
    for sp in CFG["spreads"]:
        lo, sh = series.get(sp["long"]), series.get(sp["short"])
        if not lo or not sh:
            continue
        common_date = min(lo[-1][0], sh[-1][0])
        lo_now = value_on_or_before(lo, common_date)
        sh_now = value_on_or_before(sh, common_date)
        if lo_now is None or sh_now is None:
            continue
        v = round((lo_now - sh_now) * 100, 1)
        e = {"label": sp["label"], "bp": v, "chg": {}}
        for k in CFG["lookbacks"]:
            target = (dt.date.fromisoformat(common_date) -
                      dt.timedelta(days=max(1, round(k * 7 / 5)))).isoformat()
            lo_prev = value_on_or_before(lo, target)
            sh_prev = value_on_or_before(sh, target)
            if lo_prev is not None and sh_prev is not None:
                e["chg"][str(k)] = round(v - (lo_prev - sh_prev) * 100, 1)
        spreads[sp["key"]] = e

    aligned = {}
    term_premium_curve = aligned_change_block(
        series,
        (("DGS2", "y2_bp"),
         ("DGS10", "y10_bp"),
         ("THREEFYTP10", "term_premium10_bp")),
        CFG["lookbacks"],
    )
    if term_premium_curve:
        aligned["term_premium_curve"] = term_premium_curve

    return {
        "asof": asof,
        "curve": curve,
        "decomp": decomp,
        "spreads": spreads,
        "aligned": aligned,
    }


def pressure_index(snap):
    """折現率壓力 0–100：長端實質利率／期限溢價／30年水位／20日動能。"""
    p = CFG["pressure"]

    def norm(v, lo, hi):
        if v is None:
            return None
        return max(0.0, min(1.0, (v - lo) / (hi - lo)))

    d = snap["decomp"]
    real30 = (d.get("DFII30") or {}).get("value")
    tp = (d.get("THREEFYTP10") or {}).get("value")
    y30 = next((c["value"] for c in snap["curve"] if c["label"] == "30Y"), None)
    mom = next((c["chg"].get("20") for c in snap["curve"] if c["label"] == "30Y"), None)

    parts = {
        "real30": (norm(real30, p["real30_lo"], p["real30_hi"]), real30, "30年實質利率"),
        "tp": (norm(tp, p["tp_lo"], p["tp_hi"]), tp, "10年期限溢價"),
        "y30": (norm(y30, p["y30_lo"], p["y30_hi"]), y30, "30年名目利率"),
        "mom": (norm(mom, p["mom_lo"], p["mom_hi"]), mom, "30年20日動能(bp)"),
    }
    tot, wsum, detail = 0.0, 0.0, []
    for k, (n, raw, name) in parts.items():
        w = p["weights"][k]
        if n is None:
            continue
        tot += n * w
        wsum += w
        detail.append({"key": k, "name": name, "value": raw, "score": round(n * 100)})
    score = round(tot / wsum * 100) if wsum else None
    return {"score": score, "detail": detail}


def decomposition(snap):
    """名目 = 實質 + 通膨預期；並判斷近期長端變動由誰驅動。"""
    d = snap["decomp"]
    out = {}
    for tenor, ny, real, ie in (("10Y", "DGS10", "DFII10", "T10YIE"),
                                ("5Y", "DGS5", "DFII5", "T5YIE"),
                                ("30Y", "DGS30", "DFII30", None)):
        nom = next((c for c in snap["curve"] if c["id"] == ny), None)
        rr, be = d.get(real), d.get(ie) if ie else None
        if not nom or not rr:
            continue
        e = {"nominal": nom["value"], "real": rr["value"],
             "be": be["value"] if be else (round(nom["value"] - rr["value"], 2)),
             "chg20": {"nominal": nom["chg"].get("20"), "real": rr["chg"].get("20"),
                       "be": be["chg"].get("20") if be else None}}
        cn, cr = e["chg20"]["nominal"], e["chg20"]["real"]
        if cn is not None and cr is not None:
            share = (cr / cn) if abs(cn) > 1e-6 else None
            if share is None:
                e["driver"] = "無明顯變動"
            elif abs(cn) < 5:
                e["driver"] = "20日內大致持平"
            elif share > 0.7:
                e["driver"] = "實質利率主導（成長／期限溢價／財政）"
            elif share < 0.3:
                e["driver"] = "通膨預期主導"
            else:
                e["driver"] = "實質與通膨預期各半"
        out[tenor] = e
    return out


# ---------------- 金十事件 ----------------

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
        h = {"Mcp-Session-Id": self.sid} if self.sid else {}
        r = self.s.post(self.URL, json=body, headers=h, timeout=25)
        r.encoding = "utf-8"
        if "Mcp-Session-Id" in r.headers:
            self.sid = r.headers["Mcp-Session-Id"]
        if notify or not r.text.strip():
            return None
        txt = r.text
        if "text/event-stream" in r.headers.get("Content-Type", ""):
            datas = [ln[5:].strip() for ln in txt.splitlines() if ln.startswith("data:")]
            txt = datas[-1] if datas else "{}"
        try:
            return json.loads(txt)
        except Exception:
            return {"_raw": txt[:400]}

    def start(self):
        res = self._post("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                        "clientInfo": {"name": "bond-watch", "version": "1.0"}})
        self._post("notifications/initialized", {}, notify=True)
        return res

    def tools(self):
        res = self._post("tools/list", {}) or {}
        return {t["name"]: t for t in res.get("result", {}).get("tools", [])}

    def call(self, name, args):
        res = self._post("tools/call", {"name": name, "arguments": args}) or {}
        for c in res.get("result", {}).get("content", []):
            if c.get("type") == "text":
                try:
                    return json.loads(c["text"])
                except Exception:
                    return {"_text": c["text"]}
        return res


def _items(payload):
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    it = data.get("items", []) if isinstance(data, dict) else []
    return it if isinstance(it, list) else []


def collect_events(existing_ids):
    token = os.environ.get("JIN10_MCP_TOKEN", "").strip()
    if not token:
        log("jin10: no token, skip")
        return []
    out = []
    try:
        cli = Jin10MCP(token)
        cli.start()
        tools = cli.tools()
        tool = "search_flash" if "search_flash" in tools else "list_flash"
        props = tools.get(tool, {}).get("inputSchema", {}).get("properties", {})
        kw_param = next((p for p in ("keyword", "query", "q", "search") if p in props), "keyword")
        markers = CFG["event_markers"]
        for kw in CFG["jin10_keywords"]:
            payload = cli.call(tool, {kw_param: kw})
            for it in _items(payload):
                text = (it.get("content") or "") + (it.get("title") or "")
                if not text:
                    continue
                qid = str(it.get("id", "")) or (it.get("url", "").rstrip("/").split("/")[-1]) \
                    or hashlib.md5(text.encode("utf-8")).hexdigest()[:16]
                if qid in existing_ids:
                    continue
                hits = [m for m in markers if m in text]
                bondish = ("美债" in text or "国债" in text or "收益率" in text
                           or "财政部" in text or "期限溢价" in text)
                if bondish and len(hits) >= 2:
                    out.append({"id": qid, "time": it.get("time", ""), "text": text[:900],
                                "url": it.get("url", ""), "tags": hits[:5],
                                "fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
                    existing_ids.add(qid)
            time.sleep(0.7)
    except Exception as e:
        log("jin10 failed:", type(e).__name__)
    log("jin10: %d new events" % len(out))
    return out


# ---------------- 主流程 ----------------

def main():
    password = os.environ.get("PAGE_PASSWORD", "").strip()
    if not password:
        sys.exit("PAGE_PASSWORD env is required")
    store = fwcrypto.load_store(STORE_PATH, password)
    store.setdefault("events", [])
    store.setdefault("series", {})

    series, latest = collect_fred()
    if not series:
        sys.exit("no FRED data collected")
    # 單一 FRED 序列暫時失敗時保留上一批資料；後續新鮮度檢查會明確標示過期，
    # 不讓部分成功的下載把完整舊資料整包抹掉。
    merged_series = dict(store.get("series") or {})
    merged_series.update(series)
    store["series"] = merged_series

    snap = build_snapshot(merged_series)
    snap["ts"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    snap["pressure"] = pressure_index(snap)
    snap["decomposition"] = decomposition(snap)
    store.setdefault("snapshots", []).append(snap)
    store["snapshots"] = store["snapshots"][-CFG["snapshot_keep"]:]

    ids = {e["id"] for e in store["events"]}
    store["events"].extend(collect_events(ids))
    store["events"] = sorted(store["events"], key=lambda e: e.get("time", ""))[-CFG["max_events"]:]

    fwcrypto.save_store(STORE_PATH, store, password)
    log("done: asof=%s curve=%d events=%d"
        % (snap["asof"], len(snap["curve"]), len(store["events"])))


if __name__ == "__main__":
    main()
