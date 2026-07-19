#!/usr/bin/env python3
"""Fetch public evidence and market proxies for the Iran war terminal tracker.

The collector deliberately stores headlines, source metadata and links only. It
does not scrape article bodies, infer missile inventories, or calculate an
interception rate. All counts in the dashboard are counts of public evidence
items, not counts of attacks or weapons.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SNAPSHOT_PATH = DATA_DIR / "snapshot.json"
USER_AGENT = "IranTerminalTracker/1.0 (+https://kidd0368.github.io/iran-war/)"
NOW = datetime.now(timezone.utc)

QUERIES = {
    "海峽與商船": '(Iran OR Iranian) (Hormuz OR tanker OR "commercial ship" OR shipping)',
    "軍事行動": '(Iran OR Iranian) (strike OR missile OR drone OR CENTCOM)',
    "基礎設施": 'Iran ("power plant" OR desalination OR bridge OR infrastructure)',
    "外交與停火": '("US Iran" OR "U.S. Iran") (talks OR ceasefire OR agreement OR negotiation)',
    "核問題": 'Iran (nuclear OR uranium OR IAEA)',
    "以色列動向": '(Israel OR Israeli OR IDF) (Iran OR Iranian) (retaliate OR strike OR attack OR readiness OR Netanyahu OR Katz)',
    "紅海與蘇伊士": '(Iran OR Iranian OR Houthi OR Houthis) ("Bab el-Mandeb" OR "Red Sea" OR Suez OR shipping)',
    "非對稱戰術": '(Iran OR Iranian OR IRGC OR Houthi) ("Ukraine tactics" OR "asymmetric warfare" OR "mobile launcher" OR "dispersed forces" OR "drone swarm" OR "unmanned boat")',
}

OFFICIAL_DOMAINS = {
    "centcom.mil", "war.gov", "defense.gov", "whitehouse.gov", "ukmto.org",
    "maritime.dot.gov", "iaea.org", "imo.org", "un.org", "state.gov",
}
WIRE_SOURCES = {
    "associated press", "ap news", "reuters", "bbc", "bbc news", "axios",
    "financial times", "the washington post", "the new york times", "cnn",
}
WORD_ROOT_TERMS = {"retaliat", "disrupt", "threaten", "negotiat"}
IRAN_COUNTERATTACK_PATTERNS = (
    r"\biran(?:ian)?\s+(?:attack|attacks|attacked|strike|strikes|struck|hit|hits|retaliat[a-z]*|fires?|fired|launch[a-z]*|targets?|targeted)\b",
    r"\biran(?:ian)?\s+(?:missile|missiles|drone|drones)\b.*\b(?:hit|hits|strike|strikes|attack|attacks|kill[a-z]*|damag[a-z]*)\b",
    r"\b(?:attack|strike|missile|drone)s?\b.*\b(?:by|from)\s+iran\b",
    r"\b(?:hit|killed|damaged|attacked|struck)\b.*\b(?:by|from)\s+iran\b",
    r"\btehran\s+(?:returns? fire|retaliat[a-z]*|attacks?|strikes?|hits?|launch[a-z]*)\b",
    r"\birgc\s+(?:attacks?|strikes?|hits?|retaliat[a-z]*|launch[a-z]*)\b",
)
CONSEQUENCE_TERMS = {
    "killed", "dead", "wounded", "injured", "damaged", "destroyed", "fire",
    "outage", "offline", "disrupted", "hit", "struck", "sank", "seized",
}
MARITIME_PRESSURE_TERMS = {
    "tanker", "ship", "shipping", "vessel", "hormuz", "strait", "port",
    "blockade", "transit", "navigation", "red sea", "suez", "bab el-mandeb",
}
DIPLOMACY_TERMS = {
    "talks", "ceasefire", "agreement", "negotiation", "deal", "mediator",
    "diplomacy", "truce",
}
WEAKNESS_TERMS = {
    "degraded", "destroyed", "unable", "limited", "intercepted", "depleted",
    "exhausted", "weakened", "isolated",
}
ISRAEL_TERMS = ("israel", "israeli", "idf", "netanyahu", "israel katz")
IRAN_TERMS = ("iran", "iranian", "tehran", "irgc")
ISRAEL_CONDITIONAL_TERMS = (
    "if iran", "if tehran", "if attacked", "if it attacks", "retaliat", "respond",
    "response", "warns", "warning", "hit back", "will act",
)
ISRAEL_ACTIVE_TERMS = (
    "israel strikes iran", "israel attacks iran", "israeli strike on iran",
    "israeli strikes on iran", "attacks iran", "bombed iran", "preemptive strike",
    "launched strikes on iran", "launches strikes on iran", "launching strikes on iran",
    "israel struck iran", "israeli attack on iran",
)
SECOND_CHOKEPOINT_GEO_TERMS = ("red sea", "suez", "bab el-mandeb", "bab al-mandab")
HOUTHI_TERMS = ("houthi", "houthis")
HOUTHI_OPERATIONAL_TERMS = (
    "attack", "strike", "launch", "deploy", "close", "blockade", "seized",
    "damaged", "hit ship", "targeted ship", "drone boat", "unmanned boat",
)
ASYMMETRIC_TERMS = (
    "ukraine", "asymmetric", "mobile launcher", "mobile tactics", "dispersed",
    "swarm", "unmanned boat", "drone boat", "innovation", "hit-and-run",
)
RELEVANCE_TERMS = (
    "iran", "iranian", "tehran", "irgc", "hormuz", "persian gulf", "israel",
    "israeli", "idf", "houthi", "houthis", "red sea", "suez", "bab el-mandeb",
)

MARKETS = {
    "brent": {"ticker": "BZ=F", "label": "Brent原油", "unit": "美元/桶"},
    "sp500": {"ticker": "^GSPC", "label": "S&P 500", "unit": "點"},
    "taiex": {"ticker": "^TWII", "label": "台股加權", "unit": "點"},
    "vix": {"ticker": "^VIX", "label": "VIX", "unit": ""},
    "gold": {"ticker": "GC=F", "label": "黃金", "unit": "美元/盎司"},
}


def utc_iso(dt: datetime | None = None) -> str:
    return (dt or NOW).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_bytes(url: str, timeout: int = 25, attempts: int = 2) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # network behavior is external and intentionally soft-failing
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last_error))


def parse_date(value: str | None) -> datetime:
    if not value:
        return NOW
    value = value.strip()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass
    formats = (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y%m%dT%H%M%SZ",
        "%Y-%m-%dT%H:%M:%SZ",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc)
        except ValueError:
            continue
    return NOW


def clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title or "").strip()
    return title[:300]


def normalized_title(title: str) -> str:
    text = title.lower()
    text = re.sub(r"\s+-\s+[^-]{2,60}$", "", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff ]+", " ", text)
    stop = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "with", "as", "at", "after"}
    return " ".join(word for word in text.split() if word not in stop)[:220]


def hostname(url: str) -> str:
    host = urllib.parse.urlparse(url).hostname or ""
    return host.lower().removeprefix("www.")


def source_grade(source: str, url: str) -> str:
    host = hostname(url)
    source_l = source.lower().strip()
    if any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS):
        return "官方發布"
    if source_l in WIRE_SOURCES or any(name in source_l for name in WIRE_SOURCES):
        return "大型媒體"
    return "單一來源"


def has_term(text: str, term: str) -> bool:
    """Match words/phrases without letting ship match leadership or hit match white."""
    if " " in term or "-" in term:
        return term in text
    suffix = r"[a-z]*" if term in WORD_ROOT_TERMS else r"(?:s|ed|ing)?"
    return re.search(rf"\b{re.escape(term)}{suffix}\b", text) is not None


def has_any_term(text: str, terms: Any) -> bool:
    return any(has_term(text, term) for term in terms)


def signals_iran_counterattack(text: str) -> bool:
    return any(re.search(pattern, text) is not None for pattern in IRAN_COUNTERATTACK_PATTERNS)


def flags_for_title(title: str) -> dict[str, bool]:
    text = title.lower()
    israel_posture = any(term in text for term in ISRAEL_TERMS) and any(term in text for term in IRAN_TERMS)
    second_chokepoint = any(term in text for term in SECOND_CHOKEPOINT_GEO_TERMS) or (
        any(term in text for term in HOUTHI_TERMS)
        and has_any_term(text, MARITIME_PRESSURE_TERMS)
    )
    return {
        "reported_consequence": has_any_term(text, CONSEQUENCE_TERMS),
        "maritime_pressure": has_any_term(text, MARITIME_PRESSURE_TERMS),
        "diplomacy": has_any_term(text, DIPLOMACY_TERMS),
        "weakness_signal": has_any_term(text, WEAKNESS_TERMS),
        "resilience_signal": signals_iran_counterattack(text),
        "israel_posture": israel_posture,
        "israel_conditional_response": israel_posture and any(term in text for term in ISRAEL_CONDITIONAL_TERMS),
        "israel_active_entry": israel_posture and any(term in text for term in ISRAEL_ACTIVE_TERMS),
        "second_chokepoint": second_chokepoint,
        "houthi_operational": second_chokepoint and has_any_term(text, HOUTHI_OPERATIONAL_TERMS),
        "asymmetric_adaptation": any(term in text for term in ASYMMETRIC_TERMS),
    }


def classify_category(title: str, fallback: str = "軍事行動") -> str:
    text = title.lower()
    if any(x in text for x in SECOND_CHOKEPOINT_GEO_TERMS) or (
        any(x in text for x in HOUTHI_TERMS)
        and has_any_term(text, MARITIME_PRESSURE_TERMS)
    ):
        return "紅海與蘇伊士"
    if any(x in text for x in ISRAEL_TERMS) and any(x in text for x in IRAN_TERMS):
        return "以色列動向"
    if any(x in text for x in ASYMMETRIC_TERMS):
        return "非對稱戰術"
    if has_any_term(text, ("hormuz", "tanker", "ship", "shipping", "vessel", "strait", "port", "navigation")):
        return "海峽與商船"
    if has_any_term(text, ("nuclear", "uranium", "iaea", "enrichment")):
        return "核問題"
    if has_any_term(text, ("talk", "ceasefire", "deal", "negotiat", "agreement", "diplomacy", "truce")):
        return "外交與停火"
    if has_any_term(text, ("power plant", "desalination", "bridge", "infrastructure", "refinery", "terminal")):
        return "基礎設施"
    return fallback


def google_news_items(category: str, query: str) -> list[dict[str, Any]]:
    q = f"{query} when:7d"
    params = urllib.parse.urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    url = f"https://news.google.com/rss/search?{params}"
    raw = fetch_bytes(url)
    root = ET.fromstring(raw)
    items: list[dict[str, Any]] = []
    for node in root.findall("./channel/item")[:80]:
        title = clean_title(node.findtext("title") or "")
        link = (node.findtext("link") or "").strip()
        source_node = node.find("source")
        source = clean_title(source_node.text if source_node is not None and source_node.text else "Google News")
        source_url = source_node.attrib.get("url", link) if source_node is not None else link
        published = parse_date(node.findtext("pubDate"))
        if not title or not link or not any(term in title.lower() for term in RELEVANCE_TERMS):
            continue
        items.append({
            "title": title,
            "url": link,
            "source_url": source_url,
            "source": source,
            "published_at": utc_iso(published),
            "category": classify_category(title, category),
            "collector": "Google News RSS",
            "source_grade": source_grade(source, source_url),
            "flags": flags_for_title(title),
        })
    return items


def gdelt_items() -> list[dict[str, Any]]:
    query = '(Iran OR Iranian OR Houthi OR Israel) (Hormuz OR missile OR drone OR ceasefire OR nuclear OR "Red Sea" OR Suez)'
    params = urllib.parse.urlencode({
        "query": query,
        "mode": "artlist",
        "maxrecords": 100,
        "format": "json",
        "timespan": "3d",
        "sort": "datedesc",
    })
    raw = fetch_bytes(f"https://api.gdeltproject.org/api/v2/doc/doc?{params}")
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    result: list[dict[str, Any]] = []
    for article in payload.get("articles", []):
        title = clean_title(article.get("title", ""))
        url = article.get("url", "")
        if not title or not url:
            continue
        domain = article.get("domain") or hostname(url)
        category = classify_category(title)
        result.append({
            "title": title,
            "url": url,
            "source_url": url,
            "source": domain,
            "published_at": utc_iso(parse_date(article.get("seendate"))),
            "category": category,
            "collector": "GDELT DOC 2.0",
            "source_grade": source_grade(domain, url),
            "flags": flags_for_title(title),
        })
    return result


def deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = sorted(items, key=lambda x: x["published_at"], reverse=True)
    clusters: list[dict[str, Any]] = []
    for item in items:
        norm = normalized_title(item["title"])
        matched: dict[str, Any] | None = None
        item_dt = parse_date(item["published_at"].replace("Z", "+0000"))
        for cluster in clusters:
            cluster_dt = parse_date(cluster["published_at"].replace("Z", "+0000"))
            if abs((item_dt - cluster_dt).total_seconds()) > 36 * 3600:
                continue
            if SequenceMatcher(None, norm, cluster["normalized_title"]).ratio() >= 0.72:
                matched = cluster
                break
        if matched is None:
            cluster = dict(item)
            cluster["normalized_title"] = norm
            cluster["sources"] = [{
                "name": item["source"], "url": item["url"], "grade": item["source_grade"],
            }]
            clusters.append(cluster)
        else:
            existing = {(s["name"].lower(), s["url"]) for s in matched["sources"]}
            key = (item["source"].lower(), item["url"])
            if key not in existing:
                matched["sources"].append({
                    "name": item["source"], "url": item["url"], "grade": item["source_grade"],
                })
            for flag, value in item["flags"].items():
                matched["flags"][flag] = matched["flags"][flag] or value

    for cluster in clusters:
        grades = {source["grade"] for source in cluster["sources"]}
        unique_names = {source["name"].lower() for source in cluster["sources"]}
        if "官方發布" in grades:
            cluster["confidence"] = "官方發布"
        elif len(unique_names) >= 2 and "大型媒體" in grades:
            cluster["confidence"] = "多方報導"
        else:
            cluster["confidence"] = "單一來源"
        cluster["source_count"] = len(unique_names)
        cluster.pop("normalized_title", None)
        cluster.pop("source_grade", None)
        cluster.pop("source_url", None)
    return clusters[:300]


def fetch_market(key: str, config: dict[str, str]) -> dict[str, Any]:
    ticker = urllib.parse.quote(config["ticker"], safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1mo&interval=1d"
    payload = json.loads(fetch_bytes(url).decode("utf-8", errors="replace"))
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close") or []
    rows = [(ts, close) for ts, close in zip(timestamps, closes) if close is not None]
    if not rows:
        raise RuntimeError("no market observations")
    last_ts, last = rows[-1]
    previous = rows[-2][1] if len(rows) > 1 else last
    five_day = rows[-6][1] if len(rows) > 5 else rows[0][1]
    history = [
        {"date": datetime.fromtimestamp(ts, timezone.utc).date().isoformat(), "value": round(float(value), 4)}
        for ts, value in rows[-20:]
    ]
    return {
        "key": key,
        "ticker": config["ticker"],
        "label": config["label"],
        "unit": config["unit"],
        "value": round(float(last), 4),
        "day_change_pct": round((float(last) / float(previous) - 1) * 100, 2) if previous else None,
        "five_day_change_pct": round((float(last) / float(five_day) - 1) * 100, 2) if five_day else None,
        "as_of": datetime.fromtimestamp(last_ts, timezone.utc).date().isoformat(),
        "history": history,
        "source": "Yahoo Finance public chart endpoint",
    }


def window_stats(items: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    selected = [
        item for item in items
        if start <= parse_date(item["published_at"].replace("Z", "+0000")) < end
    ]
    categories = Counter(item["category"] for item in selected)
    confidence = Counter(item["confidence"] for item in selected)
    flags: Counter[str] = Counter()
    for item in selected:
        for flag, value in item["flags"].items():
            if value:
                flags[flag] += 1
        if item["flags"]["resilience_signal"] and item["flags"]["reported_consequence"]:
            flags["consequential_resilience_signal"] += 1
            if any(source.get("grade") in ("官方發布", "大型媒體") for source in item.get("sources", [])):
                flags["quality_resilience_signal"] += 1
        if item["flags"]["resilience_signal"] and (
            item["flags"]["maritime_pressure"] or item["flags"]["diplomacy"]
        ):
            flags["stalemate_signal"] += 1
    return {
        "items": len(selected),
        "categories": dict(categories),
        "official": confidence["官方發布"],
        "multi_source": confidence["多方報導"],
        "reported_consequence": flags["reported_consequence"],
        "maritime_pressure": flags["maritime_pressure"],
        "diplomacy": flags["diplomacy"],
        "weakness_signal": flags["weakness_signal"],
        "resilience_signal": flags["consequential_resilience_signal"],
        "quality_resilience_signal": flags["quality_resilience_signal"],
        "stalemate_signal": flags["stalemate_signal"],
        "israel_posture": flags["israel_posture"],
        "israel_conditional_response": flags["israel_conditional_response"],
        "israel_active_entry": flags["israel_active_entry"],
        "second_chokepoint": flags["second_chokepoint"],
        "houthi_operational": flags["houthi_operational"],
        "asymmetric_adaptation": flags["asymmetric_adaptation"],
    }


def percent_change(current: int, previous: int) -> float | None:
    if previous == 0:
        return None
    return round((current / previous - 1) * 100, 1)


def build_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    current_24h = window_stats(items, NOW - timedelta(hours=24), NOW + timedelta(seconds=1))
    previous_24h = window_stats(items, NOW - timedelta(hours=48), NOW - timedelta(hours=24))
    recent_72h = window_stats(items, NOW - timedelta(hours=72), NOW + timedelta(seconds=1))
    daily: dict[str, Counter[str]] = defaultdict(Counter)
    for item in items:
        dt = parse_date(item["published_at"].replace("Z", "+0000"))
        if dt >= NOW - timedelta(days=7):
            daily[dt.date().isoformat()][item["category"]] += 1

    weakness = recent_72h["weakness_signal"]
    resilience = recent_72h["resilience_signal"]
    maritime = recent_72h["maritime_pressure"]
    diplomacy = recent_72h["diplomacy"]
    if recent_72h["items"] and weakness >= 3 and resilience >= 3 and maritime >= 3:
        posture = "中間僵局訊號最需要警戒"
        posture_note = "公開資訊同時出現能力受損與持續反擊，尚未形成單向結論。"
    elif recent_72h["items"] and resilience >= 5 and weakness < 3:
        posture = "持續反擊的公開訊號較強"
        posture_note = "有後果的反擊報導仍多；這只能證明壓制尚未完成，不能推算庫存。"
    elif recent_72h["items"] and weakness >= 3 and resilience < 3:
        posture = "能力衰退訊號暫時較多"
        posture_note = "媒體標題中的受損與降級訊號較多，仍需用實際損害與航運改善驗證。"
    elif recent_72h["items"]:
        posture = "實力揭露測試進行中"
        posture_note = "目前公開證據尚未跨過方向性門檻。"
    else:
        posture = "公開證據不足以判定"
        posture_note = "目前自動來源無法支持方向性結論。"

    days = []
    for offset in range(6, -1, -1):
        day = (NOW - timedelta(days=offset)).date().isoformat()
        days.append({"date": day, "categories": dict(daily.get(day, {}))})
    return {
        "evidence_items_24h": current_24h["items"],
        "evidence_items_prev_24h": previous_24h["items"],
        "evidence_change_24h_pct": percent_change(current_24h["items"], previous_24h["items"]),
        "official_24h": current_24h["official"],
        "multi_source_24h": current_24h["multi_source"],
        "reported_consequence_24h": current_24h["reported_consequence"],
        "reported_consequence_prev_24h": previous_24h["reported_consequence"],
        "maritime_pressure_24h": current_24h["maritime_pressure"],
        "maritime_pressure_prev_24h": previous_24h["maritime_pressure"],
        "diplomacy_24h": current_24h["diplomacy"],
        "diplomacy_prev_24h": previous_24h["diplomacy"],
        "weakness_signal_24h": current_24h["weakness_signal"],
        "weakness_signal_prev_24h": previous_24h["weakness_signal"],
        "resilience_signal_24h": current_24h["resilience_signal"],
        "resilience_signal_prev_24h": previous_24h["resilience_signal"],
        "quality_resilience_signal_24h": current_24h["quality_resilience_signal"],
        "quality_resilience_signal_prev_24h": previous_24h["quality_resilience_signal"],
        "stalemate_signal_24h": current_24h["stalemate_signal"],
        "stalemate_signal_prev_24h": previous_24h["stalemate_signal"],
        "israel_posture_24h": current_24h["israel_posture"],
        "israel_conditional_response_24h": current_24h["israel_conditional_response"],
        "israel_active_entry_24h": current_24h["israel_active_entry"],
        "second_chokepoint_24h": current_24h["second_chokepoint"],
        "houthi_operational_24h": current_24h["houthi_operational"],
        "asymmetric_adaptation_24h": current_24h["asymmetric_adaptation"],
        "category_counts_24h": current_24h["categories"],
        "category_counts_prev_24h": previous_24h["categories"],
        "evidence_items_72h": recent_72h["items"],
        "multi_source_72h": recent_72h["multi_source"],
        "official_72h": recent_72h["official"],
        "reported_consequence_72h": recent_72h["reported_consequence"],
        "maritime_pressure_72h": maritime,
        "diplomacy_72h": diplomacy,
        "weakness_signal_72h": weakness,
        "resilience_signal_72h": resilience,
        "quality_resilience_signal_72h": recent_72h["quality_resilience_signal"],
        "stalemate_signal_72h": recent_72h["stalemate_signal"],
        "israel_posture_72h": recent_72h["israel_posture"],
        "israel_conditional_response_72h": recent_72h["israel_conditional_response"],
        "israel_active_entry_72h": recent_72h["israel_active_entry"],
        "second_chokepoint_72h": recent_72h["second_chokepoint"],
        "houthi_operational_72h": recent_72h["houthi_operational"],
        "asymmetric_adaptation_72h": recent_72h["asymmetric_adaptation"],
        "category_counts_72h": recent_72h["categories"],
        "daily_counts_7d": days,
        "posture": posture,
        "posture_note": posture_note,
    }


def signed_pct(value: float | None) -> str:
    if value is None:
        return "無法比較"
    return f"{value:+.1f}%"


def market_value(markets: dict[str, Any], key: str, field: str = "day_change_pct") -> float | None:
    value = markets.get(key, {}).get(field)
    return float(value) if isinstance(value, (int, float)) else None


def build_daily_analysis_legacy(
    metrics: dict[str, Any], markets: dict[str, Any], fetch_status: list[dict[str, Any]]
) -> dict[str, Any]:
    current = metrics["evidence_items_24h"]
    previous = metrics["evidence_items_prev_24h"]
    consequences = metrics["reported_consequence_24h"]
    resilience = metrics["resilience_signal_24h"]
    weakness = metrics["weakness_signal_24h"]
    maritime = metrics["maritime_pressure_24h"]
    diplomacy = metrics["diplomacy_24h"]
    stalemate = metrics["stalemate_signal_24h"]
    israel_posture = metrics["israel_posture_24h"]
    israel_conditional = metrics["israel_conditional_response_24h"]
    israel_active = metrics["israel_active_entry_24h"]
    second_chokepoint = metrics["second_chokepoint_24h"]
    houthi_operational = metrics["houthi_operational_24h"]
    asymmetric = metrics["asymmetric_adaptation_24h"]
    higher_confidence = metrics["official_24h"] + metrics["multi_source_24h"]
    top_category = max(
        metrics["category_counts_24h"].items(), key=lambda pair: pair[1], default=("無", 0)
    )

    if weakness >= 3 and resilience >= 3:
        leading_id = "middle_stalemate"
        leading_name = "中間僵局"
        headline = "今日判讀：雙方都還能施加成本，戰爭終點沒有因此變近"
        bottom_line = (
            "公開證據同時出現能力受損與有後果的反擊，表示擴大戰事正在揭露實力，"
            "但尚未把結果推向任何一方可以收手的條件。拖長與反覆升級是目前最需要防範的路徑。"
        )
    elif resilience >= 5 and weakness < 3:
        leading_id = "iran_resilient"
        leading_name = "伊朗韌性高於預期"
        headline = "今日判讀：擴大打擊仍未壓低有效反擊，快速終局訊號不足"
        bottom_line = (
            "近24小時仍有多組造成後果的反擊報導，而能力明顯衰退的公開訊號偏少。"
            "這不代表伊朗能取勝，但表示美方尚未證明只靠擴大打擊就能快速換來停火與安全通航。"
        )
    elif weakness >= 3 and resilience < 3:
        leading_id = "iran_weaker"
        leading_name = "伊朗實力低於預期"
        headline = "今日判讀：反擊與實際損害轉弱，戰事開始出現收斂可能"
        bottom_line = (
            "能力衰退訊號多於有後果的反擊。如果這個差距能跨日延續，並伴隨商船風險下降，"
            "才可能表示擴大打擊正在逼近可談判的終局。"
        )
    elif maritime >= 5 and diplomacy >= 3:
        leading_id = "middle_stalemate"
        leading_name = "中間僵局"
        headline = "今日判讀：談判消息增加，但海峽壓力尚未解除"
        bottom_line = (
            "外交活動與海上壓力同時存在，代表雙方仍在談判與軍事槓桿之間來回。"
            "在商船安全沒有可驗證改善前，談判訊號還不能視為終局。"
        )
    else:
        leading_id = "undetermined"
        leading_name = "尚無明顯領先情境"
        headline = "今日判讀：實力測試仍在進行，公開證據尚未形成方向"
        bottom_line = (
            "目前訊號不足以證明伊朗能力迅速耗盡，也不足以證明其能長期承受擴大打擊。"
            "需要等待跨日反擊、實際損害與海峽通航是否同步改變。"
        )

    if israel_active or houthi_operational:
        leading_id = "middle_stalemate"
        leading_name = "區域擴散下的中間僵局"
        headline = "今日判讀：第二戰線風險升高，戰事更可能先擴散再尋找終點"
        bottom_line += (
            " 以色列實際介入或胡塞 operational 線索，會把單一戰場變成區域多點施壓；"
            "這可能加速實力揭露，也同時提高誤判、拖長與再升級的成本。"
        ).replace("operational", "行動")

    activity_delta = current - previous
    if previous:
        activity_text = (
            f"近24小時有{current}組去重公開證據，前24小時為{previous}組，"
            f"變化{signed_pct(metrics['evidence_change_24h_pct'])}；最多的是{top_category[0]}（{top_category[1]}組）。"
        )
    else:
        activity_text = f"近24小時有{current}組去重公開證據；最多的是{top_category[0]}（{top_category[1]}組）。"

    if resilience >= 5 and weakness < 3:
        battlefield_text = (
            f"有後果的反擊線索{resilience}組，能力衰退線索{weakness}組。"
            "目前較合理的解讀是壓制尚未完成，而不是伊朗已經沒有還擊能力。"
        )
    elif weakness >= 3 and resilience < 3:
        battlefield_text = (
            f"能力衰退線索{weakness}組，高於有後果的反擊線索{resilience}組。"
            "若連續數日維持，才足以支持伊朗實力低於預期。"
        )
    elif weakness >= 3 and resilience >= 3:
        battlefield_text = (
            f"能力衰退線索{weakness}組、有後果的反擊線索{resilience}組同時存在。"
            "這是典型僵局：打擊有效，但還不足以阻止對手繼續造成成本。"
        )
    else:
        battlefield_text = (
            f"有後果的反擊線索{resilience}組、能力衰退線索{weakness}組；"
            "數量仍不足以支持方向性戰力判斷。"
        )

    if maritime >= 5 and diplomacy >= 3:
        diplomacy_text = (
            f"海峽壓力線索{maritime}組、外交線索{diplomacy}組。談判活動雖存在，"
            "但通航風險仍高，表示協議的執行力尚未通過驗證。"
        )
    elif maritime >= 5:
        diplomacy_text = (
            f"海峽壓力線索{maritime}組，外交線索只有{diplomacy}組。"
            "只要商船安全沒有改善，美方就缺乏低成本收手條件。"
        )
    elif diplomacy >= 3:
        diplomacy_text = (
            f"外交線索{diplomacy}組，海峽壓力線索{maritime}組。"
            "退出窗口正在形成，但仍需連續通航與可約束武裝單位的安排確認。"
        )
    else:
        diplomacy_text = "外交與海峽訊號都不足，今天不能判定談判是否更接近可執行結果。"

    if israel_active:
        israel_text = (
            f"近24小時出現{israel_active}組以色列實際或主動介入線索。"
            "這已跨過口頭嚇阻門檻，會擴大打擊目標與伊朗報復面，區域升級風險明顯上升。"
        )
        israel_title = "以色列已出現介入線索"
    elif israel_conditional:
        israel_text = (
            f"近24小時有{israel_conditional}組條件式報復訊號。這代表『若伊朗攻擊就反擊』的預先承諾，"
            "不是以色列已主動參戰；但單次伊朗攻擊可能因此成為區域擴大的觸發器。"
        )
        israel_title = "目前仍是條件式嚇阻"
    elif israel_posture:
        israel_text = (
            f"近24小時有{israel_posture}組以色列—伊朗動向線索，但未辨識出明確主動介入或條件式報復。"
            "需等待戰備調整、兵力部署或實際打擊等更強證據。"
        )
        israel_title = "以色列動向需繼續確認"
    else:
        israel_text = "近24小時自動來源未抓到明確以色列介入訊號；這只代表公開標題證據不足，不代表以色列沒有準備。"
        israel_title = "尚無足夠以色列介入證據"

    if houthi_operational:
        red_sea_text = (
            f"近24小時有{houthi_operational}組胡塞行動線索，第二航運咽喉風險已從口頭訊號走向操作層。"
            "真正要驗證的是曼德海峽／紅海遇襲、船舶繞航、保費與蘇伊士通行量，而非把警告直接等同於封鎖。"
        )
        red_sea_title = "第二航運咽喉風險升高"
    elif second_chokepoint:
        red_sea_text = (
            f"近24小時有{second_chokepoint}組紅海—蘇伊士風險訊號，目前仍以警告與施壓訊號為主。"
            "實際咽喉是曼德海峽與紅海入口；在那裡干擾航運，才會壓縮進出蘇伊士的流量。"
        )
        red_sea_title = "第二航運咽喉仍在訊號階段"
    else:
        red_sea_text = "近24小時沒有足夠的胡塞／紅海行動證據，暫不能判定伊朗已成功開啟第二航運戰線。"
        red_sea_title = "第二航運戰線尚未確認"

    if asymmetric:
        asymmetric_text = (
            f"近24小時有{asymmetric}組分散式、機動或無人系統適應線索。"
            "空襲可以摧毀固定設施，但若機動發射器、無人機艇與代理人仍能分散行動，壓低還擊成本會比預期更慢。"
        )
        asymmetric_title = "非對稱適應提高壓制難度"
    else:
        asymmetric_text = (
            "近24小時未抓到足夠的非對稱戰術適應線索；仍需追蹤機動發射、無人機／無人艇、分散部署與代理人協同。"
        )
        asymmetric_title = "非對稱適應尚待更多證據"

    brent = market_value(markets, "brent")
    vix = market_value(markets, "vix")
    taiex = market_value(markets, "taiex")
    sp500 = market_value(markets, "sp500")
    market_date = markets.get("brent", {}).get("as_of") or markets.get("sp500", {}).get("as_of") or "最近交易日"
    if brent is not None and vix is not None and (brent >= 2 or vix >= 7):
        market_text = (
            f"截至{market_date}，Brent單日{signed_pct(brent)}、VIX {signed_pct(vix)}、"
            f"S&P 500 {signed_pct(sp500)}、台股{signed_pct(taiex)}。"
            "市場正在提高能源與風險溢價，短線仍把戰事擴大視為負面，而不是接近和平的利多。"
        )
        market_stance = "風險重新定價升高"
    elif brent is not None and vix is not None and brent <= -1 and vix <= 0:
        market_text = (
            f"截至{market_date}，Brent單日{signed_pct(brent)}、VIX {signed_pct(vix)}。"
            "市場未確認進一步升級；仍需觀察這是短暫降溫，還是通航風險真正改善。"
        )
        market_stance = "市場未確認升級"
    else:
        market_text = (
            f"截至{market_date}，Brent單日{signed_pct(brent)}、VIX {signed_pct(vix)}、"
            f"S&P 500 {signed_pct(sp500)}。市場訊號混合，尚不能單靠價格判定戰事方向。"
        )
        market_stance = "市場訊號混合"

    failures = [row["source"] for row in fetch_status if not row.get("ok")]
    confidence = "中等" if higher_confidence >= 5 and len(failures) <= 1 else "偏低"
    confidence_note = (
        f"近24小時官方或多方報導{higher_confidence}組；"
        + (f"未成功來源：{'、'.join(failures)}。" if failures else "主要自動來源均成功。")
        + "結論是方向性判讀，不是戰力或機率估算。"
    )

    scenario_updates = {
        "iran_weaker": "今日較受支持" if leading_id == "iran_weaker" else "今日未獲主要支持",
        "iran_resilient": "今日較受支持" if leading_id == "iran_resilient" else "持續觀察",
        "middle_stalemate": "區域擴散風險上升" if israel_active or houthi_operational else ("今日較受支持" if leading_id == "middle_stalemate" else ("風險仍高" if stalemate >= 3 else "持續觀察")),
    }
    return {
        "headline": headline,
        "bottom_line": bottom_line,
        "leading_scenario_id": leading_id,
        "leading_scenario": leading_name,
        "confidence": confidence,
        "confidence_note": confidence_note,
        "activity": {"title": "今天發生什麼變化", "assessment": activity_text, "delta": activity_delta},
        "battlefield": {"title": "對戰場的意義", "assessment": battlefield_text},
        "diplomacy": {"title": "對和談與海峽的意義", "assessment": diplomacy_text},
        "israel": {"title": israel_title, "assessment": israel_text},
        "red_sea": {"title": red_sea_title, "assessment": red_sea_text},
        "asymmetric": {"title": asymmetric_title, "assessment": asymmetric_text},
        "market": {"title": "對投資市場的意義", "assessment": market_text, "stance": market_stance},
        "scenario_updates": scenario_updates,
        "watch_next": [
            "有後果的反擊是否連續兩至三日下降，而非只停一天",
            "商船遇襲與海峽干擾是否出現可驗證改善",
            "外交安排是否能約束主要武裝單位並實際執行",
            "以色列是否從條件式報復轉為戰備部署、實際還擊或主動打擊",
            "胡塞是否部署或攻擊船舶，以及紅海繞航、保費與蘇伊士通行量是否惡化",
            "伊朗及代理人的機動發射、無人機／無人艇與分散部署是否持續造成後果",
            "Brent、VIX與區域股市是否共同回落，確認風險溢價下降",
        ],
    }


def build_daily_analysis(
    metrics: dict[str, Any], markets: dict[str, Any], fetch_status: list[dict[str, Any]]
) -> dict[str, Any]:
    """Translate public evidence into the escalation-to-endgame thesis.

    Headline counts are supporting evidence only. The state machine separates
    continued damage, persistence, opponent learning and an executable exit;
    it never treats those as the same proposition.
    """
    current = metrics["evidence_items_24h"]
    previous = metrics["evidence_items_prev_24h"]
    consequences = metrics["reported_consequence_24h"]
    resilience = metrics["resilience_signal_24h"]
    resilience_prev = metrics["resilience_signal_prev_24h"]
    quality_resilience = metrics["quality_resilience_signal_24h"]
    quality_resilience_prev = metrics["quality_resilience_signal_prev_24h"]
    weakness = metrics["weakness_signal_24h"]
    weakness_prev = metrics["weakness_signal_prev_24h"]
    maritime = metrics["maritime_pressure_24h"]
    maritime_prev = metrics["maritime_pressure_prev_24h"]
    diplomacy = metrics["diplomacy_24h"]
    diplomacy_prev = metrics["diplomacy_prev_24h"]
    israel_posture = metrics["israel_posture_24h"]
    israel_conditional = metrics["israel_conditional_response_24h"]
    israel_active = metrics["israel_active_entry_24h"]
    second_chokepoint = metrics["second_chokepoint_24h"]
    houthi_operational = metrics["houthi_operational_24h"]
    asymmetric = metrics["asymmetric_adaptation_24h"]
    higher_confidence = metrics["official_24h"] + metrics["multi_source_24h"]
    top_category = max(
        metrics["category_counts_24h"].items(), key=lambda pair: pair[1], default=("無", 0)
    )

    retaliation_persistent = (
        resilience >= 3 and resilience_prev >= 2
        and quality_resilience >= 1 and quality_resilience_prev >= 1
    )
    retaliation_reappeared = resilience >= 5 and resilience_prev < 3
    retaliation_fading = resilience_prev >= 5 and resilience <= max(2, round(resilience_prev * 0.5))
    weakness_dominant = weakness >= 3 and weakness > resilience
    damage_and_degradation = weakness >= 3 and resilience >= 3
    maritime_improving = maritime_prev >= 3 and maritime <= max(1, round(maritime_prev * 0.6))
    regional_active = israel_active > 0 or houthi_operational > 0
    regional_warning = israel_conditional > 0 or second_chokepoint > 0
    exit_window = diplomacy >= 3 and maritime_improving and maritime <= 4 and not regional_active

    if regional_active:
        leading_id = "middle_stalemate"
        leading_name = "區域化的中間僵局"
        test_phase = "實力揭露測試｜區域化階段"
        thesis_state = "揭露速度加快，但終局成本同步上升"
        headline = "第二戰線正在打開：實力揭露加速，終局代價也同步上升"
        bottom_line = (
            "已知的是戰事不再只測試伊朗本土能力：以色列實際介入或胡塞行動會把代理人、航運與盟友承受力一起帶入測試。"
            "這可能更快暴露伊朗底牌，也可能讓任何單一方都無法控制升級。今天較接近的不是快速終局，而是多戰線中間僵局。"
        )
    elif weakness_dominant and retaliation_fading and maritime_improving:
        leading_id = "iran_weaker"
        leading_name = "A路徑：伊朗底牌有限"
        test_phase = "實力揭露測試｜衰退確認階段"
        thesis_state = "A路徑正在形成，但仍要驗證可執行停火"
        headline = "能力揭露開始指向衰退；通航改善將決定是否真的接近終局"
        bottom_line = (
            "有後果的反擊線索跨窗下降，能力衰退線索開始占上風，海上壓力也同步改善。"
            "這是我們推演中的A路徑：擴大打擊可能正在證明伊朗底牌有限。但只有形成能約束主要武裝單位的安排，軍事衰退才會轉化為終局。"
        )
    elif retaliation_persistent:
        leading_id = "iran_resilient" if exit_window else "middle_stalemate"
        leading_name = "B路徑前半段成立" if exit_window else "C路徑風險最高"
        test_phase = "實力揭露測試｜第二階段"
        thesis_state = "伊朗仍能造成成本；能否迫使美方修正目標尚未揭曉"
        headline = "擴大戰事得到初步答案：伊朗仍能造成損害；真正關鍵是能否持續"
        bottom_line = (
            "連續兩個24小時觀察窗都有造成後果的反擊線索，因此目前公開證據不支持『擴大打擊已使伊朗迅速失去還手能力』。"
            "但這仍只完成B路徑的前半段，尚未證明伊朗能長期維持多戰線壓力，也未證明美國已接受軍事手段的限制。"
            + (
                "海上壓力下降且外交活動增加，退出窗口開始出現，但協議執行力仍待驗證。"
                if exit_window else
                "在美方沒有縮小目標、海上安全沒有持續改善以前，更直接的結果仍是C路徑：雙方都認為再打一點可能更有利。"
            )
        )
    elif retaliation_reappeared:
        leading_id = "undetermined"
        leading_name = "實力仍在揭露"
        test_phase = "實力揭露測試｜第一階段"
        thesis_state = "已證明仍能反擊，尚未證明具備持續性"
        headline = "實力測試仍在第一階段：伊朗再次造成損害，但持續作戰能力尚未揭曉"
        bottom_line = (
            "今天的證據顯示伊朗仍能造成成本，因此不能宣告其還擊能力已被清除。"
            "但單一觀察窗無法區分剩餘庫存、偶發突破與可長期維持的作戰體系；戰事擴大仍在產生答案，還沒有產生終局。"
        )
    elif damage_and_degradation:
        leading_id = "middle_stalemate"
        leading_name = "C路徑：中間僵局"
        test_phase = "實力揭露測試｜相互消耗階段"
        thesis_state = "打擊有效，但不足以阻止對手繼續施加成本"
        headline = "戰事擴大正在揭露雙方極限，但目前指向最危險的中間僵局"
        bottom_line = (
            "能力受損與有後果的反擊同時存在，表示美方打擊有效、卻尚未取得決定性壓制。"
            "這會延長雙方繼續測試底牌的誘因；除非反擊、通航或政治目標出現跨日收斂，擴大本身不會自動帶來和平。"
        )
    else:
        leading_id = "undetermined"
        leading_name = "尚無路徑完成關鍵驗證"
        test_phase = "實力揭露測試｜答案不足"
        thesis_state = "新聞活動存在，但關鍵終局變數尚未收斂"
        headline = "今天沒有新的終局答案：戰事仍在測試底牌，三條路徑都未完成驗證"
        bottom_line = (
            "目前公開資訊不足以證明伊朗能力迅速耗盡，也不足以證明其能長期迫使美方讓步。"
            "這不是『沒有事情發生』，而是目前發生的事情還不能回答誰會先修正預期、以及協議能否被執行。"
        )

    if retaliation_persistent:
        revelation_text = (
            f"有後果的反擊線索近24小時為{resilience}組，前一個24小時為{resilience_prev}組。"
            f"其中本期{quality_resilience}組來自官方或大型媒體。這支持『壓制尚未完成』，"
            "但這些是去重新聞證據，不是獨立攻擊次數。"
        )
        revelation_title = "可暫時判定：壓制尚未完成"
    elif retaliation_fading:
        revelation_text = (
            f"有後果的反擊線索由{resilience_prev}組降至{resilience}組，能力衰退線索為{weakness}組。"
            "方向開始偏弱，但必須與通航改善及後續觀察窗共同確認。"
        )
        revelation_title = "初步答案：反擊能力可能轉弱"
    else:
        revelation_text = (
            f"本期有後果的反擊線索{resilience}組、能力衰退線索{weakness}組；"
            "尚不足以把偶發突破、剩餘庫存與可持續作戰能力分開。"
        )
        revelation_title = "尚未知道：伊朗的真實持續力"

    durability_text = (
        f"72小時共有{metrics['resilience_signal_72h']}組有後果反擊線索、"
        f"{metrics['weakness_signal_72h']}組能力衰退線索，非對稱適應線索{metrics['asymmetric_adaptation_72h']}組。"
        "這能觀察跨日存在性，不能反推出飛彈庫存、可用發射器、補給速度或統一指揮能力。"
    )

    if weakness_dominant or retaliation_fading:
        us_learning_text = (
            "若反擊下降與通航改善延續，美方會更有理由相信擴大打擊能改變伊朗的成本效益。"
            "但在政治指揮鏈仍破碎的情況下，軍事優勢也未必自動換成可執行協議。"
        )
    elif retaliation_persistent:
        us_learning_text = (
            "連續反擊會削弱『空襲可快速清除威脅』的預期；真正的認知轉折要看美方是否縮小目標、承認邊際收益下降，或重新重視談判。"
            "目前只能說美方正在得到壓制尚未完成的訊息，不能說美方已接受這個結論。"
        )
    else:
        us_learning_text = "目前證據還不足以迫使美方在『繼續擴大』與『接受限制』之間做出清楚修正。"

    if leading_id == "iran_weaker":
        endpoint_text = "較接近A路徑，但軍事衰退仍需轉化成統一、可監督的停火承諾。"
    elif leading_id == "iran_resilient":
        endpoint_text = "B路徑開始出現：伊朗持續施壓，加上海上改善與外交活動，可能迫使美方重新定義可接受結果。"
    elif leading_id == "middle_stalemate":
        endpoint_text = "C路徑風險最高：伊朗受創卻仍能施加成本，美方也還沒看到必須收手的證據。"
    else:
        endpoint_text = "三條路徑都缺少最後一塊證據；今天應維持假說競爭，而不是宣布勝負。"

    if exit_window:
        negotiability_text = (
            f"外交線索{diplomacy}組，海上壓力由{maritime_prev}組降至{maritime}組，退出窗口開始形成。"
            "但仍缺少誰能代表伊朗、如何約束革命衛隊與代理人、違約如何驗證的答案。"
        )
    elif diplomacy >= 3:
        negotiability_text = (
            f"外交線索{diplomacy}組，但海上壓力仍有{maritime}組。這代表存在接觸，不代表存在可執行協議；"
            "談判價值取決於能否約束真正執行攻擊的指揮鏈。"
        )
    else:
        negotiability_text = (
            f"外交線索僅{diplomacy}組，尚未形成可信退出窗口。只要核風險、海峽通航與武裝指揮鏈無法被同時約束，"
            "美方就缺少低成本收手條件。"
        )

    escalation_text = (
        "擴大戰事的終局功能不是『打得更多就會和平』，而是迫使雙方用真實成本回答原先無法從談判桌得到的問題。"
        "若答案是伊朗底牌有限，A路徑上升；若答案是伊朗能長期施壓，B路徑上升；若答案長期模糊，C路徑反而被強化。"
    )

    activity_text = (
        f"近24小時有{current}組去重公開證據，前期{previous}組，變化{signed_pct(metrics['evidence_change_24h_pct'])}；"
        f"最多的是{top_category[0]}（{top_category[1]}組）。這只衡量資訊活動，不直接衡量戰力。"
    )

    if israel_active:
        israel_title = "以色列已跨過口頭嚇阻門檻"
        israel_text = (
            f"出現{israel_active}組實際或主動介入線索。這會擴大伊朗報復面，也讓實力測試更快區域化；"
            "終局資訊增加，但失控與多戰線僵局風險也上升。"
        )
    elif israel_conditional:
        israel_title = "以色列仍是條件式觸發器"
        israel_text = (
            f"有{israel_conditional}組條件式報復訊號、實際介入為0組。這不是已參戰，"
            "但它把單次落入以色列的伊朗攻擊，變成可能開啟第二戰線的明確觸發條件。"
        )
    elif israel_posture:
        israel_title = "以色列動向尚未跨過介入門檻"
        israel_text = f"有{israel_posture}組相關動向，但未辨識出明確主動介入；戰備與實際打擊必須分開。"
    else:
        israel_title = "尚無以色列介入證據"
        israel_text = "自動來源未抓到明確介入線索；這代表公開證據不足，不代表以色列沒有準備。"

    if houthi_operational:
        red_sea_title = "第二航運咽喉進入行動層"
        red_sea_text = (
            f"有{houthi_operational}組胡塞行動線索。若船舶遇襲、繞航、保費與蘇伊士通行量同步惡化，"
            "伊朗就能在本土受壓時把成本外溢到全球航運，強化B或C路徑。"
        )
    elif second_chokepoint:
        red_sea_title = "第二航運咽喉仍在訊號層"
        red_sea_text = (
            f"有{second_chokepoint}組紅海—蘇伊士風險訊號，但沒有胡塞實際行動線索。"
            "目前只能說第二咽喉被拿來施壓，不能說航道已被關閉。"
        )
    else:
        red_sea_title = "第二航運戰線尚未形成"
        red_sea_text = "沒有足夠胡塞／紅海行動證據；目前仍以霍爾木茲為主要航運壓力來源。"

    asymmetric_title = "非對稱能力決定空襲的邊際收益"
    asymmetric_text = (
        f"近24小時有{asymmetric}組、72小時有{metrics['asymmetric_adaptation_72h']}組機動／分散／無人系統適應線索。"
        "若固定設施被毀後仍能靠移動發射器、無人艇與代理人製造成本，空襲的邊際收益會下降；目前線索仍不足以量化這種韌性。"
    )

    brent = market_value(markets, "brent")
    vix = market_value(markets, "vix")
    taiex = market_value(markets, "taiex")
    sp500 = market_value(markets, "sp500")
    market_date = markets.get("brent", {}).get("as_of") or markets.get("sp500", {}).get("as_of") or "最近交易日"
    market_text = (
        f"截至{market_date}，Brent {signed_pct(brent)}、VIX {signed_pct(vix)}、"
        f"S&P 500 {signed_pct(sp500)}、台股{signed_pct(taiex)}。市場只顯示風險定價，"
        "不能判斷擴大最後會走向A、B或C；只有油價與波動率跨日回落並伴隨通航改善，才支持終局風險下降。"
    )
    market_stance = "風險定價佐證，不是終局證據"

    failures = [row["source"] for row in fetch_status if not row.get("ok")]
    confidence = "中等（僅方向性）" if higher_confidence >= 5 and len(failures) <= 1 else "偏低"
    confidence_note = (
        f"官方或多方報導{higher_confidence}組；"
        + (f"未成功來源：{'、'.join(failures)}。" if failures else "主要自動來源均成功。")
        + "對『是否仍有能力』的信心高於對『能維持多久』與『美方如何修正認知』的信心。"
    )

    route_a_status = "正在形成" if leading_id == "iran_weaker" else ("部分訊號" if weakness_dominant or retaliation_fading else "今日未成立")
    route_b_status = "退出窗口出現" if leading_id == "iran_resilient" else ("前半段獲支持" if retaliation_persistent else "持續觀察")
    route_c_status = "目前風險最高" if leading_id == "middle_stalemate" else ("仍是主要風險" if not exit_window else "風險下降")
    route_updates = {
        "iran_weaker": {
            "status": route_a_status,
            "evidence": f"能力衰退線索{weakness}組；有後果反擊由{resilience_prev}組變為{resilience}組。",
            "missing": "仍需跨日反擊下降、通航改善與可約束武裝單位的協議。",
        },
        "iran_resilient": {
            "status": route_b_status,
            "evidence": f"連續反擊={'是' if retaliation_persistent else '尚未確認'}；外交線索{diplomacy}組。",
            "missing": "仍需證明伊朗能長期施壓，以及美方確實因邊際收益下降而調整目標。",
        },
        "middle_stalemate": {
            "status": route_c_status,
            "evidence": f"海上壓力{maritime}組、外交線索{diplomacy}組；區域行動={'已出現' if regional_active else '未確認'}。",
            "missing": "若任一方明確縮小目標，或通航與協議執行跨日改善，僵局判讀才會被推翻。",
        },
    }

    scenario_updates = {key: value["status"] for key, value in route_updates.items()}
    watch_next = [
        "有後果反擊是否連續兩至三個觀察窗下降，而不是只安靜一天",
        "美方是否縮小政治目標、承認空襲邊際收益下降，或重新把重心移向可執行談判",
        "海峽與商船風險是否持續改善，且不是單純新聞量下降",
        "伊朗談判代表是否能約束革命衛隊、海軍與代理人，並接受違約驗證機制",
        "以色列或胡塞是否把條件式威脅轉為實際行動，使實力測試區域化",
    ]

    return {
        "model_version": 2,
        "headline": headline,
        "bottom_line": bottom_line,
        "test_phase": test_phase,
        "thesis_state": thesis_state,
        "leading_scenario_id": leading_id,
        "leading_scenario": leading_name,
        "confidence": confidence,
        "confidence_note": confidence_note,
        "revelation": {"title": revelation_title, "assessment": revelation_text},
        "durability": {"title": "仍不知道：這種能力能維持多久", "assessment": durability_text},
        "us_learning": {"title": "美方可能從中學到什麼", "assessment": us_learning_text},
        "endpoint": {"title": "今天較接近哪條終局路徑", "assessment": endpoint_text},
        "negotiability": {"title": "即使能談，協議能不能被執行", "assessment": negotiability_text},
        "escalation": {"title": "為什麼擴大可能通往終局，也可能製造僵局", "assessment": escalation_text},
        "activity": {"title": "公開資訊活動，不是戰力", "assessment": activity_text, "delta": current - previous},
        "israel": {"title": israel_title, "assessment": israel_text},
        "red_sea": {"title": red_sea_title, "assessment": red_sea_text},
        "asymmetric": {"title": asymmetric_title, "assessment": asymmetric_text},
        "market": {"title": "市場如何替終局風險定價", "assessment": market_text, "stance": market_stance},
        "route_updates": route_updates,
        "scenario_updates": scenario_updates,
        "watch_next": watch_next,
        "evidence_guardrail": (
            f"本期{current}組去重公開證據、其中{consequences}組標題提及可觀察後果。"
            "它們用來回答『有哪些命題值得人工驗證』，不直接回答飛彈庫存、攻擊總數或勝率。"
        ),
    }


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    fetch_status: list[dict[str, Any]] = []

    for category, query in QUERIES.items():
        try:
            found = google_news_items(category, query)
            items.extend(found)
            fetch_status.append({"source": f"Google News RSS / {category}", "ok": True, "items": len(found)})
        except Exception as exc:
            fetch_status.append({"source": f"Google News RSS / {category}", "ok": False, "error": str(exc)[:180]})

    try:
        found = gdelt_items()
        items.extend(found)
        fetch_status.append({"source": "GDELT DOC 2.0", "ok": True, "items": len(found)})
    except Exception as exc:
        fetch_status.append({"source": "GDELT DOC 2.0", "ok": False, "error": str(exc)[:180]})

    clusters = deduplicate(items)
    markets: dict[str, Any] = {}
    for key, config in MARKETS.items():
        try:
            markets[key] = fetch_market(key, config)
            fetch_status.append({"source": f"市場資料 / {config['label']}", "ok": True, "items": len(markets[key]["history"])})
        except Exception as exc:
            markets[key] = {"key": key, "label": config["label"], "ticker": config["ticker"], "error": str(exc)[:180]}
            fetch_status.append({"source": f"市場資料 / {config['label']}", "ok": False, "error": str(exc)[:180]})

    metrics = build_metrics(clusters)
    snapshot = {
        "schema_version": 1,
        "generated_at": utc_iso(),
        "data_window": "最近7日新聞（核心指標取72小時）、最近1個月市場資料",
        "metrics": metrics,
        "analysis": build_daily_analysis(metrics, markets, fetch_status),
        "items": clusters,
        "markets": markets,
        "fetch_status": fetch_status,
        "limitations": [
            "所有數量均為公開證據項目或市場觀測，不代表飛彈、無人機或攻擊總數。",
            "CENTCOM與UKMTO官網可能阻擋自動請求；流程透過新聞索引保留其公告連結。",
            "新聞標題分類只用於整理證據佇列，不等同於事實裁決或情境機率。",
            "新聞索引有每次查詢與頁數上限，7日活動圖是可比較的資訊活動指標，不是完整新聞母體。",
            "以色列的條件式報復言論不等同主動參戰；分析員警告也不等同紅海或蘇伊士已被封鎖。",
            "第二航運咽喉以曼德海峽與紅海入口為操作位置；對該處的干擾才會壓縮蘇伊士航運。",
            "Yahoo Finance為公開市場資料端點；失敗時保留上次成功值或顯示資料缺口。",
        ],
    }

    if not clusters and SNAPSHOT_PATH.exists():
        previous = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        previous["generated_at"] = utc_iso()
        previous["fetch_status"] = fetch_status
        previous["stale"] = True
        snapshot = previous
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {SNAPSHOT_PATH} with {len(snapshot.get('items', []))} evidence clusters")


if __name__ == "__main__":
    main()
