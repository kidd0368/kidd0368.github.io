# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cross_watch as C


def fed(key="preventive_hike", growth="resilient", credit="benign",
        inflation="anchored", market_hike=0.35):
    return {
        "ts": "2026-08-30T00:00:00+00:00",
        "scenario": {
            "key": key,
            "label": key,
            "stage": "test stage",
            "features": {
                "growth": growth,
                "credit": credit,
                "inflation_expectations": inflation,
                "realized_inflation": "hot",
                "market_hike": market_hike,
            },
        },
    }


def bond(d2=0, d10=0, real10=0, be10=0, be5=None, tp10=0,
         slope=None, pressure=45, aligned=True, aligned_d2=None,
         aligned_d10=None, aligned_tp10=None):
    slope = d10 - d2 if slope is None else slope
    be5 = be10 if be5 is None else be5
    out = {
        "ts": "2026-08-30T00:10:00+00:00",
        "asof": "2026-08-29",
        "curve": [
            {"label": "2Y", "value": 4.0, "date": "2026-08-29", "chg": {"20": d2}},
            {"label": "10Y", "value": 4.5, "date": "2026-08-29", "chg": {"20": d10}},
        ],
        "decomp": {
            "DFII10": {"value": 2.2, "date": "2026-08-29", "chg": {"20": real10}},
            "T10YIE": {"value": 2.3, "date": "2026-08-29", "chg": {"20": be10}},
            "T5YIE": {"value": 2.3, "date": "2026-08-29", "chg": {"20": be5}},
            "THREEFYTP10": {"value": 0.7, "date": "2026-08-25", "chg": {"20": tp10}},
        },
        "spreads": {"2s10s": {"bp": 50, "chg": {"20": slope}}},
        "pressure": {"score": pressure},
    }
    if aligned:
        aligned_d2 = d2 if aligned_d2 is None else aligned_d2
        aligned_d10 = d10 if aligned_d10 is None else aligned_d10
        aligned_tp10 = tp10 if aligned_tp10 is None else aligned_tp10
        out["aligned"] = {
            "term_premium_curve": {
                "date": "2026-08-25",
                "chg": {"20": {
                    "y2_bp": aligned_d2,
                    "y10_bp": aligned_d10,
                    "term_premium10_bp": aligned_tp10,
                }},
            },
        }
    return out


class CrossWatchTests(unittest.TestCase):
    def test_policy_repricing(self):
        got = C.classify(fed(), bond(d2=18, d10=14, real10=13))
        self.assertEqual(got["key"], "policy_repricing")

    def test_term_premium_shock_is_not_called_fed_hawk(self):
        got = C.classify(fed(market_hike=0.10), bond(d2=2, d10=22, real10=3, tp10=16))
        self.assertEqual(got["key"], "term_premium_shock")

    def test_new_policy_repricing_and_older_term_shock_are_both_visible(self):
        got = C.classify(
            fed(market_hike=0.40),
            bond(
                d2=18, d10=17, real10=13, tp10=16,
                aligned_d2=2, aligned_d10=22, aligned_tp10=16,
            ),
        )
        self.assertEqual(got["key"], "dual_rate_shock")

    def test_policy_error_needs_macro_and_bond_confirmation(self):
        got = C.classify(
            fed(key="policy_error", growth="weakening", market_hike=0.40),
            bond(d2=-16, d10=-3, real10=-12, slope=13),
        )
        self.assertEqual(got["key"], "policy_error_confirmed")
        self.assertFalse(got["provisional"])

    def test_policy_error_without_curve_confirmation_stays_watch(self):
        got = C.classify(
            fed(key="policy_error", growth="cooling", market_hike=0.40),
            bond(d2=-3, d10=-1, real10=-7, slope=2, pressure=76),
        )
        self.assertEqual(got["key"], "policy_error_unconfirmed")

    def test_stagflation_needs_breakeven_and_long_yield(self):
        got = C.classify(
            fed(key="stagflation", growth="weakening", inflation="deanchoring"),
            bond(d2=4, d10=18, real10=1, be10=17, tp10=7),
        )
        self.assertEqual(got["key"], "stagflation_confirmed")

    def test_resilient_inflation_cycle_is_not_called_stagflation(self):
        got = C.classify(
            fed(key="inflation_risk", growth="resilient", inflation="deanchoring"),
            bond(d2=12, d10=18, real10=1, be10=17, be5=18, tp10=7),
        )
        self.assertEqual(got["key"], "inflation_risk_unconfirmed")

    def test_hot_realized_inflation_does_not_replace_both_expectation_gates(self):
        got = C.classify(
            fed(key="stagflation", growth="weakening", inflation="deanchoring"),
            bond(d2=4, d10=18, real10=1, be10=17, be5=8, tp10=7),
        )
        self.assertEqual(got["key"], "inflation_risk_unconfirmed")

    def test_high_level_is_not_new_shock(self):
        got = C.classify(fed(key="mixed", market_hike=0.10), bond(pressure=82))
        self.assertEqual(got["key"], "high_discount_pressure")

    def test_policy_repricing_missing_real_rate_is_insufficient(self):
        broken = bond()
        broken["decomp"].pop("DFII10")
        got = C.classify(fed(), broken)
        self.assertEqual(got["key"], "insufficient")

    def test_policy_error_does_not_require_term_premium_or_real_rate(self):
        broken = bond(d2=-3, d10=-1, slope=2, pressure=76, aligned=False)
        broken["decomp"].pop("DFII10")
        broken["decomp"].pop("THREEFYTP10")
        got = C.classify(
            fed(key="policy_error", growth="cooling", market_hike=0.40),
            broken,
        )
        self.assertEqual(got["key"], "policy_error_unconfirmed")

    def test_term_premium_shock_requires_common_endpoint_changes(self):
        got = C.classify(
            fed(market_hike=0.10),
            bond(d2=2, d10=22, real10=3, tp10=16, aligned=False),
        )
        self.assertEqual(got["key"], "insufficient")

    def test_stale_batches_do_not_reuse_old_conclusion(self):
        stale = bond()
        stale["ts"] = "2026-08-28T00:00:00+00:00"
        got = C.classify(fed(), stale)
        self.assertEqual(got["key"], "insufficient")

    def test_shared_card_has_both_links_and_current_marker(self):
        link = C.classify(fed(), bond(d2=18, d10=14, real10=13))
        rendered = C.render_card(link, "fed")
        self.assertIn("../fed-watch/", rendered)
        self.assertIn("../bond-watch/", rendered)
        self.assertIn('aria-current="page"', rendered)

    def test_summary_id_is_shared_and_validated(self):
        f, b = fed(), bond(d2=18, d10=14, real10=13)
        summary = C.with_summary_id(C.classify(f, b), f, b)
        C.validate_summary(summary)
        self.assertEqual(summary["summary_id"], summary["linkage"]["summary_id"])


if __name__ == "__main__":
    unittest.main()
