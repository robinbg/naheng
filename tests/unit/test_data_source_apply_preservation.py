"""Metadata fixtures loaded through the complete staged/public tool entry."""
import copy
import importlib.util
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import unittest
import hashlib
import json
import tempfile
from unittest import mock

candidate = Path(__file__).with_name('data_source_integration_preserve.py')
if not candidate.is_file():
    candidate = Path(__file__).resolve().parents[2] / 'tools/data_source_integration.py'
spec = importlib.util.spec_from_file_location('data_source_integration_preservation_candidate', candidate)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def existing():
    return {'state_definitions': {'complete_member_crc_verified': 'bytes only; reviewed units separately'},
        'sources': [{'source_id': 'fixture_existing', 'canonical_import_status': 'seven_complete_member_unit_views_reopened',
                     'canonical_view_acceptance': {'normal_entry_handoff': {'path': 'author.json', 'sha256': 'author'},
                                                   'independent_review': {'path': 'review.json', 'sha256': 'review'}},
                     'raw_members': [{'path': 'original.csv', 'sha256': 'original',
                                      'canonical_view': {'view_sha256': 'view', 'canonical_units': {'temperature': 'K'}},
                                      'field_audit': {'scope': 'historical raw-pair audit', 'vendor_current_sign_inferred': 'UNKNOWN',
                                                      'current_sign_evidence': {'negative_current_charge_capacity_increases': 338}}}]}]}


def raw_only_fixture(current):
    proposal = copy.deepcopy(current)
    source = proposal['sources'][0]
    source['canonical_import_status'] = 'not_performed'
    source.pop('canonical_view_acceptance')
    for member in source['raw_members']:
        member.pop('canonical_view')
        member['field_audit'].pop('scope')
    return proposal


class PreservationFixtures(unittest.TestCase):
    def test_matching_bundle_rejection_precedes_validation_backup_and_index_write(self):
        """Exercise the actual apply entry; fixture files are explicitly synthetic."""
        current = existing()
        proposed = raw_only_fixture(current)
        with tempfile.TemporaryDirectory(prefix='nh-preserve-') as folder:
            directory = Path(folder)
            index = directory / 'sources.yaml'
            index.write_text(json.dumps(current), encoding='utf-8')
            original = index.read_bytes()
            proposal = directory / 'sources.proposed.yaml'
            proposal.write_text(json.dumps(proposed), encoding='utf-8')
            immutable = {'fixture-only-input': 'not-a-real-data-receipt'}
            expected = hashlib.sha256(original).hexdigest()
            (directory / 'audit.json').write_text(json.dumps({
                'original_index_sha256': expected,
                'proposed_index_sha256': hashlib.sha256(proposal.read_bytes()).hexdigest(),
                'preserved_input_hashes_before': immutable,
            }), encoding='utf-8')
            with mock.patch.object(guard, 'INDEX', index), \
                 mock.patch.object(guard, 'preserved_hashes', return_value=immutable), \
                 mock.patch.object(guard, 'validate_new_source') as validation:
                with self.assertRaisesRegex(ValueError, 'canonical acceptance'):
                    guard.apply(directory, expected)
            self.assertEqual(index.read_bytes(), original)
            validation.assert_not_called()
            for name in ('sources.backup-before-apply.yaml', 'sources.atomic-stage.yaml', 'apply.json'):
                self.assertFalse((directory / name).exists(), name)

    def test_identical_reviewed_metadata_allowed(self):
        current = existing()
        guard.assert_preserved_registered_unit_views(current, copy.deepcopy(current))

    def test_unrelated_source_and_read_date_change_allowed(self):
        current = existing()
        proposed = copy.deepcopy(current)
        proposed['sources'][0]['read_on'] = 'later local audit'
        proposed['sources'].append({'source_id': 'independent_new_fixture'})
        guard.assert_preserved_registered_unit_views(current, proposed)

    def test_first_raw_registration_does_not_need_reviewed_metadata(self):
        guard.assert_preserved_registered_unit_views({'sources': []}, existing())

    def test_downgrade_to_raw_only_rejected(self):
        current = existing()
        with self.assertRaisesRegex(ValueError, 'canonical acceptance'):
            guard.assert_preserved_registered_unit_views(current, raw_only_fixture(current))

    def test_independent_receipt_removed_or_replaced_rejected(self):
        for mutation in ('remove', 'replace'):
            with self.subTest(mutation=mutation):
                current = existing()
                proposed = copy.deepcopy(current)
                acceptance = proposed['sources'][0]['canonical_view_acceptance']
                if mutation == 'remove':
                    acceptance.pop('independent_review')
                else:
                    acceptance['independent_review']['sha256'] = 'different_review'
                with self.assertRaises(ValueError):
                    guard.assert_preserved_registered_unit_views(current, proposed)

    def test_view_removed_hash_or_units_changed_rejected(self):
        for mutation in ('remove', 'hash', 'units'):
            with self.subTest(mutation=mutation):
                current = existing()
                proposed = copy.deepcopy(current)
                member = proposed['sources'][0]['raw_members'][0]
                if mutation == 'remove':
                    member.pop('canonical_view')
                elif mutation == 'hash':
                    member['canonical_view']['view_sha256'] = 'different_view'
                else:
                    member['canonical_view']['canonical_units']['temperature'] = 'C'
                with self.assertRaises(ValueError):
                    guard.assert_preserved_registered_unit_views(current, proposed)

    def test_historical_scope_sign_or_counts_changed_rejected(self):
        for mutation in ('scope', 'sign', 'counts'):
            with self.subTest(mutation=mutation):
                current = existing()
                proposed = copy.deepcopy(current)
                field = proposed['sources'][0]['raw_members'][0]['field_audit']
                if mutation == 'scope':
                    field.pop('scope')
                elif mutation == 'sign':
                    field['vendor_current_sign_inferred'] = 'positive_charge'
                else:
                    field['current_sign_evidence']['negative_current_charge_capacity_increases'] = 0
                with self.assertRaises(ValueError):
                    guard.assert_preserved_registered_unit_views(current, proposed)

    def test_member_removed_or_duplicate_path_rejected(self):
        for mutation in ('remove', 'duplicate'):
            with self.subTest(mutation=mutation):
                current = existing()
                proposed = copy.deepcopy(current)
                members = proposed['sources'][0]['raw_members']
                if mutation == 'remove':
                    members.clear()
                else:
                    members.append(copy.deepcopy(members[0]))
                with self.assertRaises(ValueError):
                    guard.assert_preserved_registered_unit_views(current, proposed)

    def test_registered_source_removed_or_duplicated_rejected(self):
        for mutation in ('remove', 'duplicate'):
            with self.subTest(mutation=mutation):
                current = existing()
                proposed = copy.deepcopy(current)
                if mutation == 'remove':
                    proposed['sources'].clear()
                else:
                    proposed['sources'].append(copy.deepcopy(proposed['sources'][0]))
                with self.assertRaises(ValueError):
                    guard.assert_preserved_registered_unit_views(current, proposed)

    def test_old_byte_state_scope_reset_rejected(self):
        current = existing()
        proposed = copy.deepcopy(current)
        proposed['state_definitions']['complete_member_crc_verified'] = 'not canonical importer'
        with self.assertRaisesRegex(ValueError, 'scope definition'):
            guard.assert_preserved_registered_unit_views(current, proposed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
