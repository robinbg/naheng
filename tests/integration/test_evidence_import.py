"""Exporter-shaped structural fixtures, never evidence of an actual Lean build."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
import pytest
from naheng.packages.evidence_import import load_evidence


def manifest_fixture(tmp_path):
    root=tmp_path/"fixture-project";root.mkdir()
    source=root/"UnitFixture.lean";source.write_text("-- structural import fixture, not a Lean build\n",encoding="utf-8")
    log=root/"fixture-build.log";log.write_text("unit fixture only: no Lean execution or proof claim\n",encoding="utf-8")
    artifacts={path.relative_to(root).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in (source,log)}
    records=[]
    for target in ("UnitFixture.first","UnitFixture.second"):
        statement="theorem "+target+" (x : Int) : x = x"
        digest=hashlib.sha256(statement.encode()).hexdigest()
        records.append({"evidence_id":"unit.fixture."+target+"."+digest[:16],"status":"checked",
            "category":"formal_kernel","declaration":target,"statement_hash":digest,"statement":statement,
            "axioms":["propext","Classical.choice","Quot.sound"],"artifacts":artifacts,
            "scope":"Technical structural fixture; this is not a real checked Lean proof",
            "toolchain":"leanprover/lean4:v4.19.0"})
    manifest={"suite":"fixture","status":"checked","evidence":records}
    path=root/"fixture-manifest.json";path.write_text(json.dumps(manifest),encoding="utf-8")
    return root,path,manifest


def write(path,value):
    path.write_text(json.dumps(value),encoding="utf-8")


def test_import_preserves_each_declaration_hash_axiom_artifact_and_scope_without_authorization(tmp_path):
    root,path,manifest=manifest_fixture(tmp_path)
    imported=load_evidence(root,path)
    assert imported["records"]==manifest["evidence"]
    assert len(imported["records"])==2
    assert "runtime_authorizations" not in imported and "aggregate_eligible" not in imported
    manifest["evidence"][0]["scope"]="modified caller object"
    assert imported["records"][0]["scope"]!="modified caller object"


@pytest.mark.parametrize("mutation",["status","category","declaration","statement","hash","missing_axioms","untrusted_axiom","empty_artifacts","duplicate_identity"])
def test_invalid_exporter_shaped_record_is_rejected(tmp_path,mutation):
    root,path,manifest=manifest_fixture(tmp_path)
    record=manifest["evidence"][0]
    if mutation=="status": record["status"]="proposed"
    if mutation=="category": record["category"]="formal_extended_trust"
    if mutation=="declaration": record["declaration"]="UnitFixture.other"
    if mutation=="statement": record["statement"]+=" changed"
    if mutation=="hash": record["statement_hash"]="a"*64
    if mutation=="missing_axioms": record.pop("axioms")
    if mutation=="untrusted_axiom": record["axioms"].append("sorryAx")
    if mutation=="empty_artifacts": record["artifacts"]={}
    if mutation=="duplicate_identity": manifest["evidence"][1]["evidence_id"]=record["evidence_id"]
    write(path,manifest)
    with pytest.raises(ValueError):load_evidence(root,path)


def test_actual_artifact_byte_change_is_rejected_without_trusting_checked_status(tmp_path):
    root,path,_=manifest_fixture(tmp_path)
    (root/"UnitFixture.lean").write_text("changed bytes",encoding="utf-8")
    with pytest.raises(ValueError,match="Stale proof artifact"):load_evidence(root,path)


def test_distinct_artifacts_are_read_once_per_import_and_rechecked_on_the_next_call(tmp_path,monkeypatch):
    root,path,_=manifest_fixture(tmp_path)
    original_read=Path.read_bytes
    reads=[]
    def observed_read(target):
        reads.append(target)
        return original_read(target)
    monkeypatch.setattr(Path,"read_bytes",observed_read)
    load_evidence(root,path)
    assert reads.count(root/"UnitFixture.lean")==1
    assert reads.count(root/"fixture-build.log")==1
    (root/"UnitFixture.lean").write_text("changed after the previous import",encoding="utf-8")
    with pytest.raises(ValueError,match="Stale proof artifact"):load_evidence(root,path)
    assert reads.count(root/"UnitFixture.lean")==2


def test_conflicting_expected_hash_for_a_shared_artifact_is_still_rejected(tmp_path):
    root,path,manifest=manifest_fixture(tmp_path)
    manifest["evidence"][1]["artifacts"]=dict(manifest["evidence"][1]["artifacts"])
    manifest["evidence"][1]["artifacts"]["UnitFixture.lean"]="a"*64
    write(path,manifest)
    with pytest.raises(ValueError,match="Stale proof artifact"):load_evidence(root,path)


def test_outside_artifact_and_manifest_paths_are_rejected(tmp_path):
    root,path,manifest=manifest_fixture(tmp_path)
    outside=tmp_path/"outside.txt";outside.write_text("unit fixture",encoding="utf-8")
    manifest["evidence"][0]["artifacts"]={"../outside.txt":hashlib.sha256(outside.read_bytes()).hexdigest()}
    write(path,manifest)
    with pytest.raises(ValueError,match="controlled artifact"):load_evidence(root,path)
    with pytest.raises(ValueError,match="Uncontrolled evidence manifest"):load_evidence(root,outside)


def test_free_scope_and_self_reported_capability_are_not_runtime_permissions(tmp_path):
    root,path,manifest=manifest_fixture(tmp_path)
    for record in manifest["evidence"]:
        record.update(scope="T1 exact reduction and T3 safety for every model and parameter",certificate_type="output_error",applicability="applicable")
    write(path,manifest)
    imported=load_evidence(root,path)
    from naheng.risk.admission import check
    from naheng.domain.contracts import PosteriorSnapshot,Action
    snapshot=PosteriorSnapshot(snapshot_id="s",run_id="r",obs_until_s=0,
        state_names=["x1","x2","trapped_mol","reservoir_mol","temperature_K"],
        state_units=["1","1","mol","mol","K"],samples=[[.6,.6,0,.025,298]],weights=[1],mean={},quantiles={},ess=1)
    action=Action(action_id="a",snapshot_id="s",start_s=0,duration_s=60,current_A=.1)
    ref=imported["records"][0]["evidence_id"]
    package={"domain":{"temperature_K":[273,333],"max_current_A":.3,"channel_rates":[2,2]},
             "evidence_refs":[ref],"error_contracts":[{"target":"voltage_V","bound":0,"status":"checked","evidence_ref":ref}]}
    result=check(snapshot,action,package,mode="strict",formal_evidence=imported)
    assert result["decision"]=="unknown" and result["model_selected"]=="detailed"


@pytest.mark.parametrize('suffix', ['.{u_1}', '.{u_1, u_2}'])
def test_actual_lean_universe_printer_suffix_preserves_declaration_identity(tmp_path, suffix):
    root,path,manifest=manifest_fixture(tmp_path)
    row=manifest['evidence'][0]
    row['statement']='theorem '+row['declaration']+suffix+' : ∀ {α : Type u_1}, α → α'
    row['statement_hash']=hashlib.sha256(row['statement'].encode()).hexdigest()
    write(path,manifest)
    assert load_evidence(root,path)['records'][0]['statement']==row['statement']


@pytest.mark.parametrize('suffix', ['.other', '.{u_1}.other', '.{u_1}other', '.{u_1}axiom', '.{u_1;False}'])
def test_universe_suffix_does_not_accept_another_target_or_invalid_printer_syntax(tmp_path,suffix):
    root,path,manifest=manifest_fixture(tmp_path)
    row=manifest['evidence'][0]
    row['statement']='theorem '+row['declaration']+suffix+' : False'
    row['statement_hash']=hashlib.sha256(row['statement'].encode()).hexdigest()
    write(path,manifest)
    with pytest.raises(ValueError,match='another declaration'):load_evidence(root,path)
