# -*- coding: utf-8 -*-
"""bond-watch 頁面產生器：曲線、拆解、期限溢價、折現率壓力、事件台帳。
用法：PAGE_PASSWORD=... python build_page.py
"""
import datetime as dt
import html as htmlmod
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fwcrypto

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
STORE_PATH = os.path.join(BASE, "data", "store.enc")
TPE = dt.timezone(dt.timedelta(hours=8))
W = 860


def esc(s):
    return htmlmod.escape(str(s if s is not None else ""), quote=True)


def md(text):
    t = esc(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return "".join("<p>%s</p>" % p.replace("\n", "<br>") for p in t.split("\n\n") if p.strip())


def bp(v, plus=True):
    if v is None:
        return "—"
    return ("%+.0f" % v if plus else "%.0f" % v) + " bp"


# ---------------- 曲線圖 ----------------

def curve_svg(snap, store):
    cur = [c for c in snap["curve"] if c.get("value") is not None]
    if len(cur) < 4:
        return '<p class="muted">曲線資料不足。</p>'
    H, PADL, PADR, TOP, BOT = 280, 52, 30, 30, 46
    import math
    xs = [math.log(c["years"]) for c in cur]
    x0, x1 = min(xs), max(xs)

    # 找 20 / 60 日前的曲線（用 store["series"] 回推）
    hist = {}
    for lb in (20, 60):
        pts = []
        for c in cur:
            rows = store.get("series", {}).get(c["id"]) or []
            if len(rows) > lb:
                pts.append((c["years"], rows[-1 - lb][1]))
        if len(pts) >= 4:
            hist[lb] = pts

    allv = [c["value"] for c in cur] + [v for pts in hist.values() for _y, v in pts]
    lo, hi = min(allv) - 0.15, max(allv) + 0.15

    def xy(years, v):
        x = PADL + (W - PADL - PADR) * (math.log(years) - x0) / (x1 - x0 or 1)
        y = H - BOT - (H - BOT - TOP) * (v - lo) / (hi - lo or 1)
        return x, y

    grid = ""
    g = round(lo * 4) / 4
    while g <= hi:
        _x, y = xy(cur[0]["years"], g)
        grid += ('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#293545" stroke-width="1"/>'
                 '<text x="4" y="%.1f" fill="#9ba8b7" font-size="10">%.2f%%</text>'
                 % (PADL, y, W - PADR, y, y + 3, g))
        g += 0.25

    body = ""
    for lb, col, dash in ((60, "#3d4c60", "4,4"), (20, "#6b7d94", "5,4")):
        if lb in hist:
            pts = " ".join("%.1f,%.1f" % xy(y, v) for y, v in hist[lb])
            body += ('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.8" '
                     'stroke-dasharray="%s"/>' % (pts, col, dash))
    coords = [xy(c["years"], c["value"]) for c in cur]
    body += ('<polyline points="%s" fill="none" stroke="#f6c453" stroke-width="2.8"/>'
             % " ".join("%.1f,%.1f" % c for c in coords))

    labels = ""
    for c, (cx, cy) in zip(cur, coords):
        chg = c["chg"].get("20")
        col = "#ff5c78" if (chg or 0) > 3 else ("#39c6be" if (chg or 0) < -3 else "#f6c453")
        body += '<circle cx="%.1f" cy="%.1f" r="3.4" fill="%s"/>' % (cx, cy, col)
        labels += ('<text x="%.1f" y="%d" fill="#9ba8b7" font-size="10" text-anchor="middle">%s</text>'
                   % (cx, H - 26, c["label"]))
        if c["label"] in ("3M", "2Y", "10Y", "30Y"):
            labels += ('<text x="%.1f" y="%.1f" fill="%s" font-size="10" font-weight="800" '
                       'text-anchor="middle">%.2f</text>' % (cx, cy - 9, col, c["value"]))
            labels += ('<text x="%.1f" y="%d" fill="%s" font-size="9" text-anchor="middle">%s</text>'
                       % (cx, H - 12, col, bp(chg)))
    legend = ('<tspan x="%d" fill="#f6c453">━ 今日</tspan>'
              '<tspan x="%d" fill="#6b7d94">┅ 20日前</tspan>'
              '<tspan x="%d" fill="#3d4c60">┅ 60日前</tspan>'
              % (PADL, PADL + 110, PADL + 220))
    return ('<svg viewBox="0 0 %d %d" role="img">%s%s%s'
            '<text x="%d" y="16" font-size="11">%s</text></svg>'
            '<p class="muted">下排為各期別 20 日變化（紅＝殖利率上升）。橫軸為對數天期。</p>'
            % (W, H, grid, body, labels, PADL, legend))


def trend_svg(store, sid, name, color):
    rows = (store.get("series", {}) or {}).get(sid) or []
    rows = rows[-260:]
    if len(rows) < 10:
        return ""
    H, PADL, PADR, TOP, BOT = 150, 52, 26, 22, 26
    vals = [v for _d, v in rows]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.12 or 0.1
    lo, hi = lo - pad, hi + pad

    def xy(i, v):
        x = PADL + (W - PADL - PADR) * i / (len(rows) - 1)
        y = H - BOT - (H - BOT - TOP) * (v - lo) / (hi - lo or 1)
        return x, y

    pts = " ".join("%.1f,%.1f" % xy(i, v) for i, (_d, v) in enumerate(rows))
    mx = max(rows, key=lambda r: r[1])
    mxx, mxy = xy(rows.index(mx), mx[1])
    grid = ""
    for frac in (0, 0.5, 1):
        v = lo + (hi - lo) * frac
        _x, y = xy(0, v)
        grid += ('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#293545" stroke-width="1"/>'
                 '<text x="4" y="%.1f" fill="#9ba8b7" font-size="10">%.2f</text>'
                 % (PADL, y, W - PADR, y, y + 3, v))
    return ('<svg viewBox="0 0 %d %d" role="img">%s'
            '<polyline points="%s" fill="none" stroke="%s" stroke-width="2"/>'
            '<circle cx="%.1f" cy="%.1f" r="3" fill="%s"/>'
            '<text x="%d" y="14" font-size="11" fill="%s">%s　現值 %.2f　區間高 %.2f (%s)</text>'
            '<text x="%d" y="%d" fill="#9ba8b7" font-size="9">%s</text>'
            '<text x="%d" y="%d" fill="#9ba8b7" font-size="9" text-anchor="end">%s</text></svg>'
            % (W, H, grid, pts, color, mxx, mxy, color, PADL, color, name,
               rows[-1][1], mx[1], mx[0], PADL, H - 8, rows[0][0], W - PADR, H - 8, rows[-1][0]))


# ---------------- 區塊 ----------------

def pressure_block(snap):
    p = snap.get("pressure") or {}
    score = p.get("score")
    if score is None:
        return '<p class="muted">壓力指數資料不足。</p>'
    if score >= 75:
        tone, txt = "#e03a5a", "高壓：長天期成長股折現率逆風強"
    elif score >= 55:
        tone, txt = "#ff5c78", "偏高：估值敏感度上升"
    elif score >= 35:
        tone, txt = "#f6c453", "中性"
    else:
        tone, txt = "#39c6be", "寬鬆：折現率順風"
    bars = ""
    for d in p.get("detail", []):
        bars += ('<div class="prow"><span class="pname">%s</span>'
                 '<div class="ptrack"><div class="pfill" style="width:%d%%;background:%s"></div></div>'
                 '<span class="pval">%s</span></div>'
                 % (esc(d["name"]), d["score"], tone,
                    esc(("%.2f" % d["value"]) if isinstance(d["value"], float) else d["value"])))
    return ('<div class="pwrap"><div class="pscore" style="color:%s">%d<span>/100</span></div>'
            '<div class="pmeta"><b style="color:%s">%s</b>'
            '<p class="muted">長端實質利率 35%%＋期限溢價 25%%＋30年水位 25%%＋20日動能 15%%。'
            '數值越高，長天期現金流（AI capex、成長股）的折現壓力越大。</p></div></div>%s'
            % (tone, score, tone, txt, bars))


def decomp_block(snap):
    dc = snap.get("decomposition") or {}
    if not dc:
        return '<p class="muted">拆解資料不足。</p>'
    rows = ""
    for tenor in ("5Y", "10Y", "30Y"):
        e = dc.get(tenor)
        if not e:
            continue
        c = e.get("chg20", {})
        rows += ('<tr><td><b>%s</b></td><td class="num">%.2f%%</td><td class="num">%.2f%%</td>'
                 '<td class="num">%.2f%%</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%s</td><td>%s</td></tr>'
                 % (tenor, e["nominal"], e["real"], e["be"],
                    bp(c.get("nominal")), bp(c.get("real")), bp(c.get("be")),
                    esc(e.get("driver", ""))))
    return ('<table><thead><tr><th>天期</th><th>名目</th><th>實質(TIPS)</th><th>通膨預期</th>'
            '<th>名目20日</th><th>實質20日</th><th>預期20日</th><th>驅動來源</th></tr></thead>'
            '<tbody>%s</tbody></table>'
            '<p class="muted">名目 ≈ 實質 + 通膨預期。若變動由實質利率主導，代表是成長、期限溢價或'
            '財政供給在推動，而非通膨——這對 Fed 政策路徑的意涵完全不同。</p>' % rows)


def spread_block(snap):
    sp = snap.get("spreads") or {}
    cards = ""
    for key in ("2s10s", "5s30s", "3m10y", "10s30s"):
        e = sp.get(key)
        if not e:
            continue
        c20 = e["chg"].get("20")
        col = "#ff5c78" if (c20 or 0) > 3 else ("#39c6be" if (c20 or 0) < -3 else "#9ba8b7")
        cards += ('<div class="scard"><span class="slab">%s</span>'
                  '<span class="sval">%.0f<em>bp</em></span>'
                  '<span class="schg" style="color:%s">20日 %s</span></div>'
                  % (esc(e["label"]), e["bp"], col, bp(c20)))
    return '<div class="srow">%s</div>' % cards


def events_block(events):
    if not events:
        return '<p class="muted">尚無事件（等金十 Token 或關鍵字命中）。</p>'
    out = ""
    for e in sorted(events, key=lambda x: x.get("time", ""), reverse=True)[:30]:
        tags = "".join('<span class="tag">%s</span>' % esc(t) for t in e.get("tags", [])[:4])
        link = (' <a href="%s" target="_blank" rel="noopener">原文</a>' % esc(e["url"])) if e.get("url") else ""
        out += ('<li><time>%s</time>%s<span class="etext">%s</span>%s</li>'
                % (esc((e.get("time") or "")[:16].replace("T", " ")), tags,
                   esc(e["text"][:260]), link))
    return "<ul class='events'>%s</ul>" % out


def commentary_block(comm):
    if not comm:
        return '<p class="muted">首篇解讀將於明早排程後出現。</p>'
    out = ""
    for c in sorted(comm, key=lambda x: x["date"], reverse=True)[:10]:
        out += '<article><h4>%s</h4>%s</article>' % (esc(c["date"]), md(c["text"]))
    return out


def main():
    password = os.environ.get("PAGE_PASSWORD", "").strip()
    if not password:
        sys.exit("PAGE_PASSWORD env is required")
    store = fwcrypto.load_store(STORE_PATH, password)
    snaps = store.get("snapshots") or []
    if not snaps:
        sys.exit("no snapshots; run collect.py first")
    snap = snaps[-1]

    y30 = next((c for c in snap["curve"] if c["label"] == "30Y"), {})
    y10 = next((c for c in snap["curve"] if c["label"] == "10Y"), {})
    y2 = next((c for c in snap["curve"] if c["label"] == "2Y"), {})
    tp = (snap["decomp"].get("THREEFYTP10") or {})
    hero = ""
    for lab, e in (("30年", y30), ("10年", y10), ("2年", y2)):
        if not e:
            continue
        c = e["chg"].get("20")
        col = "#ff5c78" if (c or 0) > 3 else ("#39c6be" if (c or 0) < -3 else "#f6c453")
        hero += ('<div class="hb"><span class="hp" style="color:%s">%.2f<em>%%</em></span>'
                 '<span class="hl">%s　<b style="color:%s">%s</b></span></div>'
                 % (col, e["value"], lab, col, bp(c)))

    now = dt.datetime.now(TPE).strftime("%Y-%m-%d %H:%M")
    page = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><title>美債殖利率曲線與期限溢價</title>
<style>
:root{color-scheme:dark;--bg:#0c1017;--card:#131a24;--ink:#f2f5f8;--muted:#9ba8b7;--line:#293545;--gold:#f6c453}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI","Noto Sans TC","Microsoft JhengHei",sans-serif;line-height:1.6}
.wrap{max-width:960px;margin:0 auto;padding:26px 16px 60px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:34px 0 12px;color:var(--gold)}
.sub{color:var(--muted);font-size:13px}
.hero{display:flex;gap:30px;flex-wrap:wrap;align-items:center;margin:18px 0;padding:20px;background:var(--card);border:1px solid var(--line);border-radius:16px}
.hb{text-align:center}.hp{display:block;font-size:32px;font-weight:900}.hp em{font-size:15px;font-style:normal}
.hl{color:var(--muted);font-size:12px}
.card{margin:12px 0;padding:16px;background:var(--card);border:1px solid var(--line);border-radius:14px}
svg{width:100%;height:auto;background:#0d131c;border-radius:10px;margin-bottom:8px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:8px 6px;border-bottom:1px solid var(--line);text-align:left}
.num{text-align:right;white-space:nowrap}
.srow{display:flex;gap:10px;flex-wrap:wrap}
.scard{flex:1;min-width:150px;padding:12px 14px;background:#0d131c;border:1px solid var(--line);border-radius:10px}
.slab{display:block;color:var(--muted);font-size:11px}.sval{display:block;font-size:24px;font-weight:900}
.sval em{font-size:12px;font-style:normal;color:var(--muted);margin-left:3px}.schg{font-size:11px}
.pwrap{display:flex;gap:22px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.pscore{font-size:46px;font-weight:950;line-height:1}.pscore span{font-size:15px;color:var(--muted)}
.pmeta{flex:1;min-width:240px}
.prow{display:flex;align-items:center;gap:10px;margin:6px 0}
.pname{width:130px;font-size:12px;color:var(--muted)}
.ptrack{flex:1;height:10px;background:#0d131c;border-radius:5px;overflow:hidden}
.pfill{height:100%;border-radius:5px}.pval{width:60px;text-align:right;font-size:12px;color:var(--muted)}
.events{list-style:none;margin:0;padding:0}.events li{padding:9px 0;border-bottom:1px solid var(--line);font-size:13px}
.events time{color:var(--muted);margin-right:8px;font-size:12px}
.tag{display:inline-block;margin-right:5px;padding:1px 7px;border-radius:20px;background:#20293a;color:#7fb4ff;font-size:10px}
.etext{margin-right:6px}
article{padding:12px 14px;margin:10px 0;background:#0d131c;border:1px solid var(--line);border-radius:10px}
article h4{margin:0 0 6px;color:var(--gold)}
a{color:#7fb4ff}.muted{color:var(--muted);font-size:12px}
footer{margin-top:40px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
</style></head><body><div class="wrap">
<h1>美債殖利率曲線與期限溢價</h1>
<p class="sub">資料日 {{ASOF}}｜更新 {{NOW}}（台北）｜10年期限溢價 {{TP}}</p>
<div class="hero">{{HERO}}<div class="sub" style="margin-left:auto;max-width:260px">數字為當前殖利率，下方為 20 個交易日變化。紅＝殖利率上升＝債價下跌。</div></div>
<h2>折現率壓力指數</h2><div class="card">{{PRESSURE}}</div>
<h2>殖利率曲線</h2><div class="card">{{CURVE}}</div>
<h2>關鍵利差</h2><div class="card">{{SPREADS}}</div>
<h2>名目利率拆解：實質 vs 通膨預期</h2><div class="card">{{DECOMP}}</div>
<h2>30年殖利率走勢</h2><div class="card">{{T30}}</div>
<h2>10年期限溢價（ACM）</h2><div class="card">{{TTP}}{{TPNOTE}}</div>
<h2>債市政策與事件台帳</h2><div class="card">{{EVENTS}}</div>
<h2>每日解讀</h2>{{COMM}}
<h2>方法說明</h2><div class="card muted">
<p>資料源：FRED（美國公債 11 個期別、TIPS 實質利率、通膨補償、紐約聯準會 ACM 期限溢價）與金十數據快訊。每日自動更新。</p>
<p><b>為什麼要拆解？</b>名目殖利率 ≈ 實質利率 + 通膨預期。長端上升若來自通膨預期，代表通膨風險，Fed 可能需要更鷹；若來自實質利率與期限溢價（財政赤字、供給、外資減持），則是市場自己在收緊金融條件，反而降低 Fed 出手的必要性。兩者對政策路徑的意涵相反，混為一談會判斷錯誤。</p>
<p><b>折現率壓力指數</b>衡量長天期現金流的估值逆風，可與 AI 算力基建對帳戰情板對照閱讀。</p>
<p>本頁為個人研究工具，非投資建議。快訊原文版權屬金十數據，僅供本人研究使用，請勿轉傳。</p></div>
<footer>bond-watch｜每日自動更新｜姊妹頁：FED 升降息機率儀表板、AI 算力基建對帳戰情板</footer>
</div></body></html>"""

    tpnote = ""
    if tp.get("value") is not None:
        c20 = tp.get("chg", {}).get("20")
        tpnote = ('<p class="muted">期限溢價是投資人持有長債所要求的額外補償，與 Fed 政策預期無關。'
                  '現值 %.2f%%，20 日變化 %s。上升代表市場對財政赤字、發債供給或外資需求的疑慮加深。</p>'
                  % (tp["value"], bp(c20)))

    rep = {
        "ASOF": snap.get("asof", ""), "NOW": now,
        "TP": ("%.2f%%" % tp["value"]) if tp.get("value") is not None else "—",
        "HERO": hero or '<p class="muted">等待資料…</p>',
        "PRESSURE": pressure_block(snap),
        "CURVE": curve_svg(snap, store),
        "SPREADS": spread_block(snap),
        "DECOMP": decomp_block(snap),
        "T30": trend_svg(store, "DGS30", "30年期公債殖利率", "#ff5c78") or '<p class="muted">資料不足</p>',
        "TTP": trend_svg(store, "THREEFYTP10", "10年期限溢價 ACM", "#7fb4ff") or '<p class="muted">資料不足</p>',
        "TPNOTE": tpnote,
        "EVENTS": events_block(store.get("events") or []),
        "COMM": commentary_block(store.get("commentary") or []),
    }
    for k, v in rep.items():
        page = page.replace("{{" + k + "}}", v)

    fwcrypto.write_encrypted_page(page, password, BASE)
    print("[bond] page written: %d chars, pressure=%s" % (len(page), (snap.get("pressure") or {}).get("score")))


if __name__ == "__main__":
    main()
