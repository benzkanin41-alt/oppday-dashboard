from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server
from scripts import build_static_site
from scripts import sync_static_site


class MultiQuarterIndexTests(unittest.TestCase):
    def test_completed_statuses_and_manifest_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "OPPDAY"
            summary = root / "2Q69" / "Oppday" / server.SUMMARY_DIR_NAME / "2026-07-20"
            summary.mkdir(parents=True)
            (summary / "KSL-Earning call-2Q69.md").write_text("# KSL", encoding="utf-8")
            (summary / "KSL-Earning call-2Q69.pdf").write_bytes(b"%PDF-1.4\n")
            (summary / "WAIT-Earning call-2Q69.md").write_text("# WAIT", encoding="utf-8")
            status = root / "2Q69" / "Oppday" / "workflow_status_2Q69.csv"
            status.write_text(
                "run_id,registration_id,ticker,event_date,conclusion_status\n"
                "RUN-001,1001,KSL,2026-07-20,done_transcript_only\n"
                "RUN-001,1002,WAIT,2026-07-20,pending\n",
                encoding="utf-8",
            )

            q3 = root / "3Q69" / "Oppday" / server.SUMMARY_DIR_NAME / "2026-10-01"
            q3.mkdir(parents=True)
            (q3 / "GULF-Earning call-3Q69.md").write_text("# GULF", encoding="utf-8")
            (root / "3Q69" / "Oppday" / "workflow_status_3Q69.csv").write_text(
                "run_id,registration_id,ticker,event_date,conclusion_status\n"
                "RUN-002,2001,GULF,2026-10-01,done\n",
                encoding="utf-8",
            )

            legacy = root / "1Q69" / "Oppday" / server.SUMMARY_DIR_NAME / "2026-05-01"
            legacy.mkdir(parents=True)
            (legacy / "LEGACY-Earning call-1Q69.md").write_text("# LEGACY", encoding="utf-8")

            built = server.build_index(root, root / "PAST")
            symbols = {item["symbol"] for item in built["items"]}
            self.assertEqual(symbols, {"KSL", "GULF", "LEGACY"})
            ksl = next(item for item in built["items"] if item["symbol"] == "KSL")
            self.assertEqual(ksl["workflowStatus"], "done_transcript_only")
            self.assertEqual(ksl["runId"], "RUN-001")
            self.assertEqual(built["stats"]["sources"], ["3Q69", "2Q69", "1Q69"])

            with server.cache_lock:
                snapshot = dict(server.cache)
                server.cache.clear()
                server.cache.update(built)
            try:
                payload = server.index_payload(
                    {"run_id": ["RUN-001"], "manifest_tickers": ["KSL"]}
                )
                self.assertTrue(payload["manifestCheck"]["matches"])
                self.assertEqual(payload["stats"]["tickerSet"], ["KSL"])
                mismatch = server.index_payload(
                    {"run_id": ["RUN-001"], "manifest_tickers": ["KSL,WAIT"]}
                )
                self.assertFalse(mismatch["manifestCheck"]["matches"])
                self.assertEqual(mismatch["manifestCheck"]["missing"], ["WAIT"])
            finally:
                with server.cache_lock:
                    server.cache.clear()
                    server.cache.update(snapshot)


    def test_legacy_conclusion_done_status_remains_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "OPPDAY"
            summary = root / "1Q69" / "Oppday" / server.SUMMARY_DIR_NAME / "2026-05-25"
            summary.mkdir(parents=True)
            (summary / "SIS-Earning call-1Q69.md").write_text("# SIS", encoding="utf-8")
            (root / "1Q69" / "Oppday" / "workflow_status_1Q69.csv").write_text(
                "oppday_date,ticker,registration_id,conclusion_status\n"
                "2026-05-25,SIS,10868,conclusion_done\n",
                encoding="utf-8",
            )
            built = server.build_index(root, root / "PAST")
            self.assertEqual([item["symbol"] for item in built["items"]], ["SIS"])
            self.assertEqual(built["items"][0]["workflowStatus"], "conclusion_done")


class SafeStaticBuildTests(unittest.TestCase):
    def test_local_path_redaction_supports_backslash_and_forward_slash(self) -> None:
        source = "A C:\\private\\report.md\nB C:/private/report.md"
        self.assertEqual(
            build_static_site.redact_local_paths(source),
            "A [local path removed]\nB [local path removed]",
        )

    def test_bubble_dashboard_sentinel_survives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs = root / "docs"
            web = root / "web"
            sentinel = docs / "bubble-risk-dashboard" / "sentinel.txt"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text("preserve-me", encoding="utf-8")
            stale = docs / "data" / "items" / ("a" * 40 + ".json")
            stale.parent.mkdir(parents=True)
            stale.write_text("{}", encoding="utf-8")
            protected = [
                docs / "data" / "items" / "secret.txt",
                docs / "data" / "items" / ".env",
                docs / "data" / "items" / "secret.json",
                docs / "data" / "items" / "nested" / ("b" * 40 + ".json"),
            ]
            for path in protected:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("preserve-me", encoding="utf-8")
            web.mkdir()
            (web / "index.html").write_text("<!doctype html>", encoding="utf-8")
            (web / "app.js").write_text("const ok = true;", encoding="utf-8")
            (web / "styles.css").write_text("body{}", encoding="utf-8")
            built = {
                "items": [],
                "updated_at": "2026-07-20T12:00:00",
                "stats": {
                    "items": 0,
                    "symbols": 0,
                    "quarters": [],
                    "sources": [],
                    "tickerSet": [],
                    "markdownItems": 0,
                    "pdfItems": 0,
                    "currentRoots": [r"D:\\private"],
                    "workflowStatusFiles": [r"D:\\private\\workflow.csv"],
                },
            }
            with (
                mock.patch.object(build_static_site, "ROOT", root),
                mock.patch.object(build_static_site, "DOCS", docs),
                mock.patch.object(build_static_site, "WEB", web),
                mock.patch.object(build_static_site, "CACHE", root / ".cache"),
                mock.patch.object(build_static_site.server, "build_index", return_value=built),
            ):
                result = build_static_site.build()
            self.assertEqual(result["items"], 0)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve-me")
            self.assertFalse(stale.exists())
            for path in protected:
                self.assertEqual(path.read_text(encoding="utf-8"), "preserve-me")
            payload = json.loads((docs / "data" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["items"], [])
            self.assertNotIn("currentRoots", payload["stats"])
            self.assertNotIn("workflowStatusFiles", payload["stats"])

    def test_git_add_chunks_thousands_of_exact_paths(self) -> None:
        paths = [
            f"docs/data/items/{index:040x}.json"
            for index in range(3_000)
        ]
        chunks = sync_static_site.git_add_chunks(paths, max_command_chars=16_000)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(
            [path for chunk in chunks for path in chunk],
            sorted(paths),
        )
        for chunk in chunks:
            command = ["git", "add", "--", *chunk]
            self.assertLessEqual(
                len(sync_static_site.subprocess.list2cmdline(command)),
                16_000,
            )
        with self.assertRaises(ValueError):
            sync_static_site.git_add_chunks([paths[0]], max_command_chars=10)


    def test_publish_allowlist_rejects_cohosted_and_untracked_files(self) -> None:
        item_id = "a" * 40
        generated = f"docs/data/items/{item_id}.json"
        item_allowlist = {generated}
        self.assertTrue(sync_static_site.is_generated_path(generated, item_allowlist))
        self.assertTrue(sync_static_site.is_generated_path("docs/static/app.js", item_allowlist))
        self.assertFalse(
            sync_static_site.is_generated_path("docs/bubble-risk-dashboard/index.html", item_allowlist)
        )
        self.assertFalse(sync_static_site.is_generated_path("server.py", item_allowlist))

        other_json = f"docs/data/items/{'b' * 40}.json"
        suspicious = {
            "docs/data/items/secret.txt",
            "docs/data/items/.env",
            f"docs/data/items/nested/{item_id}.json",
            other_json,
        }
        self.assertEqual(
            sync_static_site.unrelated_dirty_paths(suspicious, item_allowlist),
            suspicious,
        )
        self.assertFalse(sync_static_site.direct_item_id("docs/data/items/secret.txt"))
        self.assertFalse(sync_static_site.direct_item_id("docs/data/items/.env"))
        self.assertFalse(
            sync_static_site.direct_item_id(f"docs/data/items/nested/{item_id}.json")
        )

if __name__ == "__main__":
    unittest.main()
