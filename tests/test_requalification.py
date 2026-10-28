from __future__ import annotations

import copy
import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import release_store as store
from scripts import requalification as qualification


class RequalificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for field, value in {'ROOT': self.root, 'WORK': self.root / 'work', 'PROFILE': self.root / 'profile.json'}.items():
            patcher = mock.patch.object(store, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.base = store.WORK / 'requalification/current'
        self.folder = self.base / 'TEST'
        self.folder.mkdir(parents=True)
        self.original = self.root / 'delivered'
        self.valuation = self.root / 'valuation'
        store.write_json_atomic(store.PROFILE, {'oppdayRoot': str(self.original), 'valuationRoot': str(self.valuation),
                                               'valuationMap': str(self.root / 'map.csv')})
        self.authorization = {'qualificationId': 'current', 'action': 'review_then_publish_passed_only',
                              'preserveOriginals': True, 'originalProducerEvidenceReconstructed': False,
                              'tickerSet': ['TEST'], 'curatorTaskId': 'real-curator-task'}
        self.save_authorization()
        self.job = {'kind': 'existing-earning-call-current-requalification', 'qualification_id': 'current',
                    'run_id': 'original-run', 'registration_id': '22', 'ticker': 'TEST', 'quarter': '3Q69',
                    'event_date': '2026-10-27', 'created_at': '2026-10-28T05:00:00+00:00',
                    'curator_task_id': 'real-curator-task', 'historical_producer_qa_available': False,
                    'source_binding': {}}
        for role in ('conclusion_md', 'conclusion_pdf', *qualification.SOURCE_ROLES):
            extension = '.md' if role.endswith('_md') else '.pdf'
            if role.startswith('conclusion_'):
                original = self.original / '3Q69/Oppday/สรุป oppday/2026-10-27' / ('TEST-Earning call-3Q69' + extension)
            else:
                original = self.original / '3Q69/Oppday/2026-10-27/TEST' / ('TEST_' + role.removesuffix('_md').removesuffix('_pdf') + '_3Q69' + extension)
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(b"Source: https://www.youtube.com/watch?v=real-clip\n" if role == 'transcript_md' else role.encode())
            frozen = self.folder / 'sources' / original.name
            frozen.parent.mkdir(parents=True, exist_ok=True)
            frozen.write_bytes(original.read_bytes())
            self.job['source_binding'][role] = {'path': str(frozen), 'originalPath': str(original), 'sha256': store.sha256(frozen)}
        self.job['input_sha256'] = {role: self.job['source_binding'][role]['sha256'] for role in qualification.SOURCE_ROLES}
        self.job['official_presentation_sha256'] = self.job['input_sha256']['presentation_pdf']
        self.save_job()
        self.item = {'symbol': 'TEST', 'quarter': '3Q69', 'eventDate': '2026-10-27', 'runId': 'original-run',
                     'registrationId': '22', 'files': [
                         {'extension': extension, 'path': self.job['source_binding'][role]['originalPath']}
                         for extension, role in (('.md', 'conclusion_md'), ('.pdf', 'conclusion_pdf'))]}
        store.write_json_atomic(self.folder / 'official-event.json', {'id': 22, 'symbol': 'TEST', 'year': 2026, 'round': 3,
                                                                    'meeting_date': '2026-10-27T00:00:00Z',
                                                                    'video_link': 'https://www.youtube.com/embed/real-clip?'})
        store.write_json_atomic(self.folder / 'semantic_coverage.json', {'real': 'test fixture; validator is mocked only in tests'})
        store.write_json_atomic(self.folder / 'qa_coverage.json', {'real': 'test fixture'})
        self.handoff = {key: self.job[key] for key in qualification.IDENTITY}
        self.handoff.update(qualification_id='current', terminal=True, **{'pass': True},
                            author_task_id='real-curator-task', reviewer_task_id='real-reviewer-task',
                            completed_at='2026-10-28T05:10:00+00:00', input_sha256=self.job['input_sha256'],
                            markdown_sha256=self.job['source_binding']['conclusion_md']['sha256'],
                            pdf_sha256=self.job['source_binding']['conclusion_pdf']['sha256'],
                            qa_coverage_sha256=store.sha256(self.folder / 'qa_coverage.json'),
                            semantic_coverage_sha256=store.sha256(self.folder / 'semantic_coverage.json'))
        self.save_handoff()
        inspection = self.base / 'pdf-inspections/TEST'
        self.contact = inspection / 'contact.png'
        self.contact.parent.mkdir(parents=True)
        self.contact.write_bytes(b'image fixture')
        store.write_json_atomic(inspection / 'inspection-binding.json', {
            'historical_render_manifest_available': False,
            'kind': 'current-inspection-of-existing-delivered-pdf-not-original-render-provenance'})
        self.pdf_qa = {'pass': True, 'markdown_sha256': self.handoff['markdown_sha256'], 'pdf_sha256': self.handoff['pdf_sha256'],
                       'visual_review_required_pages': [1, 3, 7, 10], 'contact_sheets': [str(self.contact)]}
        store.write_json_atomic(inspection / 'pdf-qa.json', self.pdf_qa)
        self.visual = {key: self.job[key] for key in qualification.IDENTITY}
        self.visual.update(qualification_id='current', reviewer_task_id='real-reviewer-task', terminal=True,
                           completed_at='2026-10-28T05:09:00+00:00', markdown_sha256=self.handoff['markdown_sha256'],
                           pdf_sha256=self.handoff['pdf_sha256'], **{'pass': True}, findings=[],
                           visual_reviewed_pages=[1, 3, 7, 10], inspected_images=[str(self.contact)])
        self.save_visual()
        self.delivery_row = {key: self.job[key] for key in qualification.IDENTITY}
        self.delivery_row.update(hash_status='pass', valuation_status='done_3_files')
        event = self.original / '3Q69/Oppday/2026-10-27/TEST'
        target = self.valuation / 'TEST/3Q69'
        target.mkdir(parents=True)
        for prefix in ('conclusion', 'presentation', 'transcript'):
            binding = self.job['source_binding'][prefix + '_pdf']
            source = event / Path(binding['path']).name
            source.write_bytes(Path(binding['path']).read_bytes())
            destination = target / source.name
            destination.write_bytes(source.read_bytes())
            self.delivery_row.update({prefix + '_source_path': str(source), prefix + '_target_path': str(destination),
                                      prefix + '_sha256_source': binding['sha256'], prefix + '_sha256_target': binding['sha256']})
        self.save_delivery_row()
        self.semantic = {'status': 'pass', 'author_task_id': 'real-curator-task', 'reviewer_task_id': 'real-reviewer-task'}
        patcher = mock.patch.object(qualification, 'run_semantic_validator', return_value=self.semantic)
        self.validator = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(qualification, 'official_quarter', return_value=(2026, 3))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(qualification, 'delivery_target', return_value=target)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save_authorization(self):
        store.write_json_atomic(self.base / 'authorization.json', self.authorization)
        store.write_json_atomic(self.base / 'review-assignments.json', {
            'qualificationId': 'current', 'authorizationSha256': store.sha256(self.base / 'authorization.json'),
            'reviewers': {'TEST': {'taskId': 'real-reviewer-task'}}})

    def save_job(self):
        store.write_json_atomic(self.folder / 'qualification_job.json', self.job)

    def save_handoff(self):
        store.write_json_atomic(self.folder / 'semantic_review_handoff.json', self.handoff)

    def save_visual(self):
        store.write_json_atomic(self.folder / 'visual_review.json', self.visual)
        self.handoff['visual_review_sha256'] = store.sha256(self.folder / 'visual_review.json')
        self.save_handoff()

    def save_delivery_row(self):
        path = self.original / '3Q69/Oppday/workflow_status_3Q69.csv'
        with path.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self.delivery_row))
            writer.writeheader()
            writer.writerow(self.delivery_row)

    def verify(self):
        return qualification.verify_qualification('current', [self.item])

    def test_exact_current_review_can_pass_without_claiming_historical_qa(self):
        result = self.verify()
        self.assertTrue(result['pass'])
        self.assertFalse(result['historicalProducerQaReconstructed'])
        self.assertEqual(result['items'][0]['runId'], 'original-run')
        self.validator.assert_called_once()

    def test_missing_review_never_falls_back_to_csv_hashes(self):
        (self.folder / 'semantic_review_handoff.json').unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()

    def test_failed_independent_review_blocks(self):
        self.handoff['pass'] = False
        self.save_handoff()
        with self.assertRaisesRegex(ValueError, 'review did not pass'):
            self.verify()

    def test_self_review_or_unassigned_reviewer_blocks(self):
        for reviewer in ('real-curator-task', 'invented-reviewer'):
            with self.subTest(reviewer=reviewer):
                self.handoff['reviewer_task_id'] = reviewer
                self.save_handoff()
                with self.assertRaisesRegex(ValueError, 'independent reviewer'):
                    self.verify()

    def test_authorization_cannot_be_implicitly_inferred(self):
        self.authorization['action'] = 'files_only'
        self.save_authorization()
        with self.assertRaisesRegex(ValueError, 'authorization'):
            self.verify()

    def test_changed_authorization_invalidates_assignments(self):
        authorization = copy.deepcopy(self.authorization)
        authorization['tickerSet'].append('OTHER')
        store.write_json_atomic(self.base / 'authorization.json', authorization)
        with self.assertRaisesRegex(ValueError, 'assignments'):
            self.verify()

    def test_revoked_current_authorization_blocks_even_with_matching_assignments(self):
        self.authorization['revoked'] = True
        self.save_authorization()
        with self.assertRaisesRegex(ValueError, 'authorization'):
            self.verify()

    def test_terminal_blocker_cannot_be_hidden_beside_an_older_passing_handoff(self):
        finding = {key: self.job[key] for key in qualification.IDENTITY}
        finding.update(qualification_id='current', terminal=True, **{'pass': False},
                       markdown_sha256=self.handoff['markdown_sha256'], pdf_sha256=self.handoff['pdf_sha256'])
        store.write_json_atomic(self.folder / 'review_findings.json', finding)
        with self.assertRaisesRegex(ValueError, 'terminal review blocks'):
            self.verify()

    def test_visual_receipt_identity_and_hash_must_bind_the_reviewer_and_report(self):
        original = copy.deepcopy(self.visual)
        for key, value in (('ticker', 'WRONG'), ('reviewer_task_id', 'other'), ('qualification_id', 'other'),
                           ('markdown_sha256', 'wrong'), ('pdf_sha256', 'wrong'), ('completed_at', '2026-10-27T00:00:00+00:00')):
            with self.subTest(key=key):
                self.visual = {**original, key: value}
                self.save_visual()
                with self.assertRaisesRegex(ValueError, 'Visual receipt identity'):
                    self.verify()

    def test_visual_receipt_changes_invalidate_the_handoff(self):
        store.write_json_atomic(self.folder / 'visual_review.json', {**self.visual, 'new': True})
        with self.assertRaisesRegex(ValueError, 'bind the current visual receipt'):
            self.verify()

    def test_csv_cannot_substitute_an_unrelated_file_with_its_own_valid_hash(self):
        unrelated = self.root / 'unrelated.txt'
        unrelated.write_bytes(b'not a qualified PDF')
        for prefix in ('conclusion', 'presentation', 'transcript'):
            self.delivery_row.update({prefix + '_source_path': str(unrelated), prefix + '_target_path': str(unrelated),
                                     prefix + '_sha256_source': store.sha256(unrelated), prefix + '_sha256_target': store.sha256(unrelated)})
        self.save_delivery_row()
        with self.assertRaisesRegex(ValueError, 'canonical document roles'):
            self.verify()

    def test_valuation_destination_bytes_are_freshly_verified(self):
        Path(self.delivery_row['conclusion_target_path']).write_bytes(b'changed target')
        with self.assertRaisesRegex(ValueError, 'delivery hashes differ'):
            self.verify()

    def test_prepared_release_rechecks_current_authorization_and_evidence(self):
        directory = self.root / 'release'
        directory.mkdir()
        item = {**self.item, 'id': 'item1'}
        store.write_json_atomic(directory / 'index.local.json', {'items': [item]})
        proof = self.verify()
        manifest = {'qualificationId': 'current', 'selectedItemIds': ['item1'], 'qualificationVerification': proof}
        with mock.patch.object(store, 'release_directory', return_value=directory):
            self.assertEqual(qualification.verify_prepared_release('release', manifest), proof)
            self.authorization['revoked'] = True
            self.save_authorization()
            with self.assertRaisesRegex(ValueError, 'authorization'):
                qualification.verify_prepared_release('release', manifest)

    def test_prepared_release_requires_new_id_if_review_evidence_changes(self):
        directory = self.root / 'release'
        directory.mkdir()
        store.write_json_atomic(directory / 'index.local.json', {'items': [{**self.item, 'id': 'item1'}]})
        manifest = {'qualificationId': 'current', 'selectedItemIds': ['item1'], 'qualificationVerification': self.verify()}
        self.handoff['completed_at'] = '2026-10-28T05:11:00+00:00'
        self.save_handoff()
        with mock.patch.object(store, 'release_directory', return_value=directory):
            with self.assertRaisesRegex(ValueError, 'evidence changed'):
                qualification.verify_prepared_release('release', manifest)

    def test_original_report_change_blocks_current_review(self):
        Path(self.job['source_binding']['conclusion_md']['originalPath']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.verify()

    def test_frozen_source_change_blocks_current_review(self):
        Path(self.job['source_binding']['transcript_md']['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.verify()

    def test_source_role_cannot_point_to_an_unrelated_document(self):
        other = self.root / 'unrelated.md'
        other.write_bytes(Path(self.job['source_binding']['transcript_md']['path']).read_bytes())
        self.job['source_binding']['transcript_md']['originalPath'] = str(other)
        self.save_job()
        with self.assertRaisesRegex(ValueError, 'canonical document role'):
            self.verify()

    def test_changed_semantic_ledger_blocks(self):
        store.write_json_atomic(self.folder / 'semantic_coverage.json', {'changed': True})
        with self.assertRaisesRegex(ValueError, 'stale or changed'):
            self.verify()

    def test_wrong_record_identity_blocks(self):
        self.item['registrationId'] = 'other'
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            self.verify()

    def test_official_event_identity_must_match(self):
        store.write_json_atomic(self.folder / 'official-event.json', {'id': 22, 'symbol': 'WRONG', 'year': 2026, 'round': 3})
        with self.assertRaisesRegex(ValueError, 'Official event'):
            self.verify()

    def test_old_review_cannot_impersonate_current_qualification(self):
        self.handoff['completed_at'] = '2026-10-27T00:00:00+00:00'
        self.save_handoff()
        with self.assertRaisesRegex(ValueError, 'predates'):
            self.verify()

    def test_transcript_clip_must_match_the_official_event(self):
        store.write_json_atomic(self.folder / 'official-event.json', {'id': 22, 'symbol': 'TEST', 'year': 2026,
            'round': 3, 'meeting_date': '2026-10-27T00:00:00Z', 'video_link': 'https://www.youtube.com/embed/wrong-clip'})
        with self.assertRaisesRegex(ValueError, 'Transcript video identity'):
            self.verify()

    def test_youtube_watch_embed_and_short_urls_share_identity(self):
        for url in ('https://www.youtube.com/watch?v=clip123', 'https://www.youtube.com/embed/clip123?', 'https://youtu.be/clip123'):
            self.assertEqual(qualification.youtube_id(url), 'clip123')
        self.assertEqual(qualification.youtube_id('https://example.com/watch?v=clip123'), '')

    def test_semantic_failure_is_not_replaced_by_pdf_pass(self):
        self.validator.side_effect = ValueError('strict semantic failure')
        with self.assertRaisesRegex(ValueError, 'strict semantic failure'):
            self.verify()

    def test_missing_visual_pages_or_contact_sheets_block(self):
        self.visual['visual_reviewed_pages'] = [1]
        self.save_visual()
        with self.assertRaisesRegex(ValueError, 'pages were not'):
            self.verify()
        self.visual['visual_reviewed_pages'] = [1, 3, 7, 10]
        self.visual['inspected_images'] = []
        self.save_visual()
        with self.assertRaisesRegex(ValueError, 'contact sheets'):
            self.verify()

    def test_selection_uses_exact_original_run_and_registration(self):
        other = {**self.item, 'runId': 'replacement-run'}
        self.assertEqual(qualification.select_items('current', ['TEST'], [self.item, other]), [self.item])
        with self.assertRaisesRegex(ValueError, 'absent, stale or ambiguous'):
            qualification.select_items('current', ['TEST'], [other])

    def test_invalid_or_empty_qualification_selection_is_rejected(self):
        for value in ('../outside', '/absolute', ''):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    qualification.qualification_directory(value)
        with self.assertRaisesRegex(ValueError, 'nonempty unique'):
            qualification.select_items('current', [], [])


if __name__ == '__main__':
    unittest.main()
