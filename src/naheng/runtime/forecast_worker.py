"""Numerical forecast worker invoked from a frozen source snapshot."""
from __future__ import annotations
import json, os
from pathlib import Path
import sys
import time

from naheng.domain.contracts import ForecastQuery, PosteriorSnapshot
from naheng.lifecycle.forecast import forecast
from naheng.packages.registry import ModelRegistry, content_hash
from naheng.packages.transition import ForecastExecution
from .artifacts import atomic_json, code_hash, sha256_file
from .execution_environment import capture_environment, assert_environment_unchanged
from .forecast_jobs import forecast_store, _identifier, _json, _inside, _package_model, _query_check, _incomplete


def execute_forecast(project: Path, job_id: str):
    _identifier(job_id)
    store = forecast_store(project); dest = store.root / job_id
    if not store.try_start(job_id,owner_pid=os.getpid()):
        return 2
    job = store.get(job_id); config = job["config"]
    started = time.monotonic()
    try:
        source = Path(config["source_dir"]).resolve()
        if source != (dest / "source_snapshot").resolve():
            raise ValueError("Worker source directory is not the isolated frozen job source")
        if not Path(__file__).resolve().is_relative_to(source):
            raise ValueError("Worker must execute from the frozen source")
        if code_hash(source) != config["code_hash"]:
            raise ValueError("Frozen executable source hash mismatch")
        inputs = _json(dest / "inputs.json")
        if inputs != config:
            raise ValueError("Persisted forecast input/config mismatch")
        for rel, digest in config["source_artifact_hashes"].items():
            if sha256_file(_inside(dest, rel)) != digest:
                raise ValueError("Frozen input artifact hash mismatch: " + rel)
        query = ForecastQuery.model_validate(_json(dest / "query.json"))
        if query.model_dump(mode="json") != config["query"] or content_hash(query.model_dump(mode="json")) != config["query_identity_hash"]:
            raise ValueError("Frozen query hash mismatch")
        snapshot = PosteriorSnapshot.model_validate(_json(dest / "snapshot.json"))
        package = _json(dest / "model_package.json")
        model = _package_model(package, source, snapshot)
        _query_check(query, snapshot, package)
        registry = ModelRegistry(source); registry.register(package, expected_hash=package["package_hash"])
        rebound = registry.packages[package["package_id"]]
        for field in ("parameter_hash", "binding_hashes", "execution_binding", "package_hash"):
            if rebound[field] != package[field]:
                raise ValueError("Frozen actual model differs from source Run binding: " + field)
        environment = capture_environment(source)
        atomic_json(dest / "execution_environment.json", environment)
        store.event(job_id, {"type": "forecast_computing", "snapshot_id": snapshot.snapshot_id,
                            "query_identity_hash": config["query_identity_hash"], "actual_function": "naheng.lifecycle.forecast.forecast"})
        store.state(job_id, "running", .1)
        remaining = config["wall_budget_s"] - (time.monotonic() - started)
        if remaining <= 0: raise TimeoutError("Forecast budget exhausted before solver entry")
        execution=ForecastExecution(model,snapshot,package,config.get("theory_selection"),proof_root=project)
        result = forecast(snapshot, query, model, wall_budget_s=remaining,
                          cancel_check=lambda: bool(store.get(job_id)["cancel"]),execution_context=execution)
        result.update(job_id=job_id, source_run_id=config["source_run_id"],
                      input_hash=job["input_hash"], code_hash=config["code_hash"],
                      parameter_hash=config["parameter_hash"], package_hash=config["package_hash"],
                      source_artifact_hashes=config["source_artifact_hashes"],
                      query_identity_hash=config["query_identity_hash"])
        result["budget"].update(hard_worker_wall_budget_s=config["wall_budget_s"],
                                hard_budget_enforcement="parent_owned_process_tree_including_solver_calls")
        if store.get(job_id)["cancel"]:
            raise InterruptedError("Forecast cancelled before publication")
        if result["budget"]["exhausted"] or result["budget"]["completed_paths"] != query.sample_budget:
            atomic_json(dest / "partial.json", {"complete": False, "status": "UNKNOWN", "prediction": result})
            raise RuntimeError("Forecast has failed/interrupted paths; complete prediction withheld")
        assert_environment_unchanged(source, environment)
        if code_hash(source) != config["code_hash"]:
            raise ValueError("Frozen source changed during prediction")
        process = _json(dest / "worker_process.json")
        if time.monotonic() - process["started_monotonic_s"] >= config["wall_budget_s"]:
            raise TimeoutError("Forecast exceeded hard launch-to-publication deadline")
        atomic_json(dest / "forecast.json", result)
        manifest = {"schema_version": 1, "kind": "conditional_forecast_job", "job_id": job_id,
                    "source_run_id": config["source_run_id"], "snapshot_id": snapshot.snapshot_id,
                    "query_identity_hash": config["query_identity_hash"], "query_hash": result["query_hash"],
                    "input_hash": job["input_hash"], "code_hash": config["code_hash"],
                    "parameter_hash": config["parameter_hash"], "package_hash": config["package_hash"],
                    "provenance_type": "synthetic", "complete": True, "independent_operational_trajectories": 0,
                    "artifact_index": {"forecast": "forecast.json", "query": "query.json", "snapshot": "snapshot.json", "inputs": "inputs.json"},
                    "artifact_hashes": {name: sha256_file(dest / name) for name in ("forecast.json", "query.json", "snapshot.json", "inputs.json", "execution_environment.json")}}
        atomic_json(dest / "manifest.json", manifest)
        if time.monotonic() - process["started_monotonic_s"] >= config["wall_budget_s"]:
            raise TimeoutError("Forecast exceeded hard deadline during publication")
        store.state(job_id, "succeeded", 1)
        return 0
    except Exception as exc:
        _incomplete(store, job_id, type(exc).__name__ + ": " + str(exc))
        print(json.dumps({"job_id": job_id, "status": "UNKNOWN", "error_type": type(exc).__name__, "reason": str(exc)}), flush=True)
        return 2 if store.get(job_id)["cancel"] else 1


if __name__ == "__main__":
    raise SystemExit(execute_forecast(Path(sys.argv[1]), sys.argv[2]))
