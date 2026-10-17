"""Local numerical rank and diagnostic value from supplied derivatives only.

This module does not assimilate data or modify a posterior. Local SVD is not
global identifiability, coverage, or a certificate of real-cell observability.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from math import isfinite
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from naheng.domain.contracts import PosteriorSnapshot


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class LocalJacobian(_Schema):
    snapshot_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    model_package_id: str = Field(min_length=1)
    parameter_revision: str = Field(min_length=1)
    obs_until_s: float = Field(ge=0)
    source_ref: str | None = Field(default=None, min_length=1)
    provenance_type: Literal["synthetic", "reference_simulation", "model_linearization"]
    state_names: tuple[str, ...] = Field(min_length=1, max_length=32)
    state_units: tuple[str, ...] = Field(min_length=1, max_length=32)
    evaluation_point: tuple[float, ...] = Field(min_length=1, max_length=32)
    state_scales: tuple[float, ...] = Field(min_length=1, max_length=32)
    observation_names: tuple[str, ...] = Field(default=(), max_length=256)
    observation_units: tuple[str, ...] = Field(default=(), max_length=256)
    observation_noise_std: tuple[float, ...] = Field(default=(), max_length=256)
    # Derivatives in observation-unit / state-unit, before scaling and whitening.
    jacobian: tuple[tuple[float, ...], ...] = Field(default=(), max_length=256)
    important_state_names: tuple[str, ...] | None = None
    jacobian_source: Literal["provided_local_derivatives", "finite_difference"] = "provided_local_derivatives"


class LocalRankPolicy(_Schema):
    policy_id: str = "engineering-local-rank-v1"
    relative_rank_tolerance: float = Field(default=1e-8, ge=0, lt=1)
    absolute_rank_tolerance: float = Field(default=1e-12, gt=0)
    null_projection_tolerance: float = Field(default=1e-8, gt=0)


class DiagnosticOption(_Schema):
    option_id: str = Field(min_length=1)
    kind: Literal["ica", "eis", "other_observation"]
    availability: Literal["available", "unavailable", "unknown"]
    availability_reason: str | None = None
    source_ref: str | None = Field(default=None, min_length=1)
    cost_s: float = Field(ge=0)
    conditions_confirmed: bool | None = None
    state_names: tuple[str, ...] = Field(min_length=1, max_length=32)
    sensitivity_source_ref: str | None = Field(default=None, min_length=1)
    sensitivity_rows: tuple[tuple[float, ...], ...] | None = Field(default=None, max_length=256)
    observation_noise_std: tuple[float, ...] | None = Field(default=None, max_length=256)
    noise_model: Literal["independent_gaussian", "unknown"] = "unknown"


class IdentifiabilityResult(_Schema):
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    reasons: tuple[str, ...]
    snapshot_id: str | None = None
    source_ref: str | None = None
    provenance_type: str | None = None
    rank: int | None = None
    state_dimension: int | None = None
    rank_threshold: float | None = None
    singular_values: tuple[float, ...] = ()
    scaled_whitened_jacobian: tuple[tuple[float, ...], ...] = ()
    nullspace_scaled_coordinates: tuple[tuple[float, ...], ...] = ()
    ambiguous_state_names: tuple[str, ...] = ()
    important_ambiguous_state_names: tuple[str, ...] = ()
    recommendations: tuple[dict, ...] = ()
    excluded_diagnostics: tuple[dict, ...] = ()
    policy: dict = Field(default_factory=dict)
    posterior: dict | None = None
    posterior_sha256: str | None = None
    posterior_updated: Literal[False] = False
    global_identifiability: Literal["UNKNOWN"] = "UNKNOWN"
    scope: str = "Local numerical rank of supplied scaled/noise-whitened derivatives at one posterior mean; no global proof or posterior tightening"
    information_value_scope: str = "Conditional local linear/Gaussian proxy from supplied sensitivities and current weighted samples; not measured information gain or economic value"


def _sha(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def diagnose_identifiability(snapshot: PosteriorSnapshot | dict, linearization: LocalJacobian | dict | None,
                             options: tuple[DiagnosticOption | dict, ...] | list | None = None,
                             budget_s: float = 0.0, policy: LocalRankPolicy | dict | None = None) -> IdentifiabilityResult:
    """Read a distribution, compute local diagnostics, return its unchanged deep copy."""
    try:
        snapshot = PosteriorSnapshot.model_validate(snapshot) if not isinstance(snapshot, PosteriorSnapshot) else snapshot
        posterior = snapshot.model_dump(mode="json")
        posterior_hash = _sha(posterior)
    except (ValidationError, TypeError, ValueError):
        return IdentifiabilityResult(status="FAIL", reasons=("posterior_schema_invalid",))
    common = {"snapshot_id": snapshot.snapshot_id, "posterior": deepcopy(posterior), "posterior_sha256": posterior_hash}
    if not isinstance(budget_s, (int, float)) or isinstance(budget_s, bool) or not isfinite(budget_s) or budget_s < 0:
        return IdentifiabilityResult(status="FAIL", reasons=("diagnostic_budget_invalid",), **common)
    if options is not None and not isinstance(options, (tuple, list)):
        return IdentifiabilityResult(status="FAIL", reasons=("diagnostic_options_schema_invalid",), **common)
    try:
        policy = LocalRankPolicy.model_validate(policy or {}) if not isinstance(policy, LocalRankPolicy) else policy
    except (ValidationError, TypeError, ValueError):
        return IdentifiabilityResult(status="FAIL", reasons=("local_rank_policy_invalid",), **common)
    common["policy"] = policy.model_dump(mode="json")
    if linearization is None:
        return IdentifiabilityResult(status="UNKNOWN", reasons=("local_observation_jacobian_missing",), **common)
    try:
        linearization = LocalJacobian.model_validate(linearization) if not isinstance(linearization, LocalJacobian) else linearization
    except (ValidationError, TypeError, ValueError):
        return IdentifiabilityResult(status="FAIL", reasons=("local_jacobian_schema_invalid",), **common)
    common.update(source_ref=linearization.source_ref, provenance_type=linearization.provenance_type)
    bindings = (linearization.snapshot_id == snapshot.snapshot_id, linearization.run_id == snapshot.run_id,
                linearization.model_package_id == snapshot.model_package_id, linearization.parameter_revision == snapshot.parameter_revision,
                linearization.obs_until_s == snapshot.obs_until_s,
                linearization.state_names == tuple(snapshot.state_names), linearization.state_units == tuple(snapshot.state_units))
    if not all(bindings):
        return IdentifiabilityResult(status="FAIL", reasons=("linearization_snapshot_binding_mismatch",), **common)
    n, m = len(linearization.state_names), len(linearization.observation_names)
    common["state_dimension"] = n
    if len(set(linearization.state_names)) != n or len(set(linearization.observation_names)) != m:
        return IdentifiabilityResult(status="FAIL", reasons=("duplicate_state_or_observation_names",), **common)
    if len(linearization.state_units) != n or len(linearization.evaluation_point) != n or len(linearization.state_scales) != n:
        return IdentifiabilityResult(status="FAIL", reasons=("state_vector_lengths_mismatch",), **common)
    if any(scale <= 0 for scale in linearization.state_scales):
        return IdentifiabilityResult(status="FAIL", reasons=("state_scales_not_positive",), **common)
    if any(name not in snapshot.mean for name in linearization.state_names) or tuple(snapshot.mean[name] for name in linearization.state_names) != linearization.evaluation_point:
        return IdentifiabilityResult(status="FAIL", reasons=("linearization_point_does_not_equal_snapshot_mean",), **common)
    important = linearization.important_state_names if linearization.important_state_names is not None else linearization.state_names
    if not set(important).issubset(linearization.state_names) or len(set(important)) != len(important):
        return IdentifiabilityResult(status="FAIL", reasons=("important_states_not_in_snapshot_definition",), **common)
    if m == 0 or not linearization.jacobian:
        return IdentifiabilityResult(status="UNKNOWN", reasons=("local_observation_jacobian_missing",), **common)
    if len(linearization.jacobian) != m or any(len(row) != n for row in linearization.jacobian) or len(linearization.observation_noise_std) != m or len(linearization.observation_units) != m:
        return IdentifiabilityResult(status="FAIL", reasons=("jacobian_or_noise_dimensions_mismatch",), **common)
    if any(noise <= 0 for noise in linearization.observation_noise_std):
        return IdentifiabilityResult(status="FAIL", reasons=("observation_noise_std_not_positive",), **common)
    if linearization.source_ref is None:
        return IdentifiabilityResult(status="UNKNOWN", reasons=("local_derivative_source_reference_missing",), **common)
    scales = np.asarray(linearization.state_scales)
    noise = np.asarray(linearization.observation_noise_std)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        whitened = np.asarray(linearization.jacobian) * scales / noise[:, None]
    if not np.isfinite(whitened).all():
        return IdentifiabilityResult(status="FAIL", reasons=("scaled_jacobian_overflow",), **common)
    try:
        _, singular, vh = np.linalg.svd(whitened, full_matrices=True)
    except np.linalg.LinAlgError:
        return IdentifiabilityResult(status="UNKNOWN", reasons=("local_SVD_failed",), **common)
    if not np.isfinite(singular).all() or not np.isfinite(vh).all():
        return IdentifiabilityResult(status="UNKNOWN", reasons=("local_SVD_nonfinite",), **common)
    threshold = max(policy.absolute_rank_tolerance, policy.relative_rank_tolerance * float(singular[0]))
    rank = int(np.count_nonzero(singular > threshold))
    nullspace = vh[rank:]
    projections = np.sum(nullspace**2, axis=0)
    ambiguous = tuple(name for name, projection in zip(linearization.state_names, projections) if projection > policy.null_projection_tolerance)
    important_ambiguous = tuple(name for name in ambiguous if name in important)
    candidates, excluded = [], []
    if options is not None and len(options) > 64:
        return IdentifiabilityResult(status="FAIL", reasons=("diagnostic_option_budget_exceeded",), **common)
    seen_ids = set()
    for index, option in enumerate(options or ()):
        try:
            option = DiagnosticOption.model_validate(option) if not isinstance(option, DiagnosticOption) else option
        except (ValidationError, TypeError, ValueError):
            excluded.append({"option_index": index, "reason": "diagnostic_option_schema_invalid"})
            continue
        if option.option_id in seen_ids:
            return IdentifiabilityResult(status="FAIL", reasons=("duplicate_diagnostic_option_ids",), **common)
        seen_ids.add(option.option_id)
        def exclude(reason):
            excluded.append({"option_id": option.option_id, "kind": option.kind, "reason": reason,
                             "availability": option.availability, "availability_reason": option.availability_reason})
        if option.availability != "available":
            exclude("diagnostic_not_declared_available")
            continue
        if option.cost_s > budget_s:
            exclude("diagnostic_exceeds_available_budget_s")
            continue
        if option.conditions_confirmed is not True:
            exclude("diagnostic_conditions_unconfirmed")
            continue
        if option.source_ref is None or option.sensitivity_source_ref is None:
            exclude("diagnostic_source_or_sensitivity_reference_missing")
            continue
        if option.state_names != linearization.state_names:
            exclude("diagnostic_state_definition_mismatch")
            continue
        rows, option_noise = option.sensitivity_rows, option.observation_noise_std
        if not rows or option_noise is None:
            exclude("diagnostic_sensitivity_or_noise_missing")
            continue
        if len(rows) != len(option_noise) or any(len(row) != n for row in rows) or any(value <= 0 for value in option_noise):
            exclude("diagnostic_sensitivity_or_noise_invalid")
            continue
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            proposed = np.asarray(rows) * scales / np.asarray(option_noise)[:, None]
            projected = proposed @ nullspace.T
            null_score = float(np.sum(projected**2))
        if not np.isfinite(proposed).all() or not isfinite(null_score):
            exclude("diagnostic_sensitivity_overflow")
            continue
        try:
            augmented_singular = np.linalg.svd(np.vstack((whitened, proposed)), compute_uv=False)
        except np.linalg.LinAlgError:
            exclude("diagnostic_augmented_SVD_failed")
            continue
        if not np.isfinite(augmented_singular).all():
            exclude("diagnostic_augmented_SVD_nonfinite")
            continue
        # Same absolute threshold for the augmentation comparison, preserving scale.
        augmented_rank = int(np.count_nonzero(augmented_singular > threshold))
        if nullspace.size and null_score <= policy.null_projection_tolerance:
            exclude("diagnostic_has_no_sensitivity_to_current_local_nullspace")
            continue
        information_nats, information_reason = None, "independent_gaussian_noise_not_declared"
        if option.noise_model == "independent_gaussian":
            samples, weights = np.asarray(snapshot.samples), np.asarray(snapshot.weights)
            # Use actual weighted particles, not an invented unit covariance.
            centered = samples - np.average(samples, axis=0, weights=weights)
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                projected_samples = proposed @ ((centered / scales) * np.sqrt(weights)[:, None]).T
                gram = np.eye(len(rows)) + projected_samples @ projected_samples.T
            if np.isfinite(gram).all():
                try:
                    sign, logdet = np.linalg.slogdet(gram)
                except np.linalg.LinAlgError:
                    information_reason = "local_information_logdet_failed"
                else:
                    if sign > 0 and isfinite(logdet) and logdet >= -1e-12:
                        information_nats = max(0.0, 0.5 * float(logdet))
                        information_reason = "conditional_local_linear_Gaussian_proxy_only"
                    else:
                        information_reason = "local_information_logdet_failed"
            else:
                information_reason = "local_information_matrix_overflow"
        candidates.append({"option_id": option.option_id, "kind": option.kind, "cost_s": option.cost_s,
                           "source_ref": option.source_ref, "sensitivity_source_ref": option.sensitivity_source_ref,
                           "local_rank_gain": augmented_rank - rank, "nullspace_sensitivity_score": null_score,
                           "local_information_proxy_nats": information_nats, "information_reason": information_reason,
                           "important_unidentified_states": list(important_ambiguous),
                           "scope": "Declared available option and supplied local sensitivity only; acquisition not executed"})
    candidates.sort(key=lambda row: (-row["local_rank_gain"], -row["nullspace_sensitivity_score"], row["cost_s"], row["option_id"]))
    reasons = ["important_hidden_states_locally_unidentified"] if important_ambiguous else []
    if important_ambiguous and not candidates:
        reasons.append("no_available_diagnostic_with_valid_local_sensitivity_within_budget")
    assert snapshot.model_dump(mode="json") == posterior  # No data assimilation or distribution narrowing.
    return IdentifiabilityResult(status="PASS", reasons=tuple(reasons), rank=rank, rank_threshold=threshold,
                                 singular_values=tuple(map(float, singular)),
                                 scaled_whitened_jacobian=tuple(tuple(map(float, row)) for row in whitened),
                                 nullspace_scaled_coordinates=tuple(tuple(map(float, row)) for row in nullspace),
                                 ambiguous_state_names=ambiguous, important_ambiguous_state_names=important_ambiguous,
                                 recommendations=tuple(candidates), excluded_diagnostics=tuple(excluded), **common)
