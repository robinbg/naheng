"""Actual finite joint-scenario controls; no original public tests are edited."""
from dataclasses import asdict, replace
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import uuid

import numpy as np
import pytest
from naheng.control.mpc import MPCStage, MPCParameters, MPCPlan
from naheng.domain.contracts import PosteriorSnapshot
from naheng.economics.ledger import EnergyLedger
from naheng.estimation.diagnostics import weighted_quantiles
from naheng.models.site_model import SiteModel, SiteParameters
from naheng.packages.registry import ModelRegistry
from naheng.runtime.forecast_jobs import _package_model

from naheng.control import scenario_mpc as SC
from naheng.estimation.calibration_session import run_calibration
ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / 'artifacts/calibration' / ('scenario-test-input-' + uuid.uuid4().hex[:8])
OUT = ROOT / 'artifacts/scenario_mpc_controls' / ('tests-' + uuid.uuid4().hex[:8]); OUT.mkdir(parents=True)

@pytest.fixture(scope='module', autouse=True)
def fresh_calibration_fixture():
    result = run_calibration(ROOT, ROOT / 'tests/fixtures/calibration_builtin/request.json', PACKET)
    assert result['exit_code'] == 0 and result['complete']


def save(name, value):
    (OUT / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def current():
    packet = PACKET
    snapshot = PosteriorSnapshot.model_validate(json.loads((packet / 'result.json').read_bytes())['calibration']['posterior_contract'])
    package = json.loads((packet / 'input.json').read_bytes())['model_package']
    return snapshot, _package_model(package, ROOT, snapshot), package


def parameters(**overrides):
    values = dict(current_limit_A=.02, thermal_min_W=0, thermal_max_W=0,
        nominal_terminal_buffer=0, prediction_max_step_s=5, max_iterations=25,
        max_candidate_evaluations=120, wall_budget_s=25)
    values.update(overrides)
    return MPCParameters(**values)


def stages(future_sell=.40, ambient=299.15):
    return [MPCStage(5, .05, .04, ambient), MPCStage(5, .15, future_sell, ambient)]


def fixture(model=None, temperature=299.15):
    model = model or SiteModel()
    physical = model.initial_state(soc=.6, temperature_K=temperature).tolist()
    rates = [.75, .8, .9, .95, 1.1, 1.2, 1.3, 1.4]
    sides = [.5, .7, .85, 1, 1.1, 1.3, 1.6, 2]
    rows = [physical + [r, s] for r, s in zip(rates, sides)]
    weights = [.4, .2, .15, .1, .075, .05, .025, 0]
    names, units = list(model.state_names) + ['rate_scale', 'side_rate_scale'], list(model.state_units) + ['1', '1']
    array = np.asarray(rows)
    means = dict(zip(names, np.average(array, axis=0, weights=weights)))
    quantiles = {n: weighted_quantiles(array[:, i], weights) for i, n in enumerate(names)}
    means['soc'], quantiles['soc'] = .6, [.6] * 3
    snapshot = PosteriorSnapshot(snapshot_id='explicit-eight-joint-fixture', run_id='synthetic-scenario-controls',
        model_package_id='research_base-v1', parameter_revision='scenario-controls-v1', obs_until_s=0,
        state_names=names, state_units=units, samples=rows, weights=weights, mean=means,
        quantiles=quantiles, ess=1 / sum(w*w for w in weights), identifiability=['synthetic_fixture_not_fitted'])
    raw = json.loads((ROOT / 'model_packages/research_base/package.json').read_bytes())
    raw['parameters'], raw['parameter_revision'] = asdict(model.params), snapshot.parameter_revision
    registry = ModelRegistry(ROOT)  # Isolated in-memory descriptor; no persistent writes.
    registry.register(raw)
    package = deepcopy(registry.packages[raw['package_id']])
    return snapshot, model, package


def test_actual_current_eight_joint_weighted_objective_and_first_action():
    snapshot, model, package = current()
    before = SC._hash(snapshot.model_dump(mode='json'))
    response = SC.plan(snapshot, model, package, stages(), parameters=parameters())
    save('current-weighted', response.to_dict())
    assert type(response) is MPCPlan and response.status == 'feasible', response.to_dict()
    assert response.action == response.planned_actions[0] and len(response.planned_actions) == 2
    assert all(action.snapshot_id == snapshot.snapshot_id for action in response.planned_actions)
    assert response.action.start_s == snapshot.obs_until_s
    assert response.diagnostics['only_first_action_executable'] is True
    assert response.diagnostics['future_plan_is_execution_history'] is False
    rows = response.diagnostics['scenario_predictions']
    assert len(rows) == 8 and len(set(snapshot.weights)) > 1
    assert response.diagnostics['original_weights'] == snapshot.weights
    expected_cash = sum(w * row['planning_cashflow_with_thermal_epigraph'] for w, row in zip(snapshot.weights, rows))
    expected_trapped = sum(w * row['predicted_trapped_increment_mol'] for w, row in zip(snapshot.weights, rows))
    weighted = response.diagnostics['weighted_candidate']
    assert weighted['weighted_planning_cashflow_CNY'] == pytest.approx(expected_cash, abs=1e-18)
    assert weighted['weighted_trapped_increment_mol'] == pytest.approx(expected_trapped, abs=1e-20)
    assert weighted['objective_scaled'] == pytest.approx(-3_600_000 * expected_cash, abs=1e-11)
    for i, row in enumerate(rows):
        assert row['posterior_index'] == i and row['weight'] == snapshot.weights[i]
        assert row['joint_row_sha256'] == SC._hash(snapshot.samples[i])
        assert row['terminal_soc'] >= row['initial_soc'] - 1e-7
        assert len(row['stages']) == 2
        assert row['stages'][0]['initial_state'] == snapshot.samples[i][:5]
    assert response.diagnostics['counters']['integration_calls'] == response.diagnostics['counters']['candidate_evaluations'] * 8 * 2
    assert response.diagnostics['risk_certificate'] is False
    assert SC._hash(snapshot.model_dump(mode='json')) == before


def test_future_price_changes_the_actual_joint_multistage_solution():
    snapshot, model, package = current()
    high = SC.plan(snapshot, model, package, stages(.40), parameters=parameters())
    low = SC.plan(snapshot, model, package, stages(.04), parameters=parameters())
    save('future-price-high', high.to_dict()); save('future-price-low', low.to_dict())
    assert high.status == low.status == 'feasible', (high.to_dict(), low.to_dict())
    assert abs(high.planned_actions[1].current_A - low.planned_actions[1].current_A) > 1e-3
    assert high.diagnostics['snapshot_content_sha256'] == low.diagnostics['snapshot_content_sha256']
    assert high.diagnostics['weights_sha256'] == low.diagnostics['weights_sha256']


def test_eight_joint_heat_constraints_and_actual_COP_energy_cash():
    snapshot, model, package = fixture(SiteModel(SiteParameters(thermal_capacity_J_per_K=2, thermal_cop=1.5)), temperature=310)
    schedule = [MPCStage(5, .15, .10, 310.5)] * 2
    response = SC.plan(snapshot, model, package, schedule,
        parameters=parameters(thermal_min_W=-.2, thermal_max_W=.1, temperature_max_K=310.08))
    save('thermal-joint', response.to_dict())
    assert response.status == 'feasible', response.to_dict()
    assert any(action.thermal_W < -1e-5 for action in response.planned_actions)
    for row in response.diagnostics['scenario_predictions']:
        for stage in row['stages']:
            assert stage['temperature_range_K'][1] <= 310.08 + 1e-5
            assert stage['predicted_thermal_electric_energy_J'] == pytest.approx(abs(stage['thermal_W']) * stage['elapsed_s'] / 1.5)
    action = response.action
    sampled = SC.particle_model(model, snapshot.samples[0][-2], snapshot.samples[0][-1])
    actual = sampled.integrate(snapshot.samples[0][:5], action.current_A, action.duration_s, ambient_K=310.5, thermal_W=action.thermal_W, max_step_s=5)
    ledger = EnergyLedger('synthetic-scenario-COP-check')
    entry = ledger.append(action, execution_id='first-only', energy_J=actual.energy_J,
        thermal_energy_J=actual.thermal_management_energy_J, buy_price_per_kWh=.15, sell_price_per_kWh=.10,
        duration_s=actual.elapsed_s)
    predicted = response.diagnostics['scenario_predictions'][0]['stages'][0]
    assert entry['net_cashflow'] == pytest.approx(predicted['predicted_cashflow'], abs=1e-14)
    save('thermal-first-executed-fixture', {'entry': entry, 'elapsed_s': actual.elapsed_s,
        'predicted': predicted, 'scope': 'One explicit synthetic control evaluator; not a new independent experiment'})


def test_zero_weight_bad_joint_state_cannot_be_hidden_by_mean():
    snapshot, model, package = fixture()
    rows = deepcopy(snapshot.samples); rows[-1][4] = 340
    bad = snapshot.model_copy(update={'samples': rows})
    response = SC.plan(bad, model, package, stages(), parameters=parameters())
    save('bad-zero-weight-state', response.to_dict())
    assert response.status != 'feasible' and response.action is None
    assert 'owned_pid' not in response.diagnostics
    assert response.diagnostics['fallback']['executable'] is False


def test_zero_weight_negative_joint_parameter_is_not_averaged_away():
    snapshot, model, package = fixture()
    rows = deepcopy(snapshot.samples); rows[-1][-2] = -1
    response = SC.plan(snapshot.model_copy(update={'samples': rows}), model, package, stages(), parameters=parameters())
    assert response.action is None and response.status == 'unknown' and 'owned_pid' not in response.diagnostics


def test_candidate_budget_is_unknown_and_fallback_is_same_information_only():
    snapshot, model, package = current()
    response = SC.plan(snapshot, model, package, stages(), parameters=parameters(max_candidate_evaluations=1))
    save('candidate-budget', response.to_dict())
    assert response.status == 'unknown' and response.action is None
    assert response.diagnostics['counters']['candidate_evaluations'] == 1
    backup = response.diagnostics['fallback']
    assert backup['action']['snapshot_id'] == snapshot.snapshot_id
    assert backup['snapshot_content_sha256'] == SC._hash(snapshot.model_dump(mode='json'))
    assert backup['weights_sha256'] == SC._hash(snapshot.weights)
    assert backup['automatically_executed'] is False and backup['executable'] is False
    assert backup['all_scenario_future_feasibility'].startswith('UNKNOWN')


def test_strict_T3_and_stale_actual_physical_package_do_not_launch_optimizer():
    snapshot, model, package = current()
    strict = SC.plan(snapshot, model, package, stages(), parameters=parameters(), admission_mode='strict')
    assert strict.status == 'unknown' and strict.action is None and 'owned_pid' not in strict.diagnostics
    assert 'T3' in strict.reason
    changed = deepcopy(package); changed['parameters']['resistance_ohm'] += .001
    stale = SC.plan(snapshot, model, changed, stages(), parameters=parameters())
    assert stale.status == 'unknown' and stale.action is None and 'owned_pid' not in stale.diagnostics


def test_future_start_and_single_stage_are_not_current_observed_plan():
    snapshot, model, package = current()
    with pytest.raises(ValueError, match='2..8'): SC.plan(snapshot, model, package, stages()[:1])
    with pytest.raises(ValueError, match='observation time'): SC.plan(snapshot, model, package, stages(), start_s=45)


def test_actual_active_integrator_is_hard_budgeted_without_partial_action():
    snapshot, model, package = current()
    started = time.monotonic()
    response = SC.plan(snapshot, model, package, [MPCStage(3600, .1, .2, 299.15)] * 2,
        parameters=parameters(wall_budget_s=8, prediction_max_step_s=.002, max_iterations=2))
    save('active-integrator-timeout', response.to_dict())
    assert response.status == 'unknown' and response.action is None
    assert response.diagnostics['timed_out'] is True
    assert '"phase": "integrating"' in response.diagnostics['worker_stderr']
    assert response.diagnostics['termination']['exit_code'] == 0
    assert time.monotonic() - started < 12


def test_physical_subclass_cannot_be_reconstructed_as_builtin():
    snapshot, model, package = current()
    class DifferentPhysics(SiteModel):
        def rhs(self, *args, **kwargs): raise AssertionError('not builtin')
    with pytest.raises(TypeError, match='declared SiteModel'):
        SC.plan(snapshot, DifferentPhysics(), package, stages())


if __name__ == '__main__':
    code = pytest.main([str(Path(__file__)), '-q', '-p', 'no:cacheprovider'])
    print(json.dumps({'exit_code': int(code), 'out': str(OUT),
        'source_sha256': hashlib.sha256((STAGE / 'scenario_mpc.py').read_bytes()).hexdigest(),
        'scope': 'Author actual synthetic scenario math/controls only; original public test unchanged'}))
    raise SystemExit(code)
