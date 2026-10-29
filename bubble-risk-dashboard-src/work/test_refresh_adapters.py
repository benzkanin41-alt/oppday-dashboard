from __future__ import annotations

import json
import io
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from add_ai_semiconductor_direct_data import quarterly_cashflow, patch_source_manifest_table
from refresh_ai_public_sources import PublicHTML, micron_release_points, parse_gpu_cards
from retain_dashboard_history import merge_history, merge_points
from patch_set_session_history import normalize_snapshot, verified_session
from patch_thailand_heat_mai_treasury import synchronize_curve_indicator
from sync_latest_dashboard_summary import latest_market_anchor
import update_current_market_indicators as market_refresh
import patch_mai_tradingview_history as mai_refresh
import patch_meta_latest_release_capex as meta_refresh
import refresh_ai_public_sources as public_refresh
from validate_mai_chart_history import verify_session
from thai_market_sessions import completed_daily_points, cached_completed_points, reconcile_quote, apply_reconciliation
from finalize_requested_dashboard_metrics import merge_latest_snapshot, enrich_thailand
from clean_payload_user_text import clean_price_series
from refresh_alphabet_release_capex import parse_release, reconcile_capex


RAW = Path(__file__).resolve().parent / "raw" / "ai_direct_v06"
TAG = "PaymentsToAcquireProductiveAssets"


def facts(rows):
    return {"facts": {"us-gaap": {TAG: {"units": {"USD": rows}}}}}


def row(start, end, value, form="10-Q"):
    return {"start": start, "end": end, "val": value * 1e9, "form": form, "filed": "2026-02-01", "accn": "test"}


def gpu_document(count, headline=None):
    points = [{"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "price": round(2 + i / 100, 2)} for i in range(count)]
    card = {"key": "h100-neo", "points": points, "rawValue": points[-1]["price"] if headline is None else headline}
    packet = [1, "0:" + json.dumps({"cards": [card]}) + "\n"]
    return "<script>self.__next_f.push(" + json.dumps(packet) + ")</script>"


def alphabet_document(years="2025</td><td>2026</td><td>2025</td><td>2026"):
    return ("<table><tr><td>Quarter Ended September 30,</td><td>Year To Date September 30,</td></tr>"
            f"<tr><td>{years}</td></tr><tr><td>Purchases of property and equipment</td>"
            "<td>(23,953)</td><td>(51,355)</td><td>(63,596)</td><td>(131,953)</td></tr></table>")


class RefreshAdapterTests(unittest.TestCase):
    def test_alphabet_quarter_not_ytd_or_prior_year(self):
        point = parse_release(alphabet_document())
        self.assertEqual(point["value"], 51.355)
        self.assertEqual(point["ytd_value"], 131.953)
        self.assertEqual(point["period_start"], "2026-07-01")

    def test_alphabet_changed_column_order_rejected(self):
        with self.assertRaises(ValueError):
            parse_release(alphabet_document("2026</td><td>2025</td><td>2026</td><td>2025"))

    def test_alphabet_release_preserves_authoritative_sec_fact(self):
        release = parse_release(alphabet_document())
        points = [{"date": release["date"], "value": 51.355, "form": "10-Q"}]
        self.assertEqual(reconcile_capex(points, release), points)
        with self.assertRaises(ValueError):
            reconcile_capex([{**points[0], "value": 131.953}], release)

    def test_alphabet_release_must_reconcile_to_ytd(self):
        release = parse_release(alphabet_document())
        old = {"date": "2026-06-30", "derived_from": [{"start": "2026-01-01", "end": "2026-06-30", "val": 80598000000}]}
        self.assertEqual(reconcile_capex([old], release)[-1]["value"], 51.355)
        with self.assertRaises(ValueError):
            reconcile_capex([old], {**release, "value": 100.0})

    def temporary_cache(self):
        directory = RAW.parents[1] / ".build_cache"
        directory.mkdir(parents=True, exist_ok=True)
        return TemporaryDirectory(prefix="adapter-tests-", dir=directory)

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
            expected = {"NeoCloud H100", "Hyperscaler H100"} if gpu == "h100" else {"NeoCloud B200"}
            self.assertTrue(expected.issubset(result))
            for points in result.values():
                self.assertTrue(points)
                days = [point["date"] for point in points]
                self.assertEqual(days, sorted(set(days)))
                self.assertTrue(all(0 < point["value"] < 100 for point in points))
                self.assertTrue(all(point["source_url"].startswith("https://www.silicondata.com/") for point in points))

    def test_public_gpu_variable_window(self):
        url = "https://www.silicondata.com/products/silicon-index/h100"
        for count in (7, 30):
            with self.subTest(count=count):
                points = parse_gpu_cards(gpu_document(count), url)["NeoCloud H100"]
                self.assertEqual(len(points), count)
                self.assertEqual(points[0]["date"], "2025-01-01")
                self.assertEqual(points[-1]["value"], round(2 + (count - 1) / 100, 2))

    def test_public_gpu_headline_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "headline and dated chart disagree"):
            parse_gpu_cards(gpu_document(30, headline=9), "https://www.silicondata.com/products/silicon-index/h100")

    def test_public_error_page_keeps_valid_cache(self):
        with self.temporary_cache() as folder:
            path = Path(folder) / "gpu.html"
            original = gpu_document(7)
            path.write_text(original, encoding="utf-8")
            validate = lambda text: parse_gpu_cards(text, "https://example.test")
            with patch.object(public_refresh, "urlopen", return_value=io.BytesIO(b"<html>Access denied</html>")), patch.object(public_refresh.subprocess, "run", return_value=SimpleNamespace(returncode=22, stderr="HTTP 403")):
                raw, mode = public_refresh.fetch_document("https://example.test", path, validate)
            self.assertEqual((raw, mode), (original, "cache"))
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_public_valid_response_replaces_cache_atomically(self):
        with self.temporary_cache() as folder:
            path = Path(folder) / "gpu.html"
            document = gpu_document(30)
            validate = lambda text: parse_gpu_cards(text, "https://example.test")
            with patch.object(public_refresh, "urlopen", return_value=io.BytesIO(document.encode())):
                raw, mode = public_refresh.fetch_document("https://example.test", path, validate)
            self.assertEqual((raw, mode), (document, "live"))
            self.assertEqual(path.read_text(encoding="utf-8"), document)
            self.assertFalse(path.with_suffix(".html.tmp").exists())

    def test_invalid_public_cache_is_not_accepted(self):
        with self.temporary_cache() as folder:
            path = Path(folder) / "gpu.html"
            path.write_text("<html>Access denied</html>", encoding="utf-8")
            validate = lambda text: parse_gpu_cards(text, "https://example.test")
            with patch.object(public_refresh, "urlopen", side_effect=RuntimeError("offline")), patch.object(public_refresh.subprocess, "run", return_value=SimpleNamespace(returncode=22, stderr="HTTP 403")), self.assertRaises(ValueError):
                public_refresh.fetch_document("https://example.test", path, validate)

    def test_source_manifest_renders_all_rows_and_links(self):
        sources = [{"name": "API A&B", "used_for": "Risk <data>", "publication_date": "2026-10-17", "url": "https://example.test/?x=1&y=2"}, {"name": r"Source \1", "used_for": "History", "publication_date": "2026-10-16", "url": "https://example.test/history"}]
        page = '<h2>Source Manifest</h2><table><thead><tr><th>Source</th><th>Used For</th><th>Publication / Access Date</th><th>Link</th></tr></thead><tbody></tbody></table>'
        document = PublicHTML()
        document.feed(patch_source_manifest_table(page, sources))
        self.assertEqual(len(document.tables[0]) - 1, len(sources))
        self.assertEqual([row[0] for row in document.tables[0][1:]], [source["name"] for source in sources])
        self.assertEqual(document.table_links[0], [source["url"] for source in sources])

    def test_macro_http_error_keeps_valid_cache(self):
        with self.temporary_cache() as folder:
            root = Path(folder)
            original = "observation_date,DGS10\n2026-10-01,5.26\n"
            (root / "DGS10.csv").write_text(original, encoding="utf-8")
            (root / "latest_sources.json").write_text(json.dumps({"fetch_status": {"DGS10.csv": {"last_successful_fetch": "2026-10-01T20:00:00Z"}}}), encoding="utf-8")
            with patch.object(market_refresh, "RAW", root), patch.object(market_refresh, "LATEST", root / "latest_sources.json"), patch.object(market_refresh, "run_curl", return_value="<html>upstream unavailable, try again later</html>"):
                self.assertEqual(market_refresh.cached_text("DGS10.csv", "https://example.test"), original)
            self.assertEqual((root / "DGS10.csv").read_text(encoding="utf-8"), original)
            status = market_refresh.FETCH_STATUS["DGS10.csv"]
            self.assertEqual(status["mode"], "cache")
            self.assertEqual(status["last_successful_fetch"], "2026-10-01T20:00:00Z")
            self.assertIn("No valid observations", status["error"])

    def test_macro_valid_response_replaces_cache(self):
        with self.temporary_cache() as folder:
            root = Path(folder)
            valid = "observation_date,DGS10\n2026-10-16,5.14\n"
            with patch.object(market_refresh, "RAW", root), patch.object(market_refresh, "LATEST", root / "latest_sources.json"), patch.object(market_refresh, "run_curl", return_value=valid):
                self.assertEqual(market_refresh.cached_text("DGS10.csv", "https://example.test"), valid)
            self.assertEqual((root / "DGS10.csv").read_text(encoding="utf-8"), valid)
            self.assertFalse((root / "DGS10.csv.tmp").exists())
            self.assertEqual(market_refresh.FETCH_STATUS["DGS10.csv"]["mode"], "live")

    def test_macro_invalid_documents_rejected(self):
        for name, text in (("DGS10.csv", "observation_date,DGS10\n2026-10-16,NaN\n"), ("treasury.xml", "<html>unavailable</html>"), ("nyfed_effr_latest.json", '{"error":"unavailable"}')):
            with self.subTest(name=name), self.assertRaises(ValueError):
                market_refresh.validate_source_text(name, text)

    def test_macro_curl_requires_http_success(self):
        with patch.object(market_refresh.subprocess, "run", return_value=SimpleNamespace(returncode=22, stderr="HTTP 503", stdout="")) as run:
            with self.assertRaises(RuntimeError):
                market_refresh.run_curl("https://example.test")
            self.assertIn("--fail", run.call_args.args[0])

    def test_mai_mismatched_cache_cannot_overwrite_official_close(self):
        item = {"as_of": "2026-10-17", "quote_session_date": "2026-10-12", "quote_is_final": True, "metrics": {"latest": 225.0}}
        with self.assertRaises(RuntimeError):
            mai_refresh.verify_official_close(item, [{"date": "2026-10-12", "value": 221.0}])
        self.assertEqual(item["metrics"]["latest"], 225.0)
        self.assertNotIn("history_as_of", item)

    def test_mai_incomplete_fetch_keeps_cache_timestamp(self):
        with self.temporary_cache() as folder:
            path = Path(folder) / "mai.json"
            cached = {"fetched_at": "2026-10-01T12:00:00Z", "points": [{"date": (date(2024, 1, 1) + timedelta(days=i)).isoformat(), "value": 221.0} for i in range(1000)]}
            path.write_text(json.dumps(cached), encoding="utf-8")
            with patch.object(mai_refresh, "RAW_TV", path), patch.object(mai_refresh, "load_tv_fetcher", return_value=SimpleNamespace(fetch_history=lambda *args: [])):
                points, status = mai_refresh.read_or_fetch_points()
            self.assertEqual(points, cached["points"])
            self.assertEqual(status["mode"], "cache")
            self.assertEqual(status["fetched_at"], cached["fetched_at"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), cached)

    def test_mai_session_guard_rejects_old_history(self):
        item = {"symbol": "mai", "metrics": {"latest": 225.0}}
        apply_reconciliation(item, [{"date": "2026-10-16", "value": 224.0}])
        payload = {"indices": [item]}
        with self.assertRaises(AssertionError):
            verify_session(payload, [{"date": "2026-07-03", "value": 225.0}])
        verify_session(payload, [{"date": "2026-10-16", "value": 224.0}])

    def test_meta_cache_mode_and_retrieval_are_disclosed(self):
        with self.temporary_cache() as folder:
            path = Path(folder) / "meta.json"
            point = {"date": "2026-06-30", "value": 30.116}
            path.write_text(json.dumps({"fetched_at": "2026-10-01T12:00:00Z", "point": point}), encoding="utf-8")
            with patch.object(meta_refresh, "RAW", path), patch.object(meta_refresh, "fetch_release_point", side_effect=RuntimeError("offline")):
                actual, status = meta_refresh.read_or_fetch()
            self.assertEqual(actual, point)
            self.assertEqual(status["mode"], "cache")
            sources = []
            meta_refresh.upsert_source(sources, status)
            self.assertEqual(sources[0]["last_successful_fetch"], "2026-10-01T12:00:00Z")
            self.assertIn("refresh mode: cache", sources[0]["publication_date"])

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
        self.assertTrue(item["as_of"].startswith("2026-10-03"))
        self.assertNotIn("market_session_date", item)
        self.assertEqual(item["history_as_of"], "2026-10-02")

    def test_disagreeing_session_is_not_confirmed(self):
        with self.assertRaises(RuntimeError):
            verified_session({"quote_session_date": "2026-09-15", "quote_is_final": True, "metrics": {"latest": 1571.62}}, [{"date": "2026-09-15", "value": 1582.87}])

    def test_intraday_and_prior_close_remain_separate(self):
        item = {"quote_session_date": "2026-10-29", "quote_is_final": False, "metrics": {"latest": 218.2}}
        status = apply_reconciliation(item, [{"date": "2026-10-28", "value": 219.0}])
        self.assertEqual(status["state"], "intraday_not_close_comparable")
        self.assertEqual(item["metrics"]["latest"], 218.2)
        self.assertEqual(item["history_latest"], 219.0)

    def test_preopen_closed_snapshot_does_not_establish_session(self):
        item = {"as_of": "2026-10-29 08:55:00 Bangkok", "market_status": "Closed", "metrics": {"latest": 219.0}}
        status = apply_reconciliation(item, [{"date": "2026-10-22", "value": 219.0}])
        self.assertEqual(status["state"], "session_unresolved")
        self.assertNotIn("market_session_date", item)
        self.assertTrue(item["as_of"].startswith("2026-10-29"))

    def test_current_day_candle_not_promoted_to_completed_cache(self):
        points = [{"date": "2026-10-28", "value": 219.0}, {"date": "2026-10-29", "value": 218.2}]
        self.assertEqual(completed_daily_points(points, "2026-10-29"), points[:1])

    def test_same_session_mismatch_keeps_cache_bytes(self):
        with self.temporary_cache() as folder:
            path = Path(folder) / "mai.json"
            original = '{"fetched_at":"old","points":[]}'
            path.write_text(original, encoding="utf-8")
            points = [{"date": (date(2022, 1, 1) + timedelta(days=i)).isoformat(), "value": 221.0} for i in range(1000)]
            item = {"quote_session_date": points[-1]["date"], "quote_is_final": True, "metrics": {"latest": 222.0}}
            with patch.object(mai_refresh, "RAW_TV", path), patch.object(mai_refresh, "load_tv_fetcher", return_value=SimpleNamespace(fetch_history=lambda *args: points)), self.assertRaises(RuntimeError):
                mai_refresh.read_or_fetch_points(item)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_finalizer_cannot_append_unverified_page_timestamp(self):
        item = {"as_of": "2026-10-29 08:55:00 Bangkok", "metrics": {"latest": 218.2}}
        history = {"points": [{"date": "2026-10-28", "value": 219.0}]}
        self.assertEqual(merge_latest_snapshot(item, history), [{"date": "2026-10-28", "value": 219.0}])
        self.assertEqual(item["metrics"]["latest"], 218.2)

    def test_completed_known_quote_session_reconciles(self):
        item = {"quote_session_date": "2026-10-28", "quote_is_final": True, "metrics": {"latest": 219.0}}
        self.assertEqual(reconcile_quote(item, [{"date": "2026-10-28", "value": 219.0}])["state"], "matched_completed")

    def test_legacy_cache_does_not_promote_intraday_bar_overnight(self):
        cache = {"fetched_at": "2026-10-28T04:00:00Z", "points": [{"date": "2026-10-27", "value": 220.0}, {"date": "2026-10-28", "value": 219.0}]}
        self.assertEqual(cached_completed_points(cache), cache["points"][:1])

    def test_cache_completed_watermark_is_enforced(self):
        cache = {"schema_version": 2, "completed_through": "2026-10-27", "fetched_at": "2026-10-29T02:00:00Z", "points": [{"date": "2026-10-27", "value": 220.0}, {"date": "2026-10-28", "value": 219.0}]}
        self.assertEqual(cached_completed_points(cache), cache["points"][:1])

    def test_quarantine_does_not_reappear_from_archive(self):
        bad = {"date": "2026-10-24", "value": 219.0, "source_kind": "Official SET latest close"}
        archive = {"prices": {"mai": {"chart_symbol": "SET:MAI", "points": [bad]}}, "corrected_snapshots": [{"symbol": "mai", "original_point": bad}]}
        self.assertEqual(merge_history({}, archive)["price_histories_v04"]["mai"]["points"], [])
        replacement = {**bad, "source_kind": "TradingView daily SET Index history"}
        payload = {"price_histories_v04": {"mai": {"chart_symbol": "SET:MAI", "points": [replacement]}}}
        self.assertEqual(merge_history(payload, archive)["price_histories_v04"]["mai"]["points"], [replacement])

    def test_cleanup_keeps_honest_session_disclosure(self):
        series = {"SET": {"market_session_date": "2026-10-28", "note": "Quote session unresolved; official quote is separate."}, "mai": {"history_fetch_mode": "cache", "note": "History lag; quote is separate."}}
        before = json.loads(json.dumps(series))
        clean_price_series(series)
        self.assertEqual(series, before)

    def test_finalizer_preserves_official_quote_and_updates_history_endpoints(self):
        points = [{"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "value": 200.0} for i in range(252)]
        payload = {"indices": [{"symbol": symbol, "as_of": "2026-10-29 09:00:00 Bangkok", "metrics": {"latest": 219.0}} for symbol in ("SET", "mai")], "price_histories_v04": {symbol: {"points": list(points)} for symbol in ("SET", "mai")}}
        helper = SimpleNamespace(compute_price_metrics=mai_refresh.compute_price_metrics)
        enrich_thailand(payload, helper)
        for item in payload["indices"]:
            self.assertEqual(item["metrics"]["latest"], 219.0)
            self.assertEqual(item["history_latest"], 200.0)
            self.assertEqual(item["history_as_of"], points[-1]["date"])

    def test_official_final_extension_is_not_independent_tv_crosscheck(self):
        item = {"quote_session_date": "2026-10-28", "quote_is_final": True, "metrics": {"latest": 219.0}}
        points = merge_latest_snapshot(item, {"points": [{"date": "2026-10-27", "value": 220.0}]})
        status = apply_reconciliation(item, points)
        self.assertEqual(status["state"], "official_completed_extension")
        self.assertEqual(item["history_as_of"], "2026-10-28")

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
