"""Explicit finite-support joint Gaussian observation updates.

The caller must verify the calibration packet, registered physical model, and
source files before adoption and use an owned worker with a hard 120 s process
tree budget. Checks around solvers are soft, not an interrupt inside solve_ivp.
This bounded slice permits at most 256 represented rows and a 3600 s future step.
It does not certify an operating distribution or infer pure sensor noise.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import math
import time

import numpy as np

from naheng.domain.contracts import Observation, PosteriorSnapshot
from naheng.estimation.calibration import GaussianNoise, content_hash
from naheng.estimation.diagnostics import effective_sample_size, weighted_quantiles
from naheng.estimation.particle_filter import particle_model, rekey_snapshot
from naheng.models.site_model import SiteModel
from naheng.packages.registry import content_hash as parameter_content_hash


class JointObserverUnknown(RuntimeError):
    """Propagation or numerical support cannot justify an observation update."""


def _finite(value, name, *, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (float, int, np.floating, np.integer)) or not math.isfinite(value):
        raise ValueError(name + ' must be finite')
    value = float(value)
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(name + ' outside declared bounds')
    return value


def _summaries(rows, weights, model):
    names = [*model.state_names, 'rate_scale', 'side_rate_scale']
    mean = dict(zip(names, np.average(rows, axis=0, weights=weights).tolist()))
    quantiles = {name: weighted_quantiles(rows[:, i], weights) for i, name in enumerate(names)}
    capacities = np.asarray(model.params.site_capacity_mol)
    soc = rows[:, :2] @ capacities / capacities.sum()
    mean['soc'] = float(weights @ soc)
    quantiles['soc'] = weighted_quantiles(soc, weights)
    return mean, quantiles, effective_sample_size(weights)


class JointGaussianObserver:
    """No resampling or invented process noise; represented rows remain joint."""

    def __init__(self, snapshot: PosteriorSnapshot, model: SiteModel, noise: GaussianNoise,
                 *, run_id: str | None = None, wall_budget_s: float = 100):
        if not isinstance(snapshot, PosteriorSnapshot) or not isinstance(noise, GaussianNoise):
            raise TypeError('Typed PosteriorSnapshot and GaussianNoise required')
        if type(model) is not SiteModel:
            raise TypeError('Actual builtin SiteModel required')
        budget = _finite(wall_budget_s, 'wall_budget_s', low=0, high=100)
        if budget == 0:
            raise ValueError('Positive observer budget required')
        saved = PosteriorSnapshot.model_validate(deepcopy(snapshot.model_dump(mode='python')))
        likelihood = GaussianNoise.model_validate(noise.model_dump(mode='python'))
        if likelihood.channels != ('voltage_V', 'temperature_K') or likelihood.units != ('V', 'K'):
            raise ValueError('Noise must describe ordered voltage_V,temperature_K in V,K')
        binding = likelihood.binding
        if (binding.model_package_id != saved.model_package_id
                or binding.parameter_revision != saved.parameter_revision
                or binding.chemistry_id != 'synthetic_two_site'
                or binding.provenance_type != 'synthetic'
                or binding.chemistry_identity_status != 'declared_compatible'
                or binding.source_identity_status != 'declared_compatible'):
            raise ValueError('Noise and posterior model/parameter/chemistry binding mismatch')
        if not likelihood.temporally_independent_likelihood_declared:
            raise ValueError('Future likelihood temporal factorization must be explicitly declared')
        self._model = SiteModel(model.params)
        self._model_sha = parameter_content_hash(asdict(self._model.params))
        if binding.parameter_sha256 != self._model_sha:
            raise ValueError('Noise actual physical parameter hash mismatch')
        names = [*model.state_names, 'rate_scale', 'side_rate_scale']
        units = [*model.state_units, '1', '1']
        if saved.state_names != names or saved.state_units != units:
            raise ValueError('Joint physical state/parameter column identity mismatch')
        rows, weights = np.asarray(saved.samples, dtype=float), np.asarray(saved.weights, dtype=float)
        if len(rows) > 256:
            raise ValueError('This bounded observer supports at most 256 represented rows')
        if (not np.isfinite(rows).all() or not np.isfinite(weights).all()
                or np.any(rows[:, -2:] <= 0) or np.any(weights < 0)
                or abs(float(weights.sum()) - 1) > 1e-12):
            raise ValueError('Finite joint rows, positive rate scales and normalized weights required')
        self._validate_rows(rows)
        covariance = np.asarray(likelihood.covariance, dtype=float)
        if not np.array_equal(covariance, covariance.T):
            raise ValueError('Full covariance must be exactly symmetric')
        self._cholesky = np.linalg.cholesky(covariance)
        self._bias = np.asarray(likelihood.bias, dtype=float)
        self._noise = likelihood
        self._noise_sha = content_hash(likelihood)
        self._source_snapshot_sha = content_hash(saved)
        if run_id is not None:
            if not isinstance(run_id, str) or not run_id.strip():
                raise ValueError('Explicit nonempty RunID required')
            saved = PosteriorSnapshot.model_validate(rekey_snapshot(saved.model_dump(mode='json'), run_id))
        self._snapshot = saved.model_copy(deep=True)
        self._budget_s = budget
        self._diagnostics = []
        self._adoption = {
            'source_snapshot_sha256': self._source_snapshot_sha,
            'adopted_snapshot_sha256': content_hash(saved),
            'model_parameter_sha256': self._model_sha, 'noise_sha256': self._noise_sha,
            'noise_source_sha256': likelihood.source_sha256,
            'calibration_binding': binding.model_dump(mode='json'),
            'explicit_run_rekey': run_id is not None,
            'samples_weights_time_preserved': True, 'resampling_performed': False,
            'source_verification_required_from_caller': True,
            'operating_risk_certificate': False,
            'scope': 'Explicit builtin synthetic conditional finite-support observer; no source-file verifier or saved Run migration',
        }

    def _validate_rows(self, rows):
        for row in rows:
            self._model._validate_state(row[:5])
            if not self._model.params.temperature_min_K <= row[4] <= self._model.params.temperature_max_K:
                raise ValueError('Represented physical temperature outside model domain')

    @property
    def snapshot(self):
        return self._snapshot.model_copy(deep=True)

    @property
    def update_diagnostics(self):
        return deepcopy(self._diagnostics)

    @property
    def adoption_record(self):
        return deepcopy(self._adoption)

    def update(self, observation: Observation, duration_s=None, *, ambient_K=298.15, thermal_W=0):
        """Commit one new actual observation only after all represented forwards."""
        started = time.monotonic()
        def check_budget():
            if time.monotonic() - started >= self._budget_s:
                raise JointObserverUnknown('observer_wall_budget_exhausted')
        check_budget()
        if not isinstance(observation, Observation):
            raise TypeError('Actual typed Observation required')
        for name in ('timestamp_s', 'current_A', 'voltage_V', 'temperature_K'):
            _finite(getattr(observation, name), 'observation.' + name)
        sensor = Observation.model_validate(deepcopy(observation.model_dump(mode='python')))
        old = self._snapshot
        if sensor.run_id != old.run_id:
            raise ValueError('Observation RunID mismatch')
        elapsed = sensor.timestamp_s - old.obs_until_s
        if elapsed <= 0:
            raise ValueError('Observation timestamps must strictly increase')
        duration = elapsed if duration_s is None else _finite(duration_s, 'duration_s', low=0)
        if elapsed > 3600 or duration > 3600:
            raise ValueError('This bounded observer supports at most a 3600 s future interval')
        if duration <= 0 or not math.isclose(duration, elapsed, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError('Executed duration must equal observation time advance')
        ambient = _finite(ambient_K, 'ambient_K', low=self._model.params.temperature_min_K,
                          high=self._model.params.temperature_max_K)
        thermal = _finite(thermal_W, 'thermal_W', low=-100, high=100)
        # Noisy sensor values are not true physical states. Finite readings can
        # lie outside the model state/readout domain under this Gaussian policy.
        outside_sensor_channels = []
        if not self._model.params.voltage_min_V <= sensor.voltage_V <= self._model.params.voltage_max_V:
            outside_sensor_channels.append('voltage_V')
        if not self._model.params.temperature_min_K <= sensor.temperature_K <= self._model.params.temperature_max_K:
            outside_sensor_channels.append('temperature_K')
        rows = np.asarray(old.samples, dtype=float)
        prior_weights = np.asarray(old.weights, dtype=float)
        predicted_rows = rows.copy()
        predictions, forwards = [], []
        for index, row in enumerate(rows):
            check_budget()
            sampled_model = particle_model(self._model, float(row[-2]), float(row[-1]))
            result = sampled_model.integrate(row[:5], sensor.current_A, duration,
                                             ambient_K=ambient, thermal_W=thermal)
            check_budget()
            if not math.isclose(result.elapsed_s, elapsed, rel_tol=1e-10, abs_tol=1e-8):
                raise JointObserverUnknown('represented_particle_early_stop:' + str(index))
            if result.events:
                raise JointObserverUnknown('represented_particle_terminal_event:' + str(index))
            sampled_model._validate_state(result.state)
            reading = sampled_model.observe(result.state, sensor.current_A)
            predicted_rows[index, :5] = result.state
            predictions.append([reading['voltage_V'], float(result.state[4])])
            forwards.append({'parent_index': index, 'elapsed_s': result.elapsed_s,
                'solver': result.solver, 'events': deepcopy(result.events),
                'inventory_residual_mol': result.inventory_residual_mol,
                'energy_J': result.energy_J,
                'thermal_management_energy_J': result.thermal_management_energy_J,
                'parameter_scales': row[-2:].tolist(),
                'sampled_model_parameter_sha256': parameter_content_hash(asdict(sampled_model.params))})
        self._validate_rows(predicted_rows)
        observed = np.asarray([sensor.voltage_V, sensor.temperature_K])
        innovations = observed - np.asarray(predictions) - self._bias
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            try:
                whitened = np.linalg.solve(self._cholesky, innovations.T).T
                mahalanobis = np.sum(whitened * whitened, axis=1)
                if not np.isfinite(mahalanobis).all():
                    raise JointObserverUnknown('nonfinite_joint_likelihood')
                scores = -0.5 * mahalanobis
                supported = prior_weights > 0
                log_weights = np.full(len(rows), -np.inf)
                log_weights[supported] = np.log(prior_weights[supported]) + scores[supported]
                if not np.isfinite(log_weights[supported]).all():
                    raise JointObserverUnknown('degenerate_joint_likelihood_support')
                weights = np.zeros(len(rows))
                weights[supported] = np.exp(log_weights[supported] - np.max(log_weights[supported]))
                total = float(weights.sum())
                if total <= 0 or not math.isfinite(total):
                    raise JointObserverUnknown('degenerate_joint_likelihood_support')
                weights /= total
            except (FloatingPointError, np.linalg.LinAlgError) as error:
                raise JointObserverUnknown('numerical_joint_likelihood_failure') from error
        mean, quantiles, ess = _summaries(predicted_rows, weights, self._model)
        flags = [*old.identifiability, 'conditional_joint_gaussian_assumption',
                 'finite_support_no_process_noise_or_resampling', 'operating_coverage_unverified']
        if ess < len(rows) / 2:
            flags.append('low_ess_finite_support')
        if outside_sensor_channels:
            flags.append('sensor_outside_physical_domain_not_a_state_observation')
        identity = {'parent_snapshot_sha256': content_hash(old),
            'source_snapshot_sha256': self._source_snapshot_sha,
            'model_parameter_sha256': self._model_sha, 'noise_sha256': self._noise_sha,
            'observation_sha256': content_hash(sensor), 'duration_s': duration,
            'ambient_K': ambient, 'thermal_W': thermal,
            'run_id': old.run_id, 'obs_until_s': sensor.timestamp_s,
            'samples': predicted_rows.tolist(), 'weights': weights.tolist(),
            'model_package_id': old.model_package_id, 'parameter_revision': old.parameter_revision}
        updated = PosteriorSnapshot(snapshot_id='joint-observer-' + content_hash(identity),
            run_id=old.run_id, model_package_id=old.model_package_id,
            parameter_revision=old.parameter_revision, obs_until_s=sensor.timestamp_s,
            state_names=list(old.state_names), state_units=list(old.state_units),
            samples=predicted_rows.tolist(), weights=weights.tolist(), mean=mean,
            quantiles=quantiles, ess=ess, identifiability=list(dict.fromkeys(flags)))
        diagnostic = {**identity, 'snapshot_id': updated.snapshot_id,
            'snapshot_sha256': content_hash(updated), 'prior_weights': prior_weights.tolist(),
            'predictions': predictions, 'innovations': innovations.tolist(),
            'whitened_innovations': whitened.tolist(), 'mahalanobis_sq': mahalanobis.tolist(),
            'log_likelihood_up_to_shared_normalizer': scores.tolist(),
            'posterior_weights': weights.tolist(), 'ess': ess, 'forward_results': forwards,
            'represented_forward_solves': len(rows), 'resampling_performed': False,
            'original_parameter_columns_preserved': bool(np.array_equal(predicted_rows[:, -2:], rows[:, -2:])),
            'noise_covariance': self._noise.covariance, 'noise_bias': self._noise.bias,
            'likelihood_scope': self._noise.component_scope,
            'sensor_reading_outside_physical_domain': outside_sensor_channels,
            'sensor_values_overwrote_physical_state': False,
            'temporal_factorization_declared': self._noise.temporally_independent_likelihood_declared,
            'risk_certificate': False, 'independent_operational_trajectories': 0,
            'wall_budget_s': self._budget_s, 'walltime_s': time.monotonic() - started}
        # Recheck finite JSON publication before either state/diagnostics commit.
        content_hash(diagnostic)
        check_budget()
        self._snapshot = updated
        self._diagnostics = [*self._diagnostics, diagnostic]
        return updated.model_copy(deep=True)
