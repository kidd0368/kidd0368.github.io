# -*- coding: utf-8 -*-
"""Fed Watch 與 Bond Watch 的共用聯動判讀。

這一層不改寫任一頁原有的機率或壓力指數，只負責檢查兩邊訊號是否互相確認。
所有門檻都是尚未回測的研究門檻，不是交易規則。
"""
import datetime as dt
import hashlib
import html
import json


RULES = {
    "market_hike_meaningful": 0.30,
    "policy_repricing_2y_bp": 15.0,
    "policy_repricing_real10_bp": 10.0,
    "term_premium_shock_bp": 15.0,
    "long_yield_shock_bp": 20.0,
    "long_leads_short_bp": 5.0,
    "policy_error_2y_fall_bp": -10.0,
    "policy_error_steepen_bp": 10.0,
    "inflation_expectation_rise_bp": 15.0,
    "discount_pressure_high": 70,
    "max_batch_gap_hours": 18.0,
    "daily_max_age_days": 5,
    "weekly_max_age_days": 10,
}


def _num(value):
    return float(value) if isinstance(value, (int, float)) else None


def _curve(snap, label):
    return next((row for row in (snap.get("curve") or []) if row.get("label") == label), {})


def _decomp(snap, series):
    return (snap.get("decomp") or {}).get(series) or {}


def _parse_ts(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _age_days(reference, date_value):
    try:
        return (reference.date() - dt.date.fromisoformat(str(date_value)[:10])).days
    except Exception:
        return None


def _fmt_bp(value):
    return "—" if value is None else "%+.0f bp" % value


def _fmt_pct(value, digits=0):
    return "—" if value is None else ("%." + str(digits) + "f%%") % (value * 100)


def _result(key, label, stage, tone, policy_read, bond_read, equity_read,
            evidence, next_checks, data, missing=None, provisional=True):
    return {
        "version": 1,
        "key": key,
        "label": label,
        "stage": stage,
        "tone": tone,
        "policy_read": policy_read,
        "bond_read": bond_read,
        "equity_read": equity_read,
        "evidence": evidence,
        "next_checks": next_checks,
        "data": data,
        "missing": missing or [],
        "provisional": provisional,
    }


def classify(fed_snapshot, bond_snapshot, rules=None):
    """回傳一個互斥的主要聯動狀態，以及可驗證的證據與下一門檻。"""
    r = dict(RULES)
    if rules:
        r.update(rules)

    scenario = (fed_snapshot or {}).get("scenario") or {}
    features = scenario.get("features") or {}
    bond_snapshot = bond_snapshot or {}

    y2 = _curve(bond_snapshot, "2Y")
    y10 = _curve(bond_snapshot, "10Y")
    real10 = _decomp(bond_snapshot, "DFII10")
    be10 = _decomp(bond_snapshot, "T10YIE")
    be5 = _decomp(bond_snapshot, "T5YIE")
    tp10 = _decomp(bond_snapshot, "THREEFYTP10")
    spread = (bond_snapshot.get("spreads") or {}).get("2s10s") or {}
    aligned = (bond_snapshot.get("aligned") or {}).get("term_premium_curve") or {}
    aligned20 = (aligned.get("chg") or {}).get("20") or {}

    d2 = _num((y2.get("chg") or {}).get("20"))
    d10 = _num((y10.get("chg") or {}).get("20"))
    real10_chg = _num((real10.get("chg") or {}).get("20"))
    be10_chg = _num((be10.get("chg") or {}).get("20"))
    be5_chg = _num((be5.get("chg") or {}).get("20"))
    tp10_chg = _num((tp10.get("chg") or {}).get("20"))
    slope20 = _num((spread.get("chg") or {}).get("20"))
    if slope20 is None and d2 is not None and d10 is not None:
        slope20 = d10 - d2
    aligned_d2 = _num(aligned20.get("y2_bp"))
    aligned_d10 = _num(aligned20.get("y10_bp"))
    aligned_tp10 = _num(aligned20.get("term_premium10_bp"))

    market_hike = _num(features.get("market_hike"))
    pressure = _num((bond_snapshot.get("pressure") or {}).get("score"))
    fed_ts = _parse_ts((fed_snapshot or {}).get("ts"))
    bond_ts = _parse_ts(bond_snapshot.get("ts"))
    batch_gap = abs((fed_ts - bond_ts).total_seconds()) / 3600 if fed_ts and bond_ts else None

    data = {
        "fed_scenario": scenario.get("key"),
        "fed_label": scenario.get("label"),
        "fed_stage": scenario.get("stage"),
        "growth": features.get("growth"),
        "credit": features.get("credit"),
        "inflation_expectations": features.get("inflation_expectations"),
        "market_hike": market_hike,
        "y2": _num(y2.get("value")),
        "y2_chg20_bp": d2,
        "y10": _num(y10.get("value")),
        "y10_chg20_bp": d10,
        "real10": _num(real10.get("value")),
        "real10_chg20_bp": real10_chg,
        "breakeven10": _num(be10.get("value")),
        "breakeven10_chg20_bp": be10_chg,
        "breakeven5": _num(be5.get("value")),
        "breakeven5_chg20_bp": be5_chg,
        "term_premium10": _num(tp10.get("value")),
        "term_premium10_chg20_bp": tp10_chg,
        "term_premium_common_date": aligned.get("date"),
        "term_premium_common_y2_chg20_bp": aligned_d2,
        "term_premium_common_y10_chg20_bp": aligned_d10,
        "term_premium_common_chg20_bp": aligned_tp10,
        "slope_2s10s_bp": _num(spread.get("bp")),
        "slope_2s10s_chg20_bp": slope20,
        "discount_pressure": pressure,
        "fed_ts": (fed_snapshot or {}).get("ts"),
        "bond_ts": bond_snapshot.get("ts"),
        "bond_asof": bond_snapshot.get("asof"),
        "batch_gap_hours": round(batch_gap, 2) if batch_gap is not None else None,
    }

    def dedupe(items):
        return list(dict.fromkeys(item for item in items if item))

    def insufficient(issues):
        missing = dedupe(issues)
        return _result(
            "insufficient", "聯動證據不足", "資料尚未同步，不能判斷兩頁是否互相確認", "muted",
            scenario.get("label") or "Fed Watch 尚無可用情境",
            "本次情境所需的債市資料或資料批次不完整。",
            "缺資料時不推導股票方向，也不沿用上一輪結論。",
            ["缺少：" + "、".join(missing)],
            ["補齊上述欄位，並讓兩頁完成同一輪更新後再分類。"],
            data, missing=missing,
        )

    base_issues = []
    if not scenario.get("key"):
        base_issues.append("Fed 情境")
    if fed_ts is None:
        base_issues.append("Fed Watch 資料批次時間")
    if bond_ts is None:
        base_issues.append("Bond Watch 資料批次時間")
    if batch_gap is not None and batch_gap > r["max_batch_gap_hours"]:
        base_issues.append("兩頁資料批次相差超過 %.0f 小時" % r["max_batch_gap_hours"])
    if base_issues:
        return insufficient(base_issues)

    reference = bond_ts

    def metric_issues(label, row, value, max_age):
        issues = []
        if value is None:
            issues.append(label + "缺少數值")
        age = _age_days(reference, row.get("date"))
        if age is None:
            issues.append(label + "缺資料日期")
        elif age > max_age:
            issues.append("%s已落後%d天" % (label, age))
        return issues

    y2_issues = metric_issues("2年債20日變化", y2, d2, r["daily_max_age_days"])
    y10_issues = metric_issues("10年債20日變化", y10, d10, r["daily_max_age_days"])
    real10_issues = metric_issues(
        "10年實質利率20日變化", real10, real10_chg, r["daily_max_age_days"],
    )
    be10_issues = metric_issues(
        "10年通膨預期代理20日變化", be10, be10_chg, r["daily_max_age_days"],
    )
    be5_issues = metric_issues(
        "5年通膨預期代理20日變化", be5, be5_chg, r["daily_max_age_days"],
    )
    aligned_issues = []
    if aligned_d2 is None or aligned_d10 is None or aligned_tp10 is None:
        aligned_issues.append("2年債、10年債與期限溢價的共同截至日變化")
    aligned_age = _age_days(reference, aligned.get("date"))
    if aligned_age is None:
        aligned_issues.append("期限溢價比較缺共同截至日")
    elif aligned_age > r["weekly_max_age_days"]:
        aligned_issues.append("期限溢價共同比較已落後%d天" % aligned_age)

    policy_repricing_issues = (
        ([] if market_hike is not None else ["純市場升息定價"]) +
        y2_issues + y10_issues + real10_issues
    )
    term_premium_issues = aligned_issues
    policy_error_issues = y2_issues + y10_issues
    if slope20 is None:
        policy_error_issues.append("2s10s曲線20日變化")
    stagflation_issues = y10_issues + be10_issues + be5_issues

    fed_key = scenario.get("key")
    growth = features.get("growth")
    credit = features.get("credit")
    inflation = features.get("inflation_expectations")

    policy_repricing = (
        not policy_repricing_issues and
        market_hike >= r["market_hike_meaningful"] and
        d2 >= r["policy_repricing_2y_bp"] and
        real10_chg >= r["policy_repricing_real10_bp"] and
        d2 >= d10 - r["long_leads_short_bp"]
    )
    term_premium_shock = (
        not term_premium_issues and
        aligned_tp10 >= r["term_premium_shock_bp"] and
        aligned_d10 >= r["long_yield_shock_bp"] and
        aligned_d10 - aligned_d2 >= r["long_leads_short_bp"] and
        aligned_d2 < r["policy_repricing_2y_bp"] and
        aligned_tp10 / aligned_d10 >= 0.5
    )
    policy_error_confirmed = (
        not policy_error_issues and
        fed_key == "policy_error" and
        (growth == "weakening" or credit == "tightening") and
        d2 <= r["policy_error_2y_fall_bp"] and
        (slope20 is not None and slope20 >= r["policy_error_steepen_bp"])
    )
    stagflation_confirmed = (
        not stagflation_issues and
        fed_key == "stagflation" and
        growth in ("cooling", "weakening") and
        be10_chg is not None and be10_chg >= r["inflation_expectation_rise_bp"] and
        be5_chg is not None and be5_chg >= r["inflation_expectation_rise_bp"] and
        d10 >= 10.0 and
        features.get("realized_inflation") == "hot"
    )

    common_evidence = []
    if market_hike is not None or d2 is not None:
        common_evidence.append(
            "純市場下次會議升息定價 %s；2年債近約20個交易日 %s。"
            % (_fmt_pct(market_hike), _fmt_bp(d2))
        )
    if d10 is not None or real10_chg is not None or slope20 is not None:
        common_evidence.append(
            "10年債近約20個交易日 %s，10年實質利率 %s，2s10s 曲線 %s。"
            % (_fmt_bp(d10), _fmt_bp(real10_chg), _fmt_bp(slope20))
        )
    if be10_chg is not None or be5_chg is not None:
        common_evidence.append(
            "10年與5年通膨預期代理近約20個交易日分別為 %s、%s。"
            % (_fmt_bp(be10_chg), _fmt_bp(be5_chg))
        )
    if not aligned_issues:
        common_evidence.append(
            "以共同截至日 %s 比較：2年債 %s、10年債 %s、10年期限溢價 %s。"
            % (aligned.get("date"), _fmt_bp(aligned_d2), _fmt_bp(aligned_d10),
               _fmt_bp(aligned_tp10))
        )
    common_checks = [
        "政策重新定價：升息定價至少30%，且2年債上升至少15 bp、10年實質利率上升至少10 bp。",
        "期限溢價衝擊：同一截至日下，10年債上升至少20 bp、期限溢價上升至少15 bp，且期限溢價占長端升幅至少一半。",
        "政策錯誤確認：成長或信用進一步惡化，同時2年債下降至少10 bp、2s10s陡化至少10 bp。",
        "停滯性通膨確認：成長轉弱、已實現通膨偏熱，5年與10年通膨預期代理皆上升至少15 bp，且10年債同步上升至少10 bp。",
    ]

    if stagflation_confirmed:
        return _result(
            "stagflation_confirmed", "停滯性通膨訊號獲得債市確認",
            "成長轉弱、通膨仍熱，且5年與10年通膨預期及長債殖利率同升", "risk",
            scenario.get("label") or "通膨風險升高",
            "通膨預期代理與長端殖利率同步上升，債市正在交易通膨與成長兩難。",
            "科技估值、原物料成本與資產折現率可能同時承壓；需再查企業調價能力與毛利率。",
            common_evidence, common_checks, data, provisional=False)

    if policy_error_confirmed:
        return _result(
            "policy_error_confirmed", "政策錯誤風險獲得債市確認",
            "短端下跌、曲線陡化，且成長或信用已進一步惡化", "risk",
            scenario.get("stage") or scenario.get("label") or "政策錯誤風險",
            "債市開始交易未來降息與成長下修，而非只交易一次會議。",
            "先檢查銀行信用成本、企業資本支出與景氣循環股獲利；不能只用估值反彈解讀。",
            common_evidence, common_checks, data, provisional=False)

    if term_premium_shock and policy_repricing:
        return _result(
            "dual_rate_shock", "政策重新定價與期限溢價同時施壓",
            "最新短端與實質利率已反映政策轉鷹；較低頻的期限溢價比較也跨過衝擊門檻", "risk",
            scenario.get("label") or "市場正在提高政策利率路徑",
            "這不是單一 Fed 交易或單一長債供給衝擊，而是兩種折現率來源同時存在。",
            "長天期成長股、REIT與高槓桿公司面臨雙重折現率壓力；仍需用獲利與信用資料分辨公司差異。",
            common_evidence, common_checks, data, provisional=False)

    if term_premium_shock:
        return _result(
            "term_premium_shock", "長端／期限溢價衝擊",
            "同一截至日下長債領漲且期限溢價擴大，不應誤寫成純粹的 Fed 升息交易", "warn",
            scenario.get("label") or "Fed 政策路徑未形成同幅度變化",
            "期限溢價解釋至少一半的長端升幅，財政供給或風險補償可能是重要來源。",
            "長天期成長股與REIT仍會受折現率壓力，但金融股與景氣判讀不等同於政策升息。",
            common_evidence, common_checks, data, provisional=False)

    if policy_repricing:
        return _result(
            "policy_repricing", "聯準會轉鷹獲得債市確認",
            "升息定價、短端與實質利率同步上升", "warn",
            scenario.get("label") or "市場正在提高政策利率路徑",
            "短端與實質利率同步上升，較符合政策重新定價，而非單純長債供給衝擊。",
            "科技與高估值資產先面臨折現率壓力；下一步要看獲利預期能否抵銷估值壓縮。",
            common_evidence, common_checks, data, provisional=False)

    if fed_key == "policy_error":
        if policy_error_issues:
            return insufficient(policy_error_issues)
        pressure_note = ("折現率壓力指數仍在高檔（%.0f/100）" % pressure
                         if pressure is not None and pressure >= r["discount_pressure_high"]
                         else "折現率壓力尚未形成新的高檔警報")
        return _result(
            "policy_error_unconfirmed", "政策錯誤風險，但債市尚未確認",
            "聯準會端出現風險訊號；短端、曲線與信用尚未形成完整確認", "watch",
            scenario.get("stage") or scenario.get("label") or "政策錯誤風險",
            "近約20個交易日的短端與曲線尚未同步呈現政策錯誤交易；%s。" % pressure_note,
            "目前較像高利率水位下的風險觀察。先看信用與企業獲利是否轉差，不能直接推導新一輪股價下跌。",
            common_evidence, common_checks, data)

    if fed_key in ("stagflation", "inflation_risk", "renewed_hiking"):
        if stagflation_issues:
            return insufficient(stagflation_issues)
        return _result(
            "inflation_risk_unconfirmed", "通膨風險尚未獲得債市完整確認",
            "Fed Watch 已提高通膨警戒，但通膨預期與長端尚未同時跨過門檻", "watch",
            scenario.get("stage") or scenario.get("label") or "通膨風險",
            "債市訊號不足以確認停滯性通膨或多次升息循環。",
            "暫不把所有科技、金融與原物料公司視為同方向；等待長端與通膨預期共同確認。",
            common_evidence, common_checks, data)

    generic_issues = policy_repricing_issues + term_premium_issues
    if generic_issues:
        return insufficient(generic_issues)

    if pressure is not None and pressure >= r["discount_pressure_high"]:
        return _result(
            "high_discount_pressure", "折現率水位偏高，但沒有新的共同衝擊",
            "債券水位仍對長天期資產不利，近期方向尚未與 Fed 情境形成同向加速", "watch",
            scenario.get("stage") or scenario.get("label") or "政策情境未出現警報",
            "折現率壓力指數 %.0f/100，但近期變化未達政策或期限溢價衝擊門檻。" % pressure,
            "估值仍受壓，但營運與股價方向要回到公司獲利、資本支出與信用資料驗證。",
            common_evidence, common_checks, data)

    return _result(
        "mixed", "政策與債市尚未形成共同方向",
        "目前沒有任一聯動情境跨過研究門檻", "ok",
        scenario.get("stage") or scenario.get("label") or "政策情境中性",
        "短端、長端、實質利率與期限溢價尚未組成可辨識的共同交易。",
        "維持觀察，不因單一利率日變動改寫公司基本面。",
        common_evidence, common_checks, data)


def render_card(linkage, current_page):
    """產生兩頁共用的聯動判讀卡。current_page: fed 或 bond。"""
    e = lambda value: html.escape(str(value or ""), quote=True)
    evidence = "".join("<li>%s</li>" % e(row) for row in linkage.get("evidence", []))
    checks = "".join("<li>%s</li>" % e(row) for row in linkage.get("next_checks", []))
    data = linkage.get("data") or {}
    tone = linkage.get("tone") or "muted"
    fed_cls = " current" if current_page == "fed" else ""
    bond_cls = " current" if current_page == "bond" else ""
    fed_current = ' aria-current="page"' if current_page == "fed" else ""
    bond_current = ' aria-current="page"' if current_page == "bond" else ""
    summary_id = e(linkage.get("summary_id") or "")
    return (
        '<div class="cross-watch %s" data-summary-id="%s">'
        '<div class="cross-top"><div><p class="cross-kicker">共同判讀｜政策 × 債市</p>'
        '<h3>%s</h3><p class="cross-stage">%s</p></div>'
        '<div class="watch-switch"><a class="%s"%s href="../fed-watch/">政策雷達</a>'
        '<a class="%s"%s href="../bond-watch/">債市雷達</a></div></div>'
        '<div class="cross-grid"><div><span>政策端</span><b>%s</b><p>%s</p></div>'
        '<div><span>債市驗證</span><b>%s</b><p>2年 %s｜10年 %s｜實質10年 %s</p></div>'
        '<div><span>股票傳導</span><b>%s</b><p>折現率壓力 %s/100；這是跨頁判讀，不是買賣訊號。</p></div></div>'
        '<div class="cross-cols"><div><h4>目前證據</h4><ul>%s</ul></div>'
        '<div><h4>下一個確認／反駁門檻</h4><ul>%s</ul></div></div>'
        '<p class="cross-foot">兩頁使用同一份共同摘要與同一套規則。所有門檻尚未回測；資料截至 %s｜摘要 %s。</p>'
        '</div>'
        % (e(tone), summary_id, e(linkage.get("label")), e(linkage.get("stage")),
           fed_cls.strip(), fed_current, bond_cls.strip(), bond_current,
           e(linkage.get("policy_read")), e(linkage.get("stage")),
           e(linkage.get("bond_read")), _fmt_bp(data.get("y2_chg20_bp")),
           _fmt_bp(data.get("y10_chg20_bp")), _fmt_bp(data.get("real10_chg20_bp")),
           e(linkage.get("equity_read")),
           "—" if data.get("discount_pressure") is None else "%.0f" % data["discount_pressure"],
           evidence, checks, e(data.get("bond_asof") or "—"), summary_id[:10] or "—")
    )


def with_summary_id(linkage, fed_snapshot, bond_snapshot):
    """為 canonical 共同摘要加入可在兩頁核對的一致識別碼。"""
    canonical = {
        "schema_version": 1,
        "fed_snapshot_ts": (fed_snapshot or {}).get("ts"),
        "bond_snapshot_ts": (bond_snapshot or {}).get("ts"),
        "linkage": linkage,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    out = dict(linkage)
    out["summary_id"] = digest
    return {
        "schema_version": 1,
        "summary_id": digest,
        "fed_snapshot_ts": canonical["fed_snapshot_ts"],
        "bond_snapshot_ts": canonical["bond_snapshot_ts"],
        "linkage": out,
    }


def validate_summary(summary):
    if not isinstance(summary, dict) or summary.get("schema_version") != 1:
        raise ValueError("unsupported cross-watch summary schema")
    linkage = summary.get("linkage")
    if not isinstance(linkage, dict) or not linkage.get("key"):
        raise ValueError("cross-watch summary has no linkage result")
    if summary.get("summary_id") != linkage.get("summary_id"):
        raise ValueError("cross-watch summary id mismatch")
    return summary
