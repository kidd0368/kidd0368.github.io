# -*- coding: utf-8 -*-
"""
台股波動率監控 — GitHub Actions 自動更新管線
  python pipeline.py update    抓證交所/櫃買公開資料,補齊缺的交易日
  python pipeline.py build     由 metrics.csv 產出 ../taiwan-vol/index.html
  python pipeline.py selftest  用狀態檔重算最後一天,對照 metrics.csv 驗證計算一致

資料流:
  data/metrics.csv        每日市場指標(種子:CMoney 2018→2026/07;其後:公開資料)
  data/state_returns.csv  近90交易日 × 全股票 漲跌幅(強勢股/離散度計算用)
  data/state_caps.csv     個股市值(億,以日報酬近似遞推)
  data/state_meta.csv     個股歷史觀測日數(上市未滿5日者排除)
"""
import json, os, re, sys, time
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
OUT_HTML = os.path.normpath(os.path.join(BASE, '..', 'taiwan-vol', 'index.html'))
TPL = os.path.join(BASE, 'template.html')

LOOKBACK, TOP_PCT, MIN_CAP, MIN_OBS, MIN_UNIV = 20, 0.15, 50.0, 15, 300
LD_WIN, LD_TOP, LD_CAP, LD_SHARE = 40, 0.15, 200.0, 0.3   # 主流代表股:40日動能前15%×市值≥200億×成交比重≥0.3%
STATE_DAYS, MAX_CATCHUP = 90, 15
CODE_RE = re.compile(r'^[1-9][0-9]{3}$')   # 4碼普通股(排除00xx ETF/權證/特別股/TDR)
TW_TZ = timezone(timedelta(hours=8))

EVENTS = {
    '2018-02-06': '美股VIX風暴重挫', '2018-10-11': '全球股災(美債殖利率急升)',
    '2020-01-30': 'COVID疫情爆發後春節開盤', '2020-03-12': 'COVID全球恐慌性拋售',
    '2020-03-13': 'COVID恐慌延續', '2020-03-19': 'COVID恐慌低點', '2020-03-20': 'COVID恐慌後急反彈',
    '2020-03-23': 'COVID恐慌尾聲', '2021-05-12': '本土疫情爆發', '2021-05-17': '本土疫情恐慌賣壓',
    '2021-05-18': '本土疫情恐慌後反彈', '2024-08-02': '日圓急升+美國景氣疑慮',
    '2024-08-05': '日圓套利平倉全球股災(當時史上最大跌點)', '2024-08-06': '股災後反彈',
    '2024-09-04': '美國半導體股重挫', '2025-04-07': '美國對等關稅衝擊,史上最大單日跌幅',
    '2025-04-08': '關稅恐慌延續', '2025-04-09': '關稅恐慌延續', '2025-04-10': '美方宣布關稅暫緩90天,大反彈',
    '2026-06-08': '全球AI/科技股賣壓,台積電盤中重挫', '2026-06-10': '科技股賣壓延續',
    '2026-06-24': '美科技股重挫拖累', '2026-06-26': '史上第三大跌點,失守45,000',
    '2026-07-17': '717慘案:崩跌2,953點,史上最大跌點',
}

# ------------------------------------------------------------------ 抓取 ----

def _get(url, **kw):
    import requests
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0 (taiwan-vol dashboard; github actions)'}, **kw)
            if r.status_code == 200:
                return r
        except Exception as e:
            print(f'  [warn] {url} 第{attempt+1}次失敗: {e}')
        time.sleep(3 + attempt * 3)
    return None


def _f(x):
    """字串轉float,容忍逗號/空白/--/X;失敗回None"""
    if x is None: return None
    s = str(x).replace(',', '').replace(' ', '').strip()
    if s in ('', '--', '---', '----', 'X', 'NaN', 'null', '-'): return None
    try: return float(s)
    except ValueError: return None


def _pct_from(close, chg):
    """以收盤與帶號漲跌價差回推漲跌幅(%)"""
    if close is None or chg is None: return None
    prev = close - chg
    if prev <= 0: return None
    return chg / prev * 100.0


def fetch_twse(date):
    """證交所 MI_INDEX(全部不含權證):回 (taiex_close, {code: pct}, {code: close}) 或 (None,None,{})=休市/失敗"""
    ds = date.strftime('%Y%m%d')
    r = _get(f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ds}&type=ALLBUT0999&response=json')
    if r is None: return None, None, {}
    try: j = r.json()
    except Exception: return None, None, {}
    if j.get('stat') != 'OK' or not j.get('tables'): return None, None, {}, {}
    taiex, stocks, closes, turns = None, {}, {}, {}
    for t in j['tables']:
        fields = t.get('fields') or []
        title = t.get('title') or ''
        if '收盤指數' in fields and taiex is None:
            i_name, i_close = fields.index(fields[0]), fields.index('收盤指數')
            for row in t.get('data') or []:
                if str(row[0]).strip().startswith('發行量加權股價指數'):
                    taiex = _f(row[i_close]); break
        if '證券代號' in fields and '收盤價' in fields and '漲跌價差' in fields:
            ic = fields.index('證券代號'); ip = fields.index('收盤價'); id_ = fields.index('漲跌價差')
            iv = fields.index('成交金額') if '成交金額' in fields else None
            isign = next((k for k, f0 in enumerate(fields) if '漲跌(' in f0), None)
            for row in t.get('data') or []:
                code = str(row[ic]).strip()
                if not CODE_RE.match(code): continue
                close, diff = _f(row[ip]), _f(row[id_])
                sgn = 0
                if isign is not None:
                    cell = str(row[isign])
                    if '+' in cell: sgn = 1
                    elif '-' in cell: sgn = -1
                pct = _pct_from(close, (diff or 0) * sgn)
                if pct is not None:
                    stocks[code] = pct
                    closes[code] = close
                    if iv is not None:
                        tv = _f(row[iv])
                        if tv: turns[code] = tv / 1000.0        # 元→千元(與種子一致)
    return taiex, (stocks or None), closes, turns


def fetch_twse_openapi_fallback(date):
    """備援:openapi 只有最新交易日。FMTQIK補指數(整月)、STOCK_DAY_ALL補個股"""
    ds_roc = f'{date.year - 1911}{date.strftime("%m%d")}'
    taiex, stocks, closes, turns = None, {}, {}, {}
    r = _get('https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK')
    if r is not None:
        try:
            for row in r.json():
                if str(row.get('Date')) == ds_roc:
                    taiex = _f(row.get('TAIEX')); break
        except Exception: pass
    r = _get('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL')
    if r is not None:
        try:
            for row in r.json():
                if str(row.get('Date')) != ds_roc: continue
                code = str(row.get('Code', '')).strip()
                if not CODE_RE.match(code): continue
                close = _f(row.get('ClosingPrice'))
                pct = _pct_from(close, _f(row.get('Change')))
                if pct is not None:
                    stocks[code] = pct
                    closes[code] = close
                    tv = _f(row.get('TradeValue'))
                    if tv: turns[code] = tv / 1000.0
        except Exception: pass
    return taiex, (stocks or None), closes, turns


def fetch_tpex(date):
    """櫃買:多端點嘗試。回 (otc_index_close, {code: pct}, {code: close}, {code: 成交金額千元});任一項可為None/{}"""
    roc = f'{date.year - 1911}/{date.strftime("%m/%d")}'
    iso = date.strftime('%Y/%m/%d')
    idx, stocks, closes, turns = None, {}, {}, {}

    # --- 個股候選端點 ---
    cands = [
        ('https://www.tpex.org.tw/www/zh-tw/afterTrading/otc', {'date': iso, 'response': 'json'}),
        ('https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php',
         {'l': 'zh-tw', 'd': roc, 'se': 'EW', 'o': 'json'}),
        ('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes', None),
    ]
    for url, params in cands:
        r = _get(url, params=params) if params else _get(url)
        if r is None: continue
        try: j = r.json()
        except Exception: continue
        got = _parse_tpex_stocks(j, date)
        if got:
            stocks, closes, turns = got
            print(f'  [tpex] 個股來源: {url.split("tpex.org.tw")[-1]} ({len(stocks)}檔)')
            break

    # --- 櫃買指數候選端點 ---
    icands = [
        ('https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyIndex', {'date': iso, 'response': 'json'}),
        ('https://www.tpex.org.tw/web/stock/iNdex_info/inxh/Inxh_result.php',
         {'l': 'zh-tw', 'd': f'{date.year - 1911}/{date.strftime("%m")}', 'o': 'json'}),
        ('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_highlight', None),
    ]
    for url, params in icands:
        r = _get(url, params=params) if params else _get(url)
        if r is None: continue
        try: j = r.json()
        except Exception: continue
        got = _parse_tpex_index(j, date)
        if got is not None:
            idx = got
            print(f'  [tpex] 指數來源: {url.split("tpex.org.tw")[-1]} = {got}')
            break
    return idx, (stocks or None), closes, turns


def _iter_row_dicts(j):
    """從各種JSON容器擠出list-of-dict或(fields,data)表"""
    if isinstance(j, list) and j and isinstance(j[0], dict):
        yield None, j
    if isinstance(j, dict):
        for key in ('tables',):
            for t in (j.get(key) or []):
                if isinstance(t, dict) and t.get('fields') and t.get('data') is not None:
                    yield t.get('fields'), t.get('data')
        if j.get('fields') and j.get('data') is not None:
            yield j.get('fields'), j.get('data')
        if isinstance(j.get('aaData'), list):
            yield None, j.get('aaData')


def _roc_match(s, date):
    s = str(s).replace('/', '').replace('-', '').strip()
    return s in (f'{date.year - 1911}{date.strftime("%m%d")}', date.strftime('%Y%m%d'))


def _parse_tpex_stocks(j, date):
    out, oc, ot = {}, {}, {}
    for fields, data in _iter_row_dicts(j):
        if fields:  # 表格式:欄名找 代號/收盤/漲跌/成交金額
            def col(*names):
                for k, f0 in enumerate(fields):
                    if any(nm in str(f0) for nm in names): return k
                return None
            ic, ip, ich = col('代號', 'Code'), col('收盤', 'Close'), col('漲跌', 'Change')
            iv = col('成交金額', 'Amount', 'TradeValue')
            if ic is None or ip is None or ich is None: continue
            for row in data:
                code = str(row[ic]).strip()
                if not CODE_RE.match(code): continue
                close = _f(row[ip])
                pct = _pct_from(close, _f(row[ich]))
                if pct is not None:
                    out[code] = pct; oc[code] = close
                    if iv is not None:
                        tv = _f(row[iv])
                        if tv: ot[code] = tv / 1000.0
        else:
            for row in data:
                if isinstance(row, dict):  # openapi list-of-dict
                    dkey = next((k for k in row if 'Date' in k or k == '日期'), None)
                    if dkey and not _roc_match(row[dkey], date): continue
                    code = next((str(row[k]).strip() for k in row if 'Code' in k or '代號' in str(k)), '')
                    if not CODE_RE.match(code): continue
                    close = next((_f(row[k]) for k in row if 'Close' in k or '收盤' in str(k)), None)
                    chg = next((_f(row[k]) for k in row if ('Change' in k and 'Percent' not in k) or str(k) == '漲跌'), None)
                    pct = _pct_from(close, chg)
                    if pct is not None:
                        out[code] = pct; oc[code] = close
                        tv = next((_f(row[k]) for k in row if 'TransactionAmount' in k or 'TradeValue' in k or '成交金額' in str(k)), None)
                        if tv: ot[code] = tv / 1000.0
                elif isinstance(row, list) and len(row) >= 4:  # aaData: [代號,名稱,收盤,漲跌,...]
                    code = str(row[0]).strip()
                    if not CODE_RE.match(code): continue
                    close = _f(row[2])
                    pct = _pct_from(close, _f(row[3]))
                    if pct is not None:
                        out[code] = pct; oc[code] = close
    return (out, oc, ot) if len(out) >= 200 else None   # 上櫃普通股應有數百檔


def _parse_tpex_index(j, date):
    # 月表(Inxh):rows [日期,開,高,低,收] → 找當日
    for fields, data in _iter_row_dicts(j):
        for row in data:
            if isinstance(row, list) and len(row) >= 5 and _roc_match(row[0], date):
                v = _f(row[4]) or _f(row[1])
                if v and 50 < v < 5000: return v
            if isinstance(row, dict):
                dkey = next((k for k in row if 'Date' in k or k == '日期'), None)
                if dkey and _roc_match(row[dkey], date):
                    for k in row:
                        if any(nm in str(k) for nm in ('櫃買指數', 'Index', '收盤指數', 'TPEX')):
                            v = _f(row[k])
                            if v and 50 < v < 5000: return v
    return None

# ------------------------------------------------------------------ 狀態與計算 ----

def load_state():
    R = pd.read_csv(os.path.join(DATA, 'state_returns.csv'), index_col=0)
    T = pd.read_csv(os.path.join(DATA, 'state_turnover.csv'), index_col=0)
    caps = pd.read_csv(os.path.join(DATA, 'state_caps.csv'), index_col=0)['cap']
    meta = pd.read_csv(os.path.join(DATA, 'state_meta.csv'), index_col=0)['obs']
    caps.index = caps.index.astype(str); meta.index = meta.index.astype(str)
    R.columns = R.columns.astype(str); T.columns = T.columns.astype(str)
    return R, T, caps, meta


def save_state(R, T, caps, meta):
    R.tail(STATE_DAYS).round(2).to_csv(os.path.join(DATA, 'state_returns.csv'), encoding='utf-8')
    T.tail(STATE_DAYS).round(0).to_csv(os.path.join(DATA, 'state_turnover.csv'), encoding='utf-8')
    caps.round(2).to_csv(os.path.join(DATA, 'state_caps.csv'), encoding='utf-8')
    meta.astype(int).to_csv(os.path.join(DATA, 'state_meta.csv'), encoding='utf-8')


def compute_day(R_hist, today, caps_prev, meta_prev, T_hist=None, today_turn=None):
    """R_hist: 不含今天的狀態寬表; today: Series(code→pct)。回當日指標dict"""
    today = today.clip(-10, 10)
    obs_after = meta_prev.reindex(today.index).fillna(0) + 1
    eligible = today[obs_after >= 6]                      # 排除上市未滿5日
    row = {'n': int(len(eligible))}

    # ---- 主流代表股(40日動能×市值×成交金額比重,選股基準到t-1) ----
    if T_hist is not None and len(T_hist) >= 30 and len(R_hist) >= 30:
        t40 = T_hist.tail(LD_WIN)
        share40 = t40.mean() / t40.sum(axis=1).mean() * 100
        mom40 = np.log1p(R_hist.tail(LD_WIN) / 100).sum(min_count=30)
        rk = mom40.rank(pct=True)
        cap_ok = caps_prev.reindex(mom40.index) >= LD_CAP
        sel = (rk >= 1 - LD_TOP) & cap_ok & (share40.reindex(mom40.index) >= LD_SHARE)
        cols = [c for c in sel.index[sel.fillna(False)] if c in today.index and pd.notna(today[c])]
        if len(cols) >= 5:
            seg = R_hist[cols].tail(LD_WIN - 1).fillna(0)
            arr = np.vstack([seg.values, today[cols].values.reshape(1, -1)])
            cum = np.cumprod(1 + arr / 100, axis=0)
            dd = (cum[-1] / cum.max(axis=0) - 1) * 100
            row.update(ld_n=int(len(cols)),
                       ld_share=float(share40.reindex(cols).sum()),
                       ld_abs=float(today[cols].abs().mean()),
                       ld_dd=float(np.nanmean(dd)))
    if len(eligible) >= MIN_UNIV:
        a = eligible.values
        row.update(disp=float(np.std(a, ddof=1)), absmove=float(np.abs(a).mean()),
                   pct5=float((np.abs(a) >= 5).mean() * 100), adv=float((a > 0).mean() * 100))
    # 強勢股:R_hist最後LOOKBACK列(=t-20..t-1)
    tail = R_hist.tail(LOOKBACK)
    if len(tail) >= MIN_OBS:
        mom = np.log1p(tail / 100).sum(min_count=MIN_OBS)
        mom = mom[mom.index.isin(eligible.index)]
        capf = caps_prev.reindex(mom.index)
        mom = mom[capf >= MIN_CAP].dropna()
        if len(mom) >= MIN_UNIV:
            k = max(30, int(len(mom) * TOP_PCT))
            strong = mom.nlargest(k).index
            rs = eligible.reindex(strong).dropna()
            base = eligible.reindex(mom.index).dropna()
            if len(rs) >= 20:
                row.update(s_mean=float(rs.mean()), s_abs=float(rs.abs().mean()),
                           s_lim=float((rs.abs() >= 9).mean() * 100), s_k=int(len(rs)),
                           mkt50_abs=float(base.abs().mean()))
    return row


def cmd_update():
    mfile = os.path.join(DATA, 'metrics.csv')
    m = pd.read_csv(mfile)
    last = datetime.strptime(m['date'].iloc[-1], '%Y-%m-%d').date()
    now_tw = datetime.now(TW_TZ)
    end = now_tw.date()
    if now_tw.hour < 16 or (now_tw.hour == 16 and now_tw.minute < 30):
        end = end - timedelta(days=1)     # 當日資料尚未完整發布
    days = []
    d = last + timedelta(days=1)
    while d <= end and len(days) < MAX_CATCHUP:
        if d.weekday() < 5: days.append(d)
        d += timedelta(days=1)
    if not days:
        print('已是最新,無需更新。'); return
    print(f'嘗試補 {len(days)} 個平日: {days[0]} → {days[-1]}')

    R, T, caps, meta = load_state()
    added = 0
    for d0 in days:
        print(f'[{d0}]')
        taiex, stocks, closes, turns = fetch_twse(d0)
        if stocks is None and taiex is None:
            taiex, stocks, closes, turns = fetch_twse_openapi_fallback(d0)
        if stocks is None and taiex is None:
            print('  休市或無資料,跳過'); time.sleep(2); continue
        otc_idx, otc_stocks, otc_closes, otc_turns = fetch_tpex(d0)
        allst = dict(stocks or {})
        if otc_stocks: allst.update(otc_stocks)
        allcl = dict(closes or {})
        if otc_closes: allcl.update(otc_closes)
        alltv = dict(turns or {})
        if otc_turns: alltv.update(otc_turns)
        today = pd.Series(allst, dtype=float)
        today_turn = pd.Series(alltv, dtype=float)
        print(f'  上市{len(stocks or {})}檔 + 上櫃{len(otc_stocks or {})}檔 | 加權={taiex} 櫃買={otc_idx} | 成交金額{len(alltv)}檔')

        row = {'date': d0.strftime('%Y-%m-%d'),
               'taiex_close': taiex, 'otc_close': otc_idx}
        row.update(compute_day(R, today, caps, meta, T, today_turn))

        # 更新狀態
        newrow = today.clip(-10, 10)
        R = pd.concat([R, newrow.to_frame(d0.strftime('%Y-%m-%d')).T]).tail(STATE_DAYS + 5)
        T = pd.concat([T, today_turn.to_frame(d0.strftime('%Y-%m-%d')).T]).tail(STATE_DAYS + 5)
        for c in newrow.index:
            meta[c] = meta.get(c, 0) + 1
            if c in caps.index and pd.notna(caps.get(c)):
                caps[c] = caps[c] * (1 + newrow[c] / 100)

        # 每月自動市值校正:當月第一個成功處理的交易日,用公開股本×收盤價重算
        calfile = os.path.join(DATA, 'state_calib.txt')
        last_cal = open(calfile).read().strip() if os.path.exists(calfile) else '2000-01'
        if d0.strftime('%Y-%m') > last_cal and allcl:
            if calibrate_caps(caps, allcl):
                with open(calfile, 'w') as f:
                    f.write(d0.strftime('%Y-%m'))

        m = pd.concat([m, pd.DataFrame([row])], ignore_index=True)
        added += 1
        time.sleep(3)

    # 自癒:歷史列若缺指數收盤價(端點當晚失敗或種子缺日),重試官方來源回補(每次最多10列)
    healed = 0
    for c in ('taiex_close', 'otc_close'):
        m[c] = pd.to_numeric(m[c], errors='coerce')
    holes = m.index[m['taiex_close'].isna() | m['otc_close'].isna()]
    for i in list(holes)[-10:]:
        d0 = datetime.strptime(m.at[i, 'date'], '%Y-%m-%d').date()
        if pd.isna(m.at[i, 'taiex_close']):
            tv, _, _, _ = fetch_twse(d0)
            if tv is not None:
                m.at[i, 'taiex_close'] = tv; healed += 1
                print(f'  [heal] 回補 {d0} 加權指數 = {tv}')
            time.sleep(2)
        if pd.isna(m.at[i, 'otc_close']):
            ov, _, _, _ = fetch_tpex(d0)
            if ov is not None:
                m.at[i, 'otc_close'] = ov; healed += 1
                print(f'  [heal] 回補 {d0} 櫃買指數 = {ov}')
            time.sleep(2)

    if added or healed:
        for c in ['disp', 'absmove', 's_mean', 's_abs', 'mkt50_abs']:
            if c in m: m[c] = pd.to_numeric(m[c], errors='coerce').round(4)
        m.to_csv(mfile, index=False, encoding='utf-8')
        if added:
            save_state(R, T, caps, meta)
    print(f'完成:新增 {added} 個交易日,回補 {healed} 個缺值。')

# ------------------------------------------------------------------ 市值校正 ----

def fetch_shares():
    """公開的公司基本資料 → {code: 發行股數}(實收資本額÷面額10)"""
    shares = {}
    for url in ('https://openapi.twse.com.tw/v1/opendata/t187ap03_L',
                'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O'):
        r = _get(url)
        if r is None:
            print(f'  [calib] 無法連線: {url}'); continue
        try: rows = r.json()
        except Exception:
            print(f'  [calib] 非JSON回應: {url}'); continue
        got = 0
        for row in rows:
            if not isinstance(row, dict): continue
            code = str(row.get('公司代號') or row.get('SecuritiesCompanyCode') or row.get('Code') or '').strip()
            capi = _f(row.get('實收資本額') or row.get('Paidin.Capital.NTDollars') or row.get('PaidinCapitalNTDollars'))
            if CODE_RE.match(code) and capi and capi > 0:
                shares[code] = capi / 10.0
                got += 1
        print(f'  [calib] {url.split("/v1/")[-1]}: {got} 檔股本')
    return shares


def calibrate_caps(caps, closes):
    """市值(億) = 收盤價 × 股數 ÷ 1e8。回傳是否校正成功"""
    shares = fetch_shares()
    if len(shares) < 500:
        print(f'  [calib] 股本資料不足({len(shares)}檔),本次跳過,市值續用遞推值')
        return False
    n = 0
    for code, close in closes.items():
        if close and code in shares:
            caps[code] = close * shares[code] / 1e8
            n += 1
    print(f'  [calib] 市值校正完成: {n} 檔')
    return n >= 500


def cmd_calibrate():
    """手動校正:抓最新收盤價+股本,重算市值檔"""
    from datetime import date as _date
    R, T, caps, meta = load_state()
    closes = {}
    _, _, c1, _ = fetch_twse_openapi_fallback(datetime.now(TW_TZ).date())
    closes.update(c1 or {})
    if len(closes) < 500:   # openapi以日期過濾可能落空,放寬:直接取STOCK_DAY_ALL全部
        r = _get('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL')
        if r is not None:
            try:
                for row in r.json():
                    code = str(row.get('Code', '')).strip()
                    if CODE_RE.match(code):
                        v = _f(row.get('ClosingPrice'))
                        if v: closes[code] = v
            except Exception: pass
    _, _, c2, _ = fetch_tpex(datetime.now(TW_TZ).date())
    closes.update(c2 or {})
    print(f'取得 {len(closes)} 檔收盤價')
    if calibrate_caps(caps, closes):
        save_state(R, T, caps, meta)
        with open(os.path.join(DATA, 'state_calib.txt'), 'w') as f:
            f.write(datetime.now(TW_TZ).strftime('%Y-%m'))
        print('已寫回 state_caps.csv')

# ------------------------------------------------------------------ 盤勢定位 ----

def compute_regime(close):
    """四象限:多空(價格vs半年線+距一年高點) × 穩定度(波動分位+升溫+大波動日) + 各象限前瞻統計"""
    c = close.dropna()
    lr = np.log(c / c.shift(1)) * 100
    ret = (c / c.shift(1) - 1) * 100
    v20 = lr.rolling(20).std(ddof=1) * np.sqrt(252)
    v20_pct = v20.rank(pct=True) * 100
    ma120 = c.rolling(120).mean()
    dd252 = c / c.rolling(252).max() - 1
    bigd = (ret.abs() >= 1.5).rolling(20).sum()
    rise = v20 - v20.shift(20)
    bull = (c > ma120) & (dd252 > -0.10)
    bear = (c < ma120) & (dd252 < -0.10)
    unstable = ((v20_pct >= 70) & (rise > 0)) | (v20_pct >= 90)
    q = pd.Series('T', index=c.index)
    q[bull & ~unstable] = 'Q1'
    q[bull & unstable] = 'Q2'
    q[bear & unstable] = 'Q3'
    q[bear & ~unstable] = 'Q4'
    q[ma120.isna() | dd252.isna() | v20_pct.isna()] = None

    fwd60 = c.shift(-60) / c - 1
    fmin60 = (c.shift(-1).rolling(60).min().shift(-59)) / c - 1
    fmax60 = (c.shift(-1).rolling(60).max().shift(-59)) / c - 1
    stats = []
    for k in ('Q1', 'Q2', 'Q3', 'Q4', 'T'):
        msk = (q == k) & fwd60.notna()
        n = int(msk.sum())
        if n == 0: continue
        stats.append({'q': k, 'n': n,
                      'f60': round(float(fwd60[msk].median() * 100), 1),
                      'win': round(float((fwd60[msk] > 0).mean() * 100)),
                      'dn10': round(float((fmin60[msk] < -0.10).mean() * 100)),
                      'up10': round(float((fmax60[msk] > 0.10).mean() * 100))})
    i = q.last_valid_index()
    cur = None
    if i is not None and q[i] is not None:
        cur = {'q': q[i],
               'v20pct': round(float(v20_pct[i])), 'rise': round(float(rise[i]), 1),
               'dd252': round(float(dd252[i] * 100), 1), 'bigd': int(bigd[i]),
               'above_ma': bool(c[i] > ma120[i])}
    return {'cur': cur, 'stats': stats}

# ------------------------------------------------------------------ 主流代表股快照 ----

def current_leaders():
    """由狀態檔算出「現在」的主流代表股清單(選股窗含最後一天,純快照展示)"""
    try:
        R, T, caps, meta = load_state()
        try:
            names = pd.read_csv(os.path.join(DATA, 'names.csv'), index_col=0)['name']
            names.index = names.index.astype(str)
        except Exception:
            names = pd.Series(dtype=object)
        t40 = T.tail(LD_WIN)
        share40 = t40.mean() / t40.sum(axis=1).mean() * 100
        mom40 = np.log1p(R.tail(LD_WIN) / 100).sum(min_count=30)
        rk = mom40.rank(pct=True)
        sel = (rk >= 1 - LD_TOP) & (caps.reindex(mom40.index) >= LD_CAP) \
              & (share40.reindex(mom40.index) >= LD_SHARE)
        cols = [c for c in sel.index[sel.fillna(False)]]
        if len(cols) < 3: return None
        seg = R[cols].tail(LD_WIN).fillna(0)
        cum = (1 + seg / 100).cumprod()
        dd = (cum.iloc[-1] / cum.max() - 1) * 100
        momp = np.expm1(mom40[cols]) * 100
        lastchg = R[cols].iloc[-1]
        rows = []
        for cd in cols:
            rows.append({'code': cd, 'name': str(names.get(cd, cd)),
                         'mom': round(float(momp[cd]), 1),
                         'cap': int(round(float(caps.get(cd, 0)))),
                         'share': round(float(share40[cd]), 2),
                         'dd': round(float(dd[cd]), 1),
                         'chg': None if pd.isna(lastchg[cd]) else round(float(lastchg[cd]), 2)})
        rows.sort(key=lambda r: -r['share'])
        return {'rows': rows[:15],
                'share': round(float(share40[cols].sum()), 1),
                'n': int(len(cols)),
                'asof': str(R.index[-1])}
    except Exception as e:
        print(f'  [leaders] 快照失敗: {e}')
        return None

# ------------------------------------------------------------------ 產頁 ----

def cmd_build():
    m = pd.read_csv(os.path.join(DATA, 'metrics.csv'))
    for c in m.columns:
        if c != 'date': m[c] = pd.to_numeric(m[c], errors='coerce')

    def idx_series(close):
        """個別日期缺收盤價時,在「有值的子序列」上算報酬與滾動波動,再對回原索引(缺日不會炸斷整段窗)"""
        c = close.dropna()
        lr_c = np.log(c / c.shift(1)) * 100
        ret_c = (c / c.shift(1) - 1) * 100
        out = {}
        for w in (20, 60, 252):
            out[w] = (lr_c.rolling(w).std(ddof=1) * np.sqrt(252)).reindex(close.index)
        return ret_c.reindex(close.index), out

    ret, tv = idx_series(m['taiex_close'])
    v20, v60, v252 = tv[20], tv[60], tv[252]
    _, ov = idx_series(m['otc_close'])
    ov20 = ov[20]
    roll = lambda s, w=20, mp=15: s.rolling(w, min_periods=mp).mean()
    disp20 = roll(m['disp'])
    am20 = roll(m['absmove'])
    p520 = roll(m['pct5'])
    sabs20 = roll(m['s_abs'])
    mabs20 = roll(m['mkt50_abs'])
    heat = sabs20 / mabs20
    svol20 = m['s_mean'].rolling(20, min_periods=15).std(ddof=1) * np.sqrt(252)
    ldabs20 = roll(m['ld_abs']) if 'ld_abs' in m else pd.Series(np.nan, index=m.index)
    for c in ('ld_share', 'ld_dd', 'ld_n'):
        if c not in m: m[c] = np.nan

    r2 = lambda s, nd: [None if pd.isna(v) else round(float(v), nd) for v in s]
    D = {'date': m['date'].tolist(), 'close': r2(m['taiex_close'], 1), 'ret': r2(ret, 2),
         'v20': r2(v20, 1), 'v60': r2(v60, 1), 'v252': r2(v252, 1), 'ov20': r2(ov20, 1),
         'disp': r2(m['disp'], 2), 'disp20': r2(disp20, 2), 'am20': r2(am20, 2),
         'p5': r2(m['pct5'], 1), 'p520': r2(p520, 1), 'adv': r2(m['adv'], 1),
         'sabs': r2(m['s_abs'], 2), 'sabs20': r2(sabs20, 2), 'mabs20': r2(mabs20, 2),
         'heat': r2(heat, 2), 'svol20': r2(svol20, 1), 'slim': r2(m['s_lim'], 1),
         'ldabs': r2(m['ld_abs'], 2), 'ldabs20': r2(ldabs20, 2),
         'ldshare': r2(m['ld_share'], 1), 'lddd': r2(m['ld_dd'], 1), 'ldn': r2(m['ld_n'], 0),
         'events': EVENTS,
         'regime': compute_regime(m.set_index('date')['taiex_close']),
         'leaders': current_leaders()}

    vv, hh = v20.dropna(), heat.dropna()
    li = m.index[v20.notna()][-1]
    pi = m.index[v20.notna()][-21] if v20.notna().sum() > 21 else li
    dd = disp20.dropna(); aa = am20.dropna(); oo = ov20.dropna()
    D['summary'] = {
        'asof': m['date'].iloc[-1], 'close': round(float(m['taiex_close'].dropna().iloc[-1]), 1),
        'v20': round(float(v20[li]), 1), 'v60': round(float(v60[li]), 1), 'v252': round(float(v252[li]), 1),
        'v20_chg': round(float(v20[li] - v20[pi]), 1),
        'v20_pct': round(float((vv <= v20[li]).mean() * 100)),
        'ov20': round(float(oo.iloc[-1]), 1),
        'ov20_chg': round(float(oo.iloc[-1] - oo.iloc[-21]), 1) if len(oo) > 21 else 0,
        'ov20_pct': round(float((oo <= oo.iloc[-1]).mean() * 100)),
        'disp20': round(float(dd.iloc[-1]), 2),
        'disp20_chg': round(float(dd.iloc[-1] - dd.iloc[-21]), 2) if len(dd) > 21 else 0,
        'disp20_pct': round(float((dd <= dd.iloc[-1]).mean() * 100)),
        'am20': round(float(aa.iloc[-1]), 2),
        'am20_chg': round(float(aa.iloc[-1] - aa.iloc[-21]), 2) if len(aa) > 21 else 0,
        'am20_pct': round(float((aa <= aa.iloc[-1]).mean() * 100)),
        'v20_med': round(float(vv.median()), 1), 'v20_max': round(float(vv.max()), 1),
        'v20_max_date': m['date'][v20.idxmax()],
        'n_stocks': int(m['n'].dropna().iloc[-1]),
        'span': m['date'].iloc[0].replace('-', '/') + ' – ' + m['date'].iloc[-1].replace('-', '/'),
        'days': int(len(m)),
    }
    if len(hh) > 21:
        D['summary'].update({
            'heat': round(float(hh.iloc[-1]), 2),
            'heat_chg': round(float(hh.iloc[-1] - hh.iloc[-21]), 2),
            'heat_pct': round(float((hh <= hh.iloc[-1]).mean() * 100)),
            'heat_med': round(float(hh.median()), 2),
            'svol20': round(float(svol20.dropna().iloc[-1]), 1),
            's_k': int(m['s_k'].dropna().iloc[-1]),
        })

    with open(TPL, encoding='utf-8') as f:
        html = f.read()
    html = html.replace('__DATA__', json.dumps(D, ensure_ascii=False, separators=(',', ':')))
    html = html.replace('__GENERATED__', datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M') + ' (台北時間)')
    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    with open(OUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    s = D['summary']
    print(f"已產出 {OUT_HTML}: 資料至 {s['asof']}, 20日波動 {s['v20']}%, 熱度比 {s.get('heat')}")

# ------------------------------------------------------------------ 自測 ----

def cmd_selftest():
    """用狀態檔重算最後一天,對照 metrics.csv(容忍微小捨入差)"""
    m = pd.read_csv(os.path.join(DATA, 'metrics.csv'))
    R, T, caps, meta = load_state()
    last_date = R.index[-1]
    today = R.iloc[-1].dropna()
    # 還原前一日的caps/meta
    caps_prev = caps.copy()
    for c in today.index:
        if c in caps_prev.index and pd.notna(caps_prev.get(c)):
            caps_prev[c] = caps_prev[c] / (1 + today[c] / 100)
    meta_prev = meta.copy()
    for c in today.index: meta_prev[c] = meta_prev.get(c, 1) - 1
    row = compute_day(R.iloc[:-1], today, caps_prev, meta_prev, T.iloc[:-1], T.iloc[-1].dropna())
    ref = m[m['date'] == last_date].iloc[0]
    okall = True
    for k, tol in [('disp', 0.03), ('absmove', 0.03), ('pct5', 0.5), ('adv', 0.5),
                   ('s_abs', 0.15), ('mkt50_abs', 0.05), ('s_k', 6),
                   ('ld_abs', 0.3), ('ld_dd', 1.5), ('ld_n', 5)]:
        a, b = row.get(k), ref.get(k)
        if a is None or pd.isna(b):
            print(f'  {k}: 略過(缺值 a={a} b={b})'); continue
        ok = abs(float(a) - float(b)) <= tol
        okall &= ok
        print(f'  {k}: 重算 {float(a):.3f} vs 種子 {float(b):.3f} {"✓" if ok else "✗ 超出容差"}')
    print('selftest:', 'PASS' if okall else 'FAIL', f'({last_date})')
    sys.exit(0 if okall else 1)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'update'
    {'update': cmd_update, 'build': cmd_build, 'selftest': cmd_selftest,
     'calibrate': cmd_calibrate}[cmd]()
