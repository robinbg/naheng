"""Immutable local diagnostic analysis; no assimilation or cell safety claim."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from naheng.domain.contracts import PosteriorSnapshot
from naheng.runtime.artifacts import atomic_json, code_hash, sha256_file
from .ica import ICATrace, ICAQualityPolicy, ICAResult, evaluate_ica
from .impedance import ImpedanceInput, evaluate_impedance
from .identifiability import (DiagnosticOption, LocalJacobian, LocalRankPolicy,
                             IdentifiabilityResult, diagnose_identifiability)


class DiagnosticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal[1] = 1
    analysis_id: str = Field(min_length=1, max_length=128)
    ica_trace: ICATrace | None = None
    ica_policy: ICAQualityPolicy | None = None
    impedance: ImpedanceInput | None = None
    snapshot: PosteriorSnapshot | None = None
    linearization: LocalJacobian | None = None
    diagnostic_options: tuple[DiagnosticOption, ...] = Field(default=(), max_length=64)
    diagnostic_budget_s: float = Field(default=0.0, ge=0)
    rank_policy: LocalRankPolicy | None = None

    @model_validator(mode="after")
    def owned_inputs(self):
        if self.ica_policy is not None and self.ica_trace is None:
            raise ValueError("ICA policy requires a trace")
        if self.snapshot is None and (self.linearization is not None or self.diagnostic_options):
            raise ValueError("Local derivatives and options require their posterior snapshot")
        return self


def analyze_diagnostics(request: DiagnosticRequest | dict) -> dict:
    """Each component retains its own source; their data are not merged or fitted."""
    request = DiagnosticRequest.model_validate(request)
    ica = (evaluate_ica(request.ica_trace, request.ica_policy)
           if request.ica_trace is not None else
           ICAResult(status="UNKNOWN", reasons=("ica_trace_not_provided",)))
    impedance = evaluate_impedance(request.impedance)
    local = (diagnose_identifiability(request.snapshot, request.linearization,
                                     request.diagnostic_options,
                                     request.diagnostic_budget_s, request.rank_policy)
             if request.snapshot is not None else
             IdentifiabilityResult(status="UNKNOWN", reasons=("posterior_snapshot_not_provided",)))
    components = {"ica": ica.model_dump(mode="json"),
                  "impedance": impedance.model_dump(mode="json"),
                  "identifiability": local.model_dump(mode="json")}
    # UNKNOWN is a completed availability check, never evidence of a measurement.
    return {"schema_version": 1, "analysis_id": request.analysis_id,
            "completion": "analysis_completed",
            "exit_code": 1 if any(v["status"] == "FAIL" for v in components.values()) else 0,
            "components": components, "posterior_updated": False,
            "source_authenticity": "Input source references are declarations; verify their provenance separately",
            "independent_experiment": False,
            "scope": "Quality and local numerical diagnostics of supplied observations only; no fit, global identifiability, formal or risk certificate"}


def run_diagnostics(root: Path, input_path: Path, output_path: Path) -> dict:
    """Save the exact request and computed result in a new artifact directory."""
    root, input_path = Path(root).resolve(), Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    if not output_path.is_relative_to(root / "artifacts") or output_path == root / "artifacts":
        raise ValueError("Diagnostic output must be a new directory under project artifacts")
    if input_path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Diagnostic JSON exceeds 8 MiB input budget")
    body = input_path.read_bytes()
    if len(body) > 8 * 1024 * 1024:
        raise ValueError("Diagnostic JSON exceeds 8 MiB input budget")
    digest = hashlib.sha256(body).hexdigest()
    request = DiagnosticRequest.model_validate_json(body)
    source_hash = code_hash(root)
    started = time.monotonic()
    result = analyze_diagnostics(request)
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != digest or code_hash(root) != source_hash:
        raise ValueError("Input or implementation changed during diagnostic analysis")
    output_path.mkdir(parents=True, exist_ok=False)
    (output_path / "input.json").write_bytes(body)
    atomic_json(output_path / "result.json", result)
    manifest = {"schema_version": 1, "complete": True,
                "analysis_id": request.analysis_id,
                "utc": datetime.now(timezone.utc).isoformat(),
                "wall_s": time.monotonic() - started,
                "code_hash": source_hash, "input_sha256": digest,
                "result_sha256": sha256_file(output_path / "result.json"),
                "input_path": str(input_path),
                "artifact_index": {"input": "input.json", "result": "result.json"},
                "algorithm_hashes": {name: sha256_file(root / "src/naheng/estimation" / name)
                                     for name in ("ica.py", "impedance.py", "identifiability.py", "diagnostic_session.py")},
                "exit_code": result["exit_code"], "posterior_updated": False,
                "independent_experiment": False, "scope": result["scope"]}
    atomic_json(output_path / "manifest.json", manifest)
    return {"analysis_id": request.analysis_id, "exit_code": result["exit_code"],
            "artifact_dir": str(output_path), "manifest": str(output_path / "manifest.json"),
            "availability": {key: value["status"] for key, value in result["components"].items()},
            "scope": result["scope"]}
