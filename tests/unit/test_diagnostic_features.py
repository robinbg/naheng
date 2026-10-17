"""Synthetic mathematical and bad-input checks, not real ICA/EIS measurements.

For public integration, replace only these three local imports with their
canonical naheng.estimation module paths, then rerun this exact test body.
"""
from copy import deepcopy
import hashlib
import json
from math import atan2, log, sqrt
from pathlib import Path

import numpy as np
import pytest

from naheng.estimation import ica
from naheng.estimation import impedance
from naheng.estimation import identifiability
from naheng.domain.contracts import PosteriorSnapshot


def charge_trace(mode="charge"):
    sign = 1 if mode == "charge" else -1
    return {"trace_id": "synthetic-math-ica", "provenance_type": "synthetic",
            "source_ref": "synthetic:linear-voltage-constant-current-fixture",
            "time_s": [10.0 * i for i in range(31)],
            "voltage_V": [3.0 + sign * 0.002 * i for i in range(31)],
            "current_A": [-sign * 0.1] * 31, "temperature_K": [298.15] * 31,
            "voltage_noise_std_V": 1e-5,
            "protocol": {"protocol_id": "synthetic-quasi-static-math", "mode": mode,
                         "quasi_static": True, "nominal_capacity_C": 11520.0,
                         "temperature_reference_K": 298.15}}


def eis_record():
    return {"record_id": "synthetic-math-eis", "provenance_type": "synthetic",
            "source_ref": "synthetic:provided-three-frequency-vectors", "kind": "eis",
            "frequency_Hz": [10.0, 100.0, 1000.0], "real_Ohm": [3.0, 1.0, 0.2],
            "imaginary_Ohm": [4.0, 1.0, 0.02], "imaginary_convention": "negative_imaginary",
            "protocol_id": "synthetic-small-signal", "temperature_K": 298.15,
            "excitation_amplitude_V": 0.005, "small_signal_verified": True, "stationary_verified": True}


def posterior():
    return PosteriorSnapshot(snapshot_id="snapshot-synthetic-local", run_id="run-synthetic-local",
                             model_package_id="synthetic-local-linear", parameter_revision="math-fixture-v1",
                             obs_until_s=30.0, state_names=["site_1", "site_2"], state_units=["1", "1"],
                             samples=[[0.2, 0.8], [0.8, 0.2]], weights=[0.5, 0.5],
                             mean={"site_1": 0.5, "site_2": 0.5},
                             quantiles={"site_1": [0.2, 0.5, 0.8], "site_2": [0.2, 0.5, 0.8]},
                             ess=2.0, identifiability=["distribution_retained"])


def local_jacobian():
    snap = posterior()
    return {"snapshot_id": snap.snapshot_id, "run_id": snap.run_id,
            "model_package_id": snap.model_package_id, "parameter_revision": snap.parameter_revision,
            "obs_until_s": snap.obs_until_s, "source_ref": "synthetic:actual-linear-readout-y=x1+x2",
            "provenance_type": "synthetic", "state_names": snap.state_names, "state_units": snap.state_units,
            "evaluation_point": [0.5, 0.5], "state_scales": [1.0, 1.0],
            "observation_names": ["sum_readout"], "observation_units": ["1"],
            "observation_noise_std": [1.0], "jacobian": [[1.0, 1.0]],
            "important_state_names": ["site_2"]}


def option():
    return {"option_id": "declared-synthetic-difference-readout", "kind": "other_observation",
            "availability": "available", "source_ref": "synthetic:declared-available-diagnostic",
            "cost_s": 8.0, "conditions_confirmed": True, "state_names": ["site_1", "site_2"],
            "sensitivity_source_ref": "synthetic:actual-linear-readout-y=x1-x2",
            "sensitivity_rows": [[1.0, -1.0]], "observation_noise_std": [1.0],
            "noise_model": "independent_gaussian"}


def test_source_identity_and_synthetic_scope():
    paths = [Path(module.__file__) for module in (ica, impedance, identifiability)] + [Path(__file__)]
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    print(json.dumps({"scope": "Synthetic math/unit evidence; no real diagnostic rows, fits or role changes",
                      "source_sha256": before}, sort_keys=True))
    assert len(before) == 4
    assert before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


@pytest.mark.parametrize("mode,expected_derivative", [("charge", 500.0), ("discharge", -500.0)])
def test_actual_interval_charge_and_derivative_hand_calculation(mode, expected_derivative):
    trace = charge_trace(mode)
    untouched = deepcopy(trace)
    result = ica.evaluate_ica(trace)
    assert result.status == "PASS"
    assert result.protocol_mode == mode
    assert len(result.intervals) == 30
    # Each interval transfers 0.1 A * 10 s = 1 C; sign of dV remains declared.
    assert result.intervals[0].delta_charge_C == pytest.approx(1.0)
    assert result.intervals[0].dQ_dV_C_per_V == pytest.approx(expected_derivative)
    assert result.intervals[0].dQ_dV_Ah_per_V == pytest.approx(expected_derivative / 3600.0)
    assert result.statistics["total_transferred_charge_C"] == pytest.approx(30.0)
    assert "not signed stored-sodium" in result.charge_sign_convention
    assert result.posterior_updated is False
    assert trace == untouched
    json.dumps(result.model_dump(mode="json"), allow_nan=False)


@pytest.mark.parametrize("change,expected_reason", [
    ("nonmonotonic", "voltage_not_strictly_monotonic_in_protocol_direction"),
    ("coarse_voltage", "voltage_sampling_too_coarse"),
    ("coarse_time", "time_sampling_too_coarse"),
    ("noise", "voltage_noise_too_large_for_derivative"),
    ("noise_unknown", "voltage_noise_level_unknown"),
    ("protocol_missing", "diagnostic_protocol_missing"),
    ("pulse", "quasi_static_constant_current_protocol_unconfirmed"),
    ("quasi_unknown", "quasi_static_constant_current_protocol_unconfirmed"),
    ("current_change", "constant_current_unconfirmed"),
    ("temperature_missing", "temperature_measurements_missing"),
    ("temperature_drift", "temperature_not_stationary"),
    ("nominal_missing", "nominal_capacity_for_rate_missing"),
    ("source_missing", "source_reference_missing"),
    ("sign_wrong", "current_direction_or_rest_inconsistent_with_protocol"),
])
def test_ica_quality_unknown_without_curve(change, expected_reason):
    trace = charge_trace()
    if change == "nonmonotonic":
        trace["voltage_V"][8] = trace["voltage_V"][7] - 0.001
    elif change == "coarse_voltage":
        trace["voltage_V"] = [3 + i * 0.02 for i in range(31)]
    elif change == "coarse_time":
        trace["time_s"] = [100 * i for i in range(31)]
    elif change == "noise":
        trace["voltage_noise_std_V"] = 0.002
    elif change == "noise_unknown":
        trace["voltage_noise_std_V"] = None
    elif change == "protocol_missing":
        trace["protocol"] = None
    elif change == "pulse":
        trace["protocol"].update(mode="pulse", quasi_static=False)
    elif change == "quasi_unknown":
        trace["protocol"]["quasi_static"] = None
    elif change == "current_change":
        trace["current_A"][5] = -0.4
    elif change == "temperature_missing":
        trace["temperature_K"] = None
    elif change == "temperature_drift":
        trace["temperature_K"][5] = 300
    elif change == "nominal_missing":
        trace["protocol"]["nominal_capacity_C"] = None
    elif change == "source_missing":
        trace["source_ref"] = None
    else:
        trace["current_A"] = [0.1] * 31
    result = ica.evaluate_ica(trace)
    assert result.status == "UNKNOWN"
    assert expected_reason in result.reasons
    assert result.intervals == ()


@pytest.mark.parametrize("change,reason", [("length", "vector_lengths_mismatch"),
                                           ("time", "timestamps_not_strictly_increasing"),
                                           ("nonfinite", "trace_schema_invalid"),
                                           ("temperature", "temperature_not_positive_K"),
                                           ("extra_truth", "trace_schema_invalid")])
def test_invalid_ica_inputs_fail_without_curve(change, reason):
    trace = charge_trace()
    if change == "length":
        trace["current_A"] = trace["current_A"][:-1]
    elif change == "time":
        trace["time_s"][5] = trace["time_s"][4]
    elif change == "nonfinite":
        trace["voltage_V"][2] = float("nan")
    elif change == "temperature":
        trace["temperature_K"][2] = -1
    else:
        trace["reference_true_soh"] = 0.8
    result = ica.evaluate_ica(trace)
    assert result.status == "FAIL" and reason in result.reasons and result.intervals == ()


def test_explicit_capacity_unit_conversion_and_quality_policy():
    assert ica.coulombs_from_Ah(3.2) == pytest.approx(11520.0)
    for value in (0.0, -1.0, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            ica.coulombs_from_Ah(value)
    assert ica.evaluate_ica(charge_trace(), {"min_voltage_increment_V": 0.02}).status == "FAIL"
    sparse = charge_trace()
    for key in ("time_s", "voltage_V", "current_A", "temperature_K"):
        sparse[key] = sparse[key][:4]
    assert ica.evaluate_ica(sparse).intervals == ()


@pytest.mark.parametrize("convention,declared_imaginary", [("imaginary", -4.0), ("negative_imaginary", 4.0)])
def test_provided_complex_eis_sign_and_magnitude_hand_calculation(convention, declared_imaginary):
    record = eis_record()
    record["imaginary_convention"] = convention
    record["imaginary_Ohm"][0] = declared_imaginary
    before = deepcopy(record)
    result = impedance.evaluate_impedance(record)
    assert result.status == "PASS"
    first = result.spectrum[0]
    assert first.imaginary_Ohm == -4.0
    assert first.magnitude_Ohm == pytest.approx(5.0)  # hypot(3,-4)
    assert first.phase_rad == pytest.approx(atan2(-4, 3))
    assert result.frequency_coverage_Hz == (10.0, 1000.0)
    assert record == before and result.posterior_updated is False


def test_scalar_ac_resistance_never_creates_frequency_spectrum():
    for frequency in (None, [1000.0]):
        result = impedance.evaluate_impedance({"record_id": "synthetic-acr", "provenance_type": "synthetic",
                                               "kind": "scalar_ac_resistance", "frequency_Hz": frequency,
                                               "scalar_ac_resistance_Ohm": 0.02})
        assert result.status == "UNKNOWN" and result.spectrum == ()
        assert result.scalar_ac_resistance_Ohm == 0.02
        assert "scalar_ac_resistance_is_not_frequency_resolved_EIS" in result.reasons
    assert impedance.evaluate_impedance(None).status == "UNKNOWN"


def test_zero_complex_impedance_preserves_spectrum_but_phase_is_mathematically_undefined():
    record = eis_record()
    record["real_Ohm"][1] = 0.0
    record["imaginary_Ohm"][1] = 0.0
    result = impedance.evaluate_impedance(record)
    assert result.status == "PASS" and len(result.spectrum) == 3
    middle = result.spectrum[1]
    assert middle.real_Ohm == 0.0 and middle.imaginary_Ohm == 0.0 and middle.magnitude_Ohm == 0.0
    assert middle.phase_rad is None and middle.phase_status == "UNKNOWN"
    assert middle.phase_reason == "zero_complex_impedance_phase_undefined"
    assert result.spectrum[0].phase_status == "PASS" and result.spectrum[0].phase_rad == pytest.approx(atan2(-4, 3))
    assert result.spectrum[2].phase_status == "PASS" and result.spectrum[2].phase_rad is not None


@pytest.mark.parametrize("field,value,reason", [
    ("imaginary_convention", None, "imaginary_sign_convention_unknown"),
    ("small_signal_verified", False, "small_signal_condition_unconfirmed"),
    ("stationary_verified", None, "stationarity_unconfirmed"),
    ("temperature_K", None, "impedance_temperature_unknown"),
    ("source_ref", None, "source_reference_missing"),
    ("frequency_Hz", None, "frequency_resolved_complex_impedance_missing"),
])
def test_missing_eis_acquisition_conditions_unknown(field, value, reason):
    record = eis_record()
    record[field] = value
    result = impedance.evaluate_impedance(record)
    assert result.status == "UNKNOWN" and reason in result.reasons and result.spectrum == ()


@pytest.mark.parametrize("field,value,reason", [
    ("frequency_Hz", [0.0, 1.0, 2.0], "frequency_not_positive_Hz"),
    ("frequency_Hz", [1.0, 1.0, 2.0], "duplicate_frequencies_require_explicit_repeat_protocol"),
    ("real_Ohm", [1.0], "impedance_vector_lengths_mismatch"),
    ("real_Ohm", [float("inf"), 1.0, 2.0], "impedance_schema_invalid"),
    ("scalar_ac_resistance_Ohm", 0.5, "spectrum_contains_conflicting_scalar_record"),
])
def test_invalid_eis_inputs_fail_without_spectrum(field, value, reason):
    record = eis_record()
    record[field] = value
    result = impedance.evaluate_impedance(record)
    assert result.status == "FAIL" and reason in result.reasons and result.spectrum == ()


def test_rank_one_has_actual_local_nullspace_and_retains_particle_distribution():
    snap = posterior()
    untouched = snap.model_dump(mode="json")
    result = identifiability.diagnose_identifiability(snap, local_jacobian())
    assert result.status == "PASS" and result.rank == 1
    assert result.state_dimension == 2 and result.global_identifiability == "UNKNOWN"
    assert set(result.ambiguous_state_names) == {"site_1", "site_2"}
    assert result.important_ambiguous_state_names == ("site_2",)
    null = np.asarray(result.nullspace_scaled_coordinates)
    assert null.shape == (1, 2)
    assert np.linalg.norm(np.asarray(result.scaled_whitened_jacobian) @ null.T) < 1e-14
    assert np.linalg.norm(null[0]) == pytest.approx(1.0)
    assert result.posterior == untouched == snap.model_dump(mode="json")
    assert result.posterior_updated is False
    result.posterior["samples"][0][0] = 999.0
    assert snap.model_dump(mode="json") == untouched  # Returned copy cannot mutate original distribution.


def test_available_diagnostic_uses_actual_local_sensitivity_and_weighted_covariance():
    result = identifiability.diagnose_identifiability(posterior(), local_jacobian(), [option()], budget_s=8.0)
    assert result.rank == 1 and len(result.recommendations) == 1
    recommended = result.recommendations[0]
    assert recommended["local_rank_gain"] == 1
    assert recommended["nullspace_sensitivity_score"] == pytest.approx(2.0)
    # Weighted x1-x2 deviations are +/-0.6, variance0.36, noise variance1.
    assert recommended["local_information_proxy_nats"] == pytest.approx(0.5 * log(1.36))
    assert recommended["important_unidentified_states"] == ["site_2"]
    assert "proxy" in result.information_value_scope
    assert result.posterior == posterior().model_dump(mode="json")


@pytest.mark.parametrize("field,value,reason", [
    ("availability", "unavailable", "diagnostic_not_declared_available"),
    ("availability", "unknown", "diagnostic_not_declared_available"),
    ("cost_s", 9.0, "diagnostic_exceeds_available_budget_s"),
    ("conditions_confirmed", False, "diagnostic_conditions_unconfirmed"),
    ("sensitivity_source_ref", None, "diagnostic_source_or_sensitivity_reference_missing"),
    ("sensitivity_rows", None, "diagnostic_sensitivity_or_noise_missing"),
    ("sensitivity_rows", [[1.0, 1.0]], "diagnostic_has_no_sensitivity_to_current_local_nullspace"),
])
def test_unavailable_uninformative_diagnostics_not_recommended(field, value, reason):
    diagnostic = option()
    diagnostic[field] = value
    result = identifiability.diagnose_identifiability(posterior(), local_jacobian(), [diagnostic], budget_s=8.0)
    assert result.recommendations == ()
    assert result.excluded_diagnostics[0]["reason"] == reason
    assert result.posterior == posterior().model_dump(mode="json")


def test_no_gaussian_noise_declaration_has_no_fabricated_information_value():
    diagnostic = option()
    diagnostic["noise_model"] = "unknown"
    result = identifiability.diagnose_identifiability(posterior(), local_jacobian(), [diagnostic], budget_s=8)
    assert result.recommendations[0]["local_information_proxy_nats"] is None
    assert result.recommendations[0]["information_reason"] == "independent_gaussian_noise_not_declared"


def test_scaled_whitening_and_near_rank_deficiency_have_explicit_numeric_tolerance():
    model = local_jacobian()
    model.update(jacobian=[[2.0, 0.0], [0.0, 0.001]], observation_names=["a", "b"],
                 observation_units=["V", "A"], observation_noise_std=[2.0, 1.0], state_scales=[1.0, 1000.0])
    result = identifiability.diagnose_identifiability(posterior(), model)
    assert result.rank == 2 and result.nullspace_scaled_coordinates == ()
    assert np.asarray(result.scaled_whitened_jacobian) == pytest.approx(np.eye(2))
    assert result.global_identifiability == "UNKNOWN" and result.posterior_updated is False
    model.update(jacobian=[[1.0, 0.0], [0.0, 1e-12]], observation_noise_std=[1.0, 1.0], state_scales=[1.0, 1.0])
    near = identifiability.diagnose_identifiability(posterior(), model)
    assert near.rank == 1 and near.rank_threshold == pytest.approx(1e-8)


@pytest.mark.parametrize("field,value,reason", [
    ("snapshot_id", "other-snapshot", "linearization_snapshot_binding_mismatch"),
    ("obs_until_s", 31.0, "linearization_snapshot_binding_mismatch"),
    ("parameter_revision", "other-revision", "linearization_snapshot_binding_mismatch"),
    ("evaluation_point", [0.4, 0.5], "linearization_point_does_not_equal_snapshot_mean"),
    ("state_scales", [1.0, 0.0], "state_scales_not_positive"),
    ("jacobian", [[1.0]], "jacobian_or_noise_dimensions_mismatch"),
    ("observation_noise_std", [0.0], "observation_noise_std_not_positive"),
    ("jacobian", [[float("nan"), 1.0]], "local_jacobian_schema_invalid"),
    ("important_state_names", ["true_hidden_reference"], "important_states_not_in_snapshot_definition"),
])
def test_invalid_local_derivative_context_fails_without_narrowing(field, value, reason):
    model = local_jacobian()
    model[field] = value
    result = identifiability.diagnose_identifiability(posterior(), model)
    assert result.status == "FAIL" and reason in result.reasons
    assert result.rank is None and result.recommendations == ()
    assert result.posterior == posterior().model_dump(mode="json")


def test_missing_jacobian_and_svd_failure_stay_unknown(monkeypatch):
    snap = posterior()
    assert identifiability.diagnose_identifiability(snap, None).status == "UNKNOWN"
    def failed_svd(*args, **kwargs):
        raise np.linalg.LinAlgError("synthetic solver failure")
    monkeypatch.setattr(np.linalg, "svd", failed_svd)
    result = identifiability.diagnose_identifiability(snap, local_jacobian())
    assert result.status == "UNKNOWN" and result.reasons == ("local_SVD_failed",)
    assert result.rank is None and result.posterior == snap.model_dump(mode="json")


def test_duplicate_options_budget_error_and_scaled_overflow_are_fail_closed():
    duplicate = identifiability.diagnose_identifiability(posterior(), local_jacobian(), [option(), option()], budget_s=8)
    assert duplicate.status == "FAIL" and duplicate.reasons == ("duplicate_diagnostic_option_ids",)
    assert identifiability.diagnose_identifiability(posterior(), local_jacobian(), budget_s=float("nan")).status == "FAIL"
    model = local_jacobian()
    model.update(jacobian=[[1e300, 1.0]], state_scales=[1e300, 1.0])
    assert identifiability.diagnose_identifiability(posterior(), model).reasons == ("scaled_jacobian_overflow",)


def test_actual_finite_matrix_can_have_nonfinite_svd_and_must_not_fabricate_rank():
    model = local_jacobian()
    model.update(jacobian=[[1e308, 1e308], [1e308, 1e308]],
                 observation_names=["a", "b"], observation_units=["1", "1"], observation_noise_std=[1.0, 1.0])
    result = identifiability.diagnose_identifiability(posterior(), model)
    assert result.status == "UNKNOWN" and result.reasons == ("local_SVD_nonfinite",)
    assert result.rank is None and result.recommendations == ()
    assert result.posterior == posterior().model_dump(mode="json")


def test_invalid_options_container_is_structured_failure_and_keeps_posterior():
    for container in (7, "available EIS", {"invented_hardware": "available"}):
        result = identifiability.diagnose_identifiability(posterior(), local_jacobian(), container)
        assert result.status == "FAIL" and result.reasons == ("diagnostic_options_schema_invalid",)
        assert result.posterior == posterior().model_dump(mode="json")


def test_information_logdet_solver_failure_is_unknown_not_fake_zero(monkeypatch):
    def failed_logdet(*args, **kwargs):
        raise np.linalg.LinAlgError("synthetic information solver failure")
    monkeypatch.setattr(np.linalg, "slogdet", failed_logdet)
    result = identifiability.diagnose_identifiability(posterior(), local_jacobian(), [option()], budget_s=8)
    assert result.status == "PASS" and result.rank == 1
    assert result.recommendations[0]["local_information_proxy_nats"] is None
    assert result.recommendations[0]["information_reason"] == "local_information_logdet_failed"
    assert result.posterior == posterior().model_dump(mode="json")
