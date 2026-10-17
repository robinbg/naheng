"""Bounded CSV ingestion and measured electrical accounting, without model labels."""
from __future__ import annotations
import csv
import io
import math
from pathlib import Path
import re
import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from naheng.runtime.artifacts import atomic_json, code_hash, sha256_file

COLUMNS = ('timestamp_s', 'voltage_V', 'current_A', 'temperature_K')
UNITS = dict(zip(COLUMNS, ('s', 'V', 'A', 'K')))
LIMIT_BYTES = 2 * 1024 * 1024
LIMIT_ROWS = 5000

class DatasetImport(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    filename: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=500)
    chemistry_id: str = Field(min_length=1, max_length=80, pattern=r'^[a-zA-Z0-9_.-]+$')
    provenance_type: Literal['public_measurement', 'synthetic', 'reference_simulation']
    current_sign: Literal['positive_discharge', 'positive_charge']
    units: dict[str, str]
    csv_text: str = Field(min_length=1, max_length=LIMIT_BYTES)

def parse(request: DatasetImport):
    if len(request.csv_text.encode('utf-8')) > LIMIT_BYTES:
        raise ValueError('CSV exceeds the 2 MiB limit')
    if request.units != UNITS:
        raise ValueError('Explicit canonical units required: s, V, A, K')
    reader = csv.DictReader(io.StringIO(request.csv_text, newline=''))
    if reader.fieldnames != list(COLUMNS):
        raise ValueError('CSV header must be timestamp_s,voltage_V,current_A,temperature_K')
    rows = []
    for index, row in enumerate(reader, start=2):
        if len(rows) >= LIMIT_ROWS:
            raise ValueError('CSV exceeds the 5000 row limit')
        if set(row) != set(COLUMNS) or any(value is None for value in row.values()):
            raise ValueError(f'CSV row {index}: wrong field count')
        try:
            values = {key: float(row[key]) for key in COLUMNS}
        except (ValueError, TypeError):
            raise ValueError(f'CSV row {index}: numeric observations required') from None
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError(f'CSV row {index}: nonfinite observations rejected')
        if values['timestamp_s'] < 0 or values['temperature_K'] <= 0:
            raise ValueError(f'CSV row {index}: invalid time or absolute temperature')
        if rows and values['timestamp_s'] <= rows[-1]['timestamp_s']:
            raise ValueError(f'CSV row {index}: strictly increasing single-epoch time required')
        if request.current_sign == 'positive_charge': values['current_A'] *= -1
        rows.append(values)
    if len(rows) < 2:
        raise ValueError('At least two observations required for electrical accounting')
    return rows

def accounting(rows):
    charge = discharge = energy_charge = energy_discharge = 0.0
    for a, b in zip(rows, rows[1:]):
        dt = b['timestamp_s'] - a['timestamp_s']
        i0, di = a['current_A'], b['current_A'] - a['current_A']
        v0, dv = a['voltage_V'], b['voltage_V'] - a['voltage_V']
        cut = -i0 / di if di else -1
        bounds = [0, cut, 1] if 0 < cut < 1 else [0, 1]
        for lo, hi in zip(bounds, bounds[1:]):
            dq = dt * (i0*(hi-lo) + di*(hi*hi-lo*lo)/2)
            de = dt * (i0*v0*(hi-lo) + (i0*dv+di*v0)*(hi*hi-lo*lo)/2
                       + di*dv*(hi**3-lo**3)/3)
            if i0 + di*(lo+hi)/2 >= 0:
                discharge += dq; energy_discharge += de
            else:
                charge -= dq; energy_charge -= de
    values = [charge, discharge, energy_charge, energy_discharge]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Electrical accounting exceeds finite numeric range')
    return {'discharge_throughput_Ah': discharge/3600, 'charge_throughput_Ah': charge/3600,
        'discharge_port_energy_J': energy_discharge, 'charge_port_energy_J': energy_charge,
        'net_outward_port_energy_J': energy_discharge-energy_charge,
        'duration_s': rows[-1]['timestamp_s']-rows[0]['timestamp_s'],
        'voltage_range_V': [min(r['voltage_V'] for r in rows), max(r['voltage_V'] for r in rows)],
        'temperature_range_K': [min(r['temperature_K'] for r in rows), max(r['temperature_K'] for r in rows)],
        'method': 'Exact integration of piecewise-linear measured current and voltage; split current sign at zero',
        'scope': 'Measured-port reconstruction under interpolation; no unseen-pulse or sensor-error certificate',
        'capacity_Ah': None, 'SOH': None, 'RUL_s': None, 'risk_probability': None,
        'unknown_reason': 'Initialization/cutoff protocol, calibrated chemistry and uncertainty certificate unavailable',
        'independent_operating_n': 0}

def save(root: Path, request: DatasetImport):
    rows = parse(request)
    result = accounting(rows)
    identifier = 'ds-' + uuid.uuid4().hex
    directory = root/'artifacts/datasets'/identifier
    directory.mkdir(parents=True, exist_ok=False)
    (directory/'source.csv').write_bytes(request.csv_text.encode('utf-8'))
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=COLUMNS)
    writer.writeheader(); writer.writerows(rows)
    (directory/'observations.csv').write_text(stream.getvalue(), encoding='utf-8', newline='')
    packet = {'dataset_id': identifier, 'code_hash': code_hash(root), 'row_count': len(rows),
        'source': request.source, 'filename': request.filename, 'chemistry_id': request.chemistry_id,
        'provenance_type': request.provenance_type, 'provenance_verification': 'user_declared_unverified',
        'source_current_sign': request.current_sign, 'canonical_current_sign': 'positive_discharge',
        'units': UNITS, 'source_csv_sha256': sha256_file(directory/'source.csv'),
        'observations': rows, 'analysis': result, 'mode': 'measured_data_analysis',
        'model_assimilation': {'status': 'unknown', 'reason': 'No verified mapping to the research model; observations were not used as synthetic truth'}}
    atomic_json(directory/'analysis.json', packet)
    from naheng.api.reports import dataset_report
    (directory/'report.html').write_text(dataset_report(packet), encoding='utf-8')
    files = {'source': 'source.csv', 'observations': 'observations.csv', 'analysis': 'analysis.json', 'report': 'report.html'}
    atomic_json(directory/'manifest.json', {'dataset_id': identifier, 'artifacts': files,
        'sha256': {key: sha256_file(directory/name) for key, name in files.items()}})
    return packet

def directory_for(root: Path, identifier: str):
    if not re.fullmatch(r'ds-[0-9a-f]{32}', identifier): raise KeyError('Unknown dataset')
    directory = root/'artifacts/datasets'/identifier
    if not (directory/'manifest.json').is_file(): raise KeyError('Unknown dataset')
    return directory

def artifact(root: Path, identifier: str, key: str):
    import json
    directory = directory_for(root, identifier)
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('dataset_id') != identifier: raise ValueError('Dataset identity changed')
    files = {'source': 'source.csv', 'observations': 'observations.csv', 'analysis': 'analysis.json', 'report': 'report.html'}
    if key not in files or manifest.get('artifacts') != files: raise KeyError('Unknown dataset artifact')
    path = directory/files[key]
    if sha256_file(path) != manifest.get('sha256', {}).get(key): raise ValueError('Dataset artifact checksum changed')
    return path

def read(root: Path, identifier: str):
    import json
    # Verify the raw source as well as the derived packet, on every reopen.
    artifact(root, identifier, 'source')
    packet = json.loads(artifact(root, identifier, 'analysis').read_text(encoding='utf-8'))
    if packet.get('dataset_id') != identifier: raise ValueError('Dataset packet identity changed')
    return packet
