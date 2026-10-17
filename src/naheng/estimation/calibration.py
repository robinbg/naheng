"""Conditional joint-particle calibration, without registry or PF mutation.

Arrays and source declarations are caller inputs. Runtime source-file freshness,
actual model forward propagation and scientific calibration remain integration
obligations. Residual scatter is not identified measurement noise.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from naheng.domain.contracts import PosteriorSnapshot
from naheng.estimation.diagnostics import effective_sample_size, weighted_quantiles

Name = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r'\S')]
SHA256 = Annotated[str, StringConstraints(strict=True, pattern=r'^[a-f0-9]{64}$')]
Vector = tuple[float, ...]
Matrix = tuple[Vector, ...]


class Frozen(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True, allow_inf_nan=False)


def content_hash(value) -> str:
    payload = value.model_dump(mode='json') if isinstance(value, BaseModel) else value
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class CalibrationBinding(Frozen):
    chemistry_id: Name
    model_id: Name
    model_package_id: Name
    parameter_revision: Name
    source_id: Name
    source_revision: Name
    model_source_sha256: SHA256
    parameter_sha256: SHA256
    source_sha256: SHA256
    chemistry_identity_status: Literal['declared_compatible', 'UNKNOWN']
    source_identity_status: Literal['declared_compatible', 'UNKNOWN']
    provenance_type: Literal['synthetic', 'reference_simulation', 'public_measurement']


class DerivedObservable(Frozen):
    name: Name
    unit: Name
    particle_values: Vector


class FrozenPosterior(Frozen):
    snapshot_id: Name
    run_id: Name
    model_package_id: Name
    parameter_revision: Name
    obs_until_s: float = Field(ge=0)
    binding: CalibrationBinding
    source_snapshot_sha256: SHA256
    state_names: tuple[Name, ...]
    state_units: tuple[Name, ...]
    parameter_state_names: tuple[Name, ...]
    samples: Matrix
    weights: Vector
    derived_observables: tuple[DerivedObservable, ...]
    mean: Vector
    quantiles: Matrix
    ess: float = Field(gt=0)
    identifiability: tuple[str, ...]

    @model_validator(mode='after')
    def dimensions(self):
        n, d = len(self.samples), len(self.state_names)
        if not n or not d or len(set(self.state_names)) != d or len(self.state_units) != d:
            raise ValueError('Nonempty unique state definition required')
        if any(len(row) != d for row in self.samples) or len(self.weights) != n:
            raise ValueError('Joint particle dimensions disagree')
        if any(w < 0 for w in self.weights) or abs(sum(self.weights) - 1) > 1e-12:
            raise ValueError('Nonnegative normalized joint weights required')
        if len(set(self.parameter_state_names)) != len(self.parameter_state_names) or not set(self.parameter_state_names) <= set(self.state_names):
            raise ValueError('Parameter columns must be explicitly defined state columns')
        names = [item.name for item in self.derived_observables]
        if len(set(names)) != len(names) or set(names) & set(self.state_names):
            raise ValueError('Derived observables must have unique additional names')
        if any(len(item.particle_values) != n for item in self.derived_observables):
            raise ValueError('Derived values must use the same joint particle order')
        if len(self.mean) != d + len(names) or len(self.quantiles) != len(self.mean) or any(len(q) != 3 for q in self.quantiles):
            raise ValueError('Summary dimensions disagree')
        if self.binding.model_package_id != self.model_package_id or self.binding.parameter_revision != self.parameter_revision:
            raise ValueError('Posterior physical package/parameter revision mismatch')
        values = _summary(self.samples, self.weights, self.derived_observables)
        if not np.allclose(self.mean, values[0], rtol=1e-12, atol=1e-12) or not np.allclose(self.quantiles, values[1], rtol=1e-12, atol=1e-12):
            raise ValueError('Summaries are not computed from actual joint weighted samples')
        if not np.isclose(self.ess, values[2], rtol=1e-12, atol=1e-12):
            raise ValueError('ESS is not computed from actual weights')
        return self

    @property
    def content_sha256(self) -> str:
        return content_hash(self)


def _summary(samples: Matrix, weights: Vector, derived: tuple[DerivedObservable, ...]):
    values = np.asarray(samples, dtype=float)
    if derived:
        values = np.column_stack((values, *[item.particle_values for item in derived]))
    means = tuple(float(v) for v in np.average(values, axis=0, weights=weights))
    quantiles = tuple(tuple(weighted_quantiles(values[:, col], weights)) for col in range(values.shape[1]))
    return means, quantiles, effective_sample_size(weights)


def freeze_posterior(snapshot: PosteriorSnapshot, binding: CalibrationBinding, *,
                     parameter_state_names: tuple[str, ...],
                     derived_observables: tuple[DerivedObservable, ...] = ()) -> FrozenPosterior:
    """Copy and validate existing posterior; extra summaries need explicit readouts."""
    if not isinstance(snapshot, PosteriorSnapshot) or not isinstance(binding, CalibrationBinding):
        raise TypeError('Typed PosteriorSnapshot and CalibrationBinding required')
    original = PosteriorSnapshot.model_validate(snapshot.model_dump(mode='python'))
    names = tuple(original.state_names) + tuple(item.name for item in derived_observables)
    if set(original.mean) != set(names) or set(original.quantiles) != set(names):
        raise ValueError('Every extra summary (including SOC) needs same-particle derived values')
    return FrozenPosterior(snapshot_id=original.snapshot_id, run_id=original.run_id,
        model_package_id=original.model_package_id, parameter_revision=original.parameter_revision,
        obs_until_s=original.obs_until_s, binding=binding, source_snapshot_sha256=content_hash(original),
        state_names=tuple(original.state_names), state_units=tuple(original.state_units),
        parameter_state_names=parameter_state_names, samples=tuple(tuple(row) for row in original.samples),
        weights=tuple(original.weights), derived_observables=derived_observables,
        mean=tuple(original.mean[name] for name in names), quantiles=tuple(tuple(original.quantiles[name]) for name in names),
        ess=original.ess, identifiability=tuple(original.identifiability))


def particle_ids(prior: FrozenPosterior) -> tuple[str, ...]:
    return tuple(content_hash({'index': i, 'sample': row}) for i, row in enumerate(prior.samples))


class TrainingObservation(Frozen):
    observation_id: Name
    binding: CalibrationBinding
    timestamp_s: float = Field(ge=0)
    role: Literal['train', 'validation', 'test', 'stress']
    values: Vector


class PropagationEvidence(Frozen):
    source_ref: Name
    artifact_sha256: SHA256
    model_source_sha256: SHA256
    parent_content_sha256: SHA256


class TrainingBatch(Frozen):
    binding: CalibrationBinding
    prediction_binding: CalibrationBinding
    snapshot_id: Name
    posterior_content_sha256: SHA256
    trajectory_id: Name
    cell_id: Name
    channels: tuple[Name, ...]
    units: tuple[Name, ...]
    observations: tuple[TrainingObservation, ...]
    nominal_predictions: Matrix
    particle_predictions: tuple[Matrix, ...]  # observation x parent-particle x channel
    particle_ids: tuple[SHA256, ...]
    compatible_train_declared: bool
    compatibility_declaration_ref: Name
    assimilation_prefix_snapshot_id: Name
    unassimilated_observation_ids: tuple[Name, ...]
    available_until_s: float = Field(ge=0)
    propagated_joint_samples: Matrix | None = None
    propagated_until_s: float | None = Field(default=None, ge=0)
    propagation_evidence: PropagationEvidence | None = None
    propagated_derived_observables: tuple[DerivedObservable, ...] = ()
    input_scope: Literal['synthetic_math_fixture', 'declared_training_data']

    @model_validator(mode='after')
    def shapes(self):
        m, d = len(self.observations), len(self.channels)
        if not d or len(set(self.channels)) != d or len(self.units) != d:
            raise ValueError('Unique channels and matching units required')
        if len(self.nominal_predictions) != m or len(self.particle_predictions) != m:
            raise ValueError('Predictions must align with every observation')
        if any(len(o.values) != d for o in self.observations) or any(len(row) != d for row in self.nominal_predictions):
            raise ValueError('Observation/nominal channel mismatch')
        if any(len(pred) != len(self.particle_ids) or any(len(row) != d for row in pred) for pred in self.particle_predictions):
            raise ValueError('Particle prediction shape/order mismatch')
        if len({o.observation_id for o in self.observations}) != m:
            raise ValueError('Unique observation identities required')
        return self


class GaussianNoise(Frozen):
    """An explicitly supplied likelihood assumption, not inferred pure noise."""
    noise_id: Name
    source_ref: Name
    source_sha256: SHA256
    binding: CalibrationBinding
    channels: tuple[Name, ...]
    units: tuple[Name, ...]
    covariance: Matrix
    bias: Vector
    component_scope: Literal['measurement_noise_assumption', 'combined_error_assumption']
    assumption_text: Name
    temporally_independent_likelihood_declared: bool
    operating_distribution_calibrated: bool = False

    @model_validator(mode='after')
    def positive_definite(self):
        n = len(self.channels)
        if not n or len(self.units) != n or len(self.bias) != n or len(self.covariance) != n or any(len(row) != n for row in self.covariance):
            raise ValueError('Noise channel dimensions disagree')
        a = np.asarray(self.covariance)
        if not np.allclose(a, a.T, rtol=0, atol=1e-14):
            raise ValueError('Gaussian covariance must be symmetric')
        try:
            np.linalg.cholesky(a)
        except np.linalg.LinAlgError as error:
            raise ValueError('Strictly positive-definite covariance required; missing noise is not zero') from error
        return self


class ResidualStatistics(Frozen):
    residuals: Matrix
    mean_bias: Vector
    covariance: Matrix
    std: Vector
    observed_span_s: float
    interpretation: Literal['empirical_combined_observation_and_model_residual'] = 'empirical_combined_observation_and_model_residual'
    measurement_noise_identified: Literal[False] = False


class CalibrationCandidate(Frozen):
    posterior: FrozenPosterior
    parent_content_sha256: SHA256
    calibration_input_sha256: SHA256
    noise_sha256: SHA256
    noise_id: Name
    calibration_revision: Name
    scope: Literal['conditional_gaussian_joint_particle_candidate'] = 'conditional_gaussian_joint_particle_candidate'
    requires_explicit_new_run_adoption: Literal[True] = True
    source_files_freshness_verified_here: Literal[False] = False
    actual_forward_dynamics_verified_here: Literal[False] = False
    operating_risk_certificate: Literal[False] = False

    @property
    def content_sha256(self) -> str:
        return content_hash(self)


class CalibrationResult(Frozen):
    status: Literal['PASS', 'FAIL', 'UNKNOWN']
    reasons: tuple[str, ...]
    residual_statistics: ResidualStatistics | None = None
    candidate: CalibrationCandidate | None = None


def _eligibility(prior: FrozenPosterior, batch: TrainingBatch, noise: GaussianNoise | None, *, require_train=True):
    fails, unknowns = [], []
    if batch.binding != prior.binding or batch.prediction_binding != prior.binding:
        fails.append('chemistry_model_package_parameter_or_source_revision_mismatch')
    if any(o.binding != prior.binding for o in batch.observations):
        fails.append('per_observation_chemistry_or_source_binding_mismatch')
    if batch.snapshot_id != prior.snapshot_id or batch.posterior_content_sha256 != prior.content_sha256 or batch.particle_ids != particle_ids(prior):
        fails.append('snapshot_content_or_particle_order_mismatch')
    if require_train and any(o.role != 'train' for o in batch.observations):
        fails.append('heldout_or_stress_observations_must_not_fit')
    if not batch.compatible_train_declared:
        unknowns.append('compatible_observation_and_prediction_source_not_declared')
    if prior.binding.chemistry_identity_status == 'UNKNOWN' or prior.binding.source_identity_status == 'UNKNOWN':
        unknowns.append('chemistry_or_source_identity_UNKNOWN')
    timestamps = tuple(o.timestamp_s for o in batch.observations)
    if not timestamps:
        unknowns.append('no_observations')
    elif any(t <= prior.obs_until_s for t in timestamps) or any(a >= b for a, b in zip(timestamps, timestamps[1:])):
        fails.append('future_only_strict_time_order_required_no_reassimilation')
    if timestamps and any(t > batch.available_until_s for t in timestamps):
        fails.append('observation_after_declared_available_time')
    if batch.assimilation_prefix_snapshot_id != prior.snapshot_id or batch.unassimilated_observation_ids != tuple(o.observation_id for o in batch.observations):
        fails.append('explicit_assimilation_prefix_and_disjoint_observation_ids_required')
    if noise is None:
        unknowns.append('explicit_positive_noise_model_missing')
    elif noise.binding != prior.binding or noise.channels != batch.channels or noise.units != batch.units:
        fails.append('noise_source_model_or_units_binding_mismatch')
    elif not noise.temporally_independent_likelihood_declared:
        unknowns.append('temporal_likelihood_factorization_not_declared')
    if require_train:
        if not prior.parameter_state_names:
            unknowns.append('explicit_parameter_column_mapping_missing')
        if batch.propagated_joint_samples is None or batch.propagated_until_s is None or batch.propagation_evidence is None:
            unknowns.append('actual_future_joint_state_propagation_missing')
        elif timestamps:
            n, d = len(prior.samples), len(prior.state_names)
            samples, evidence = batch.propagated_joint_samples, batch.propagation_evidence
            if len(samples) != n or any(len(row) != d for row in samples):
                fails.append('propagated_joint_sample_dimensions_mismatch')
            else:
                indices = [prior.state_names.index(name) for name in prior.parameter_state_names]
                if any(samples[i][j] != prior.samples[i][j] for i in range(n) for j in indices):
                    fails.append('propagation_altered_original_parameter_samples')
            if batch.propagated_until_s != timestamps[-1] or batch.available_until_s != timestamps[-1]:
                fails.append('propagation_cutoff_must_equal_last_available_training_time')
            if evidence.parent_content_sha256 != prior.content_sha256 or evidence.model_source_sha256 != prior.binding.model_source_sha256:
                fails.append('propagation_parent_or_model_source_binding_mismatch')
            expected = tuple((item.name, item.unit) for item in prior.derived_observables)
            actual = tuple((item.name, item.unit) for item in batch.propagated_derived_observables)
            if actual != expected or any(len(item.particle_values) != n for item in batch.propagated_derived_observables):
                fails.append('propagated_same_joint_derived_readouts_missing_or_mismatch')
    return ('FAIL', tuple(fails + unknowns)) if fails else ('UNKNOWN', tuple(unknowns)) if unknowns else ('PASS', ())


def fit_candidate(prior: FrozenPosterior, batch: TrainingBatch, noise: GaussianNoise | None,
                  *, minimum_samples: int = 3, minimum_span_s: float = 1e-9) -> CalibrationResult:
    """Reweight original parameter particles and explicitly propagated states.

PASS covers supplied conditional Gaussian arithmetic and declarations only.
It is not real-cell parameter validation or a runtime source/solver certificate.
"""
    if not isinstance(prior, FrozenPosterior) or not isinstance(batch, TrainingBatch) or (noise is not None and not isinstance(noise, GaussianNoise)):
        raise TypeError('Strict typed calibration inputs required')
    # Pydantic model_copy/model_construct can bypass validation; public numerical
    # entry points validate the complete values again rather than trusting type.
    prior = FrozenPosterior.model_validate(prior.model_dump(mode='python'))
    batch = TrainingBatch.model_validate(batch.model_dump(mode='python'))
    noise = None if noise is None else GaussianNoise.model_validate(noise.model_dump(mode='python'))
    if type(minimum_samples) is not int or minimum_samples < 3 or not np.isfinite(minimum_span_s) or minimum_span_s <= 0:
        raise ValueError('At least3 samples and a strictly positive time span required')
    status, reasons = _eligibility(prior, batch, noise)
    if status != 'PASS':
        return CalibrationResult(status=status, reasons=reasons)
    n = len(batch.observations)
    span = batch.observations[-1].timestamp_s - batch.observations[0].timestamp_s
    if n < max(minimum_samples, len(batch.channels) + 1) or span < minimum_span_s:
        return CalibrationResult(status='UNKNOWN', reasons=('insufficient_samples_or_time_span_for_residual_calibration',))
    try:
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            observed = np.asarray([o.values for o in batch.observations])
            residual = observed - np.asarray(batch.nominal_predictions)
            mean = residual.mean(axis=0)
            centered = residual - mean
            covariance = centered.T @ centered / (n - 1)
            residual_stats = ResidualStatistics(residuals=tuple(tuple(row) for row in residual),
                mean_bias=tuple(mean), covariance=tuple(tuple(row) for row in covariance),
                std=tuple(np.sqrt(np.diag(covariance))), observed_span_s=span)
            innovations = observed[:, None, :] - np.asarray(batch.particle_predictions) - np.asarray(noise.bias)
            cholesky = np.linalg.cholesky(np.asarray(noise.covariance))
            whitened = np.linalg.solve(cholesky, innovations.reshape(-1, len(batch.channels)).T).T
            score = -.5 * (whitened.reshape(n, len(prior.samples), -1) ** 2).sum(axis=(0, 2))
            positive = np.asarray(prior.weights) > 0
            logweights = np.full(len(prior.samples), -np.inf)
            logweights[positive] = np.log(np.asarray(prior.weights)[positive]) + score[positive]
            weights = np.exp(logweights - np.max(logweights))
            weights /= weights.sum()
            new_weights = tuple(float(w) for w in weights)
            means, quantiles, ess = _summary(batch.propagated_joint_samples, new_weights, batch.propagated_derived_observables)
    except (FloatingPointError, OverflowError, np.linalg.LinAlgError) as error:
        return CalibrationResult(status='UNKNOWN', reasons=('numerical_likelihood_or_residual_failure:' + type(error).__name__,))
    update_hash = content_hash({'parent': prior.content_sha256, 'batch': content_hash(batch), 'noise': content_hash(noise), 'weights': new_weights})
    posterior = FrozenPosterior(snapshot_id='calibrated-' + update_hash[:24], run_id=prior.run_id,
        model_package_id=prior.model_package_id, parameter_revision=prior.parameter_revision,
        obs_until_s=batch.propagated_until_s, binding=prior.binding, source_snapshot_sha256=prior.source_snapshot_sha256,
        state_names=prior.state_names, state_units=prior.state_units, parameter_state_names=prior.parameter_state_names,
        samples=batch.propagated_joint_samples, weights=new_weights, derived_observables=batch.propagated_derived_observables,
        mean=means, quantiles=quantiles, ess=ess, identifiability=prior.identifiability + (
            'conditional_gaussian_likelihood_assumption', 'residual_scatter_not_identified_measurement_noise',
            'finite_joint_particles_not_full_parameter_domain', 'posterior_need_not_narrow',
            'runtime_forward_and_source_freshness_not_verified_here'))
    candidate = CalibrationCandidate(posterior=posterior, parent_content_sha256=prior.content_sha256,
        calibration_input_sha256=content_hash(batch), noise_sha256=content_hash(noise), noise_id=noise.noise_id,
        calibration_revision='calibration-' + update_hash[:24])
    return CalibrationResult(status='PASS', reasons=('conditional_candidate_requires_explicit_new_run_adoption',), residual_statistics=residual_stats, candidate=candidate)


def posterior_to_contract(candidate: CalibrationCandidate) -> PosteriorSnapshot:
    """Return an independent copy; adopting this new posterior is caller work."""
    if not isinstance(candidate, CalibrationCandidate):
        raise TypeError('Typed candidate required')
    candidate = CalibrationCandidate.model_validate(candidate.model_dump(mode='python'))
    p = candidate.posterior
    names = p.state_names + tuple(item.name for item in p.derived_observables)
    return PosteriorSnapshot(snapshot_id=p.snapshot_id, run_id=p.run_id, model_package_id=p.model_package_id,
        parameter_revision=p.parameter_revision, obs_until_s=p.obs_until_s, state_names=list(p.state_names),
        state_units=list(p.state_units), samples=[list(row) for row in p.samples], weights=list(p.weights),
        mean=dict(zip(names, p.mean)), quantiles={name: list(row) for name, row in zip(names, p.quantiles)},
        ess=p.ess, identifiability=list(p.identifiability))
