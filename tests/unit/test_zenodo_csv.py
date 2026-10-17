"""Small synthetic instrument fixtures; actual seven-member check is separate."""
import csv
from dataclasses import replace
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zlib

import pytest

try:
    from naheng.data.zenodo_csv import COLUMNS, SOURCE_ID, SourceEvidenceError, analyze_member, load_zenodo_member_specs, write_member_view
except ModuleNotFoundError as exc:
    if exc.name != 'naheng.data.zenodo_csv':
        raise
    spec = importlib.util.spec_from_file_location('naheng_zenodo_draft', Path(__file__).with_name('zenodo_csv.py'))
    draft = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = draft
    spec.loader.exec_module(draft)
    COLUMNS, SOURCE_ID, SourceEvidenceError = draft.COLUMNS, draft.SOURCE_ID, draft.SourceEvidenceError
    analyze_member, load_zenodo_member_specs, write_member_view = draft.analyze_member, draft.load_zenodo_member_specs, draft.write_member_view


def fixture(root, change=None, omit=()):
    raw_dir = root / 'data/raw'
    raw_dir.mkdir(parents=True)
    path = raw_dir / 'Pulse_data_temp25_bat3.CSV'
    rows, charge, discharge = [], 0.0, 0.0
    for index in range(12):
        current = 3 if index < 6 else -3
        charge += .001 if current > 0 else 0
        discharge += .001 if current < 0 else 0
        row = {COLUMNS['time']: str(index), COLUMNS['current']: str(current), COLUMNS['voltage']: '3',
               COLUMNS['temperature']: '25.1234', COLUMNS['step']: '1', COLUMNS['cycle']: '1',
               COLUMNS['sequence']: str(index + 1), COLUMNS['power']: str(current * 3),
               COLUMNS['charge']: str(charge), COLUMNS['discharge']: str(discharge)}
        rows.append(row)
    if change:
        change(rows)
    headers = [column for column in COLUMNS.values() if column not in omit]
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    metadata = root / 'metadata.json'
    metadata.write_text(json.dumps({'id': 13836819, 'metadata': {'license': {'id': 'cc-by-4.0'},
        'description': 'Synthetic fixture of the registered format; not real source bytes'}}), encoding='utf-8')
    registry = root / 'data/manifests/sources.yaml'
    registry.parent.mkdir(parents=True)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    member = {'name': path.name, 'path': path.relative_to(root).as_posix(), 'sha256': sha(path),
              'crc32': format(zlib.crc32(path.read_bytes()) & 0xffffffff, '08x'), 'rows': 12,
              'author_group': 'zenodo13836819_10Ah_bat3', 'author_battery_number': 3,
              'archive_member_name': '1_Enhanced pulse test data/' + path.name,
              'crc_status': 'complete_member_crc_verified', 'source_temperature_condition_degC': 25}
    source = {'source_id': SOURCE_ID, 'verification_status': 'complete_member_crc_verified', 'license_id': 'CC-BY-4.0',
              'license_evidence_path': 'metadata.json', 'license_evidence_sha256': sha(metadata),
              'archives': [{'archive_md5_status': 'UNKNOWN', 'whole_archive_official_md5_verified': False}],
              'conservative_split_components': [[member['author_group']]], 'raw_members': [member]}
    registry.write_text(json.dumps({'sources': [source]}), encoding='utf-8')
    return path, load_zenodo_member_specs(root)[0], rows


def output_rows(path):
    with gzip.open(path / 'observations.jsonl.gz', 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def test_units(tmp_path):
    path, spec, originals = fixture(tmp_path)
    before = path.read_bytes()
    out = tmp_path / 'view'
    manifest = write_member_view(path, spec, out)
    rows = output_rows(out)
    assert manifest['complete'] and manifest['row_count'] == 12 and manifest['rows_dropped'] == 0
    assert manifest['current_sign_evidence']['vendor_current_sign'] == 'positive_charge'
    assert rows[0]['current_A'] == -3 and rows[-1]['current_A'] == 3
    assert rows[0]['temperature_K'] == 298.2734 and rows[0]['source_temperature_degC'] == 25.1234
    assert [r['source_row'] for r in rows] == list(range(1, 13))
    assert rows[0]['source_values'] == originals[0]
    assert path.read_bytes() == before
    assert manifest['archive_md5_status'] == 'UNKNOWN' and manifest['independent_physical_cells'] is None


@pytest.mark.parametrize('kind', ['no_capacity', 'single_direction', 'contradiction', 'bad_power'])
def test_unknown(tmp_path, kind):
    def change(rows):
        if kind == 'no_capacity':
            for row in rows:
                row[COLUMNS['charge']] = row[COLUMNS['discharge']] = '0'
        elif kind == 'single_direction':
            for row in rows:
                row[COLUMNS['current']] = '3'
                row[COLUMNS['power']] = '9'
                row[COLUMNS['discharge']] = '0'
        elif kind == 'contradiction':
            rows[4][COLUMNS['charge']] = rows[3][COLUMNS['charge']]
            rows[4][COLUMNS['discharge']] = '.001'
        else:
            for row in rows:
                row[COLUMNS['power']] = '999'
    path, spec, originals = fixture(tmp_path, change)
    out = tmp_path / 'view'
    manifest = write_member_view(path, spec, out)
    assert manifest['normalization_status'] == 'UNKNOWN'
    assert manifest['row_count'] == 12
    assert all(row['current_A'] is None and row['vendor_current_A'] == float(original[COLUMNS['current']])
               for row, original in zip(output_rows(out), originals))


def test_contexts(tmp_path):
    def change(rows):
        rows[10][COLUMNS['time']] = rows[9][COLUMNS['time']]
        rows[11][COLUMNS['time']] = '0'
        rows[0][COLUMNS['voltage']] = '-.4'
        rows[0][COLUMNS['power']] = '-1.2'
    path, spec, original = fixture(tmp_path, change)
    out = tmp_path / 'view'
    manifest = write_member_view(path, spec, out)
    rows = output_rows(out)
    assert rows[0]['voltage_V'] == -.4
    assert 'negative_original_voltage' in rows[0]['quality_flags']
    assert 'co_timed_original_record' in rows[10]['quality_flags']
    assert 'original_test_time_reset' in rows[11]['quality_flags']
    assert rows[11]['context_id'] != rows[10]['context_id']
    assert [r['time_s'] for r in rows] == [float(r[COLUMNS['time']]) for r in original]
    assert manifest['timestamps_shifted'] == manifest['rows_dropped'] == 0


def test_missing_sensor(tmp_path):
    path, spec, original = fixture(tmp_path, omit=(COLUMNS['temperature'],))
    out = tmp_path / 'view'
    manifest = write_member_view(path, spec, out)
    assert manifest['current_sign_evidence']['vendor_current_sign'] == 'positive_charge'
    assert all(r['temperature_K'] is None and 'temperature_not_measured' in r['quality_flags'] for r in output_rows(out))


def test_invalid_row(tmp_path):
    def change(rows):
        rows[0][COLUMNS['current']] = 'NaN'
    path, spec, original = fixture(tmp_path, change)
    out = tmp_path / 'view'
    manifest = write_member_view(path, spec, out)
    rows = output_rows(out)
    assert len(rows) == 12 and rows[0]['current_A'] is None
    assert rows[0]['source_values'][COLUMNS['current']] == 'NaN'
    assert rows[0]['normalization_status'] == 'UNKNOWN' and manifest['unknown_row_count'] >= 1


@pytest.mark.parametrize('field,value', [('author_group', 'zenodo13836819_10Ah_bat4'),
    ('conservative_split_component', 'fake-component'), ('duplicate_content', True), ('expected_rows', 2)])
def test_spec_binding(tmp_path, field, value):
    path, spec, original = fixture(tmp_path)
    with pytest.raises(SourceEvidenceError):
        write_member_view(path, replace(spec, **{field: value}), tmp_path / 'bad-view')
    assert json.loads((tmp_path / 'bad-view/failure.json').read_text())['complete'] is False


def test_source_change(tmp_path):
    path, spec, original = fixture(tmp_path)
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(SourceEvidenceError, match='SHA/CRC'):
        write_member_view(path, spec, tmp_path / 'view')


def test_no_overwrite(tmp_path):
    path, spec, original = fixture(tmp_path)
    out = tmp_path / 'view'
    write_member_view(path, spec, out)
    before = (out / 'manifest.json').read_bytes()
    with pytest.raises(FileExistsError):
        write_member_view(path, spec, out)
    assert (out / 'manifest.json').read_bytes() == before


def test_duplicate_components(tmp_path):
    path, spec, original = fixture(tmp_path)
    registry = spec.registry_path
    doc = json.loads(registry.read_text())
    second = dict(doc['sources'][0]['raw_members'][0])
    second_path = path.with_name('Pulse_data_temp25_bat4.CSV')
    second_path.write_bytes(path.read_bytes())
    second.update(name=second_path.name, path=second_path.relative_to(tmp_path).as_posix(),
                  author_group='zenodo13836819_10Ah_bat4', author_battery_number=4,
                  archive_member_name='1_Enhanced pulse test data/' + second_path.name)
    doc['sources'][0]['raw_members'].append(second)
    doc['sources'][0]['conservative_split_components'][0].append(second['author_group'])
    registry.write_text(json.dumps(doc))
    specs = load_zenodo_member_specs(tmp_path)
    assert all(s.duplicate_content for s in specs)
    assert specs[0].conservative_split_component == specs[1].conservative_split_component
    doc['sources'][0]['conservative_split_components'] = [[specs[0].author_group], [specs[1].author_group]]
    registry.write_text(json.dumps(doc))
    with pytest.raises(SourceEvidenceError, match='cross split'):
        load_zenodo_member_specs(tmp_path)
