#!/usr/bin/env python3
"""Fail the update job if the generated dashboard is incomplete or misleading."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"validation failed: {message}")


def main() -> None:
    snapshot = json.loads((ROOT / "data" / "snapshot.json").read_text(encoding="utf-8"))
    assessment = json.loads((ROOT / "data" / "assessment.json").read_text(encoding="utf-8"))
    events = json.loads((ROOT / "data" / "curated_events.json").read_text(encoding="utf-8"))
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    require(snapshot.get("schema_version") == 1, "unexpected snapshot schema")
    require(snapshot.get("generated_at"), "missing generated timestamp")
    require(snapshot.get("analysis", {}).get("model_version") == 2, "terminal thesis model is not v2")
    require(all(key in snapshot.get("analysis", {}) for key in (
        "headline", "plain_summary", "bottom_line", "hero_explanation", "test_phase", "thesis_state", "leading_scenario", "confidence",
        "revelation", "durability", "us_learning", "endpoint", "negotiability", "escalation",
        "activity", "israel", "red_sea", "asymmetric", "market", "route_updates",
        "watch_next", "evidence_guardrail",
    )), "daily analysis layer is incomplete")
    hero_explanation = snapshot.get("analysis", {}).get("hero_explanation", [])
    require(len(hero_explanation) == 5, "hero conclusion must contain exactly five reasoning layers")
    require(all(item.get("label") and item.get("title") and item.get("assessment") for item in hero_explanation),
            "hero conclusion reasoning layer is incomplete")
    require(isinstance(snapshot.get("items"), list), "evidence items must be a list")
    require(len(snapshot.get("fetch_status", [])) >= 6, "source health ledger is incomplete")
    require(all(key in snapshot.get("metrics", {}) for key in (
        "evidence_items_72h", "maritime_pressure_72h", "diplomacy_72h",
        "weakness_signal_72h", "resilience_signal_72h", "stalemate_signal_72h", "daily_counts_7d",
        "evidence_items_24h", "evidence_items_prev_24h", "reported_consequence_24h",
        "weakness_signal_prev_24h", "resilience_signal_prev_24h", "stalemate_signal_prev_24h",
        "quality_resilience_signal_24h", "quality_resilience_signal_prev_24h",
        "israel_posture_24h", "israel_active_entry_24h", "second_chokepoint_24h",
        "houthi_operational_24h", "asymmetric_adaptation_24h",
    )), "required metrics are missing")
    require(len(assessment.get("scenarios", [])) == 3, "exactly three scenarios are required")
    require(len(assessment.get("thesis", {}).get("steps", [])) == 4, "terminal thesis chain is incomplete")
    require(len(events.get("events", [])) >= 5, "curated timeline is too short")
    require("<title>美伊戰爭終局追蹤</title>" in html, "HTML title missing")
    require(html.rstrip().endswith("</html>"), "HTML is truncated")
    require("__SNAPSHOT__" not in html and "__ASSESSMENT__" not in html, "unresolved template placeholder")
    require("攻擊次數" in html and "不是情境機率" in html, "interpretation guardrails missing")
    require("核心推演：擴大如何可能通往終局" in html and "今日終局推演" in html, "terminal thesis UI missing")
    require(all(label in html for label in (
        "今天確認了什麼", "這代表什麼", "不能因此推論什麼", "目前較接近哪一種結局", "什麼情況會讓結論改變",
    )), "plain-language hero explanation is missing")
    require("什麼證據會推翻今天的結論" in html and "今天較接近哪條終局路徑" in html, "falsification layer missing")
    require("以色列觸發器" in html and "紅海第二咽喉" in html and "分散與非對稱能力" in html, "regional expansion factors missing")
    require("<script src=" not in html, "dashboard must not depend on external JavaScript")
    require(len(html.encode("utf-8")) > 30_000, "generated dashboard unexpectedly small")
    print(f"validation passed: {len(snapshot.get('items', []))} evidence clusters, {len(html):,} HTML characters")


if __name__ == "__main__":
    main()
