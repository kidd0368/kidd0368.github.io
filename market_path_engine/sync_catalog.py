#!/usr/bin/env python3
"""Refresh the last-known Pages Hub catalog used by the browser fallback."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


ENGINE = Path(__file__).resolve().parent
SNAPSHOT = ENGINE / "site_catalog_snapshot.json"
CATALOG_URL = os.environ.get(
    "MARKET_PATH_CATALOG_URL", "https://kidd0368.github.io/github/catalog.json"
)
USER_AGENT = "MarketPathCatalogSync/1.0"


def validate(catalog):
    if not isinstance(catalog, dict) or not isinstance(catalog.get("sites"), list):
        raise ValueError("catalog must contain a sites array")
    if (catalog.get("policy") or {}).get("external_sites_direct_weight") is not False:
        raise ValueError("catalog must explicitly disable direct external-site weighting")
    roles = {"core_signal", "conditional_module", "research_only"}
    for site in catalog["sites"]:
        role = (site.get("market_path") or {}).get("role")
        if role not in roles:
            raise ValueError(f"invalid Market Path role: {role!r}")
    return catalog


def fetch_catalog():
    request = urllib.request.Request(
        f"{CATALOG_URL}?cb=workflow",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return validate(json.loads(response.read().decode("utf-8")))


def main():
    try:
        catalog = fetch_catalog()
    except Exception as exc:
        if SNAPSHOT.exists():
            validate(json.loads(SNAPSHOT.read_text(encoding="utf-8")))
            print(f"catalog refresh unavailable; keeping valid snapshot: {exc}")
            return
        raise
    SNAPSHOT.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"catalog refreshed: {len(catalog['sites'])} inventory entries, "
        f"{(catalog.get('counts') or {}).get('bundle', 0)} bundle sources"
    )


if __name__ == "__main__":
    main()
