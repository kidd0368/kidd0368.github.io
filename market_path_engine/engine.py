#!/usr/bin/env python3
"""Build the Market Path Engine V1 dashboard and its prediction archive.

The engine is deliberately dependency-free so it can run in GitHub Actions with
only Python's standard library. Official sources are preferred. Public quote
sources and model-derived proxies are explicitly labelled in the output.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import statistics
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = ROOT / "market_path_engine"
DATA_DIR = ENGINE_DIR / "data"
TEMPLATE_PATH = ENGINE_DIR / "dashboard_template.html"
OUTPUT_PATH = ROOT / "market-path" / "index.html"
LATEST_PATH = DATA_DIR / "latest.json"
PREDICTIONS_PATH = DATA_DIR / "predictions.jsonl"
VALIDATIONS_PATH = DATA_DIR / "validations.jsonl"

MODEL_VERSION = "mpe-v1.0.0"
USER_AGENT = "MarketPathEngine/1.0 (+https://github.com/kidd0368/kidd0368.github.io)"

FRED_SERIES = {
    "dgs2": "DGS2",
    "dgs10": "DGS10",
    "dgs30": "DGS30",
    "real10": "DFII10",
    "usd_broad": "DTWEXBGS",
    "ig_oas": "BAMLC0A0CM",
    "bbb_oas": "BAMLC0A4CBBB",
    "hy_oas": "BAMLH0A0HYM2",
    "fed_assets": "WALCL",
    "reserves": "WRESBAL",
    "tga": "WTREGEN",
    "rrp": "RRPONTSYD",
    "vix": "VIXCLS",
    "sp500": "SP500",
    "nasdaq": "NASDAQCOM",
    "wti": "DCOILWTICO",
}

SOURCE_REGISTRY = {
    "fred": {
        "name": "Federal Reserve Economic Data (FRED)",
        "kind": "official",
        "url": "https://fred.stlouisfed.org/",
        "note": "Rates, real yields, dollar, credit spreads, Fed balance sheet and liquidity series.",
    },
    "cboe": {
        "name": "Cboe Global Indices",
        "kind": "official",
        "url": "https://www.cboe.com/tradable_products/vix/vix_historical_data/",
        "note": "VIX9D, VIX, VIX3M and VVIX closing histories. V1 uses the index-tenor curve as a free VIX-curve proxy.",
    },
    "cftc": {
        "name": "CFTC Traders in Financial Futures",
        "kind": "official",
        "url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
        "note": "Weekly futures positioning. V1 reads the official futures-only TFF report.",
    },
    "ibkr": {
        "name": "IBKR market-data adapter",
        "kind": "existing / optional",
        "url": "https://www.interactivebrokers.com/campus/ibkr-api-page/twsapi-doc/",
        "note": "The V1 contract is ready for an existing IBKR connection; the deployable free build uses official FRED market series.",
    },
    "model": {
        "name": "Market Path Engine V1 model",
        "kind": "proxy",
        "url": "https://github.com/kidd0368/kidd0368.github.io/tree/main/market_path_engine",
        "note": "CTA, vol-control, Event Shock, regime and path probabilities are transparent proxies, not dealer or bank feeds.",
    },
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def round_or_none(value: float | None, digits: int = 2) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, digits)


def get_text(url: str, timeout: int = 30, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/csv,text/plain,application/json,*/*"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
            return raw.decode("utf-8-sig", errors="replace")
        except Exception as exc:  # Each source is allowed to fail independently.
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def parse_numeric(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {".", "NA", "N/A", "null", "None"}:
        return None
    try:
        number = float(text)
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def parse_date(value: str) -> str | None:
    text = value.strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        text = text[:10]
    candidates = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y%m%d")
    for fmt in candidates:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def fetch_fred(series_id: str) -> list[list[Any]]:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urllib.parse.urlencode({"id": series_id})
    rows = csv.DictReader(io.StringIO(get_text(url)))
    output: list[list[Any]] = []
    for row in rows:
        d = row.get("DATE") or row.get("observation_date") or next(iter(row.values()), "")
        value = row.get(series_id)
        if value is None and row:
            value = list(row.values())[-1]
        parsed_date, parsed_value = parse_date(str(d)), parse_numeric(value)
        if parsed_date and parsed_value is not None:
            output.append([parsed_date, parsed_value])
    if not output:
        raise RuntimeError(f"FRED returned no observations for {series_id}")
    return output[-900:]


def fetch_cboe_index(index_name: str) -> list[list[Any]]:
    url = f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{index_name}_History.csv"
    rows = csv.DictReader(io.StringIO(get_text(url)))
    output: list[list[Any]] = []
    for row in rows:
        normalized = {str(k).strip().upper(): v for k, v in row.items() if k is not None}
        d = normalized.get("DATE") or normalized.get("TRADE DATE")
        close = None
        for key, value in normalized.items():
            if "CLOSE" in key:
                close = parse_numeric(value)
                if close is not None:
                    break
        if close is None:
            close = parse_numeric(normalized.get(index_name.upper()))
        if close is None:
            close = next((parse_numeric(value) for key, value in normalized.items() if key not in {"DATE", "TRADE DATE"} and parse_numeric(value) is not None), None)
        parsed_date = parse_date(str(d or ""))
        if parsed_date and close is not None:
            output.append([parsed_date, close])
    output.sort(key=lambda item: item[0])
    if not output:
        raise RuntimeError(f"Cboe returned no observations for {index_name}")
    return output[-900:]


def fetch_cftc_positioning() -> dict[str, Any]:
    query = urllib.parse.urlencode({"$limit": 500, "$order": "report_date_as_yyyy_mm_dd DESC"})
    url = "https://publicreporting.cftc.gov/resource/gpe5-46if.json?" + query
    rows = json.loads(get_text(url))
    candidates = []
    for row in rows:
        market = str(row.get("market_and_exchange_names") or "")
        upper = market.upper()
        if "E-MINI S&P 500" in upper and "MICRO" not in upper:
            candidates.append(row)
    if not candidates:
        raise RuntimeError("CFTC TFF report did not contain E-mini S&P 500")
    row = candidates[0]

    def field(*names: str) -> float | None:
        for name in names:
            if name in row:
                return parse_numeric(row[name])
        wanted = {name.lower().replace("_", " ") for name in names}
        for key, value in row.items():
            if str(key).lower().replace("_", " ") in wanted:
                return parse_numeric(value)
        return None

    oi = field("open_interest_all") or 0.0
    asset_long = field("asset_mgr_positions_long")
    asset_short = field("asset_mgr_positions_short")
    lev_long = field("lev_money_positions_long")
    lev_short = field("lev_money_positions_short")
    asset_net = None if not oi or asset_long is None or asset_short is None else 100 * (asset_long - asset_short) / oi
    lev_net = None if not oi or lev_long is None or lev_short is None else 100 * (lev_long - lev_short) / oi
    report_date = (
        row.get("report_date_as_yyyy_mm_dd")
        or ""
    )
    return {
        "asof": parse_date(str(report_date)) or str(report_date).strip(),
        "market": str(row.get("market_and_exchange_names") or "E-mini S&P 500"),
        "open_interest": round_or_none(oi, 0),
        "asset_manager_net_pct_oi": round_or_none(asset_net),
        "leveraged_money_net_pct_oi": round_or_none(lev_net),
    }


def last(series: list[list[Any]] | None) -> float | None:
    return None if not series else parse_numeric(series[-1][1])


def asof(series: list[list[Any]] | None) -> str | None:
    return None if not series else str(series[-1][0])


def delta(series: list[list[Any]] | None, periods: int) -> float | None:
    if not series or len(series) <= periods:
        return None
    a, b = parse_numeric(series[-1 - periods][1]), parse_numeric(series[-1][1])
    return None if a is None or b is None else b - a


def pct_change(series: list[list[Any]] | None, periods: int) -> float | None:
    if not series or len(series) <= periods:
        return None
    a, b = parse_numeric(series[-1 - periods][1]), parse_numeric(series[-1][1])
    return None if a in {None, 0} or b is None else 100 * (b / a - 1)


def returns(series: list[list[Any]] | None) -> list[float]:
    if not series:
        return []
    values = [parse_numeric(row[1]) for row in series]
    result = []
    for previous, current in zip(values, values[1:]):
        if previous not in {None, 0} and current is not None and current > 0:
            result.append(math.log(current / previous))
    return result


def realized_vol(series: list[list[Any]] | None, periods: int) -> float | None:
    data = returns(series)
    if len(data) < periods:
        return None
    window = data[-periods:]
    return statistics.stdev(window) * math.sqrt(252) * 100 if len(window) > 1 else None


def last_return_z(series: list[list[Any]] | None, lookback: int = 60) -> float | None:
    data = returns(series)
    if len(data) < max(20, lookback // 2):
        return None
    sample = data[-lookback:]
    sigma = statistics.stdev(sample) if len(sample) > 1 else 0
    mean = statistics.mean(sample)
    return None if sigma == 0 else (sample[-1] - mean) / sigma


def carry_forward_series(existing: dict[str, Any], bucket: str, key: str) -> list[list[Any]]:
    return (((existing.get("raw") or {}).get(bucket) or {}).get(key) or [])


def metric(
    label: str,
    value: float | str | None,
    unit: str,
    source: str,
    *,
    change: float | None = None,
    change_label: str = "",
    quality: str = "live",
    note: str = "",
    history: list[list[Any]] | None = None,
    digits: int = 2,
) -> dict[str, Any]:
    normalized = round_or_none(value, digits) if isinstance(value, (int, float)) else value
    return {
        "label": label,
        "value": normalized,
        "unit": unit,
        "change": round_or_none(change, digits),
        "change_label": change_label,
        "source": source,
        "quality": quality,
        "note": note,
        "history": (history or [])[-90:],
    }


def module(score: float, stance: str, summary: str, metrics: list[dict[str, Any]]) -> dict[str, Any]:
    return {"score": round(score, 1), "stance": stance, "summary": summary, "metrics": metrics}


def softmax(values: Iterable[float]) -> list[float]:
    numbers = list(values)
    peak = max(numbers)
    exp_values = [math.exp(value - peak) for value in numbers]
    total = sum(exp_values)
    return [value / total for value in exp_values]


def path_probabilities(stress_score: float, event_score: float, liquidity_score: float) -> list[dict[str, Any]]:
    specs = [
        ("1–5D", 5, 0.95, 0.62, 1.0),
        ("1–4W", 20, 0.85, 0.46, 3.0),
        ("1–3M", 63, 0.72, 0.32, 6.0),
    ]
    output = []
    for label, days, sensitivity, event_weight, threshold in specs:
        directional = (50 - stress_score) / 18
        liquidity_tilt = (liquidity_score - 50) / 70
        shock_drag = max(0.0, (event_score - 45) / 55) * event_weight
        x = sensitivity * directional + liquidity_tilt - shock_drag
        logits = [0.86 * x, 0.50 - 0.30 * abs(x), -0.86 * x]
        probs = softmax(logits)
        rounded = [round(prob * 100, 1) for prob in probs]
        rounded[1] = round(100 - rounded[0] - rounded[2], 1)
        leader = ("up", "range", "down")[max(range(3), key=lambda i: probs[i])]
        output.append(
            {
                "horizon": label,
                "trading_days": days,
                "threshold_pct": threshold,
                "probabilities": {"up": rounded[0], "range": rounded[1], "down": rounded[2]},
                "dominant_path": leader,
                "note": {
                    "up": "風險資產延續／修復",
                    "range": "震盪消化、等待新催化",
                    "down": "去風險／流動性壓力延續",
                }[leader],
            }
        )
    return output


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except FileNotFoundError:
        return []


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def trading_target(series: list[list[Any]], anchor_date: str, trading_days: int) -> tuple[str, float] | None:
    dates = [str(row[0]) for row in series]
    try:
        index = dates.index(anchor_date)
    except ValueError:
        index = max((i for i, d in enumerate(dates) if d <= anchor_date), default=-1)
    target_index = index + trading_days
    if index < 0 or target_index >= len(series):
        return None
    value = parse_numeric(series[target_index][1])
    return None if value is None else (dates[target_index], value)


def update_archive(payload: dict[str, Any], price_series: list[list[Any]], anchor_symbol: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    predictions = read_jsonl(PREDICTIONS_PATH)
    validations = read_jsonl(VALIDATIONS_PATH)
    anchor_value = last(price_series)
    anchor_date = asof(price_series)
    prediction_id = f"{MODEL_VERSION}:{payload['asof']}"
    if anchor_value is not None and anchor_date and not any(p.get("prediction_id") == prediction_id for p in predictions):
        predictions.append(
            {
                "schema_version": "1.0",
                "prediction_id": prediction_id,
                "model_version": MODEL_VERSION,
                "generated_at": payload["generated_at"],
                "asof": payload["asof"],
                "anchor": {"symbol": anchor_symbol, "date": anchor_date, "close": round(anchor_value, 4)},
                "regime": payload["regime"],
                "paths": payload["paths"],
                "features": {key: value["score"] for key, value in payload["modules"].items()},
                "disclosure": "Heuristic V1 probabilities; not statistically calibrated and not investment advice.",
            }
        )

    existing_validation_ids = {record.get("validation_id") for record in validations}
    price_map = {str(row[0]): parse_numeric(row[1]) for row in price_series}
    for prediction in predictions:
        anchor = prediction.get("anchor") or {}
        start_price = parse_numeric(anchor.get("close"))
        start_date = str(anchor.get("date") or "")
        if start_price in {None, 0} or not start_date:
            continue
        for path in prediction.get("paths") or []:
            days = int(path.get("trading_days") or 0)
            validation_id = f"{prediction.get('prediction_id')}:{days}D"
            if validation_id in existing_validation_ids:
                continue
            target = trading_target(price_series, start_date, days)
            if not target:
                continue
            target_date, target_price = target
            if price_map.get(target_date) is None:
                continue
            return_pct = 100 * (target_price / start_price - 1)
            threshold = float(path.get("threshold_pct") or 0)
            actual = "up" if return_pct > threshold else "down" if return_pct < -threshold else "range"
            probabilities = path.get("probabilities") or {}
            probs = {key: clamp(float(probabilities.get(key, 0)) / 100, 1e-8, 1) for key in ("up", "range", "down")}
            brier = sum((probs[key] - (1.0 if key == actual else 0.0)) ** 2 for key in probs) / 3
            log_loss = -math.log(probs[actual])
            validations.append(
                {
                    "schema_version": "1.0",
                    "validation_id": validation_id,
                    "prediction_id": prediction.get("prediction_id"),
                    "model_version": prediction.get("model_version"),
                    "horizon": path.get("horizon"),
                    "target_date": target_date,
                    "anchor_close": start_price,
                    "target_close": round(target_price, 4),
                    "return_pct": round(return_pct, 3),
                    "threshold_pct": threshold,
                    "predicted_class": max(probs, key=probs.get),
                    "realized_class": actual,
                    "brier_score": round(brier, 5),
                    "log_loss": round(log_loss, 5),
                    "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
            )
            existing_validation_ids.add(validation_id)

    predictions = predictions[-500:]
    validations = validations[-1500:]
    write_jsonl(PREDICTIONS_PATH, predictions)
    write_jsonl(VALIDATIONS_PATH, validations)
    return predictions, validations


def build() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = read_json(LATEST_PATH, {})
    errors: list[str] = []
    source_status: dict[str, dict[str, Any]] = {}

    fred: dict[str, list[list[Any]]] = {}
    fred_success = 0
    for key, series_id in FRED_SERIES.items():
        try:
            fred[key] = fetch_fred(series_id)
            fred_success += 1
        except Exception as exc:
            fallback = carry_forward_series(existing, "fred", key)
            if fallback:
                fred[key] = fallback
            errors.append(f"FRED {series_id}: {exc}")
    source_status["fred"] = {
        "status": "live" if fred_success == len(FRED_SERIES) else "partial" if fred_success else "fallback",
        "asof": max((asof(series) or "" for series in fred.values()), default=""),
        "received": fred_success,
        "expected": len(FRED_SERIES),
    }

    cboe: dict[str, list[list[Any]]] = {}
    cboe_success = 0
    for key, index_name in {"vix9d": "VIX9D", "vix3m": "VIX3M", "vvix": "VVIX"}.items():
        try:
            cboe[key] = fetch_cboe_index(index_name)
            cboe_success += 1
        except Exception as exc:
            fallback = carry_forward_series(existing, "cboe", key)
            if fallback:
                cboe[key] = fallback
            errors.append(f"Cboe {index_name}: {exc}")
    source_status["cboe"] = {
        "status": "live" if cboe_success == 3 else "partial" if cboe_success else "fallback",
        "asof": max((asof(series) or "" for series in cboe.values()), default=""),
        "received": cboe_success,
        "expected": 3,
    }

    source_status["ibkr"] = {"status": "deferred", "asof": None, "received": 0, "expected": 0}

    try:
        cftc = fetch_cftc_positioning()
        source_status["cftc"] = {"status": "live", "asof": cftc.get("asof"), "received": 1, "expected": 1}
    except Exception as exc:
        cftc = ((existing.get("raw") or {}).get("cftc") or {})
        source_status["cftc"] = {
            "status": "fallback" if cftc else "missing",
            "asof": cftc.get("asof"),
            "received": 0,
            "expected": 1,
        }
        errors.append(f"CFTC: {exc}")

    # Financial conditions: a high score means tighter / more stressful.
    rate_20 = delta(fred.get("dgs10"), 20) or 0.0
    real_20 = delta(fred.get("real10"), 20) or 0.0
    usd_20 = pct_change(fred.get("usd_broad"), 20) or 0.0
    hy_20 = delta(fred.get("hy_oas"), 20) or 0.0
    financial_score = clamp(
        50 + 18 * clamp(rate_20 / 0.60, -1, 1) + 14 * clamp(real_20 / 0.40, -1, 1)
        + 10 * clamp(usd_20 / 3.0, -1, 1) + 18 * clamp(hy_20 / 1.0, -1, 1),
        0,
        100,
    )
    financial_stance = "Tightening" if financial_score >= 58 else "Easing" if financial_score <= 42 else "Neutral"

    fed_assets_bn = (last(fred.get("fed_assets")) or 0) / 1000
    reserves_bn = (last(fred.get("reserves")) or 0) / 1000
    tga_bn = (last(fred.get("tga")) or 0) / 1000
    rrp_bn = last(fred.get("rrp")) or 0
    net_liquidity_bn = fed_assets_bn - tga_bn - rrp_bn
    net_liquidity_change = (
        (delta(fred.get("fed_assets"), 4) or 0) / 1000
        - (delta(fred.get("tga"), 4) or 0) / 1000
        - (delta(fred.get("rrp"), 20) or 0)
    )
    reserves_change = (delta(fred.get("reserves"), 4) or 0) / 1000
    liquidity_score = clamp(50 + 35 * clamp(net_liquidity_change / 250, -1, 1) + 15 * clamp(reserves_change / 200, -1, 1), 0, 100)
    liquidity_stance = "Supportive" if liquidity_score >= 58 else "Draining" if liquidity_score <= 42 else "Neutral"

    vix = last(fred.get("vix"))
    vvix = last(cboe.get("vvix"))
    vix9d = last(cboe.get("vix9d"))
    vix3m = last(cboe.get("vix3m"))
    curve_slope = None if vix is None or vix3m is None or vix == 0 else 100 * (vix3m / vix - 1)
    volatility_score = clamp(
        20
        + 45 * clamp(((vix or 15) - 12) / 28, 0, 1)
        + 20 * clamp(((vvix or 90) - 80) / 80, 0, 1)
        + 15 * clamp(-(curve_slope or 0) / 20, 0, 1),
        0,
        100,
    )
    volatility_stance = "Stress" if volatility_score >= 65 else "Elevated" if volatility_score >= 48 else "Contained"

    # Transparent CTA and vol-control proxies based on public closes.
    trend_inputs = []
    for key in ("sp500", "nasdaq", "wti", "usd_broad", "dgs10"):
        series = fred.get(key)
        if series:
            momentum = statistics.mean([(pct_change(series, p) or 0) / scale for p, scale in ((20, 8), (60, 14), (120, 22))])
            trend_inputs.append(clamp(momentum, -1.5, 1.5))
    risk_trend = []
    for key in ("sp500", "nasdaq"):
        if fred.get(key):
            risk_trend.append(clamp((pct_change(fred[key], 60) or 0) / 12, -1, 1))
    cta_score = clamp(50 + 40 * (statistics.mean(risk_trend) if risk_trend else 0), 0, 100)
    cta_gross = clamp(100 * (statistics.mean(abs(value) for value in trend_inputs) if trend_inputs else 0), 0, 150)
    rv20 = realized_vol(fred.get("sp500"), 20)
    rv60 = realized_vol(fred.get("sp500"), 60)
    blended_vol = None if rv20 is None else 0.65 * rv20 + 0.35 * (rv60 or rv20)
    vol_control_exposure = None if blended_vol is None else clamp(10 / max(blended_vol, 1), 0.15, 1.50)
    vol_control_score = 50 if vol_control_exposure is None else clamp(vol_control_exposure / 1.5 * 100, 0, 100)
    asset_mgr_net = parse_numeric(cftc.get("asset_manager_net_pct_oi"))
    lev_net = parse_numeric(cftc.get("leveraged_money_net_pct_oi"))
    cftc_score = clamp(50 + 1.5 * (asset_mgr_net or 0) + 1.0 * (lev_net or 0), 0, 100)
    positioning_score = clamp(0.45 * cta_score + 0.35 * vol_control_score + 0.20 * cftc_score, 0, 100)
    positioning_stance = "Supportive" if positioning_score >= 58 else "Defensive" if positioning_score <= 42 else "Mixed"

    credit_oas_change = delta(fred.get("hy_oas"), 20)
    confirmations = [
        clamp((pct_change(fred.get("sp500"), 20) or 0) / 6, -1, 1),
        clamp((pct_change(fred.get("nasdaq"), 20) or 0) / 7, -1, 1),
        -clamp((credit_oas_change or 0) / 0.75, -1, 1),
        -clamp((pct_change(fred.get("usd_broad"), 20) or 0) / 3.0, -1, 1),
        clamp((pct_change(fred.get("wti"), 20) or 0) / 12, -1, 1),
    ]
    cross_score = clamp(50 + 42 * statistics.mean(confirmations), 0, 100)
    cross_stance = "Confirming risk" if cross_score >= 58 else "Confirming defense" if cross_score <= 42 else "Divergent"

    shock_z = [
        abs(value)
        for value in (
            last_return_z(fred.get("sp500")),
            last_return_z(fred.get("dgs10")),
            last_return_z(fred.get("usd_broad")),
            last_return_z(fred.get("vix")),
        )
        if value is not None
    ]
    event_score = clamp((statistics.mean(shock_z) if shock_z else 0) * 28, 0, 100)
    event_stance = "Shock" if event_score >= 72 else "Elevated" if event_score >= 45 else "Quiet"

    modules = {
        "financial": module(
            financial_score,
            financial_stance,
            "Rates, real yields, dollar and credit are combined as a tightening score; higher is more restrictive.",
            [
                metric("US 2Y", last(fred.get("dgs2")), "%", "fred", change=delta(fred.get("dgs2"), 20), change_label="20 obs", history=fred.get("dgs2")),
                metric("US 10Y", last(fred.get("dgs10")), "%", "fred", change=rate_20, change_label="20 obs", history=fred.get("dgs10")),
                metric("10Y real yield", last(fred.get("real10")), "%", "fred", change=real_20, change_label="20 obs", history=fred.get("real10")),
                metric("Broad USD", last(fred.get("usd_broad")), "index", "fred", change=usd_20, change_label="20 obs %", history=fred.get("usd_broad")),
                metric("IG OAS", last(fred.get("ig_oas")), "%", "fred", change=delta(fred.get("ig_oas"), 20), change_label="20 obs", history=fred.get("ig_oas")),
                metric("HY OAS", last(fred.get("hy_oas")), "%", "fred", change=hy_20, change_label="20 obs", history=fred.get("hy_oas")),
            ],
        ),
        "liquidity": module(
            liquidity_score,
            liquidity_stance,
            "Net Liquidity is a market proxy: Fed assets − TGA − ON RRP. It is not an official Federal Reserve measure.",
            [
                metric("Fed assets", fed_assets_bn, "$bn", "fred", change=(delta(fred.get("fed_assets"), 4) or 0) / 1000, change_label="4 weeks", history=[[d, v / 1000] for d, v in fred.get("fed_assets", [])]),
                metric("Reserve balances", reserves_bn, "$bn", "fred", change=reserves_change, change_label="4 weeks", history=[[d, v / 1000] for d, v in fred.get("reserves", [])]),
                metric("TGA", tga_bn, "$bn", "fred", change=(delta(fred.get("tga"), 4) or 0) / 1000, change_label="4 weeks", history=[[d, v / 1000] for d, v in fred.get("tga", [])], note="FRED weekly Treasury General Account series; direct Daily Treasury Statement can replace it in V2."),
                metric("ON RRP", rrp_bn, "$bn", "fred", change=delta(fred.get("rrp"), 20), change_label="20 obs", history=fred.get("rrp")),
                metric("Net liquidity proxy", net_liquidity_bn, "$bn", "model", change=net_liquidity_change, change_label="~4 weeks", note="Fed assets − TGA − ON RRP."),
            ],
        ),
        "volatility": module(
            volatility_score,
            volatility_stance,
            "The free VIX curve uses official 9-day, 30-day and 3-month volatility indices; it is labelled as a futures-curve proxy.",
            [
                metric("VIX", vix, "", "fred", change=delta(fred.get("vix"), 5), change_label="5 obs", history=fred.get("vix")),
                metric("VVIX", vvix, "", "cboe", change=delta(cboe.get("vvix"), 5), change_label="5 obs", history=cboe.get("vvix")),
                metric("VIX9D", vix9d, "", "cboe", history=cboe.get("vix9d")),
                metric("VIX3M", vix3m, "", "cboe", history=cboe.get("vix3m")),
                metric("VIX term slope", curve_slope, "%", "model", quality="proxy", note="VIX3M / VIX − 1; positive usually indicates contango."),
            ],
        ),
        "positioning": module(
            positioning_score,
            positioning_stance,
            "CFTC is observed weekly data. CTA and vol-control are transparent trend/risk-target proxies, not bank exposure estimates.",
            [
                metric("CFTC asset manager net", asset_mgr_net, "% OI", "cftc", quality=source_status["cftc"]["status"], note=f"E-mini S&P 500; report {cftc.get('asof') or 'n/a'}."),
                metric("CFTC leveraged money net", lev_net, "% OI", "cftc", quality=source_status["cftc"]["status"]),
                metric("CTA risk trend score", cta_score, "/100", "model", quality="proxy", note="20/60/120-day momentum across official S&P 500 and Nasdaq Composite closes."),
                metric("CTA gross trend proxy", cta_gross, "%", "model", quality="proxy", note="Average absolute standardized trend; not notional exposure."),
                metric("Vol-control exposure", None if vol_control_exposure is None else 100 * vol_control_exposure, "% NAV", "model", quality="proxy", note="10% target volatility divided by blended 20/60-day S&P 500 realized volatility; capped at 150%."),
            ],
        ),
        "cross_asset": module(
            cross_score,
            cross_stance,
            "Equities, credit, the dollar, energy and rates vote on whether the primary risk direction is confirmed or divergent.",
            [
                metric("S&P 500", last(fred.get("sp500")), "index", "fred", change=pct_change(fred.get("sp500"), 20), change_label="20 obs %", history=fred.get("sp500")),
                metric("Nasdaq Composite", last(fred.get("nasdaq")), "index", "fred", change=pct_change(fred.get("nasdaq"), 20), change_label="20 obs %", history=fred.get("nasdaq")),
                metric("HY OAS", last(fred.get("hy_oas")), "%", "fred", change=credit_oas_change, change_label="20 obs", history=fred.get("hy_oas")),
                metric("Broad USD", last(fred.get("usd_broad")), "index", "fred", change=pct_change(fred.get("usd_broad"), 20), change_label="20 obs %", history=fred.get("usd_broad")),
                metric("WTI crude", last(fred.get("wti")), "$/bbl", "fred", change=pct_change(fred.get("wti"), 20), change_label="20 obs %", history=fred.get("wti")),
                metric("US 10Y yield", last(fred.get("dgs10")), "%", "fred", change=delta(fred.get("dgs10"), 20), change_label="20 obs", history=fred.get("dgs10")),
            ],
        ),
        "event_shock": module(
            event_score,
            event_stance,
            "V1 measures realized cross-asset shock intensity. A forward official event calendar is intentionally deferred rather than filled with an unstable feed.",
            [
                metric("S&P 500 1D return z", last_return_z(fred.get("sp500")), "σ", "model", quality="proxy"),
                metric("10Y yield 1D move z", last_return_z(fred.get("dgs10")), "σ", "model", quality="proxy"),
                metric("USD 1D return z", last_return_z(fred.get("usd_broad")), "σ", "model", quality="proxy"),
                metric("VIX 1D return z", last_return_z(fred.get("vix")), "σ", "model", quality="proxy"),
                metric("Forward event calendar", "V2", "", "model", quality="deferred", note="FOMC/CPI/payroll calendar will be added only with a stable official source."),
            ],
        ),
    }

    stress_score = clamp(
        0.22 * financial_score
        + 0.18 * (100 - liquidity_score)
        + 0.22 * volatility_score
        + 0.14 * (100 - positioning_score)
        + 0.16 * (100 - cross_score)
        + 0.08 * event_score,
        0,
        100,
    )
    if stress_score >= 75:
        regime_name, regime_code = "Shock / Stress", "shock"
    elif stress_score >= 62:
        regime_name, regime_code = "Risk-off / Deleveraging", "risk_off"
    elif stress_score >= 52:
        regime_name, regime_code = "Transition / Fragile", "transition"
    elif stress_score >= 38:
        regime_name, regime_code = "Risk-on / Fragile", "risk_on_fragile"
    else:
        regime_name, regime_code = "Risk-on / Expansion", "risk_on"

    received = sum(status.get("received", 0) for status in source_status.values())
    expected = sum(status.get("expected", 0) for status in source_status.values())
    coverage = 0 if not expected else 100 * received / expected
    data_dates = [status.get("asof") for status in source_status.values() if status.get("asof")]
    overall_asof = max(data_dates, default=date.today().isoformat())
    paths = path_probabilities(stress_score, event_score, liquidity_score)

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "model_version": MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asof": overall_asof,
        "coverage_pct": round(coverage, 1),
        "status": "live" if coverage >= 95 else "partial" if coverage >= 50 else "degraded",
        "regime": {
            "name": regime_name,
            "code": regime_code,
            "stress_score": round(stress_score, 1),
            "confidence": round(clamp(coverage * (1 - abs(stress_score - 50) / 180), 0, 100), 1),
            "summary": f"Composite stress is {stress_score:.1f}/100. Financial conditions are {financial_stance.lower()}, liquidity is {liquidity_stance.lower()}, and cross-asset confirmation is {cross_stance.lower()}.",
        },
        "paths": paths,
        "modules": modules,
        "vix_curve": [
            {"tenor": "9D", "value": round_or_none(vix9d)},
            {"tenor": "30D", "value": round_or_none(vix)},
            {"tenor": "3M", "value": round_or_none(vix3m)},
        ],
        "source_registry": SOURCE_REGISTRY,
        "source_status": source_status,
        "warnings": errors[-20:],
        "methodology": {
            "eps_included": False,
            "probability_type": "heuristic_prior",
            "calibrated": False,
            "net_liquidity_formula": "Fed assets − TGA − ON RRP",
            "free_data_first": True,
            "ibkr_adapter": "planned; public quote adapter is used in V1",
        },
        "raw": {"fred": fred, "cboe": cboe, "cftc": cftc},
    }

    anchor_series = fred.get("sp500") or []
    predictions, validations = update_archive(payload, anchor_series, "SP500")
    payload["archive"] = {
        "prediction_count": len(predictions),
        "validation_count": len(validations),
        "recent_predictions": list(reversed(predictions[-8:])),
        "recent_validations": list(reversed(validations[-12:])),
        "schema_paths": {
            "prediction": "../market_path_engine/schema/prediction.schema.json",
            "validation": "../market_path_engine/schema/validation.schema.json",
        },
    }
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    embedded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    output = template.replace("/*__MPE_DATA__*/null", embedded, 1)
    if output == template:
        raise RuntimeError("dashboard template data placeholder was not found")
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    return payload


def main() -> None:
    payload = build()
    print(
        json.dumps(
            {
                "status": payload["status"],
                "asof": payload["asof"],
                "coverage_pct": payload["coverage_pct"],
                "regime": payload["regime"]["name"],
                "stress_score": payload["regime"]["stress_score"],
                "output": str(OUTPUT_PATH.relative_to(ROOT)),
                "warnings": len(payload["warnings"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
