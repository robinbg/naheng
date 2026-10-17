"""Real native event solves; operational limits are declared synthetic fixtures."""
from copy import deepcopy
from dataclasses import asdict, replace
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import numpy as np
import pytest

from naheng.control.mpc import MPCParameters
from naheng.domain.contracts import Action
from naheng.models.site_model import SiteModel, SiteParameters
from naheng.packages.registry import ModelRegistry, content_hash

ROOT = Path(os.environ.get('NAHENG_GUARDED_EXECUTION_ROOT', Path(__file__).resolve().parents[2]))
if os.environ.get('NAHENG_GUARDED_EXECUTION_CANDIDATE'):
    path = Path(os.environ['NAHENG_GUARDED_EXECUTION_CANDIDATE'])
    spec = importlib.util.spec_from_file_location('staged_guarded_execution', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    integrate_guarded_action, GuardedExecutionRejected = module.integrate_guarded_action, module.GuardedExecutionRejected
else:
    from naheng.control.execution import integrate_guarded_action, GuardedExecutionRejected


def inputs(model=None, *, current=.02, duration=20., thermal=0.):
    model = model or SiteModel()
    state = model.initial_state()
    action = Action(action_id='guard-synthetic-action', snapshot_id='explicit-synthetic-snapshot',
                    start_s=40., duration_s=duration, current_A=current, thermal_W=thermal)
    raw = json.loads((ROOT / 'model_packages/research_base/package.json').read_bytes())
    raw.update(parameters=asdict(model.params), parameter_revision='guard-synthetic-revision')
    registry = ModelRegistry(ROOT)
    registry.register(raw)
    package = registry.packages[raw['package_id']]
    parameters = MPCParameters(current_limit_A=.2, prediction_max_step_s=5.)
    return model, state, action, package, parameters


@pytest.mark.parametrize('current, field, event_name', [(-.02, 'voltage_max_V', 'voltage_high'), (.02, 'voltage_min_V', 'voltage_low')])
def test_real_midway_voltage_cutoff_is_native_event_not_truncated_full_curve(current, field, event_name):
    model, state, action, package, parameters = inputs(current=current)
    # This model's unequal site biases cause relaxation from equal occupations.
    # Derive a legitimate near-equilibrium state from the actual same-source rates;
    # direction below is checked on the real curve, not assumed for all sodium cells.
    a, b, c = model.rates(0., state[4])
    state[:2] = a / (a + b + c)
    model._validate_state(state)
    free = model.integrate(state, action.current_A, action.duration_s, max_step_s=5)
    v0 = model.observe(state, action.current_A)['voltage_V']
    assert (free.voltages_V[-1] < v0) if field == 'voltage_min_V' else (free.voltages_V[-1] > v0)
    cutoff = float((free.voltages_V[-1] + v0) / 2)
    parameters = replace(parameters, **{field: cutoff})
    saved = deepcopy(model.__dict__)
    initial = state.copy()
    result = integrate_guarded_action(model, state, action, package, parameters, 298.15)
    actual, receipt = result.result, result.receipt
    assert 0 < actual.elapsed_s < action.duration_s
    assert any(event['name'] == event_name for event in actual.events)
    assert actual.voltages_V[-1] == pytest.approx(cutoff, abs=1e-9)
    assert receipt['status'] == 'stopped' and receipt['no_post_hoc_truncation']
    assert receipt['native_events_with_scope'][0]['constraint_origin'] == 'operational_stop'
    assert receipt['native_events_with_scope'][0]['limit_source'] == 'operational'
    assert receipt['native_events_with_scope'][0]['original_physical_limit'] == getattr(model.params, field)
    assert receipt['native_events_with_scope'][0]['policy_limit'] == cutoff
    assert all(receipt['all_nonstop_parameters_identical'].values())
    assert model.__dict__ == saved and np.array_equal(state, initial)
    # Independently execute the original physics for exactly the observed stop time.
    original = model.integrate(state, action.current_A, actual.elapsed_s, max_step_s=5)
    assert actual.state == pytest.approx(original.state, abs=1e-8)
    assert actual.energy_J == pytest.approx(original.energy_J, abs=1e-8)
    assert receipt['actual_elapsed_s'] == actual.elapsed_s
    assert receipt['initial_actual_state'] == initial.tolist()
    assert receipt['risk_certificate'] is False


@pytest.mark.parametrize('thermal', [-2., 2.])
def test_nonzero_cooling_heating_stops_at_real_temperature_event_with_actual_COP(thermal):
    model = SiteModel(replace(SiteParameters(), thermal_cop=1.5))
    model, state, action, package, parameters = inputs(model, current=.02, duration=20., thermal=thermal)
    parameters = replace(parameters, thermal_min_W=-3., thermal_max_W=3.,
        temperature_min_K=state[4] - .2 if thermal < 0 else None,
        temperature_max_K=state[4] + .2 if thermal > 0 else None)
    output = integrate_guarded_action(model, state, action, package, parameters, 298.15)
    assert 0 < output.result.elapsed_s < 20
    name = 'temperature_low' if thermal < 0 else 'temperature_high'
    assert any(event['name'] == name for event in output.result.events)
    assert output.result.thermal_management_energy_J == pytest.approx(abs(thermal) * output.result.elapsed_s / 1.5)
    assert output.receipt['thermal_electric_energy_J'] == output.result.thermal_management_energy_J
    assert output.receipt['status'] == 'stopped'


def test_four_threshold_clone_has_equal_real_rhs_rates_drive_and_readout():
    model, state, action, package, parameters = inputs()
    parameters = replace(parameters, voltage_min_V=2.1, voltage_max_V=4.1,
                         temperature_min_K=280., temperature_max_K=325.)
    result = integrate_guarded_action(model, state, action, package, parameters, 298.15)
    bounds = result.receipt['operational_stop_bounds']
    clone = SiteModel(replace(model.params, **bounds))
    for soc, temperature, current in ((.3, 285., -.02), (.6, 298.15, .02), (.8, 320., 0.)):
        s = model.initial_state(soc=soc, temperature_K=temperature)
        assert model.solve_drive(s, current) == clone.solve_drive(s, current)
        assert model.observe(s, current) == clone.observe(s, current)
        assert model.rhs(0, s, current, 298.15, -.05) == pytest.approx(clone.rhs(0, s, current, 298.15, -.05), abs=0)
        for left, right in zip(model.rates(.02, temperature), clone.rates(.02, temperature)):
            assert np.array_equal(left, right)
    old, new = asdict(model.params), asdict(clone.params)
    assert {k for k in old if old[k] != new[k]} <= set(bounds)


def test_prediction_reserve_does_not_change_common_operational_cutoff():
    model, state, action, package, parameters = inputs()
    first = integrate_guarded_action(model, state, action, package, replace(parameters, voltage_margin_V=0), 298.15)
    second = integrate_guarded_action(model, state, action, package, replace(parameters, voltage_margin_V=.5), 298.15)
    assert first.receipt['operational_stop_bounds'] == second.receipt['operational_stop_bounds']
    assert first.result.state == pytest.approx(second.result.state, abs=0)
    assert first.result.elapsed_s == second.result.elapsed_s


def test_sampled_model_parameters_are_preserved_separately_from_base_registered_package():
    base, state, action, package, parameters = inputs()
    actual = SiteModel(replace(base.params, rate_s_inv=tuple(v * 1.2 for v in base.params.rate_s_inv)))
    result = integrate_guarded_action(actual, state, action, package, parameters, 298.15)
    receipt = result.receipt
    assert receipt['incoming_actual_parameter_sha256'] == content_hash(asdict(actual.params))
    assert receipt['incoming_actual_parameter_sha256'] != receipt['registered_base_parameter_sha256']
    assert receipt['incoming_actual_parameters']['rate_s_inv'] == actual.params.rate_s_inv
    assert all(receipt['all_nonstop_parameters_identical'].values())
    assert 'caller' in receipt['source_and_sampled_model_mapping_verification']


def test_package_bounds_only_tighten_and_unknown_domains_are_not_assumed():
    model, state, action, package, parameters = inputs()
    tight = deepcopy(package)
    tight['domain']['voltage_V'] = [2.2, 4.0]
    output = integrate_guarded_action(model, state, action, tight, replace(parameters, voltage_min_V=1.0, voltage_max_V=5.0), 298.15)
    assert output.receipt['operational_stop_bounds']['voltage_min_V'] == 2.2
    assert output.receipt['operational_stop_bounds']['voltage_max_V'] == 4.0
    missing = deepcopy(package)
    del missing['domain']['temperature_K']
    with pytest.raises(GuardedExecutionRejected):
        integrate_guarded_action(model, state, action, missing, parameters, 298.15)


@pytest.mark.parametrize('bad', ['already_voltage', 'already_temperature', 'soc', 'band', 'current', 'thermal', 'nan', 'bool_current', 'ambient', 'hash', 'empty'])
def test_initial_rejection_never_substitutes_zero_current_or_executes(bad):
    model, state, action, package, parameters = inputs()
    if bad == 'already_voltage': parameters = replace(parameters, voltage_min_V=4.)
    if bad == 'already_temperature': parameters = replace(parameters, temperature_max_K=state[4])
    if bad == 'soc': parameters = replace(parameters, soc_min=.7)
    if bad == 'band': parameters = replace(parameters, soc_bands=((1., .001, .001),))
    if bad == 'current': action = action.model_copy(update={'current_A': 1.})
    if bad == 'thermal': action = action.model_copy(update={'thermal_W': 1.})
    if bad == 'nan': state[0] = math.nan
    if bad == 'bool_current': action = action.model_copy(update={'current_A': True})
    if bad == 'ambient': ambient = 400.
    else: ambient = 298.15
    if bad == 'hash': package['parameter_hash'] = '0' * 64
    if bad == 'empty': parameters = replace(parameters, voltage_min_V=4.3, voltage_max_V=4.4)
    with pytest.raises((GuardedExecutionRejected, ValueError)) as error:
        integrate_guarded_action(model, state, action, package, parameters, ambient)
    if isinstance(error.value, GuardedExecutionRejected):
        assert error.value.receipt['solver_calls'] == 0 and error.value.receipt['executed'] is False
    assert action.current_A != 0


def test_actual_soc_dod_violation_is_recorded_as_trace_scope_not_faked_prevented_event():
    model, state, action, package, parameters = inputs()
    parameters = replace(parameters, max_dod=1e-8, nominal_terminal_buffer=0)
    output = integrate_guarded_action(model, state, action, package, parameters, 298.15)
    assert output.result.elapsed_s == action.duration_s
    assert 'interval_dod' in output.receipt['constraint_violations']
    assert output.receipt['status'] == 'realized_constraint_violation'
    assert output.receipt['executed'] is True
    assert 'caller tracks cumulative' in output.receipt['soc_dod_check_scope']
    assert not output.result.events
