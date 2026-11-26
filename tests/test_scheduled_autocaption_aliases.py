from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from scripts import markdown_import as importer


class ScheduledAutocaptionAliasTests(unittest.TestCase):
    """Automatic exceptions must remain specific to real matching source pairs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / '3Q69' / 'Oppday' / 'summary'
        self.root.mkdir(parents=True)
        root_patch = patch.object(importer, 'summary_root', return_value=self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.inherited = []
        aliases_patch = patch.object(importer, 'source_aliases', side_effect=lambda quarter: list(self.inherited))
        aliases_patch.start()
        self.addCleanup(aliases_patch.stop)
        self.accepted = set()
        accepted_patch = patch.object(importer, 'accepted_event_keys',
                                      side_effect=lambda quarter: set(self.accepted), create=True)
        accepted_patch.start()
        self.addCleanup(accepted_patch.stop)
        self.status = self.root.parent / 'workflow_status_3Q69.csv'
        self.rows = []
        self.write_status()

    def write_status(self):
        self.status.write_text('ticker,event_date,registration_id,run_id,conclusion_status\n'
                               + ''.join(self.rows), encoding='utf-8')

    def pair(self, ticker='NEW', day='2026-11-24', nested=False, registration='12034'):
        name = f'{ticker}-Earning call-3Q69-YouTube-autocaption.md'
        event = f'{day}-{registration}-C-Sign'
        relative = Path(day) / ticker / event / name if nested else Path(day) / name
        summary = self.root / relative
        primary = self.root.parent / relative if nested else self.root.parent / day / ticker / name
        body = f'# {ticker} Earning call 3Q69\nEvent date: {day}\nSET registration {registration}\nContent\n'.encode('utf-8')
        for path in (summary, primary):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        self.rows.append(f'{ticker},{day},{registration},run-{ticker},done\n')
        self.write_status()
        alias = {'ticker': ticker, 'eventDate': day, 'filename': name,
                 'sha256': hashlib.sha256(body).hexdigest()}
        if nested:
            alias['nestedEvent'] = event
        return summary, primary, alias

    def discover(self):
        return importer.discover_scheduled_autocaption_aliases('3Q69')

    def test_flat_and_nested_pairs_become_exact_hash_bound_aliases(self):
        flat, flat_primary, one = self.pair('FLAT')
        nested, nested_primary, two = self.pair('NEST', nested=True, registration='12035')
        before = {p: p.read_bytes() for p in (flat, flat_primary, nested, nested_primary)}
        aliases = self.discover()
        self.assertCountEqual(aliases, [one, two])
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertIn(flat, importer.discover('3Q69', aliases))
        self.assertIn(nested, importer.discover('3Q69', aliases))
        self.assertEqual(importer.source_event(nested, '3Q69', 'NEST'), '2026-11-24')

    def test_non_3q69_scope_is_rejected(self):
        self.pair()
        with self.assertRaises((ValueError, AssertionError)):
            importer.discover_scheduled_autocaption_aliases('4Q69')

    def test_missing_or_mismatched_primary_is_rejected(self):
        summary, primary, _ = self.pair()
        primary.unlink()
        with self.assertRaises((ValueError, OSError)):
            self.discover()
        primary.write_bytes(summary.read_bytes() + b'changed')
        with self.assertRaises((ValueError, OSError)):
            self.discover()

    def test_both_copies_with_wrong_heading_are_rejected(self):
        summary, primary, _ = self.pair()
        for path in (summary, primary):
            path.write_text('# OTHER Earning call 3Q69\nEvent date: 2026-11-24\nSET registration 12034\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.discover()

    def test_nested_event_registration_must_match_content(self):
        summary, primary, _ = self.pair(nested=True)
        for path in (summary, primary):
            path.write_text('# NEW Earning call 3Q69\nEvent date: 2026-11-24\nSET registration 999\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.discover()

    def test_nested_thai_set_registration_binds_header_folder_and_workflow(self):
        summary, primary, _ = self.pair(nested=True)
        body = ('# NEW Earning call 3Q69\nEvent date: 2026-11-24\n'
                '- สไลด์ SET ทะเบียน 12034 และ transcript\n')
        for path in (summary, primary):
            path.write_text(body, encoding='utf-8')
        aliases = self.discover()
        self.assertEqual(aliases[0]['sha256'], hashlib.sha256(summary.read_bytes()).hexdigest())
        self.assertEqual(importer.event_registration(body), '12034')
        self.assertEqual(importer.source_event(summary, '3Q69', 'NEW'), '2026-11-24')

    def test_nested_thai_registration_rejects_wrong_and_ambiguous_numbers(self):
        summary, primary, _ = self.pair(nested=True)
        for registration in ('SET ทะเบียน 120340',
                             'SET ทะเบียน 12034\nทะเบียน SET 999',
                             'SET ทะเบียน 12034\nทะเบียน 999',
                             'SET ทะเบียน\n12034'):
            with self.subTest(registration=registration):
                body = ('# NEW Earning call 3Q69\nEvent date: 2026-11-24\n'
                        + registration + '\n')
                for path in (summary, primary):
                    path.write_text(body, encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.discover()
                with self.assertRaises(ValueError):
                    importer.source_event(summary, '3Q69', 'NEW')

    def test_thai_registration_requires_matching_workflow_row(self):
        summary, primary, _ = self.pair(nested=True)
        body = '# NEW Earning call 3Q69\nEvent date: 2026-11-24\nSET ทะเบียน 12034\n'
        for path in (summary, primary):
            path.write_text(body, encoding='utf-8')
        self.rows = ['NEW,2026-11-24,999,run-new,done\n']
        self.write_status()
        with self.assertRaises(ValueError):
            self.discover()

    def test_nested_folder_registration_cannot_be_supplied_only_in_late_body(self):
        summary, primary, _ = self.pair(nested=True, registration='123')
        self.rows = ['NEW,2026-11-24,456,run-new,done\n']
        self.write_status()
        body = ('# NEW Earning call 3Q69\nEvent date: 2026-11-24\n'
                'SET registration 456\n' + '\n' * 12 + 'SET registration 123\n')
        for path in (summary, primary):
            path.write_text(body, encoding='utf-8')
        with self.assertRaises(ValueError):
            self.discover()

    def test_header_date_must_match_source_folder(self):
        summary, primary, _ = self.pair()
        for path in (summary, primary):
            path.write_text('# NEW Earning call 3Q69\nEvent date: 2026-11-23\nSET registration 12034\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.discover()

    def test_thai_buddhist_era_header_date_is_supported(self):
        summary, primary, _ = self.pair()
        for path in (summary, primary):
            path.write_text('# NEW Earning call 3Q69\nEarnings Call 24 พฤศจิกายน 2569\nSET registration 12034\n', encoding='utf-8')
        alias = self.discover()[0]
        self.assertEqual(alias['sha256'], hashlib.sha256(summary.read_bytes()).hexdigest())
        self.assertEqual(alias['eventDate'], '2026-11-24')

    def test_event_date_label_distinguishes_fiscal_period_and_later_header_line(self):
        for event_label in ('นำเสนอ', 'Oppday', 'Oppday วันที่', 'SET Opportunity Day'):
            with self.subTest(label=event_label):
                header = ('# NEW Earning call 3Q69\n\nCompany\n\n'
                          'งวดสิ้นสุด 30 กันยายน 2569 | ' + event_label + ' 24 พฤศจิกายน 2569\n')
                self.assertEqual(importer.autocaption_header_event_dates(header), {'2026-11-24'})

    def test_missing_conflicting_or_wrong_event_label_dates_block(self):
        summary, primary, _ = self.pair()
        headers = ('งวดสิ้นสุด 24 พฤศจิกายน 2569',
                   'Oppday 24 พฤศจิกายน 2569 | นำเสนอ 23 พฤศจิกายน 2569',
                   'Oppday 23 พฤศจิกายน 2569',
                   'Oppday\n24 พฤศจิกายน 2569',
                   'Oppday 24 พฤศจิกายน 25690',
                   'Oppday 2026-11-240',
                   'Oppday 24 พฤศจิกายน 2569 ถึง 25 พฤศจิกายน 2569',
                   'Oppday 2026-11-24 / 2026-11-25',
                   'Oppday 2026-11-24, 2026-11-25',
                   'Oppday 24 พฤศจิกายน 2569 | Event date: unknown')
        for header in headers:
            with self.subTest(header=header):
                body = '# NEW Earning call 3Q69\n' + header + '\nSET registration 12034\n'
                for path in (summary, primary):
                    path.write_text(body, encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.discover()

    def test_registration_matches_workflow_row_when_present(self):
        _, _, alias = self.pair()
        status = self.root.parent / 'workflow_status_3Q69.csv'
        status.write_text('ticker,event_date,registration_id,run_id,conclusion_status\n'
                          'NEW,2026-11-24,12034,run-a,done\n', encoding='utf-8')
        self.assertEqual(self.discover(), [alias])
        status.write_text('ticker,event_date,registration_id,run_id,conclusion_status\n'
                          'NEW,2026-11-24,999,run-a,done\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.discover()

    def test_missing_or_ambiguous_workflow_match_blocks(self):
        self.pair()
        self.rows.clear()
        self.write_status()
        with self.assertRaises(ValueError):
            self.discover()
        self.rows.extend(['NEW,2026-11-24,12034,run-a,done\n',
                          'NEW,2026-11-24,12034,run-b,done\n'])
        self.write_status()
        with self.assertRaises(ValueError):
            self.discover()

    def test_missing_header_registration_blocks_even_with_workflow_row(self):
        summary, primary, _ = self.pair()
        for path in (summary, primary):
            path.write_text('# NEW Earning call 3Q69\nEvent date: 2026-11-24\nContent\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.discover()

    def test_accepted_canonical_event_is_not_rebound_to_new_alias(self):
        self.pair()
        self.accepted.add(('NEW', '2026-11-24'))
        with self.assertRaises(ValueError):
            self.discover()

    def test_nested_ticker_folder_must_match_filename(self):
        summary, primary, _ = self.pair(nested=True)
        other_summary = self.root / '2026-11-24' / 'OTHER' / summary.parent.name / summary.name
        other_primary = self.root.parent / '2026-11-24' / 'OTHER' / primary.parent.name / primary.name
        for original, renamed in ((summary, other_summary), (primary, other_primary)):
            renamed.parent.mkdir(parents=True, exist_ok=True)
            original.rename(renamed)
        with self.assertRaises(ValueError):
            self.discover()

    def test_inherited_alias_cannot_change_even_if_both_copies_change(self):
        summary, primary, alias = self.pair()
        self.inherited.append(alias)
        for path in (summary, primary):
            path.write_bytes(path.read_bytes() + b'changed in both copies')
        with self.assertRaises(ValueError):
            self.discover()

    def test_inherited_alias_remains_hash_bound_and_not_duplicated(self):
        _, _, alias = self.pair()
        self.inherited.append(alias)
        self.assertEqual(self.discover(), [alias])

    def test_differing_standard_copy_is_not_silently_deduplicated(self):
        summary, primary, _ = self.pair()
        for path in (summary, primary):
            path.with_name('NEW-Earning call-3Q69.md').write_bytes(path.read_bytes() + b'different')
        with self.assertRaises(ValueError):
            self.discover()

    def test_identical_standard_copy_results_in_one_original_record(self):
        summary, primary, alias = self.pair()
        for path in (summary, primary):
            path.with_name('NEW-Earning call-3Q69.md').write_bytes(path.read_bytes())
        aliases = self.discover()
        self.assertEqual(aliases, [alias])
        self.assertEqual(importer.discover('3Q69', aliases), [summary])

    def test_alias_uses_standard_identity(self):
        summary, _, _ = self.pair()
        aliases = self.discover()
        actual = importer.source_metadata(summary, '3Q69', aliases)
        canonical = summary.with_name('NEW-Earning call-3Q69.md')
        expected = server.detect_current_file(canonical, '3Q69', self.root)
        self.assertEqual(actual, expected)

    def test_hash_remains_frozen_after_discovery(self):
        summary, primary, _ = self.pair()
        aliases = self.discover()
        for path in (summary, primary):
            path.write_bytes(path.read_bytes() + b'changed after discovery')
        with self.assertRaises(ValueError):
            importer.discover('3Q69', aliases)

    def test_other_suffix_still_fails_closed(self):
        summary, primary, _ = self.pair()
        other = 'NEW-Earning call-3Q69-unapproved.md'
        summary.rename(summary.with_name(other))
        primary.rename(primary.with_name(other))
        with self.assertRaisesRegex(ValueError, 'Unapproved Earning call filenames'):
            importer.discover('3Q69', self.discover())


if __name__ == '__main__':
    unittest.main()
