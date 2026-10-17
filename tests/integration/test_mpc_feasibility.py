"""Actual SiteModel/optimizer checks; all fixtures are uncalibrated synthetic."""
from dataclasses import asdict, replace
from pathlib import Path
from copy import deepcopy
import json
import time
import pytest
from naheng.control.mpc import MPCParameters, MPCStage, plan
from naheng.domain.contracts import PosteriorSnapshot
from naheng.economics.ledger import EnergyLedger
from naheng.models.site_model import SiteModel, SiteParameters

ROOT = Path(__file__).resolve().parents[2]


def inputs(model=None, state=None):
    model = model or SiteModel()
    state = model.initial_state() if state is None else state
    snapshot = PosteriorSnapshot(snapshot_id="mpc-synthetic-snapshot", run_id="mpc-synthetic-test", obs_until_s=0,
        state_names=list(model.state_names), state_units=list(model.state_units), samples=[state.tolist()], weights=[1],
        mean=dict(zip(model.state_names, state.tolist())), quantiles={"soc": [0.6]*3, "temperature_K": [float(state[4])]*3}, ess=1)
    package = json.loads((ROOT / "model_packages/research_base/package.json").read_text(encoding="utf-8"))
    package["parameters"] = asdict(model.params)
    package["parameter_revision"] = snapshot.parameter_revision
    return snapshot, model, package


def schedule(future_sell=0.40, ambient=298.15, duration=30):
    return [MPCStage(duration, 0.05, 0.04, ambient), MPCStage(duration, 0.15, future_sell, ambient),
            MPCStage(duration, 0.15, 0.20, ambient)]


def test_actual_multi_step_optimization_uses_future_prices_and_terminal_inventory():
    snapshot, model, package = inputs()
    higher = plan(snapshot, model, package, schedule(), parameters=MPCParameters(wall_budget_s=25))
    lower = plan(snapshot, model, package, schedule(future_sell=0.04), parameters=MPCParameters(wall_budget_s=25))
    assert higher.status == lower.status == "feasible", (higher.to_dict(), lower.to_dict())
    assert len(higher.planned_actions) == 3 and higher.action == higher.planned_actions[0]
    assert higher.action.current_A < 0
    assert any(action.current_A > 0 for action in higher.planned_actions[1:])
    assert abs(higher.planned_actions[1].current_A-lower.planned_actions[1].current_A) > 1e-3
    assert higher.diagnostics["optimizer"]["success"]
    assert higher.diagnostics["counters"]["candidate_evaluations"] > 1
    prediction = higher.diagnostics["nominal_prediction"]
    assert len(prediction["stages"]) == 3
    assert prediction["terminal_soc"] >= prediction["terminal_soc_floor"]-1e-7
    for scenario in higher.diagnostics["scenario_predictions"]:
        assert scenario["terminal_soc"] >= scenario["initial_soc"]-1e-7
    assert higher.diagnostics["risk_certificate"] is False


def test_actual_thermal_constraint_and_unity_accounting_use_model_cop_once():
    model = SiteModel(SiteParameters(thermal_capacity_J_per_K=2.0, thermal_cop=1.5))
    snapshot, model, package = inputs(model, model.initial_state(temperature_K=310))
    stages = [MPCStage(10, 0.15, 0.10, 310.5) for _ in range(3)]
    result = plan(snapshot, model, package, stages,
                  parameters=MPCParameters(temperature_max_K=310.25, wall_budget_s=25))
    assert result.status == "feasible", result.to_dict()
    assert any(action.thermal_W < -1e-5 for action in result.planned_actions)
    for stage in result.diagnostics["nominal_prediction"]["stages"]:
        assert stage["temperature_range_K"][1] <= 310.25+1e-5
    action = result.action
    actual = model.integrate(snapshot.samples[0], action.current_A, action.duration_s, ambient_K=310.5, thermal_W=action.thermal_W)
    ledger = EnergyLedger("mpc-synthetic-test")
    entry = ledger.append(action, execution_id="actual-thermal-mpc-step", energy_J=actual.energy_J,
        thermal_energy_J=actual.thermal_management_energy_J, buy_price_per_kWh=0.15, sell_price_per_kWh=0.10)
    predicted = result.diagnostics["nominal_prediction"]["stages"][0]
    assert actual.thermal_management_energy_J == pytest.approx(abs(action.thermal_W)*10/1.5)
    assert entry["net_cashflow"] == pytest.approx(predicted["predicted_cashflow"], abs=1e-14)


def test_candidate_budget_is_unknown_and_never_executes_partial_plan():
    snapshot, model, package = inputs()
    result = plan(snapshot, model, package, schedule(),
                  parameters=MPCParameters(max_candidate_evaluations=1, wall_budget_s=20))
    assert result.status == "unknown" and result.action is None
    assert "Candidate evaluation budget" in result.reason
    assert result.diagnostics["counters"]["candidate_evaluations"] == 1


def test_wall_budget_interrupts_an_observed_active_integrator_process():
    snapshot, model, package = inputs()
    started = time.monotonic()
    result = plan(snapshot, model, package, [MPCStage(3600, 0.1, 0.2) for _ in range(2)],
        parameters=MPCParameters(prediction_max_step_s=0.002, wall_budget_s=8, max_iterations=2))
    assert result.status == "unknown" and result.action is None
    assert result.diagnostics["timed_out"] is True
    assert '"phase": "integrating"' in result.diagnostics["worker_stderr"]
    assert result.diagnostics["termination"]["exit_code"] == 0
    assert result.diagnostics["worker_returncode"] is not None
    assert time.monotonic()-started < 12


def test_invalid_represented_state_cannot_be_hidden_by_posterior_mean():
    snapshot, model, package = inputs()
    invalid = list(snapshot.samples[0]); invalid[4] = 340
    varied = snapshot.model_copy(update={"samples": [snapshot.samples[0], invalid], "weights": [0.999, 0.001]})
    result = plan(varied, model, package, schedule())
    assert result.status == "infeasible" and result.action is None
    assert "owned_pid" not in result.diagnostics


def test_strict_mode_and_stale_parameters_are_unknown_before_optimizer_launch():
    snapshot, model, package = inputs()
    strict = plan(snapshot, model, package, schedule(), admission_mode="strict")
    assert strict.status == "unknown" and strict.action is None
    assert "T3" in strict.reason and "owned_pid" not in strict.diagnostics
    stale = deepcopy(package); stale["parameters"]["resistance_ohm"] += 0.01
    result = plan(snapshot, model, stale, schedule())
    assert result.status == "unknown" and result.action is None
    assert "not bound" in result.reason


def test_one_stage_or_unobserved_start_time_is_not_a_valid_mpc_problem():
    snapshot, model, package = inputs()
    with pytest.raises(ValueError, match="2..8"):
        plan(snapshot, model, package, schedule()[:1])
    with pytest.raises(ValueError, match="observation time"):
        plan(snapshot, model, package, schedule(), start_s=10)
