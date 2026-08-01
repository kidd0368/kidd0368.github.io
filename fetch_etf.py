# -*- coding: utf-8 -*-
"""槓桿ETF數據抓取（GitHub Actions 直連版，全部為免登入公開端點）

來源
  A. Naver 金融 ETF 全清單 JSON  → 逐檔現價 / NAV / 市值(억원) / 成交
  B. Naver 金融 個股日線 JSON    → 逐檔上市以來收盤價（跌破發行價家數的時序）
  C. KOFIA 特定類型基金現況      → 全體 ETF 規模（「佔整體 ETF 比重」的分母）
  D. Naver 個股市值             → 三星電子 / SK海力士 市值（風險敞口分母，選配）

為何不用 KRX：2026 改版後 data.krx.co.kr 需登入，open API 金鑰不對境外開放。
以上四個來源皆可匿名存取，Actions runner 直連即可。

狀態延續：規模／份額無公開歷史，故自首次執行起逐日累積；
狀態載體＝上一版 index.html 內嵌的 IND.etf.series（不需要改動 workflow）。
"""
import json, os, re, sys, time
from datetime import datetime, timezone, timedelta

import requests

PAR = 20000                     # 單股槓桿ETF上市發行價（₩），2026-05-27 上市
LIST_DATE = "20260527"
UNIT_SEED_TRIL = 26.7           # 已記錄的份額對應資產高點（2026-07-10 觀測，兆₩）
AUM_SEED_TRIL = 25.0            # 已記錄的規模高點（約 US$16.7bn，兆₩）

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
H_NAVER = {"User-Agent": UA, "Referer": "https://finance.naver.com/sise/etf.naver",
           "Accept": "application/json, text/plain, */*"}

# 標的關鍵字（名稱比對為主，代碼清單為輔——兩者取聯集，任一來源改版都不會漏）
UNDERLYING = [("삼성전자", "三星電子"), ("하이닉스", "SK海力士")]
LEV_KW = ("레버리지", "2X", "2x")
INV_KW = ("인버스", "인버스2X")
KNOWN = {  # 2026-05-27 上市的單股槓桿/反向 ETF（僅作補漏，非唯一依據）
    "0193W0", "0195R0", "0194M0", "0192M0", "0193K0", "0194N0", "0198B0",
    "0193T0", "0195S0", "0194T0", "0192L0", "0197W0", "0194R0", "0198D0",
    "0193L0", "0197X0",
}

PROBE = {}

# 時間預算：本模組掛在 fetch_kofia.py 尾端，與主抓取共用同一個 workflow step
# （update.yml 設 timeout-minutes: 15）。ETF 來源若無回應，重試累加可達數十分鐘，
# 會連帶讓「計算指標／組裝／提交」三步永遠不執行——亦即整份儀表板停更。
# 故給本模組硬性上限：超時即帶著已取得的部分結果收工，主管線不受影響。
BUDGET_S = 240
_T0 = [None]


def budget_left():
    if _T0[0] is None:
        return BUDGET_S
    return BUDGET_S - (time.time() - _T0[0])


def kst_today():
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y%m%d")


def get(sess, url, tries=3, **kw):
    kw.setdefault("timeout", 30)
    kw.setdefault("headers", H_NAVER)
    last = None
    for i in range(tries):
        if budget_left() <= 0:
            raise RuntimeError("time budget exhausted")
        try:
            r = sess.get(url, **kw)
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(1.5 * (i + 1))
    raise last


# ---------------------------------------------------------------- A. ETF 清單
def naver_etf_list(sess):
    url = ("https://finance.naver.com/api/sise/etfItemList.nhn"
           "?etfType=0&targetColumn=market_sum&sortOrder=desc")
    r = get(sess, url)
    js = r.json()
    items = (js.get("result") or {}).get("etfItemList") or []
    PROBE["list"] = {"ok": True, "n": len(items)}
    return items


def classify(it):
    """回傳 (標的中文名, 'lev'|'inv'|None)

    採「名稱為準」：必須同時命中標的（삼성전자／하이닉스）與槓桿/反向關鍵字。
    KNOWN 代碼清單不作為納入依據（來源非一手，誤納會污染總量），
    僅在 probe 裡回報「已知代碼卻沒被選中」，供事後校正命名規則。
    """
    nm = str(it.get("itemname") or "")
    under = None
    for kw, zh in UNDERLYING:
        if kw in nm:
            under = zh
            break
    if under is None:
        return None, None
    is_inv = any(k in nm for k in INV_KW)
    is_lev = any(k in nm for k in LEV_KW) and not is_inv
    if not (is_lev or is_inv):
        return None, None
    return under, ("inv" if is_inv else "lev")


# ------------------------------------------------------------ B. 逐檔價格歷史
def naver_price_hist(sess, code, d1, d2):
    """回傳 {date: close}。主端點 siseJson，備援 fchart XML。

    逐檔呼叫（十餘次），故縮短逾時與重試次數：單檔失敗只損失該檔，
    不值得為它耗掉整個模組的時間預算。
    """
    try:
        url = ("https://api.finance.naver.com/siseJson.naver?symbol=%s&requestType=1"
               "&startTime=%s&endTime=%s&timeframe=day" % (code, d1, d2))
        txt = get(sess, url, tries=2, timeout=12).text.strip()
        arr = json.loads(txt.replace("'", '"'))
        out = {}
        for row in arr[1:]:
            if len(row) >= 5 and re.fullmatch(r"\d{8}", str(row[0])):
                out[str(row[0])] = float(row[4])
        if out:
            return out
    except Exception as e:
        PROBE.setdefault("hist_err", []).append("%s:siseJson:%s" % (code, str(e)[:60]))
    try:
        url = ("https://fchart.stock.naver.com/sise.nhn?symbol=%s&timeframe=day"
               "&count=400&requestType=0" % code)
        txt = get(sess, url, tries=2, timeout=12).text
        out = {}
        for m in re.finditer(r'data="(\d{8})\|([^"]+)"', txt):
            parts = m.group(2).split("|")
            if len(parts) >= 4:
                out[m.group(1)] = float(parts[3])
        return out
    except Exception as e:
        PROBE.setdefault("hist_err", []).append("%s:fchart:%s" % (code, str(e)[:60]))
    return {}


# --------------------------------------------------- C. KOFIA 全體 ETF 規模
def kofia_all_etf(sess, day):
    url = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
    body = {"dmSearch": {"tmpV40": "100000000", "tmpV41": "1", "tmpV34": day,
                         "tmpV11": "", "tmpV7": "1", "OBJ_NM": "STATFND0100100140BO"}}
    r = sess.post(url, json=body, timeout=35, headers={
        "Content-Type": "application/json", "User-Agent": UA,
        "Origin": "https://freesis.kofia.or.kr",
        "Referer": "https://freesis.kofia.or.kr/stat/FreeSIS.do"})
    r.raise_for_status()
    rows = r.json().get("ds1") or []
    for row in rows:
        blob = " ".join(str(v) for v in row.values())
        if "ETF" in blob.upper() or "상장지수" in blob:
            nums = []
            for v in row.values():
                try:
                    nums.append(float(str(v).replace(",", "")))
                except Exception:
                    pass
            if nums:
                PROBE["kofia_etf_row"] = {k: str(v)[:24] for k, v in list(row.items())[:12]}
                v = max(nums)             # 억원
                # 合理區間檢查：南韓全體 ETF 純資產約 100–500 兆₩＝100 萬–500 萬億원。
                # 超出 50 兆–2,000 兆₩ 者視為抓錯欄位，寧可留空也不輸出錯比率。
                if 500000 <= v <= 20000000:
                    return v
                PROBE["kofia_reject"] = v
    return None


# ------------------------------------------------- D. 標的個股市值（選配）
MCAP_URLS = ("https://m.stock.naver.com/api/stock/%s/integration",
             "https://api.stock.naver.com/stock/%s/integration",
             "https://m.stock.naver.com/api/stock/%s/basic")


def won_to_eok(s):
    """Naver 顯示字串 → 억원。支援「340조 3,443억원」「3,403,443억원」「340조원」與純數字。"""
    s = str(s).replace(",", "").strip()
    if not s:
        return None
    tot, hit = 0.0, False
    m = re.search(r"([\d.]+)\s*조", s)
    if m:
        tot += float(m.group(1)) * 10000.0      # 1조 = 10,000억
        hit = True
        s = s[m.end():]
    m = re.search(r"([\d.]+)\s*억", s)
    if m:
        tot += float(m.group(1))
        hit = True
    elif not hit:
        m = re.search(r"[\d.]+", s)             # 已是억원 的純數字
        if m:
            tot, hit = float(m.group(0)), True
    return tot if hit else None


def scan_mcap(node, out, depth=0):
    """在任意深度的 JSON 裡找標著「시가총액」的欄位。
    端點改版時欄位路徑常變、標籤文字不變，故以標籤比對取代硬編路徑。"""
    if depth > 6 or len(out) > 8:
        return
    if isinstance(node, dict):
        blob = " ".join(str(x) for x in list(node.keys()) + list(node.values())
                        if not isinstance(x, (dict, list)))
        if "시가총액" in blob or "marketValue" in blob:
            for f in ("value", "amount", "marketValue", "desc", "text"):
                v = won_to_eok(node.get(f, ""))
                if v:
                    out.append(v)
                    break
        for v in node.values():
            scan_mcap(v, out, depth + 1)
    elif isinstance(node, list):
        for it in node:
            scan_mcap(it, out, depth + 1)


def naver_mcap(sess, code):
    for tpl in MCAP_URLS:
        if budget_left() < 15:
            PROBE["mcap_skipped"] = "budget"
            return None
        try:
            js = get(sess, tpl % code, tries=2,
                     headers={"User-Agent": UA,
                              "Referer": "https://m.stock.naver.com/"}).json()
        except Exception as e:
            PROBE.setdefault("mcap_err", []).append("%s:%s" % (code, str(e)[:50]))
            continue
        cand = []
        scan_mcap(js, cand)
        for v in cand:
            # 三星／海力士市值量級為 50 兆–1,000 兆₩；超出即視為單位解析錯誤
            if 500000 <= v <= 10000000:
                return v
        # 沒中就把這個端點的形狀記進 probe，下次執行即可直接看出欄位改到哪
        PROBE.setdefault("mcap_shape", {})[code] = {
            "url": tpl.split("/api/")[-1] if "/api/" in tpl else tpl,
            "keys": sorted(js.keys())[:15] if isinstance(js, dict) else type(js).__name__,
            "cand": cand[:5]}
    return None


# ------------------------------------------ E. 交叉驗證：外資持股率與券商股價
# 目的：儀表板主體量「賣方」（份額註銷、融資去化）；此塊量「接手方」與座標——
#   個股外資持股率（三星電子/SK海力士，槓桿ETF標的）＋券商股價（槓桿景氣溫度計）。
# 設計：每次全量重抓近400日，無自建狀態 → 任一天漏跑都能自癒；缺數據不估算。
CTX_STOCKS = [("005930", "三星電子"), ("000660", "SK海力士")]
CTX_BROKERS = [("006800", "未來資產證券"), ("039490", "Kiwoom證券")]


def sise_rows(sess, code, d1, d2):
    """siseJson 原始表 → (表頭, 資料列)。欄位一律用表頭標籤定位，不硬編位置。"""
    url = ("https://api.finance.naver.com/siseJson.naver?symbol=%s&requestType=1"
           "&startTime=%s&endTime=%s&timeframe=day" % (code, d1, d2))
    arr = json.loads(get(sess, url, tries=2, timeout=12).text.strip().replace("'", '"'))
    if not isinstance(arr, list) or len(arr) < 2:
        return [], []
    return [str(x) for x in arr[0]], arr[1:]


def col_of(header, kw):
    for i, h in enumerate(header):
        if kw in h:
            return i
    return None


def pack_col(rows, ci):
    """{YYYYMMDD: float}；空值/壞列直接略過。"""
    out = {}
    for r in rows:
        d = str(r[0])
        if re.fullmatch(r"\d{8}", d) and ci is not None and ci < len(r):
            try:
                out[d] = float(r[ci])
            except (TypeError, ValueError):
                pass
    return out


def fetch_ctx(sess):
    d2 = kst_today()
    d1 = (datetime.now(timezone.utc) + timedelta(hours=9)
          - timedelta(days=400)).strftime("%Y%m%d")
    ctx = {}

    # 個股外資持股率（외국인소진율 欄；標籤含「외국인」）
    frgn = {}
    for code, _zh in CTX_STOCKS:
        if budget_left() < 25:
            PROBE["ctx_skipped"] = "budget"
            break
        try:
            hd, rows = sise_rows(sess, code, d1, d2)
            PROBE.setdefault("ctx_header", hd[:8])
            ci = col_of(hd, "외국인")
            if ci is None:
                PROBE.setdefault("ctx_nofrgn", []).append(code)
                continue
            m = pack_col(rows, ci)
            if m:
                frgn[code] = m
        except Exception as e:
            PROBE.setdefault("ctx_err", []).append("%s:%s" % (code, str(e)[:50]))
        time.sleep(0.25)
    if frgn:
        alld = sorted(set().union(*[set(m) for m in frgn.values()]))
        stat = {}
        for c, m in frgn.items():
            ds = sorted(m)
            prev = m[ds[-21]] if len(ds) >= 21 else None
            stat[c] = {"latest": round(m[ds[-1]], 2),
                       "d20_pp": round(m[ds[-1]] - prev, 2) if prev is not None else None}
        ctx["stock_frgn"] = {
            "dates": alld,
            "series": {c: [round(m[d], 2) if d in m else None for d in alld]
                       for c, m in frgn.items()},
            "stat": stat, "names": dict(CTX_STOCKS)}

    # 券商收盤價 → 距52週高（52週高由抓回的歷史自身計得，不引用外部欄位）
    brok = {}
    for code, _zh in CTX_BROKERS:
        if budget_left() < 25:
            PROBE["ctx_skipped"] = "budget"
            break
        try:
            hd, rows = sise_rows(sess, code, d1, d2)
            m = pack_col(rows, col_of(hd, "종가"))
            if m:
                brok[code] = m
            else:
                PROBE.setdefault("ctx_noclose", []).append(code)
        except Exception as e:
            PROBE.setdefault("ctx_err", []).append("%s:%s" % (code, str(e)[:50]))
        time.sleep(0.25)
    if brok:
        alld = sorted(set().union(*[set(m) for m in brok.values()]))
        stat = {}
        for c, m in brok.items():
            ds = sorted(m)[-252:]
            hi = max(m[d] for d in ds)
            cur = m[sorted(m)[-1]]
            stat[c] = {"price": round(cur), "hi52": round(hi),
                       "hi52_date": max(d for d in ds if m[d] == hi),
                       "vs_hi52": round(cur / hi - 1, 4)}
        ctx["brokers"] = {
            "dates": alld,
            "close": {c: [round(m[d]) if d in m else None for d in alld]
                      for c, m in brok.items()},
            "stat": stat, "names": dict(CTX_BROKERS)}

    ctx["asof"] = d2
    return ctx if (ctx.get("stock_frgn") or ctx.get("brokers")) else None


# --------------------------------------------------------- 前次狀態（時序）
def load_prev(path="index.html"):
    try:
        with open(path, encoding="utf-8") as f:
            html = f.read()
        i = html.find("const IND = ")
        if i < 0:
            return {}
        obj, _ = json.JSONDecoder().raw_decode(html[i + len("const IND = "):])
        return (obj or {}).get("etf") or {}
    except Exception as e:
        PROBE["prev_err"] = str(e)[:80]
        return {}


def merge_series(prev, day, aum, unit_value):
    s = (prev.get("series") or {}) if isinstance(prev, dict) else {}
    dates = list(s.get("dates") or [])
    a = list(s.get("aum") or [])
    u = list(s.get("unit_value") or [])
    while len(a) < len(dates):
        a.append(None)
    while len(u) < len(dates):
        u.append(None)
    if day in dates:
        i = dates.index(day)
        a[i], u[i] = aum, unit_value
    else:
        dates.append(day); a.append(aum); u.append(unit_value)
        order = sorted(range(len(dates)), key=lambda i: dates[i])
        dates = [dates[i] for i in order]
        a = [a[i] for i in order]
        u = [u[i] for i in order]
    return {"dates": dates, "aum": a, "unit_value": u}


def main():
    _T0[0] = time.time()
    os.makedirs("data", exist_ok=True)
    out_path = "data/krx_etf_indicators.json"
    prev = load_prev()
    sess = requests.Session()
    result = {"enabled": False, "par": PAR,
              "note": "槓桿ETF分項抓取失敗，本次沿用前次時序。"}
    try:
        items = naver_etf_list(sess)
        lev, inv = [], []
        for it in items:
            under, kind = classify(it)
            if kind is None:
                continue
            price = float(it.get("nowVal") or 0)
            msum = float(it.get("marketSum") or 0)          # 억원
            nav = float(it.get("nav") or 0)
            if price <= 0 or msum <= 0:
                continue
            rec = {"code": str(it.get("itemcode")), "name": str(it.get("itemname")),
                   "under": under, "price": price, "nav": nav,
                   "aum_tril": round(msum / 1e4, 4),         # 억원 → 兆₩
                   "units_eok": round(msum / price, 4),      # 億좌
                   "chg": float(it.get("changeRate") or 0),
                   # Naver 欄名為 amonut（來源端拼字如此），保留 amount 作備援
                   "val_bil": round(float(it.get("amonut") or it.get("amount") or 0) / 100.0, 2),
                   "vs_par": round(price / PAR - 1, 4)}
            (lev if kind == "lev" else inv).append(rec)
        # 診斷：命名規則若在來源端改版，這兩項會直接顯示在發布結果裡
        picked = {x["code"] for x in lev + inv}
        PROBE["known_missed"] = sorted(KNOWN - picked)
        PROBE["lev_names"] = [str(i.get("itemname"))[:32] for i in items
                              if any(k in str(i.get("itemname") or "") for k in LEV_KW)][:40]
        if not lev:
            raise RuntimeError("清單中找不到單股槓桿ETF（命名規則可能已變更）")
        lev.sort(key=lambda x: -x["aum_tril"])

        aum_tril = round(sum(x["aum_tril"] for x in lev), 3)
        units_eok = round(sum(x["units_eok"] for x in lev), 3)
        unit_value_tril = round(units_eok * PAR / 1e4, 3)     # 億좌×₩ → 兆₩
        below = sum(1 for x in lev if x["price"] < PAR)
        avg_vs_par = round(sum(x["vs_par"] for x in lev) / len(lev), 4)
        turn_bil = round(sum(x["val_bil"] for x in lev), 1)

        # 逐檔價格歷史 → 跌破發行價家數時序
        d2 = kst_today()
        hists, asof = {}, None
        for x in lev:
            # 預留 90 秒給後面的分母查詢；不足就停在這裡，已抓到的檔數照樣成圖
            if budget_left() < 90:
                PROBE["hist_truncated"] = {"done": len(hists), "of": len(lev)}
                break
            h = naver_price_hist(sess, x["code"], LIST_DATE, d2)
            if h:
                hists[x["code"]] = h
                asof = max(asof or "", max(h))
            time.sleep(0.25)
        ph = None
        if hists:
            alld = sorted({d for h in hists.values() for d in h})
            avg, cnt = [], []
            for d in alld:
                vs = [h[d] for h in hists.values() if d in h]
                avg.append(round(sum(v / PAR - 1 for v in vs) / len(vs) * 100, 2))
                cnt.append(sum(1 for v in vs if v < PAR))
            ph = {"dates": alld, "avg_pct_par": avg, "below_par": cnt,
                  "n_track": len(hists)}
        asof = asof or d2

        series = merge_series(prev, asof, aum_tril, unit_value_tril)
        # 5 日規模變化（需累積足夠天數才有值）
        aum_hist = [v for v in series["aum"] if v is not None]
        aum_d5 = round(aum_hist[-1] / aum_hist[-6] - 1, 4) if len(aum_hist) >= 6 else None
        unit_peak = round(max([UNIT_SEED_TRIL] + [v for v in series["unit_value"] if v]), 3)
        aum_peak = round(max([AUM_SEED_TRIL] + [v for v in series["aum"] if v]), 3)

        # 分母：全體 ETF 規模（억원）；假日往前找最近有值的一天
        # 兩個分母都是選配：抓不到就讓對應欄位留空，主體讀數不受影響
        all_etf = None
        day = datetime.strptime(asof, "%Y%m%d")
        for k in range(6):
            if budget_left() < 45:
                PROBE["kofia_skipped"] = "budget"
                break
            try:
                v = kofia_all_etf(sess, (day - timedelta(days=k)).strftime("%Y%m%d"))
            except Exception as e:
                PROBE.setdefault("kofia_err", []).append(str(e)[:60]); v = None
            if v:
                all_etf = round(v / 1e4, 1)                   # 억원 → 兆₩
                break
        # 風險敞口分母：三星電子＋SK海力士市值
        mcap = None
        if budget_left() > 20:
            m1, m2 = naver_mcap(sess, "005930"), naver_mcap(sess, "000660")
            if m1 and m2:
                mcap = round((m1 + m2) / 1e4, 1)              # 兆₩
        else:
            PROBE["mcap_skipped"] = "budget"

        result = {
            "enabled": True,
            "asof": asof,
            "par": PAR,
            "n_lev": len(lev),
            "n_inv": len(inv),
            "aum_tril": aum_tril,
            "units_eok": units_eok,
            "unit_value_tril": unit_value_tril,
            "unit_peak_tril": unit_peak,
            "aum_peak_tril": aum_peak,
            "aum_vs_peak": round(aum_tril / aum_peak - 1, 4) if aum_peak else None,
            "remaining": round(min(1.0, unit_value_tril / unit_peak), 4) if unit_peak else None,
            "below_par": below,
            "avg_vs_par": avg_vs_par,
            "turn_bil": turn_bil,
            "aum_d5": aum_d5,
            "all_etf_tril": all_etf,
            "share_of_all_etf": round(aum_tril / all_etf * 100, 3) if all_etf else None,
            "under_mcap_tril": mcap,
            "exposure_pct": round(aum_tril * 2 / mcap * 100, 3) if mcap else None,
            "items": lev + inv,
            "price_hist": ph,
            "series": series,
            "tracking_since": series["dates"][0] if series["dates"] else asof,
            "source": "Naver 金融公開行情 API＋KOFIA 基金統計（皆免登入）",
        }
    except Exception as e:
        PROBE["fatal"] = str(e)[:200]
        if prev:
            for k in ("series", "price_hist", "tracking_since"):
                if prev.get(k):
                    result[k] = prev[k]
        print("ETF fetch failed:", e, file=sys.stderr)

    # 交叉驗證數據：獨立於主體之外，任何失敗都不影響上方 ETF 讀數
    try:
        ctx = fetch_ctx(sess)
        if ctx:
            result["ctx"] = ctx
    except Exception as e:
        PROBE["ctx_fatal"] = str(e)[:120]

    PROBE["elapsed_s"] = round(time.time() - _T0[0], 1)
    result["probe"] = PROBE
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print("ETF:", "OK" if result.get("enabled") else "FAILED",
          "n=", result.get("n_lev"), "aum=", result.get("aum_tril"),
          "below_par=", result.get("below_par"), "probe=", json.dumps(PROBE)[:300])


if __name__ == "__main__":
    main()
