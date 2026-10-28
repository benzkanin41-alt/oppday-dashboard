from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

import release_store as store
import server
from scripts import build_static_site as static
from scripts import release_snapshot as release


class ReleaseSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        work = self.root / ".oppday-work"
        for name, value in {
            "ROOT": self.root, "WORK": work, "RELEASES": work / "releases",
            "CURRENT": work / "releases/current.json", "PROFILE": work / "profile.json",
        }.items():
            patcher = mock.patch.object(store, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(release, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.source = self.root / "source"
        self.source.mkdir()
        self.old = self.make_item("1" * 40, "OLD", "2Q69", "old-run", "1")
        self.new = self.make_item("2" * 40, "NEW", "3Q69", "new-run", "2")
        self.pending = self.make_item("3" * 40, "WAIT", "3Q69", "files-only", "3")
        self.docs = self.root / "docs/data"
        (self.docs / "items").mkdir(parents=True)
        static.write_json(self.docs / "index.json", {
            "updatedAt": "2026-09-05T00:00:00", "stats": {},
            "items": [static.public_item(self.old)],
        })
        self.old_payload = json.dumps({"item": {**static.public_item(self.old), "markdown": "# OLD\nReviewed conclusion"}}, separators=(",", ":")).encode()
        (self.docs / "items" / f"{self.old['id']}.json").write_bytes(self.old_payload)
        patcher = mock.patch.object(server, "build_index", return_value={"items": [self.old, self.new, self.pending]})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(server, "read_workflow_status", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(server, "find_workflow_row", return_value=self.status_row(self.new))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.real_verify_run_provenance = release.verify_run_provenance
        patcher = mock.patch.object(release, "verify_run_provenance", return_value={"pass": True})
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_item(self, item_id, symbol, quarter, run_id, registration):
        path = self.source / f"{symbol}.md"
        path.write_text(f"# {symbol}\nReviewed conclusion", encoding="utf-8")
        entry = server.file_payload(path)
        return {
            "id": item_id, "symbol": symbol, "quarter": quarter, "period": quarter,
            "eventDate": "2026-10-14", "source": quarter, "sourceFolder": str(self.source),
            "title": symbol, "files": [entry], "searchText": symbol.lower(),
            "hasMarkdown": True, "hasPdf": False, "latestModified": "2026-10-14T00:00:00",
            "primaryMarkdownId": entry["id"], "primaryPdfId": None,
            "workflowStatus": "done", "runId": run_id, "registrationId": registration,
        }

    def status_row(self, item):
        path = item["files"][0]["path"]
        digest = store.sha256(Path(path))
        row = {"hash_status": "pass", "valuation_status": "done_3_files"}
        for kind in ("conclusion", "transcript", "presentation"):
            row[kind + "_source_path"] = path
            row[kind + "_target_path"] = path
            row[kind + "_sha256_source"] = digest
        return row

    def prepare(self):
        return release.prepare_release("release-1", run_id="new-run", registrations=["2"])

    def test_release_preserves_history_and_excludes_unrequested_files_only(self):
        result = self.prepare()
        self.assertEqual(result["items"], 2)
        directory = store.release_directory("release-1")
        self.assertEqual((directory / "public/data/items" / f"{self.old['id']}.json").read_bytes(), self.old_payload)
        index = store.read_json(directory / "public/data/index.json")
        self.assertEqual({item["symbol"] for item in index["items"]}, {"OLD", "NEW"})
        self.assertFalse(store.CURRENT.exists())

    def test_source_changes_do_not_change_published_text_or_files(self):
        result = self.prepare()
        proof = {**result, "commit": "verified-commit"}
        release.promote_release("release-1", proof)
        Path(self.new["files"][0]["path"]).write_text("changed after publication", encoding="utf-8")
        cache = store.current_cache()
        payload = store.item_from_cache(cache, self.new["id"])
        self.assertIn("Reviewed conclusion", payload["item"]["markdown"])
        blob = Path(cache["by_item_id"][self.new["id"]]["files"][0]["path"])
        self.assertIn("Reviewed conclusion", blob.read_text(encoding="utf-8"))

    def test_online_failure_cannot_promote_or_replace_current(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "Online byte verification"):
            release.promote_release("release-1", {"ok": False})
        self.assertFalse(store.CURRENT.exists())

    def test_manifest_set_mismatch_stops_before_export(self):
        with self.assertRaisesRegex(ValueError, "selection mismatch"):
            release.prepare_release("release-1", run_id="new-run", registrations=["2", "missing"])
        self.assertFalse((store.RELEASES / "release-1").exists())

    def test_unavailable_source_never_erases_accepted_history(self):
        Path(self.old["files"][0]["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "unavailable files"):
            self.prepare()
        self.assertEqual((self.docs / "items" / f"{self.old['id']}.json").read_bytes(), self.old_payload)

    def test_corrupt_payload_fails_verification(self):
        self.prepare()
        path = store.release_directory("release-1") / "public/data/items" / f"{self.new['id']}.json"
        payload = store.read_json(path)
        payload["item"]["markdown"] = "tampered"
        static.write_json(path, payload)
        with self.assertRaisesRegex(ValueError, "Payload hash"):
            release.verify_release("release-1")

    def test_repeat_prepare_is_idempotent_and_rejects_different_selection(self):
        first = self.prepare()
        self.assertEqual(first, self.prepare())
        with self.assertRaisesRegex(ValueError, "selection"):
            release.prepare_release("release-1", run_id="another-run", registrations=["2"])

    def test_csv_hashes_without_original_run_qa_cannot_publish(self):
        store.write_json_atomic(store.PROFILE, {"runRoot": str(self.root / "missing-control")})
        with mock.patch.object(release, "verify_run_provenance", side_effect=self.real_verify_run_provenance):
            with self.assertRaisesRegex(ValueError, "manifest/QA evidence is missing"):
                self.prepare()
        self.assertFalse((store.RELEASES / "release-1").exists())

    def test_same_size_edit_between_qa_and_freeze_is_rejected(self):
        path = Path(self.new["files"][0]["path"])
        def changed_after_qa(*args):
            path.write_text(path.read_text(encoding="utf-8").replace("Reviewed", "Tampered"), encoding="utf-8")
            return {"pass": True}
        with (
            mock.patch.object(release, "verify_run_provenance", side_effect=changed_after_qa),
            mock.patch.object(server, "find_workflow_row", return_value=self.status_row(self.old)),
        ):
            with self.assertRaisesRegex(ValueError, "bytes changed after QA"):
                self.prepare()
        self.assertFalse((store.RELEASES / "release-1").exists())

    def provenance_fixture(self):
        run_root = self.root / "control"
        run_dir = run_root / "runs/new-run"
        final = run_dir / "staging_final/2026-10-14/NEW"
        final.mkdir(parents=True)
        accepted_md = final / "NEW-Earning call-3Q69.md"
        accepted_md.write_bytes(Path(self.new["files"][0]["path"]).read_bytes())
        accepted_pdf = final / "NEW-Earning call-3Q69.pdf"
        accepted_pdf.write_bytes(b"%PDF-fixture")
        scanned_pdf = self.source / "NEW.pdf"
        scanned_pdf.write_bytes(accepted_pdf.read_bytes())
        self.new["files"].append(server.file_payload(scanned_pdf))
        store.write_json_atomic(store.PROFILE, {"runRoot": str(run_root), "valuationMap": str(run_root / "config/map.csv")})
        store.write_json_atomic(run_dir / "run_manifest.json", {"run_id": "new-run", "items": [{"registration_id": "2", "ticker": "NEW", "event_date": "2026-10-14"}]})
        store.write_json_atomic(final / "agent6_handoff.json", {
            "run_id": "new-run", "registration_id": "2",
            "outputs": {"conclusion_md": str(accepted_md), "conclusion_pdf": str(accepted_pdf)},
            "output_sha256": {"conclusion_md": store.sha256(accepted_md), "conclusion_pdf": store.sha256(accepted_pdf)},
        })
        return {
            "publishing": SimpleNamespace(verify_run=lambda **kwargs: {"pass": True}),
            "workflow_common": SimpleNamespace(parse_quarter=lambda value: SimpleNamespace(label=value)),
        }

    def test_dashboard_markdown_must_match_exact_accepted_agent6_artifact(self):
        modules = self.provenance_fixture()
        Path(self.new["files"][0]["path"]).write_text("unreviewed replacement", encoding="utf-8")
        with mock.patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(ValueError, "exact accepted Agent6 output"):
                self.real_verify_run_provenance("new-run", [self.new])

    def test_matching_agent6_summary_set_passes_provenance_binding(self):
        with mock.patch.dict(sys.modules, self.provenance_fixture()):
            self.assertTrue(self.real_verify_run_provenance("new-run", [self.new])["pass"])

    def test_verified_blob_render_ignores_stale_metadata_text_cache(self):
        with mock.patch.object(static, "cached_text", return_value="stale text"):
            self.prepare()
        payload = store.read_json(store.release_directory("release-1") / "public/data/items" / f"{self.new['id']}.json")
        self.assertIn("Reviewed conclusion", payload["item"]["markdown"])

    def test_modified_local_index_does_not_replace_verified_cache(self):
        result = self.prepare()
        release.promote_release("release-1", {**result, "commit": "verified"})
        old_cache = copy.deepcopy(server.cache)
        try:
            server.refresh_cache()
            path = store.release_directory("release-1") / "index.local.json"
            payload = store.read_json(path)
            payload["items"].append(self.pending)
            static.write_json(path, payload)
            response = server.refresh_cache()
            self.assertIn("warning", response)
            self.assertEqual({item["symbol"] for item in server.cache["items"]}, {"OLD", "NEW"})
            with self.assertRaisesRegex(ValueError, "Local release index failed"):
                store.current_cache()
        finally:
            server.cache.clear()
            server.cache.update(old_cache)

    def test_docx_snapshot_keeps_original_document_title(self):
        path = self.source / "original-name.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Reviewed body</w:t></w:r></w:p></w:body></w:document>')
        entry = server.file_payload(path)
        entry["path"] = str(release._copy_blob(path))
        text = release.frozen_text_loader({"files": [entry]})(Path(entry["path"]))
        self.assertTrue(text.startswith("# original-name\n"))

    def test_lost_profile_keeps_active_snapshot_mode(self):
        result = self.prepare()
        release.promote_release("release-1", {**result, "commit": "verified"})
        self.assertFalse(store.PROFILE.exists())
        self.assertTrue(store.snapshot_mode())

    def test_bootstrap_cannot_replace_an_online_verified_release(self):
        result = self.prepare()
        release.promote_release("release-1", {**result, "commit": "verified"})
        with self.assertRaisesRegex(ValueError, "published release"):
            release.promote_release("release-1", {"baselineVerified": True}, bootstrap=True)

    def test_bootstrap_reconciliation_cannot_add_new_records(self):
        self.prepare()
        release.promote_release("release-1", {"baselineVerified": True}, bootstrap=True)
        with mock.patch.object(server, "find_workflow_row", return_value=self.status_row(self.pending)):
            release.prepare_release("release-2", run_id="files-only", registrations=["3"])
        with self.assertRaisesRegex(ValueError, "cannot change the accepted public dataset"):
            release.promote_release("release-2", {"baselineVerified": True}, bootstrap=True)
        self.assertEqual(store.current_pointer()["releaseId"], "release-1")

    def test_lock_prevents_concurrent_release_writer(self):
        with release.release_lock():
            with self.assertRaisesRegex(RuntimeError, "Another OPPDAY release"):
                with release.release_lock():
                    self.fail("must not enter a second release writer")

    def test_old_caller_refresh_reads_release_without_discovering_sources(self):
        result = self.prepare()
        release.promote_release("release-1", {**result, "commit": "verified-commit"})
        store.write_json_atomic(store.PROFILE, {"releaseMode": "snapshot"})
        old_cache = copy.deepcopy(server.cache)
        try:
            with mock.patch.object(server, "build_index", side_effect=AssertionError("source scan forbidden")):
                server.refresh_cache()
                server.ensure_cache()
                payload = server.index_payload()
            self.assertEqual(payload["releaseId"], "release-1")
            self.assertEqual(payload["stats"]["items"], 2)
        finally:
            server.cache.clear()
            server.cache.update(old_cache)


if __name__ == "__main__":
    unittest.main()
