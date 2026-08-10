# -*- coding: utf-8 -*-
"""FED 反應函數模型（第二層）＋ 三層合成（市場/模型/專家）。
設計原則：完全透明、每個因子的貢獻都攤在頁面上，可被檢驗與質疑。
模型輸出鷹派分數 H → 映射成升降息機率分布（離散常態）。
"""
import datetime as dt
import math

BUCKETS = ["cut50p", "cut25", "hold", "hike25", "hike50p"]
MOVES = {"cut50p": -2, "cut25": -1, "hold": 0, "hike25": 1, "hike50p": 2}


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def factors_from_macro(macro, target_mid):
    """回傳 [(代號, 說明, 顯示值, 正規化分數, 權重)]；分數>0 偏鷹。
    設計原則：日頻前瞻因子（通膨預期／曲線／實質利率）與落後的物價實績並用，
    但不放「2年債 − 目標中值」——那等於用債市推利率路徑，會跟市場層重複計算。
    """
    f = []

    # ---- 物價實績（落後，降權） ----
    pce = macro.get("PCEPILFE", {})
    if "yoy" in pce:
        f.append(("infl", "核心PCE年增率 − 2%%目標（%s）" % pce.get("date", "")[:7], pce["yoy"],
                  _clip((pce["yoy"] - 2.0) / 1.0, -2, 2), 0.25))
    cpi = macro.get("CPILFESL", {})
    if "m3ann" in cpi:
        f.append(("mom", "核心CPI三個月年化動能 − 2%", cpi["m3ann"],
                  _clip((cpi["m3ann"] - 2.0) / 1.5, -2, 2), 0.15))

    # ---- 通膨預期（前瞻，日頻） ----
    ie = macro.get("T10YIE", {})
    if "value" in ie:
        v = ie["value"]
        s = _clip((v - 2.3) / 0.4, -2, 2)
        d20 = ie.get("chg20d")
        if d20 is not None:
            s += _clip(d20 / 0.15, -1, 1) * 0.5  # 近期動向加成
        f.append(("be", "10年通膨預期 − 2.3%%（20日變化 %s）"
                  % ("%+.2f" % d20 if d20 is not None else "—"), v,
                  _clip(s, -2, 2), 0.15))

    # ---- 就業動能 ----
    pay = macro.get("PAYEMS", {})
    un = macro.get("UNRATE", {})
    if "diff3avg" in pay:
        labor = _clip((pay["diff3avg"] - 100.0) / 150.0, -1.5, 1.5)
        if "chg3m" in un:
            labor -= 0.6 * _clip(un["chg3m"] / 0.3, -1.5, 1.5)
        f.append(("labor", "就業動能（非農3月均 %s 千人 vs 10萬）" % pay.get("diff3avg"),
                  pay.get("diff3avg"), _clip(labor, -2, 2), 0.15))

    # ---- 油價衝擊（部分已被通膨預期吸收，降權） ----
    oil = macro.get("DCOILWTICO", {})
    if "chg60d" in oil:
        f.append(("oil", "WTI 60天漲跌幅（供給衝擊傳導）", oil["chg60d"],
                  _clip(oil["chg60d"] / 25.0, -1.5, 1.5), 0.10))

    # ---- 曲線斜率（分解牛熊陡化） ----
    sp = macro.get("T10Y2Y", {})
    d2, d10 = macro.get("DGS2", {}), macro.get("DGS10", {})
    if "value" in sp:
        bp = sp["value"] * 100
        c2, c10 = d2.get("chg20d"), d10.get("chg20d")
        if c2 is not None and c10 is not None:
            dslope = c10 - c2
            short_leads = abs(c2) >= abs(c10)  # 哪一腳主導了形狀變化
            if dslope > 0.03:                  # 陡化
                if short_leads:
                    kind = "牛市陡化（2年領跌→降息預期）"
                    s = -_clip(-c2 / 0.20, 0, 1.5)
                else:
                    kind = "熊市陡化（10年領漲→期限溢價／財政）"
                    s = _clip(c10 / 0.30, 0, 0.6)
            elif dslope < -0.03:               # 平坦化
                if short_leads:
                    kind = "熊市平坦化（2年領漲→升息預期）"
                    s = _clip(c2 / 0.20, 0, 1.5)
                else:
                    kind = "牛市平坦化（10年領跌→成長疑慮）"
                    s = -_clip(-c10 / 0.30, 0, 0.6)
            else:
                kind, s = "形狀持平", 0.0
        else:
            kind, s = "（缺20日變化，僅看水位）", -_clip((bp - 20) / 60.0, -0.8, 0.8)
        f.append(("slope", "2s10s 斜率 %.0f bp｜%s" % (bp, kind), "%.0f bp" % bp,
                  _clip(s, -2, 2), 0.12))

    # ---- 10年實質利率（金融條件，鴿派抵銷） ----
    if "value" in d10 and "value" in ie:
        rr = d10["value"] - ie["value"]
        f.append(("real", "10年實質利率（金融條件；越高越不需升息）", round(rr, 2),
                  _clip(-(rr - 1.9) / 0.5, -1.5, 1.5), 0.08))
    return f


def hawk_score(factors):
    if not factors:
        return 0.0, 0.0
    wsum = sum(w for *_x, w in factors)
    h = sum(s * w for _c, _d, _v, s, w in factors) / (wsum or 1.0)
    return round(h, 3), wsum


def dist_from_mu(mu, sigma):
    """離散常態：對五個動作桶取密度後正規化。"""
    ps = {}
    for b, m in MOVES.items():
        ps[b] = math.exp(-((m - mu) ** 2) / (2 * sigma * sigma))
    s = sum(ps.values())
    return {b: round(v / s, 4) for b, v in ps.items()}


def model_layer(macro, meetings, target_mid, now=None):
    """對未來各會議產生模型機率。近的會議取完整訊號，遠的會議往不確定收斂。"""
    facs = factors_from_macro(macro, target_mid)
    h, _ = hawk_score(facs)
    mu0 = 1.15 * h  # 鷹派分數 → 預期動作（碼）
    out = {}
    for k, m in enumerate(meetings):
        mu = mu0 * (0.85 ** k)
        sigma = 0.80 * (1 + 0.35 * k)
        out[m["key"]] = dist_from_mu(mu, sigma)
    return {"factors": [{"code": c, "desc": d, "value": v, "score": round(s, 3), "weight": w}
                        for c, d, v, s, w in facs],
            "hawk_score": h, "dists": out}


def expert_layer(quotes, meetings, lookback_days, min_quotes, now=None):
    """已分類言論 → 鷹鴿淨傾向 → 分布。cls: hawk/dove/neutral；w 預設1。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    scored = []
    for q in quotes:
        if q.get("cls") not in ("hawk", "dove", "neutral"):
            continue
        try:
            t = dt.datetime.fromisoformat(q["time"].replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.timezone.utc)
        except Exception:
            continue
        age = (now - t).days
        if age > lookback_days:
            continue
        w = float(q.get("w", 1.0)) * (0.5 ** (age / 14.0))  # 越舊權重越低
        scored.append((q["cls"], w))
    n = len(scored)
    if n < min_quotes:
        return {"n": n, "tilt": None, "dists": None}
    tot = sum(w for _c, w in scored) or 1.0
    tilt = sum((1 if c == "hawk" else -1 if c == "dove" else 0) * w for c, w in scored) / tot
    out = {}
    for k, m in enumerate(meetings):
        mu = 1.1 * tilt * (0.9 ** k)
        sigma = 1.0 * (1 + 0.3 * k)
        out[m["key"]] = dist_from_mu(mu, sigma)
    return {"n": n, "tilt": round(tilt, 3), "dists": out}


def market_layer(snap, meetings):
    """Kalshi / Polymarket /（金十引用的）FedWatch 平均。"""
    out = {}
    srcs_used = {}
    for m in meetings:
        key = m["key"]
        cands = []
        for src in ("kalshi", "polymarket"):
            d = (snap.get(src) or {}).get(key)
            if d:
                cands.append((src, d))
        fw = snap.get("fedwatch")
        if fw and fw.get("meeting") == key and fw.get("probs"):
            cands.append(("fedwatch", fw["probs"]))
        if not cands:
            continue
        avg = {b: round(sum(d.get(b, 0.0) for _s, d in cands) / len(cands), 4) for b in BUCKETS}
        out[key] = avg
        srcs_used[key] = [s for s, _d in cands]
    return {"dists": out, "sources": srcs_used}


def blend(market, model, expert, meetings, weights):
    wm, wo, we = weights["market"], weights["model"], weights["expert"]
    out = {}
    for m in meetings:
        key = m["key"]
        layers = []
        if market["dists"].get(key):
            layers.append((wm, market["dists"][key]))
        if model["dists"].get(key):
            layers.append((wo, model["dists"][key]))
        if expert.get("dists") and expert["dists"].get(key):
            layers.append((we, expert["dists"][key]))
        if not layers:
            continue
        tw = sum(w for w, _d in layers)
        out[key] = {b: round(sum(w * d.get(b, 0.0) for w, d in layers) / tw, 4) for b in BUCKETS}
    return out

