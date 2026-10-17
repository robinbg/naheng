"""Frozen-worker binding tests using explicitly labelled STRUCTURAL fixtures.

No fixture is a Lean proof. These checks cover routing, coefficient checks,
source identity and withdrawal; actual Lean and actual worker acceptance remain
separate tasks owned by the integrator.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest
import yaml

from naheng.formal.runtime_binding import load_runtime_binding, revalidate_runtime_binding
from naheng.models.site_model import SiteModel
from naheng.packages.registry import ModelRegistry, _DERIVED, content_hash
from naheng.runtime.artifacts import atomic_json, code_hash
from naheng.runtime.freezing import freeze_source
from test_chemistry_binding import FILES, ROOT, sha, structural_fixture, write


def frozen_fixture(tmp_path):
    project, package, parameters, manifest_path, manifest = structural_fixture(tmp_path)
    package["parameters"] = asdict(parameters)
    package["package_hash"] = content_hash({key: value for key, value in package.items() if key not in _DERIVED})
    package.update(validation_status="executable", execution_binding="builtin_site_v1",
                   evidence_validity="unverified")
    snapshot, _ = freeze_source(project, tmp_path / "run")
    return project, snapshot, package, parameters, manifest_path, manifest


def load(value, manifest=True):
    project, snapshot, package, parameters, path, _ = value
    return load_runtime_binding(project, snapshot, package, parameters, path if manifest else None)


def reindex(snapshot):
    atomic_json(snapshot.parent / "source_index.json", {
        "code_hash": code_hash(snapshot),
        "files": {path.relative_to(snapshot).as_posix(): sha(path)
                  for path in snapshot.rglob("*") if path.is_file()}})


def test_structural_fixture_binds_exact_frozen_source_and_only_four_t0_refs(tmp_path):
    value = frozen_fixture(tmp_path)
    result = load(value)
    assert result.record["status"] == "PASS"
    assert result.record["snapshot"]["mode"] == "immutable_source_snapshot"
    assert result.record["snapshot"]["code_hash"] == code_hash(value[1])
    assert result.record["checked_manifest_sha256"] == sha(value[4])
    assert len(result.record["evidence_refs"]) == len(result.binding.declarations) == 4
    assert not result.record["grants_reduction"] and not result.record["grants_strict_safety"]
    assert not result.binding.grants_reduction and not result.binding.grants_strict_safety
    assert len(result.binding.channels) == 2
    assert json.loads(json.dumps(result.record))["status"] == "PASS"
    fresh = revalidate_runtime_binding(*value[:2], result, *value[2:4])
    assert fresh.record["status"] == "PASS"
    assert [event["phase"] for event in fresh.record["freshness_results"]] == ["load", "before_use"]


@pytest.mark.parametrize("proof", ["missing", "status_only", "stale_artifact", "stale_statement", "untrusted_axiom", "duplicate_declaration"])
def test_missing_or_invalid_proof_withdraws_t0_refs_but_preserves_detailed_fallback(tmp_path, proof):
    value = frozen_fixture(tmp_path)
    project, _, _, _, path, manifest = value
    if proof == "status_only": manifest.clear(); manifest["status"] = "checked"
    if proof == "stale_artifact": (project / "structural-fixture-build.log").write_text("changed", encoding="utf-8")
    if proof == "stale_statement": manifest["evidence"][0]["statement_hash"] = "a" * 64
    if proof == "untrusted_axiom": manifest["evidence"][0]["axioms"] = ["forged_conclusion"]
    if proof == "duplicate_declaration":
        duplicate = deepcopy(manifest["evidence"][0]); duplicate["evidence_id"] += ".duplicate"
        manifest["evidence"].append(duplicate)
    write(path, manifest)
    result = load(value, manifest=proof != "missing")
    assert result.record["status"] == "UNKNOWN" and result.record["withdrawn"]
    assert result.record["evidence_refs"] == [] and result.binding.declarations == ()
    assert result.record["empirical_detailed_fallback_allowed"]


@pytest.mark.parametrize("damage", ["missing_index", "source_bytes", "code_hash", "unindexed_source", "escaping_index"])
def test_snapshot_integrity_damage_withdraws_authority_without_authorizing_fallback(tmp_path, damage):
    value = frozen_fixture(tmp_path)
    snapshot = value[1]; path = snapshot.parent / "source_index.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    if damage == "missing_index": path.rename(path.with_suffix(".preserved"))
    if damage == "source_bytes": (snapshot / FILES[1]).write_text("changed", encoding="utf-8")
    if damage == "code_hash": index["code_hash"] = "a" * 64; write(path, index)
    if damage == "unindexed_source": (snapshot / "unindexed.txt").write_text("extra", encoding="utf-8")
    if damage == "escaping_index": index["files"]["../outside"] = "a" * 64; write(path, index)
    result = load(value)
    assert result.record["status"] == "UNKNOWN" and result.record["withdrawn"]
    assert result.record["evidence_refs"] == []
    assert not result.record["empirical_detailed_fallback_allowed"]


def test_current_worktree_executable_change_does_not_replace_frozen_worker_identity(tmp_path):
    value = frozen_fixture(tmp_path)
    (value[0] / FILES[1]).write_text("changed working source; frozen worker retained", encoding="utf-8")
    assert load(value).record["status"] == "PASS"


def test_freshly_hashed_proof_for_different_formal_bytes_does_not_bind_snapshot(tmp_path):
    value = frozen_fixture(tmp_path)
    project, _, _, _, path, manifest = value
    name = FILES[4]
    formal = project / name
    formal.write_text(formal.read_text(encoding="utf-8") + "\n-- different proved source\n", encoding="utf-8")
    for row in manifest["evidence"]: row["artifacts"][name] = sha(formal)
    write(path, manifest)
    result = load(value)
    assert result.record["status"] == "UNKNOWN" and not result.record["evidence_refs"]
    assert result.record["empirical_detailed_fallback_allowed"]


def test_exact_chemical_coefficient_mismatch_fails_even_with_fresh_snapshot_and_package_hashes(tmp_path):
    value = frozen_fixture(tmp_path)
    _, snapshot, package, _, _, _ = value
    path = snapshot / FILES[0]
    chemistry = yaml.safe_load(path.read_text(encoding="utf-8"))
    chemistry["reactions"][0]["stoichiometry"] = {
        name: coefficient * 2 for name, coefficient in chemistry["reactions"][0]["stoichiometry"].items()}
    path.write_text(yaml.safe_dump(chemistry), encoding="utf-8")
    package["binding_hashes"][FILES[0]] = sha(path)
    reindex(snapshot)
    result = load(value)
    assert result.record["status"] == "FAIL" and not result.record["evidence_refs"]
    assert not result.record["empirical_detailed_fallback_allowed"]


@pytest.mark.parametrize("damage", ["actual_parameters", "modified_package", "register_return_without_metadata"])
def test_actual_parameter_or_registered_identity_mismatch_fails(tmp_path, damage):
    value = list(frozen_fixture(tmp_path))
    if damage == "actual_parameters": value[3] = replace(value[3], side_rate_s_inv=(1e-7, 1e-7))
    if damage == "modified_package": value[2]["parameter_revision"] = "changed_without_registration"
    if damage == "register_return_without_metadata": value[2].pop("parameter_hash")
    result = load(value)
    assert result.record["status"] == "FAIL" and not result.record["evidence_refs"]
    assert not result.record["empirical_detailed_fallback_allowed"]


def test_before_use_changed_manifest_and_restored_proof_require_explicit_rebinding(tmp_path):
    value = frozen_fixture(tmp_path)
    previous = load(value)
    value[4].write_text(value[4].read_text(encoding="utf-8") + "\n", encoding="utf-8")
    withdrawn = revalidate_runtime_binding(*value[:2], previous, *value[2:4])
    assert withdrawn.record["status"] == "UNKNOWN" and not withdrawn.record["evidence_refs"]
    assert withdrawn.record["checked_manifest_sha256"] != previous.record["checked_manifest_sha256"]
    again = revalidate_runtime_binding(*value[:2], withdrawn, *value[2:4])
    assert again.record["status"] == "UNKNOWN" and len(again.record["freshness_results"]) == 3
    assert load(value).record["status"] == "PASS"


def test_before_use_consistently_registered_new_parameters_cannot_inherit_old_binding(tmp_path):
    value = frozen_fixture(tmp_path)
    previous = load(value)
    parameters = replace(value[3], side_rate_s_inv=(1e-7, 1e-7))
    package = deepcopy(value[2])
    package["parameters"] = asdict(parameters)
    package["parameter_hash"] = content_hash(asdict(parameters))
    package["package_hash"] = content_hash({key: item for key, item in package.items() if key not in _DERIVED})
    withdrawn = revalidate_runtime_binding(*value[:2], previous, package, parameters)
    assert withdrawn.record["status"] == "FAIL" and not withdrawn.record["evidence_refs"]
    assert load_runtime_binding(*value[:2], package, parameters, value[4]).record["status"] == "PASS"


def test_direct_actual_registry_call_reports_current_byte_scope_without_claiming_immutability():
    registry = ModelRegistry(ROOT)
    raw = json.loads((ROOT / "model_packages/research_base/package.json").read_text(encoding="utf-8"))
    registry.register(raw)
    result = load_runtime_binding(ROOT, ROOT, registry.packages[raw["package_id"]], SiteModel().params)
    assert result.record["status"] == "UNKNOWN"
    assert result.record["snapshot"]["mode"] == "working_project_direct"
    assert result.record["snapshot"]["source_index_sha256"] is None
    assert result.record["empirical_detailed_fallback_allowed"]
