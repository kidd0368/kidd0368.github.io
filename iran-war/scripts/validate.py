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
    require(all(key in snapshot.get("analysis", {}) for key in (
        "headline", "bottom_line", "leading_scenario", "confidence",
        "activity", "battlefield", "diplomacy", "israel", "red_sea",
        "asymmetric", "market", "watch_next",
    )), "daily analysis layer is incomplete")
    require(isinstance(snapshot.get("items"), list), "evidence items must be a list")
    require(len(snapshot.get("fetch_status", [])) >= 6, "source health ledger is incomplete")
    require(all(key in snapshot.get("metrics", {}) for key in (
        "evidence_items_72h", "maritime_pressure_72h", "diplomacy_72h",
        "weakness_signal_72h", "resilience_signal_72h", "stalemate_signal_72h", "daily_counts_7d",
        "evidence_items_24h", "evidence_items_prev_24h", "reported_consequence_24h",
        "israel_posture_24h", "israel_active_entry_24h", "second_chokepoint_24h",
        "houthi_operational_24h", "asymmetric_adaptation_24h",
    )), "required metrics are missing")
    require(len(assessment.get("scenarios", [])) == 3, "exactly three scenarios are required")
    require(len(events.get("events", [])) >= 5, "curated timeline is too short")
    require("<title>美伊戰爭終局追蹤</title>" in html, "HTML title missing")
    require(html.rstrip().endswith("</html>"), "HTML is truncated")
    require("__SNAPSHOT__" not in html and "__ASSESSMENT__" not in html, "unresolved template placeholder")
    require("攻擊次數" in html and "不是情境機率" in html, "interpretation guardrails missing")
    require("今天這些數據是什麼意思" in html and "下一步看什麼" in html, "daily interpretation UI missing")
    require("以色列介入" in html and "紅海—蘇伊士" in html and "非對稱戰術" in html, "regional expansion factors missing")
    require("<script src=" not in html, "dashboard must not depend on external JavaScript")
    require(len(html.encode("utf-8")) > 30_000, "generated dashboard unexpectedly small")
    print(f"validation passed: {len(snapshot.get('items', []))} evidence clusters, {len(html):,} HTML characters")


if __name__ == "__main__":
    main()
