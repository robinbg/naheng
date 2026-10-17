"""Actual SiteModel forwards and closed-form Gaussian arithmetic; synthetic only."""
from copy import deepcopy
from dataclasses import asdict, replace
import importlib.util
import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from naheng.domain.contracts import Observation, PosteriorSnapshot
from naheng.estimation.calibration import CalibrationBinding, GaussianNoise, content_hash
from naheng.estimation.diagnostics import weighted_quantiles
from naheng.estimation.particle_filter import particle_model
from naheng.models.site_model import SiteModel, SiteParameters
from naheng.packages.registry import content_hash as parameter_content_hash

if os.environ.get('NAHENG_JOINT_OBSERVER_CANDIDATE'):
    _path = Path(os.environ['NAHENG_JOINT_OBSERVER_CANDIDATE']).resolve()
    _spec = importlib.util.spec_from_file_location('staged_joint_gaussian_observer', _path)
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    JointGaussianObserver, JointObserverUnknown = _module.JointGaussianObserver, _module.JointObserverUnknown
else:
    from naheng.estimation.joint_gaussian_observer import JointGaussianObserver, JointObserverUnknown


def inputs(model=None, rows=None, weights=None, covariance=((.0025, .009), (.009, .04)), bias=(.015, -.08)):
    model = model or SiteModel()
    if rows is None:
        rows = [model.initial_state(soc=soc, temperature_K=temp).tolist() + [rate, side]
                for soc, temp, rate, side in ((.45, 298., .7, 1.2), (.6, 298.2, 1.1, .6), (.75, 298.4, 1.6, 1.8))]
    weights = [.2, .5, .3] if weights is None else weights
    values, w = np.asarray(rows), np.asarray(weights)
    names = [*model.state_names, 'rate_scale', 'side_rate_scale']
    means = dict(zip(names, np.average(values, axis=0, weights=w)))
    socs = values[:, :2] @ np.asarray(model.params.site_capacity_mol) / sum(model.params.site_capacity_mol)
    means['soc'] = float(w @ socs)
    quantiles = {name: weighted_quantiles(values[:, i], w) for i, name in enumerate(names)}
    quantiles['soc'] = weighted_quantiles(socs, w)
    snapshot = PosteriorSnapshot(snapshot_id='synthetic-joint-prior', run_id='synthetic-observer-run',
        model_package_id='research_base-v1', parameter_revision='verified-synthetic-revision',
        obs_until_s=40., state_names=names, state_units=[*model.state_units, '1', '1'],
        samples=rows, weights=weights, mean=means, quantiles=quantiles,
        ess=float(1 / (w @ w)), identifiability=['synthetic_conditional_test_only'])
    binding = CalibrationBinding(chemistry_id='synthetic_two_site', model_id='two_site_current_adapter_v1',
        model_package_id=snapshot.model_package_id, parameter_revision=snapshot.parameter_revision,
        source_id='synthetic-test-source', source_revision='1', model_source_sha256='a' * 64,
        parameter_sha256=parameter_content_hash(asdict(model.params)), source_sha256='b' * 64,
        chemistry_identity_status='declared_compatible', source_identity_status='declared_compatible',
        provenance_type='synthetic')
    noise = GaussianNoise(noise_id='synthetic-combined-error', source_ref='synthetic:declared-policy',
        source_sha256='c' * 64, binding=binding, channels=('voltage_V', 'temperature_K'), units=('V', 'K'),
        covariance=covariance, bias=bias, component_scope='combined_error_assumption',
        assumption_text='Synthetic conditional likelihood calibration; not identified pure sensor noise',
        temporally_independent_likelihood_declared=True)
    return snapshot, model, noise


def forwards(snapshot, model, duration=5., current=.02, ambient=299.15, thermal=0.):
    predictions, rows = [], []
    for row in snapshot.samples:
        actual_model = particle_model(model, row[-2], row[-1])
        result = actual_model.integrate(row[:5], current, duration, ambient_K=ambient, thermal_W=thermal)
        assert result.elapsed_s == duration
        rows.append(result.state.tolist() + row[-2:])
        predictions.append([actual_model.observe(result.state, current)['voltage_V'], float(result.state[4])])
    return np.asarray(predictions), np.asarray(rows)


def sensor(snapshot, values, *, timestamp=45., current=.02):
    return Observation(run_id=snapshot.run_id, timestamp_s=timestamp, current_A=current,
                       voltage_V=float(values[0]), temperature_K=float(values[1]))


def literal_bayes(prior, predictions, observed, covariance, bias):
    # Independent scalar inverse of the two-by-two matrix; never calls candidate.
    a, b, d = covariance[0][0], covariance[0][1], covariance[1][1]
    determinant = a * d - b * b
    score = []
    for prediction in predictions:
        x, y = observed[0] - prediction[0] - bias[0], observed[1] - prediction[1] - bias[1]
        score.append(-.5 * (d * x * x - 2 * b * x * y + a * y * y) / determinant)
    logs = [math.log(w) + s if w > 0 else -math.inf for w, s in zip(prior, score)]
    maximum = max(logs)
    weights = [math.exp(logw - maximum) if w > 0 else 0. for w, logw in zip(prior, logs)]
    return np.asarray(weights) / sum(weights)


def test_actual_correlated_biased_forward_matches_scalar_gaussian_bayes():
    snapshot, model, noise = inputs()
    before = snapshot.model_dump(mode='json')
    predictions, rows = forwards(snapshot, model)
    observed = predictions[1] + [.03, .15]
    expected = literal_bayes(snapshot.weights, predictions, observed, noise.covariance, noise.bias)
    diagonal = literal_bayes(snapshot.weights, predictions, observed, ((.0025, 0.), (0., .04)), noise.bias)
    zero_bias = literal_bayes(snapshot.weights, predictions, observed, noise.covariance, (0., 0.))
    assert np.max(np.abs(expected - diagonal)) > 1e-5
    assert np.max(np.abs(expected - zero_bias)) > 1e-5
    observer = JointGaussianObserver(snapshot, model, noise)
    result = observer.update(sensor(snapshot, observed), duration_s=5, ambient_K=299.15)
    assert result.weights == pytest.approx(expected, abs=1e-12)
    assert np.asarray(result.samples) == pytest.approx(rows, abs=1e-12)
    assert result.mean['temperature_K'] == pytest.approx(expected @ rows[:, 4])
    assert result.mean['temperature_K'] != pytest.approx(observed[1], abs=1e-5)
    assert np.asarray(result.samples)[:, -2:] == pytest.approx(np.asarray(snapshot.samples)[:, -2:])
    diagnostic = observer.update_diagnostics[-1]
    assert diagnostic['represented_forward_solves'] == 3
    assert diagnostic['predictions'] == pytest.approx(predictions)
    assert np.asarray(diagnostic['innovations']) == pytest.approx(observed - predictions - noise.bias)
    assert result.ess == pytest.approx(1 / (expected @ expected))
    assert snapshot.model_dump(mode='json') == before
    json.dumps(diagnostic, allow_nan=False)
    assert diagnostic['risk_certificate'] is False


def test_adoption_and_rekey_preserve_rows_weights_time_and_defensive_properties():
    snapshot, model, noise = inputs()
    before = deepcopy(snapshot.model_dump())
    observer = JointGaussianObserver(snapshot, model, noise, run_id='explicit-new-run')
    adopted = observer.snapshot
    assert adopted.run_id == 'explicit-new-run' and adopted.snapshot_id != snapshot.snapshot_id
    assert adopted.samples == snapshot.samples and adopted.weights == snapshot.weights and adopted.obs_until_s == 40
    adopted.samples[0][0] = .99
    assert observer.snapshot.samples == snapshot.samples
    assert snapshot.model_dump() == before and observer.update_diagnostics == []
    assert observer.adoption_record['samples_weights_time_preserved'] is True


def test_exact_zero_prior_weight_is_not_revived_and_still_has_actual_forward():
    snapshot, model, noise = inputs(weights=[.7, .3, 0.])
    predictions, _ = forwards(snapshot, model)
    observer = JointGaussianObserver(snapshot, model, noise)
    result = observer.update(sensor(snapshot, predictions[2]), 5, ambient_K=299.15)
    assert result.weights[2] == 0.
    assert len(observer.update_diagnostics[-1]['forward_results']) == 3
    assert observer.update_diagnostics[-1]['forward_results'][2]['parent_index'] == 2


def test_all_eight_joint_rows_and_common_snapshot_are_preserved():
    model = SiteModel()
    rows = [model.initial_state(soc=.45 + .03 * i, temperature_K=298.1 + .025 * i).tolist()
            + [.6 + .1 * i, .8 + .08 * i] for i in range(8)]
    snapshot, model, noise = inputs(model, rows, [i / 36 for i in range(1, 9)])
    predictions, expected_rows = forwards(snapshot, model, thermal=.2)
    observer = JointGaussianObserver(snapshot, model, noise)
    result = observer.update(sensor(snapshot, predictions[4]), 5, ambient_K=299.15, thermal_W=.2)
    assert len(result.samples) == 8 and np.asarray(result.samples) == pytest.approx(expected_rows)
    assert observer.update_diagnostics[-1]['represented_forward_solves'] == 8
    capacities = np.asarray(model.params.site_capacity_mol)
    soc = expected_rows[:, :2] @ capacities / capacities.sum()
    assert result.mean['soc'] == pytest.approx(np.asarray(result.weights) @ soc)
    assert result.quantiles['rate_scale'] == weighted_quantiles(expected_rows[:, -2], result.weights)
    first, second = observer.snapshot, observer.snapshot
    assert content_hash(first) == content_hash(second) == observer.update_diagnostics[-1]['snapshot_sha256']
    assert result.obs_until_s == 45. and result.parameter_revision == snapshot.parameter_revision


def test_weighted_parameter_interval_can_become_wider_without_new_samples():
    model = SiteModel()
    rows = [model.initial_state(soc=.6, temperature_K=t).tolist() + [r, 1.]
            for t, r in ((298.15, .6), (299., 1.), (298.15, 1.8))]
    snapshot, model, noise = inputs(model, rows, [.04, .92, .04], ((.0025, 0.), (0., .01)), (0., 0.))
    predictions, _ = forwards(snapshot, model)
    observer = JointGaussianObserver(snapshot, model, noise)
    result = observer.update(sensor(snapshot, predictions[0]), 5, ambient_K=299.15)
    assert result.quantiles['rate_scale'][2] - result.quantiles['rate_scale'][0] > snapshot.quantiles['rate_scale'][2] - snapshot.quantiles['rate_scale'][0]
    assert [row[-2:] for row in result.samples] == [row[-2:] for row in snapshot.samples]
    assert observer.update_diagnostics[-1]['resampling_performed'] is False


@pytest.mark.parametrize('bad', ['repeat', 'wrong_run', 'duration', 'nan_current', 'ambient', 'thermal', 'long_interval', 'bool_duration', 'bool_current', 'bool_ambient', 'bool_thermal'])
def test_invalid_sensor_or_history_preserves_observer_exactly(bad):
    snapshot, model, noise = inputs()
    observer = JointGaussianObserver(snapshot, model, noise)
    reading = sensor(snapshot, [3.2, 298.2])
    duration, kwargs = 5., {}
    if bad == 'repeat': reading = reading.model_copy(update={'timestamp_s': 40.})
    if bad == 'wrong_run': reading = reading.model_copy(update={'run_id': 'other'})
    if bad == 'duration': duration = 4.
    if bad == 'nan_current': reading = reading.model_copy(update={'current_A': math.nan})
    if bad == 'ambient': kwargs['ambient_K'] = 500.
    if bad == 'thermal': kwargs['thermal_W'] = math.inf
    if bad == 'long_interval': reading, duration = reading.model_copy(update={'timestamp_s': 3641.}), 3601.
    if bad == 'bool_duration': duration = True
    if bad == 'bool_current': reading = reading.model_copy(update={'current_A': True})
    if bad == 'bool_ambient': kwargs['ambient_K'] = True
    if bad == 'bool_thermal': kwargs['thermal_W'] = False
    before = observer.snapshot.model_dump()
    with pytest.raises((ValueError, JointObserverUnknown)):
        observer.update(reading, duration, **kwargs)
    assert observer.snapshot.model_dump() == before and observer.update_diagnostics == []


def test_actual_early_terminal_stop_rolls_back_even_for_zero_weight_parent():
    model = SiteModel(replace(SiteParameters(), temperature_max_K=299.))
    rows = [model.initial_state(temperature_K=t).tolist() + [1., 1.] for t in (298.15, 298.2, 298.99)]
    snapshot, model, noise = inputs(model, rows, [.7, .3, 0.])
    observer = JointGaussianObserver(snapshot, model, noise)
    before = observer.snapshot.model_dump()
    with pytest.raises(JointObserverUnknown, match='represented_particle_early_stop:2'):
        observer.update(sensor(snapshot, [3.2, 298.2]), 5, ambient_K=298.15, thermal_W=.5)
    assert observer.snapshot.model_dump() == before and observer.update_diagnostics == []


def test_timeout_and_nonfinite_likelihood_support_roll_back_without_floor_weights():
    snapshot, model, noise = inputs()
    timed = JointGaussianObserver(snapshot, model, noise, wall_budget_s=1e-12)
    with pytest.raises(JointObserverUnknown, match='wall_budget'):
        timed.update(sensor(snapshot, [3.2, 298.2]), 5)
    assert timed.snapshot.model_dump() == snapshot.model_dump() and timed.update_diagnostics == []
    _, _, tiny = inputs(covariance=((1e-320, 0.), (0., 1e-320)), bias=(0., 0.))
    unsupported = JointGaussianObserver(snapshot, model, tiny)
    with pytest.raises(JointObserverUnknown, match='likelihood'):
        unsupported.update(sensor(snapshot, [3.3, 298.8]), 5)
    assert unsupported.snapshot.model_dump() == snapshot.model_dump() and unsupported.update_diagnostics == []


@pytest.mark.parametrize('bad', ['noise_binding', 'channels', 'nonspd', 'asymmetric', 'parameter', 'row_nan', 'bad_zero_weight_row', 'factorization'])
def test_invalid_adoption_is_rejected_even_with_unvalidated_model_copy(bad):
    snapshot, model, noise = inputs()
    if bad == 'noise_binding': noise = noise.model_copy(update={'binding': noise.binding.model_copy(update={'parameter_revision': 'other'})})
    if bad == 'channels': noise = noise.model_copy(update={'channels': ('temperature_K', 'voltage_V')})
    if bad == 'nonspd': noise = noise.model_copy(update={'covariance': ((1., 2.), (2., 1.))})
    if bad == 'asymmetric': noise = noise.model_copy(update={'covariance': ((.0025, .009), (.009 + 1e-15, .04))})
    if bad == 'parameter': noise = noise.model_copy(update={'binding': noise.binding.model_copy(update={'parameter_sha256': 'f' * 64})})
    if bad in {'row_nan', 'bad_zero_weight_row'}:
        rows = deepcopy(snapshot.samples)
        rows[2][0] = math.nan if bad == 'row_nan' else 1.2
        snapshot = snapshot.model_copy(update={'samples': rows, 'weights': [.7, .3, 0.]})
    if bad == 'factorization': noise = noise.model_copy(update={'temporally_independent_likelihood_declared': False})
    with pytest.raises((ValueError, np.linalg.LinAlgError)):
        JointGaussianObserver(snapshot, model, noise)


def test_success_then_rejected_repeat_preserves_committed_diagnostics_and_snapshot():
    snapshot, model, noise = inputs()
    predictions, _ = forwards(snapshot, model)
    observer = JointGaussianObserver(snapshot, model, noise)
    reading = sensor(snapshot, predictions[1])
    observer.update(reading, ambient_K=299.15)
    prior, diagnostics = observer.snapshot.model_dump(), observer.update_diagnostics
    diagnostics[0]['posterior_weights'][0] = -1
    saved = observer.update_diagnostics
    with pytest.raises(ValueError, match='strictly increase'):
        observer.update(reading)
    assert observer.snapshot.model_dump() == prior and observer.update_diagnostics == saved


def test_row_budget_is_explicit_and_does_not_silently_subsample():
    snapshot, model, noise = inputs()
    rows = [deepcopy(snapshot.samples[0]) for _ in range(257)]
    expanded = snapshot.model_copy(update={'samples': rows, 'weights': [1 / 257] * 257, 'ess': 257.})
    with pytest.raises(ValueError, match='256 represented rows'):
        JointGaussianObserver(expanded, model, noise)


def test_finite_noisy_reading_outside_physical_domain_is_not_a_true_state():
    snapshot, model, noise = inputs()
    predictions, rows = forwards(snapshot, model)
    observed = np.asarray([4.8, 450.])
    expected = literal_bayes(snapshot.weights, predictions, observed, noise.covariance, noise.bias)
    observer = JointGaussianObserver(snapshot, model, noise)
    result = observer.update(sensor(snapshot, observed), 5, ambient_K=299.15)
    assert result.weights == pytest.approx(expected, abs=1e-12)
    assert np.asarray(result.samples) == pytest.approx(rows, abs=1e-12)
    assert all(model.params.temperature_min_K <= row[4] <= model.params.temperature_max_K for row in result.samples)
    assert result.mean['temperature_K'] != observed[1]
    assert observer.update_diagnostics[-1]['sensor_reading_outside_physical_domain'] == ['voltage_V', 'temperature_K']
    assert observer.update_diagnostics[-1]['sensor_values_overwrote_physical_state'] is False
    assert 'sensor_outside_physical_domain_not_a_state_observation' in result.identifiability


@pytest.mark.parametrize('budget', [True, 0., -1., 101., math.nan])
def test_invalid_soft_budget_is_not_silently_relaxed(budget):
    snapshot, model, noise = inputs()
    with pytest.raises(ValueError):
        JointGaussianObserver(snapshot, model, noise, wall_budget_s=budget)
