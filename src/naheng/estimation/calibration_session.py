"""Bounded calibration with recomputed builtin dynamics and immutable artifacts."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from naheng.domain.contracts import Observation, PosteriorSnapshot, RegisteredModelPackage
from naheng.runtime.artifacts import atomic_json, code_hash, sha256_file
from naheng.runtime.forecast_jobs import _package_model
from .particle_filter import ParticleFilter, particle_model
from .calibration import (FrozenPosterior, TrainingBatch, GaussianNoise, fit_candidate,
                          posterior_to_contract, content_hash, _eligibility)
from .discrepancy import monitor_discrepancy


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FileRef(Schema):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class HistoryStep(Schema):
    timestamp_s: float = Field(ge=0)
    current_A: float
    ambient_K: float = Field(gt=0)
    thermal_W: float


class SensorRecord(HistoryStep):
    observation_id: str = Field(min_length=1)
    values: tuple[float, float]


class TrainingSource(Schema):
    schema_version: Literal[1] = 1
    source_id: str
    source_revision: str
    model_id: Literal["two_site_current_adapter_v1"]
    model_package_id: str
    parameter_revision: str
    chemistry_id: Literal["synthetic_two_site"]
    provenance_type: Literal["synthetic"]
    role: Literal["train"]
    filter_seed: int
    voltage_noise_V: float = Field(gt=0)
    temperature_noise_K: float = Field(gt=0)
    initial_observation: Observation
    prior_snapshot: PosteriorSnapshot
    records: tuple[SensorRecord, ...] = Field(min_length=3, max_length=32)


class CalibrationRequest(Schema):
    schema_version: Literal[1] = 1
    analysis_id: str = Field(min_length=1, max_length=128)
    prior: FrozenPosterior
    batch: TrainingBatch
    noise: GaussianNoise | None
    model_package: RegisteredModelPackage
    training_source: FileRef
    execution_history: tuple[HistoryStep, ...] = Field(min_length=3, max_length=32)
    minimum_samples: int = Field(default=3, ge=3, le=32)
    minimum_span_s: float = Field(default=1e-9, gt=0)
    discrepancy_window: int = Field(default=5, ge=1, le=32)
    discrepancy_minimum_history: int = Field(default=3, ge=1, le=32)
    innovation_limit: float = Field(default=3, gt=0)
    bias_limit: float = Field(default=2, gt=0)
    joint_innovation_limit: float = Field(default=3, gt=0)


def _file(root: Path, ref: FileRef, folder: str) -> Path:
    path = (root / ref.path).resolve()
    if (not path.is_relative_to(root / folder)
            or any(part.casefold() == "evaluator" for part in Path(ref.path).parts)
            or any(part.casefold() == "evaluator" for part in path.parts)):
        raise ValueError("Only controlled public calibration source files are allowed")
    if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024 or sha256_file(path) != ref.sha256:
        raise ValueError("Missing, oversized or changed calibration source bytes")
    return path


def verify_builtin_forward(root: Path, request: CalibrationRequest) -> dict:
    """Recompute prefix, every parent prediction, final state and SOC readout."""
    started = time.monotonic()
    prior, batch = request.prior, request.batch
    if len(prior.samples) > 64:
        raise ValueError("Builtin calibration is limited to 64 parent particles")
    if batch.channels != ("voltage_V", "temperature_K") or batch.units != ("V", "K"):
        raise ValueError("Builtin calibration accepts voltage and temperature sensor channels")
    source_path = _file(root, request.training_source, "data/synthetic")
    source = TrainingSource.model_validate_json(source_path.read_bytes())
    binding = prior.binding
    expected = (binding.source_id, binding.source_revision, binding.model_id,
                binding.model_package_id, binding.parameter_revision, binding.chemistry_id, binding.provenance_type)
    actual = (source.source_id, source.source_revision, source.model_id,
              source.model_package_id, source.parameter_revision, source.chemistry_id, source.provenance_type)
    if expected != actual or binding.source_sha256 != request.training_source.sha256:
        raise ValueError("Training source header and posterior binding disagree")
    if content_hash(source.prior_snapshot) != prior.source_snapshot_sha256:
        raise ValueError("Initial posterior does not match its public source prefix")
    snapshot = source.prior_snapshot
    # Hash the supplied registered descriptor, preserving omitted defaults.
    # Adding schema_version during serialization changes its registered hash.
    model = _package_model(request.model_package.model_dump(mode="json", exclude_unset=True), root, snapshot)
    if binding.parameter_sha256 != request.model_package.parameter_hash or binding.model_source_sha256 != request.model_package.binding_hashes["src/naheng/models/site_model.py"]:
        raise ValueError("Actual model parameter/source binding mismatch")
    if prior.state_names != tuple(model.state_names) + ("rate_scale", "side_rate_scale") or prior.parameter_state_names != ("rate_scale", "side_rate_scale"):
        raise ValueError("Builtin joint state/parameter mapping mismatch")
    expected_units = tuple(model.state_units) + ("1", "1")
    if prior.state_units != expected_units or tuple(snapshot.state_units) != expected_units:
        raise ValueError("Builtin joint state units differ from the actual model and source posterior")
    if prior.obs_until_s != 0 or source.initial_observation.timestamp_s != 0 or source.initial_observation.run_id != prior.run_id:
        raise ValueError("This builtin source must start from an explicitly observed time-zero prefix")
    prefix_filter = ParticleFilter(prior.run_id, model, seed=source.filter_seed,
                                   particles=len(prior.samples), voltage_noise_V=source.voltage_noise_V,
                                   temperature_noise_K=source.temperature_noise_K)
    recomputed = prefix_filter.update(source.initial_observation)
    if recomputed.model_dump(mode="json") != snapshot.model_dump(mode="json"):
        raise ValueError("Initial posterior differs from actual seeded sensor assimilation")
    if tuple(tuple(row) for row in snapshot.samples) != prior.samples or tuple(snapshot.weights) != prior.weights:
        raise ValueError("Frozen prior differs from the actual source posterior")
    if len(source.records) != len(batch.observations) or len(source.records) != len(request.execution_history):
        raise ValueError("Sensor records, prediction rows and action history disagree")
    for row, observation, step in zip(source.records, batch.observations, request.execution_history):
        if (row.observation_id, row.timestamp_s, row.values) != (observation.observation_id, observation.timestamp_s, observation.values):
            raise ValueError("Training measurements differ from the hashed public sensor source")
        if step.model_dump() != {key: getattr(row, key) for key in ("timestamp_s", "current_A", "ambient_K", "thermal_W")}:
            raise ValueError("Prediction execution history differs from the public source")
    evidence = batch.propagation_evidence
    forward_path = _file(root, FileRef(path=evidence.source_ref, sha256=evidence.artifact_sha256), "artifacts")
    particles = np.asarray(prior.samples).copy()
    nominal = np.asarray(prior.mean[:len(prior.state_names)]).copy()
    models = [particle_model(model, row[-2], row[-1]) for row in particles]
    nominal_model = particle_model(model, nominal[-2], nominal[-1])
    predictions, nominal_predictions = [], []
    timestamp = prior.obs_until_s
    for step in request.execution_history:
        elapsed = step.timestamp_s - timestamp
        if not 0 < elapsed <= 60:
            raise ValueError("Strictly forward intervals of at most 60s are supported")
        readings = []
        for row, sampled in zip(particles, models):
            if time.monotonic() - started >= 100:
                raise TimeoutError("Calibration forward verification budget exhausted")
            integrated = sampled.integrate(row[:5], step.current_A, elapsed, ambient_K=step.ambient_K, thermal_W=step.thermal_W)
            if integrated.elapsed_s < elapsed - 1e-6:
                raise ValueError("Parent trajectory terminated before a training observation")
            row[:5] = integrated.state
            sensed = sampled.observe(row[:5], step.current_A)
            readings.append([sensed["voltage_V"], sensed["temperature_K"]])
        if time.monotonic() - started >= 100:
            raise TimeoutError("Calibration forward verification budget exhausted before nominal solve")
        integrated = nominal_model.integrate(nominal[:5], step.current_A, elapsed, ambient_K=step.ambient_K, thermal_W=step.thermal_W)
        if integrated.elapsed_s < elapsed - 1e-6:
            raise ValueError("Nominal trajectory terminated before a training observation")
        nominal[:5] = integrated.state
        sensed = nominal_model.observe(nominal[:5], step.current_A)
        nominal_predictions.append([sensed["voltage_V"], sensed["temperature_K"]])
        predictions.append(readings)
        timestamp = step.timestamp_s
    def same(values, supplied):
        return np.shape(values) == np.shape(supplied) and np.allclose(values, supplied, rtol=1e-10, atol=1e-12)
    if not same(predictions, batch.particle_predictions) or not same(nominal_predictions, batch.nominal_predictions) or not same(particles, batch.propagated_joint_samples):
        raise ValueError("Supplied predictions or final states fail actual builtin forward recomputation")
    capacities = np.asarray(model.params.site_capacity_mol)
    for supplied, states in ((prior.derived_observables, prior.samples), (batch.propagated_derived_observables, particles)):
        if len(supplied) != 1 or supplied[0].name != "soc" or supplied[0].unit != "1":
            raise ValueError("Builtin derived readout must be same-particle dimensionless SOC")
        actual_soc = np.asarray(states)[:, :2] @ capacities / capacities.sum()
        if not same(actual_soc, supplied[0].particle_values):
            raise ValueError("Supplied SOC fails the actual same-particle capacity readout")
    _file(root, request.training_source, "data/synthetic")
    _file(root, FileRef(path=evidence.source_ref, sha256=evidence.artifact_sha256), "artifacts")
    return {"status": "PASS", "source_bytes_and_headers_match": True,
            "initial_sensor_assimilation_recomputed": True,
            "actual_parent_forward_predictions_recomputed": True, "same_particle_SOC_recomputed": True,
            "parents": len(particles), "training_observations": len(source.records),
            "channels": list(batch.channels), "model_binding_hashes": request.model_package.binding_hashes,
            "scope": "Declared synthetic sensor source and actual builtin numerical solves; not real sensors or validated solver error bounds"}


def analyze_calibration(root: Path, request: CalibrationRequest) -> dict:
    status, reasons = _eligibility(request.prior, request.batch, request.noise)
    verification = {"status": "UNKNOWN", "reasons": list(reasons), "actual_forward_verified": False}
    if status == "PASS":
        verification = verify_builtin_forward(root, request)
    result = fit_candidate(request.prior, request.batch, request.noise,
                           minimum_samples=request.minimum_samples, minimum_span_s=request.minimum_span_s)
    data = result.model_dump(mode="json")
    if result.candidate is not None:
        data["candidate_content_sha256"] = result.candidate.content_sha256
        data["posterior_content_sha256"] = result.candidate.posterior.content_sha256
        data["posterior_contract"] = posterior_to_contract(result.candidate).model_dump(mode="json")
    discrepancy = (monitor_discrepancy(request.prior, request.batch, request.noise,
                    window=request.discrepancy_window, minimum_history=request.discrepancy_minimum_history,
                    innovation_limit=request.innovation_limit, bias_limit=request.bias_limit,
                    joint_innovation_limit=request.joint_innovation_limit).model_dump(mode="json")
                   if request.noise is not None else None)
    return {"schema_version": 1, "analysis_id": request.analysis_id,
            "exit_code": {"PASS": 0, "FAIL": 1, "UNKNOWN": 2}[result.status],
            "calibration": data, "discrepancy": discrepancy, "integration_verification": verification,
            "existing_run_or_filter_modified": False, "independent_experiment": False,
            "scope": "Conditional synthetic joint-particle calibration candidate; no automatic adoption, real-cell fit or risk certificate"}


def worker(root: Path, input_path: Path, out: Path) -> int:
    source_hash = code_hash(root)
    try:
        request = CalibrationRequest.model_validate_json(input_path.read_bytes())
        result = analyze_calibration(root, request)
    except (ValueError, OSError, TimeoutError) as error:
        result = {"exit_code": 2 if isinstance(error, (OSError, TimeoutError)) else 1,
                  "status": "UNKNOWN" if isinstance(error, (OSError, TimeoutError)) else "FAIL",
                  "reason": str(error), "candidate": None, "existing_run_or_filter_modified": False}
    if code_hash(root) != source_hash:
        result = {"exit_code": 2, "status": "UNKNOWN", "reason": "Implementation changed during analysis", "candidate": None}
    atomic_json(out / "result.json", result)
    print(json.dumps({"exit_code": result["exit_code"], "result": str(out / "result.json")}, ensure_ascii=False))
    return result["exit_code"]


def run_calibration(root: Path, input_path: Path, output_path: Path) -> dict:
    from naheng.formal.checker import run_command
    root, input_path, out = Path(root).resolve(), Path(input_path).resolve(), Path(output_path).resolve()
    if not out.is_relative_to(root / "artifacts") or out == root / "artifacts":
        raise ValueError("Calibration output must be a new directory under project artifacts")
    if input_path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Calibration JSON exceeds 4 MiB input budget")
    body = input_path.read_bytes()
    if len(body) > 4 * 1024 * 1024:
        raise ValueError("Calibration JSON exceeds 4 MiB input budget")
    CalibrationRequest.model_validate_json(body)
    source_hash, input_hash = code_hash(root), sha256_file(input_path)
    out.mkdir(parents=True, exist_ok=False)
    (out / "input.json").write_bytes(body)
    command = [sys.executable, "-m", "naheng.estimation.calibration_session", "--worker", str(root), str(out / "input.json"), str(out)]
    atomic_json(out / "started.json", {"argv": command, "code_hash": source_hash, "input_sha256": input_hash,
                "status": "started", "timeout_s": 120, "utc": datetime.now(timezone.utc).isoformat()})
    record = run_command(command, root, out / "worker.log", timeout=120)
    atomic_json(out / "worker-command.json", {key: value for key, value in record.items() if key not in ("stdout", "stderr")})
    intact = sha256_file(input_path) == input_hash and sha256_file(out / "input.json") == input_hash and code_hash(root) == source_hash
    result_path = out / "result.json"
    complete = not record["timed_out"] and result_path.is_file() and intact
    result = json.loads(result_path.read_text(encoding="utf-8")) if complete else {"exit_code": 2}
    code = result["exit_code"] if complete and result["exit_code"] == record["exit_code"] else 2
    atomic_json(out / "manifest.json", {"schema_version": 1, "complete": complete, "exit_code": code,
                "code_hash": source_hash, "input_sha256": input_hash, "result_sha256": sha256_file(result_path),
                "existing_run_or_filter_modified": False, "independent_experiment": False,
                "scope": "Bounded owned worker for a conditional calibration candidate; source and forward verification recorded separately"})
    return {"exit_code": code, "artifact_dir": str(out), "complete": complete,
            "scope": "Conditional calibration candidate; existing runs and filters preserved"}


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--worker":
        raise SystemExit("Internal owned calibration worker arguments required")
    raise SystemExit(worker(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))
