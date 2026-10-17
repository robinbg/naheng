from naheng.risk.admission import check
from naheng.domain.contracts import Action,PosteriorSnapshot
from copy import deepcopy
import json
from pathlib import Path
import pytest
def snap():
    return PosteriorSnapshot(snapshot_id="s",run_id="r",obs_until_s=0,state_names=["x1","x2","trapped_mol","reservoir_mol","temperature_K"],state_units=["1","1","mol","mol","K"],samples=[[.6,.6,0,.025,298]],weights=[1],mean={},quantiles={},ess=1)
def test_balance_proof_does_not_certify_safety_or_zero_current():
    package={"domain":{"temperature_K":[273,333],"max_current_A":.3,"channel_rates":[2,2]},"error_contracts":[{"bound":None}]}
    a=Action(action_id="a",snapshot_id="s",start_s=0,duration_s=60,current_A=0)
    result=check(snap(),a,package,mode="strict",formal_evidence={"status":"checked","evidence_id":"balance-only"})
    assert result["decision"]=="unknown"
def test_empirical_useful_action_and_domain_rejection():
    package={"domain":{"temperature_K":[273,333],"max_current_A":.3,"channel_rates":[2,4]},"error_contracts":[]}
    a=Action(action_id="a",snapshot_id="s",start_s=0,duration_s=60,current_A=.1)
    assert check(snap(),a,package)["decision"]=="accept"
    assert check(snap(),a,package,ambient_K=400)["decision"]=="reject"


def foundation_fixture(scope="Structural unit fixture only; no Lean build has occurred"):
    """A negative authorization fixture, never a registered proof artifact."""
    exports=json.loads((Path(__file__).resolve().parents[2]/"formal/exports.json").read_text(encoding="utf-8"))
    targets=exports["suites"]["foundation"]["targets"]
    return {"status":"checked","evidence_id":"unit-fixture-foundation-bundle",
        "records":[{"evidence_id":"unit-fixture-"+str(index),"declaration":target,
                    "status":"checked","category":"formal_kernel","scope":scope}
                   for index,target in enumerate(targets)]}


def package_fixture():
    return {"package_id":"fixture-package","parameter_revision":"fixture-v1","package_hash":"a"*64,
        "domain":{"temperature_K":[273,333],"max_current_A":.3,"channel_rates":[2,2]},
        "evidence_refs":[],"error_contracts":[]}


@pytest.mark.parametrize("scope",[
    "Instantaneous element/charge balance and site boundary lemmas",
    "T1 aggregate closure, T3 output errors, all parameter bindings and strict safety are authorized",
])
def test_foundation_targets_and_equal_rates_never_authorize_aggregate_from_free_scope(scope):
    evidence=foundation_fixture(scope)
    package=package_fixture();package["evidence_refs"]=[row["evidence_id"] for row in evidence["records"]]
    action=Action(action_id="a",snapshot_id="s",start_s=0,duration_s=60,current_A=.1)
    result=check(snap(),action,package,formal_evidence=evidence)
    assert len(evidence["records"])>=8
    assert result["decision"]=="accept" and result["model_selected"]=="detailed"
    assert result["evidence_refs"]==[]
    assert next(row for row in result["checks"] if row["name"]=="chemical_reduction")["status"]=="PASS"
    certificate=next(row for row in result["checks"] if row["name"]=="chemical_reduction_certificate")
    assert certificate["status"]=="UNKNOWN" and "T1" in certificate["reason"]


@pytest.mark.parametrize("case",["unregistered","not_imported","wrong_property","missing_binding","wrong_binding","self_reported_binding"])
def test_strict_does_not_promote_unresolved_or_untyped_output_contract(case):
    package=package_fixture();evidence=foundation_fixture()
    ref=evidence["records"][0]["evidence_id"]
    package["evidence_refs"]=[ref]
    contract={"target":"voltage_V","bound":0,"status":"checked","evidence_ref":ref,
              "comparison_reference":"real_cell","horizon_s":60}
    if case=="unregistered": package["evidence_refs"]=[]
    if case=="not_imported": contract["evidence_ref"]="absent";package["evidence_refs"]=["absent"]
    if case in {"missing_binding","wrong_binding","self_reported_binding"}:
        evidence["records"][0]["certificate_type"]="output_error"
    if case=="wrong_binding": evidence["records"][0]["model_binding"]={"package_hash":"f"*64,"parameter_revision":"other"}
    if case=="self_reported_binding":
        evidence["records"][0].update(certificate_type="output_error",applicability="applicable",
            model_binding={"package_hash":package["package_hash"],"parameter_revision":package["parameter_revision"]})
    package["error_contracts"]=[contract]
    action=Action(action_id="a",snapshot_id="s",start_s=0,duration_s=60,current_A=.1)
    result=check(snap(),action,package,mode="strict",formal_evidence=evidence)
    assert result["decision"]=="unknown" and result["model_selected"]=="detailed"
    assert result["evidence_refs"]==[]
    assert next(row for row in result["checks"] if row["name"]=="output_error_contract")["status"]=="UNKNOWN"
    assert "T3" in result["reason"]


@pytest.mark.parametrize("current",[-.1,0,.1])
def test_scope_fix_keeps_useful_empirical_actions_and_rejects_zero_current_outside_domain(current):
    action=Action(action_id="a",snapshot_id="s",start_s=0,duration_s=60,current_A=current)
    package=package_fixture()
    assert check(snap(),action,package,formal_evidence=foundation_fixture())["decision"]=="accept"
    assert check(snap(),action,package,ambient_K=400,formal_evidence=foundation_fixture())["decision"]=="reject"
    assert check(snap(),action,package,ambient_K=400,mode="strict")["decision"]=="reject"


def test_known_current_violation_remains_reject_even_when_strict_evidence_is_missing():
    action=Action(action_id="a",snapshot_id="s",start_s=0,duration_s=60,current_A=.4)
    result=check(snap(),action,package_fixture(),mode="strict")
    assert result["decision"]=="reject"
    assert next(row for row in result["checks"] if row["name"]=="current")["status"]=="FAIL"
    with pytest.raises(ValueError,match="mode"):
        check(snap(),action,package_fixture(),mode="self-certified")


@pytest.mark.parametrize("rates",[None,[2,2],[2,4]])
@pytest.mark.parametrize("evidence",[None,{"status":"checked"},{"status":"checked","records":None}])
def test_numerical_rate_condition_and_outer_tags_do_not_authorize_any_runtime_certificate(rates,evidence):
    package=package_fixture();package["domain"]["channel_rates"]=rates
    action=Action(action_id="a",snapshot_id="s",start_s=0,duration_s=60,current_A=.1)
    empirical=check(snap(),action,package,formal_evidence=evidence)
    assert empirical["decision"]=="accept" and empirical["model_selected"]=="detailed"
    assert check(snap(),action,package,mode="strict",formal_evidence=evidence)["decision"]=="unknown"


def test_missing_physical_state_returns_unknown_instead_of_empirical_accept():
    snapshot=PosteriorSnapshot(snapshot_id="s",run_id="r",obs_until_s=0,
        state_names=["x1","x2","temperature_K"],state_units=["1","1","K"],
        samples=[[.6,.6,298]],weights=[1],mean={},quantiles={},ess=1)
    action=Action(action_id="a",snapshot_id="s",start_s=0,duration_s=60,current_A=.1)
    for mode in ("empirical","strict"):
        assert check(snapshot,action,package_fixture(),mode=mode)["decision"]=="unknown"


def test_empirical_scope_fix_executes_actual_model_and_energy_ledger(tmp_path):
    from naheng.models.site_model import SiteModel
    from naheng.estimation.particle_filter import ParticleFilter
    from naheng.domain.contracts import Observation
    from naheng.economics.ledger import EnergyLedger
    model=SiteModel();state=model.initial_state()
    measured=model.observe(state,0)
    observation=Observation(run_id="synthetic-admission-integration",timestamp_s=0,current_A=0,
        voltage_V=measured["voltage_V"],temperature_K=measured["temperature_K"])
    snapshot=ParticleFilter(observation.run_id,model,seed=31,particles=8).update(observation,duration_s=0)
    action=Action(action_id="actual-executed-fixture",snapshot_id=snapshot.snapshot_id,start_s=0,duration_s=10,current_A=.1)
    decision=check(snapshot,action,package_fixture(),formal_evidence=foundation_fixture())
    assert decision["decision"]=="accept" and decision["model_selected"]=="detailed"
    executed=model.integrate(state,action.current_A,action.duration_s)
    assert executed.elapsed_s==10 and not executed.events and executed.energy_J>0
    assert abs(executed.inventory_residual_mol)<1e-12
    ledger=EnergyLedger(observation.run_id)
    ledger.append(action,execution_id=action.action_id,energy_J=executed.energy_J,
        thermal_energy_J=executed.thermal_management_energy_J,duration_s=executed.elapsed_s)
    summary=ledger.summary()
    assert summary["executions"]==1 and summary["energy_J"]==executed.energy_J and summary["net_cashflow"]>0
    sample={"scope":"Actual synthetic-model integration and ledger test; foundation metadata is an authorization-negative fixture, not a Lean proof or real battery revenue",
        "decision":decision,"current_A":action.current_A,"elapsed_s":executed.elapsed_s,
        "energy_J":executed.energy_J,"inventory_residual_mol":executed.inventory_residual_mol,"ledger":summary}
    (tmp_path/"actual_empirical_sample.json").write_text(json.dumps(sample,indent=2),encoding="utf-8")
