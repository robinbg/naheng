from dataclasses import asdict
import json
from pathlib import Path
import shutil
import time
import uuid

import pytest

from naheng.domain.contracts import ForecastQuery, Observation, RunManifest
from naheng.estimation.particle_filter import ParticleFilter
from naheng.models.site_model import SiteModel
from naheng.packages.registry import ModelRegistry
from naheng.runtime.artifacts import atomic_json, sha256_file
from naheng.runtime.forecast_jobs import create_forecast_job, dispatch_forecast_job, forecast_store, get_forecast_result
from naheng.runtime.freezing import freeze_source
from naheng.runtime.jobs import JobStore, JobQuotaExceeded
from naheng.runtime.snapshots import save_snapshot

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def saved_source(tmp_path):
    project = tmp_path / "p"
    for folder in ("src", "configs", "model_packages"):
        shutil.copytree(ROOT / folder, project / folder, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(ROOT / "uv.lock", project / "uv.lock")
    shutil.copyfile(ROOT / "pyproject.toml", project / "pyproject.toml")
    runs = JobStore(project / "artifacts/runs")
    source_id = runs.create({"mode": "interactive"})["run_id"]
    model = SiteModel()
    pf = ParticleFilter(source_id, model, particles=4, seed=120)
    observed = model.observe(model.initial_state(), 0)
    snapshot = pf.update(Observation(run_id=source_id, timestamp_s=0, current_A=0,
                        voltage_V=observed["voltage_V"], temperature_K=observed["temperature_K"]), duration_s=0)
    dest = runs.root / source_id; dest.mkdir(parents=True)
    save_snapshot(dest, snapshot)
    package = json.loads((ROOT / "model_packages/research_base/package.json").read_text(encoding="utf-8"))
    package.update(parameters=asdict(model.params), parameter_revision=snapshot.parameter_revision)
    registry = ModelRegistry(ROOT); registry.register(package)
    package = registry.packages[package["package_id"]]
    atomic_json(dest / "posterior.json", [snapshot.model_dump(mode="json")])
    atomic_json(dest / "model_package.json", package)
    source, digest = freeze_source(project, dest)
    manifest = RunManifest(run_id=source_id, mode="interactive", provenance_type="synthetic",
        model_id="two_site_current_adapter_v1", parameter_revision=snapshot.parameter_revision,
        policy_id="fixture-sensor-posterior", data_id="synthetic-test-fixture", code_hash=digest,
        dependency_lock_hash=sha256_file(project / "uv.lock"), seed_bundle={"filter":120},
        artifact_index={"posterior":"posterior.json", "model_package":"model_package.json"}, complete=True)
    atomic_json(dest / "manifest.json", manifest.model_dump(mode="json"))
    atomic_json(dest / "artifact_hashes.json", {"posterior":sha256_file(dest / "posterior.json"),
                "model_package":sha256_file(dest / "model_package.json")})
    assert runs.try_start(source_id); runs.state(source_id, "succeeded", 1)
    return project, source_id, snapshot, dest


def query(snapshot, **overrides):
    return ForecastQuery(snapshot_id=snapshot.snapshot_id, future_policy_id="fixed-current-v1",
        environment_id="constant-ambient-v1", horizon_s=overrides.pop("horizon_s", 30),
        endpoint_protocol=overrides.pop("endpoint_protocol", "unknown-test-endpoint"),
        sample_budget=overrides.pop("sample_budget", 2), current_A=overrides.pop("current_A", .02),
        **overrides)


def wait(project, job_id, timeout=35):
    store = forecast_store(project); until = time.monotonic() + timeout
    while time.monotonic() < until:
        job = store.get(job_id)
        if job["state"] in {"succeeded", "failed", "cancelled", "interrupted"} and (store.root / job_id / "worker_exit.json").is_file():
            return job
        time.sleep(.05)
    raise AssertionError("Forecast did not reach bounded terminal state")


def test_actual_distinct_queries_recompute_from_same_saved_posterior(saved_source):
    project, source_id, snapshot, source = saved_source
    ids = []
    for parameters in ({"current_A":.02, "ambient_K":298.15, "horizon_s":30},
                       {"current_A":-.02, "ambient_K":310.15, "horizon_s":60}):
        job_id = create_forecast_job(project, source_id, snapshot.snapshot_id, query(snapshot, **parameters))
        ids.append(job_id); assert forecast_store(project).get(job_id)["state"] == "queued"
        dispatch_forecast_job(project, job_id)
        assert wait(project, job_id)["state"] == "succeeded"
    first, second = [get_forecast_result(project, i) for i in ids]
    assert ids[0] != ids[1] and first["query_hash"] != second["query_hash"]
    assert first["snapshot_id"] == second["snapshot_id"] == snapshot.snapshot_id
    assert first["paths"][0]["final_state"] != second["paths"][0]["final_state"]
    assert first["paths"][0]["energy_J"] > 0 > second["paths"][0]["energy_J"]
    assert all(r["budget"]["forward_integrations"] > 0 for r in (first, second))
    assert all(r["rul"]["status"] == "unknown" and r["rul"]["median_observed_s"] is None for r in (first, second))
    assert all(r["budget"]["independent_operational_trajectories"] == 0 for r in (first, second))
    assert all(forecast_store(project).get(i)["reused_from"] is None for i in ids)


def test_wrong_snapshot_revision_and_parameter_source_rejected(saved_source):
    project, source_id, snapshot, source = saved_source
    with pytest.raises(ValueError, match="snapshot"):
        create_forecast_job(project, source_id, "missing-snapshot", query(snapshot))
    with pytest.raises(ValueError, match="identity"):
        create_forecast_job(project, source_id, snapshot.snapshot_id, query(snapshot).model_copy(update={"snapshot_id":"wrong"}))
    path = source / "model_package.json"; package = json.loads(path.read_text())
    package["parameters"]["source_id"] = "unregistered-substitute"
    atomic_json(path, package)
    with pytest.raises(ValueError, match="Published source artifact hash"):
        create_forecast_job(project, source_id, snapshot.snapshot_id, query(snapshot))


def test_model_physical_source_drift_is_not_silently_rebound(saved_source):
    project, source_id, snapshot, source = saved_source
    path = project / "src/naheng/models/thermal.py"
    path.write_bytes(path.read_bytes() + b"\n# changed implementation\n")
    with pytest.raises(ValueError, match="physical source hash"):
        create_forecast_job(project, source_id, snapshot.snapshot_id, query(snapshot))


def test_query_domains_and_unknown_policy_are_rejected_without_zero_results(saved_source):
    project, source_id, snapshot, source = saved_source
    for q in (query(snapshot, current_A=1), query(snapshot).model_copy(update={"future_policy_id":"unsupported-scheduled-policy"}),
              query(snapshot).model_copy(update={"environment_id":"unmapped-weather-series"})):
        with pytest.raises(ValueError): create_forecast_job(project, source_id, snapshot.snapshot_id, q)
    with pytest.raises(ValueError): create_forecast_job(project, "../evaluator", snapshot.snapshot_id, query(snapshot))
    with pytest.raises(ValueError): get_forecast_result(project, "../evaluator")
    assert not forecast_store(project).list()


def test_queue_cancel_never_dispatches_or_publishes(saved_source):
    project, source_id, snapshot, source = saved_source
    job_id = create_forecast_job(project, source_id, snapshot.snapshot_id, query(snapshot))
    store = forecast_store(project); store.cancel(job_id)
    with pytest.raises(ValueError, match="queued"): dispatch_forecast_job(project, job_id)
    with pytest.raises(ValueError, match="not complete"): get_forecast_result(project, job_id)
    assert not (store.root / job_id / "forecast.json").exists()


def test_running_cancel_terminates_owned_worker_and_retains_unknown(saved_source):
    project, source_id, snapshot, source = saved_source
    job_id = create_forecast_job(project, source_id, snapshot.snapshot_id,
        query(snapshot, sample_budget=256, horizon_s=3600, endpoint_protocol="synthetic_capacity_v1"))
    store = forecast_store(project); proc = dispatch_forecast_job(project, job_id)
    until = time.monotonic() + 15
    while not any(e["type"] == "forecast_computing" for e in store.events(job_id)) and time.monotonic() < until:
        time.sleep(.05)
    assert any(e["type"] == "forecast_computing" for e in store.events(job_id))
    store.cancel(job_id)
    assert wait(project, job_id)["state"] == "cancelled"
    assert proc.poll() is not None
    failure = json.loads((store.root / job_id / "failure.json").read_text())
    assert failure["status"] == "UNKNOWN" and failure["complete"] is False
    with pytest.raises(ValueError): get_forecast_result(project, job_id)


def test_hard_timeout_is_not_success_and_frozen_input_tamper_fails(saved_source):
    project, source_id, snapshot, source = saved_source
    timed = create_forecast_job(project, source_id, snapshot.snapshot_id,
        query(snapshot, sample_budget=256, horizon_s=3600, endpoint_protocol="synthetic_capacity_v1"), wall_budget_s=2)
    dispatch_forecast_job(project, timed)
    assert wait(project, timed)["state"] == "failed"
    exit_record = json.loads((forecast_store(project).root / timed / "worker_exit.json").read_text())
    assert exit_record["walltime_s"] < 8
    assert exit_record["termination"]["exit_code"] == 0
    tampered = create_forecast_job(project, source_id, snapshot.snapshot_id, query(snapshot))
    path = forecast_store(project).root / tampered / "snapshot.json"
    value = json.loads(path.read_text()); value["parameter_revision"] = "stale"
    atomic_json(path, value)
    dispatch_forecast_job(project, tampered)
    assert wait(project, tampered)["state"] == "failed"
    assert "Frozen input artifact hash mismatch" in forecast_store(project).get(tampered)["error"]


def test_fresh_identical_queries_respect_forecast_store_quota(saved_source):
    project, source_id, snapshot, source = saved_source
    ids = [create_forecast_job(project, source_id, snapshot.snapshot_id, query(snapshot)) for _ in range(4)]
    assert len(set(ids)) == 4
    with pytest.raises(JobQuotaExceeded): create_forecast_job(project, source_id, snapshot.snapshot_id, query(snapshot))
    store = forecast_store(project)
    store.cancel(ids[0])
    new_id = create_forecast_job(project, source_id, snapshot.snapshot_id, query(snapshot))
    assert new_id not in ids
