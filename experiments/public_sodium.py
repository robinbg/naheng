"""Frozen public sodium voltage-transfer pilot. No physical-cell certification.

The only learned predictor is fixed ridge regression of V_next - V_now using
V_now, I_now, T_now and the previous sampling interval. Neither the target's
current/temperature nor its sampling interval enters a feature. Training uses
only unique raw contents in the immutable train role. Validation/test are read
after the model is persisted and never tune the predictor or eligibility rule.
"""
from __future__ import annotations
import argparse
from collections import Counter, deque
from dataclasses import asdict, dataclass
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import time
from typing import Iterator
import numpy as np
import yaml
from naheng.runtime.artifacts import code_hash as current_code_hash


@dataclass(frozen=True)
class PilotConfig:
    ridge_alpha: float = 1.0
    max_gap_s: float = 60.0
    batch_rows: int = 4096

    def __post_init__(self):
        if isinstance(self.ridge_alpha, bool) or not math.isfinite(self.ridge_alpha) or self.ridge_alpha <= 0:
            raise ValueError('ridge_alpha must be finite and positive')
        if isinstance(self.max_gap_s, bool) or not math.isfinite(self.max_gap_s) or self.max_gap_s <= 0:
            raise ValueError('max_gap_s must be finite and positive')
        if isinstance(self.batch_rows, bool) or not isinstance(self.batch_rows, int) or not 16 <= self.batch_rows <= 65536:
            raise ValueError('batch_rows must be an integer from 16 through 65536')


class InputDependencyError(ValueError):
    """Input/licence/unit/identity is missing or no longer binds to frozen bytes."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def within(root: Path, value: str | Path) -> Path:
    p = Path(value)
    p = (p if p.is_absolute() else root / p).resolve()
    if not p.is_relative_to(root):
        raise InputDependencyError('Registered input must remain within the project root: ' + str(value))
    return p


def bind_ref(root: Path, ref: dict, bindings: dict[str, str]) -> Path:
    if not isinstance(ref, dict) or not isinstance(ref.get('path'), str) or not isinstance(ref.get('sha256'), str):
        raise InputDependencyError('Explicit path and SHA256 are required')
    p = within(root, ref['path'])
    if not p.is_file() or sha256(p) != ref['sha256']:
        raise InputDependencyError('Missing or changed registered bytes: ' + ref['path'])
    bindings[p.relative_to(root).as_posix()] = ref['sha256']
    return p


def validate_frozen_roles(split: dict, policy: dict, catalog: dict) -> None:
    """Pure metadata gate: existing catalog and predeclared component roles."""
    if policy.get('catalog_sha256') != split['catalog_ref']['sha256'] or catalog.get('cohort_id') != split.get('cohort_id'):
        raise InputDependencyError('Policy/catalog/cohort identities disagree')
    candidates = policy.get('explicit_candidate_roles')
    if not isinstance(candidates, dict) or set(candidates) != {'train', 'validation', 'test'}:
        raise InputDependencyError('Explicit predeclared frozen component roles are required')
    registered = {m['member_id']: m for m in catalog['members']}
    if len(registered) != len(catalog['members']) or set(registered) != {m['member_id'] for m in split['members']}:
        raise InputDependencyError('Frozen split must retain every catalog member exactly once')
    for member in split['members']:
        original = registered[member['member_id']]
        for key in ('source_id', 'author_group', 'raw', 'observations', 'view_manifest', 'row_count', 'protocol', 'nominal_capacity_Ah'):
            if member[key] != original[key]:
                raise InputDependencyError('Catalog member identity or complete payload changed: '+member['member_id'])
        if member['role'] not in candidates or member['leakage_component_id'] != candidates[member['role']]:
            raise InputDependencyError('Frozen member/component role reassignment is forbidden')
        if member.get('original_row_range') != [1, member['row_count']]:
            raise InputDependencyError('A partial original row range is forbidden')


def validate_inputs(root: Path, manifest: Path) -> tuple[dict, dict, dict[str, str]]:
    bindings = {manifest.relative_to(root).as_posix(): sha256(manifest)}
    split = read_json(manifest)
    if split.get('kind') != 'frozen_complete_member_provenance_partition' or split.get('schema_version') != 1:
        raise InputDependencyError('A supported frozen complete-member provenance partition is required')
    active_path = root / 'data/manifests/public_sodium.yaml'
    if not active_path.is_file():
        raise InputDependencyError('The active accepted-cohort trust anchor is missing')
    active = read_json(active_path)['current_cohort']
    bindings[active_path.relative_to(root).as_posix()] = sha256(active_path)
    if not (active.get('D01_engineering_complete') is True and active['frozen_split_ref']['sha256'] == sha256(manifest)
            and active['cohort_id'] == split['cohort_id']):
        raise InputDependencyError('Manifest is not the exact currently accepted frozen cohort')
    for key in ('catalog_ref', 'policy_ref'):
        bind_ref(root, split[key], bindings)
    validate_frozen_roles(split, read_json(within(root, split['policy_ref']['path'])),
                          read_json(within(root, split['catalog_ref']['path'])))
    for ref in split['protected_refs']:
        bind_ref(root, ref, bindings)
    for path, h in split['public_source_hashes'].items():
        bind_ref(root, {'path': path, 'sha256': h}, bindings)
    registry_path = root / 'data/manifests/sources.yaml'
    if registry_path.relative_to(root).as_posix() not in bindings:
        raise InputDependencyError('Frozen source registry identity is missing')
    registry = read_json(registry_path)
    sources = {s['source_id']: s for s in registry['sources']}
    members = split['members']
    if not members or len(set(m['member_id'] for m in members)) != len(members):
        raise InputDependencyError('Unique complete-member identities are required')
    component_roles: dict[str, set] = {}; content_roles: dict[str, set] = {}
    rowcounts = Counter(); declared = Counter()
    for member in members:
        role = member['role']
        if role not in ('train', 'validation', 'test'):
            raise InputDependencyError('Unknown frozen role')
        component_roles.setdefault(member['leakage_component_id'], set()).add(role)
        content_roles.setdefault(member['raw']['sha256'], set()).add(role)
        rowcounts[role] += member['row_count']
        source = sources.get(member['source_id'])
        if source is None or source.get('kind') != 'public_measurement' or source.get('license_id') != 'CC-BY-4.0':
            raise InputDependencyError('This pilot requires the explicitly licensed public measurement source')
        bind_ref(root, source['author_metadata'], bindings)
        for refkey in ('raw', 'observations', 'view_manifest'):
            bind_ref(root, member[refkey], bindings)
        vm = read_json(within(root, member['view_manifest']['path']))
        if not (vm.get('complete') is True and vm['member_sha256'] == member['raw']['sha256']
                and vm['observations_sha256'] == member['observations']['sha256']
                and vm['source_id'] == member['source_id'] and vm['author_group'] == member['author_group']
                and vm['conservative_split_component'] == member['leakage_component_id']
                and vm['row_count'] == member['row_count'] and vm['rows_dropped'] == 0
                and vm['canonical_units'] == {'time': 's', 'current': 'A', 'voltage': 'V', 'temperature': 'K'}
                and vm['canonical_current_sign'] == 'positive_discharge'
                and vm['current_sign_evidence']['vendor_current_sign'] == 'positive_charge'):
            raise InputDependencyError('Raw/view/source/row/unit/current-sign binding is incomplete: ' + member['member_id'])
        declared[role] += 1
    if any(len(r) != 1 for r in component_roles.values()) or any(len(r) != 1 for r in content_roles.values()):
        raise InputDependencyError('Provenance or byte-identical content crosses frozen roles')
    if dict(rowcounts) != split['role_row_counts'] or sum(rowcounts.values()) != split['total_rows']:
        raise InputDependencyError('Frozen role row counts disagree')
    if set(declared) != {'train', 'validation', 'test'}:
        raise InputDependencyError('Train, validation and test roles must all be explicitly present')
    return split, sources, bindings


def finite_number(row: dict, key: str):
    value = row.get(key)
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def causal_window(previous: dict, now: dict, target: dict, member: dict, config: PilotConfig):
    """Return only prefix features; target-time data determines eligibility only."""
    for row in (previous, now, target):
        if not (row.get('source_id') == member['source_id'] and row.get('member_sha256') == member['raw']['sha256']
                and row.get('author_group') == member['author_group']
                and row.get('conservative_split_component') == member['leakage_component_id']):
            return None, 'identity_mismatch'
    if not (previous.get('context_id') == now.get('context_id') == target.get('context_id')):
        return None, 'trajectory_boundary'
    for row in (previous, now, target):
        if not finite_number(row, 'time_s') or row['time_s'] <= 0:
            return None, 'invalid_or_nonpositive_time'
    if not (finite_number(now, 'voltage_V') and finite_number(now, 'current_A')
            and finite_number(now, 'temperature_K') and now['temperature_K'] > 0
            and finite_number(target, 'voltage_V')):
        return None, 'invalid_prefix_feature_or_voltage_target'
    indices = [row.get('source_row') for row in (previous, now, target)]
    if any(not isinstance(x, int) or isinstance(x, bool) or x <= 0 for x in indices):
        return None, 'invalid_source_row'
    if not (indices[1] == indices[0] + 1 and indices[2] == indices[1] + 1):
        return None, 'source_sequence_gap'
    dt_previous = now['time_s'] - previous['time_s']
    dt_target = target['time_s'] - now['time_s']
    if dt_previous <= 0 or dt_target <= 0:
        return None, 'nonincreasing_time'
    if dt_previous > config.max_gap_s or dt_target > config.max_gap_s:
        return None, 'sampling_gap_above_predeclared_limit'
    x = [float(now['voltage_V']), float(now['current_A']), float(now['temperature_K']), float(dt_previous)]
    # Neither I_target/T_target nor dt_target appears in x.
    return (x, float(target['voltage_V'] - now['voltage_V']), dt_target), None


def iter_windows(root: Path, member: dict, config: PilotConfig, accounting: dict | None = None) -> Iterator:
    rows = 0; accepted = 0; reasons = Counter(); history: deque = deque(maxlen=3)
    with gzip.open(within(root, member['observations']['path']), 'rt', encoding='utf-8') as source:
        for line in source:
            rows += 1
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                history.clear(); reasons['malformed_canonical_json'] += 1; continue
            if not isinstance(row, dict):
                history.clear(); reasons['malformed_canonical_object'] += 1; continue
            history.append(row)
            if len(history) < 3:
                reasons['insufficient_two_row_prefix'] += 1; continue
            previous, now, target = history
            window, reason = causal_window(previous, now, target, member, config)
            if reason is not None:
                reasons[reason] += 1; continue
            accepted += 1
            yield window, previous, now, target
    if rows != member['row_count']:
        raise InputDependencyError('Canonical member row count changed: ' + member['member_id'])
    if accounting is not None:
        accounting.update(original_rows=rows, eligible_windows=accepted, ineligible_windows=dict(reasons))


def batches(values: Iterator, size: int):
    bucket = []
    for value in values:
        bucket.append(value)
        if len(bucket) == size:
            yield bucket; bucket = []
    if bucket:
        yield bucket


def training_members(split: dict) -> tuple[list[dict], list[dict]]:
    selected = []; duplicates = []; seen = set()
    for member in split['members']:
        if member['role'] != 'train':
            continue
        if member['raw']['sha256'] in seen:
            duplicates.append(member)
        else:
            selected.append(member); seen.add(member['raw']['sha256'])
    return selected, duplicates


def train_fixed_predictor(root: Path, members: list[dict], config: PilotConfig) -> dict:
    """Two streaming train-only passes; fixed four features and ridge penalty."""
    if any(member.get('role') != 'train' for member in members):
        raise InputDependencyError('Predictor fitting may consume only the train role')
    if len(set(member['raw']['sha256'] for member in members)) != len(members):
        raise InputDependencyError('Byte-identical train contents must be deduplicated before fitting')
    n = 0; mean = np.zeros(4); m2 = np.zeros(4); accounting = []
    for member in members:
        counts = {'member_id': member['member_id']}
        for batch in batches(iter_windows(root, member, config, counts), config.batch_rows):
            x = np.asarray([b[0][0] for b in batch], dtype=float)
            bn = len(x); bm = x.mean(axis=0); bm2 = ((x - bm) ** 2).sum(axis=0)
            delta = bm - mean; total = n + bn
            m2 += bm2 + delta * delta * (n * bn / total)
            mean += delta * bn / total; n = total
        accounting.append(counts)
    if n < 5:
        raise InputDependencyError('Insufficient eligible train-only windows')
    scale = np.sqrt(m2 / n); scale[scale < 1e-12] = 1.0
    gram = np.zeros((5, 5)); cross = np.zeros(5); y_squared = 0.; y_sum = 0.; second_count = 0
    for member in members:
        for batch in batches(iter_windows(root, member, config), config.batch_rows):
            x = np.asarray([b[0][0] for b in batch], dtype=float)
            y = np.asarray([b[0][1] for b in batch], dtype=float)
            design = np.column_stack((np.ones(len(x)), (x - mean) / scale))
            gram += design.T @ design; cross += design.T @ y
            y_squared += float(y @ y); y_sum += float(y.sum()); second_count += len(y)
    if second_count != n:
        raise InputDependencyError('Train-only passes disagree')
    regularizer = np.diag([0., config.ridge_alpha, config.ridge_alpha, config.ridge_alpha, config.ridge_alpha])
    coefficients = np.linalg.solve(gram + regularizer, cross)
    if not np.isfinite(coefficients).all():
        raise InputDependencyError('Nonfinite train-only predictor')
    squared_error = max(0., y_squared - 2 * float(coefficients @ cross) + float(coefficients @ gram @ coefficients))
    return {'model': 'fixed_train_only_ridge_delta_voltage', 'feature_names': ['V_now_V', 'I_now_A', 'T_now_K', 'dt_previous_s'],
            'target': 'V_next_V - V_now_V', 'feature_mean': mean.tolist(), 'feature_scale': scale.tolist(),
            'coefficients_intercept_then_features': coefficients.tolist(), 'ridge_alpha': config.ridge_alpha,
            'intercept_regularized': False, 'fit_window_count': n, 'fit_accounting': accounting,
            'fit_RMSE_from_training_moments_V': math.sqrt(squared_error / n),
            'last_value_training_RMSE_from_moments_V': math.sqrt(y_squared / n),
            'target_delta_mean_V': y_sum / n,
            'train_normal_equation_gram': gram.tolist(), 'train_normal_equation_cross': cross.tolist(),
            'fixed_before_evaluation': True, 'heldout_tuning': False,
            'scope': 'Transparent empirical next-recorded-voltage predictor; no SOC/SOH/material parameter inference or physical simulator'}


class ErrorMetrics:
    def __init__(self):
        self.n = 0; self.abs = 0.; self.sq = 0.; self.bias = 0.; self.maximum = 0.
    def add(self, errors):
        a = np.asarray(errors, dtype=float)
        if not np.isfinite(a).all():
            raise InputDependencyError('Nonfinite forecast errors')
        self.n += len(a); self.abs += float(np.abs(a).sum()); self.sq += float(a @ a)
        self.bias += float(a.sum()); self.maximum = max(self.maximum, float(np.abs(a).max(initial=0.)))
    def result(self):
        return {'target_rows': self.n, 'MAE_V': self.abs / self.n if self.n else None,
                'RMSE_V': math.sqrt(self.sq / self.n) if self.n else None,
                'mean_error_V': self.bias / self.n if self.n else None, 'max_absolute_error_V': self.maximum if self.n else None,
                'no_IID_or_independent_cell_claim': True}


def evaluate_member(root: Path, member: dict, model: dict, config: PilotConfig, writer, role_metrics: dict) -> dict:
    accounting = {'member_id': member['member_id'], 'role': member['role']}
    mean = np.asarray(model['feature_mean']); scale = np.asarray(model['feature_scale'])
    coefficients = np.asarray(model['coefficients_intercept_then_features'])
    own = {k: ErrorMetrics() for k in ('ridge', 'last_value', 'unflagged_ridge', 'unflagged_last_value')}
    quality = Counter(); horizon = ErrorMetrics()
    for batch in batches(iter_windows(root, member, config, accounting), config.batch_rows):
        x = np.asarray([b[0][0] for b in batch]); delta = np.asarray([b[0][1] for b in batch])
        design = np.column_stack((np.ones(len(x)), (x - mean) / scale))
        predicted_delta = design @ coefficients
        errors = predicted_delta - delta; last_errors = -delta
        own['ridge'].add(errors); own['last_value'].add(last_errors)
        role_metrics['ridge'].add(errors); role_metrics['last_value'].add(last_errors)
        clean = []
        for i, (window, previous, now, target) in enumerate(batch):
            flags = sorted(set(previous.get('quality_flags', []) + now.get('quality_flags', []) + target.get('quality_flags', [])))
            quality.update(flags)
            if not flags: clean.append(i)
            writer.writerow([member['role'], member['member_id'], member['source_id'], member['raw']['sha256'],
                member['author_group'], member['leakage_component_id'], now['context_id'], previous['source_row'],
                now['source_row'], target['source_row'], previous['time_s'], now['time_s'], target['time_s'],
                window[0][0], window[0][1], window[0][2], window[0][3], window[2], target['voltage_V'],
                float(x[i, 0] + predicted_delta[i]), float(x[i, 0]), float(errors[i]), float(last_errors[i]), json.dumps(flags)])
        if clean:
            own['unflagged_ridge'].add(errors[clean]); own['unflagged_last_value'].add(last_errors[clean])
            role_metrics['unflagged_ridge'].add(errors[clean]); role_metrics['unflagged_last_value'].add(last_errors[clean])
        horizon.add([b[0][2] for b in batch])
    accounting.update(metrics={k:v.result() for k,v in own.items()}, quality_flag_target_window_counts=dict(quality),
        target_gap_summary={'count':horizon.n,'mean_s':horizon.bias/horizon.n if horizon.n else None,'max_s':horizon.maximum if horizon.n else None},
        unflagged_sensitivity='Declared sensitivity only; all eligible flagged rows are retained in primary metrics')
    return accounting


def reference_difference_scope(root: Path, sources: dict, bindings: dict) -> dict:
    config_path = root / 'configs/models/reference_sodium.yaml'
    manifest_path = root / 'artifacts/reference_smoke/verified/manifest.json'
    # YAML is kept as bytes/evidence; the real saved trace records exact parameters.
    for p in (config_path, root/'src/naheng/models/reference_pybamm.py', manifest_path):
        if not p.is_file():
            raise InputDependencyError('Required reference difference metadata is missing: ' + str(p))
        bindings[p.relative_to(root).as_posix()] = sha256(p)
    mf = read_json(manifest_path)
    for ref in mf['artifacts'].values():bind_ref(root, ref, bindings)
    trace = read_json(within(root, mf['artifacts']['trace']['path']))
    reference_config = yaml.safe_load(config_path.read_text(encoding='utf-8-sig'))
    if trace.get('status') != 'completed' or trace.get('provenance_type') != 'reference_simulation' or trace.get('public_measurement') is not False:
        raise InputDependencyError('A separate actual saved reference simulation is required')
    return {'status': 'scientifically_blocked_same_cell_comparison', 'new_reference_solver_runs': 0,
       'stored_trace': mf['artifacts']['trace'], 'reference_source_id': trace['source_id'],
       'reference_chemistry_id': trace['chemistry_id'], 'reference_parameter_revision': trace['parameter_revision'],
       'reference_backend_version': trace['backend_version'], 'reference_nominal_capacity_Ah': reference_config['nominal_capacity']['value'],
       'reference_nominal_capacity_evidence': 'configs/models/reference_sodium.yaml: source_geometry_only',
       'public_chemistry_ids': sorted(set(sources[m]['chemistry_id'] for m in sources if sources[m].get('kind')=='public_measurement' and m.startswith('zenodo13836819'))),
       'reference_domain': trace['supported_execution_domain'], 'reference_capabilities': trace['capabilities'],
       'blockers': ['Public electrodes/electrolyte and fixture-to-DFN parameter/initial-state mapping are unconfirmed',
           '0.003Ah hard-carbon/NVPF/NaPF6-EC-PC source geometry is not the public 3.2Ah or 10Ah author group',
           'Current reference adapter only accepts constant positive discharge, 0<C_rate<=1, prescribed298.15K; public traces are bipolar variable current with measured varying temperature',
           'The train-only empirical voltage predictor has no physical two-site-to-DFN mapping'],
       'shared_control_reference_assumptions_and_blindspots': trace['limitations'],
       'same_cell_voltage_residual_calculated': False, 'same_chemistry_fit_claimed': False,
       'zero_residual_substitution': False}


PREDICTION_HEADER = ['role','member_id','source_id','raw_sha256','author_group','leakage_component_id','context_id',
    'previous_source_row','now_source_row','target_source_row','previous_time_s','now_time_s','target_time_s',
    'feature_V_now_V','feature_I_now_A','feature_T_now_K','feature_dt_previous_s','target_gap_s_reporting_only',
    'measured_V_next_V','ridge_V_next_V','last_value_V_next_V','ridge_error_V','last_value_error_V','quality_flags']


def run_public_sodium_pilot(root: Path, manifest: Path, output: Path, config: PilotConfig | None = None) -> dict:
    root = root.resolve(); manifest = within(root, manifest); output = within(root, output)
    config = config or PilotConfig()
    if not output.is_relative_to(root/'artifacts'):
        raise ValueError('Pilot output must be a new controlled project artifacts directory')
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    global_code_before = current_code_hash(root)
    module_source = Path(__file__).resolve()
    module_sha_before = sha256(module_source)
    report = {'protocol_version':1,'started_at_utc':datetime.now(timezone.utc).isoformat(),
       'config':asdict(config),'execution_completed':False,'voltage_transfer_pilot_completed':False,
       'D02_complete':False,'scientific_external_acceptance_passed':False,'UI_tested':False,
       'status':'partial','exit_code':2,'scope':'Causal empirical voltage method transfer on frozen provenance roles',
       'new_model_type':'fixed_train_only_empirical_voltage_predictor', 'new_physical_model_or_PF_runs':0,
       'new_Lean_runs':0,'new_reference_solver_runs':0,'downloads':0,'missing_dependencies':[]}
    report.update(code_hash=global_code_before, module_source_sha256=module_sha_before,
                  module_source_path=module_source.relative_to(root).as_posix(), source_current=False)
    bindings = {}
    try:
        split, sources, bindings = validate_inputs(root, manifest)
        reference = reference_difference_scope(root, sources, bindings)
        train, duplicates = training_members(split)
        train_sources = [m['member_id'] for m in train]
        protocol = {'feature_names':['V_now_V','I_now_A','T_now_K','dt_previous_s'],
            'forbidden_features':['V_next','I_next','T_next','dt_next','hidden_SOC','future_capacity_or_protocol_label'],
            'known_future_observation_schedule_assumed':False,'target':'next recorded measured voltage',
            'config':asdict(config),'tuning_roles':[],'training_role':'train','evaluation_roles':['validation','test'],
            'frozen_manifest':{'path':manifest.relative_to(root).as_posix(),'sha256':sha256(manifest)},
            'train_member_ids_used':train_sources,'duplicate_train_member_ids_not_fit_again':[m['member_id'] for m in duplicates],
            'deduplication':'Exact raw byte content SHA only, within train; frozen roles/component assignments unchanged',
            'role_row_counts':split['role_row_counts'],'eligibility':'Three consecutive source rows in same context; positive strictly increasing finite time; finite prefix features/voltage target; both gaps<=fixed60s default; negative measured voltage and other quality flags retained',
            'measurement_units':{'time':'s','current':'A','voltage':'V','temperature':'K'},
            'current_sign':'positive_discharge, converted from verified vendor positive_charge; no physical commands executed',
            'temperature':'Actual Aux_Temperature_1(C)+273.15; filename chamber condition is not the sensor',
            'registered_bindings':bindings}
        write_json(output/'protocol-preregistered.json',protocol)
        model = train_fixed_predictor(root, train, config)
        model.update(train_member_ids=train_sources, train_member_raw_sha256=[m['raw']['sha256'] for m in train],
            split_sha256=sha256(manifest), protocol_sha256=sha256(output/'protocol-preregistered.json'))
        write_json(output/'model-frozen-before-heldout.json',model)
        model_hash = sha256(output/'model-frozen-before-heldout.json')
        evaluations=[]; role_results={}
        for role in ('validation','test'):
            accumulators={k:ErrorMetrics() for k in ('ridge','last_value','unflagged_ridge','unflagged_last_value')}
            predictions=output/(role+'-predictions.csv.gz')
            with predictions.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as gz:
                with io.TextIOWrapper(gz,encoding='utf-8',newline='') as stream:
                    writer=csv.writer(stream);writer.writerow(PREDICTION_HEADER)
                    for member in split['members']:
                        if member['role']==role:
                            evaluations.append(evaluate_member(root,member,model,config,writer,accumulators))
            role_results[role]={'metrics':{k:v.result() for k,v in accumulators.items()},
                'predictions':{'path':predictions.relative_to(root).as_posix(),'sha256':sha256(predictions)},
                'role_not_reassigned':True,'used_for_training_or_selection':False}
            if accumulators['ridge'].n==0:
                raise InputDependencyError('No eligible heldout target rows for role '+role)
        if sha256(output/'model-frozen-before-heldout.json')!=model_hash:
            raise InputDependencyError('Frozen predictor changed during heldout evaluation')
        for path,h in bindings.items():
            if sha256(within(root,path))!=h:
                raise InputDependencyError('Registered source changed during actual experiment: '+path)
        if current_code_hash(root)!=global_code_before or sha256(module_source)!=module_sha_before:
            raise InputDependencyError('Current project or experiment module source changed during calculation')
        report.update(execution_completed=True,voltage_transfer_pilot_completed=True,
            source_provenance_type='public_measurement',frozen_cohort_id=split['cohort_id'],
            original_row_count=split['total_rows'],complete_member_count=len(split['members']),
            unique_raw_content_count=len(set(m['raw']['sha256'] for m in split['members'])),
            independent_physical_cell_count=split['confirmed_independent_physical_cells'],
            physical_independence_status=split['physical_independence_status'],
            IID=split['IID'],strict_protocol_heldout=split['strict_protocol_heldout'],
            model={'path':(output/'model-frozen-before-heldout.json').relative_to(root).as_posix(),'sha256':model_hash},
            train_fit_window_count=model['fit_window_count'],train_accounting=model['fit_accounting'],
            train_duplicate_original_rows_not_fit_again=sum(m['row_count'] for m in duplicates),
            frozen_role_row_counts=split['role_row_counts'],heldout_results=role_results,heldout_member_accounting=evaluations,
            reference_difference=reference,protected_inputs_unchanged=True,registered_bindings=bindings,source_current=True,
            missing_dependencies=reference['blockers'],
            result_interpretation='Actual causal voltage prediction errors on known correlated source rows; model and last-value baseline receive the same prefix information. No leading-model conclusion is prewritten.',
            scientific_limits=['Rows and author provenance groups are not independent physical-cell replicates or risk-certificate N',
                'Pulse test shares protocol/temperature conditions with train; Driving validation transfer stays validation',
                'No audited capacity/impedance/aging/SOC/SOH/RUL/fire/accident/profit target is manufactured',
                'No statistical coverage, operational probability or whole-product delivery acceptance is claimed',
                'Actual flags remain in primary heldout metrics; unflagged metrics are a separately declared sensitivity',
                'The future observation schedule is unknown; target gap is only eligibility/reporting, never a model feature'])
    except (InputDependencyError, KeyError, ValueError, OSError, np.linalg.LinAlgError) as error:
        report['missing_dependencies'].append(str(error))
        report['execution_failure_or_missing_metadata']=type(error).__name__
        report['registered_bindings']=bindings
    report['elapsed_s']=time.monotonic()-started
    report['code_hash_after']=current_code_hash(root)
    report['finished_at_utc']=datetime.now(timezone.utc).isoformat()
    write_json(output/'report.json',report)
    source=Path(__file__).resolve()
    (output/'pilot-source.py.txt').write_bytes(source.read_bytes())
    manifest_out={'exit_code':report['exit_code'],'report':{'path':(output/'report.json').relative_to(root).as_posix(),'sha256':sha256(output/'report.json')},
       'pilot_source_sha256':sha256(source),'code_hash':global_code_before,'source_current':report['source_current'],
       'execution_completed':report['execution_completed'],
       'D02_complete':False,'scope':'Partial public sodium voltage-transfer pilot; missing same-cell physical reference mapping remains explicit'}
    write_json(output/'manifest.json',manifest_out)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=run_public_sodium_pilot(args.root,args.manifest,args.output)
    print(json.dumps({'exit_code':report['exit_code'],'execution_completed':report['execution_completed'],
       'voltage_transfer_pilot_completed':report['voltage_transfer_pilot_completed'],
       'report':str(args.output/'report.json'),'D02_complete':False,'elapsed_s':report['elapsed_s']}))
    return report['exit_code']


if __name__=='__main__':
    raise SystemExit(main())
