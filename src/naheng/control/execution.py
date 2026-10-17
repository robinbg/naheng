"""Native numerical V/T operational stopping with unchanged physical dynamics.

Call only inside a caller-owned bounded worker after source/package/admission
verification. Receipts contain actual execution parameters/state information;
sampled-world details belong in private evaluator/operator storage, never in a
controller or observation input. SOC/DoD checks are initial and trace based.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import math
import time

import numpy as np

from naheng.control.mpc import MPCParameters
from naheng.domain.contracts import Action
from naheng.models.site_model import IntegrationResult, SiteModel
from naheng.packages.registry import content_hash as parameter_content_hash

STOP_FIELDS = ('voltage_min_V', 'voltage_max_V', 'temperature_min_K', 'temperature_max_K')


@dataclass(frozen=True)
class GuardedExecutionResult:
    result: IntegrationResult
    receipt: dict


class GuardedExecutionRejected(ValueError):
    def __init__(self, reason, receipt=None):
        self.receipt = {**(receipt or {}), 'status': 'rejected', 'reason': reason,
                        'solver_calls': 0, 'executed': False}
        super().__init__(reason)


def _number(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.floating, np.integer)) or not math.isfinite(value):
        raise GuardedExecutionRejected(name + ' must be finite and nonboolean')
    return float(value)


def _pair(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise GuardedExecutionRejected('Explicit ' + name + ' bounds required')
    low, high = (_number(v, name) for v in value)
    if low >= high:
        raise GuardedExecutionRejected('Empty or reversed ' + name + ' bounds')
    return low, high


def _band_limit(soc, current, parameters, package_limit):
    lower, matching = 0., []
    for upper, charge, discharge in parameters.soc_bands:
        if lower - 1e-12 <= soc <= upper + 1e-12:
            matching.append(charge if current < 0 else discharge)
        lower = upper
    return min(parameters.current_limit_A, package_limit, *matching) if matching else 0.


def integrate_guarded_action(model, state, action, package, parameters, ambient_K):
    """Integrate the original command with common explicit operational cutoffs.

Fixed-policy and voltage_margin_V prediction reserves are deliberately excluded
from operational stop fields. Caller must pass common execution parameters to
all families and retains cumulative DoD responsibility across calls. Exceptions
before launch have a rejection receipt, never a substitute zero-current action.
"""
    started = time.monotonic()
    if type(model) is not SiteModel or not isinstance(action, Action) or not isinstance(parameters, MPCParameters):
        raise GuardedExecutionRejected('Builtin SiteModel, typed Action and MPCParameters required')
    if not isinstance(package, dict) or not isinstance(package.get('domain'), dict) or not isinstance(package.get('parameters'), dict):
        raise GuardedExecutionRejected('Explicit registered package parameters and domain required')
    for name in ('start_s', 'duration_s', 'thermal_W'):
        _number(getattr(action, name), 'action.' + name)
    if action.current_A is not None:
        _number(action.current_A, 'action.current_A')
    action = Action.model_validate(deepcopy(action.model_dump(mode='python')))
    if action.current_A is None:
        raise GuardedExecutionRejected('Current-mode action required; power conversion needs a verified adapter')
    current = _number(action.current_A, 'current_A')
    ambient = _number(ambient_K, 'ambient_K')
    parameters = MPCParameters(**asdict(parameters))
    for name in ('current_limit_A', 'soc_min', 'soc_max', 'max_dod', 'thermal_min_W', 'thermal_max_W'):
        _number(getattr(parameters, name), 'parameters.' + name)
    domain, registered = package['domain'], package['parameters']
    if domain.get('provenance_type') != 'synthetic' or model.params.model_kind != 'theory_fixture':
        raise GuardedExecutionRejected('This guarded SiteModel backend is declared synthetic only')
    if any(package.get('state_definition', {}).get(name) != unit for name, unit in zip(model.state_names, model.state_units)):
        raise GuardedExecutionRejected('Physical state units differ from package declaration')
    package_sha = parameter_content_hash(registered)
    if package.get('parameter_hash') != package_sha:
        raise GuardedExecutionRejected('Registered physical parameter digest mismatch')
    package_current_limit = _number(domain.get('max_current_A'), 'package current limit')
    if package_current_limit <= 0 or abs(current) > min(package_current_limit, parameters.current_limit_A):
        raise GuardedExecutionRejected('Current exceeds common/package domain')
    package_temperature = _pair(domain.get('temperature_K'), 'package temperature')
    if not package_temperature[0] <= ambient <= package_temperature[1]:
        raise GuardedExecutionRejected('Ambient outside package domain')
    original = asdict(model.params)
    if not model.params.temperature_min_K <= ambient <= model.params.temperature_max_K:
        raise GuardedExecutionRejected('Ambient outside incoming model domain')
    requested = {}
    for name in STOP_FIELDS:
        registered_value = _number(registered.get(name), 'registered.' + name)
        policy = getattr(parameters, name)
        policy = None if policy is None else _number(policy, 'policy.' + name)
        values = [original[name], registered_value, *([] if policy is None else [policy])]
        requested[name] = max(values) if '_min_' in name else min(values)
    requested['temperature_min_K'] = max(requested['temperature_min_K'], package_temperature[0])
    requested['temperature_max_K'] = min(requested['temperature_max_K'], package_temperature[1])
    if 'voltage_V' in domain:
        voltage = _pair(domain['voltage_V'], 'package voltage')
        requested['voltage_min_V'] = max(requested['voltage_min_V'], voltage[0])
        requested['voltage_max_V'] = min(requested['voltage_max_V'], voltage[1])
    if requested['voltage_min_V'] >= requested['voltage_max_V'] or requested['temperature_min_K'] >= requested['temperature_max_K']:
        raise GuardedExecutionRejected('Common operational bounds have empty intersection')
    operational_params = replace(model.params, **requested)
    operational = asdict(operational_params)
    unchanged = {key: original[key] == operational[key] for key in original if key not in STOP_FIELDS}
    if not all(unchanged.values()):
        raise GuardedExecutionRejected('Operational clone altered physical dynamics parameters')
    guarded = SiteModel(operational_params)
    raw_state = np.asarray(state)
    if raw_state.shape != (5,) or raw_state.dtype.kind == 'b':
        raise GuardedExecutionRejected('Actual finite five-state vector required, never a posterior mean object')
    try:
        initial = guarded._validate_state(raw_state).copy()
    except ValueError as error:
        raise GuardedExecutionRejected('Invalid actual initial state: ' + str(error)) from error
    capacity = np.asarray(guarded.params.site_capacity_mol)
    initial_soc = float(initial[:2] @ capacity / capacity.sum())
    receipt = {'action': action.model_dump(mode='json'), 'ambient_K': ambient,
        'initial_actual_state': initial.tolist(),
        'incoming_actual_parameters': original, 'incoming_actual_parameter_sha256': parameter_content_hash(original),
        'registered_base_parameter_sha256': package_sha,
        'operational_stop_parameter_sha256': parameter_content_hash(operational),
        'operational_stop_bounds': requested, 'all_nonstop_parameters_identical': unchanged,
        'model_was_mutated': False, 'action_was_replaced': False,
        'source_and_sampled_model_mapping_verification': 'required_from_caller',
        'same_common_execution_parameters_required_for_all_policies': True,
        'prediction_voltage_margin_V_excluded_from_stopping': parameters.voltage_margin_V,
        'receipt_storage': 'private execution evaluator/operator; not observation/controller input',
        'risk_certificate': False, 'scope': 'Real native numerical V/T events; no validated numeric error or continuous SOC/DoD certificate'}
    try:
        reading = guarded.observe(initial, current)
    except (ValueError, RuntimeError) as error:
        raise GuardedExecutionRejected('Initial current/readout infeasible: ' + str(error), receipt) from error
    if not (requested['voltage_min_V'] < reading['voltage_V'] < requested['voltage_max_V']
            and requested['temperature_min_K'] < initial[4] < requested['temperature_max_K']):
        raise GuardedExecutionRejected('Initial state already at/outside operational V/T boundary', receipt)
    if not parameters.soc_min <= initial_soc <= parameters.soc_max:
        raise GuardedExecutionRejected('Initial actual SOC outside common bounds', receipt)
    if abs(current) > _band_limit(initial_soc, current, parameters, package_current_limit):
        raise GuardedExecutionRejected('Initial SOC-band current exceeds common limit', receipt)
    if not parameters.thermal_min_W <= action.thermal_W <= parameters.thermal_max_W:
        raise GuardedExecutionRejected('Thermal command exceeds common limits', receipt)
    actual = guarded.integrate(initial, current, action.duration_s, ambient_K=ambient,
                               thermal_W=action.thermal_W, max_step_s=parameters.prediction_max_step_s)
    soc = actual.states[:, :2] @ capacity / capacity.sum()
    tolerance = parameters.feasibility_tolerance
    checks = {'soc': bool(soc.min() >= parameters.soc_min - tolerance and soc.max() <= parameters.soc_max + tolerance),
        'soc_band_current': all(abs(current) <= _band_limit(float(v), current, parameters, package_current_limit) + tolerance for v in soc),
        'interval_dod': float(soc.max() - soc.min()) <= parameters.max_dod + tolerance,
        'temperature': bool(actual.states[:, 4].min() >= requested['temperature_min_K'] - tolerance
                            and actual.states[:, 4].max() <= requested['temperature_max_K'] + tolerance),
        'voltage': bool(actual.voltages_V.min() >= requested['voltage_min_V'] - tolerance
                        and actual.voltages_V.max() <= requested['voltage_max_V'] + tolerance)}
    violations = [key for key, passed in checks.items() if not passed]
    event_receipts = []
    event_fields = dict(zip(('voltage_low', 'voltage_high', 'temperature_low', 'temperature_high'), STOP_FIELDS))
    for event in actual.events:
        name = event['name']
        field = event_fields.get(name)
        event_receipts.append({**event, 'constraint_origin': 'operational_stop' if field is not None and requested[field] != original[field] else 'native_physical_model',
            'limit_source': 'operational' if field is not None and requested[field] != original[field] else 'physical',
            'physical_limit': original[field] if field else None,
            'original_physical_limit': original[field] if field else None,
            'registered_base_limit': registered[field] if field else None,
            'effective_operational_limit': requested[field] if field else None,
            'policy_limit': getattr(parameters, field) if field else None})
    receipt.update(status='realized_constraint_violation' if violations else 'stopped' if actual.events else 'completed',
        executed=True, solver_calls=1, solver=actual.solver,
        requested_duration_s=action.duration_s, actual_elapsed_s=actual.elapsed_s,
        actual_energy_J=actual.energy_J, thermal_electric_energy_J=actual.thermal_management_energy_J,
        trace_checks=checks, constraint_violations=violations,
        native_events_with_scope=event_receipts, initial_actual_soc=initial_soc,
        actual_interval_dod=float(soc.max()-soc.min()),
        soc_dod_check_scope='Initial and actual solver trace; caller tracks cumulative cycle/case SOC excursion',
        wall_s=time.monotonic()-started, caller_owned_hard_timeout_s=120,
        no_post_hoc_truncation=True)
    parameter_content_hash(receipt)
    return GuardedExecutionResult(actual, receipt)
