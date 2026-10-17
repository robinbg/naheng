"""Explicitly fork an observer from a verified calibration, without old-run writes."""
from __future__ import annotations

from copy import deepcopy
import numpy as np

from naheng.estimation.calibration_session import TrainingSource
from naheng.estimation.particle_filter import ParticleFilter
from .calibration_consumer import _packet
from naheng.estimation.calibration import content_hash


def fork_calibrated_observer(root, calibration_dir):
    """Return a new estimator and adoption record for future actual sensors.

    This builtin filter supports the original declared diagonal, zero-bias
    sensor likelihood. Other likelihoods require a corresponding observer.
    It does not relabel timestamps or count a prediction as an observation.
    The caller must run this verification inside its bounded owned worker.
    """
    from pathlib import Path
    root = Path(root).resolve()
    loaded = _packet(root, calibration_dir)
    request, candidate, model = (loaded[k] for k in ('request', 'candidate', 'model'))
    source_path = root / request.training_source.path
    source = TrainingSource.model_validate_json(source_path.read_bytes())
    expected_cov = np.diag([source.voltage_noise_V**2, source.temperature_noise_K**2])
    if (not np.array_equal(np.asarray(request.noise.covariance), expected_cov)
            or request.noise.bias != (0., 0.)):
        raise ValueError('This observer cannot adopt a different covariance or bias likelihood')
    original = ParticleFilter(request.prior.run_id, model, seed=source.filter_seed,
                              particles=len(request.prior.samples), voltage_noise_V=source.voltage_noise_V,
                              temperature_noise_K=source.temperature_noise_K)
    original.update(source.initial_observation)
    prefix = original.export_checkpoint()
    adopted = deepcopy(prefix)
    snapshot = loaded['snapshot']
    adopted.update(samples=deepcopy(snapshot.samples), weights=list(snapshot.weights),
                   last_timestamp=snapshot.obs_until_s, last_snapshot=snapshot.model_dump(mode='json'))
    adopted['update_diagnostics'].append({'kind': 'batch_calibration_adoption',
        'timestamp_s': snapshot.obs_until_s, 'source_snapshot_id': snapshot.snapshot_id,
        'training_observation_ids': list(request.batch.unassimilated_observation_ids),
        'sequential_PF_updates_claimed': False, 'random_resampling_performed': False})
    # Preserve the real prefix RNG state: batch calibration performs no random
    # resampling. from_checkpoint validates the physical model and revision.
    observer = ParticleFilter.from_checkpoint(run_id=snapshot.run_id, model=model, payload=adopted)
    assert original.export_checkpoint() == prefix
    record = {'source_calibration_dir': str(loaded['packet']), 'code_hash': loaded['implementation_sha'],
              'source_candidate_sha256': candidate.content_sha256,
              'source_snapshot_id': snapshot.snapshot_id, 'observer_snapshot_id': observer.snapshot.snapshot_id,
              'source_snapshot_content_sha256': content_hash(snapshot),
              'observer_snapshot_content_sha256': content_hash(observer.snapshot),
              'source_prefix_rng_sha256': content_hash(prefix['rng_state']),
              'observer_rng_sha256': content_hash(observer.export_checkpoint()['rng_state']),
              'assimilation_scope': 'Actual time-zero PF plus verified batch calibration through source observations; not sequential PF updates at every training time',
              'source_obs_until_s': snapshot.obs_until_s, 'observer_obs_until_s': observer.snapshot.obs_until_s,
              'samples_and_weights_preserved': observer.export_checkpoint()['samples'] == snapshot.samples
                  and observer.export_checkpoint()['weights'] == snapshot.weights,
              'physical_parameter_revision': snapshot.parameter_revision,
              'future_sensor_assimilated': False, 'existing_filter_or_run_modified': False,
              'likelihood_scope': request.noise.component_scope,
              'scope': 'Explicit new builtin synthetic observer; not real-cell calibration or saved Run migration'}
    return observer, record
