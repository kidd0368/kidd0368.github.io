# -*- coding: utf-8 -*-
"""讀加密資料庫 → 跑模型與三層合成 → 產出儀表板 HTML → AES-GCM 加密發布。
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
import model as M

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
STORE_PATH = os.path.join(BASE, "data", "store.enc")
BUCKETS = CFG["buckets"]
BL = CFG["bucket_labels"]
COL = {"cut50p": "#1fa89f", "cut25": "#39c6be", "hold": "#f6c453", "hike25": "#ff5c78", "hike50p": "#e03a5a"}
TPE = dt.timezone(dt.timedelta(hours=8))


def esc(s):
    return htmlmod.escape(str(s or ""), quote=True)


def md(text):
    t = esc(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return "".join("<p>%s</p>" % p.replace("\n", "<br>") for p in t.split("\n\n") if p.strip())


def bar_row(label, dist, note=""):
    if not dist:
        return ('<div class="lrow"><span class="lname">%s</span>'
                '<div class="track empty">無資料</div></div>' % esc(label))
    segs, ticks = "", ""
    acc = 0.0
    for b in BUCKETS:
        p = dist.get(b, 0) * 100
        if p < 0.4:
            acc += p
            continue
        segs += ('<div class="seg" style="width:%.2f%%;background:%s" title="%s %.1f%%">%s</div>'
                 % (p, COL[b], BL[b], p, ("%.0f%%" % p) if p >= 8 else ""))
        acc += p
    return ('<div class="lrow"><span class="lname">%s%s</span><div class="track">%s</div></div>'
            % (esc(label), ('<em>%s</em>' % esc(note)) if note else "", segs))


def meeting_card(m, market, mdl, expert, blended, srcs):
    key = m["key"]
    b = blended.get(key)
    head = ""
    if b:
        top = max(BUCKETS, key=lambda x: b[x])
        head = '<span class="verdict" style="color:%s">%s %.0f%%</span>' % (COL[top], BL[top], b[top] * 100)
    rows = bar_row("綜合", b) + \
        bar_row("市場", market["dists"].get(key), "+".join(srcs.get(key, []))) + \
        bar_row("模型", mdl["dists"].get(key)) + \
        bar_row("專家", (expert.get("dists") or {}).get(key),
                ("n=%d" % expert["n"]) if expert.get("n") else "")
    days = (dt.date.fromisoformat(m["date"]) - dt.datetime.now(TPE).date()).days
    return ('<section class="card"><div class="chead"><h3>%s</h3>'
            '<span class="days">還有 %d 天</span>%s</div>%s</section>'
            % (esc(m["label"]), max(days, 0), head, rows))


def _hike(p):
    return p.get("hike25", 0) + p.get("hike50p", 0)


def _cut(p):
    return p.get("cut25", 0) + p.get("cut50p", 0)


def history_svg(store, next_key, next_label):
    """市場歷史軌跡（Kalshi 日K回填）＋ 我們的綜合機率（快照累積）。"""
    mkt = [(d, p) for d, p in (store.get("market_history", {}).get(next_key) or [])]
    ours = []
    for s in store.get("snapshots", []):
        bl = (s.get("blend") or {}).get(next_key)
        if bl:
            ours.append((s["ts"][:10], bl))
    if len(mkt) < 2:
        return '<p class="muted">市場歷史尚未回填，下次自動更新後出現。</p>'

    days = sorted({d for d, _ in mkt} | {d for d, _ in ours})
    idx = {d: i for i, d in enumerate(days)}
    n = len(days)
    W, H, PAD, TOP = 860, 250, 40, 30

    def xy(d, v):
        x = PAD + (W - 2 * PAD) * idx[d] / max(n - 1, 1)
        y = H - PAD - (H - PAD - TOP) * v
        return "%.1f,%.1f" % (x, y)

    def line(pts, color, dash="", width=2.2):
        if len(pts) < 2:
            return ""
        p = " ".join(xy(d, v) for d, v in pts)
        return ('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s"%s/>'
                % (p, color, width, (' stroke-dasharray="%s"' % dash) if dash else ""))

    mk_hike = [(d, _hike(p)) for d, p in mkt]
    mk_hold = [(d, p.get("hold", 0)) for d, p in mkt]
    our_hike = [(d, _hike(p)) for d, p in ours]

    body = line(mk_hold, "#f6c453") + line(mk_hike, "#ff5c78")
    if len(our_hike) >= 2:
        body += line(our_hike, "#ffa8ba", "5,4", 2.6)
    elif our_hike:
        d, v = our_hike[-1]
        cx, cy = xy(d, v).split(",")
        body += '<circle cx="%s" cy="%s" r="4" fill="#ffa8ba"/>' % (cx, cy)

    grid = ""
    for v in (0, 0.25, 0.5, 0.75, 1):
        y = H - PAD - (H - PAD - TOP) * v
        grid += ('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#293545" stroke-width="1"/>'
                 '<text x="4" y="%.1f" fill="#9ba8b7" font-size="10">%d%%</text>'
                 % (PAD, y, W - PAD, y, y + 3, v * 100))

    peak = max(mk_hike, key=lambda x: x[1])
    marks = ""
    if peak[1] > 0.55:
        px, py = xy(peak[0], peak[1]).split(",")
        marks += ('<circle cx="%s" cy="%s" r="3" fill="#ff5c78"/>'
                  '<text x="%s" y="%.1f" fill="#ff5c78" font-size="10" text-anchor="middle">高點 %.0f%%</text>'
                  % (px, py, px, float(py) - 8, peak[1] * 100))

    legend = ('<tspan x="%d" fill="#ff5c78">━ 市場·升息 %.0f%%</tspan>'
              '<tspan x="%d" fill="#f6c453">━ 市場·不變 %.0f%%</tspan>'
              '<tspan x="%d" fill="#ffa8ba">┅ 我們·升息 %s</tspan>'
              % (PAD, mk_hike[-1][1] * 100, PAD + 210, mk_hold[-1][1] * 100,
                 PAD + 420, ("%.0f%%" % (our_hike[-1][1] * 100)) if our_hike else "累積中"))
    return ('<svg viewBox="0 0 %d %d" role="img">%s%s%s'
            '<text x="%d" y="16" font-size="11">%s</text>'
            '<text x="%d" y="%d" fill="#9ba8b7" font-size="10">%s</text>'
            '<text x="%d" y="%d" fill="#9ba8b7" font-size="10" text-anchor="end">%s</text></svg>'
            % (W, H, grid, body, marks, PAD, legend,
               PAD, H - 12, days[0], W - PAD, H - 12, days[-1]))


def expected_moves(dist):
    """機率分布 → 預期動作碼數。"""
    return sum(dist.get(b, 0) * M.MOVES[b] for b in BUCKETS)


def path_svg(market, blended, meetings, mid):
    """預期政策利率路徑：市場 vs 我們的綜合，累積碼數換算成利率水準。"""
    rows = []
    for src, dists in (("market", market["dists"]), ("ours", blended)):
        cum, pts = 0.0, [(-1, mid, "現在")]
        for i, m in enumerate(meetings):
            d = dists.get(m["key"])
            if not d:
                continue
            cum += expected_moves(d)
            pts.append((i, mid + 0.25 * cum, m["zh_month"]))
        rows.append((src, pts))
    if not rows or len(rows[0][1]) < 2:
        return '<p class="muted">等待市場資料。</p>'

    allv = [v for _s, pts in rows for _i, v, _l in pts]
    lo, hi = min(allv) - 0.12, max(allv) + 0.12
    W, H, PADL, PADR, TOP, BOT = 860, 240, 52, 26, 34, 44
    n = len(meetings)

    def xy(i, v):
        x = PADL + (W - PADL - PADR) * (i + 1) / n
        y = H - BOT - (H - BOT - TOP) * (v - lo) / (hi - lo or 1)
        return x, y

    grid = ""
    step = 0.25
    g = round(lo / step) * step
    while g <= hi:
        _x, y = xy(0, g)
        grid += ('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#293545" stroke-width="1"/>'
                 '<text x="4" y="%.1f" fill="#9ba8b7" font-size="10">%.2f%%</text>'
                 % (PADL, y, W - PADR, y, y + 3, g))
        g += step

    xlab = ""
    for i, m in enumerate(meetings):
        x, _y = xy(i, lo)
        xlab += ('<text x="%.1f" y="%d" fill="#9ba8b7" font-size="10" text-anchor="middle">%s</text>'
                 % (x, H - 14, m["label"].split(" ")[0].replace("2026年", "").replace("2027年", "27/")))
    x0, _ = xy(-1, lo)
    xlab += ('<text x="%.1f" y="%d" fill="#9ba8b7" font-size="10" text-anchor="middle">現在</text>'
             % (x0, H - 14))

    body, legend = "", ""
    style = {"market": ("#7fb4ff", "", "市場定價"), "ours": ("#f6c453", "6,4", "我們的綜合")}
    for k, (src, pts) in enumerate(rows):
        col, dash, name = style[src]
        coords = [xy(i, v) for i, v, _l in pts]
        body += ('<polyline points="%s" fill="none" stroke="%s" stroke-width="2.6"%s/>'
                 % (" ".join("%.1f,%.1f" % c for c in coords), col,
                    (' stroke-dasharray="%s"' % dash) if dash else ""))
        for cx, cy in coords:
            body += '<circle cx="%.1f" cy="%.1f" r="3.2" fill="%s"/>' % (cx, cy, col)
        ex, ey = coords[-1]
        body += ('<text x="%.1f" y="%.1f" fill="%s" font-size="11" font-weight="800" '
                 'text-anchor="end">%.2f%%</text>' % (ex - 6, ey - 8, col, pts[-1][1]))
        legend += '<tspan x="%d" fill="%s">%s %s</tspan>' % (PADL + k * 190, col,
                                                             "┅" if dash else "━", name)
    gap = rows[1][1][-1][1] - rows[0][1][-1][1] if len(rows) > 1 else 0
    return ('<svg viewBox="0 0 %d %d" role="img">%s%s%s'
            '<text x="%d" y="16" font-size="11">%s</text></svg>'
            '<p class="muted">終點差距 %+.2f 個百分點（%s）。正值代表我們比市場鷹派。</p>'
            % (W, H, grid, body, xlab, PADL, legend, gap,
               "我們更鷹" if gap > 0.03 else ("我們更鴿" if gap < -0.03 else "基本一致")))


def factor_table(mdl):
    rows = ""
    for f in mdl["factors"]:
        s = f["score"]
        w = abs(s) / 2 * 100
        side = "right" if s >= 0 else "left"
        col = "#ff5c78" if s > 0.05 else ("#39c6be" if s < -0.05 else "#9ba8b7")
        rows += ('<tr><td>%s</td><td class="num">%s</td>'
                 '<td class="fbar"><div class="fmid"><div class="fseg %s" '
                 'style="width:%.0f%%;background:%s"></div></div></td>'
                 '<td class="num" style="color:%s">%+.2f</td><td class="num">%.0f%%</td></tr>'
                 % (esc(f["desc"]), esc(f["value"]), side, w / 2, col, col, s, f["weight"] * 100))
    return ('<table><thead><tr><th>因子</th><th>數值</th><th>鴿 ← 0 → 鷹</th>'
            '<th>分數</th><th>權重</th></tr></thead><tbody>%s</tbody></table>'
            '<p class="muted">鷹派總分 H = %+.2f（加權平均；正=偏升息，負=偏降息）</p>'
            % (rows, mdl["hawk_score"]))


def quotes_html(quotes):
    tally = {"hawk": 0, "dove": 0, "neutral": 0, "un": 0}
    items = ""
    for q in sorted(quotes, key=lambda x: x.get("time", ""), reverse=True)[:40]:
        c = q.get("cls")
        tally[c if c in tally else "un"] += 1
        chip = {"hawk": '<span class="chip hawk">鷹</span>',
                "dove": '<span class="chip dove">鴿</span>',
                "neutral": '<span class="chip neu">中</span>'}.get(c, '<span class="chip un">未分類</span>')
        link = ' <a href="%s" target="_blank" rel="noopener">原文</a>' % esc(q["url"]) if q.get("url") else ""
        items += ('<li>%s<time>%s</time><span class="qt">%s</span>%s</li>'
                  % (chip, esc((q.get("time") or "")[:16].replace("T", " ")), esc(q["text"][:220]), link))
    head = ('<p class="tally">近期樣本：<b class="h">鷹 %d</b>／<b class="d">鴿 %d</b>／中性 %d／未分類 %d</p>'
            % (tally["hawk"], tally["dove"], tally["neutral"], tally["un"]))
    return head + "<ul class='quotes'>%s</ul>" % (items or "<li>尚無資料（等金十 Token 開通）</li>")


def commentary_html(comm):
    if not comm:
        return '<p class="muted">首篇推演將在明早的排程分析後出現。</p>'
    out = ""
    for c in sorted(comm, key=lambda x: x["date"], reverse=True)[:10]:
        out += '<article><h4>%s</h4>%s</article>' % (esc(c["date"]), md(c["text"]))
    return out


def main():
    password = os.environ.get("PAGE_PASSWORD", "").strip()
    if not password:
        sys.exit("PAGE_PASSWORD env is required")
    store = fwcrypto.load_store(STORE_PATH, password)
    if not store["snapshots"]:
        sys.exit("store has no snapshots; run collect.py first")

    meetings = CFG["meetings"]
    tgt = CFG["current_target"]
    mid = (tgt["low"] + tgt["high"]) / 2
    snap = store["snapshots"][-1]

    market = M.market_layer(snap, meetings)
    mdl = M.model_layer(store["macro"], meetings, mid)
    expert = M.expert_layer(store["quotes"], meetings,
                            CFG["expert_lookback_days"], CFG["expert_min_quotes"])
    blended = M.blend(market, mdl, expert, meetings, CFG["weights"])
    snap["model"] = {"hawk_score": mdl["hawk_score"], "dists": mdl["dists"]}
    snap["blend"] = blended
    fwcrypto.save_store(STORE_PATH, store, password)

    nxt = meetings[0]
    nb = blended.get(nxt["key"], {})
    hero = ""
    if nb:
        for b in BUCKETS:
            if nb.get(b, 0) >= 0.005:
                hero += ('<div class="hbucket"><span class="hpct" style="color:%s">%.0f%%</span>'
                         '<span class="hlab">%s</span></div>' % (COL[b], nb[b] * 100, BL[b]))

    now_tpe = dt.datetime.now(TPE).strftime("%Y-%m-%d %H:%M")
    cards = "".join(meeting_card(m, market, mdl, expert, blended, market["sources"])
                    for m in meetings)

    page = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><title>FED 升降息機率儀表板</title>
<style>
:root{color-scheme:dark;--bg:#0c1017;--card:#131a24;--ink:#f2f5f8;--muted:#9ba8b7;--line:#293545;--gold:#f6c453}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI","Noto Sans TC","Microsoft JhengHei",sans-serif;line-height:1.6}
.wrap{max-width:960px;margin:0 auto;padding:26px 16px 60px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:34px 0 12px;color:var(--gold)}h3{font-size:16px;margin:0}
.sub{color:var(--muted);font-size:13px}
.hero{display:flex;gap:26px;flex-wrap:wrap;align-items:center;margin:18px 0;padding:20px;background:var(--card);border:1px solid var(--line);border-radius:16px}
.hbucket{text-align:center}.hpct{display:block;font-size:34px;font-weight:900}.hlab{color:var(--muted);font-size:12px}
.card{margin:12px 0;padding:16px;background:var(--card);border:1px solid var(--line);border-radius:14px}
.chead{display:flex;align-items:baseline;gap:12px;margin-bottom:10px}.days{color:var(--muted);font-size:12px}.verdict{margin-left:auto;font-weight:900}
.lrow{display:flex;align-items:center;gap:10px;margin:7px 0}.lname{width:92px;font-size:13px;color:var(--muted)}.lname em{display:block;font-size:10px;font-style:normal;opacity:.75}
.track{flex:1;display:flex;height:24px;border-radius:6px;overflow:hidden;background:#0d131c}.track.empty{align-items:center;padding-left:10px;color:var(--muted);font-size:12px}
.seg{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;color:#10131a;min-width:0}
svg{width:100%;height:auto;background:#0d131c;border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:8px 6px;border-bottom:1px solid var(--line);text-align:left}.num{text-align:right;white-space:nowrap}
.fbar{width:34%}.fmid{position:relative;height:12px;background:#0d131c;border-radius:6px}.fmid:before{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--line)}
.fseg{position:absolute;top:0;bottom:0;border-radius:6px}.fseg.right{left:50%}.fseg.left{right:50%}
.quotes{list-style:none;margin:0;padding:0}.quotes li{padding:9px 0;border-bottom:1px solid var(--line);font-size:13px}
.quotes time{color:var(--muted);margin-right:8px;font-size:12px}.qt{margin-right:6px}
.chip{display:inline-block;min-width:30px;text-align:center;margin-right:8px;padding:1px 7px;border-radius:20px;font-size:11px;font-weight:800}
.chip.hawk{background:#3a1520;color:#ff5c78}.chip.dove{background:#0f2f2d;color:#39c6be}.chip.neu{background:#2a2a1a;color:#f6c453}.chip.un{background:#20293a;color:#9ba8b7}
.tally .h{color:#ff5c78}.tally .d{color:#39c6be}
article{padding:12px 14px;margin:10px 0;background:#0d131c;border:1px solid var(--line);border-radius:10px}article h4{margin:0 0 6px;color:var(--gold)}
a{color:#7fb4ff}.muted{color:var(--muted);font-size:13px}
.meth{font-size:13px;color:var(--muted)}.meth b{color:var(--ink)}
footer{margin-top:40px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
</style></head><body><div class="wrap">
<h1>FED 升降息機率儀表板</h1>
<p class="sub">現行目標區間 <b>{{TLOW}}%–{{THIGH}}%</b>｜下次會議 {{NLABEL}}｜更新 {{NOW}}（台北）</p>
<div class="hero">{{HERO}}<div class="sub" style="margin-left:auto;max-width:300px">下次會議（{{NLABEL}}）三層合成機率：市場定價 {{WM}}%━反應函數模型 {{WO}}%━專家共識 {{WE}}%</div></div>
<h2>預期政策利率路徑</h2><div class="card">{{PATH}}</div>
<h2>四次會議機率分布</h2>{{CARDS}}
<h2>歷史軌跡（{{NLABEL}}・升息機率）</h2><div class="card">{{HIST}}</div>
<h2>模型因子（第二層）</h2><div class="card">{{FACTORS}}</div>
<h2>券商與專家言論（第三層）</h2><div class="card">{{QUOTES}}</div>
<h2>機率推演（Claude 每日分析）</h2>{{COMM}}
<h2>方法說明</h2><div class="card meth">
<p><b>市場層</b>：Kalshi 與 Polymarket 的 FOMC 決議市場中價，加上金十快訊引用的 CME FedWatch 數字（三者平均）。</p>
<p><b>模型層</b>：透明反應函數——核心PCE缺口、核心CPI動能、油價衝擊、就業動能、債市定價五因子加權成鷹派分數 H，再以離散常態映射成五檔動作機率；愈遠的會議不確定性愈大。</p>
<p><b>專家層</b>：金十快訊中券商／經濟學家對 Fed 的表態，由 Claude 逐條分類鷹鴿（時間衱減加權），樣本不足 {{MINQ}} 條時此層不啟用。</p>
<p>本頁為個人研究工具，非投資建議。快訊原文版權屬金十數據，僅供本人研究使用，請勿轉傳。</p></div>
<footer>資料源：Kalshi API・Polymarket Gamma API・FRED・金十數據 MCP｜每日 4 次自動更新｜fed-watch</footer>
</div></body></html>"""
    rep = {
        "TLOW": "%.2f" % tgt["low"], "THIGH": "%.2f" % tgt["high"],
        "NLABEL": nxt["label"], "NOW": now_tpe,
        "HERO": hero or '<p class="muted">等待首批市場資料…</p>',
        "WM": "%.0f" % (CFG["weights"]["market"] * 100),
        "WO": "%.0f" % (CFG["weights"]["model"] * 100),
        "WE": "%.0f" % (CFG["weights"]["expert"] * 100),
        "CARDS": cards,
        "PATH": path_svg(market, blended, meetings, mid),
        "HIST": history_svg(store, nxt["key"], nxt["label"]),
        "FACTORS": factor_table(mdl), "QUOTES": quotes_html(store["quotes"]),
        "COMM": commentary_html(store["commentary"]), "MINQ": str(CFG["expert_min_quotes"]),
    }
    for k, v in rep.items():
        page = page.replace("{{" + k + "}}", v)

    fwcrypto.write_encrypted_page(page, password, BASE)
    print("[build] page written: %d chars, blend(next)=%s" % (len(page), json.dumps(nb)))


if __name__ == "__main__":
    main()

