"""One additional Zenodo member candidate CLI, separate from accepted7 CLI.

Uses frozen public importer and full-row reopened_audit without changing them.
The sealed pending registry grants source byte/identity evidence only.
"""
import argparse
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import re
import sys
import time

SOURCE_ID = 'zenodo13836819_sodium_soc_original_members'
CENTRAL_SHA = 'b41c746c7514aabb28e443cf78a63c7137fc5a5025856fc7b949aab62a37740f'
PUBLIC = {'src/naheng/data/zenodo_csv.py': '798037591e4a511b3e6ef401d2e816bd5aad5606e00b83886c0444138be8b73b',
          'tools/validate_zenodo_csv.py': 'fbb65cc886fe1c7cd2f5c22bfba53e5bb3b9d7047778107eaf4a4e2e68ecce49',
          'tests/unit/test_zenodo_csv.py': '63ea020b1fbd7ddfb8f70d6481cfdeb928dc21a32a5290a73ee0fb0fad961d42'}


def sha(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            hasher.update(block)
    return hasher.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def pending_source(document):
    if document.get('status') != 'sealed_pending_additional_member_candidate' or document.get('central_index_sha256') != CENTRAL_SHA:
        raise ValueError('Sealed additional-member pending scope required')
    sources = document.get('sources', [])
    if len(sources) != 1 or sources[0].get('source_id') != SOURCE_ID:
        raise ValueError('Exactly one controlled source required')
    source = sources[0]
    members = source.get('raw_members', [])
    if len(members) != 1 or source.get('raw_member_count') != 1:
        raise ValueError('Exactly one complete original member required')
    member = members[0]
    rows = member.get('rows')
    if type(rows) is not int or not 0 < rows <= 2_000_000 or source.get('raw_rows_including_duplicate') != rows:
        raise ValueError('Positive exact full CSV record count required')
    if member.get('author_battery_number') != 1 or member.get('author_group') != 'zenodo13836819_3p2Ah_bat1' or Path(member.get('path', '')).name != 'Pulse_data_temp25_bat1.CSV':
        raise ValueError('Only the recovered official battery1 Pulse25 candidate is authorized')
    if source.get('license_id') != 'CC-BY-4.0' or source.get('verification_status') != 'complete_member_crc_verified' or member.get('crc_status') != 'complete_member_crc_verified':
        raise ValueError('Complete licensed member source evidence required')
    if source.get('physical_independence_status') != 'UNKNOWN' or source.get('independent_physical_groups') is not None or member.get('physical_independence_status') != 'UNKNOWN':
        raise ValueError('Author numbers do not grant physical independence')
    if any(source.get(key) is not False for key in ('D01_complete', 'D02_complete')):
        raise ValueError('D01/D02 remain false')
    if source.get('model_fit_status') != 'not_performed' or source.get('external_model_validation') != 'not_performed' or source.get('split_assignment_status') != 'not_performed' or source.get('frozen_split') is not None:
        raise ValueError('No split roles, fit or external validation granted')
    if source.get('canonical_import_status') != 'not_performed':
        raise ValueError('Candidate registry must not presuppose successful unit normalization')
    if source.get('conservative_split_components') != [[member['author_group']]] or source.get('conservative_split_component_count') != 1:
        raise ValueError('One local provenance component required; not role assignment')
    archives = source.get('archives', [])
    if len(archives) != 1 or any(row.get('archive_md5_status') != 'UNKNOWN' or row.get('whole_archive_official_md5_verified') is not False for row in archives):
        raise ValueError('Whole archive MD5 remains UNKNOWN')
    return source


def import_file(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def preserve_all_strings(raw_path, artifact_dir, expected_rows):
    """Supplement public10-field views with every original26-field string."""
    sidecar = artifact_dir / 'all-original-field-strings.jsonl.gz'
    count = 0
    with raw_path.open(encoding='utf-8-sig', newline='') as raw_stream, sidecar.open('xb') as binary:
        reader = csv.DictReader(raw_stream)
        headers = reader.fieldnames
        with gzip.GzipFile(filename='', mode='wb', fileobj=binary, compresslevel=1, mtime=0) as zipped:
            for count, row in enumerate(reader, 1):
                source_values = {column: row.get(column) for column in headers}
                if None in row:
                    source_values['__extra_columns__'] = row[None]
                record = {'source_row': count, 'csv_line_number': reader.line_num, 'source_values': source_values}
                zipped.write((json.dumps(record, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode())
    if count != expected_rows:
        raise ValueError('All-string sidecar count differs from actual full member count')
    reopened = 0
    with raw_path.open(encoding='utf-8-sig', newline='') as raw_stream, gzip.open(sidecar, 'rt', encoding='utf-8') as stream:
        reader = csv.DictReader(raw_stream)
        for reopened, pair in enumerate(itertools.zip_longest(reader, stream), 1):
            raw, encoded = pair
            if raw is None or encoded is None:
                raise ValueError('Original-string sidecar drops/adds rows')
            row = json.loads(encoded)
            expected = {column: raw.get(column) for column in headers}
            if None in raw:
                expected['__extra_columns__'] = raw[None]
            if row != {'source_row': reopened, 'csv_line_number': reader.line_num, 'source_values': expected}:
                raise ValueError('Any original field string/row/CSV line differs')
    if reopened != expected_rows:
        raise ValueError('Full original-field sidecar reopening incomplete')
    return {'path': str(sidecar), 'sha256': sha(sidecar), 'bytes': sidecar.stat().st_size,
            'original_columns': headers, 'original_column_count': len(headers),
            'rows_written_and_reopened': reopened, 'status': 'all_original_field_strings_reopened_equal'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--registry-sha', required=True)
    parser.add_argument('--registry', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    registry = (root / args.registry).resolve()
    out = (root / args.out).resolve()
    if not registry.is_relative_to(root / 'data/manifests') or not re.fullmatch(r'pending-zenodo13836819-bat1-[A-Za-z0-9-]+\.json', registry.name):
        raise ValueError('Controlled sealed pending registry path required')
    if not re.fullmatch(r'[0-9a-f]{64}', args.registry_sha) or sha(registry) != args.registry_sha:
        raise ValueError('Sealed candidate registry SHA changed')
    if not out.is_relative_to(root / 'data/processed') or out == root / 'data/processed' or out.exists():
        raise ValueError('New data/processed output path required')
    artifact_dir = root / 'artifacts/data/public_independent' / ('unitview-audit-' + out.name)
    if artifact_dir.exists():
        raise ValueError('Preserve previous complete/failure receipt')
    document = load(registry)
    source = pending_source(document)
    if sha(root / 'data/manifests/sources.yaml') != CENTRAL_SHA:
        raise ValueError('Frozen central b41 source index changed')
    for name, expected in PUBLIC.items():
        if sha(root / name) != expected:
            raise ValueError('Frozen public importer/audit/test source changed: ' + name)
    artifact_dir.mkdir(parents=True)
    started = time.monotonic()
    module = import_file(root / 'src/naheng/data/zenodo_csv.py', 'zenodo_additional_public_importer')
    audit = import_file(root / 'tools/validate_zenodo_csv.py', 'zenodo_additional_public_reopened_audit')
    specs = module.load_zenodo_member_specs(root, registry.relative_to(root).as_posix())
    if len(specs) != 1:
        raise ValueError('One additional complete member expected')
    spec = specs[0]
    central = load(root / 'data/manifests/sources.yaml')
    old_source = next(row for row in central['sources'] if row['source_id'] == SOURCE_ID)
    if any(row['sha256'] == spec.member_sha256 or row['author_group'] == spec.author_group for row in old_source['raw_members']):
        raise ValueError('Additional candidate overlaps registered author/content cohort')
    cvut = next(row for row in central['sources'] if row['source_id'] == 'zenodo17459188_cvut_sib_0001')
    paths = {root / name for name in PUBLIC} | {root / 'data/manifests/sources.yaml', registry, spec.member_path, spec.metadata_path}
    paths.update(root / row['path'] for row in old_source['raw_members'])
    paths.update(root / cvut[key]['path'] for key in ('frozen_split', 'frozen_split_v3'))
    before = {str(path): sha(path) for path in paths}
    try:
        manifest = module.write_member_view(spec.member_path, spec, out)
        print(json.dumps({'phase': 'public_member_view_written', 'rows': manifest['row_count'],
                          'normalization_status': manifest['normalization_status'], 'elapsed_s': time.monotonic() - started}), flush=True)
        reopened = audit.reopened_audit(spec, manifest, out)
        print(json.dumps({'phase': 'public_full_row_reopened_audit_complete', **reopened,
                          'elapsed_s': time.monotonic() - started}), flush=True)
        all_strings = preserve_all_strings(spec.member_path, artifact_dir, spec.expected_rows)
        after = {str(path): sha(path) for path in paths}
        if before != after:
            raise ValueError('Frozen public inputs, old raw, holdouts or new evidence changed')
        code = 0 if manifest['normalization_status'] == 'PASS' else 2
        result = {'schema_version': 1, 'utc': datetime.now(timezone.utc).isoformat(),
                  'status': 'additional_candidate_full_member_view_and_all_strings_reopened', 'exit_code': code,
                  'entry_type': 'new_additional_member_cli_candidate_using_frozen_public_APIs_and_reopened_audit',
                  'not_original_seven_cohort_cli_acceptance': True,
                  'actual_argv': [sys.executable, *sys.argv], 'candidate_cli_sha256': sha(Path(__file__)),
                  'public_baseline_hashes': PUBLIC, 'sealed_pending_registry': {'path': str(registry), 'sha256': args.registry_sha},
                  'new_raw': {'path': str(spec.member_path), 'sha256': spec.member_sha256, 'crc32': spec.member_crc32,
                              'actual_full_source_rows': spec.expected_rows},
                  'view': {'path': str(out), 'manifest_sha256': sha(out / 'manifest.json'),
                           'observations_sha256': manifest['observations_sha256'], 'bytes': manifest['observations_bytes']},
                  'member_manifest': manifest, 'reopened_audit': reopened, 'all_original_strings': all_strings,
                  'input_sha256_before': before, 'input_sha256_after': after, 'inputs_unchanged': True,
                  'author_group': spec.author_group, 'author_group_is_physical_cell_confirmation': False,
                  'conservative_component_scope': 'Singleton candidate member/context provenance; no whole-cohort role assignment',
                  'archive_md5_status': 'UNKNOWN', 'independent_physical_cells_confirmed': None,
                  'D01_complete': False, 'D02_complete': False, 'roles_assigned': False, 'model_fits': 0,
                  'network_requests': 0, 'database_writes': 0, 'rows_dropped': 0, 'timestamps_shifted': 0,
                  'old_registered_component_count': 2, 'wall_s': time.monotonic() - started,
                  'limits': ['Pending single-member candidate only; central seven-member accepted index remains b41.',
                             'Cross-member row leakage/physical independence/operational calibration remain unverified.',
                             'Insufficient or contradictory sign evidence leaves current_A null and UNKNOWN with exit2.']}
        with (artifact_dir / 'manifest.json').open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'manifest': str(artifact_dir / 'manifest.json'), 'exit_code': code,
                          'rows': spec.expected_rows, 'wall_s': result['wall_s'], 'manifest_sha256': sha(artifact_dir / 'manifest.json')}), flush=True)
        return code
    except Exception as error:
        failure = {'exit_code': 1, 'complete': False, 'error_type': type(error).__name__, 'error': str(error),
                   'actual_argv': [sys.executable, *sys.argv], 'candidate_cli_sha256': sha(Path(__file__)),
                   'input_sha256_before': before, 'D01_complete': False, 'D02_complete': False,
                   'archive_md5_status': 'UNKNOWN', 'wall_s': time.monotonic() - started}
        with (artifact_dir / 'failure.json').open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(failure, ensure_ascii=False, indent=2) + '\n')
        raise


if __name__ == '__main__':
    raise SystemExit(main())
