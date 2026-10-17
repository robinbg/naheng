"""Actual solver samples in a planning reserve are not operational events."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from naheng.models.site_model import SiteModel
from naheng.domain.contracts import Action
from naheng.packages.registry import ModelRegistry
from naheng.control.mpc import MPCParameters
from naheng.control.execution import integrate_guarded_action
from naheng.runtime.baseline_frontier import _execution_constraints
from naheng.runtime.execution_receipts import stop_status

ROOT = Path(__file__).resolve().parents[2]

def test_real_trace_in_prediction_reserve_is_not_a_cutoff_or_physical_event():
    original = SiteModel()
    state = original.initial_state()
    free = original.integrate(state, .02, 20, max_step_s=5)
    upper = float(max(free.voltages_V)) + 1e-4
    model = SiteModel(replace(original.params, voltage_max_V=upper))
    package = json.loads((ROOT / 'model_packages/research_base/package.json').read_bytes())
    package.update(parameters=asdict(model.params), parameter_revision='declared-synthetic-reserve-case')
    registry = ModelRegistry(ROOT)
    registry.register(package)
    package = registry.packages[package['package_id']]
    params = MPCParameters(current_limit_A=.02, voltage_margin_V=4e-4, prediction_max_step_s=5)
    action = Action(action_id='synthetic-reserve-actual', snapshot_id='explicit-method-snapshot',
                    start_s=0, duration_s=20, current_A=.02)
    guarded = integrate_guarded_action(model, state, action, package, params, 298.15)
    actual = guarded.result
    assert max(actual.voltages_V) > upper - params.voltage_margin_V
    assert max(actual.voltages_V) < upper and not actual.events
    checks, _ = _execution_constraints(actual, action, model, params, package, [])
    assert all(checks.values())
    assert stop_status(guarded.receipt, actual, action.duration_s, checks) is None
    assert guarded.receipt['prediction_voltage_margin_V_excluded_from_stopping'] == 4e-4
