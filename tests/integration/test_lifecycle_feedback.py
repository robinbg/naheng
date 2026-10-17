from dataclasses import replace
import numpy as np
import pytest
from naheng.models.site_model import SiteModel,SiteParameters
from naheng.lifecycle.capacity_protocol import CapacityProtocol
from naheng.lifecycle.runner import CyclePolicy,CycleJumpBudget,LifecycleEconomics,cycle_jump_check,run_lifecycle
from naheng.simulation.module import ModuleModel


def test_jump_candidate_has_real_short_cycle_reference_and_error():
    model=SiteModel()
    result=cycle_jump_check(model,model.initial_state(),3,CyclePolicy(phase_duration_s=10))
    assert result["reference"]["completed_cycles"]==3
    assert len(result["reference"]["phases"])==6
    assert result["normalized_max_error"]>=0
    assert result["execution_mode"]=="exact_reference"
    assert result["speedup_claim"] is False


def test_lifecycle_protocol_feedback_replacement_and_policy_replanning():
    model=SiteModel(replace(SiteParameters(),side_rate_s_inv=(.0003,.0004),accelerated_synthetic=True))
    contexts=[]
    def replan(context):
        contexts.append(context)
        return CyclePolicy(policy_id=f"revision-{len(contexts)}",phase_duration_s=20)
    result=run_lifecycle(model,cycles=3,protocol=CapacityProtocol(retirement_ratio=.995),
                         policy_provider=replan,maximum_replacements=1)
    assert result["accelerated_synthetic"] is True
    assert result["replacement_count"]==1
    assert result["maintenance"][0]["discarded_inventory_mol"]>0
    assert any(context["replacement_count"]==1 for context in contexts)
    assert len({phase["policy_id"] for phase in result["phases"]})>1
    assert [phase["cycle"] for phase in result["phases"]]==[0,0,1,1]
    assert [phase["start_s"] for phase in result["phases"]]==[0,20,40,60]
    assert result["electrical_energy_J"]==pytest.approx(sum(phase["energy_J"] for phase in result["phases"]))
    assert all(row["cells"][0]["protocol"]["protocol_id"]=="synthetic_capacity_v1" for row in result["trace"])
    assert result["retirement_detection"]=="protocol_checkpoints"


def test_missing_capacity_keeps_lifecycle_unknown():
    result=run_lifecycle(cycles=2,protocol=CapacityProtocol(maximum_duration_s=1))
    assert result["status"]=="unknown_capacity"
    assert result["completed_cycles"]==0
    assert result["retirement_interval_s"] is None


def test_actual_macro_jump_has_fine_cycle_comparison_and_separate_projected_ledger():
    model=SiteModel()
    policy=lambda context:CyclePolicy(phase_duration_s=2,hold_cycles=6)
    exact=run_lifecycle(model,cycles=12,policy_provider=policy)
    jumped=run_lifecycle(model,cycles=12,policy_provider=policy,jump_check_cycles=6)
    assert exact["completed_cycles"]==jumped["completed_cycles"]==12
    assert jumped["numerical"]["accepted_jumps"]>=2
    assert jumped["numerical"]["fine_cycles_avoided"]>=3
    assert any(phase["cycle_count"]>1 and phase["execution_mode"]=="cycle_map_jump" for phase in jumped["phases"])
    assert np.all(np.abs(np.array(jumped["final_state"])-exact["final_state"])<=CycleJumpBudget().state_limits())
    assert abs(jumped["electrical_energy_J"]-exact["electrical_energy_J"])<=CycleJumpBudget().electrical_energy_abs_J
    assert jumped["macro_projected_ledger"] and jumped["numerical"]["strict_error_certificate"] is False
    assert jumped["economics"]["terminal_probe_energy_in_operating_sales"] is False
    assert jumped["economics"]["valuation_is_realized_revenue"] is False
    assert sum(row["sales"] for row in jumped["macro_projected_ledger"])==pytest.approx(jumped["economics"]["macro_projected_totals"]["sales"])


def test_zero_error_budget_falls_back_without_fake_macro_cycles():
    budget=CycleJumpBudget(occupancy_abs=0,sodium_abs_mol=0,temperature_abs_K=0,electrical_energy_abs_J=0)
    result=run_lifecycle(cycles=4,policy_provider=lambda c:CyclePolicy(phase_duration_s=2,hold_cycles=4),jump_check_cycles=4,jump_budget=budget)
    assert result["completed_cycles"]==4
    assert result["numerical"]["accepted_jumps"]==0
    assert not result["macro_projected_ledger"]
    assert any(r.get("reason")=="estimated_cumulative_error_budget" for r in result["jump_checks"])
    assert len(result["exact_phase_ledger"])==8


def test_callback_policy_hold_and_reoptimization_changes_actual_commands():
    calls=[]
    def reopt(context):
        calls.append(context)
        magnitude=.2 if context["cycle"]<6 else .1
        return CyclePolicy(policy_id=f"reopt-{context['cycle']}",discharge_A=magnitude,charge_A=-magnitude,phase_duration_s=2,hold_cycles=6)
    result=run_lifecycle(cycles=12,policy_provider=reopt,jump_check_cycles=6)
    assert [c["cycle"] for c in calls]==[0,6]
    assert {p["current_A"] for p in result["phases"]}=={.2,-.2,.1,-.1}
    assert all("soh" in c and "cell_age_s" in c for c in calls)


def test_replacement_age_salvage_and_terminal_asset_do_not_double_count_energy():
    model=SiteModel(replace(SiteParameters(),side_rate_s_inv=(.0003,.0004),accelerated_synthetic=True))
    accounting=LifecycleEconomics(replacement_cost_per_cell=50,salvage_fraction_of_cost_per_soh=.2)
    result=run_lifecycle(model,cycles=3,protocol=CapacityProtocol(retirement_ratio=.995),
                         policy_provider=lambda c:CyclePolicy(phase_duration_s=20),maximum_replacements=1,economics=accounting)
    maintenance=result["maintenance"][0]
    assert maintenance["replacement_cost"]==50
    assert maintenance["salvage_value"]==pytest.approx(50*.2*maintenance["retired_soh"])
    assert result["retirement_records"][0]["birth_time_s"]==0
    assert result["retirement_records"][-1]["birth_time_s"]==maintenance["time_s"]
    econ=result["economics"]
    expected=econ["exact_phase_totals"]["net_cashflow"]+econ["macro_projected_totals"]["net_cashflow"]+econ["maintenance_net_cashflow"]+econ["stored_energy_value_adjustment"]+econ["final_asset_residual"]-econ["initial_asset_residual"]
    assert econ["conditional_comparison_value"]==pytest.approx(expected)
    assert econ["terminal_probe_energy_in_operating_sales"] is False


def test_heterogeneous_4s_lifecycle_jump_compares_with_full_cycles():
    cells=(SiteModel(replace(SiteParameters(),site_capacity_mol=(.010,.006))),SiteModel(),SiteModel(replace(SiteParameters(),rate_s_inv=(.0012,.0008))),SiteModel())
    module=ModuleModel(cells)
    initial=module.initial_state(soc=[.52,.62,.59,.65])
    policy=lambda c:CyclePolicy(phase_duration_s=2,hold_cycles=6)
    reference=run_lifecycle(module,initial,cycles=12,policy_provider=policy)
    macro=run_lifecycle(module,initial,cycles=12,policy_provider=policy,jump_check_cycles=6)
    assert macro["topology"]=="4s" and macro["completed_cycles"]==reference["completed_cycles"]==12
    assert macro["numerical"]["fine_cycles_avoided"]>0
    assert np.all(np.abs(np.asarray(macro["final_state"])-reference["final_state"])<=CycleJumpBudget().state_limits())
    assert abs(macro["electrical_energy_J"]-reference["electrical_energy_J"])<=CycleJumpBudget().electrical_energy_abs_J
    assert max(abs(r) for item in macro["jump_checks"] if item.get("accepted") for r in item["inventory_residual_mol"])<1e-10


def test_module_replacement_is_local_and_domain_conflict_is_unknown():
    module=ModuleModel()
    initial=module.initial_state()
    initial[0,2]=.004
    initial[0,3]-=.004  # explicit aged synthetic fixture, preserves sodium inventory
    result=run_lifecycle(module,initial,cycles=1,protocol=CapacityProtocol(retirement_ratio=.9),maximum_replacements=1,
                         policy_provider=lambda c:CyclePolicy(phase_duration_s=2))
    assert result["replacement_count"]==1 and result["maintenance"][0]["cell_id"]=="cell-1"
    assert len(result["final_state"])==4
    limited=SiteModel(replace(SiteParameters(),voltage_min_V=3.0))
    unknown=run_lifecycle(limited,cycles=1,protocol=CapacityProtocol(cutoff_voltage_V=2.8))
    assert unknown["status"]=="unknown_capacity" and unknown["completed_cycles"]==0
    assert unknown["trace"][0]["cells"][0]["protocol"]["reason"]=="protocol_cutoff_below_declared_cell_domain"


def test_local_replacement_retains_other_cells_accumulated_jump_error():
    cells=(SiteModel(replace(SiteParameters(),side_rate_s_inv=(.003,.003),accelerated_synthetic=True)),SiteModel(),SiteModel(),SiteModel())
    module=ModuleModel(cells)
    contexts=[]
    def policy(context):
        contexts.append(context)
        return CyclePolicy(phase_duration_s=2,hold_cycles=6)
    # This accelerated fixture needs an explicitly larger mol budget to exercise
    # the post-jump replacement path; default strict budgets correctly reject it.
    result=run_lifecycle(module,cycles=14,policy_provider=policy,protocol=CapacityProtocol(retirement_ratio=.955),maximum_replacements=1,
                         jump_check_cycles=6,jump_budget=CycleJumpBudget(occupancy_abs=.03,sodium_abs_mol=1e-5))
    assert result["maintenance"] and result["maintenance"][0]["cell_id"]=="cell-1"
    replacement_index=next(i for i,context in enumerate(contexts) if context["replacement_count"]==1)
    before=contexts[replacement_index-1]
    after=contexts[replacement_index]
    assert np.any(np.asarray(before["numerical_state_error_estimate"])[1:]>0)
    assert np.array_equal(np.asarray(after["numerical_state_error_estimate"])[1:],np.asarray(before["numerical_state_error_estimate"])[1:])
    assert np.all(np.asarray(after["numerical_state_error_estimate"])[0]==0)
