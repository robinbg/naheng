"""Separate, immutable-input conditional forecast jobs for API dispatch.

Only saved public posterior artifacts enter the worker. A new query always
gets a new computation; source-run forecasts and evaluator data are not read.
"""
from __future__ import annotations

from dataclasses import asdict, fields
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from naheng.domain.contracts import ForecastQuery, PosteriorSnapshot, RegisteredModelPackage, RunManifest
from naheng.models.site_model import SiteModel, SiteParameters
from naheng.packages.registry import content_hash
from naheng.packages.transition import make_theory_selection
from .artifacts import atomic_json, code_hash, sha256_file
from .freezing import freeze_source
from .jobs import JobStore, TERMINAL
from .process_tree import ProcessTree

_DERIVED = {"package_hash", "validation_status", "execution_binding", "parameter_hash", "binding_hashes", "evidence_validity"}
_ID = re.compile(r"nh-[0-9a-f]{32}\Z")


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Controlled job/run identifier required")
    return value


def _inside(root: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or any(part.casefold() == "evaluator" for part in Path(rel).parts):
        raise ValueError("Only public controlled source files are permitted")
    path = (root / rel).resolve()
    if (not path.is_relative_to(root.resolve()) or not path.is_file()
            or any(part.casefold() == "evaluator" for part in path.parts)):
        raise ValueError("Missing or uncontrolled input artifact")
    return path


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def forecast_store(project: Path) -> JobStore:
    return JobStore(Path(project).resolve() / "artifacts/forecast_jobs")


def _package_model(package: dict, source_root: Path, snapshot: PosteriorSnapshot) -> SiteModel:
    checked = RegisteredModelPackage.model_validate(package)
    if (checked.validation_status != "executable" or checked.execution_binding != "builtin_site_v1"
            or checked.chemistry_id != "synthetic_two_site" or checked.evidence_validity == "stale"):
        raise ValueError("Unsupported or stale forecast model binding")
    if (snapshot.model_package_id != checked.package_id or snapshot.parameter_revision != checked.parameter_revision):
        raise ValueError("Posterior model/revision mismatch")
    if checked.package_hash != content_hash({k: v for k, v in package.items() if k not in _DERIVED}):
        raise ValueError("Model package content hash mismatch")
    if set(checked.parameters) != {field.name for field in fields(SiteParameters)}:
        raise ValueError("All actual model parameters and their source must be persisted")
    params = dict(checked.parameters)
    for name in ("site_capacity_mol", "rate_s_inv", "equilibrium_drive_V", "side_rate_s_inv"):
        params[name] = tuple(params[name])
    model = SiteModel(SiteParameters(**params))
    if model.params.model_kind != "theory_fixture" or checked.domain.get("provenance_type") != "synthetic":
        raise ValueError("Synthetic model cannot be relabelled as public/real-cell data")
    if checked.parameter_hash != content_hash(asdict(model.params)):
        raise ValueError("Actual parameter/source hash mismatch")
    required = {"src/naheng/models/site_model.py", "src/naheng/models/thermal.py", "src/naheng/models/degradation.py",
                checked.dynamics_ast.get("source")}
    if None in required or not required.issubset(checked.binding_hashes):
        raise ValueError("Actual physical model source bindings are required")
    for rel, digest in checked.binding_hashes.items():
        if sha256_file(_inside(source_root, rel)) != digest:
            raise ValueError("Forecast physical source hash differs from source Run binding: " + rel)
    positions = []
    for name, unit in zip(model.state_names, model.state_units):
        if snapshot.state_names.count(name) != 1:
            raise ValueError("Posterior state identity is ambiguous")
        i = snapshot.state_names.index(name)
        if snapshot.state_units[i] != unit:
            raise ValueError("Posterior physical state units mismatch")
        positions.append(i)
    for row in snapshot.samples:
        model._validate_state([row[i] for i in positions])
    return model


def _query_check(query: ForecastQuery, snapshot: PosteriorSnapshot, package: dict):
    if query.snapshot_id != snapshot.snapshot_id:
        raise ValueError("Query snapshot identity mismatch")
    if query.future_policy_id != "fixed-current-v1":
        raise ValueError("Unsupported future policy; only actual fixed-current computation is implemented")
    if query.environment_id not in {"constant-ambient-v1", "ambient-" + str(query.ambient_K)}:
        raise ValueError("Unknown environment; an explicit constant ambient environment is required")
    domain = package["domain"]
    low, high = domain["temperature_K"]
    if not low <= query.ambient_K <= high or abs(query.current_A) > domain["max_current_A"]:
        raise ValueError("Requested current/environment exceeds the registered model domain")


def create_forecast_job(project: Path, source_run_id: str, snapshot_id: str,
                        query: ForecastQuery, *, wall_budget_s: float = 120,
                        max_nonterminal: int = 4) -> str:
    """Freeze server-saved inputs and return a fresh queued ID; no dispatch/reuse."""
    project = Path(project).resolve()
    _identifier(source_run_id)
    query = ForecastQuery.model_validate(query.model_dump(mode="json") if isinstance(query, ForecastQuery) else query)
    if not isinstance(snapshot_id, str) or not snapshot_id or any(x in snapshot_id for x in ("/", "\\", "..", ":")):
        raise ValueError("Controlled snapshot identifier required")
    if not math.isfinite(wall_budget_s) or not 0 < wall_budget_s <= 120:
        raise ValueError("Forecast hard wall budget must be positive and at most 120 seconds")
    runs = JobStore(project / "artifacts/runs")
    source_job = runs.get(source_run_id)
    if source_job["state"] != "succeeded":
        raise ValueError("Source Run must have a complete public posterior")
    source_dir = runs.root / source_run_id
    mf_path = _inside(source_dir, "manifest.json")
    manifest = RunManifest.model_validate(_json(mf_path))
    if not manifest.complete or manifest.run_id != source_run_id or manifest.provenance_type != "synthetic":
        raise ValueError("Source Run identity/completion/provenance mismatch")
    if manifest.artifact_index.get("posterior") != "posterior.json" or manifest.artifact_index.get("model_package") != "model_package.json":
        raise ValueError("Source manifest must register the public posterior and model package")
    posterior_path = _inside(source_dir, "posterior.json")
    package_path = _inside(source_dir, "model_package.json")
    published_hashes = _json(_inside(source_dir, "artifact_hashes.json"))
    for key, path in (("posterior", posterior_path), ("model_package", package_path)):
        if sha256_file(path) != published_hashes.get(key):
            raise ValueError("Published source artifact hash mismatch: " + key)
    posterior = _json(posterior_path)
    matches = [row for row in posterior if row.get("snapshot_id") == snapshot_id]
    if len(matches) != 1:
        raise ValueError("Exactly one registered posterior snapshot is required")
    snapshot_path = _inside(source_dir, "snapshots/" + snapshot_id + ".json")
    snapshot = PosteriorSnapshot.model_validate(_json(snapshot_path))
    if snapshot.model_dump(mode="json") != matches[0] or snapshot.run_id != source_run_id:
        raise ValueError("Immutable/public posterior snapshot identity mismatch")
    package = _json(package_path)
    if manifest.parameter_revision != snapshot.parameter_revision or manifest.model_id != "two_site_current_adapter_v1":
        raise ValueError("Source Run model/revision mismatch")
    _package_model(package, project, snapshot)
    _query_check(query, snapshot, package)
    # Validate the source Run's frozen model files, never the mutable old source_dir.
    source_index_path = _inside(source_dir, "source_index.json")
    source_index = _json(source_index_path)
    if source_index.get("code_hash") != manifest.code_hash:
        raise ValueError("Source Run frozen code identity mismatch")
    for rel, digest in package["binding_hashes"].items():
        if source_index.get("files", {}).get(rel) != digest or sha256_file(_inside(source_dir / "source_snapshot", rel)) != digest:
            raise ValueError("Source Run original physical binding mismatch: " + rel)
    # Server selection is frozen into the new job input hash; clients never supply paths.
    theory_selection=make_theory_selection(project)
    inputs = {"theory_selection":theory_selection,"source_run_id": source_run_id, "snapshot_id": snapshot_id,
              "source_run_code_hash": manifest.code_hash, "query": query.model_dump(mode="json"),
              "wall_budget_s": float(wall_budget_s), "source_artifact_hashes": {
                  "source_manifest.json": sha256_file(mf_path), "posterior.json": sha256_file(posterior_path),
                  "snapshot.json": sha256_file(snapshot_path), "model_package.json": sha256_file(package_path),
                  "source_index_original.json": sha256_file(source_index_path)},
              "parameter_hash": package["parameter_hash"], "package_hash": package["package_hash"],
              "query_identity_hash": content_hash(query.model_dump(mode="json")), "kind": "conditional_forecast_v1"}
    store = forecast_store(project)
    job_id = store.create(inputs, reuse=False, max_nonterminal=max_nonterminal,owner_pid=os.getpid())["run_id"]
    dest = store.root / job_id
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for name, path in (("source_manifest.json", mf_path), ("posterior.json", posterior_path),
                           ("snapshot.json", snapshot_path), ("model_package.json", package_path),
                           ("source_index_original.json", source_index_path)):
            (dest / name).write_bytes(path.read_bytes())
            if sha256_file(dest / name) != inputs["source_artifact_hashes"][name]:
                raise ValueError("Source input changed during freeze: " + name)
        atomic_json(dest / "query.json", query.model_dump(mode="json"))
        frozen, digest = freeze_source(project, dest)
        _package_model(package, frozen, snapshot)
        inputs.update(source_dir=str(frozen), code_hash=digest, dependency_lock_hash=sha256_file(frozen / "uv.lock"))
        store.bind_frozen_config(job_id, inputs)
        atomic_json(dest / "inputs.json", inputs)
        store.event(job_id, {"type": "inputs_frozen", "snapshot_id": snapshot_id, "query_identity_hash": inputs["query_identity_hash"],
                             "code_hash": digest, "parameter_hash": inputs["parameter_hash"]})
    except Exception as exc:
        store.state(job_id, "failed", error="Input freeze failed: " + str(exc))
        raise
    return job_id


def _incomplete(store: JobStore, job_id: str, reason: str, *, cancelled=False, diagnostics=None):
    dest = store.root / job_id
    atomic_json(dest / "failure.json", {"complete": False, "status": "UNKNOWN", "reason": reason,
                                       "termination": diagnostics, "job_id": job_id})
    mf = dest / "manifest.json"
    if mf.is_file():
        value = _json(mf); value["complete"] = False; value["incomplete_reason"] = reason
        atomic_json(mf, value)
    job = store.get(job_id)
    if job["state"] not in TERMINAL:
        store.state(job_id, "cancelled" if cancelled or job["cancel"] else "failed", error=reason)


def dispatch_forecast_job(project: Path, job_id: str) -> subprocess.Popen:
    """Start the frozen worker once and immediately monitor its owned process tree."""
    _identifier(job_id)
    project = Path(project).resolve(); store = forecast_store(project)
    job = store.get(job_id)
    if job["state"] != "queued" or job["cancel"]:
        raise ValueError("Only queued, uncancelled forecast jobs may be dispatched")
    dest = store.root / job_id
    with (dest / "dispatch.json").open("x", encoding="utf-8") as stream:
        json.dump({"job_id": job_id, "utc": store.now(), "single_dispatch": True}, stream)
    argv = [sys.executable, "-m", "naheng.runtime.forecast_worker", str(project), job_id]
    started = time.monotonic()
    try:
        with (dest / "worker.log").open("ab") as log:
            proc = subprocess.Popen(argv, cwd=project, stdout=log, stderr=log,
                env={**os.environ, "PYTHONPATH": str(Path(job["config"]["source_dir"]) / "src"),
                     "PYTHONIOENCODING": "utf-8", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
                start_new_session=os.name != "nt", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        tree = ProcessTree(proc)
        store.bind_worker_owner(job_id,proc.pid)
        atomic_json(dest / "worker_process.json", {"argv": argv, "owned_pid": proc.pid,
                    "hard_wall_budget_s": job["config"]["wall_budget_s"], "started_monotonic_s": started, "utc": store.now()})
        threading.Thread(target=_monitor, args=(proc, tree, store, job_id, started), daemon=True).start()
        return proc
    except Exception as exc:
        if "proc" in locals() and proc.poll() is None:
            proc.kill(); proc.wait(timeout=10)
        _incomplete(store, job_id, "Forecast worker launch failed: " + str(exc))
        raise


def _monitor(proc, tree, store, job_id, started):
    reason = None; termination = None
    budget = store.get(job_id)["config"]["wall_budget_s"]
    try:
        while proc.poll() is None:
            job = store.get(job_id)
            if job["state"] in TERMINAL:
                # Publication happened within the worker's persisted hard deadline;
                # reap its final exit without invalidating committed results.
                try: proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    termination = tree.terminate(); proc.wait(timeout=10)
                break
            if job["cancel"]:
                reason = "Forecast cancelled during worker computation"; break
            remaining = budget - (time.monotonic() - started)
            if remaining <= 0:
                reason = "Forecast hard worker wall budget exhausted; prediction is UNKNOWN"; break
            try: proc.wait(timeout=min(.1, remaining))
            except subprocess.TimeoutExpired: pass
        if reason is not None:
            termination = tree.terminate(); proc.wait(timeout=10)
            store.event(job_id, {"type": "owned_worker_tree_termination", "reason": reason, **termination})
            _incomplete(store, job_id, reason, diagnostics=termination)
        elif store.get(job_id)["state"] not in TERMINAL:
            _incomplete(store, job_id, f"Forecast worker exited {proc.returncode} without complete publication")
        atomic_json(store.root / job_id / "worker_exit.json", {"exit_code": proc.returncode,
                    "walltime_s": time.monotonic() - started, "hard_wall_budget_s": budget,
                    "termination": termination, "reason": reason})
    except Exception as exc:
        if proc.poll() is None:
            try: termination = tree.terminate(); proc.wait(timeout=10)
            except Exception as stop_error: termination = {"error": str(stop_error)}
        _incomplete(store, job_id, "Forecast monitor failed: " + str(exc), diagnostics=termination)
    finally:
        tree.close()


def get_forecast_result(project: Path, job_id: str) -> dict:
    _identifier(job_id)
    store = forecast_store(project); job = store.get(job_id)
    if job["state"] != "succeeded":
        raise ValueError("Forecast result is not complete: " + job["state"])
    dest = store.root / job_id; manifest = _json(dest / "manifest.json")
    if not manifest.get("complete") or manifest.get("job_id") != job_id:
        raise ValueError("Forecast publication identity/completion mismatch")
    if manifest.get("input_hash") != job["input_hash"] or manifest.get("code_hash") != job["config"]["code_hash"]:
        raise ValueError("Forecast input/source identity mismatch")
    path = _inside(dest, "forecast.json")
    if sha256_file(path) != manifest.get("artifact_hashes", {}).get("forecast.json"):
        raise ValueError("Forecast artifact hash mismatch")
    result = _json(path)
    if (result.get("snapshot_id") != job["config"]["snapshot_id"]
            or result.get("query") != job["config"]["query"]
            or result.get("job_id") != job_id or result.get("source_run_id") != job["config"]["source_run_id"]):
        raise ValueError("Forecast snapshot/query/source identity mismatch")
    if result.get("input_hash") != job["input_hash"] or result.get("code_hash") != manifest["code_hash"]:
        raise ValueError("Forecast result input/code hash mismatch")
    return result
