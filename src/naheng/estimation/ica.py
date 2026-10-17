"""Quality-gated interval ICA from supplied sensor traces, with SI charge.

Thresholds are declared engineering policy, not calibrated sodium-cell limits.
No resampling, smoothing, synthetic peaks or posterior update is performed.
"""
from __future__ import annotations

from math import isfinite, sqrt
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ICAProtocol(_Schema):
    protocol_id: str = Field(min_length=1)
    mode: Literal["charge", "discharge", "pulse", "dynamic", "unknown"]
    quasi_static: bool | None = None
    nominal_capacity_C: float | None = Field(default=None, gt=0)
    temperature_reference_K: float | None = Field(default=None, gt=0)


class ICATrace(_Schema):
    trace_id: str = Field(min_length=1)
    provenance_type: Literal["synthetic", "public_measurement", "reference_simulation"]
    source_ref: str | None = Field(default=None, min_length=1)
    time_s: tuple[float, ...] = Field(min_length=1, max_length=20000)
    voltage_V: tuple[float, ...] = Field(min_length=1, max_length=20000)
    current_A: tuple[float, ...] = Field(min_length=1, max_length=20000)
    temperature_K: tuple[float, ...] | None = None
    voltage_noise_std_V: float | None = Field(default=None, ge=0)
    protocol: ICAProtocol | None = None


class ICAQualityPolicy(_Schema):
    policy_id: str = "engineering-ica-quality-v1"
    min_samples: int = Field(default=16, ge=3, le=20000)
    min_voltage_span_V: float = Field(default=0.05, gt=0)
    min_voltage_increment_V: float = Field(default=1e-5, gt=0)
    max_voltage_increment_V: float = Field(default=0.01, gt=0)
    max_sample_interval_s: float = Field(default=60.0, gt=0)
    max_relative_current_deviation: float = Field(default=0.05, ge=0, lt=1)
    max_c_rate_per_hour: float = Field(default=0.1, gt=0)
    max_temperature_span_K: float = Field(default=0.5, ge=0)
    max_reference_temperature_deviation_K: float = Field(default=1.0, ge=0)
    max_relative_voltage_difference_noise_std: float = Field(default=0.15, gt=0)


class ICAInterval(_Schema):
    start_s: float
    end_s: float
    midpoint_voltage_V: float
    delta_charge_C: float
    delta_voltage_V: float
    dQ_dV_C_per_V: float
    dQ_dV_Ah_per_V: float


class ICAResult(_Schema):
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    reasons: tuple[str, ...]
    trace_id: str | None = None
    source_ref: str | None = None
    provenance_type: str | None = None
    protocol_id: str | None = None
    protocol_mode: str | None = None
    intervals: tuple[ICAInterval, ...] = ()
    statistics: dict[str, float | int] = Field(default_factory=dict)
    quality_policy: dict = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=lambda: {
        "time": "s", "current": "A", "voltage": "V", "temperature": "K",
        "charge": "C", "dQ_dV": "C/V", "display_dQ_dV": "Ah/V"})
    scope: str = "Interval finite differences under supplied engineering quality conditions; not peaks, capacity certification or calibration"
    charge_sign_convention: str = "Positive mode-transferred charge: charging integral(-I dt), discharging integral(I dt); not signed stored-sodium inventory. dQ/dV retains signed voltage change."
    posterior_updated: Literal[False] = False


def coulombs_from_Ah(value: float) -> float:
    """Explicit nominal-capacity/display conversion; one Ah equals 3600 C."""
    if not isfinite(value) or value <= 0:
        raise ValueError("Nominal capacity must be finite and positive Ah")
    converted = value * 3600.0
    if not isfinite(converted):
        raise ValueError("Nominal capacity conversion overflow")
    return converted


def evaluate_ica(trace: ICATrace | dict, policy: ICAQualityPolicy | dict | None = None) -> ICAResult:
    """Reject invalid vectors; insufficient diagnostic conditions yield no curve."""
    try:
        policy = ICAQualityPolicy.model_validate(policy or {}) if not isinstance(policy, ICAQualityPolicy) else policy
    except (ValidationError, TypeError, ValueError):
        return ICAResult(status="FAIL", reasons=("quality_policy_invalid",))
    if policy.min_voltage_increment_V > policy.max_voltage_increment_V:
        return ICAResult(status="FAIL", reasons=("quality_policy_increment_bounds_inverted",))
    try:
        trace = ICATrace.model_validate(trace) if not isinstance(trace, ICATrace) else trace
    except (ValidationError, TypeError, ValueError):
        return ICAResult(status="FAIL", reasons=("trace_schema_invalid",), quality_policy=policy.model_dump(mode="json"))
    metadata = {"trace_id": trace.trace_id, "source_ref": trace.source_ref,
                "provenance_type": trace.provenance_type, "quality_policy": policy.model_dump(mode="json"),
                "protocol_id": trace.protocol.protocol_id if trace.protocol else None,
                "protocol_mode": trace.protocol.mode if trace.protocol else None}
    n = len(trace.time_s)
    if any(len(vector) != n for vector in (trace.voltage_V, trace.current_A)) or (
            trace.temperature_K is not None and len(trace.temperature_K) != n):
        return ICAResult(status="FAIL", reasons=("vector_lengths_mismatch",), **metadata)
    times, voltages, currents = (np.asarray(vector, dtype=float) for vector in
                                (trace.time_s, trace.voltage_V, trace.current_A))
    with np.errstate(over="ignore", invalid="ignore"):
        dt, dv = np.diff(times), np.diff(voltages)
    if not np.isfinite(dt).all() or not np.isfinite(dv).all():
        return ICAResult(status="FAIL", reasons=("numeric_difference_overflow",), **metadata)
    if len(dt) and np.any(dt <= 0):
        return ICAResult(status="FAIL", reasons=("timestamps_not_strictly_increasing",), **metadata)
    reasons, statistics = [], {"samples": n}
    if trace.source_ref is None:
        reasons.append("source_reference_missing")
    if n < policy.min_samples:
        reasons.append("insufficient_samples")
    protocol = trace.protocol
    if protocol is None:
        reasons.append("diagnostic_protocol_missing")
    elif protocol.mode not in {"charge", "discharge"} or protocol.quasi_static is not True:
        reasons.append("quasi_static_constant_current_protocol_unconfirmed")
    elif (protocol.mode == "charge" and np.any(currents >= 0)) or (protocol.mode == "discharge" and np.any(currents <= 0)):
        reasons.append("current_direction_or_rest_inconsistent_with_protocol")
    if np.any(voltages <= 0):
        reasons.append("nonpositive_voltage_not_supported_by_ICA_protocol")
    if len(dt):
        statistics.update(max_sample_interval_s=float(np.max(dt)),
                          voltage_span_V=float(np.max(voltages) - np.min(voltages)),
                          min_abs_voltage_increment_V=float(np.min(np.abs(dv))),
                          max_abs_voltage_increment_V=float(np.max(np.abs(dv))))
        if float(np.max(dt)) > policy.max_sample_interval_s:
            reasons.append("time_sampling_too_coarse")
        if statistics["voltage_span_V"] < policy.min_voltage_span_V:
            reasons.append("voltage_span_insufficient")
        if float(np.max(np.abs(dv))) > policy.max_voltage_increment_V:
            reasons.append("voltage_sampling_too_coarse")
        if float(np.min(np.abs(dv))) < policy.min_voltage_increment_V:
            reasons.append("voltage_increments_too_small_or_repeated")
        if protocol is not None and protocol.mode in {"charge", "discharge"}:
            direction = 1 if protocol.mode == "charge" else -1
            if np.any(direction * dv <= 0):
                reasons.append("voltage_not_strictly_monotonic_in_protocol_direction")
    median_current = float(np.median(np.abs(currents)))
    if median_current <= 0:
        reasons.append("nonzero_constant_current_unconfirmed")
    else:
        deviation = float(np.max(np.abs(np.abs(currents) - median_current)) / median_current)
        if not isfinite(deviation):
            return ICAResult(status="FAIL", reasons=("current_statistic_overflow",), **metadata)
        statistics["relative_current_deviation"] = deviation
        if deviation > policy.max_relative_current_deviation:
            reasons.append("constant_current_unconfirmed")
        if protocol is None or protocol.nominal_capacity_C is None:
            reasons.append("nominal_capacity_for_rate_missing")
        else:
            rate = median_current / protocol.nominal_capacity_C * 3600.0
            if not isfinite(rate):
                return ICAResult(status="FAIL", reasons=("rate_statistic_overflow",), **metadata)
            statistics["c_rate_per_hour"] = rate
            if rate > policy.max_c_rate_per_hour:
                reasons.append("rate_exceeds_declared_quasi_static_policy")
    if trace.temperature_K is None:
        reasons.append("temperature_measurements_missing")
    elif any(value <= 0 for value in trace.temperature_K):
        return ICAResult(status="FAIL", reasons=("temperature_not_positive_K",), **metadata)
    else:
        temperatures = np.asarray(trace.temperature_K, dtype=float)
        span = float(np.max(temperatures) - np.min(temperatures))
        statistics["temperature_span_K"] = span
        if not isfinite(span):
            return ICAResult(status="FAIL", reasons=("temperature_statistic_overflow",), **metadata)
        if span > policy.max_temperature_span_K:
            reasons.append("temperature_not_stationary")
        if protocol is None or protocol.temperature_reference_K is None:
            reasons.append("protocol_temperature_reference_missing")
        elif np.any(np.abs(temperatures - protocol.temperature_reference_K) > policy.max_reference_temperature_deviation_K):
            reasons.append("temperature_outside_declared_protocol_condition")
    if trace.voltage_noise_std_V is None:
        reasons.append("voltage_noise_level_unknown")
    elif len(dv) and float(np.min(np.abs(dv))) > 0:
        ratio = sqrt(2.0) * trace.voltage_noise_std_V / float(np.min(np.abs(dv)))
        if not isfinite(ratio):
            return ICAResult(status="FAIL", reasons=("noise_statistic_overflow",), **metadata)
        statistics["relative_voltage_difference_noise_std"] = ratio
        if ratio > policy.max_relative_voltage_difference_noise_std:
            reasons.append("voltage_noise_too_large_for_derivative")
    if reasons:
        return ICAResult(status="UNKNOWN", reasons=tuple(dict.fromkeys(reasons)), statistics=statistics, **metadata)
    direction = -1.0 if protocol.mode == "charge" else 1.0
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        charge = direction * (currents[:-1] / 2 + currents[1:] / 2) * dt
        derivative = charge / dv
        midpoint = voltages[:-1] / 2 + voltages[1:] / 2
    if not all(np.isfinite(array).all() for array in (charge, derivative, midpoint)):
        return ICAResult(status="FAIL", reasons=("numerical_derivative_overflow",), **metadata)
    intervals = tuple(ICAInterval(start_s=float(times[i]), end_s=float(times[i + 1]),
                                 midpoint_voltage_V=float(midpoint[i]), delta_charge_C=float(charge[i]),
                                 delta_voltage_V=float(dv[i]), dQ_dV_C_per_V=float(derivative[i]),
                                 dQ_dV_Ah_per_V=float(derivative[i] / 3600.0)) for i in range(n - 1))
    total_charge = float(np.sum(charge))
    if not isfinite(total_charge):
        return ICAResult(status="FAIL", reasons=("total_transferred_charge_overflow",), **metadata)
    statistics["total_transferred_charge_C"] = total_charge
    return ICAResult(status="PASS", reasons=(), intervals=intervals, statistics=statistics, **metadata)
