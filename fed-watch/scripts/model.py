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
        f.append(("be", "10年損益兩平通膨率代理 − 2.3%%（20日變化 %s）"
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


def _prob(dist, *buckets):
    return sum((dist or {}).get(b, 0.0) for b in buckets)


def _macro_value(macro, series, field="value"):
    value = (macro.get(series) or {}).get(field)
    return float(value) if isinstance(value, (int, float)) else None


def _macro_date(macro, series):
    return str((macro.get(series) or {}).get("date") or "")


def scenario_features(macro, market, model, expert, meetings, rules):
    """建立獨立於三層機率之外的政策情境特徵。

    這裡刻意不把信用與初領失業金塞回原有 hawk_score，避免在沒有回測前
    改寫既有升降息機率。情境層的任務是找出市場、模型與總經資料的矛盾。
    """
    if not meetings:
        return {"available": False, "missing": ["FOMC 會議設定"]}

    ir = rules["inflation_expectations"]
    rr = rules["realized_inflation"]
    lr = rules["labor"]
    cr = rules["credit"]
    mr = rules["market"]
    next_key = meetings[0]["key"]
    mkt = (market.get("dists") or {}).get(next_key) or {}
    mdl = (model.get("dists") or {}).get(next_key) or {}
    later_hikes = [_prob((market.get("dists") or {}).get(m["key"]), "hike25", "hike50p")
                   for m in meetings[1:] if (market.get("dists") or {}).get(m["key"])]

    be = _macro_value(macro, "T10YIE")
    be20 = _macro_value(macro, "T10YIE", "chg20d")
    if be is None:
        inflation_expectations = "insufficient"
    elif (be >= ir["warning_level"] and be20 is not None and
          be20 >= ir["deanchor_20d_change"]):
        inflation_expectations = "deanchoring"
    elif be >= ir["warning_level"] or (be20 is not None and be20 >= ir["warning_20d_change"]):
        inflation_expectations = "at_risk"
    elif be <= ir["anchored_max"] and (be20 is None or be20 < ir["warning_20d_change"]):
        inflation_expectations = "anchored"
    else:
        inflation_expectations = "mixed"

    pce = _macro_value(macro, "PCEPILFE", "yoy")
    cpi3 = _macro_value(macro, "CPILFESL", "m3ann")
    hot_checks = []
    if pce is not None:
        hot_checks.append(pce >= rr["core_pce_hot"])
    if cpi3 is not None:
        hot_checks.append(cpi3 >= rr["core_cpi_3m_hot"])
    realized_inflation = "hot" if any(hot_checks) else ("easing" if hot_checks else "insufficient")

    labor_rows = []
    payroll = _macro_value(macro, "PAYEMS", "diff3avg")
    if payroll is not None:
        labor_rows.append({
            "metric": "非農就業三個月平均",
            "value": payroll,
            "unit": "千人",
            "date": _macro_date(macro, "PAYEMS"),
            "weak": payroll < lr["payroll_3m_weak_k"],
            "resilient": payroll >= lr["payroll_3m_resilient_k"],
        })
    unchg = _macro_value(macro, "UNRATE", "chg3m")
    if unchg is not None:
        labor_rows.append({
            "metric": "失業率三個月變化",
            "value": unchg,
            "unit": "個百分點",
            "date": _macro_date(macro, "UNRATE"),
            "weak": unchg >= lr["unemployment_3m_warning_pp"],
            "resilient": unchg <= 0,
        })
    claims = _macro_value(macro, "ICSA", "ma4")
    claims_chg = _macro_value(macro, "ICSA", "ma4chg4")
    if claims is not None:
        labor_rows.append({
            "metric": "初領失業金四週平均",
            "value": claims,
            "unit": "人",
            "date": _macro_date(macro, "ICSA"),
            "change": claims_chg,
            "weak": claims_chg is not None and claims_chg >= lr["claims_4w_rise_pct"],
            "resilient": claims_chg is not None and claims_chg <= 2.0,
        })
    labor_weak = sum(1 for row in labor_rows if row["weak"])
    labor_resilient = sum(1 for row in labor_rows if row["resilient"])
    if labor_weak >= 2:
        growth = "weakening"
    elif labor_weak == 1:
        growth = "cooling"
    elif len(labor_rows) >= 2 and labor_resilient >= 1:
        growth = "resilient"
    else:
        growth = "insufficient"

    credit_rows = []
    hy = _macro_value(macro, "BAMLH0A0HYM2")
    if hy is not None:
        credit_rows.append({
            "metric": "高收益債利差", "value": hy, "unit": "%",
            "date": _macro_date(macro, "BAMLH0A0HYM2"),
            "warning": hy >= cr["high_yield_warning"],
            "stress": hy >= cr["high_yield_stress"],
        })
    nfci = _macro_value(macro, "NFCI")
    if nfci is not None:
        credit_rows.append({
            "metric": "全國金融狀況指數", "value": nfci, "unit": "指數",
            "date": _macro_date(macro, "NFCI"),
            "warning": nfci >= cr["nfci_tight"], "stress": nfci >= 0.5,
        })
    sloos = _macro_value(macro, "DRTSCILM")
    if sloos is not None:
        credit_rows.append({
            "metric": "銀行收緊企業放款標準淨比例", "value": sloos, "unit": "%",
            "date": _macro_date(macro, "DRTSCILM"),
            "warning": sloos >= cr["sloos_tightening"], "stress": sloos >= 40.0,
        })
    credit_warnings = sum(1 for row in credit_rows if row["warning"])
    credit_stress = sum(1 for row in credit_rows if row["stress"])
    if credit_stress >= 1 or credit_warnings >= 2:
        credit = "tightening"
    elif len(credit_rows) >= 2 and credit_warnings == 0:
        credit = "benign"
    elif credit_rows:
        credit = "watch"
    else:
        credit = "insufficient"

    market_hike = _prob(mkt, "hike25", "hike50p") if mkt else None
    market_hold = _prob(mkt, "hold") if mkt else None
    market_cut = _prob(mkt, "cut25", "cut50p") if mkt else None
    model_hike = _prob(mdl, "hike25", "hike50p") if mdl else None
    expert_tilt = expert.get("tilt")
    hawk = model.get("hawk_score")
    # 在尚未結構化官方談話前，只用純市場升息定價當作政策轉鷹代理。
    # 自家模型或券商觀點可以偏鷹，但不能單獨被寫成 Fed 已轉鷹。
    hawkish_pressure = market_hike is not None and market_hike >= mr["hike_meaningful"]
    if market_hike is None:
        market_overlay = "insufficient"
    elif market_hike >= mr["hike_base_case"]:
        market_overlay = "hike_base_case"
    elif market_hike >= mr["hike_meaningful"]:
        market_overlay = "hike_meaningful"
    else:
        market_overlay = "hike_tail"

    missing = []
    for label, value in (("10年損益兩平通膨率代理", be), ("非農就業", payroll),
                         ("失業率", unchg), ("初領失業金", claims),
                         ("高收益債利差", hy), ("金融狀況指數", nfci),
                         ("銀行放款標準", sloos)):
        if value is None:
            missing.append(label)

    return {
        "available": True,
        "next_key": next_key,
        "inflation_expectations": inflation_expectations,
        "realized_inflation": realized_inflation,
        "growth": growth,
        "credit": credit,
        "market_overlay": market_overlay,
        "market_hike": market_hike,
        "market_hold": market_hold,
        "market_cut": market_cut,
        "model_hike": model_hike,
        "later_market_hike_max": max(later_hikes) if later_hikes else None,
        "expert_tilt": expert_tilt,
        "hawk_score": hawk,
        "hawkish_pressure": hawkish_pressure,
        "be": be,
        "be20": be20,
        "pce_yoy": pce,
        "core_cpi_3m": cpi3,
        "labor_rows": labor_rows,
        "credit_rows": credit_rows,
        "missing": missing,
        "market_sources": (market.get("sources") or {}).get(next_key, []),
    }


def classify_policy_scenario(features, rules):
    """把通膨預期與成長拆成四象限，再把市場定價當成獨立覆蓋層。"""
    if not features.get("available"):
        return {"key": "insufficient", "label": "證據不足", "stage": "尚無法分類",
                "provisional": True, "features": features}

    infl = features["inflation_expectations"]
    growth = features["growth"]
    weak_side = growth in ("cooling", "weakening")
    hawkish = features.get("hawkish_pressure", False)
    later_hike = features.get("later_market_hike_max")
    if infl == "insufficient" or growth == "insufficient":
        key, label = "insufficient", "證據不足"
    elif infl == "anchored" and growth == "resilient" and hawkish:
        key, label = "preventive_hike", "預防性升息／口頭轉鷹"
    elif (infl == "deanchoring" and growth == "resilient" and later_hike is not None and
          later_hike >= rules["market"]["later_hike_cycle"]):
        key, label = "renewed_hiking", "重新啟動升息循環"
    elif infl == "deanchoring" and growth == "resilient":
        key, label = "inflation_risk", "通膨失錨風險，但尚無多次升息定價"
    elif infl == "anchored" and weak_side and hawkish:
        key, label = "policy_error", "政策錯誤風險"
    elif infl == "anchored" and weak_side:
        key, label = "cooling_without_hawk", "成長降溫，但尚非政策錯誤"
    elif infl == "deanchoring" and weak_side:
        key, label = "stagflation", "停滯性通膨陷阱"
    else:
        key, label = "mixed", "過渡／矛盾情境"

    mr = rules["market"]
    hike = features.get("market_hike")
    if key == "policy_error":
        if (growth == "weakening" and features["credit"] == "tightening" and
                hike is not None and hike >= mr["hike_base_case"]):
            stage = "警報條件成立"
        elif growth == "weakening" or features["credit"] == "tightening":
            stage = "風險升高，仍待政策與信用交叉確認"
        else:
            stage = "觀察中：成長降溫，但尚未證明 Fed 已犯錯"
    elif key in ("renewed_hiking", "stagflation"):
        stage = "風險升高" if hike is not None and hike >= mr["hike_meaningful"] else "尚未成為市場主情境"
    elif key == "preventive_hike":
        stage = "市場正交易升息" if hike is not None and hike >= mr["hike_base_case"] else "目前較像口頭轉鷹"
    elif key == "cooling_without_hawk":
        stage = "尚未看到足夠的政策轉鷹或升息壓力"
    elif key == "inflation_risk":
        stage = "通膨預期代理已轉差，但遠期市場尚未交易升息循環"
    elif key == "insufficient":
        stage = "關鍵資料不足，暫不分類"
    else:
        stage = "證據方向不一致，暫不強迫歸類"

    support, refute, conflicts = [], [], []
    if infl == "anchored":
        support.append("10年損益兩平通膨率代理仍在研究門檻內，尚未看到失錨。")
    elif infl == "deanchoring":
        support.append("10年損益兩平通膨率代理的水位與近期變化都已跨過失錨警戒門檻。")
    if growth == "weakening":
        support.append("至少兩項勞動市場先行或同步指標轉弱。")
    elif growth == "cooling":
        support.append("已有一項勞動指標明顯轉弱，但其他指標尚未共同確認。")
    elif growth == "resilient":
        support.append("就業資料整體仍顯示韌性。")
    if features["credit"] == "tightening":
        support.append("信用或金融條件已出現收緊訊號。")
    elif features["credit"] == "benign":
        refute.append("信用與金融條件仍寬鬆，尚不支持『政策錯誤已發生』。")

    if features.get("pce_yoy") is not None and features["pce_yoy"] >= rules["realized_inflation"]["core_pce_hot"] and infl == "anchored":
        conflicts.append("核心PCE仍偏高，但10年損益兩平通膨率代理沒有同步失控；這是『預防性升息』與『過度緊縮』爭論的核心落差。")
    weak_labor = any(row["weak"] for row in features["labor_rows"])
    resilient_labor = any(row["resilient"] for row in features["labor_rows"])
    if weak_labor and resilient_labor:
        conflicts.append("勞動市場資料互相矛盾：部分招聘動能已轉弱，但失業率或初領失業金尚未全面惡化。")
    mh, oh = features.get("market_hike"), features.get("model_hike")
    if mh is not None and oh is not None and abs(mh - oh) >= mr["market_model_gap"]:
        conflicts.append("市場定價與總經反應函數的升息機率差距已達研究警戒值，必須分開判讀。")
    if key == "policy_error" and hawkish:
        support.append("純市場升息定價已跨過轉鷹研究門檻；模型與券商觀點只作佐證。")

    if key == "policy_error":
        refute.extend([
            "若非農三個月平均回到研究門檻以上，且初領失業金沒有上升，成長轉弱假設將被反駁。",
            "若10年損益兩平通膨率代理明顯失錨，問題將改成通膨升息或停滯性通膨，而不是單純政策錯誤。",
        ])
    elif key == "preventive_hike":
        refute.append("若就業、信用與企業指引連續轉弱，『一次預防性升息可承受』的假設將失效。")
    elif key in ("renewed_hiking", "stagflation", "inflation_risk"):
        refute.append("若核心物價動能回落且10年損益兩平通膨率代理重新穩定，持續升息假設將被削弱。")

    return {
        "key": key,
        "label": label,
        "stage": stage,
        "provisional": True,
        "support": support[:4],
        "refute": refute[:4],
        "conflicts": conflicts[:4],
        "features": features,
    }

