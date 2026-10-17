"""Binding integration and exporter-shaped STRUCTURAL fixtures.

Fixture PASS checks routing/identity/chemistry validation, not a Lean proof.
Actual checked manifests and actual Run references are a separate acceptance.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest
import yaml

from naheng.domain.contracts import Action, PosteriorSnapshot
from naheng.formal.chemistry_binding import bind_chemistry, revalidate_binding
from naheng.models.site_model import SiteModel, SiteParameters
from naheng.packages.registry import ModelRegistry, content_hash
from naheng.risk.admission import check

ROOT = Path(__file__).resolve().parents[2]
FILES = ("configs/models/two_site_research.yaml", "src/naheng/models/site_model.py",
         "src/naheng/models/thermal.py", "src/naheng/models/degradation.py",
         "formal/Naheng/Chemistry/Species.lean", "formal/Naheng/Chemistry/Reaction.lean",
         "formal/Naheng/Chemistry/Balance.lean", "formal/lean-toolchain")
STATEMENTS = {
    "element_stoichiometry_balanced": "(element : Element) (reaction : Reaction) : (∑ species : Species, composition element species * stoichiometry species reaction) = 0",
    "charge_stoichiometry_balanced": "(reaction : Reaction) : (∑ species : Species, charge species * stoichiometry species reaction) = 0",
    "element_rate_from_ports": "(element : Element) (v : Reaction → ℝ) (b : PortFlux) : (∑ species : Species, composition element species * amountRate v b species) = ∑ species : Species, composition element species * b species",
    "charge_rate_from_ports": "(v : Reaction → ℝ) (b : PortFlux) : (∑ species : Species, charge species * amountRate v b species) = ∑ species : Species, charge species * b species",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def structural_fixture(tmp_path):
    """Copy controlled source bytes; fabricate only clearly named fixture records."""
    root = tmp_path / "structural-fixture-project"
    for name in FILES:
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    parameters = SiteParameters()
    package = json.loads((ROOT / "model_packages/research_base/package.json").read_text(encoding="utf-8"))
    # This constructed registered-package shape is a fixture, not Registry proof.
    package.update(package_hash=content_hash(package), parameter_hash=content_hash(asdict(parameters)),
                   binding_hashes={name: sha(root / name) for name in FILES[:4]})
    log = root / "structural-fixture-build.log"
    log.write_text("STRUCTURAL FIXTURE ONLY. Lean was not run. No proof claim.\n", encoding="utf-8")
    artifacts = {name: sha(root / name) for name in FILES[4:]}
    artifacts[log.name] = sha(log)
    records = []
    for name, formula in STATEMENTS.items():
        target = "Naheng.Chemistry." + name
        statement = "theorem " + target + " " + formula
        digest = hashlib.sha256(statement.encode()).hexdigest()
        records.append(dict(evidence_id="structural.fixture." + name + "." + digest[:16],
                            status="checked", category="formal_kernel", declaration=target,
                            statement=statement, statement_hash=digest,
                            axioms=["propext", "Classical.choice", "Quot.sound"], artifacts=deepcopy(artifacts),
                            scope="STRUCTURAL fixture; no Lean execution or proof claim",
                            toolchain=(root / "formal/lean-toolchain").read_text(encoding="utf-8").strip()))
    manifest = dict(status="checked", evidence=records)
    path = root / "structural-fixture-manifest.json"
    write(path, manifest)
    return root, package, parameters, path, manifest


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def edit_chemistry(root, package, edit):
    path = root / FILES[0]
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(value)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    package["binding_hashes"][FILES[0]] = sha(path)


def test_structural_binding_preserves_two_channels_exact_coefficients_and_four_declarations(tmp_path):
    root, package, parameters, path, manifest = structural_fixture(tmp_path)
    binding = bind_chemistry(root, package, parameters, path)
    assert binding.status == "PASS"
    assert len(binding.channels) == 2 and len(binding.declarations) == 4
    assert binding.channels[0].species != binding.channels[1].species
    assert {row[2] for row in binding.channels[0].coefficients} == {"-1", "1"}
    assert {ref.statement_hash for ref in binding.declarations} == {row["statement_hash"] for row in manifest["evidence"]}
    assert binding.identity.parameter_hash == content_hash(asdict(parameters))
    assert not binding.grants_reduction and not binding.grants_strict_safety
    assert revalidate_binding(root, binding, package, parameters).status == "PASS"
    assert json.loads(json.dumps(binding.to_dict()))["status"] == "PASS"


@pytest.mark.parametrize("kind", ["balanced_double_stoichiometry", "balanced_wrong_elements", "balanced_wrong_charge", "wrong_channel", "extra_species"])
def test_conserved_but_wrong_chemistry_does_not_match_formal_template(tmp_path, kind):
    root, package, parameters, path, _ = structural_fixture(tmp_path)
    def mutate(value):
        if kind == "balanced_double_stoichiometry":
            value["reactions"][0]["stoichiometry"] = {sp: 2 * n for sp, n in value["reactions"][0]["stoichiometry"].items()}
        if kind == "balanced_wrong_elements":
            for species in value["species"]:
                if "Na" in species["elements"]:
                    species["elements"]["Na"] = 2
        if kind == "balanced_wrong_charge":
            value["species"][0]["charge"] = 2
            value["species"][1]["charge"] = -2
        if kind == "wrong_channel":
            value["reactions"][0]["stoichiometry"] = {"Na_plus": -1, "electron": -1, "S2": -1, "NaS2": 1}
        if kind == "extra_species":
            value["species"].append(dict(name="unmodeled", elements={}, charge=0))
    edit_chemistry(root, package, mutate)
    binding = bind_chemistry(root, package, parameters, path)
    assert binding.status == "FAIL" and binding.declarations == ()


def test_missing_proof_keeps_unknown_even_when_exact_chemistry_matches(tmp_path):
    root, package, parameters, _, _ = structural_fixture(tmp_path)
    binding = bind_chemistry(root, package, parameters)
    assert binding.status == "UNKNOWN" and binding.checks[0].status == "PASS"
    assert not binding.declarations and not binding.grants_strict_safety


@pytest.mark.parametrize("mutation", ["chemistry_identity", "backend_identity", "source_identity", "parameter_hash", "stale_source"])
def test_model_parameter_and_source_mismatch_rejects_binding(tmp_path, mutation):
    root, package, parameters, path, _ = structural_fixture(tmp_path)
    if mutation == "chemistry_identity": package["chemistry_id"] = "real_sodium"
    if mutation == "backend_identity": package["dynamics_ast"]["model"] = "different_model"
    if mutation == "source_identity": parameters = replace(parameters, source_id="different-source")
    if mutation == "parameter_hash": parameters = replace(parameters, side_rate_s_inv=(1e-7, 1e-7))
    if mutation == "stale_source": (root / FILES[1]).write_text("changed source bytes", encoding="utf-8")
    assert bind_chemistry(root, package, parameters, path).status == "FAIL"


@pytest.mark.parametrize("mutation", ["wrong_scope", "stale_statement", "false_hypothesis", "unknown_status", "wrong_toolchain", "stale_artifact", "missing_source_link"])
def test_declaration_identity_hash_scope_and_artifact_binding_are_checked(tmp_path, mutation):
    root, package, parameters, path, manifest = structural_fixture(tmp_path)
    record = manifest["evidence"][0]
    if mutation == "wrong_scope":
        record["declaration"] = "Naheng.Chemistry.site_lower_boundary"
        record["statement"] = "theorem Naheng.Chemistry.site_lower_boundary : True"
        record["statement_hash"] = hashlib.sha256(record["statement"].encode()).hexdigest()
    if mutation == "stale_statement": record["statement_hash"] = "a" * 64
    if mutation == "false_hypothesis":
        record["statement"] = record["statement"].replace(" (element", " (h : False) (element", 1)
        record["statement_hash"] = hashlib.sha256(record["statement"].encode()).hexdigest()
    if mutation == "unknown_status": manifest["status"] = "blocked"
    if mutation == "wrong_toolchain": record["toolchain"] = "leanprover/lean4:v0.0.0"
    if mutation == "stale_artifact": (root / "structural-fixture-build.log").write_text("changed", encoding="utf-8")
    if mutation == "missing_source_link": record["artifacts"].pop(FILES[4])
    write(path, manifest)
    binding = bind_chemistry(root, package, parameters, path)
    assert binding.status == ("UNKNOWN" if mutation in {"wrong_scope", "unknown_status"} else "FAIL")
    assert not binding.declarations


def test_scope_text_cannot_grant_reduction_or_strict_safety(tmp_path):
    root, package, parameters, path, manifest = structural_fixture(tmp_path)
    for record in manifest["evidence"]:
        record.update(scope="T1/T3 all-model guarantee", grants_reduction=True, grants_strict_safety=True)
    write(path, manifest)
    binding = bind_chemistry(root, package, parameters, path)
    assert binding.status == "PASS"
    assert not binding.grants_reduction and not binding.grants_strict_safety


@pytest.mark.parametrize("mutation", ["integer_followed_by_expression", "weakened_formal_statement"])
def test_changed_formal_semantics_cannot_be_hidden_by_fresh_source_hashes(tmp_path, mutation):
    root, package, parameters, path, manifest = structural_fixture(tmp_path)
    name = FILES[4] if mutation == "integer_followed_by_expression" else FILES[6]
    source = root / name
    text = source.read_text(encoding="utf-8")
    if mutation == "integer_followed_by_expression":
        text = text.replace(".sodium, .sodiumIon => 1", ".sodium, .sodiumIon => 1 + 1")
    else:
        text = text.replace("theorem element_rate_from_ports (element : Element)",
                            "theorem element_rate_from_ports (element : Element) (h : False)")
    source.write_text(text, encoding="utf-8")
    for record in manifest["evidence"]:
        record["artifacts"][name] = sha(source)
    write(path, manifest)
    binding = bind_chemistry(root, package, parameters, path)
    assert binding.status == "FAIL" and not binding.declarations


@pytest.mark.parametrize("mutation", ["parameter", "revision", "package", "artifact", "manifest"])
def test_previously_bound_runtime_evidence_is_withdrawn_after_change(tmp_path, mutation):
    root, package, parameters, path, _ = structural_fixture(tmp_path)
    binding = bind_chemistry(root, package, parameters, path)
    assert binding.status == "PASS"
    if mutation == "parameter":
        parameters = replace(parameters, side_rate_s_inv=(1e-7, 1e-7))
        package["parameter_hash"] = content_hash(asdict(parameters))
    if mutation == "revision": package["parameter_revision"] = "v2"
    if mutation == "package": package["package_id"] = "different-package"
    if mutation == "artifact": (root / "structural-fixture-build.log").write_text("changed", encoding="utf-8")
    if mutation == "manifest": path.write_text("{}", encoding="utf-8")
    assert revalidate_binding(root, binding, package, parameters).status == "FAIL"


def test_normal_empirical_action_remains_useful_without_real_checked_lean_evidence():
    # Uses the actual Registry, actual SiteModel and numerical integration.
    registry = ModelRegistry(ROOT)
    raw = json.loads((ROOT / "model_packages/research_base/package.json").read_text(encoding="utf-8"))
    registry.register(raw)
    package = registry.packages[raw["package_id"]]
    model = SiteModel()
    binding = bind_chemistry(ROOT, package, model.params)
    assert binding.status == "UNKNOWN"
    state = model.initial_state()
    snapshot = PosteriorSnapshot(snapshot_id="binding-s", run_id="binding-r", obs_until_s=0,
        state_names=list(model.state_names), state_units=list(model.state_units), samples=[state.tolist()],
        weights=[1], mean={}, quantiles={}, ess=1)
    action = Action(action_id="binding-a", snapshot_id=snapshot.snapshot_id, start_s=0, duration_s=30, current_A=.1)
    assert check(snapshot, action, package, mode="empirical")["decision"] == "accept"
    assert check(snapshot, action, package, mode="strict")["decision"] == "unknown"
    integrated = model.integrate(state, .1, 30, 298.15)
    assert integrated.energy_J > 0
    assert integrated.state[0] != state[0] and abs(integrated.inventory_residual_mol) < 1e-8
