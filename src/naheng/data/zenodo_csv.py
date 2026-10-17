"""Preserved-member unit views for Zenodo13836819; no splitting or fitting.

CRC and local SHA bind complete recovered members, not whole ZIP authenticity.
Author IDs and conservative components are provenance labels, not independent
cell assertions. Every CSV record is retained, including instrument anomalies.
"""
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import zlib

SOURCE_ID = 'zenodo13836819_sodium_soc_original_members'
COLUMNS = {'time': 'Test Time (s)', 'current': 'Current (A)', 'voltage': 'Voltage (V)',
           'temperature': 'Aux_Temperature_1 (C)', 'step': 'Step Index', 'cycle': 'Cycle Index',
           'sequence': 'Data Point', 'power': 'Power (W)', 'charge': 'Charge Capacity (Ah)',
           'discharge': 'Discharge Capacity (Ah)'}
REQUIRED = ('time', 'current', 'voltage', 'step', 'cycle')
SIGN_POLICY = {'current_noise_threshold_A': 0.01, 'capacity_increment_threshold_Ah': 1e-8,
               'minimum_trusted_observations_each_direction': 3,
               'power_absolute_tolerance_W': 1e-6, 'power_relative_tolerance': 1e-6,
               'trusted_subset': 'finite positive voltage, Power=I*V, adjacent source sequence, same step/cycle, increasing test time, same nonzero current polarity, one increasing capacity counter and no reset'}


class SourceEvidenceError(ValueError):
    """A source/license/member identity is unavailable or has changed."""


@dataclass(frozen=True)
class ZenodoMemberSpec:
    source_id: str
    member_path: Path
    member_sha256: str
    member_crc32: str
    expected_rows: int
    author_group: str
    author_battery_number: int
    conservative_split_component: str
    duplicate_content: bool
    archive_member_name: str
    registry_path: Path
    registry_sha256: str
    metadata_path: Path
    metadata_sha256: str
    source_temperature_condition_degC: float | None = None
    archive_md5_status: str = 'UNKNOWN'


def _sha(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            hasher.update(block)
    return hasher.hexdigest()


def _raw_identity(path):
    hasher, crc, size = hashlib.sha256(), 0, 0
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            hasher.update(block)
            crc = zlib.crc32(block, crc)
            size += len(block)
    return hasher.hexdigest(), format(crc & 0xffffffff, '08x'), size


def _verify(spec, path):
    path = Path(path).resolve()
    if path != spec.member_path.resolve() or spec.source_id != SOURCE_ID or spec.archive_md5_status != 'UNKNOWN':
        raise SourceEvidenceError('Member/source binding or whole-archive claim mismatch')
    if _sha(spec.registry_path) != spec.registry_sha256 or _sha(spec.metadata_path) != spec.metadata_sha256:
        raise SourceEvidenceError('Registered source/license metadata changed')
    root = spec.registry_path.resolve().parents[2]
    registered = json.loads(spec.registry_path.read_text(encoding='utf-8-sig'))
    source = next((s for s in registered['sources'] if s['source_id'] == SOURCE_ID), None)
    if source is None or source['verification_status'] != 'complete_member_crc_verified' or source['license_id'] != 'CC-BY-4.0':
        raise SourceEvidenceError('Registered complete licensed source identity mismatch')
    member = next((m for m in source['raw_members'] if (root / m['path']).resolve() == path), None)
    group_set = next((groups for groups in source['conservative_split_components'] if spec.author_group in groups), None)
    if member is None or group_set is None or not path.is_relative_to(root / 'data/raw'):
        raise SourceEvidenceError('Registered member/author group missing')
    expected_component = 'zenodo13836819_component_' + hashlib.sha256(json.dumps(sorted(group_set)).encode()).hexdigest()[:16]
    duplicates = sum(m['sha256'] == member['sha256'] for m in source['raw_members']) > 1
    if (member['sha256'], member['crc32'], member['rows'], member['author_group'], member['author_battery_number'],
            member['archive_member_name'], expected_component, duplicates, member['source_temperature_condition_degC']) != (
            spec.member_sha256, spec.member_crc32, spec.expected_rows, spec.author_group, spec.author_battery_number,
            spec.archive_member_name, spec.conservative_split_component, spec.duplicate_content, spec.source_temperature_condition_degC):
        raise SourceEvidenceError('Full member specification differs from registered evidence')
    if (root / source['license_evidence_path']).resolve() != spec.metadata_path.resolve() or source['license_evidence_sha256'] != spec.metadata_sha256:
        raise SourceEvidenceError('License evidence differs from registered source')
    metadata = json.loads(spec.metadata_path.read_text(encoding='utf-8-sig'))
    if str(metadata.get('id')) != '13836819' or metadata['metadata']['license']['id'] != 'cc-by-4.0':
        raise SourceEvidenceError('Stored official record/license mismatch')
    digest, crc, size = _raw_identity(path)
    if digest != spec.member_sha256 or crc != spec.member_crc32:
        raise SourceEvidenceError('Original complete member SHA/CRC mismatch')
    return size


def load_zenodo_member_specs(root, manifest='data/manifests/sources.yaml'):
    """Load the registered cohort, joining all identical-content author IDs."""
    root = Path(root).resolve()
    registry = (root / manifest).resolve()
    if not registry.is_relative_to(root / 'data/manifests'):
        raise SourceEvidenceError('Source registry outside project data/manifests')
    document = json.loads(registry.read_text(encoding='utf-8-sig'))
    source = next((s for s in document['sources'] if s['source_id'] == SOURCE_ID), None)
    if source is None or source['verification_status'] != 'complete_member_crc_verified' or source['license_id'] != 'CC-BY-4.0':
        raise SourceEvidenceError('Registered complete licensed original members required')
    if any(a['archive_md5_status'] != 'UNKNOWN' or a['whole_archive_official_md5_verified'] for a in source['archives']):
        raise SourceEvidenceError('Partial recovered archives cannot be whole-archive verified')
    metadata = (root / source['license_evidence_path']).resolve()
    if not metadata.is_relative_to(root):
        raise SourceEvidenceError('Uncontrolled metadata path')
    component_map = {}
    for group_set in source['conservative_split_components']:
        component_id = 'zenodo13836819_component_' + hashlib.sha256(json.dumps(sorted(group_set)).encode()).hexdigest()[:16]
        for group in group_set:
            if group in component_map:
                raise SourceEvidenceError('Author group assigned to multiple components')
            component_map[group] = component_id
    content_groups = {}
    for member in source['raw_members']:
        content_groups.setdefault(member['sha256'], []).append(member)
    for members in content_groups.values():
        if len({component_map.get(m['author_group']) for m in members}) != 1:
            raise SourceEvidenceError('Identical raw members cannot cross split components')
    specs = []
    for member in source['raw_members']:
        raw_path = (root / member['path']).resolve()
        match = re.fullmatch(r'(Pulse|Driving_cycle)_data_temp(-?[0-9]+)_bat([0-9]+)\.CSV', raw_path.name)
        if not raw_path.is_relative_to(root / 'data/raw') or not match or member['crc_status'] != 'complete_member_crc_verified':
            raise SourceEvidenceError('Complete controlled original member identity required')
        number = int(match.group(3))
        if number != member['author_battery_number'] or not member['author_group'].endswith('_bat' + str(number)):
            raise SourceEvidenceError('Filename/author battery identity mismatch; no mixing')
        if raw_path.name != Path(member['archive_member_name']).name or member['author_group'] not in component_map:
            raise SourceEvidenceError('Archive/group provenance mismatch')
        spec = ZenodoMemberSpec(SOURCE_ID, raw_path, member['sha256'], member['crc32'], member['rows'],
            member['author_group'], number, component_map[member['author_group']], len(content_groups[member['sha256']]) > 1,
            member['archive_member_name'], registry, _sha(registry), metadata, source['license_evidence_sha256'],
            member['source_temperature_condition_degC'])
        _verify(spec, raw_path)
        specs.append(spec)
    return tuple(specs)


def _number(raw):
    try:
        number = float(raw)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _index(raw):
    try:
        number = Decimal(raw)
        return int(number) if number.is_finite() and number >= 0 and number == number.to_integral_value() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not all(COLUMNS[k] in reader.fieldnames for k in REQUIRED):
            raise SourceEvidenceError('Original time/current/voltage/step/cycle columns missing')
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise SourceEvidenceError('Duplicate original CSV headers cannot be mapped reliably')
        for source_row, raw in enumerate(reader, 1):
            malformed = None in raw or any(v is None for k, v in raw.items() if k is not None)
            extra = raw.pop(None, None)
            if extra is not None:
                raw['__extra_columns__'] = extra
            yield source_row, reader.line_num, raw, malformed


def _values(raw):
    return {name: (_index(raw.get(column)) if name in ('step', 'cycle', 'sequence') else _number(raw.get(column)))
            for name, column in COLUMNS.items()}


def _power_consistent(values):
    if any(values[k] is None for k in ('power', 'current', 'voltage')):
        return False
    expected = values['current'] * values['voltage']
    return abs(values['power'] - expected) <= SIGN_POLICY['power_absolute_tolerance_W'] + SIGN_POLICY['power_relative_tolerance'] * abs(expected)


def analyze_member(path, spec):
    """Infer convention only from a bidirectional trustworthy capacity subset.

    Power consistency alone grants no charging/discharging direction. Conflicts
    or insufficient bidirectional capacity evidence remain UNKNOWN.
    """
    raw_bytes = _verify(spec, path)
    counts = {'positive_current_charge': 0, 'negative_current_discharge': 0,
              'positive_current_discharge': 0, 'negative_current_charge': 0}
    power = {'consistent_rows': 0, 'missing_or_inconsistent_rows': 0}
    rows, previous, trusted_pairs = 0, None, 0
    eps = SIGN_POLICY['capacity_increment_threshold_Ah']
    for rows, line, raw, malformed in _rows(path):
        values = _values(raw)
        okay_power = _power_consistent(values)
        power['consistent_rows' if okay_power else 'missing_or_inconsistent_rows'] += 1
        sign_fields = ('time', 'current', 'voltage', 'step', 'cycle', 'sequence', 'power', 'charge', 'discharge')
        if previous is not None and not malformed and all(values[k] is not None and previous[k] is not None for k in sign_fields):
            dc, dd = values['charge'] - previous['charge'], values['discharge'] - previous['discharge']
            credible = (okay_power and _power_consistent(previous) and values['voltage'] > 0 and previous['voltage'] > 0 and
                values['sequence'] == previous['sequence'] + 1 and values['step'] == previous['step'] and
                values['cycle'] == previous['cycle'] and values['time'] > previous['time'] and
                abs(values['current']) > .01 and abs(previous['current']) > .01 and values['current'] * previous['current'] > 0 and
                dc >= -eps and dd >= -eps)
            if credible and ((dc > eps) != (dd > eps)):
                trusted_pairs += 1
                key = ('positive' if values['current'] > 0 else 'negative') + '_current_' + ('charge' if dc > eps else 'discharge')
                counts[key] += 1
        previous = values if not malformed else None
    if rows != spec.expected_rows:
        raise SourceEvidenceError('Full original member row count mismatch')
    minimum = SIGN_POLICY['minimum_trusted_observations_each_direction']
    positive_charge = counts['positive_current_charge'] >= minimum and counts['negative_current_discharge'] >= minimum
    positive_discharge = counts['positive_current_discharge'] >= minimum and counts['negative_current_charge'] >= minimum
    if positive_charge and counts['positive_current_discharge'] == counts['negative_current_charge'] == 0:
        convention = 'positive_charge'
    elif positive_discharge and counts['positive_current_charge'] == counts['negative_current_discharge'] == 0:
        convention = 'positive_discharge'
    else:
        convention = 'UNKNOWN'
    _verify(spec, path)
    return {'rows': rows, 'raw_bytes': raw_bytes, 'vendor_current_sign': convention,
            'normalization_status': 'PASS' if convention != 'UNKNOWN' else 'UNKNOWN',
            'capacity_direction_counts': counts, 'trusted_capacity_pairs': trusted_pairs, 'power_consistency': power,
            'sign_policy': SIGN_POLICY, 'metadata_sha256': spec.metadata_sha256,
            'reason': 'Bidirectional capacity increments support convention; Power only corroborates columns' if convention != 'UNKNOWN' else
                      'Insufficient or conflicting bidirectional capacity evidence; current_A remains null'}


def write_member_view(path, spec, out_dir, maximum_rows=2_000_000):
    """Write a complete per-member JSONL.gz view without changing raw data.

    Refuse overwrites. Failure artifacts remain incomplete. Rows with unknown
    direction retain vendor_current_A and null canonical current_A.
    """
    out_dir = Path(out_dir).resolve()
    if out_dir == Path(path).resolve() or out_dir.is_relative_to(spec.member_path.parent):
        raise ValueError('Output must not overlap the original raw member directory')
    out_dir.mkdir(parents=True, exist_ok=False)
    rows_written = 0
    try:
        analysis = analyze_member(path, spec)
        if analysis['rows'] > maximum_rows:
            raise ValueError('Explicit row limit exceeded')
        data_path = out_dir / 'observations.jsonl.gz'
        flag_counts, unknown_rows, context_index, context_counts = {}, 0, 0, {}
        previous = None
        with data_path.open('xb') as output, gzip.GzipFile(filename='', mode='wb', fileobj=output, compresslevel=1, mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding='utf-8', newline='\n') as stream:
                for source_row, line, raw, malformed in _rows(path):
                    values = _values(raw)
                    flags = []
                    if malformed:
                        flags.append('malformed_source_column_count')
                    for key in REQUIRED:
                        if values[key] is None:
                            flags.append('missing_or_nonfinite_' + key)
                    if values['temperature'] is None:
                        flags.append('temperature_not_measured')
                    if values['voltage'] is not None:
                        if values['voltage'] < 0:
                            flags.append('negative_original_voltage')
                        if values['voltage'] < 1.5 or values['voltage'] > 3.9:
                            flags.append('outside_authored_protocol_voltage_cutoffs')
                    if values['temperature'] is not None and values['temperature'] < -273.15:
                        flags.append('temperature_below_absolute_zero')
                    if not _power_consistent(values):
                        flags.append('power_column_missing_or_inconsistent')
                    if spec.duplicate_content:
                        flags.append('byte_identical_member_content')
                    if values['sequence'] is None or values['sequence'] != source_row:
                        flags.append('source_data_point_differs_from_original_row_order')
                    if previous is not None:
                        if values['time'] is not None and previous['time'] is not None:
                            if values['time'] == previous['time']:
                                flags.append('co_timed_original_record')
                                if values['step'] == previous['step'] and values['cycle'] == previous['cycle']:
                                    flags.append('co_timed_within_instrument_step')
                            elif values['time'] < previous['time']:
                                flags.append('original_test_time_reset')
                                context_index += 1
                        if values['cycle'] is not None and previous['cycle'] is not None and values['cycle'] < previous['cycle']:
                            flags.append('original_cycle_index_reset')
                            if 'original_test_time_reset' not in flags:
                                context_index += 1
                    convention = analysis['vendor_current_sign']
                    current = (-values['current'] if convention == 'positive_charge' else values['current']) if convention != 'UNKNOWN' and values['current'] is not None else None
                    if convention == 'UNKNOWN':
                        flags.append('current_direction_unknown')
                    normal = convention != 'UNKNOWN' and not malformed and all(values[k] is not None for k in REQUIRED)
                    normal &= values['temperature'] is None or values['temperature'] >= -273.15
                    unknown_rows += not normal
                    context = spec.member_sha256[:16] + ':' + spec.author_group + ':time_epoch_' + str(context_index)
                    context_counts[context] = context_counts.get(context, 0) + 1
                    for flag in flags:
                        flag_counts[flag] = flag_counts.get(flag, 0) + 1
                    temperature_K = None if values['temperature'] is None else float(Decimal(raw[COLUMNS['temperature']]) + Decimal('273.15'))
                    row = {'source_id': spec.source_id, 'member_sha256': spec.member_sha256, 'author_group': spec.author_group,
                        'conservative_split_component': spec.conservative_split_component, 'source_row': source_row,
                        'time_s': values['time'], 'current_A': current, 'voltage_V': values['voltage'], 'temperature_K': temperature_K,
                        'step_index': values['step'], 'cycle_index': values['cycle'], 'quality_flags': flags,
                        'context_id': context, 'vendor_current_A': values['current'], 'source_temperature_degC': values['temperature'],
                        'source_data_point': values['sequence'], 'csv_line_number': line, 'duplicate_content': spec.duplicate_content,
                        'normalization_status': 'PASS' if normal else 'UNKNOWN',
                        'source_values': {column: raw.get(column) for column in COLUMNS.values()}}
                    if '__extra_columns__' in raw:
                        row['source_values']['__extra_columns__'] = raw['__extra_columns__']
                    stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
                    rows_written += 1
                    previous = values
        _verify(spec, path)
        if rows_written != analysis['rows']:
            raise SourceEvidenceError('Complete row preservation failed')
        manifest = {'schema_version': 1, 'complete': True, 'source_id': spec.source_id, 'member_sha256': spec.member_sha256,
            'member_crc32': spec.member_crc32, 'raw_path': str(spec.member_path), 'raw_bytes': analysis['raw_bytes'],
            'archive_member_name': spec.archive_member_name, 'archive_md5_status': 'UNKNOWN', 'whole_archive_official_md5_verified': False,
            'row_count': rows_written, 'rows_dropped': 0, 'timestamps_shifted': 0, 'author_group': spec.author_group,
            'conservative_split_component': spec.conservative_split_component, 'duplicate_content': spec.duplicate_content,
            'physical_independence_status': 'UNKNOWN', 'independent_physical_cells': None,
            'observations': 'observations.jsonl.gz', 'observations_sha256': _sha(data_path), 'observations_bytes': data_path.stat().st_size,
            'contexts': context_counts, 'quality_flag_counts': flag_counts, 'unknown_row_count': unknown_rows,
            'normalization_status': 'PASS' if not unknown_rows else 'UNKNOWN', 'current_sign_evidence': analysis,
            'canonical_units': {'time': 's', 'current': 'A', 'voltage': 'V', 'temperature': 'K'},
            'canonical_current_sign': 'positive_discharge' if analysis['vendor_current_sign'] != 'UNKNOWN' else 'UNKNOWN',
            'source_temperature_condition_degC': spec.source_temperature_condition_degC,
            'source_temperature_condition_is_sensor': False, 'registry_sha256': spec.registry_sha256,
            'metadata_sha256': spec.metadata_sha256, 'external_model_validation': 'not_performed', 'D01_complete': False, 'D02_complete': False,
            'scope': 'Full original member canonical unit view; no interpolation, dataset splitting, fitting or operational acceptance'}
        (out_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return manifest
    except Exception as exc:
        failure = {'complete': False, 'rows_written': rows_written, 'error_type': type(exc).__name__, 'error': str(exc),
                   'member_sha256': spec.member_sha256, 'archive_md5_status': 'UNKNOWN', 'normalization_status': 'UNKNOWN'}
        (out_dir / 'failure.json').write_text(json.dumps(failure, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
