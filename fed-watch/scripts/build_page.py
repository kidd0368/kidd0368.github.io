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


def pct(v):
    return "—" if v is None else "%.0f%%" % (v * 100)


def num(v, digits=2, suffix=""):
    return "—" if v is None else (("%%.%df" % digits) % v) + suffix


def scenario_labels(features):
    return {
        "inflation": {
            "anchored": "預期仍穩定", "at_risk": "失錨風險升高",
            "deanchoring": "正在失錨", "mixed": "訊號混合", "insufficient": "資料不足",
        }.get(features.get("inflation_expectations"), "資料不足"),
        "growth": {
            "resilient": "成長仍有韌性", "cooling": "成長正在降溫",
            "weakening": "成長明顯轉弱", "insufficient": "資料不足",
        }.get(features.get("growth"), "資料不足"),
        "credit": {
            "benign": "信用條件仍寬鬆", "watch": "信用條件需觀察",
            "tightening": "信用條件正在收緊", "insufficient": "資料不足",
        }.get(features.get("credit"), "資料不足"),
        "market": {
            "hike_base_case": "升息已成市場主情境",
            "hike_meaningful": "升息被明顯定價，但仍非主情境",
            "hike_tail": "升息仍屬尾端風險",
            "insufficient": "市場資料不足",
        }.get(features.get("market_overlay"), "市場資料不足"),
    }


def scenario_summary_html(scenario, next_label):
    f = scenario["features"]
    lab = scenario_labels(f)
    cls = "risk" if scenario["key"] in ("policy_error", "stagflation") else (
        "warn" if scenario["key"] in ("renewed_hiking", "mixed") else "ok")
    caveat = ("這是依目前公開資料做的研究判斷，不是已發生的政策錯誤。"
              if scenario["key"] == "policy_error" else
              "這是待後續資料驗證的情境分類，不代表政策結果已經發生。")
    return """<section class="decision %s" id="status">
<div class="decision-main"><p class="eyebrow">目前研究判斷｜%s</p><h2>%s</h2>
<p class="stage">%s</p><p class="plain">%s</p></div>
<div class="decision-grid">
  <div><span>市場正在交易什麼</span><b>%s</b><small>升息 %s／不變 %s／降息 %s</small></div>
  <div><span>通膨預期代理</span><b>%s</b><small>10年損益兩平率 %s；20日變化 %s</small></div>
  <div><span>成長與就業</span><b>%s</b><small>非農3月均 %s 千人；失業率3月變化 %s 個百分點</small></div>
  <div><span>信用與金融條件</span><b>%s</b><small>必須和就業同步惡化，才足以確認政策錯誤。</small></div>
</div></section>""" % (
        cls, esc(next_label), esc(scenario["label"]), esc(scenario["stage"]), esc(caveat),
        esc(lab["market"]), pct(f.get("market_hike")), pct(f.get("market_hold")), pct(f.get("market_cut")),
        esc(lab["inflation"]), num(f.get("be"), 2, "%"),
        num(f.get("be20"), 2, " 個百分點"), esc(lab["growth"]),
        num(next((r["value"] for r in f.get("labor_rows", []) if r["metric"].startswith("非農")), None), 0),
        num(next((r["value"] for r in f.get("labor_rows", []) if r["metric"].startswith("失業率")), None), 2),
        esc(lab["credit"]),
    )


def scenario_matrix_html(active_key):
    cells = [
        ("preventive_hike", "通膨預期穩定 × 成長有韌性", "一次預防性升息或只是口頭轉鷹",
         "主要衝擊是折現率與估值重定價；若企業獲利與資本支出沒有下修，通常還不能稱為政策錯誤。"),
        ("renewed_hiking", "通膨預期失錨 × 成長有韌性", "重新啟動升息循環",
         "若薪資、服務價格、能源與長期通膨預期同時加速，市場必須交易多次升息，而不是只交易一碼。"),
        ("policy_error", "通膨預期穩定 × 成長轉弱", "政策錯誤風險",
         "若 Fed 仍維持鷹派立場，而就業、信用、企業指引與資本支出同步惡化，升息可能從預防性動作變成過度緊縮。"),
        ("stagflation", "通膨預期失錨 × 成長轉弱", "停滯性通膨陷阱",
         "成長走弱卻無法降息，長天期殖利率、信用成本與企業獲利會同時承壓，對股票通常是最不利的組合。"),
    ]
    body = ""
    keys = {cell[0] for cell in cells}
    for key, axis, title, text in cells:
        body += ('<article class="scenario-cell%s"><span>%s</span><h3>%s</h3><p>%s</p></article>'
                 % (" active" if key == active_key else "", esc(axis), esc(title), esc(text)))
    note = ("高亮格是目前最接近的研究情境；若資料互相矛盾，頁面會標示為暫定，而不會強迫給出精確機率。"
            if active_key in keys else
            "目前沒有高亮四象限，表示政策轉鷹或關鍵資料尚未形成；此時不把單純的景氣降溫誤寫成政策錯誤。")
    return '<div class="matrix">%s</div><p class="note">%s</p>' % (body, esc(note))


def conflict_and_falsifier_html(scenario):
    def items(rows, empty):
        return "".join("<li>%s</li>" % esc(x) for x in rows) or "<li>%s</li>" % esc(empty)
    return """<div class="two-col">
<section class="card"><h3>目前最重要的矛盾</h3><ul class="read-list">%s</ul></section>
<section class="card"><h3>什麼證據可以反駁目前判斷</h3><ul class="read-list">%s</ul></section>
</div><section class="card confirm"><h3>目前支持這個情境的證據</h3><ul class="read-list">%s</ul></section>""" % (
        items(scenario.get("conflicts", []), "目前沒有足夠資料辨識新的跨來源矛盾。"),
        items(scenario.get("refute", []), "尚待建立可驗證的反證條件。"),
        items(scenario.get("support", []), "目前仍是證據不足。"),
    )


def what_changed_html(store, meetings, market, mdl, scenario):
    nxt = meetings[0]["key"]
    prev = None
    for row in reversed(store.get("snapshots", [])[:-1]):
        if (row.get("blend") or {}).get(nxt):
            prev = row
            break
    items = []
    now_hike = scenario["features"].get("market_hike")
    if prev:
        prior_market = M.market_layer(prev, meetings)
        prior_dist = (prior_market.get("dists") or {}).get(nxt)
        prior_hike = _hike(prior_dist) if prior_dist else None
        if now_hike is not None and prior_hike is not None:
            delta = (now_hike - prior_hike) * 100
            items.append("市場對下次會議的升息定價較前一個可比快照%s %.1f 個百分點。"
                         % ("上升" if delta >= 0 else "下降", abs(delta)))
        old_h = (prev.get("model") or {}).get("hawk_score")
        if old_h is not None and mdl.get("hawk_score") is not None:
            dh = mdl["hawk_score"] - old_h
            items.append("總經反應函數的鷹派分數較前一個可比快照%s %+.2f；這是模型訊號，不是 Fed 的正式表態。"
                         % ("變動" if abs(dh) >= 0.01 else "大致持平", dh))
        old_s = prev.get("scenario") or {}
        if old_s.get("key"):
            if old_s["key"] == scenario["key"]:
                items.append("四象限情境沒有改變；目前仍是「%s」。" % scenario["label"])
            else:
                items.append("四象限情境由「%s」轉為「%s」，需要下一輪資料確認後才視為有效轉折。"
                             % (old_s.get("label", old_s["key"]), scenario["label"]))
        else:
            items.append("本次是四象限情境的第一筆基準紀錄；之後每次更新會保留變化歷史。")
    else:
        items.append("本次先建立比較基準；下一個快照開始才會顯示市場與情境變化。")
    return "<ul class='change-list'>%s</ul>" % "".join("<li>%s</li>" % esc(x) for x in items)


def metric_evidence_html(macro, scenario):
    f = scenario["features"]
    rows = []

    def add(name, series, value, fact, interpretation, test):
        date = (macro.get(series) or {}).get("date", "—")
        link = "https://fred.stlouisfed.org/series/%s" % series
        rows.append((name, link, value, date, fact if value != "—" else "尚未取得資料", interpretation, test))

    add("10年損益兩平通膨率（市場代理）", "T10YIE", num(f.get("be"), 2, "%"), "已公布市場資料",
        scenario_labels(f)["inflation"],
        "水位至少2.55%，且20日上升至少0.20個百分點，才判為正在失錨；只達其中一項先列警戒。")
    add("核心PCE年增率", "PCEPILFE", num(f.get("pce_yoy"), 2, "%"), "已公布經濟數據",
        ("等待資料，不能據此判斷物價。" if f.get("pce_yoy") is None else
         ("核心PCE仍高於研究警戒門檻。" if f["pce_yoy"] >= CFG["scenario_rules"]["realized_inflation"]["core_pce_hot"] else "核心PCE低於研究警戒門檻。")),
        "若核心PCE與核心CPI短期動能同時再加速，持續升息假設會增強。")
    add("核心CPI三個月年化", "CPILFESL", num(f.get("core_cpi_3m"), 2, "%"), "已公布經濟數據",
        ("等待資料，不能據此判斷近期物價方向。" if f.get("core_cpi_3m") is None else
         "用來檢查近期物價方向，不能單獨代表長期通膨預期。"),
        "若連續資料高於3%，而通膨預期也上升，應把焦點轉向升息循環。")
    pay = macro.get("PAYEMS") or {}
    add("非農就業三個月平均", "PAYEMS", num(pay.get("diff3avg"), 0, " 千人"), "已公布經濟數據",
        ("等待資料，不能據此判斷招聘動能。" if pay.get("diff3avg") is None else
         ("低於研究門檻，顯示招聘動能轉弱。" if pay["diff3avg"] < CFG["scenario_rules"]["labor"]["payroll_3m_weak_k"] else "招聘動能仍有韌性。")),
        "回到150千人以上，會明顯反駁成長轉弱假設。")
    un = macro.get("UNRATE") or {}
    add("失業率三個月變化", "UNRATE", num(un.get("chg3m"), 2, " 個百分點"), "已公布經濟數據",
        ("等待資料，不能據此判斷勞動市場。" if un.get("chg3m") is None else
         ("失業率尚未同步惡化。" if un["chg3m"] <= 0 else "失業率正在上升。")),
        "三個月上升至少0.20個百分點，才構成更強的轉弱確認。")
    claims = macro.get("ICSA") or {}
    add("初領失業金四週平均", "ICSA", num(claims.get("ma4"), 0, " 人"), "已公布經濟數據",
        ("較前四週上升 %s%%。" % num(claims.get("ma4chg4"), 1)) if claims.get("ma4chg4") is not None else "等待首次更新。",
        "四週平均較前四週上升至少10%，視為就業轉弱的先行警報。")
    hy = macro.get("BAMLH0A0HYM2") or {}
    add("高收益債利差", "BAMLH0A0HYM2", num(hy.get("value"), 2, "%"), "已發生的信用市場定價",
        ("等待資料，不能據此判斷信用壓力。" if hy.get("value") is None else
         ("信用壓力升高。" if hy["value"] >= CFG["scenario_rules"]["credit"]["high_yield_warning"] else "尚未跨過信用警戒門檻。")),
        "高於4%先列警戒；高於5%視為更明顯的信用壓力。")
    nfci = macro.get("NFCI") or {}
    add("全國金融狀況指數", "NFCI", num(nfci.get("value"), 3), "已公布金融條件指數",
        ("等待資料，不能據此判斷金融條件。" if nfci.get("value") is None else
         ("正值代表金融條件較歷史平均緊。" if nfci["value"] >= 0 else "金融條件仍比歷史平均寬鬆。")),
        "升到0以上，才支持『金融條件已明顯收緊』。")
    sloos = macro.get("DRTSCILM") or {}
    add("銀行收緊企業放款標準淨比例", "DRTSCILM", num(sloos.get("value"), 1, "%"), "已公布銀行問卷",
        ("等待資料，不能據此判斷銀行放款條件。" if sloos.get("value") is None else
         ("銀行放款條件正在收緊。" if sloos["value"] >= 20 else "尚未跨過研究警戒值。")),
        "高於20%並與信用利差同步惡化，才構成政策錯誤的信用確認。")

    body = ""
    for name, link, value, date, fact, interpretation, test in rows:
        body += ("<tr><td><a href='%s' target='_blank' rel='noopener'>%s</a></td><td class='num'>%s</td>"
                 "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                 % (esc(link), esc(name), esc(value), esc(date), esc(fact), esc(interpretation), esc(test)))
    return ("<div class='table-wrap'><table class='evidence'><thead><tr><th>指標</th><th>最新值</th><th>資料截至</th>"
            "<th>這是什麼</th><th>目前怎麼解讀</th><th>下一個驗證門檻</th></tr></thead><tbody>%s</tbody></table></div>" % body)


def transmission_html():
    rows = [
        ("實質利率 → 科技估值與AI資本支出門檻",
         "實質利率先影響折現率與投資報酬門檻，之後才可能影響雲端業者的資本支出、AI設備訂單與供應鏈產能利用率。",
         "台積電、聯發科、日月光、京元電、廣達、緯穎、緯創、鴻海、台達電",
         "Microsoft、Amazon、Alphabet、Meta、NVIDIA、Broadcom、Equinix、Digital Realty",
         "先看實質殖利率與雲端資本支出指引，再看訂單、折舊、產能利用率與自由現金流。",
         "若雲端業者以充足現金流支應投資，而且獲利上修持續高於資金成本上升，估值壓力未必會變成營運下修。"),
        ("美元與新台幣 → 出口換算、毛利與資金流",
         "美元升值可能增加台灣出口商的新台幣營收換算，但也可能提高美元計價設備、材料與海外擴產成本；不能只用匯率方向判斷毛利。",
         "台積電、聯發科、廣達、緯穎、緯創、鴻海、台達電",
         "Microsoft、Apple、Alphabet、Meta、Salesforce",
         "先看美元指數、美元兌新台幣、台美利差與外資流向，之後核對公司避險比率、匯兌損益與毛利率。",
         "若公司具備自然避險，且產品價格、出貨量與產品組合的影響遠大於匯率，匯率傳導就不是主因。"),
        ("終端需求 → 半導體與AI伺服器訂單",
         "過度緊縮通常先壓低企業軟體、一般伺服器、消費電子與汽車需求，再傳到晶圓投片、封裝測試與伺服器組裝；AI投資可能暫時與一般景氣脫鉤。",
         "台積電、聯電、聯發科、日月光、京元電、廣達、緯穎、緯創、英業達、智邦",
         "NVIDIA、AMD、Broadcom、Micron、Microsoft、Amazon、Oracle",
         "先看雲端資本支出、在手訂單、台灣外銷訂單、PMI新訂單與台灣月營收，之後看產能利用率、庫存與毛利率。",
         "若AI訂單、客戶預付款與先進製程利用率持續成長，而且一般景氣轉弱沒有造成公司下修指引，需求傳導假設就被削弱。"),
        ("信用條件 → 資料中心融資與供應商現金轉換",
         "信用利差與銀行放款標準收緊，會先影響新興雲端業者、資料中心開發商與高槓桿供應商，再透過專案延後、應收帳款與庫存傳到台灣供應鏈。",
         "廣達、緯穎、緯創、京元電、兆聯、漢唐、帆宣",
         "CoreWeave、Oracle、Equinix、Digital Realty及主要AI設備供應商",
         "先看高收益債利差、銀行放款標準、客戶預付款與資料中心融資完成率，之後看應收天數、存貨與營業現金流。",
         "若專案由現金充足的雲端巨頭承擔，或預付款、補助與長期融資已覆蓋建設支出，信用收緊不一定會傳到供應鏈訂單。"),
        ("殖利率曲線與避險成本 → 金融股",
         "短端利率、殖利率曲線與美元避險成本會同時影響銀行淨利差、壽險債券評價、資本比率與股利能力，因此高利率不等於金融股單向受益。",
         "國泰金、富邦金、中信金、玉山金、兆豐金",
         "JPMorgan、Bank of America、Wells Fargo、Citigroup、U.S. Bancorp、PNC",
         "先看曲線、存款成本、美元避險成本與放款需求，再看淨利差、信用成本、OCI與資本回報。",
         "若資產負債管理、固定利率資金與手續費收入足以抵銷評價及信用損失，政策錯誤對金融股的衝擊會低於預期。"),
        ("房貸利率與資產折現率 → 營建及REIT",
         "高利率先壓低購屋能力、交易量與資產估值，再影響推案、土地價格、再融資與租金收益；資料中心、物流、住宅與商場REIT不可視為同一方向。",
         "國建、華固、冠德、潤泰新，以及國泰金與富邦金的不動產曝險",
         "Prologis、Equinix、Digital Realty、Realty Income、Welltower、Simon Property、American Tower",
         "先看房貸利率、成交量、資本化率與債務到期，再看交屋、出租率、資產減損與實際再融資成本。",
         "若建商已有高預售比率與淨現金，或REIT具長期固定利率負債和強勁租金成長，估值壓力未必會轉成現金流惡化。"),
    ]
    out = ""
    for i, (title, chain, tw, overseas, lead, refute) in enumerate(rows):
        out += ("<details%s><summary>%s</summary><div class='transmission-body'><p><b>傳導：</b>%s</p>"
                "<p><b>台灣觀察公司：</b>%s</p><p><b>海外觀察公司：</b>%s</p>"
                "<p><b>驗證順序：</b>%s</p><p><b>反證：</b>%s</p></div></details>"
                % (" open" if i < 2 else "", esc(title), esc(chain), esc(tw), esc(overseas), esc(lead), esc(refute)))
    return out


def scenario_history_html(store):
    rows = []
    last_sig = None
    for snap in reversed(store.get("snapshots", [])):
        s = snap.get("scenario") or {}
        f = s.get("features") or {}
        if not s.get("key"):
            continue
        sig = (snap.get("ts", "")[:10], s.get("key"), s.get("stage"))
        if sig == last_sig:
            continue
        last_sig = sig
        rows.append((snap.get("ts", "")[:16].replace("T", " "), s.get("label"), s.get("stage"),
                     pct(f.get("market_hike")), scenario_labels(f)["growth"], scenario_labels(f)["credit"]))
        if len(rows) >= 20:
            break
    if not rows:
        return '<p class="muted">本次建立第一筆基準；下一次更新開始累積情境歷史。</p>'
    body = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td><td>%s</td><td>%s</td></tr>"
                   % tuple(esc(x) for x in row) for row in rows)
    return ("<div class='table-wrap'><table><thead><tr><th>時間（UTC）</th><th>情境</th><th>判斷階段</th>"
            "<th>市場升息定價</th><th>成長／就業</th><th>信用</th></tr></thead><tbody>%s</tbody></table></div>" % body)


def source_ledger_html(macro, snap):
    series = ["PCEPILFE", "CPILFESL", "UNRATE", "PAYEMS", "T10YIE", "DGS2", "DGS10",
              "DCOILWTICO", "T10Y2Y", "ICSA", "BAMLH0A0HYM2", "NFCI", "DRTSCILM"]
    body = ""
    for sid in series:
        m = macro.get(sid) or {}
        body += ("<tr><td><a href='https://fred.stlouisfed.org/series/%s' target='_blank' rel='noopener'>%s</a></td>"
                 "<td>FRED／官方或聯準銀行資料</td><td>%s</td><td>%s</td></tr>"
                 % (sid, esc(m.get("name") or sid), esc(m.get("date") or "等待更新"),
                    "已取得" if m else "尚未取得"))
    body += ("<tr><td><a href='https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm' target='_blank' rel='noopener'>FOMC 會議日曆</a></td>"
             "<td>Federal Reserve／官方日曆</td><td>依官方頁面</td><td>會議日期</td></tr>")
    body += ("<tr><td>Kalshi／Polymarket／CME FedWatch轉述</td><td>市場機率</td><td>%s</td><td>市場正在交易的預期，不是已發生事實</td></tr>"
             % esc((snap.get("ts") or "")[:16].replace("T", " ")))
    return ("<div class='table-wrap'><table><thead><tr><th>來源</th><th>來源類型</th><th>資料截至</th><th>用途／限制</th>"
            "</tr></thead><tbody>%s</tbody></table></div>" % body)


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
    features = M.scenario_features(store["macro"], market, mdl, expert, meetings,
                                   CFG["scenario_rules"])
    scenario = M.classify_policy_scenario(features, CFG["scenario_rules"])
    snap["model"] = {"hawk_score": mdl["hawk_score"], "dists": mdl["dists"]}
    snap["blend"] = blended
    snap["scenario"] = scenario
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
<meta name="robots" content="noindex,nofollow,noarchive"><title>聯準會政策錯誤雷達｜研究路徑 02</title>
<style>
:root{color-scheme:dark;--bg:#091018;--surface:#101a25;--card:#142130;--ink:#eef4f8;--muted:#9cadbc;--line:#2a3b4d;--gold:#f2c35b;--teal:#43cfbf;--red:#ff7b86;--blue:#77aef7;--orange:#ffac63}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 8% 0,rgba(67,207,191,.08),transparent 28%),var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI","Noto Sans TC","Microsoft JhengHei",sans-serif;line-height:1.65}
.wrap{max-width:1180px;margin:0 auto;padding:24px 18px 72px}.site-head{padding:10px 0 18px;border-bottom:1px solid var(--line)}
h1{font-size:clamp(28px,4vw,42px);letter-spacing:-.035em;margin:2px 0 4px}h2{font-size:23px;letter-spacing:-.02em;margin:42px 0 14px}h3{font-size:16px;margin:0 0 8px}.eyebrow{margin:0;color:var(--teal);font-size:12px;font-weight:900;letter-spacing:.11em;text-transform:uppercase}.sub,.note,.muted{color:var(--muted);font-size:13px}.plain{margin:8px 0 0;color:#d7e2e9}
nav{display:flex;gap:8px;overflow:auto;margin-top:16px;padding-bottom:4px}nav a{flex:none;padding:6px 10px;border:1px solid var(--line);border-radius:999px;color:var(--muted);font-size:12px;text-decoration:none}nav a:hover{color:var(--ink);border-color:var(--blue)}
.decision{display:grid;grid-template-columns:minmax(260px,.82fr) 1.5fr;gap:18px;margin:20px 0 0;padding:20px;border:1px solid var(--line);border-left:5px solid var(--blue);border-radius:18px;background:linear-gradient(135deg,rgba(119,174,247,.08),transparent 44%),var(--surface)}.decision.risk{border-left-color:var(--red)}.decision.warn{border-left-color:var(--orange)}.decision.ok{border-left-color:var(--teal)}.decision h2{margin:5px 0 4px;font-size:28px}.stage{margin:0;font-weight:850;color:var(--gold)}
.decision-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.decision-grid div{padding:13px;background:rgba(7,13,20,.5);border:1px solid var(--line);border-radius:12px}.decision-grid span,.decision-grid small{display:block;color:var(--muted);font-size:11px}.decision-grid b{display:block;margin:3px 0;font-size:15px}
.card{margin:12px 0;padding:16px;background:var(--surface);border:1px solid var(--line);border-radius:14px}.confirm{border-left:4px solid var(--teal)}.two-col{display:grid;grid-template-columns:1fr 1fr;gap:12px}.matrix{display:grid;grid-template-columns:1fr 1fr;gap:12px}.scenario-cell{padding:16px;margin:0;background:var(--surface);border:1px solid var(--line);border-radius:14px}.scenario-cell.active{border-color:var(--gold);box-shadow:0 0 0 2px rgba(242,195,91,.13)}.scenario-cell span{color:var(--muted);font-size:11px}.scenario-cell h3{margin-top:5px;color:var(--gold)}.scenario-cell p{margin:0;color:#c6d2da;font-size:13px}.read-list,.change-list{margin:8px 0 0;padding-left:20px}.read-list li,.change-list li{margin:8px 0}.change-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 28px}.change-list li{padding-left:3px}
.probability-strip{display:flex;gap:24px;flex-wrap:wrap;align-items:center;padding:18px;background:var(--surface);border:1px solid var(--line);border-radius:14px}.hbucket{text-align:center;min-width:64px}.hpct{display:block;font-size:31px;font-weight:900}.hlab{color:var(--muted);font-size:11px}.probability-note{margin-left:auto;max-width:360px;color:var(--muted);font-size:13px}
.chead{display:flex;align-items:baseline;gap:12px;margin-bottom:10px}.days{color:var(--muted);font-size:12px}.verdict{margin-left:auto;font-weight:900}.lrow{display:flex;align-items:center;gap:10px;margin:7px 0}.lname{width:92px;font-size:13px;color:var(--muted)}.lname em{display:block;font-size:10px;font-style:normal;opacity:.75}.track{flex:1;display:flex;height:24px;border-radius:6px;overflow:hidden;background:#0a121b}.track.empty{align-items:center;padding-left:10px;color:var(--muted);font-size:12px}.seg{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:850;color:#10131a;min-width:0}
svg{width:100%;height:auto;background:#0a121b;border-radius:10px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:12px}table{width:100%;border-collapse:collapse;font-size:12.5px}th,td{padding:10px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{position:sticky;top:0;background:#101a25;color:#cbd7df}.num{text-align:right;white-space:nowrap}.evidence{min-width:1040px}.fbar{width:34%}.fmid{position:relative;height:12px;background:#0a121b;border-radius:6px}.fmid:before{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--line)}.fseg{position:absolute;top:0;bottom:0;border-radius:6px}.fseg.right{left:50%}.fseg.left{right:50%}
details{margin:10px 0;background:var(--surface);border:1px solid var(--line);border-radius:12px}summary{cursor:pointer;padding:13px 15px;font-weight:800}.transmission-body{padding:0 15px 13px;border-top:1px solid var(--line)}.transmission-body p{margin:10px 0;color:#cad6de;font-size:13px}.transmission-body b{color:var(--ink)}
.quotes{list-style:none;margin:0;padding:0}.quotes li{padding:9px 0;border-bottom:1px solid var(--line);font-size:13px}.quotes time{color:var(--muted);margin-right:8px;font-size:12px}.qt{margin-right:6px}.chip{display:inline-block;min-width:30px;text-align:center;margin-right:8px;padding:1px 7px;border-radius:20px;font-size:11px;font-weight:800}.chip.hawk{background:#3a1520;color:var(--red)}.chip.dove{background:#0f2f2d;color:var(--teal)}.chip.neu{background:#2a2a1a;color:var(--gold)}.chip.un{background:#20293a;color:var(--muted)}.tally .h{color:var(--red)}.tally .d{color:var(--teal)}
article:not(.scenario-cell){padding:12px 14px;margin:10px 0;background:#0a121b;border:1px solid var(--line);border-radius:10px}article h4{margin:0 0 6px;color:var(--gold)}a{color:var(--blue)}.meth{font-size:13px;color:var(--muted)}.meth b{color:var(--ink)}.callout{padding:12px 14px;border-left:4px solid var(--gold);background:rgba(242,195,91,.08);color:#dce5eb;font-size:13px}
footer{margin-top:48px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
@media(max-width:760px){.decision{grid-template-columns:1fr}.decision-grid,.matrix,.two-col,.change-list{grid-template-columns:1fr}.wrap{padding-inline:13px}.lrow{align-items:flex-start}.lname{width:72px}.probability-note{margin-left:0}.chead{flex-wrap:wrap}.verdict{margin-left:0;width:100%}}
</style></head><body><div class="wrap">
<header class="site-head"><p class="eyebrow">研究路徑 02｜持續追蹤</p><h1>聯準會政策錯誤雷達</h1>
<p class="sub">研究問題：通膨預期仍穩定時轉鷹，究竟只是一次預防性升息，還是政策錯誤的起點？｜現行目標區間 <b>{{TLOW}}%–{{THIGH}}%</b>｜更新 {{NOW}}（台北）</p>
<nav><a href="#status">目前判斷</a><a href="#changes">本次變化</a><a href="#matrix">四情境</a><a href="#evidence">核心證據</a><a href="#pricing">市場定價</a><a href="#transmission">台美股傳導</a><a href="#analysis">每日推演</a><a href="#history">歷史</a><a href="#sources">來源</a></nav></header>
{{SCENARIO}}
<section id="changes"><h2>這次更新改變了什麼</h2><div class="card">{{CHANGES}}</div></section>
<section id="matrix"><h2>四種互斥情境：先判斷經濟，再看市場交易了多少</h2>{{MATRIX}}{{CONFLICTS}}</section>
<section id="evidence"><h2>核心證據與下一個驗證門檻</h2>
<p class="callout">「最新值」是已公布資料或已發生的市場定價；「目前怎麼解讀」是研究判斷。初版門檻尚未回測，不能當作交易規則。</p>{{EVIDENCE}}</section>
<section id="pricing"><h2>市場定價：與情境判斷分開顯示</h2>
<div class="probability-strip">{{HERO}}<div class="probability-note">下次會議（{{NLABEL}}）的三層合成機率，權重為市場 {{WM}}%、反應函數 {{WO}}%、專家言論 {{WE}}%。這個合成結果描述政策路徑，不等於政策錯誤機率。</div></div>
<h3 style="margin-top:22px">預期政策利率路徑</h3><div class="card">{{PATH}}</div>
<h3 style="margin-top:22px">未來四次會議機率分布</h3>{{CARDS}}
<h3 style="margin-top:22px">下次會議升息定價的歷史軌跡</h3><div class="card">{{HIST}}</div>
<h3 style="margin-top:22px">總經反應函數的七項因子</h3><div class="card">{{FACTORS}}</div></section>
<section id="transmission"><h2>如果情境成立，怎麼傳到台灣與海外公司</h2>
<p class="note">公司名稱是需要查證的觀察名單，不代表已確認受益或受害。股價反應只能說明市場可能交易了多少，不能單獨證明訂單、毛利或信用已經改變。</p>{{TRANSMISSION}}</section>
<section id="analysis"><h2>每日推演與專家觀點</h2><div class="two-col"><div><h3>既有每日推演</h3>{{COMM}}</div>
<div><details open><summary>券商與專家言論（21日觀察窗、14日半衰期）</summary><div class="transmission-body">{{QUOTES}}</div></details></div></div></section>
<section id="history"><h2>情境變化歷史</h2>{{SCENARIO_HISTORY}}
<p class="note">歷史採追加方式保留。新情境若只出現一次，先視為暫定；至少等下一次排程或下一個官方數據交叉確認。</p></section>
<section id="sources"><h2>來源、資料截至與限制</h2>{{SOURCES}}
<div class="card meth"><h3>持續追蹤節奏</h3><p><b>每六小時：</b>更新市場機率、FRED數據、模型與四象限判斷。<b>重要數據或FOMC後：</b>下一輪自動更新重新分類，也可手動立即重跑。<b>每週：</b>回看情境歷史、反證是否增加，以及台美股傳導是否從估值進一步進入營運數據。</p>
<h3>方法邊界</h3><p><b>市場層：</b>Kalshi、Polymarket與金十快訊轉述的CME FedWatch。<b>模型層：</b>核心PCE、核心CPI近期動能、10年損益兩平通膨率代理、就業、油價、殖利率曲線與實質利率七項訊號。<b>專家層：</b>21日內言論，以14日為時間衰減半衰期；少於 {{MINQ}} 條時停用。</p>
<p><b>四象限層：</b>與三層機率相互獨立，專門檢查「通膨預期、成長、信用與市場升息定價」是否互相矛盾。資料缺口：{{GAPS}}。</p>
<p>本頁為個人研究工具，情境門檻未經樣本外回測，不是投資建議。金十快訊原文版權屬原資料提供者，僅供本人研究使用，請勿轉傳。</p></div></section>
<footer>資料源：Federal Reserve・FRED・Kalshi・Polymarket・金十數據｜每日 4 次自動更新｜研究判斷與市場預期分離</footer>
</div></body></html>"""
    rep = {
        "TLOW": "%.2f" % tgt["low"], "THIGH": "%.2f" % tgt["high"],
        "NLABEL": nxt["label"], "NOW": now_tpe,
        "SCENARIO": scenario_summary_html(scenario, nxt["label"]),
        "CHANGES": what_changed_html(store, meetings, market, mdl, scenario),
        "MATRIX": scenario_matrix_html(scenario["key"]),
        "CONFLICTS": conflict_and_falsifier_html(scenario),
        "EVIDENCE": metric_evidence_html(store["macro"], scenario),
        "HERO": hero or '<p class="muted">等待首批市場資料…</p>',
        "WM": "%.0f" % (CFG["weights"]["market"] * 100),
        "WO": "%.0f" % (CFG["weights"]["model"] * 100),
        "WE": "%.0f" % (CFG["weights"]["expert"] * 100),
        "CARDS": cards,
        "PATH": path_svg(market, blended, meetings, mid),
        "HIST": history_svg(store, nxt["key"], nxt["label"]),
        "FACTORS": factor_table(mdl), "QUOTES": quotes_html(store["quotes"]),
        "COMM": commentary_html(store["commentary"]), "MINQ": str(CFG["expert_min_quotes"]),
        "TRANSMISSION": transmission_html(),
        "SCENARIO_HISTORY": scenario_history_html(store),
        "SOURCES": source_ledger_html(store["macro"], snap),
        "GAPS": "、".join(features.get("missing", [])) or "目前核心欄位已齊全",
    }
    for k, v in rep.items():
        page = page.replace("{{" + k + "}}", v)

    fwcrypto.write_encrypted_page(page, password, BASE)
    print("[build] page written: %d chars, scenario=%s, blend(next)=%s"
          % (len(page), scenario["key"], json.dumps(nb)))


if __name__ == "__main__":
    main()

