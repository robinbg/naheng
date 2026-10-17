"""Observable discrepancy diagnostics; thresholds are not incident probabilities."""
from __future__ import annotations

import numpy as np
from pydantic import Field
from typing import Literal

from .calibration import Frozen, FrozenPosterior, TrainingBatch, GaussianNoise, Vector, Name, SHA256, _eligibility, content_hash


class InnovationRecord(Frozen):
    observation_id: Name
    timestamp_s: float = Field(ge=0)
    residual: Vector
    standardized_innovation: Vector
    whitened_innovation: Vector
    mahalanobis_sq: float = Field(ge=0)
    joint_exceeded: bool
    rolling_bias: Vector
    rolling_standardized_bias: Vector
    window_count: int = Field(ge=1)
    status: Literal['out_of_bounds', 'UNKNOWN_insufficient_history', 'within_declared_bounds']
    exceeded_channels: tuple[str, ...]


class DiscrepancyResult(Frozen):
    status: Literal['PASS', 'FAIL', 'UNKNOWN', 'out_of_bounds', 'within_declared_bounds']
    reasons: tuple[str, ...]
    observations: tuple[InnovationRecord, ...] = ()
    input_sha256: SHA256
    noise_sha256: SHA256
    joint_innovation_limit: float = Field(gt=0)
    joint_threshold_scope: Literal['declared_empirical_whitened_norm_not_probability'] = 'declared_empirical_whitened_norm_not_probability'
    joint_exceedance_count: int = Field(default=0, ge=0)
    empirical_scope: str = 'Supplied nominal predictions, explicit conditional residual/noise assumption and overlapping-window bias diagnostics'
    incident_probability: None = None
    operating_risk_certificate: Literal[False] = False


def monitor_discrepancy(prior: FrozenPosterior, batch: TrainingBatch, noise: GaussianNoise, *,
                        window: int = 5, minimum_history: int = 3,
                        innovation_limit: float = 3.0, bias_limit: float = 2.0,
                        joint_innovation_limit: float = 3.0) -> DiscrepancyResult:
    """Monitor without fitting, including declared heldout/stress observations.

Rolling biases are normalized by residual scale, not divided by sqrt(window):
correlated/overlapping samples do not supply independent operational evidence.
"""
    if not isinstance(prior, FrozenPosterior) or not isinstance(batch, TrainingBatch) or not isinstance(noise, GaussianNoise):
        raise TypeError('Typed posterior, batch and noise required')
    prior = FrozenPosterior.model_validate(prior.model_dump(mode='python'))
    batch = TrainingBatch.model_validate(batch.model_dump(mode='python'))
    noise = GaussianNoise.model_validate(noise.model_dump(mode='python'))
    if type(window) is not int or type(minimum_history) is not int or not 1 <= minimum_history <= window:
        raise ValueError('Valid integer window/history required')
    if not all(np.isfinite(v) and v > 0 for v in (innovation_limit, bias_limit, joint_innovation_limit)):
        raise ValueError('Finite positive empirical thresholds required')
    status, reasons = _eligibility(prior, batch, noise, require_train=False)
    base = {'input_sha256': content_hash(batch), 'noise_sha256': content_hash(noise),
            'joint_innovation_limit': float(joint_innovation_limit)}
    if status != 'PASS':
        return DiscrepancyResult(status=status, reasons=reasons, **base)
    try:
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            residual = np.asarray([o.values for o in batch.observations]) - np.asarray(batch.nominal_predictions)
            centered = residual - np.asarray(noise.bias)
            scales = np.sqrt(np.diag(noise.covariance))
            standardized = centered / scales
            whitened = np.linalg.solve(np.linalg.cholesky(np.asarray(noise.covariance)), centered.T).T
            mahalanobis_sq = (whitened * whitened).sum(axis=1)
            records = []
            for index, observation in enumerate(batch.observations):
                start = max(0, index + 1 - window)
                bias = residual[start:index + 1].mean(axis=0)
                normalized_bias = (bias - np.asarray(noise.bias)) / scales
                history = index + 1 - start
                excess = (np.abs(standardized[index]) > innovation_limit)
                if history >= minimum_history:
                    excess |= np.abs(normalized_bias) > bias_limit
                names = tuple(name for name, exceeded in zip(batch.channels, excess) if exceeded)
                joint_exceeded = bool(np.sqrt(mahalanobis_sq[index]) > joint_innovation_limit)
                label = 'out_of_bounds' if names or joint_exceeded else 'UNKNOWN_insufficient_history' if history < minimum_history else 'within_declared_bounds'
                records.append(InnovationRecord(observation_id=observation.observation_id, timestamp_s=observation.timestamp_s,
                    residual=tuple(residual[index]), standardized_innovation=tuple(standardized[index]),
                    whitened_innovation=tuple(whitened[index]), mahalanobis_sq=float(mahalanobis_sq[index]),
                    joint_exceeded=joint_exceeded, rolling_bias=tuple(bias),
                    rolling_standardized_bias=tuple(normalized_bias), window_count=history, status=label,
                    exceeded_channels=names))
    except (FloatingPointError, OverflowError, np.linalg.LinAlgError) as error:
        return DiscrepancyResult(status='UNKNOWN', reasons=('numerical_innovation_failure:' + type(error).__name__,), **base)
    reasons = ('threshold_flags_are_empirical_discrepancy_not_incident_probability',
               'operating_distribution_calibration_not_verified_here', 'overlapping_windows_not_independent_trajectories',
               'joint_whitened_norm_threshold_is_declared_policy_not_p_value',
               'whitened_components_are_mixed_coordinates_not_physical_channel_attribution')
    status = 'out_of_bounds' if any(r.exceeded_channels or r.joint_exceeded for r in records) else 'UNKNOWN' if len(records) < minimum_history else 'within_declared_bounds'
    return DiscrepancyResult(status=status, reasons=reasons, observations=tuple(records),
        joint_exceedance_count=sum(r.joint_exceeded for r in records), **base)
