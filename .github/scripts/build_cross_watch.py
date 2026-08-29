# -*- coding: utf-8 -*-
"""由兩份加密 store 產生唯一的政策 × 債市共同摘要。"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FED_SCRIPTS = os.path.join(ROOT, "fed-watch", "scripts")
sys.path.insert(0, FED_SCRIPTS)
sys.path.insert(0, HERE)

import cross_watch as C
import fwcrypto
import model as M

FED_BASE = os.path.join(ROOT, "fed-watch")
BOND_BASE = os.path.join(ROOT, "bond-watch")
FED_STORE = os.path.join(FED_BASE, "data", "store.enc")
BOND_STORE = os.path.join(BOND_BASE, "data", "store.enc")
SUMMARY_PATH = os.environ.get(
    "CROSS_WATCH_SUMMARY_PATH",
    os.path.join(ROOT, ".github", "data", "cross_watch.enc"),
)
CFG = json.load(open(os.path.join(FED_BASE, "config.json"), encoding="utf-8"))


def _run_at(snapshot):
    try:
        value = dt.datetime.fromisoformat(str(snapshot.get("ts", "")).replace("Z", "+00:00"))
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return dt.datetime.now(dt.timezone.utc)


def derive_fed_analysis(store, now):
    meetings = CFG["meetings"]
    target = CFG["current_target"]
    midpoint = (target["low"] + target["high"]) / 2
    snapshot = store["snapshots"][-1]
    market = M.market_layer(snapshot, meetings)
    model = M.model_layer(store["macro"], meetings, midpoint, now=now)
    expert = M.expert_layer(
        store["quotes"], meetings, CFG["expert_lookback_days"],
        CFG["expert_min_quotes"], now=now,
    )
    blended = M.blend(market, model, expert, meetings, CFG["weights"])
    features = M.scenario_features(
        store["macro"], market, model, expert, meetings, CFG["scenario_rules"],
    )
    scenario = M.classify_policy_scenario(features, CFG["scenario_rules"])
    return {
        "schema_version": 1,
        "run_at": now.isoformat(timespec="seconds"),
        "market": market,
        "model": model,
        "expert": expert,
        "blend": blended,
        "scenario": scenario,
    }


def main():
    password = os.environ.get("PAGE_PASSWORD", "").strip()
    if not password:
        sys.exit("PAGE_PASSWORD env is required")

    fed_store = fwcrypto.load_store(FED_STORE, password)
    bond_store = fwcrypto.load_store(BOND_STORE, password)
    if not fed_store.get("snapshots"):
        sys.exit("fed-watch store has no snapshots")
    if not bond_store.get("snapshots"):
        sys.exit("bond-watch store has no snapshots")

    fed_snapshot = fed_store["snapshots"][-1]
    bond_snapshot = bond_store["snapshots"][-1]
    analysis = derive_fed_analysis(fed_store, _run_at(fed_snapshot))
    fed_snapshot["analysis"] = analysis
    fed_snapshot["model"] = {
        "hawk_score": analysis["model"]["hawk_score"],
        "dists": analysis["model"]["dists"],
    }
    fed_snapshot["blend"] = analysis["blend"]
    fed_snapshot["scenario"] = analysis["scenario"]

    linkage = C.classify(fed_snapshot, bond_snapshot)
    summary = C.with_summary_id(linkage, fed_snapshot, bond_snapshot)
    summary["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    fed_snapshot["cross_watch_summary_id"] = summary["summary_id"]

    # 兩份產物都維持加密；任何一步失敗時 workflow 不會提交半成品。
    fwcrypto.save_store(FED_STORE, fed_store, password)
    fwcrypto.save_store(SUMMARY_PATH, summary, password)
    print("[cross-watch] encrypted shared summary written")


if __name__ == "__main__":
    main()
