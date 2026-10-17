"""Actual complete-member entry plus independent full-row output reopening."""
import argparse
import csv
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import sys
import time


def sha(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            hasher.update(block)
    return hasher.hexdigest()


def parse(raw):
    try:
        value = float(raw)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def source_index(raw):
    try:
        value = Decimal(raw)
        return int(value) if value.is_finite() and value >= 0 and value == value.to_integral_value() else None
    except (TypeError, ValueError, ArithmeticError):
        return None


def reopened_audit(spec, manifest, view):
    count, negative, unknown_current, missing_temperature, previous_time, time_resets, co_timed = 0, 0, 0, 0, None, 0, 0
    with spec.member_path.open(encoding='utf-8-sig', newline='') as raw_stream, gzip.open(view / 'observations.jsonl.gz', 'rt', encoding='utf-8') as normalized_stream:
        source = csv.DictReader(raw_stream)
        for count, pair in enumerate(itertools.zip_longest(source, normalized_stream), 1):
            original, encoded = pair
            if original is None or encoded is None:
                raise ValueError('Reopened output drops/adds original rows')
            row = json.loads(encoded)
            if row['source_row'] != count or row['csv_line_number'] != source.line_num:
                raise ValueError('Original source row/CSV line number changed')
            if row['member_sha256'] != spec.member_sha256 or row['author_group'] != spec.author_group or row['conservative_split_component'] != spec.conservative_split_component:
                raise ValueError('Raw member/group/component provenance changed')
            if any(row['source_values'][column] != original.get(column) for column in row['source_values'] if column != '__extra_columns__'):
                raise ValueError('Required original field strings changed')
            time_value, current, voltage, temperature = [parse(original.get(column)) for column in ('Test Time (s)', 'Current (A)', 'Voltage (V)', 'Aux_Temperature_1 (C)')]
            canonical_current = -current if manifest['current_sign_evidence']['vendor_current_sign'] == 'positive_charge' and current is not None else current if manifest['current_sign_evidence']['vendor_current_sign'] == 'positive_discharge' else None
            canonical_temperature = None if temperature is None else float(Decimal(original['Aux_Temperature_1 (C)']) + Decimal('273.15'))
            if (row['time_s'], row['vendor_current_A'], row['current_A'], row['voltage_V'], row['temperature_K'], row['source_temperature_degC']) != (time_value, current, canonical_current, voltage, canonical_temperature, temperature):
                raise ValueError('Canonical unit conversion or unknown-value semantics differ')
            if row['duplicate_content'] is not spec.duplicate_content:
                raise ValueError('Duplicate original content annotation changed')
            if (row['step_index'], row['cycle_index'], row['source_data_point']) != tuple(source_index(original.get(column)) for column in ('Step Index', 'Cycle Index', 'Data Point')):
                raise ValueError('Original step/cycle/data-point index conversion changed')
            if ('negative_original_voltage' in row['quality_flags']) != (voltage is not None and voltage < 0):
                raise ValueError('Original negative voltage quality annotation changed')
            if ('byte_identical_member_content' in row['quality_flags']) is not spec.duplicate_content:
                raise ValueError('Duplicate quality annotation changed')
            negative += voltage is not None and voltage < 0
            unknown_current += row['current_A'] is None
            missing_temperature += temperature is None
            if previous_time is not None and time_value is not None:
                co_timed += time_value == previous_time
                time_resets += time_value < previous_time
            previous_time = time_value
    if count != spec.expected_rows or count != manifest['row_count'] or manifest['rows_dropped'] or manifest['timestamps_shifted']:
        raise ValueError('Full original row count/time preservation failed')
    return {'rows_reopened_and_compared': count, 'negative_voltage_rows_preserved': negative,
            'unknown_current_rows': unknown_current, 'missing_temperature_rows': missing_temperature,
            'original_time_resets': time_resets, 'original_co_timed_records': co_timed,
            'member_output_sha256': sha(view / 'observations.jsonl.gz'), 'status': 'passed'}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='.')
    parser.add_argument('--module', default=None)
    parser.add_argument('--members', default=None, help='Explicit 1-based cohort member indices, comma-separated; default all')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    module_path = Path(args.module).resolve() if args.module else Path(__file__).with_name('zenodo_csv.py')
    if not module_path.is_file():
        module_path = root / 'src/naheng/data/zenodo_csv.py'
    out = (root / args.out).resolve()
    if not out.is_relative_to(root / 'artifacts'):
        raise ValueError('New project artifact directory required')
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    module_spec = importlib.util.spec_from_file_location('zenodo_csv_local_validation', module_path)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    module_hash = sha(module_path)
    results = []
    try:
        cohort_specs = module.load_zenodo_member_specs(root)
        selected = list(range(1, len(cohort_specs) + 1)) if args.members is None else [int(index) for index in args.members.split(',')]
        if not selected or len(set(selected)) != len(selected) or any(index < 1 or index > len(cohort_specs) for index in selected):
            raise ValueError('Member selection must contain unique existing 1-based cohort indices')
        specs = tuple(cohort_specs[index - 1] for index in selected)
        paths = {s.member_path for s in cohort_specs} | {s.registry_path for s in cohort_specs} | {s.metadata_path for s in cohort_specs}
        sources = json.loads((root / 'data/manifests/sources.yaml').read_text(encoding='utf-8'))
        cvut = next(s for s in sources['sources'] if s['source_id'] == 'zenodo17459188_cvut_sib_0001')
        paths.update(root / cvut[key]['path'] for key in ('frozen_split', 'frozen_split_v3'))
        paths.update(root / name for name in ['artifacts/data/public_independent/D01_independent_data_delivery.json',
            'artifacts/data/public_independent/cohort-revision2-addd1ce2/delivery.json',
            'artifacts/data/public_new/ordered-delivery-v3-fa6715bc.json',
            'artifacts/validation/D01-public-full-import-v2-4648ab65/command.json'])
        before = {str(p.relative_to(root)): sha(p) for p in paths}
        for index, member in zip(selected, specs):
            view = out / ('member-' + str(index) + '-' + member.member_path.stem)
            manifest = module.write_member_view(member.member_path, member, view)
            audit = reopened_audit(member, manifest, view)
            result = {'name': member.member_path.name, 'view': str(view.relative_to(root)), 'manifest': manifest, 'reopened_audit': audit}
            results.append(result)
            print(json.dumps({'member': result['name'], 'rows': manifest['row_count'],
                'sign': manifest['current_sign_evidence']['vendor_current_sign'], 'normalization_status': manifest['normalization_status'],
                'negative_voltage_rows_preserved': audit['negative_voltage_rows_preserved'],
                'output_bytes': manifest['observations_bytes'], 'wall_s_so_far': time.monotonic() - started}), flush=True)
        after = {str(p.relative_to(root)): sha(p) for p in paths}
        if before != after or sha(module_path) != module_hash:
            raise ValueError('Original inputs or normalization source changed during actual validation')
        total = sum(r['manifest']['row_count'] for r in results)
        if len(results) != len(specs) or total != sum(spec.expected_rows for spec in specs):
            raise ValueError('Expected complete selected original members and all selected source rows')
        if len(cohort_specs) != 7 or sum(spec.expected_rows for spec in cohort_specs) != 1108614:
            raise ValueError('Expected registered seven-member cohort and all 1108614 original source rows')
        all_normalized = all(r['manifest']['normalization_status'] == 'PASS' for r in results)
        result = {'schema_version': 1, 'status': 'actual_complete_member_views_reopened_and_source_rows_preserved',
            'exit_code': 0 if all_normalized else 2, 'module_path': str(module_path), 'module_sha256': module_hash,
            'tool_sha256': sha(Path(__file__)), 'actual_argv': [sys.executable, *sys.argv],
            'member_results': results, 'member_count': len(results), 'all_original_rows': total, 'rows_dropped': 0,
            'selected_cohort_member_indices': selected, 'complete_seven_member_cohort_in_this_batch': len(specs) == len(cohort_specs),
            'cohort_original_row_count': 1108614,
            'timestamps_shifted': 0, 'archive_md5_status': 'UNKNOWN', 'confirmed_independent_physical_cells': None,
            'conservative_split_component_count': len({s.conservative_split_component for s in specs}),
            'duplicate_members_retained': sum(s.duplicate_content for s in specs),
            'output_bytes': sum(r['manifest']['observations_bytes'] for r in results),
            'input_sha256_before': before, 'input_sha256_after': after, 'original_inputs_unchanged': True,
            'network_requests': 0, 'database_writes': 0, 'split_assignments': 0, 'model_fits': 0,
            'D01_complete': False, 'D02_complete': False, 'wall_s': time.monotonic() - started,
            'limitations': ['Canonical member unit views preserve source anomalies; not operational-cell validity or calibrated model acceptance.',
                            'Power=I*V corroborates columns only. Each member sign is inferred from bidirectional trusted capacity increments; insufficient/conflicting evidence returns UNKNOWN.',
                            'Two conservative split components are leakage constraints, not proof of independent cells; exact duplicates remain separate complete original member views.',
                            'Whole archive official MD5 remains unknown; no training/test roles assigned and no frozen holdout used for fitting.']}
        (out / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'manifest': str(out / 'manifest.json'), 'exit_code': result['exit_code'], 'rows': total,
                          'output_bytes': result['output_bytes'], 'wall_s': result['wall_s']}), flush=True)
        return result['exit_code']
    except Exception as exc:
        failure = {'complete': False, 'exit_code': 1, 'error_type': type(exc).__name__, 'error': str(exc),
                   'completed_members': len(results), 'member_results': results, 'module_sha256': module_hash,
                   'archive_md5_status': 'UNKNOWN', 'wall_s': time.monotonic() - started}
        (out / 'failure.json').write_text(json.dumps(failure, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise


if __name__ == '__main__':
    raise SystemExit(main())
