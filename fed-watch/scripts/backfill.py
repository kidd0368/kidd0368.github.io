# -*- coding: utf-8 -*-
"""回填 Kalshi 日 K，建立市場機率的歷史軌跡（每日一點，預設 120 天）。
寫入 store["market_history"][meeting_key] = [[YYYY-MM-DD, {bucket: p}], ...]
一天最多跑一次（20 小時內跳過），避免每次 collect 都打 20 支 API。
用法：PAGE_PASSWORD=... python backfill.py [--force]
"""
import datetime as dt
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
UA = {"User-Agent": "fed-watch-dashboard/1.0 (personal research)"}
BUCKETS = CFG["buckets"]
DAYS = 120
API = "https://api.elections.kalshi.com/trade-api/v2"


def log(*a):
    print("[backfill]", *a, flush=True)


def strike_bucket(strike):
    if "Hike" in strike:
        v = str(strike["Hike"])
        return "hold" if v == "0" else ("hike25" if v == "25" else "hike50p")
    if "Cut" in strike:
        v = str(strike["Cut"])
        return "cut25" if v == "25" else "cut50p"
    return None


def tickers_for(event):
    """回傳 {ticker: bucket}。"""
    r = requests.get(API + "/markets", params={"event_ticker": event},
                     headers=UA, timeout=25)
    r.raise_for_status()
    out = {}
    for mk in r.json().get("markets", []):
        b = strike_bucket(mk.get("custom_strike", {}))
        if b:
            out[mk["ticker"]] = b
    return out


def candles(ticker, start_ts, end_ts):
    """回傳 {date: mid_price}。優先用 bid/ask 中價，退回收盤價。"""
    r = requests.get("%s/series/KXFEDDECISION/markets/%s/candlesticks" % (API, ticker),
                     params={"start_ts": start_ts, "end_ts": end_ts,
                             "period_interval": 1440},
                     headers=UA, timeout=30)
    r.raise_for_status()
    out = {}
    for c in r.json().get("candlesticks", []):
        ts = c.get("end_period_ts")
        if not ts:
            continue
        day = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")
        px = None
        bid = (c.get("yes_bid") or {}).get("close_dollars")
        ask = (c.get("yes_ask") or {}).get("close_dollars")
        try:
            if bid is not None and ask is not None and float(ask) > 0:
                px = (float(bid) + float(ask)) / 2.0
        except (TypeError, ValueError):
            px = None
        if px is None:
            cl = (c.get("price") or {}).get("close_dollars")
            try:
                px = float(cl) if cl is not None else None
            except (TypeError, ValueError):
                px = None
        if px is not None:
            out[day] = px
    return out


def main():
    password = os.environ.get("PAGE_PASSWORD", "").strip()
    if not password:
        sys.exit("PAGE_PASSWORD env is required")
    force = "--force" in sys.argv
    store = fwcrypto.load_store(STORE_PATH, password)
    mh = store.get("market_history") or {}

    if not force and mh.get("_ts"):
        try:
            age = (dt.datetime.now(dt.timezone.utc)
                   - dt.datetime.fromisoformat(mh["_ts"])).total_seconds() / 3600
            if age < 20:
                log("last backfill %.1fh ago, skip" % age)
                return
        except Exception:
            pass

    end_ts = int(time.time())
    start_ts = end_ts - DAYS * 86400
    total = 0
    for m in CFG["meetings"]:
        key = m["key"]
        try:
            tk = tickers_for(m["kalshi_event"])
        except Exception as e:
            log(key, "markets failed:", repr(e))
            continue
        by_day = {}
        for ticker, bucket in tk.items():
            try:
                for day, px in candles(ticker, start_ts, end_ts).items():
                    by_day.setdefault(day, {})[bucket] = px
            except Exception as e:
                log(key, ticker, "candles failed:", repr(e))
            time.sleep(0.35)
        series = []
        for day in sorted(by_day):
            d = by_day[day]
            # 至少三個桶有報價才收，避免早期流動性稀薄的雜訊
            if len(d) < 3:
                continue
            s = sum(max(0.0, v) for v in d.values())
            if s <= 0:
                continue
            series.append([day, {b: round(max(0.0, d.get(b, 0.0)) / s, 4) for b in BUCKETS}])
        if series:
            mh[key] = series
            total += len(series)
            log("%s: %d days (%s → %s)" % (key, len(series), series[0][0], series[-1][0]))

    mh["_ts"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    store["market_history"] = mh
    fwcrypto.save_store(STORE_PATH, store, password)
    log("done, %d day-points across %d meetings" % (total, len([k for k in mh if not k.startswith("_")])))


if __name__ == "__main__":
    main()
