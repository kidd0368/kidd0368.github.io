# -*- coding: utf-8 -*-
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as M


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))["scenario_rules"]
MEETINGS = [{"key": "NEXT"}, {"key": "LATER"}]


def macro(be=2.3, be20=0.03, weak=False):
    return {
        "T10YIE": {"date": "2026-08-28", "value": be, "chg20d": be20},
        "PCEPILFE": {"date": "2026-07-01", "yoy": 3.2},
        "CPILFESL": {"date": "2026-07-01", "m3ann": 2.1},
        "PAYEMS": {"date": "2026-07-01", "diff3avg": 40.0 if weak else 180.0},
        "UNRATE": {"date": "2026-07-01", "chg3m": 0.3 if weak else -0.1},
        "ICSA": {"date": "2026-08-22", "ma4": 260000.0 if weak else 220000.0,
                 "ma4chg4": 12.0 if weak else 0.0},
        "BAMLH0A0HYM2": {"date": "2026-08-28", "value": 5.2 if weak else 3.0},
        "NFCI": {"date": "2026-08-21", "value": 0.2 if weak else -0.5},
        "DRTSCILM": {"date": "2026-07-01", "value": 30.0 if weak else 5.0},
    }


def classify(data, hike=0.6, later_hike=0.4, hawk_score=0.3, expert_tilt=0.2):
    market = {"dists": {"NEXT": {"hike25": hike, "hold": 1 - hike},
                        "LATER": {"hike25": later_hike, "hold": 1 - later_hike}},
              "sources": {"NEXT": ["test"]}}
    model_hike = 0.55 if hawk_score >= 0.2 else 0.1
    model = {"dists": {"NEXT": {"hike25": model_hike, "hold": 1 - model_hike}},
             "hawk_score": hawk_score}
    features = M.scenario_features(data, market, model, {"tilt": expert_tilt}, MEETINGS, RULES)
    return M.classify_policy_scenario(features, RULES)


class ScenarioTests(unittest.TestCase):
    def test_anchored_resilient(self):
        self.assertEqual(classify(macro())["key"], "preventive_hike")

    def test_deanchoring_resilient(self):
        self.assertEqual(classify(macro(be=2.7, be20=0.22))["key"], "renewed_hiking")

    def test_anchored_weakening(self):
        result = classify(macro(weak=True))
        self.assertEqual(result["key"], "policy_error")
        self.assertEqual(result["stage"], "警報條件成立")

    def test_deanchoring_weakening(self):
        self.assertEqual(classify(macro(be=2.7, be20=0.22, weak=True))["key"], "stagflation")

    def test_cooling_without_hawk_is_not_policy_error(self):
        result = classify(macro(weak=True), hike=0.1, hawk_score=0.0, expert_tilt=0.0)
        self.assertEqual(result["key"], "cooling_without_hawk")

    def test_low_level_rebound_is_not_deanchoring(self):
        result = classify(macro(be=2.2, be20=0.22))
        self.assertNotEqual(result["features"]["inflation_expectations"], "deanchoring")

    def test_deanchoring_without_later_hikes_is_not_hiking_cycle(self):
        result = classify(macro(be=2.7, be20=0.22), later_hike=0.1)
        self.assertEqual(result["key"], "inflation_risk")

    def test_missing_core_axis_is_insufficient(self):
        data = macro()
        del data["T10YIE"]
        self.assertEqual(classify(data)["key"], "insufficient")


if __name__ == "__main__":
    unittest.main()
