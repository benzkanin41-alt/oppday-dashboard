from __future__ import annotations

import json
import unittest
from pathlib import Path

from add_ai_semiconductor_direct_data import quarterly_cashflow
from refresh_ai_public_sources import micron_release_points, parse_gpu_cards
from retain_dashboard_history import merge_history, merge_points
from patch_set_session_history import normalize_snapshot, verified_session
from patch_thailand_heat_mai_treasury import synchronize_curve_indicator
from sync_latest_dashboard_summary import latest_market_anchor


RAW = Path(__file__).resolve().parent / "raw" / "ai_direct_v06"
TAG = "PaymentsToAcquireProductiveAssets"


def facts(rows):
    return {"facts": {"us-gaap": {TAG: {"units": {"USD": rows}}}}}


def row(start, end, value, form="10-Q"):
    return {"start": start, "end": end, "val": value * 1e9, "form": form, "filed": "2026-02-01", "accn": "test"}


class RefreshAdapterTests(unittest.TestCase):
    def test_explicit_quarter(self):
        points = quarterly_cashflow(facts([row("2025-04-01", "2025-06-30", 20)]), [TAG])
        self.assertEqual(points[0]["value"], 20)
        self.assertEqual(points[0]["basis"], "Reported quarter")

    def test_lone_ytd_is_not_quarter(self):
        self.assertEqual(quarterly_cashflow(facts([row("2025-01-01", "2025-06-30", 30)]), [TAG]), [])

    def test_skipped_quarter_is_not_difference(self):
        points = quarterly_cashflow(facts([row("2025-01-01", "2025-03-31", 10), row("2025-01-01", "2025-09-30", 60)]), [TAG])
        self.assertEqual([point["date"] for point in points], ["2025-03-31"])

    def test_annual_minus_nine_months(self):
        points = quarterly_cashflow(facts([row("2025-01-01", "2025-09-30", 92.297), row("2025-01-01", "2025-12-31", 131.819, "10-K")]), [TAG])
        self.assertEqual(points[-1]["value"], 39.522)
        self.assertEqual(points[-1]["period_start"], "2025-10-01")
        self.assertEqual(len(points[-1]["derived_from"]), 2)

    def test_different_fiscal_starts_not_mixed(self):
        points = quarterly_cashflow(facts([row("2024-12-01", "2025-02-28", 10), row("2025-01-01", "2025-06-30", 30)]), [TAG])
        self.assertEqual(len(points), 1)

    def test_point_retention_and_revision(self):
        points = merge_points([{"date": "2025-01-01", "value": 1}, {"date": "2025-01-02", "value": 2}], [{"date": "2025-01-02", "value": 3}, {"date": "2025-01-03", "value": 4}])
        self.assertEqual([point["value"] for point in points], [1, 3, 4])

    def test_rank_change_keeps_old_symbol(self):
        old = {"prices": {"XLE": {"chart_symbol": "XLE", "points": [{"date": "2025-01-01", "value": 1}]}}, "curves": {}, "ai": {}}
        payload = merge_history({}, old)
        self.assertIn("XLE", payload["price_histories_v04"])

    def test_instrument_mismatch_rejected(self):
        old = {"prices": {"QQQ": {"chart_symbol": "QQQ", "points": []}}, "curves": {}, "ai": {}}
        with self.assertRaises(RuntimeError):
            merge_history({"price_histories_v04": {"QQQ": {"chart_symbol": "^NDX", "points": []}}}, old)

    def test_public_gpu_structured_primary_data(self):
        for gpu in ("h100", "b200"):
            result = parse_gpu_cards((RAW / f"silicon_{gpu}.html").read_text(encoding="utf-8"), f"https://www.silicondata.com/products/silicon-index/{gpu}")
            self.assertTrue(result)
            for points in result.values():
                self.assertEqual(len(points), 7)
                self.assertTrue(all(point["source_url"].startswith("https://www.silicondata.com/") for point in points))

    def test_micron_quarter_vs_annual_and_gross_vs_net(self):
        result = micron_release_points((RAW / "micron_q4_2026.html").read_text(encoding="utf-8"))
        self.assertEqual(result["MU revenue"]["value"], 54.229)
        self.assertEqual(result["MU inventory"]["value"], 10.372)
        self.assertEqual(result["MU capex"]["value"], 11.110)
        self.assertEqual(result["MU capex"]["date"], "2026-09-03")

    def test_actual_amazon_missing_q4(self):
        data = json.loads((RAW / "sec_companyfacts_AMZN.json").read_text(encoding="utf-8"))
        points = quarterly_cashflow(data, [TAG])
        q4 = next(point for point in points if point["date"] == "2025-12-31")
        self.assertEqual(q4["value"], 39.522)

    def test_webpage_update_is_not_trading_date(self):
        item = {"as_of": "2026-10-03 03:20:11 Bangkok", "metrics": {"latest": 1571.62}}
        session = normalize_snapshot(item, [{"date": "2026-10-02", "value": 1571.62}])
        self.assertEqual(session, "2026-10-02")
        self.assertEqual(item["as_of"], "2026-10-02")
        self.assertTrue(item["page_updated_at"].startswith("2026-10-03"))

    def test_disagreeing_session_is_not_confirmed(self):
        with self.assertRaises(RuntimeError):
            verified_session({"metrics": {"latest": 1571.62}}, [{"date": "2026-09-15", "value": 1582.87}])

    def test_macro_curve_matches_bond_chart(self):
        payload = {}
        synchronize_curve_indicator(payload, [
            {"date": "2026-10-01", "2Y": 4.80, "10Y": 5.26},
            {"date": "2026-10-02", "2Y": 4.83, "10Y": 5.28},
        ])
        indicator = payload["macro_v04"]["indicators"][0]
        self.assertEqual(indicator["date"], "2026-10-02")
        self.assertAlmostEqual(indicator["latest"], 0.45)

    def test_market_anchor_prefers_verified_session(self):
        anchor = latest_market_anchor({"indices": [{"as_of": "2026-10-03 03:20:11 Bangkok", "market_session_date": "2026-10-02"}], "data_anchor": "2026-10-03"})
        self.assertEqual(anchor, "2026-10-02")

    def test_later_restatement_not_mixed_into_earlier_quarter(self):
        old = {**row("2025-01-01", "2025-06-30", 4.432723), "filed": "2025-08-12", "accn": "old"}
        restated = {**old, "val": 4.396e9, "filed": "2026-08-12", "accn": "new"}
        current = {**row("2025-01-01", "2025-09-30", 7.562686), "filed": "2025-11-10", "accn": "q3"}
        points = quarterly_cashflow(facts([old, restated, current]), [TAG])
        q3 = next(point for point in points if point["date"] == "2025-09-30")
        self.assertEqual(q3["value"], 3.13)
        self.assertEqual(q3["derived_from"][1]["filed"], "2025-08-12")

    def test_actual_coreweave_q3_filing_vintage(self):
        data = json.loads((RAW / "sec_companyfacts_CRWV.json").read_text(encoding="utf-8"))
        points = quarterly_cashflow(data, ["ProceedsFromIssuanceOfLongTermDebt"])
        q3 = next(point for point in points if point["date"] == "2025-09-30")
        self.assertEqual(q3["value"], 3.13)
        self.assertEqual(q3["derived_from"][1]["val"], 4432723000)
        self.assertLessEqual(q3["derived_from"][1]["filed"], q3["filed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
