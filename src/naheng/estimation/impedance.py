"""Provided impedance observations only; scalar ACR is not an EIS spectrum."""
from __future__ import annotations

from math import atan2, hypot, isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ImpedanceInput(_Schema):
    record_id: str = Field(min_length=1)
    provenance_type: Literal["synthetic", "public_measurement", "reference_simulation"]
    source_ref: str | None = Field(default=None, min_length=1)
    kind: Literal["eis", "scalar_ac_resistance", "unavailable"]
    frequency_Hz: tuple[float, ...] | None = None
    real_Ohm: tuple[float, ...] | None = None
    imaginary_Ohm: tuple[float, ...] | None = None
    imaginary_convention: Literal["imaginary", "negative_imaginary"] | None = None
    scalar_ac_resistance_Ohm: float | None = Field(default=None, ge=0)
    protocol_id: str | None = Field(default=None, min_length=1)
    temperature_K: float | None = Field(default=None, gt=0)
    excitation_amplitude_V: float | None = Field(default=None, gt=0)
    small_signal_verified: bool | None = None
    stationary_verified: bool | None = None


class ImpedancePoint(_Schema):
    frequency_Hz: float
    real_Ohm: float
    imaginary_Ohm: float
    magnitude_Ohm: float
    phase_rad: float | None
    phase_status: Literal["PASS", "UNKNOWN"]
    phase_reason: str | None = None


class ImpedanceResult(_Schema):
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    reasons: tuple[str, ...]
    record_id: str | None = None
    source_ref: str | None = None
    provenance_type: str | None = None
    spectrum: tuple[ImpedancePoint, ...] = ()
    scalar_ac_resistance_Ohm: float | None = None
    frequency_coverage_Hz: tuple[float, float] | None = None
    scope: str = "Provided frequency-resolved data and declared acquisition conditions only; no circuit fit, causality proof or state calibration"
    posterior_updated: Literal[False] = False


def evaluate_impedance(record: ImpedanceInput | dict | None) -> ImpedanceResult:
    if record is None:
        return ImpedanceResult(status="UNKNOWN", reasons=("impedance_data_not_provided",))
    try:
        record = ImpedanceInput.model_validate(record) if not isinstance(record, ImpedanceInput) else record
    except (ValidationError, TypeError, ValueError):
        return ImpedanceResult(status="FAIL", reasons=("impedance_schema_invalid",))
    metadata = {"record_id": record.record_id, "source_ref": record.source_ref,
                "provenance_type": record.provenance_type}
    if record.kind == "unavailable":
        return ImpedanceResult(status="UNKNOWN", reasons=("impedance_data_not_provided",), **metadata)
    if record.kind == "scalar_ac_resistance":
        if record.scalar_ac_resistance_Ohm is None:
            return ImpedanceResult(status="UNKNOWN", reasons=("scalar_ac_resistance_value_missing",), **metadata)
        if any(value is not None for value in (record.real_Ohm, record.imaginary_Ohm)):
            return ImpedanceResult(status="FAIL", reasons=("scalar_record_contains_conflicting_spectrum",), **metadata)
        return ImpedanceResult(status="UNKNOWN", reasons=("scalar_ac_resistance_is_not_frequency_resolved_EIS",),
                               scalar_ac_resistance_Ohm=record.scalar_ac_resistance_Ohm, **metadata)
    if record.scalar_ac_resistance_Ohm is not None:
        return ImpedanceResult(status="FAIL", reasons=("spectrum_contains_conflicting_scalar_record",), **metadata)
    reasons = []
    if record.frequency_Hz is None or record.real_Ohm is None or record.imaginary_Ohm is None:
        return ImpedanceResult(status="UNKNOWN", reasons=("frequency_resolved_complex_impedance_missing",), **metadata)
    n = len(record.frequency_Hz)
    if len(record.real_Ohm) != n or len(record.imaginary_Ohm) != n:
        return ImpedanceResult(status="FAIL", reasons=("impedance_vector_lengths_mismatch",), **metadata)
    if n > 20000:
        return ImpedanceResult(status="FAIL", reasons=("impedance_sample_budget_exceeded",), **metadata)
    if n < 3:
        reasons.append("insufficient_distinct_frequencies_for_spectrum")
    if any(frequency <= 0 for frequency in record.frequency_Hz):
        return ImpedanceResult(status="FAIL", reasons=("frequency_not_positive_Hz",), **metadata)
    if len(set(record.frequency_Hz)) != n:
        return ImpedanceResult(status="FAIL", reasons=("duplicate_frequencies_require_explicit_repeat_protocol",), **metadata)
    if record.source_ref is None:
        reasons.append("source_reference_missing")
    if record.protocol_id is None:
        reasons.append("impedance_protocol_missing")
    if record.temperature_K is None:
        reasons.append("impedance_temperature_unknown")
    if record.imaginary_convention is None:
        reasons.append("imaginary_sign_convention_unknown")
    if record.small_signal_verified is not True or record.excitation_amplitude_V is None:
        reasons.append("small_signal_condition_unconfirmed")
    if record.stationary_verified is not True:
        reasons.append("stationarity_unconfirmed")
    if reasons:
        return ImpedanceResult(status="UNKNOWN", reasons=tuple(reasons), **metadata)
    sign = 1.0 if record.imaginary_convention == "imaginary" else -1.0
    points = []
    for frequency, real, imaginary in zip(record.frequency_Hz, record.real_Ohm, record.imaginary_Ohm):
        canonical_imaginary = sign * imaginary
        magnitude = hypot(real, canonical_imaginary)
        if not isfinite(magnitude):
            return ImpedanceResult(status="FAIL", reasons=("impedance_magnitude_overflow",), **metadata)
        points.append(ImpedancePoint(frequency_Hz=frequency, real_Ohm=real,
                                     imaginary_Ohm=canonical_imaginary, magnitude_Ohm=magnitude,
                                     phase_rad=atan2(canonical_imaginary, real) if magnitude > 0 else None,
                                     phase_status="PASS" if magnitude > 0 else "UNKNOWN",
                                     phase_reason=None if magnitude > 0 else "zero_complex_impedance_phase_undefined"))
    return ImpedanceResult(status="PASS", reasons=(), spectrum=tuple(points),
                           frequency_coverage_Hz=(min(record.frequency_Hz), max(record.frequency_Hz)), **metadata)
