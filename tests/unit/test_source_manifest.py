import json
from pathlib import Path

import pytest

from naheng.data.registry_availability import SKIP_REASON, unit_view_evidence_available

ROOT = Path(__file__).resolve().parents[2]

def test_source_states_cannot_imply_missing_download_validation():
    manifest = json.loads((ROOT / 'data/manifests/sources.yaml').read_text(encoding='utf-8'))
    assert len({s['source_id'] for s in manifest['sources']}) == len(manifest['sources'])
    for source in manifest['sources']:
        if source['download_status'] == 'not_downloaded':
            assert source['checksum'] is None
            assert source['verification_status'] != 'verified'
        assert source['read_origin']
        assert 'license' in source
        assert 'limitations' in source

def test_public_data_and_model_identities_separate():
    manifest = json.loads((ROOT / 'data/manifests/sources.yaml').read_text(encoding='utf-8'))
    identities = manifest['model_identities']
    assert {i['model_kind'] for i in identities} == {'theory_fixture','fast_operational','reference_sodium','public_data_case'}
    public = next(i for i in identities if i['model_kind'] == 'public_data_case')
    assert public['status'] == 'not_downloaded'
    tum = next(s for s in manifest['sources'] if s['source_id'] == 'tum_sodium_1762675')
    assert tum['verification_status'] == 'blocked'


def test_local_parameter_provenance_matches_registered_bytes_and_chemistry():
    import hashlib
    import yaml
    manifest = json.loads((ROOT / 'data/manifests/sources.yaml').read_text(encoding='utf-8'))
    fixture = next(s for s in manifest['sources'] if s['source_id'] == 'synthetic-two-site-v1')
    original = ROOT / fixture['local_path']
    assert hashlib.sha256(original.read_bytes()).hexdigest() == fixture['checksum']
    parameters = yaml.safe_load(original.read_text(encoding='utf-8'))
    package = json.loads((ROOT / 'model_packages/research_base/package.json').read_text(encoding='utf-8'))
    assert fixture['chemistry_id'] == parameters['chemistry_id'] == package['chemistry_id']
    assert all(value['source_id'] == fixture['source_id'] for value in parameters['parameters'].values())


def _data_integration_tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location('data_source_integration', ROOT / 'tools/data_source_integration.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw_member_source():
    manifest = json.loads((ROOT / 'data/manifests/sources.yaml').read_text(encoding='utf-8'))
    return next(s for s in manifest['sources'] if s['source_id'] == 'zenodo13836819_sodium_soc_original_members')


@pytest.mark.skipif(not unit_view_evidence_available(), reason=SKIP_REASON)
def test_new_raw_members_keep_unknown_claims():
    import hashlib
    source = _raw_member_source()
    _data_integration_tool().validate_new_source(source)
    assert source['raw_member_count'] == len(source['raw_members']) == 7
    assert source['unique_content_count'] == len({m['sha256'] for m in source['raw_members']}) == 6
    assert source['raw_rows_including_duplicate'] == sum(m['rows'] for m in source['raw_members']) == 1108614
    assert source['author_declared_group_count'] == 3
    assert source['conservative_split_component_count'] == 2
    assert source['independent_physical_groups'] is None
    metadata_path = ROOT / source['license_evidence_path']
    assert hashlib.sha256(metadata_path.read_bytes()).hexdigest() == source['license_evidence_sha256']
    assert json.loads(metadata_path.read_text(encoding='utf-8'))['metadata']['license']['id'] == 'cc-by-4.0'
    assert all(m['manufacturer_serial_id'] is None for m in source['raw_members'])
    assert any(m['field_audit']['anomalies']['negative_voltage'] > 0 for m in source['raw_members'])
    assert all(m['field_audit']['no_rows_removed_or_fitted'] for m in source['raw_members'])


def test_data_claims_reject_inflated_evidence():
    import copy
    import pytest
    tool = _data_integration_tool()
    original = _raw_member_source()
    mutations = [
        lambda s: s.update(independent_physical_groups=3),
        lambda s: s.update(verification_status='verified'),
        lambda s: s.update(checksum='invented_whole_archive_hash'),
        lambda s: s.update(D01_complete=True),
        lambda s: s.update(D02_complete=True),
        lambda s: s['archives'][0].update(archive_md5_status='verified'),
        lambda s: s['archives'][0].update(whole_archive_official_md5_verified=True),
        lambda s: s.update(conservative_split_component_count=3),
        lambda s: s['raw_members'][0].update(crc_status='partial_stream'),
    ]
    for mutate in mutations:
        candidate = copy.deepcopy(original)
        mutate(candidate)
        with pytest.raises(ValueError):
            tool.validate_new_source(candidate)


def test_content_duplicates_join_transitive_groups():
    tool = _data_integration_tool()
    members = [
        {'author_group': 'A', 'sha256': 'same1', 'name': 'a1'},
        {'author_group': 'B', 'sha256': 'same1', 'name': 'b1'},
        {'author_group': 'B', 'sha256': 'same2', 'name': 'b2'},
        {'author_group': 'C', 'sha256': 'same2', 'name': 'c2'},
        {'author_group': 'D', 'sha256': 'other', 'name': 'd1'},
    ]
    components, duplicates = tool.components_for_members(members)
    assert components == [['A', 'B', 'C'], ['D']]
    assert len(duplicates) == 2
    assert all(d['cross_author_group'] for d in duplicates)


def test_duplicate_author_ids_cannot_split():
    import copy
    import pytest
    source = copy.deepcopy(_raw_member_source())
    source['conservative_split_components'] = [[group] for group in sorted({m['author_group'] for m in source['raw_members']})]
    source['conservative_split_component_count'] = 3
    with pytest.raises(ValueError, match='content duplicates'):
        _data_integration_tool().validate_new_source(source)


def test_cvut_v3_keeps_single_pack_holdout():
    import hashlib
    manifest = json.loads((ROOT / 'data/manifests/sources.yaml').read_text(encoding='utf-8'))
    source = next(s for s in manifest['sources'] if s['source_id'] == 'zenodo17459188_cvut_sib_0001')
    assert source['independent_physical_groups'] == 1
    assert len(source['active_views']) == 3
    v3 = next(v for v in source['active_views'] if v['view'] == 'complete_event_order_v3')
    assert v3['records_persisted'] == 64 and v3['records_dropped'] == v3['timestamps_shifted'] == 0
    assert all(v['physical_group_id'] == source['physical_group_id'] for v in source['active_views'])
    for split in [source['frozen_split'], source['frozen_split_v3']]:
        assert split['role_record_counts'] == {'train': 0, 'validation': 0, 'test': 64}
        assert split['independent_group_count'] == 1
        assert hashlib.sha256((ROOT / split['path']).read_bytes()).hexdigest() == split['sha256']
    assert source['active_views'][0]['actual_import_exit_code'] == 1
    assert source['active_views'][0]['field_compatibility'] == 'failed_duplicate_time_at_source_row33'
