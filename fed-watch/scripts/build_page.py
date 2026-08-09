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


def history_svg(snapshots, next_key):
    pts = []
    for s in snapshots:
        bl = (s.get("blend") or {}).get(next_key)
        if bl:
            pts.append((s["ts"], bl))
    pts = pts[-150:]
    if len(pts) < 2:
        return '<p class="muted">歷史軌跡將隨每日快照累積後出現。</p>'
    W, H, PAD = 860, 240, 34
    n = len(pts)

    def xy(i, v):
        x = PAD + (W - 2 * PAD) * i / (n - 1)
        y = H - PAD - (H - 2 * PAD) * v
        return "%.1f,%.1f" % (x, y)

    series = {
        "升息(≥1碼)": ("#ff5c78", [p["hike25"] + p["hike50p"] for _t, p in pts]),
        "按兵不動": ("#f6c453", [p["hold"] for _t, p in pts]),
        "降息(≥1碼)": ("#39c6be", [p["cut25"] + p["cut50p"] for _t, p in pts]),
    }
    lines, legend = "", ""
    for i, (name, (c, vals)) in enumerate(series.items()):
        path = " ".join(xy(j, v) for j, v in enumerate(vals))
        lines += '<polyline points="%s" fill="none" stroke="%s" stroke-width="2.2"/>' % (path, c)
        legend += ('<tspan x="%d" dy="0" fill="%s">● %s %.0f%%</tspan>'
                   % (PAD + i * 200, c, name, vals[-1] * 100))
    grid = "".join('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#293545" stroke-width="1"/>'
                   '<text x="6" y="%.1f" fill="#9ba8b7" font-size="11">%d%%</text>'
                   % (PAD, H - PAD - (H - 2 * PAD) * v, W - PAD,
                      H - PAD - (H - 2 * PAD) * v, H - PAD - (H - 2 * PAD) * v + 4, v * 100)
                   for v in (0, 0.25, 0.5, 0.75, 1))
    t0, t1 = pts[0][0][:10], pts[-1][0][:10]
    return ('<svg viewBox="0 0 %d %d" role="img">%s%s'
            '<text x="%d" y="18" font-size="12">%s</text>'
            '<text x="%d" y="%d" fill="#9ba8b7" font-size="11">%s</text>'
            '<text x="%d" y="%d" fill="#9ba8b7" font-size="11" text-anchor="end">%s</text></svg>'
            % (W, H, grid, lines, PAD, legend, PAD, H - 8, t0, W - PAD, H - 8, t1))


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
<h2>四次會議機率路徑</h2>{{CARDS}}
<h2>歷史軌跡（下次會議・綜合機率）</h2><div class="card">{{HIST}}</div>
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
        "CARDS": cards, "HIST": history_svg(store["snapshots"], nxt["key"]),
        "FACTORS": factor_table(mdl), "QUOTES": quotes_html(store["quotes"]),
        "COMM": commentary_html(store["commentary"]), "MINQ": str(CFG["expert_min_quotes"]),
    }
    for k, v in rep.items():
        page = page.replace("{{" + k + "}}", v)

    fwcrypto.write_encrypted_page(page, password, BASE)
    print("[build] page written: %d chars, blend(next)=%s" % (len(page), json.dumps(nb)))


if __name__ == "__main__":
    main()
