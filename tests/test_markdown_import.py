from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import release_store as store
import server
from scripts import build_static_site as static
from scripts import markdown_import as importer
from scripts import release_snapshot as release


class MarkdownImportTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.work = self.root / ".oppday-work"
        self.sources = self.root / "canonical"
        for key, value in {
            "ROOT": self.root, "WORK": self.work, "RELEASES": self.work / "releases",
            "CURRENT": self.work / "releases/current.json", "PROFILE": self.work / "profile.json",
        }.items():
            self.stack.enter_context(mock.patch.object(store, key, value))
        self.stack.enter_context(mock.patch.object(release, "ROOT", self.root))
        store.write_json_atomic(store.PROFILE, {"oppdayRoot": str(self.sources)})
        self.old = self.make_item("OLD", "2Q69")
        self.kept = self.make_item("KEEP", "3Q69")
        self.new = self.make_item("NEW", "3Q69")
        self.baseline = store.RELEASES / "baseline"
        for directory in (self.baseline / "public/data/items", self.root / "docs/data/items"):
            directory.mkdir(parents=True)
        old_items = [self.old, self.kept]
        public = {"items": [static.public_item(item) for item in old_items], "stats": {"items": 2}}
        store.write_json_atomic(self.baseline / "public/data/index.json", public)
        store.write_json_atomic(self.baseline / "index.local.json", {"items": old_items})
        store.write_json_atomic(store.CURRENT, {"releaseId": "baseline",
                                               "indexSha256": store.sha256(self.baseline / "public/data/index.json")})
        for item in old_items:
            text = Path(item["files"][0]["path"]).read_text(encoding="utf-8")
            static.write_json(self.baseline / "public/data/items" / f"{item['id']}.json",
                              {"item": {**static.public_item(item), "markdown": text}})
        self.stack.enter_context(mock.patch.object(server, "build_index", return_value={"items": old_items + [self.new]}))
        self.producer = self.stack.enter_context(mock.patch.object(release, "verify_run_provenance",
                                                                 side_effect=AssertionError("Not a production run")))
        self.import_id = "md-only"
        self.authorization = {"action": importer.ACTION, "importId": self.import_id, "quarter": "3Q69",
                              "preserveOriginals": True, "preserveHistory": True,
                              "userRequest": "Import existing Earning call Markdown without PDF QA"}

    def make_item(self, ticker, quarter):
        root = self.sources / quarter / "Oppday" / server.SUMMARY_DIR_NAME
        path = root / "2026-10-27" / f"{ticker}-Earning call-{quarter}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {ticker} Earning call {quarter}\n\nExisting source text", encoding="utf-8")
        groups = {}
        server.add_group(groups, server.detect_current_file(path, quarter, root), path)
        item = next(iter(groups.values()))
        item.update(primaryMarkdownId=item["files"][0]["id"], primaryPdfId=None)
        return item

    def request(self):
        return importer.create_request(self.import_id, "3Q69", self.authorization)

    def prepare(self):
        self.request()
        return release.prepare_release("md-release", markdown_import_id=self.import_id)

    def test_nested_event_is_distinct_and_bound_to_registration(self):
        root = importer.summary_root('3Q69')
        path = root / '2026-11-16' / 'KEEP' / '2026-11-16-11984-C-Sign' / 'KEEP-Earning call-3Q69.md'
        path.parent.mkdir(parents=True)
        path.write_text('# KEEP Earning call 3Q69\nSET registration 11984\n', encoding='utf-8')
        job = self.request()
        event = next(e for e in job['entries'] if e['originalPath'] == str(path))
        self.assertEqual(event['eventDate'], '2026-11-16')
        self.assertNotEqual(event['itemId'], self.kept['id'])
        self.assertEqual(event['disposition'], 'add')
        importer.load_request(self.import_id)
        path.write_text('# KEEP Earning call 3Q69\nSET registration 999\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'registration differs'):
            importer.load_request(self.import_id)

    def test_same_ticker_and_date_events_have_distinct_bound_ids(self):
        path = importer.summary_root('3Q69') / '2026-10-27' / 'NEW' / '2026-10-27-123-C-Sign' / 'NEW-Earning call-3Q69.md'
        path.parent.mkdir(parents=True)
        path.write_text('# NEW Earning call 3Q69\nSET registration 123\n', encoding='utf-8')
        standard = Path(self.new['files'][0]['path'])
        standard.write_text('# NEW Earning call 3Q69\nSET registration 122\n', encoding='utf-8')
        status = importer.summary_root('3Q69').parent / 'workflow_status_3Q69.csv'
        status.write_text('ticker,event_date,registration_id,run_id,conclusion_status\n'
                          'NEW,2026-10-27,122,run-a,done\nNEW,2026-10-27,123,run-b,done\n', encoding='utf-8')
        job = self.request()
        entries = [e for e in job['entries'] if e['ticker'] == 'NEW']
        self.assertEqual(len(entries), 2)
        plain = next(e for e in entries if e['originalPath'] == str(standard))
        nested = next(e for e in entries if e['originalPath'] == str(path))
        self.assertEqual(plain['itemId'], self.new['id'])
        self.assertEqual((plain['registrationId'], plain['runId']), ('122', 'run-a'))
        self.assertEqual((nested['registrationId'], nested['runId']), ('123', 'run-b'))
        self.assertNotEqual(plain['itemId'], nested['itemId'])
        self.assertEqual(nested['identityScheme'], 'event-registration-v1')
        selected = importer.select_items(self.import_id)
        self.assertEqual({i['id'] for i in selected}, {e['itemId'] for e in entries})
        importer.verify_import(self.import_id, selected)
        job_path = importer.import_directory(self.import_id) / 'import.json'
        original = job_path.read_bytes()
        for field, value in [('registrationId', '999'), ('runId', 'wrong'), ('workflowStatus', 'wrong')]:
            changed = store.read_json(job_path)
            legacy = next(e for e in changed['entries'] if e['itemId'] == plain['itemId'])
            legacy[field] = value
            store.write_json_atomic(job_path, changed)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'workflow evidence differs'):
                importer.load_request(self.import_id)
            job_path.write_bytes(original)
        status.write_text(status.read_text(encoding='utf-8') + 'NEW,2026-10-27,122,run-a,done\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'workflow status differs or is ambiguous'):
            importer.load_request(self.import_id)
        # A previously verified immutable release can still be checked after CSV drift.
        importer.verify_import(self.import_id, selected, require_complete_inventory=False)

    def test_same_day_events_with_missing_workflow_registration_block(self):
        path = importer.summary_root('3Q69') / '2026-10-27' / 'NEW' / '2026-10-27-123-C-Sign' / 'NEW-Earning call-3Q69.md'
        path.parent.mkdir(parents=True)
        path.write_text('# NEW Earning call 3Q69\nSET registration 123\n', encoding='utf-8')
        Path(self.new['files'][0]['path']).write_text('# NEW Earning call 3Q69\nSET registration 122\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'missing or ambiguous workflow status'):
            self.request()

    def test_previously_accepted_nested_event_keeps_its_id_when_standard_arrives(self):
        root = importer.summary_root('3Q69')
        standard = Path(self.new['files'][0]['path'])
        standard.unlink()
        nested = root / '2026-10-27' / 'NEW' / '2026-10-27-123-C-Sign' / 'NEW-Earning call-3Q69.md'
        nested.parent.mkdir(parents=True)
        nested.write_text('# NEW Earning call 3Q69\nSET registration 123\n', encoding='utf-8')
        self.prepare()
        release_path = store.release_directory('md-release')
        store.write_json_atomic(store.CURRENT, {'releaseId': 'md-release',
            'indexSha256': store.sha256(release_path / 'public/data/index.json')})
        standard.write_text('# NEW Earning call 3Q69\nSET registration 122\n', encoding='utf-8')
        status = root.parent / 'workflow_status_3Q69.csv'
        status.write_text('ticker,event_date,registration_id,run_id,conclusion_status\n'
                          'NEW,2026-10-27,122,run-a,done\nNEW,2026-10-27,123,run-b,done\n', encoding='utf-8')
        next_id = 'next-same-day'
        job = importer.create_request(next_id, '3Q69', {**self.authorization, 'importId': next_id})
        old = next(e for e in job['entries'] if e['originalPath'] == str(nested))
        new = next(e for e in job['entries'] if e['originalPath'] == str(standard))
        self.assertEqual((old['itemId'], old['disposition']), (self.new['id'], 'preserve_existing'))
        self.assertEqual(new['identityScheme'], 'event-registration-v1')
        self.assertNotEqual(new['itemId'], old['itemId'])
        selected = importer.select_items(next_id)
        self.assertEqual([i['id'] for i in selected], [new['itemId']])

    def test_md_import_needs_no_pdf_producer_manifest_or_status_qa(self):
        Path(self.new["files"][0]["path"]).with_suffix(".pdf").write_bytes(b"not a PDF")
        old_bytes = (self.baseline / "public/data/items" / f"{self.kept['id']}.json").read_bytes()
        result = self.prepare()
        directory = store.release_directory("md-release")
        self.assertEqual(result["items"], 3)
        self.assertEqual((directory / "public/data/items" / f"{self.kept['id']}.json").read_bytes(), old_bytes)
        item = store.read_json(directory / "public/data/items" / f"{self.new['id']}.json")["item"]
        self.assertEqual([entry["extension"] for entry in item["files"]], [".md"])
        self.assertFalse(item["hasPdf"])
        self.producer.assert_not_called()
        self.assertFalse((directory / "deployment.json").exists())
        self.assertEqual(store.current_pointer()["releaseId"], "baseline")
        release.verify_release_admission("md-release")

    def test_existing_changed_markdown_is_never_overwritten(self):
        path = Path(self.kept["files"][0]["path"])
        path.write_text(path.read_text(encoding="utf-8") + " changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "history cannot be overwritten"):
            self.request()
        self.assertFalse(importer.import_directory(self.import_id).exists())

    def make_alias(self):
        source = Path(self.new['files'][0]['path'])
        alias = source.with_name('NEW custom summary.md')
        source.rename(alias)
        primary = alias.parent.parent.parent / alias.parent.name / 'NEW' / alias.name
        primary.parent.mkdir(parents=True)
        primary.write_bytes(alias.read_bytes())
        entry = {'ticker': 'NEW', 'eventDate': alias.parent.name,
                 'filename': alias.name, 'sha256': store.sha256(alias)}
        self.authorization['sourceAliases'] = [entry]
        return alias, primary, entry

    def test_explicit_alias_preserves_original_name_bytes_and_standard_stable_id(self):
        alias, _, _ = self.make_alias()
        result = self.prepare()
        self.assertEqual(result['items'], 3)
        manifest = store.read_json(store.release_directory('md-release') / 'manifest.json')
        self.assertEqual(manifest['selectedItemIds'], [self.new['id']])
        item = store.read_json(store.release_directory('md-release') / 'public/data/items' / f"{self.new['id']}.json")['item']
        self.assertEqual(item['files'][0]['name'], alias.name)
        self.assertEqual(item['markdown'], alias.read_text(encoding='utf-8'))
        release.verify_release_admission('md-release')

    def test_scheduled_alias_status_hash_is_rechecked_without_breaking_historical_release(self):
        self.make_alias()
        status = importer.summary_root('3Q69').parent / 'workflow_status_3Q69.csv'
        status.write_text('ticker,event_date,registration_id,run_id,conclusion_status\n'
                          'NEW,2026-10-27,12034,run-a,done\n', encoding='utf-8')
        self.authorization.update(sourceAliasPolicy='3q69-scheduled-verified-youtube-autocaption-v1',
                                  sourceAliasStatusSha256=store.sha256(status))
        self.request()
        importer.load_request(self.import_id)
        status.write_text(status.read_text(encoding='utf-8') + 'NEW,2026-10-27,999,run-b,done\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'workflow status changed'):
            importer.load_request(self.import_id)
        importer.load_request(self.import_id, require_complete_inventory=False)

    def test_scheduled_alias_request_rejects_stale_status_hash_before_writing(self):
        self.make_alias()
        status = importer.summary_root('3Q69').parent / 'workflow_status_3Q69.csv'
        status.write_text('ticker,event_date,registration_id,run_id,conclusion_status\n'
                          'NEW,2026-10-27,12034,run-a,done\n', encoding='utf-8')
        self.authorization.update(sourceAliasPolicy='3q69-scheduled-verified-youtube-autocaption-v1',
                                  sourceAliasStatusSha256='a' * 64)
        with self.assertRaisesRegex(ValueError, 'workflow status changed'):
            self.request()
        self.assertFalse(importer.import_directory(self.import_id).exists())

    def test_expected_inventory_drift_blocks_before_request_directory_is_created(self):
        with self.assertRaisesRegex(ValueError, 'Source inventory changed'):
            importer.create_request(self.import_id, '3Q69', self.authorization,
                                    expected_inventory={'unexpected': 'a' * 64})
        self.assertFalse(importer.import_directory(self.import_id).exists())

    def test_alias_is_not_discovered_without_explicit_approval(self):
        self.make_alias()
        self.authorization.pop('sourceAliases')
        self.request()
        self.assertEqual(importer.select_items(self.import_id), [])

    def test_unapproved_earning_call_variant_fails_closed_with_filename(self):
        alias, primary, entry = self.make_alias()
        renamed = alias.with_name('NEW-Earning call-3Q69-YouTube-autocaption.md')
        alias.rename(renamed)
        primary.rename(primary.with_name(renamed.name))
        self.authorization.pop('sourceAliases')
        with self.assertRaisesRegex(ValueError, 'Unapproved Earning call filenames:.*NEW-Earning call-3Q69-YouTube-autocaption'):
            self.request()

    def test_nested_hash_bound_alias_checks_registration_and_pair(self):
        root = importer.summary_root('3Q69')
        event = '2026-11-18-12009-C-Sign'
        summary = root / '2026-11-18' / 'NEST' / event / 'NEST-Earning call-3Q69-YouTube-autocaption.md'
        primary = root.parent / summary.relative_to(root)
        for path in (summary, primary):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# NEST Earning call 3Q69\nทะเบียน SET 12009\n', encoding='utf-8')
        alias = {'ticker': 'NEST', 'eventDate': '2026-11-18', 'nestedEvent': event,
                 'filename': summary.name, 'sha256': store.sha256(summary)}
        self.authorization['sourceAliases'] = [alias]
        job = self.request()
        entry = next(e for e in job['entries'] if e['ticker'] == 'NEST')
        self.assertEqual(entry['originalPath'], str(summary))
        importer.load_request(self.import_id)
        with self.assertRaisesRegex(ValueError, 'registration differs'):
            wrong = root / '2026-11-18' / 'NEST' / '2026-11-18-999-C-Sign' / summary.name
            wrong.parent.mkdir(parents=True)
            wrong.write_bytes(summary.read_bytes())
            importer.source_event(wrong, '3Q69', 'NEST')
        wrong.unlink()
        primary.write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'copies differ'):
            importer.load_request(self.import_id)

    def test_nested_alias_rejects_traversal(self):
        _, _, entry = self.make_alias()
        entry['nestedEvent'] = '../outside'
        with self.assertRaisesRegex(ValueError, 'nested alias event'):
            self.request()

    def test_alias_rejects_dot_tickers(self):
        _, _, entry = self.make_alias()
        for ticker in ('.', '..'):
            entry['ticker'] = ticker
            with self.subTest(ticker=ticker), self.assertRaisesRegex(ValueError, 'identity'):
                self.request()

    def test_alias_rejects_resolved_summary_and_primary_escapes(self):
        summary, primary, entry = self.make_alias()
        original_resolve = Path.resolve
        outside = self.root / 'outside' / 'escaped.md'
        for target, message in ((summary, 'Summary alias escapes'), (primary, 'Primary alias escapes')):
            def resolve(path, *args, **kwargs):
                if path == target:
                    return outside
                return original_resolve(path, *args, **kwargs)
            with self.subTest(target=target), mock.patch.object(Path, 'resolve', resolve):
                with self.assertRaisesRegex(ValueError, message):
                    importer.verify_alias_sources('3Q69', entry)

    def test_standard_duplicate_alias_cannot_escape_its_event_or_stock(self):
        summary, primary, entry = self.make_alias()
        summary_standard = summary.with_name('NEW-Earning call-3Q69.md')
        primary_standard = primary.with_name('NEW-Earning call-3Q69.md')
        for path in (summary_standard, primary_standard):
            path.write_bytes(summary.read_bytes())
        original_resolve = Path.resolve
        outside = self.root / 'outside' / 'escaped.md'
        for target in (summary_standard, primary_standard):
            def resolve(path, *args, **kwargs):
                if path == target:
                    return outside
                return original_resolve(path, *args, **kwargs)
            with self.subTest(target=target), mock.patch.object(Path, 'resolve', resolve):
                with self.assertRaisesRegex(ValueError, 'escapes its event or stock root'):
                    importer.verify_alias_sources('3Q69', entry)

    def test_nested_alias_is_inherited_after_release(self):
        root = importer.summary_root('3Q69')
        event = '2026-11-18-12009-C-Sign'
        summary = root / '2026-11-18' / 'NEST' / event / 'NEST-Earning call-3Q69-YouTube-autocaption.md'
        primary = root.parent / summary.relative_to(root)
        for path in (summary, primary):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# NEST Earning call 3Q69\nทะเบียน SET 12009\n', encoding='utf-8')
        entry = {'ticker': 'NEST', 'eventDate': '2026-11-18', 'nestedEvent': event,
                 'filename': summary.name, 'sha256': store.sha256(summary)}
        self.authorization['sourceAliases'] = [entry]
        self.prepare()
        release_path = store.release_directory('md-release')
        store.write_json_atomic(store.CURRENT, {'releaseId': 'md-release',
            'indexSha256': store.sha256(release_path / 'public/data/index.json')})
        self.assertEqual(importer.source_aliases('3Q69'), [entry])
        auth = {**self.authorization, 'importId': 'next-nested'}
        auth.pop('sourceAliases')
        job = importer.create_request('next-nested', '3Q69', auth)
        self.assertEqual(job['sourceAliases'], [entry])
        self.assertEqual(importer.select_items('next-nested'), [])

    def test_alias_rejects_changed_primary_even_during_rollback_admission(self):
        _, primary, _ = self.make_alias()
        self.prepare()
        primary.write_bytes(primary.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'copies differ'):
            release.verify_release_admission('md-release')

    def test_alias_rejects_standard_collision_or_escaping_path(self):
        alias, _, entry = self.make_alias()
        standard = alias.with_name('NEW-Earning call-3Q69.md')
        standard.write_bytes(alias.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'copies differ'):
            self.request()
        standard.unlink()
        entry['filename'] = '../outside.md'
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.request()

    def test_identical_standard_copy_and_approved_alias_create_one_record(self):
        alias, primary, _ = self.make_alias()
        for path in (alias, primary):
            path.with_name('NEW-Earning call-3Q69.md').write_bytes(alias.read_bytes())
        self.prepare()
        manifest = store.read_json(store.release_directory('md-release') / 'manifest.json')
        self.assertEqual(manifest['selectedItemIds'], [self.new['id']])
        release.verify_release_admission('md-release')

    def test_accepted_alias_is_inherited_for_later_refresh_without_duplicate(self):
        _, _, entry = self.make_alias()
        self.prepare()
        store.write_json_atomic(store.CURRENT, {'releaseId': 'md-release',
            'indexSha256': store.sha256(store.release_directory('md-release') / 'public/data/index.json')})
        self.assertEqual(importer.source_aliases('3Q69'), [entry])
        auth = {**self.authorization, 'importId': 'next'}
        auth.pop('sourceAliases')
        job = importer.create_request('next', '3Q69', auth)
        self.assertEqual(job['sourceAliases'], [entry])
        self.assertEqual(importer.select_items('next'), [])

    def test_changed_original_hash_blocks_import(self):
        self.request()
        path = Path(self.new["files"][0]["path"])
        path.write_text(path.read_text(encoding="utf-8") + " changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            importer.select_items(self.import_id)

    def test_noncanonical_source_cannot_substitute_same_bytes(self):
        self.request()
        job_path = importer.import_directory(self.import_id) / "import.json"
        job = store.read_json(job_path)
        job["entries"][0]["originalPath"] = str(self.root / "elsewhere.md")
        store.write_json_atomic(job_path, job)
        with self.assertRaises(ValueError):
            importer.select_items(self.import_id)

    def test_wrong_heading_or_invalid_utf8_rejected(self):
        path = Path(self.new["files"][0]["path"])
        for data in (b"# WRONG Earning call 3Q69\nBody", b"\xff\xfe", b"", b"# NEW Earning call 3Q69\n\x00"):
            with self.subTest(data=data):
                path.write_bytes(data)
                with self.assertRaises((ValueError, IndexError)):
                    self.request()

    def test_added_or_removed_md_requires_new_complete_inventory(self):
        self.request()
        extra = self.make_item("EXTRA", "3Q69")
        with self.assertRaisesRegex(ValueError, "cohort changed"):
            importer.select_items(self.import_id)
        Path(extra["files"][0]["path"]).unlink()
        Path(self.new["files"][0]["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "cohort changed"):
            importer.select_items(self.import_id)

    def test_later_arrivals_do_not_invalidate_a_prepared_release_or_its_recovery(self):
        self.prepare()
        extra = self.make_item("LATER", "3Q69")
        release.verify_release_admission("md-release")
        manifest = store.read_json(store.release_directory("md-release") / "manifest.json")
        self.assertNotIn(extra["id"], manifest["selectedItemIds"])
        with self.assertRaisesRegex(ValueError, "cohort changed"):
            importer.select_items(self.import_id)

    def test_prepared_release_still_rejects_changed_or_missing_bound_sources(self):
        self.prepare()
        self.make_item("LATER", "3Q69")
        path = Path(self.new["files"][0]["path"])
        original = path.read_bytes()
        path.write_bytes(original + b"changed")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            release.verify_release_admission("md-release")
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            release.verify_release_admission("md-release")

    def test_transcripts_and_other_quarters_are_not_imported(self):
        path = Path(self.new["files"][0]["path"])
        path.with_name("NEW_transcript_3Q69.md").write_text("transcript", encoding="utf-8")
        self.make_item("FUTURE", "4Q69")
        job = self.request()
        self.assertEqual({entry["ticker"] for entry in job["entries"]}, {"NEW", "KEEP"})
        self.assertEqual([item["symbol"] for item in importer.select_items(self.import_id)], ["NEW"])

    def test_no_authorization_or_revoked_authorization_rejected(self):
        for override in ({"action": "review_then_publish_passed_only"}, {"revoked": True}, {"preserveHistory": False}):
            with self.subTest(override=override):
                with self.assertRaisesRegex(ValueError, "authorization"):
                    importer.create_request(self.import_id, "3Q69", {**self.authorization, **override})

    def test_duplicate_request_does_not_overwrite_evidence(self):
        self.request()
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.request()

    def test_import_cannot_mix_production_or_qualification_modes(self):
        for selection in ({"run_id": "new-run"}, {"qualification_id": "review"}, {"baseline_only": True}):
            with self.subTest(selection=selection):
                with self.assertRaisesRegex(ValueError, "separate explicit mode"):
                    release.prepare_release("bad", markdown_import_id=self.import_id, **selection)

    def test_pdf_or_changed_selected_file_cannot_enter_md_mode(self):
        self.request()
        for kind in ("pdf", "hash", "identity"):
            with self.subTest(kind=kind):
                items = importer.select_items(self.import_id)
                if kind == "pdf":
                    items[0]["hasPdf"] = True
                elif kind == "hash":
                    substitute = self.root / "substitute.md"
                    substitute.write_text("other", encoding="utf-8")
                    items[0]["files"][0]["path"] = str(substitute)
                else:
                    items[0]["registrationId"] = "invented"
                with self.assertRaises(ValueError):
                    importer.verify_import(self.import_id, items)

    def test_prepared_export_and_promotion_recheck_authorization(self):
        result = self.prepare()
        path = importer.import_directory(self.import_id) / "authorization.json"
        store.write_json_atomic(path, {**self.authorization, "revoked": True})
        for action in (lambda: release.export_release("md-release"),
                       lambda: release.promote_release("md-release", {**result, "commit": "verified"})):
            with self.subTest(action=action):
                with self.assertRaisesRegex(ValueError, "authorization"):
                    action()
        self.assertEqual(store.current_pointer()["releaseId"], "baseline")

    def test_changed_request_evidence_requires_new_release_id(self):
        self.prepare()
        path = importer.import_directory(self.import_id) / "authorization.json"
        store.write_json_atomic(path, {**self.authorization, "userRequest": "Different authorization"})
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            release.prepare_release("md-release", markdown_import_id=self.import_id)
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            release.verify_release_admission("md-release")

    def test_prepared_history_mutation_is_rejected(self):
        self.prepare()
        path = store.release_directory("md-release") / "public/data/items" / f"{self.kept['id']}.json"
        payload = store.read_json(path)
        payload["item"]["markdown"] += " historical change"
        static.write_json(path, payload)
        with self.assertRaisesRegex(ValueError, "historical payload"):
            release.verify_release_admission("md-release")

    def test_import_cannot_claim_semantic_or_pdf_success(self):
        self.request()
        path = importer.import_directory(self.import_id) / "import.json"
        job = store.read_json(path)
        job["semanticValidation"] = "pass"
        store.write_json_atomic(path, job)
        with self.assertRaisesRegex(ValueError, "cannot claim"):
            importer.select_items(self.import_id)

    def test_normal_production_still_requires_its_qa(self):
        self.new.update(runId="new-run", registrationId="2")
        self.producer.side_effect = ValueError("Original production QA required")
        with self.assertRaisesRegex(ValueError, "production QA required"):
            release.prepare_release("production", run_id="new-run", registrations=["2"])


if __name__ == "__main__":
    unittest.main()
