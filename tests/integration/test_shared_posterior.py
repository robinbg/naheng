"""Synthetic mathematical calibration tests, not real-cell or UI acceptance."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys

import numpy as np
from pydantic import ValidationError
import pytest

from naheng.estimation.calibration import (
    CalibrationBinding, DerivedObservable, GaussianNoise, TrainingObservation,
    TrainingBatch, PropagationEvidence, freeze_posterior, fit_candidate,
    particle_ids, posterior_to_contract, content_hash,
)
from naheng.estimation.discrepancy import monitor_discrepancy
from naheng.domain.contracts import PosteriorSnapshot
from naheng.estimation.diagnostics import weighted_quantiles


def replace(instance, **changes):
    value = instance.model_dump(mode='python')
    value.update(changes)
    return type(instance).model_validate(value)


def example():
    """Known arithmetic fixture: correlated state/theta, middle-heavy prior."""
    binding = CalibrationBinding(chemistry_id='synthetic_declared_fixture', model_id='fixture-linear',
        model_package_id='fixture-package-v1', parameter_revision='fixture-parameter-v1',
        source_id='fixture-training-source', source_revision='fixture-source-v1',
        model_source_sha256='1' * 64, parameter_sha256='2' * 64, source_sha256='3' * 64,
        chemistry_identity_status='declared_compatible', source_identity_status='declared_compatible',
        provenance_type='synthetic')
    samples = [[.2, 0.], [.4, 1.], [.6, 2.]]
    weights = [.01, .98, .01]
    raw = PosteriorSnapshot(snapshot_id='fixture-prior', run_id='fixture-run',
        model_package_id=binding.model_package_id, parameter_revision=binding.parameter_revision,
        obs_until_s=0., state_names=['state', 'theta'], state_units=['1', '1'],
        samples=samples, weights=weights,
        mean={'state': .4, 'theta': 1., 'soc': .4},
        quantiles={name: weighted_quantiles(values, weights) for name, values in (
            ('state', [.2, .4, .6]), ('theta', [0., 1., 2.]), ('soc', [.2, .4, .6]))},
        ess=1 / sum(w*w for w in weights), identifiability=['synthetic_not_real_data'])
    derived = (DerivedObservable(name='soc', unit='1', particle_values=(.2, .4, .6)),)
    prior = freeze_posterior(raw, binding, parameter_state_names=('theta',), derived_observables=derived)
    observations = tuple(TrainingObservation(observation_id=f'fixture-observation-{i}', binding=binding,
        timestamp_s=float(i+1), role='train', values=(0.,)) for i in range(3))
    batch = TrainingBatch(binding=binding, prediction_binding=binding, snapshot_id=prior.snapshot_id,
        posterior_content_sha256=prior.content_sha256, trajectory_id='fixture-training-trajectory',
        cell_id='fixture-cell', channels=('voltage',), units=('V',), observations=observations,
        nominal_predictions=((-1.,), (0.,), (1.,)),
        particle_predictions=tuple(((0.,), (2.,), (0.,)) for _ in observations), particle_ids=particle_ids(prior),
        compatible_train_declared=True, compatibility_declaration_ref='fixture-compatible-declaration',
        assimilation_prefix_snapshot_id=prior.snapshot_id,
        unassimilated_observation_ids=tuple(o.observation_id for o in observations), available_until_s=3.,
        propagated_joint_samples=((.3, 0.), (.5, 1.), (.7, 2.)), propagated_until_s=3.,
        propagation_evidence=PropagationEvidence(source_ref='fixture-forward-evidence', artifact_sha256='4'*64,
            model_source_sha256=binding.model_source_sha256, parent_content_sha256=prior.content_sha256),
        propagated_derived_observables=(DerivedObservable(name='soc', unit='1', particle_values=(.3, .5, .7)),),
        input_scope='synthetic_math_fixture')
    noise = GaussianNoise(noise_id='fixture-unit-Gaussian', source_ref='fixture-noise-assumption', source_sha256='5'*64,
        binding=binding, channels=batch.channels, units=batch.units, covariance=((1.,),), bias=(0.,),
        component_scope='combined_error_assumption', assumption_text='Synthetic known conditional Gaussian errors; no physical calibration',
        temporally_independent_likelihood_declared=True)
    return raw, prior, batch, noise


def test_actual_likelihood_weights_bias_covariance_and_joint_statistics():
    raw, prior, batch, noise = example()
    before = content_hash(raw)
    result = fit_candidate(prior, batch, noise)
    assert result.status == 'PASS'
    posterior = result.candidate.posterior
    # Analytic likelihood: 3 innovations of2 at middle particle => exp(-6).
    denominator = .02 + .98 * math.exp(-6.)
    expected_weights = (.01/denominator, .98*math.exp(-6.)/denominator, .01/denominator)
    assert posterior.weights == pytest.approx(expected_weights)
    assert posterior.ess == pytest.approx(1/sum(w*w for w in expected_weights))
    assert posterior.samples == batch.propagated_joint_samples
    assert tuple(row[1] for row in posterior.samples) == tuple(row[1] for row in prior.samples)
    assert posterior.mean == pytest.approx((.5, 1., .5))
    assert posterior.obs_until_s == 3.
    assert posterior.quantiles[2] == posterior.quantiles[0]
    assert result.residual_statistics.residuals == ((1.,), (0.,), (-1.,))
    assert result.residual_statistics.mean_bias == (0.,)
    assert result.residual_statistics.covariance == ((1.,),)
    assert result.residual_statistics.std == (1.,)
    assert result.residual_statistics.measurement_noise_identified is False
    assert result.candidate.parent_content_sha256 == prior.content_sha256
    assert result.candidate.calibration_input_sha256 == content_hash(batch)
    assert result.candidate.noise_sha256 == content_hash(noise)
    assert result.candidate.posterior.model_package_id == prior.model_package_id
    assert result.candidate.posterior.parameter_revision == prior.parameter_revision
    assert result.candidate.content_sha256 != prior.content_sha256
    assert content_hash(raw) == before


def test_parameter_posterior_can_be_wider_without_altering_parameter_samples():
    _, prior, batch, noise = example()
    candidate = fit_candidate(prior, batch, noise).candidate
    old = prior.quantiles[1][-1] - prior.quantiles[1][0]
    new = candidate.posterior.quantiles[1][-1] - candidate.posterior.quantiles[1][0]
    assert new > old
    assert [row[1] for row in candidate.posterior.samples] == [0., 1., 2.]


def test_same_candidate_for_three_module_consumers_is_immutable_and_copy_safe():
    _, prior, batch, noise = example()
    candidate = fit_candidate(prior, batch, noise).candidate
    views = {name: posterior_to_contract(candidate) for name in ('RUL', 'risk', 'revenue')}
    assert len({view.snapshot_id for view in views.values()}) == 1
    assert len({content_hash(view) for view in views.values()}) == 1
    assert all(view.samples == views['RUL'].samples and view.weights == views['RUL'].weights for view in views.values())
    before = candidate.content_sha256
    views['risk'].samples[0][0] = 99.
    assert views['RUL'].samples[0][0] == .3 and views['revenue'].samples[0][0] == .3
    assert candidate.content_sha256 == before
    with pytest.raises(ValidationError):
        candidate.posterior.weights = (.1, .8, .1)
    with pytest.raises(TypeError):
        candidate.posterior.samples[0][0] = 99.


@pytest.mark.parametrize('role', ['test', 'validation', 'stress'])
def test_heldout_and_stress_never_fit(role):
    _, prior, batch, noise = example()
    bad = replace(batch, observations=tuple(replace(o, role=role) for o in batch.observations))
    result = fit_candidate(prior, bad, noise)
    assert result.status == 'FAIL' and result.candidate is None and result.residual_statistics is None
    assert 'heldout_or_stress_observations_must_not_fit' in result.reasons


@pytest.mark.parametrize('identity', ['chemistry_identity_status', 'source_identity_status'])
def test_unknown_material_or_source_remains_unknown(identity):
    raw, prior, batch, noise = example()
    unknown = replace(prior.binding, **{identity: 'UNKNOWN'})
    p = freeze_posterior(raw, unknown, parameter_state_names=('theta',), derived_observables=prior.derived_observables)
    b = replace(batch, binding=unknown, prediction_binding=unknown, posterior_content_sha256=p.content_sha256,
        observations=tuple(replace(o, binding=unknown) for o in batch.observations),
        propagation_evidence=replace(batch.propagation_evidence, parent_content_sha256=p.content_sha256))
    result = fit_candidate(p, b, replace(noise, binding=unknown))
    assert result.status == 'UNKNOWN' and result.candidate is None


@pytest.mark.parametrize('field', ['chemistry_id', 'model_id', 'model_package_id', 'parameter_revision', 'source_id', 'source_revision'])
def test_distinct_physical_or_source_identities_cannot_mix(field):
    _, prior, batch, noise = example()
    other = replace(batch.binding, **{field: 'other-declared-identity'})
    bad = replace(batch, prediction_binding=other)
    assert fit_candidate(prior, bad, noise).status == 'FAIL'
    bad = replace(batch, observations=(replace(batch.observations[0], binding=other), *batch.observations[1:]))
    result = fit_candidate(prior, bad, noise)
    assert result.status == 'FAIL' and 'per_observation_chemistry_or_source_binding_mismatch' in result.reasons


@pytest.mark.parametrize('field', ['model_source_sha256', 'parameter_sha256', 'source_sha256'])
def test_source_byte_revisions_are_part_of_binding(field):
    _, prior, batch, noise = example()
    bad = replace(batch, prediction_binding=replace(batch.binding, **{field: '6'*64}))
    assert fit_candidate(prior, bad, noise).status == 'FAIL'


@pytest.mark.parametrize('changes', [
    {'snapshot_id': 'other-snapshot'}, {'posterior_content_sha256': '6'*64},
    {'particle_ids': ('6'*64, '7'*64, '8'*64)}, {'assimilation_prefix_snapshot_id': 'other-prefix'},
    {'unassimilated_observation_ids': ('observation-not-declared',)},
])
def test_snapshot_order_and_assimilation_disjointness(changes):
    _, prior, batch, noise = example()
    result = fit_candidate(prior, replace(batch, **changes), noise)
    assert result.status == 'FAIL' and result.candidate is None


@pytest.mark.parametrize('changes', [
    {'propagated_joint_samples': None}, {'propagated_until_s': None}, {'propagation_evidence': None},
    {'compatible_train_declared': False},
])
def test_future_data_without_propagation_or_compatibility_never_yields_runtime_snapshot(changes):
    _, prior, batch, noise = example()
    result = fit_candidate(prior, replace(batch, **changes), noise)
    assert result.status == 'UNKNOWN' and result.candidate is None
    assert prior.obs_until_s == 0. and prior.samples[0] == (.2, 0.)


@pytest.mark.parametrize('changes', [
    {'propagated_until_s': 4.}, {'available_until_s': 2.},
    {'propagated_joint_samples': ((.3, .1), (.5, 1.), (.7, 2.))},
    {'propagated_joint_samples': ((.3, 0.),)}, {'propagated_derived_observables': ()},
])
def test_bad_propagation_cutoff_parameters_dimensions_and_readout_rejected(changes):
    _, prior, batch, noise = example()
    result = fit_candidate(prior, replace(batch, **changes), noise)
    assert result.status == 'FAIL' and result.candidate is None


def test_propagation_model_source_and_parent_content_need_exact_binding():
    _, prior, batch, noise = example()
    for field in ('model_source_sha256', 'parent_content_sha256'):
        bad = replace(batch, propagation_evidence=replace(batch.propagation_evidence, **{field: '6'*64}))
        assert fit_candidate(prior, bad, noise).status == 'FAIL'


def test_old_repeated_or_out_of_order_timestamps_never_assimilated():
    _, prior, batch, noise = example()
    for times in ((0., 2., 3.), (1., 1., 3.), (2., 1., 3.)):
        bad = replace(batch, observations=tuple(replace(o, timestamp_s=t) for o, t in zip(batch.observations, times)))
        assert fit_candidate(prior, bad, noise).status == 'FAIL'


def test_minimum_residual_samples_time_and_explicit_noise_conditions():
    _, prior, batch, noise = example()
    short = replace(batch, observations=batch.observations[:2], nominal_predictions=batch.nominal_predictions[:2],
        particle_predictions=batch.particle_predictions[:2], unassimilated_observation_ids=batch.unassimilated_observation_ids[:2],
        available_until_s=2., propagated_until_s=2.)
    assert fit_candidate(prior, short, noise).status == 'UNKNOWN'
    assert fit_candidate(prior, batch, noise, minimum_span_s=10.).status == 'UNKNOWN'
    assert fit_candidate(prior, batch, None).status == 'UNKNOWN'
    assert fit_candidate(prior, batch, replace(noise, temporally_independent_likelihood_declared=False)).status == 'UNKNOWN'
    for covariance in (((0.,),), ((-1.,),)):
        with pytest.raises(ValidationError):
            replace(noise, covariance=covariance)


def test_missing_same_particle_SOC_or_false_original_statistics_rejected():
    raw, prior, batch, noise = example()
    with pytest.raises(ValueError, match='Every extra summary'):
        freeze_posterior(raw, prior.binding, parameter_state_names=('theta',))
    bad = raw.model_copy(deep=True)
    bad.mean['theta'] = 99.
    with pytest.raises(ValidationError, match='Summaries'):
        freeze_posterior(bad, prior.binding, parameter_state_names=('theta',), derived_observables=prior.derived_observables)
    badprior = replace(prior, parameter_state_names=())
    b = replace(batch, posterior_content_sha256=badprior.content_sha256,
        propagation_evidence=replace(batch.propagation_evidence, parent_content_sha256=badprior.content_sha256))
    assert fit_candidate(badprior, b, noise).status == 'UNKNOWN'


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_observations_predictions_and_bypass_copies_rejected(value):
    _, prior, batch, noise = example()
    with pytest.raises(ValidationError):
        replace(batch.observations[0], values=(value,))
    with pytest.raises(ValidationError):
        replace(batch, nominal_predictions=((value,), (0.,), (1.,)))
    with pytest.raises(ValidationError):
        fit_candidate(prior, batch.model_copy(update={'nominal_predictions': ((value,), (0.,), (1.,))}), noise)
    with pytest.raises(ValidationError):
        replace(noise, covariance=((value,),))


def test_strict_schema_rejects_hidden_truth_unknown_fields_and_bad_units():
    _, prior, batch, noise = example()
    with pytest.raises(ValidationError):
        replace(batch, hidden_truth=(0.,))
    with pytest.raises(TypeError):
        fit_candidate(prior, batch.model_dump(), noise)
    with pytest.raises(ValidationError):
        replace(batch, compatible_train_declared='true')
    assert fit_candidate(prior, batch, replace(noise, units=('K',))).status == 'FAIL'


def test_discrepancy_actual_innovations_window_bias_and_bounds_no_probability():
    _, prior, batch, noise = example()
    observations = tuple(replace(o, values=(4.,)) for o in batch.observations)
    bad = replace(batch, observations=observations, nominal_predictions=((0.,),)*3)
    result = monitor_discrepancy(prior, bad, noise, window=3, minimum_history=2, innovation_limit=3., bias_limit=2.)
    assert result.status == 'out_of_bounds'
    assert all(o.residual == o.standardized_innovation == o.whitened_innovation == (4.,) for o in result.observations)
    assert [o.window_count for o in result.observations] == [1, 2, 3]
    assert all(o.rolling_bias == o.rolling_standardized_bias == (4.,) for o in result.observations)
    assert all(o.exceeded_channels == ('voltage',) for o in result.observations)
    assert result.incident_probability is None and result.operating_risk_certificate is False
    assert 'overlapping_windows_not_independent_trajectories' in result.reasons


def test_discrepancy_can_monitor_heldout_without_fitting_or_zero_history_claim():
    _, prior, batch, noise = example()
    heldout = replace(batch, observations=tuple(replace(o, role='test') for o in batch.observations))
    result = monitor_discrepancy(prior, heldout, noise, window=3, minimum_history=3)
    assert result.status == 'within_declared_bounds'
    assert result.observations[0].status == 'UNKNOWN_insufficient_history'
    assert fit_candidate(prior, heldout, noise).status == 'FAIL'
    assert monitor_discrepancy(prior, heldout, noise, window=5, minimum_history=5).status == 'UNKNOWN'


def test_correlated_covariance_whitening_is_actual_linear_algebra():
    _, prior, batch, noise = example()
    observations = tuple(replace(o, values=(1., 2.)) for o in batch.observations)
    b = replace(batch, channels=('V', 'K'), units=('V', 'K'), observations=observations,
        nominal_predictions=((0., 0.),)*3,
        particle_predictions=tuple(((0., 0.), (1., 1.), (2., 2.)) for _ in observations))
    n = replace(noise, channels=b.channels, units=b.units, covariance=((1., .5), (.5, 4.)), bias=(0., 0.))
    result = monitor_discrepancy(prior, b, n, window=3, minimum_history=1)
    assert result.observations[0].standardized_innovation == (1., 1.)
    expected_second = 1.5/math.sqrt(3.75)
    assert result.observations[0].whitened_innovation == pytest.approx((1., expected_second))


def test_zero_empirical_scatter_does_not_create_zero_measurement_noise():
    _, prior, batch, noise = example()
    batch = replace(batch, nominal_predictions=((0.,),)*3)
    result = fit_candidate(prior, batch, noise)
    assert result.status == 'PASS' and result.residual_statistics.std == (0.,)
    assert result.residual_statistics.measurement_noise_identified is False
    assert result.candidate.noise_sha256 == content_hash(noise)


def test_reproducible_candidate_hashes_but_noise_revision_changes_lineage():
    _, prior, batch, noise = example()
    first = fit_candidate(prior, batch, noise).candidate
    assert first.content_sha256 == fit_candidate(prior, batch, noise).candidate.content_sha256
    second = fit_candidate(prior, batch, replace(noise, source_sha256='6'*64)).candidate
    assert second.noise_sha256 != first.noise_sha256 and second.content_sha256 != first.content_sha256
    assert second.posterior.snapshot_id != first.posterior.snapshot_id


def test_joint_correlated_innovation_catches_preserved_marginal_only_boundary():
    _, prior, batch, noise = example()
    observations = tuple(replace(o, values=(2., -2.)) for o in batch.observations)
    b = replace(batch, channels=('V', 'K'), units=('V', 'K'), observations=observations,
        nominal_predictions=((0., 0.),)*3,
        particle_predictions=tuple(((0., 0.), (1., 1.), (2., 2.)) for _ in observations))
    n = replace(noise, channels=b.channels, units=b.units, covariance=((1., .99), (.99, 1.)), bias=(0., 0.))
    result = monitor_discrepancy(prior, b, n, window=3, minimum_history=3)
    assert result.status == 'out_of_bounds' and result.joint_exceedance_count == 3
    assert result.joint_innovation_limit == 3.
    first = result.observations[0]
    assert first.standardized_innovation == (2., -2.) and first.exceeded_channels == ()
    assert first.mahalanobis_sq == pytest.approx(800.)
    assert first.joint_exceeded and first.status == 'out_of_bounds'
    assert result.joint_threshold_scope == 'declared_empirical_whitened_norm_not_probability'
    assert result.incident_probability is None and result.operating_risk_certificate is False
    assert 'whitened_components_are_mixed_coordinates_not_physical_channel_attribution' in result.reasons


def test_joint_threshold_policy_is_explicit_boundary_and_invalid_limits_rejected():
    _, prior, batch, noise = example()
    for limit in (0., -1., float('nan'), float('inf')):
        with pytest.raises(ValueError):
            monitor_discrepancy(prior, batch, noise, joint_innovation_limit=limit)
    b = replace(batch, nominal_predictions=((-3.,),)*3)
    boundary = monitor_discrepancy(prior, b, noise, window=3, minimum_history=3,
        innovation_limit=10., bias_limit=10., joint_innovation_limit=3.)
    assert boundary.status == 'within_declared_bounds'
    assert all(r.mahalanobis_sq == 9. and not r.joint_exceeded for r in boundary.observations)
    tighter = monitor_discrepancy(prior, b, noise, window=3, minimum_history=3,
        innovation_limit=10., bias_limit=10., joint_innovation_limit=2.99)
    assert tighter.status == 'out_of_bounds' and tighter.joint_exceedance_count == 3
