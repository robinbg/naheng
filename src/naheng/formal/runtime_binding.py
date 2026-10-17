"""Bind imported T0 declarations to the source and parameters actually executed.

This adapter checks provenance and exact coefficient correspondence. Its PASS
does not extend the declaration's chemical bookkeeping scope to reduction,
output errors, physical-cell safety, or independently validated experiments.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Mapping

from naheng.formal.chemistry_binding import (
    BindingCheck, ChemistryBinding, DeclarationReference, _DECLARATIONS,
    _FORMAL_FILES, _statement_scope, bind_chemistry,
)
from naheng.models.site_model import SiteParameters
from naheng.packages.evidence_import import load_evidence
from naheng.packages.registry import _DERIVED, content_hash
from naheng.runtime.artifacts import code_hash, iter_source_files

_SHA = re.compile(r"[0-9a-f]{64}")
_ERRORS = (ValueError, TypeError, KeyError, OSError)


@dataclass(frozen=True)
class RuntimeBindingResult:
    record: dict
    binding: ChemistryBinding | None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, name: str) -> Path:
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
            or PurePosixPath(name).as_posix() != name):
        raise ValueError("Noncanonical controlled source/artifact path")
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Controlled source/artifact is missing or escaped: {name}")
    return path


def _snapshot(root: Path, project: Path) -> dict:
    if not root.is_dir():
        raise ValueError("Execution source directory is missing")
    if root == project:
        return {"mode": "working_project_direct", "code_hash": code_hash(root),
                "source_index_sha256": None,
                "scope": "Current controlled source bytes; no immutable snapshot claim"}
    index_path = root.parent / "source_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(index, dict) or not _SHA.fullmatch(str(index.get("code_hash", ""))):
        raise ValueError("Immutable snapshot code hash is missing or malformed")
    expected = index.get("files")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("Immutable snapshot file index is missing")
    contents = {}  # Exact bytes retained only within this full verification call.
    for name, digest in expected.items():
        if not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise ValueError("Immutable snapshot source hash is malformed")
        data = _file(root, name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"Immutable snapshot bytes differ from source_index: {name}")
        contents[name] = data
    present = set()
    for directory, children, files in os.walk(root):
        children[:] = [name for name in children if name not in {".lake", "__pycache__"}]
        present.update((Path(directory) / name).relative_to(root).as_posix() for name in files)
    if present != set(expected):
        raise ValueError("Immutable snapshot has missing or unindexed source files")
    aggregate = hashlib.sha256()
    for path in iter_source_files(root):
        name = path.relative_to(root).as_posix()
        aggregate.update(name.encode())
        aggregate.update(contents[name])
    actual = aggregate.hexdigest()
    if actual != index["code_hash"]:
        raise ValueError("Immutable snapshot code_hash differs from indexed code_hash")
    return {"mode": "immutable_source_snapshot", "code_hash": actual,
            "source_index_sha256": _sha(index_path),
            "scope": "Every indexed source byte and aggregate code hash verified"}


def _package(package: Mapping) -> None:
    if not isinstance(package, Mapping):
        raise ValueError("Full registered model-package metadata required")
    if (package.get("validation_status") != "executable"
            or package.get("execution_binding") != "builtin_site_v1"):
        raise ValueError("Actual registered executable SiteModel metadata required")
    if package.get("evidence_validity") == "stale":
        raise ValueError("Registered package dependencies are stale")
    payload = {key: value for key, value in package.items() if key not in _DERIVED}
    if package.get("package_hash") != content_hash(payload):
        raise ValueError("Registered package contents changed without re-registration")


def _event(status: str, reason: str, phase: str) -> dict:
    return {"phase": phase, "status": status, "reason": reason,
            "checked_at_utc": datetime.now(timezone.utc).isoformat()}


def _finish(record: dict, status: str, reason: str, binding: ChemistryBinding | None,
            *, fallback: bool, phase: str = "load") -> RuntimeBindingResult:
    record.update(status=status, reason=reason, withdrawn=status != "PASS",
                  empirical_detailed_fallback_allowed=fallback,
                  evidence_refs=([ref.evidence_id for ref in binding.declarations]
                                 if status == "PASS" and binding is not None else []),
                  grants_reduction=False, grants_strict_safety=False)
    record["freshness_results"] = [_event(status, reason, phase)]
    if status != "PASS" and binding is not None:
        binding = replace(binding, status=status, declarations=(), proof_artifact_hashes=())
    return RuntimeBindingResult(record, binding)


def load_runtime_binding(project: Path, source_root: Path, registered_package: Mapping,
                         parameters: SiteParameters,
                         checked_manifest: Path | None = None) -> RuntimeBindingResult:
    """Return scoped authority plus a persistable result, including withdrawal.

    A worker snapshot requires its complete source_index and code_hash. Direct
    project calls verify current bytes and explicitly make no immutable-source
    claim. Missing or stale proof is UNKNOWN; an invalid actual package,
    parameter identity, or exact chemical coefficient mapping is FAIL.
    """
    project, source_root = Path(project).resolve(), Path(source_root).resolve()
    record = {"schema_version": "1.0", "project": str(project),
              "source_root": str(source_root), "snapshot": None,
              "checked_manifest": None, "checked_manifest_sha256": None,
              "checks": [], "proof_artifact_hashes": {},
              "scope": "T0 declared synthetic stoichiometry and instantaneous open-port bookkeeping only"}
    try:
        record["snapshot"] = _snapshot(source_root, project)
    except _ERRORS as error:
        return _finish(record, "UNKNOWN", str(error), None, fallback=False)
    try:
        _package(registered_package)
        template = bind_chemistry(source_root, registered_package, parameters)
    except _ERRORS as error:
        return _finish(record, "FAIL", str(error), None, fallback=False)
    record["checks"] = [asdict(item) for item in template.checks]
    record["identity"] = asdict(template.identity) if template.identity is not None else None
    if template.status == "FAIL":
        return _finish(record, "FAIL", template.checks[-1].reason, template, fallback=False)
    if checked_manifest is None:
        return _finish(record, "UNKNOWN", "No checked T0 declaration manifest; proof authority withdrawn",
                       template, fallback=True)
    manifest_path = Path(checked_manifest).resolve()
    try:
        if not manifest_path.is_relative_to(project):
            raise ValueError("Checked manifest is outside the controlled project")
        record["checked_manifest"] = manifest_path.relative_to(project).as_posix()
        record["checked_manifest_sha256"] = _sha(manifest_path)
        imported = load_evidence(project, manifest_path)
        rows = {}
        for row in imported["records"]:
            if row["declaration"] in _DECLARATIONS:
                if row["declaration"] in rows:
                    raise ValueError("Duplicate required T0 declaration")
                rows[row["declaration"]] = row
        if set(rows) != set(_DECLARATIONS):
            raise ValueError("Required individual T0 declarations are absent; other scopes cannot substitute")
        artifacts, references = {}, []
        toolchain = _file(source_root, "formal/lean-toolchain").read_text(encoding="utf-8").strip()
        for target in _DECLARATIONS:
            row = rows[target]
            if row.get("toolchain") != toolchain:
                raise ValueError("Proof toolchain differs from the executed source lock")
            _statement_scope(source_root, target, row["statement"])
            if not set(_FORMAL_FILES).issubset(row["artifacts"]):
                raise ValueError("Proof does not bind the required formal chemistry sources")
            for name, digest in row["artifacts"].items():
                if name in artifacts and artifacts[name] != digest:
                    raise ValueError("T0 declaration proof artifacts have conflicting identities")
                # All formal source/lock artifacts are part of the frozen source.
                if name not in artifacts and name.startswith("formal/") and _sha(_file(source_root, name)) != digest:
                    raise ValueError(f"Proof/formal source bytes differ from executed snapshot: {name}")
                artifacts[name] = digest
            references.append(DeclarationReference(row["evidence_id"], target, row["statement_hash"]))
        artifacts[record["checked_manifest"]] = record["checked_manifest_sha256"]
        record["proof_artifact_hashes"] = artifacts
        checks = tuple(item for item in template.checks if item.name != "foundation_declarations") + (
            BindingCheck("foundation_declarations", "PASS", "Four individual T0 declarations match executed formal source bytes and audited project artifacts"),)
        binding = replace(template, status="PASS", checks=checks, declarations=tuple(references),
                          proof_artifact_hashes=tuple(sorted(artifacts.items())))
        record["checks"] = [asdict(item) for item in checks]
    except _ERRORS as error:
        record["checks"].append(asdict(BindingCheck("runtime_proof_import", "UNKNOWN", str(error))))
        return _finish(record, "UNKNOWN", str(error) + "; proof authority withdrawn",
                       template, fallback=True)
    return _finish(record, "PASS", "T0 bookkeeping authority is bound to actual source, parameters and imported declarations",
                   binding, fallback=False)


def revalidate_runtime_binding(project: Path, source_root: Path, previous: RuntimeBindingResult,
                               registered_package: Mapping,
                               parameters: SiteParameters) -> RuntimeBindingResult:
    """Recheck before use; changed identity or proof cannot inherit old refs."""
    old = previous.record
    name = old.get("checked_manifest")
    manifest = Path(project) / name if isinstance(name, str) else None
    current = load_runtime_binding(project, source_root, registered_package, parameters, manifest)
    record = current.record
    if old.get("status") != "PASS" and record["status"] == "PASS":
        current = _finish(record, "UNKNOWN", "Previously withdrawn authority requires an explicit new binding",
                          current.binding, fallback=True, phase="before_use")
    elif old.get("status") == "PASS" and record["status"] == "PASS":
        if record.get("identity") != old.get("identity"):
            current = _finish(record, "FAIL", "Runtime package or parameter identity changed since binding",
                              current.binding, fallback=False, phase="before_use")
        elif record.get("snapshot") != old.get("snapshot"):
            current = _finish(record, "UNKNOWN", "Execution source identity changed since binding; authority withdrawn",
                              current.binding, fallback=False, phase="before_use")
        elif record.get("checked_manifest_sha256") != old.get("checked_manifest_sha256"):
            current = _finish(record, "UNKNOWN", "Checked manifest bytes changed since binding; authority withdrawn",
                              current.binding, fallback=True, phase="before_use")
    latest = _event(current.record["status"], current.record["reason"], "before_use")
    current.record["freshness_results"] = list(old.get("freshness_results", [])) + [latest]
    return current
