"""Actual fixed-rule and original nominal baselines, all synthetic scope."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time
import uuid

import numpy as np
import pytest

from naheng.control.fixed_baseline import FixedBaselinePolicy, propose
from naheng.control.mpc import MPCParameters, MPCStage
from naheng.domain.contracts import PosteriorSnapshot
from naheng.estimation.diagnostics import weighted_quantiles
from naheng.models.site_model import SiteModel, SiteParameters
from naheng.packages.registry import ModelRegistry

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/fixed_baseline_controls" / ("tests-" + uuid.uuid4().hex[:8])
OUT.mkdir(parents=True)


def save(name, value):
    (OUT / (name + ".json")).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def save_input(name, snapshot, model, package, stages, fixed, common):
    save(name+"-input", {"snapshot": snapshot.model_dump(mode="json"), "model_parameters": asdict(model.params),
        "model_package": package, "stages": [asdict(stage) for stage in stages],
        "policy": asdict(fixed), "common_parameters": asdict(common),
        "scope": "explicit synthetic test fixture; no independent experiment or real-cell data"})


def fixture(model=None, temperature=299.15, rows=3):
    model = model or SiteModel()
    physical = model.initial_state(soc=.6, temperature_K=temperature).tolist()
    joint = [physical+[r, s] for r, s in zip([.8, 1.2, 1.4], [.7, 1.3, 2])][:rows]
    weights = [1] if rows == 1 else [.7, .3, 0]
    names = list(model.state_names)+["rate_scale", "side_rate_scale"]
    units = list(model.state_units)+["1", "1"]
    array = np.asarray(joint)
    mean = dict(zip(names, np.average(array, axis=0, weights=weights)))
    quantiles = {name: weighted_quantiles(array[:, i], weights) for i, name in enumerate(names)}
    mean["soc"], quantiles["soc"] = .6, [.6]*3
    snapshot = PosteriorSnapshot(snapshot_id="fixed-baseline-control", run_id="synthetic-fixed-baseline-test",
        parameter_revision="fixed-baseline-fixture-v1", obs_until_s=0,
        state_names=names, state_units=units, samples=joint, weights=weights,
        mean=mean, quantiles=quantiles, ess=1/sum(w*w for w in weights))
    raw = json.loads((ROOT / "model_packages/research_base/package.json").read_bytes())
    raw["parameters"], raw["parameter_revision"] = asdict(model.params), snapshot.parameter_revision
    registry = ModelRegistry(ROOT)
    registry.register(raw)
    return snapshot, model, deepcopy(registry.packages[raw["package_id"]])


def params(**overrides):
    values = dict(current_limit_A=.02, thermal_min_W=0, thermal_max_W=0,
        nominal_terminal_buffer=0, prediction_max_step_s=5, wall_budget_s=25)
    values.update(overrides)
    return MPCParameters(**values)


def policy(kind="rules", **overrides):
    values = dict(policy_id="fixed-"+kind, kind=kind, current_limit_A=.02,
        voltage_margin_V=.01, soc_margin=.02, temperature_margin_K=.25)
    values.update(overrides)
    return FixedBaselinePolicy(**values)


def schedule(buy=.05, sell=.04, duration=5, ambient=299.15):
    return [MPCStage(duration, buy, sell, ambient), MPCStage(duration, .15, .4, ambient)]


@pytest.mark.parametrize("buy,sell,sign,decision", [
    (.05, .04, -1, "charge_using_buy_price"),
    (.20, .4, 1, "discharge_using_sell_price"),
    (.20, .04, 0, "idle"),
    (.05, .4, -1, "charge_using_buy_price")])
def test_actual_rules_use_distinct_buy_and_sell_tariffs(buy, sell, sign, decision):
    snapshot, model, package = fixture()
    before = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True)
    declared_stages, fixed, common = schedule(buy, sell), policy(), params()
    save_input("tariff-"+str(buy)+"-"+str(sell), snapshot, model, package, declared_stages, fixed, common)
    response = propose(snapshot, model, package, declared_stages, policy=fixed, parameters=common)
    save("tariff-"+str(buy)+"-"+str(sell), response.to_dict())
    assert response.status == "feasible", response.to_dict()
    assert np.sign(response.action.current_A) == sign
    assert response.action.duration_s == 5 and response.action.start_s == snapshot.obs_until_s
    assert len(response.planned_actions) == 1
    assert response.diagnostics["price_decision"] == decision
    predictions = response.diagnostics["scenario_predictions"]
    assert len(predictions) == 3 and predictions[-1]["weight"] == 0
    assert response.diagnostics["integration_calls"] == response.diagnostics["completed_integrations"] == 3
    for row in predictions:
        assert row["elapsed_s"] == 5 and row["events"] == []
        expected = max(row["predicted_energy_J"], 0)/3_600_000*sell-max(-row["predicted_energy_J"], 0)/3_600_000*buy-row["predicted_thermal_cost"]
        assert row["predicted_cashflow"] == pytest.approx(expected, abs=1e-20)
    assert response.diagnostics["risk_certificate"] is False
    assert response.diagnostics["future_plan_is_execution_history"] is False
    assert json.dumps(snapshot.model_dump(mode="json"), sort_keys=True) == before


def test_fixed_constraints_only_tighten_the_common_problem():
    snapshot, model, package = fixture()
    common = params(current_limit_A=.01, soc_min=.2, soc_max=.8,
        temperature_min_K=290, temperature_max_K=310, voltage_min_V=2.4, voltage_max_V=4,
        voltage_margin_V=.03)
    response = propose(snapshot, model, package, schedule(), policy=policy(current_limit_A=.02, voltage_margin_V=.02), parameters=common)
    assert response.status == "feasible", response.to_dict()
    effective = response.diagnostics["effective_parameters"]
    assert effective["current_limit_A"] == .01
    assert effective["soc_min"] == pytest.approx(.22) and effective["soc_max"] == pytest.approx(.78)
    assert effective["temperature_min_K"] == 290.25 and effective["temperature_max_K"] == 309.75
    assert effective["voltage_min_V"] == 2.4 and effective["voltage_max_V"] == 4
    assert effective["voltage_margin_V"] == .03
    for name in ("max_dod", "soc_bands", "thermal_min_W", "thermal_max_W", "terminal_soc_min", "degradation_shadow_CNY_per_mol"):
        assert effective[name] == asdict(common)[name]
    impossible = propose(snapshot, model, package, schedule(), policy=policy(voltage_margin_V=2), parameters=common)
    assert impossible.status == "unknown" and impossible.action is None
    assert "owned_pid" not in impossible.diagnostics


def test_zero_weight_temperature_violation_cannot_hide_in_rule_quantiles():
    snapshot, model, package = fixture()
    bad = deepcopy(snapshot.samples)
    bad[-1][4] = 320
    varied = snapshot.model_copy(update={"samples": bad})
    response = propose(varied, model, package, schedule(), policy=policy(), parameters=params(temperature_max_K=310))
    save("zero-weight-margin-failure", response.to_dict())
    assert response.status == "infeasible" and response.action is None
    rows = response.diagnostics["scenario_predictions"]
    assert rows[-1]["weight"] == 0 and rows[-1]["constraint_margins"]["temperature_high_K"] < 0
    assert response.diagnostics["integration_calls"] == 3


def test_soc_band_current_and_dod_constraints_are_actually_checked():
    snapshot, model, package = fixture()
    limited = params(soc_bands=((1., .001, .001),))
    response = propose(snapshot, model, package, schedule(), policy=policy(), parameters=limited)
    assert response.status == "infeasible" and response.action is None
    assert all(row["constraint_margins"]["soc_band_current_A"] < 0 for row in response.diagnostics["scenario_predictions"])
    dod = propose(snapshot, model, package, schedule(), policy=policy(), parameters=params(max_dod=1e-8))
    assert dod.status == "infeasible" and dod.action is None
    assert any(row["constraint_margins"]["max_dod"] < -1e-7 for row in dod.diagnostics["scenario_predictions"])


def test_original_nominal_mpc_is_reused_with_actual_optimizer_and_ode():
    snapshot, model, package = fixture(rows=1)
    declared_stages, fixed, common = schedule(), policy("nominal"), params()
    save_input("original-nominal", snapshot, model, package, declared_stages, fixed, common)
    response = propose(snapshot, model, package, declared_stages, policy=fixed, parameters=common)
    save("original-nominal", response.to_dict())
    assert response.status == "feasible", response.to_dict()
    assert len(response.planned_actions) == 2
    assert response.diagnostics["nominal_diagnostics"]["algorithm"] == "scipy_SLSQP_nonlinear_nominal_MPC"
    assert response.diagnostics["nominal_diagnostics"]["optimizer"]["success"]
    assert response.diagnostics["integration_calls"] > 2
    assert response.diagnostics["original_weights"] == snapshot.weights
    assert response.diagnostics["risk_certificate"] is False
    assert response.diagnostics["nominal_mpc_source_sha256"] == hashlib.sha256((ROOT / "src/naheng/control/mpc.py").read_bytes()).hexdigest()


def test_real_rule_cooling_cost_uses_actual_elapsed_time_and_model_cop_once():
    model = SiteModel(SiteParameters(thermal_capacity_J_per_K=2, thermal_cop=1.5))
    snapshot, model, package = fixture(model, temperature=310)
    declared_stages, fixed, common = schedule(.20, .04, ambient=310), policy(), params(thermal_min_W=-.2, thermal_max_W=.1)
    save_input("rule-thermal", snapshot, model, package, declared_stages, fixed, common)
    response = propose(snapshot, model, package, declared_stages, policy=fixed, parameters=common)
    save("rule-thermal", response.to_dict())
    assert response.status == "feasible", response.to_dict()
    assert response.action.thermal_W == -.1
    for row in response.diagnostics["scenario_predictions"]:
        assert row["predicted_thermal_electric_energy_J"] == pytest.approx(.1*row["elapsed_s"]/1.5)
        assert row["predicted_thermal_cost"] == pytest.approx(.1*5/1.5/3_600_000*.20)


def test_actual_source_stale_units_joint_parameters_and_private_path_refused():
    snapshot, model, package = fixture()
    packages = []
    stale = deepcopy(package); stale["evidence_validity"] = "stale"; packages.append(stale)
    wrong = deepcopy(package); wrong["parameters"]["resistance_ohm"] += .01; packages.append(wrong)
    source = deepcopy(package); source["binding_hashes"]["src/naheng/models/site_model.py"] = "0"*64; packages.append(source)
    private = deepcopy(package); private["binding_hashes"]["artifacts/Evaluator/private.json"] = "0"*64; packages.append(private)
    for i, bad in enumerate(packages):
        response = propose(snapshot, model, bad, schedule(), policy=policy(), parameters=params())
        save("bad-package-"+str(i), response.to_dict())
        assert response.status == "unknown" and response.action is None and "owned_pid" not in response.diagnostics
    units = list(snapshot.state_units); units[-1] = "V"
    wrong_units = snapshot.model_copy(update={"state_units": units})
    bad_samples = deepcopy(snapshot.samples); bad_samples[-1][-1] = -1
    wrong_sample = snapshot.model_copy(update={"samples": bad_samples})
    bad_states = deepcopy(snapshot.samples); bad_states[-1][0] = -0.01
    wrong_state = snapshot.model_copy(update={"samples": bad_states})
    duplicate = snapshot.model_copy(update={"state_names": snapshot.state_names[:-1]+["rate_scale"]})
    for bad in (wrong_units, wrong_sample, wrong_state, duplicate):
        response = propose(bad, model, package, schedule(), policy=policy(), parameters=params())
        assert response.status == "unknown" and response.action is None and "owned_pid" not in response.diagnostics


def test_strict_mode_does_not_release_first_action_without_t3():
    snapshot, model, package = fixture()
    for kind in ("rules", "nominal"):
        response = propose(snapshot, model, package, schedule(), policy=policy(kind), parameters=params(), admission_mode="strict")
        assert response.status == "unknown" and response.action is None
        assert "T3" in response.reason and "owned_pid" not in response.diagnostics


def test_owned_timeout_interrupts_a_genuinely_active_rule_integrator():
    snapshot, model, package = fixture()
    started = time.monotonic()
    response = propose(snapshot, model, package, schedule(.20, .04, duration=3600),
        policy=policy(), parameters=params(prediction_max_step_s=.002, wall_budget_s=8))
    save("owned-active-rule-timeout", response.to_dict())
    assert response.status == "unknown" and response.action is None and response.planned_actions == ()
    assert response.diagnostics["timed_out"] is True
    assert '"phase": "integrating"' in response.diagnostics["worker_stderr"]
    assert response.diagnostics["termination"]["exit_code"] == 0
    assert response.diagnostics["worker_returncode"] is not None
    assert time.monotonic()-started < 12


def test_nonfinite_policy_negative_margin_and_bad_duration_are_not_silently_accepted():
    for bad in ({"soc_margin": -.01}, {"temperature_margin_K": float("nan")}, {"current_limit_A": float("inf")},
                {"voltage_margin_V": True}, {"charge_below_price": -.01}, {"policy_id": ""}, {"kind": "magic"}):
        with pytest.raises(ValueError):
            policy(**bad)
    snapshot, model, package = fixture()
    forged = MPCStage(5, .2, .04)
    object.__setattr__(forged, "duration_s", float("nan"))
    with pytest.raises(ValueError):
        propose(snapshot, model, package, [forged, schedule()[1]], policy=policy(), parameters=params())


def test_actual_nominal_reserve_corrects_a_mean_only_terminal_candidate():
    snapshot, model, package = fixture()
    declared_stages, common = schedule(), params()
    prior = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True)
    responses = {}
    for reserve in (0, 5e-6, 1e-5):
        fixed = policy("nominal", nominal_terminal_buffer=reserve)
        name = "joint-nominal-reserve-"+str(reserve)
        save_input(name, snapshot, model, package, declared_stages, fixed, common)
        response = propose(snapshot, model, package, declared_stages, policy=fixed, parameters=common)
        save(name, response.to_dict())
        responses[reserve] = response
        assert response.diagnostics["original_weights"] == snapshot.weights
        assert response.diagnostics["nominal_diagnostics"]["optimizer"]["success"]
        assert response.diagnostics["integration_calls"] >= 8
        assert response.diagnostics["risk_certificate"] is False
        assert response.diagnostics["effective_parameters"]["nominal_terminal_buffer"] == reserve
        assert json.dumps(snapshot.model_dump(mode="json"), sort_keys=True) == prior
    zero = responses[0]
    assert zero.status == "infeasible" and zero.action is None and zero.planned_actions == ()
    nominal = zero.diagnostics["nominal_diagnostics"]["nominal_prediction"]
    assert nominal["terminal_soc"] >= nominal["terminal_soc_floor"]-common.feasibility_tolerance
    failures = [row for row in zero.diagnostics["nominal_diagnostics"]["scenario_predictions"]
        if row["terminal_soc"] < row["terminal_soc_floor"]-common.feasibility_tolerance]
    assert failures and any(row["weight"] == 0 for row in failures)
    for reserve in (5e-6, 1e-5):
        response = responses[reserve]
        assert response.status == "feasible", response.to_dict()
        assert len(response.planned_actions) == 2 and response.action == response.planned_actions[0]
        rows = response.diagnostics["nominal_diagnostics"]["scenario_predictions"]
        assert len(rows) == 3 and rows[-1]["weight"] == 0
        assert all(row["status"] == "computed" and row["terminal_soc"] >= row["initial_soc"]-common.feasibility_tolerance for row in rows)


@pytest.mark.parametrize("reserve,effective", [(None, 5e-6), (0, 5e-6), (1e-6, 5e-6), (1e-5, 1e-5)])
def test_nominal_reserve_inherits_or_increases_common_buffer(reserve, effective):
    snapshot, model, package = fixture()
    fixed, common, declared_stages = policy("nominal", nominal_terminal_buffer=reserve), params(nominal_terminal_buffer=5e-6), schedule()
    save_input("inherit-buffer-"+str(reserve), snapshot, model, package, declared_stages, fixed, common)
    response = propose(snapshot, model, package, declared_stages, policy=fixed, parameters=common)
    save("inherit-buffer-"+str(reserve), response.to_dict())
    assert response.status == "feasible", response.to_dict()
    assert response.diagnostics["common_parameters"]["nominal_terminal_buffer"] == 5e-6
    assert response.diagnostics["effective_parameters"]["nominal_terminal_buffer"] == effective
    assert response.diagnostics["nominal_diagnostics"]["budgets"]["nominal_terminal_buffer"] == effective


def test_bad_reserves_and_unsupported_rule_reserves_are_explicitly_refused():
    for reserve in (float("nan"), float("inf"), -.00001, True, False, "0"):
        with pytest.raises(ValueError, match="finite, nonboolean and nonnegative"):
            policy("nominal", nominal_terminal_buffer=reserve)
    with pytest.raises(ValueError, match="unsupported"):
        policy("rules", nominal_terminal_buffer=1e-5)
    snapshot, model, package = fixture()
    for reserve in (None, 0):
        response = propose(snapshot, model, package, schedule(), policy=policy(nominal_terminal_buffer=reserve), parameters=params())
        assert response.status == "feasible", response.to_dict()
        assert response.diagnostics["effective_parameters"]["nominal_terminal_buffer"] == 0
        assert len(response.planned_actions) == 1
    impossible = propose(snapshot, model, package, schedule(), policy=policy("nominal", nominal_terminal_buffer=1e-5),
        parameters=params(max_dod=5e-6))
    save("reserve-exceeds-common-max-dod", impossible.to_dict())
    assert impossible.status == "unknown" and impossible.action is None
    assert "terminal buffer" in impossible.reason and "owned_pid" not in impossible.diagnostics
