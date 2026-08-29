# -*- coding: utf-8 -*-
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 這組測試只驗證日期與利差數學，不呼叫網路；避免離線測試被 requests 安裝狀態綁住。
sys.modules.setdefault("requests", types.SimpleNamespace(Session=object))
import collect as C


class BondMathTests(unittest.TestCase):
    def test_weekly_series_uses_calendar_aligned_20_trading_days(self):
        rows = [
            ("2026-07-24", 0.60),
            ("2026-07-31", 0.80),
            ("2026-08-07", 0.84),
            ("2026-08-14", 0.86),
            ("2026-08-21", 0.88),
            ("2026-08-28", 0.90),
        ]
        self.assertEqual(C.change_bp_on_aligned_date(rows, "2026-08-28", 0.90, 20), 10.0)

    def test_spread_uses_same_asof_date_for_both_legs(self):
        series = {
            "DGS2": [
                ("2026-07-31", 4.00),
                ("2026-08-27", 4.10),
                ("2026-08-28", 4.30),
            ],
            "DGS10": [
                ("2026-07-31", 4.50),
                ("2026-08-27", 4.60),
            ],
        }
        snap = C.build_snapshot(series)
        self.assertEqual(snap["spreads"]["2s10s"]["bp"], 50.0)

    def test_term_premium_comparison_uses_one_common_endpoint(self):
        series = {
            "DGS2": [
                ("2026-07-28", 4.00),
                ("2026-08-25", 4.05),
                ("2026-08-28", 4.30),
            ],
            "DGS10": [
                ("2026-07-28", 4.50),
                ("2026-08-25", 4.70),
                ("2026-08-27", 4.90),
            ],
            "THREEFYTP10": [
                ("2026-07-28", 0.50),
                ("2026-08-25", 0.62),
            ],
        }
        snap = C.build_snapshot(series)
        aligned = snap["aligned"]["term_premium_curve"]
        self.assertEqual(aligned["date"], "2026-08-25")
        self.assertEqual(aligned["chg"]["20"]["y2_bp"], 5.0)
        self.assertEqual(aligned["chg"]["20"]["y10_bp"], 20.0)
        self.assertEqual(aligned["chg"]["20"]["term_premium10_bp"], 12.0)


if __name__ == "__main__":
    unittest.main()
