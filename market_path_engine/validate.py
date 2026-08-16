#!/usr/bin/env python3
"""Regression checks for the generated Market Path page and source policy."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "market_path_engine"
INDEX = ROOT / "market-path" / "index.html"
LATEST = ENGINE / "data" / "latest.json"
BUNDLE = ENGINE / "analysis_bundle.js"


def require(text: str, token: str, label: str) -> None:
    if token not in text:
        raise AssertionError(f"missing {label}: {token}")


def main() -> None:
    index = INDEX.read_text(encoding="utf-8")
    bundle = BUNDLE.read_text(encoding="utf-8")
    payload = json.loads(LATEST.read_text(encoding="utf-8"))

    for token in (
        "Financial Conditions",
        "Liquidity",
        "Volatility",
        "Positioning",
        "Cross-Asset Confirmation",
        "Event Shock",
        "Current regime",
        "1–5D / 1–4W / 1–3M Path",
        "Prediction Archive / Validation",
        "data-role-count=\"core_signal\"",
        "data-role-count=\"conditional_module\"",
        "data-role-count=\"research_only\"",
        "Heuristic V1 · uncalibrated",
        "EPS／企業獲利預估完全不進模型",
    ):
        require(index, token, "generated page contract")

    if "/*__MPE_DATA__*/null" in index:
        raise AssertionError("generated page still contains the data placeholder")
    if "12 個網頁" in index or "11 個已發布" in index or "12 個網頁" in bundle:
        raise AssertionError("cross-site page count is still hard-coded")

    for token in (
        "/github/catalog.json",
        "raw.githubusercontent.com/kidd0368/github/main/sites.json",
        "site_catalog_snapshot.json",
        "new_published_sites_auto_bundle:true",
        "external_sites_direct_weight:false",
        "adjusted_probabilities:'do_not_invent_without_a_separate_calibrated_method'",
    ):
        require(bundle, token, "dynamic catalog policy")

    methodology = payload.get("methodology") or {}
    if methodology.get("eps_included") is not False:
        raise AssertionError("EPS forecasts must remain excluded")
    if methodology.get("probability_type") != "heuristic_prior" or methodology.get("calibrated") is not False:
        raise AssertionError("probabilities must remain explicitly heuristic and uncalibrated")
    if (methodology.get("external_site_policy") or {}).get("direct_weight") is not False:
        raise AssertionError("external sites must not directly change model weights")

    weights = methodology.get("regime_weights") or {}
    if round(sum(float(value) for value in weights.values()), 10) != 1.0:
        raise AssertionError("regime weights must sum to 1")

    expected_horizons = {"1–5D", "1–4W", "1–3M"}
    paths = payload.get("paths") or []
    if {path.get("horizon") for path in paths} != expected_horizons:
        raise AssertionError("required path horizons changed")
    for path in paths:
        probabilities = path.get("probabilities") or {}
        total = sum(float(probabilities.get(key, 0)) for key in ("up", "range", "down"))
        if abs(total - 100) > 0.05:
            raise AssertionError(f"path probabilities do not sum to 100: {path.get('horizon')}")

    print(
        "validation passed: "
        f"{len(payload.get('modules') or {})} modules, "
        f"{len(paths)} horizons, "
        f"{(payload.get('archive') or {}).get('prediction_count', 0)} archived predictions"
    )


if __name__ == "__main__":
    main()
