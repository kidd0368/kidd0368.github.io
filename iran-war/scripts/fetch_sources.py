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
}

OFFICIAL_DOMAINS = {
    "centcom.mil", "war.gov", "defense.gov", "whitehouse.gov", "ukmto.org",
    "maritime.dot.gov", "iaea.org", "imo.org", "un.org", "state.gov",
}
WIRE_SOURCES = {
    "associated press", "ap news", "reuters", "bbc", "bbc news", "axios",
    "financial times", "the washington post", "the new york times", "cnn",
}
CONSEQUENCE_TERMS = {
    "killed", "dead", "wounded", "injured", "damaged", "destroyed", "fire",
    "outage", "offline", "disrupted", "hit", "struck", "sank", "seized",
}
MARITIME_PRESSURE_TERMS = {
    "tanker", "ship", "shipping", "vessel", "hormuz", "strait", "port",
    "blockade", "transit", "navigation",
}
DIPLOMACY_TERMS = {
    "talks", "ceasefire", "agreement", "negotiation", "deal", "mediator",
    "diplomacy", "truce",
}
WEAKNESS_TERMS = {
    "degraded", "destroyed", "unable", "limited", "intercepted", "depleted",
    "exhausted", "weakened", "isolated",
}
RESILIENCE_TERMS = {
    "retaliat", "attack", "struck", "hit", "killed", "damaged", "closed",
    "disrupt", "outage", "seized", "threaten",
}
RELEVANCE_TERMS = ("iran", "iranian", "tehran", "irgc", "hormuz", "persian gulf")

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


def flags_for_title(title: str) -> dict[str, bool]:
    text = title.lower()
    return {
        "reported_consequence": any(term in text for term in CONSEQUENCE_TERMS),
        "maritime_pressure": any(term in text for term in MARITIME_PRESSURE_TERMS),
        "diplomacy": any(term in text for term in DIPLOMACY_TERMS),
        "weakness_signal": any(term in text for term in WEAKNESS_TERMS),
        "resilience_signal": any(term in text for term in RESILIENCE_TERMS),
    }


def classify_category(title: str, fallback: str = "軍事行動") -> str:
    text = title.lower()
    if any(x in text for x in ("hormuz", "tanker", "ship", "shipping", "vessel", "strait", "port", "navigation")):
        return "海峽與商船"
    if any(x in text for x in ("nuclear", "uranium", "iaea", "enrichment")):
        return "核問題"
    if any(x in text for x in ("talk", "ceasefire", "deal", "negotiat", "agreement", "diplomacy", "truce")):
        return "外交與停火"
    if any(x in text for x in ("power plant", "desalination", "bridge", "infrastructure", "refinery", "terminal")):
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
    query = '(Iran OR Iranian) (Hormuz OR missile OR drone OR ceasefire OR nuclear)'
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


def build_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    cutoff_72h = NOW - timedelta(hours=72)
    recent = [item for item in items if parse_date(item["published_at"].replace("Z", "+0000")) >= cutoff_72h]
    categories = Counter(item["category"] for item in recent)
    confidence = Counter(item["confidence"] for item in recent)
    flags = Counter()
    daily: dict[str, Counter[str]] = defaultdict(Counter)
    for item in items:
        dt = parse_date(item["published_at"].replace("Z", "+0000"))
        if dt >= NOW - timedelta(days=7):
            daily[dt.date().isoformat()][item["category"]] += 1
        if dt >= cutoff_72h:
            for flag, value in item["flags"].items():
                if value:
                    flags[flag] += 1
            if item["flags"]["resilience_signal"] and item["flags"]["reported_consequence"]:
                flags["consequential_resilience_signal"] += 1
            if item["flags"]["resilience_signal"] and (
                item["flags"]["maritime_pressure"] or item["flags"]["diplomacy"]
            ):
                flags["stalemate_signal"] += 1

    weakness = flags["weakness_signal"]
    resilience = flags["consequential_resilience_signal"]
    maritime = flags["maritime_pressure"]
    diplomacy = flags["diplomacy"]
    if recent and weakness >= 3 and resilience >= 3 and maritime >= 3:
        posture = "中間僵局訊號最需要警戒"
        posture_note = "公開資訊同時出現能力受損與持續反擊，尚未形成單向結論。"
    elif recent and resilience >= 5 and weakness < 3:
        posture = "持續反擊的公開訊號較強"
        posture_note = "有後果的反擊報導仍多；這只能證明壓制尚未完成，不能推算庫存。"
    elif recent and weakness >= 3 and resilience < 3:
        posture = "能力衰退訊號暫時較多"
        posture_note = "媒體標題中的受損與降級訊號較多，仍需用實際損害與航運改善驗證。"
    elif recent:
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
        "evidence_items_72h": len(recent),
        "multi_source_72h": confidence["多方報導"],
        "official_72h": confidence["官方發布"],
        "reported_consequence_72h": flags["reported_consequence"],
        "maritime_pressure_72h": maritime,
        "diplomacy_72h": diplomacy,
        "weakness_signal_72h": weakness,
        "resilience_signal_72h": resilience,
        "stalemate_signal_72h": flags["stalemate_signal"],
        "category_counts_72h": dict(categories),
        "daily_counts_7d": days,
        "posture": posture,
        "posture_note": posture_note,
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

    snapshot = {
        "schema_version": 1,
        "generated_at": utc_iso(),
        "data_window": "最近7日新聞（核心指標取72小時）、最近1個月市場資料",
        "metrics": build_metrics(clusters),
        "items": clusters,
        "markets": markets,
        "fetch_status": fetch_status,
        "limitations": [
            "所有數量均為公開證據項目或市場觀測，不代表飛彈、無人機或攻擊總數。",
            "CENTCOM與UKMTO官網可能阻擋自動請求；流程透過新聞索引保留其公告連結。",
            "新聞標題分類只用於整理證據佇列，不等同於事實裁決或情境機率。",
            "新聞索引有每次查詢與頁數上限，7日活動圖是可比較的資訊活動指標，不是完整新聞母體。",
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
