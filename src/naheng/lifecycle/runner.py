"""Synthetic lifecycle feedback and bounded, empirically checked cycle maps.

Macro states/energy are numerical approximations with explicit error estimates,
not certified reality bounds. Short-cycle calibration, periodic reference
audits and exact fallback are distinct from operating executions.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import math
import time
from typing import Callable
import numpy as np

from naheng.models.site_model import SiteModel
from .capacity_protocol import CapacityProtocol, protocol_capacity


@dataclass(frozen=True)
class CyclePolicy:
    policy_id: str = "synthetic-cycle-v1"
    discharge_A: float = .2
    charge_A: float = -.2
    phase_duration_s: float = 30
    thermal_W: float = 0
    hold_cycles: int = 1

    def __post_init__(self):
        if not all(math.isfinite(x) for x in (self.discharge_A,self.charge_A,self.phase_duration_s,self.thermal_W)):
            raise ValueError("cycle policy values must be finite")
        if self.discharge_A <= 0 or self.charge_A >= 0 or self.phase_duration_s <= 0:
            raise ValueError("cycle requires positive discharge, negative charge and positive duration")
        if type(self.hold_cycles) is not int or not 1 <= self.hold_cycles <= 20:
            raise ValueError("policy hold window must contain 1..20 cycles")


@dataclass(frozen=True)
class CycleJumpBudget:
    occupancy_abs: float = 1e-4
    sodium_abs_mol: float = 2e-8
    temperature_abs_K: float = .001
    electrical_energy_abs_J: float = .02
    safety_factor: float = 4
    audit_every_jumps: int = 2
    retirement_margin: float = .01

    def __post_init__(self):
        values=(self.occupancy_abs,self.sodium_abs_mol,self.temperature_abs_K,self.electrical_energy_abs_J,self.safety_factor,self.retirement_margin)
        if not all(math.isfinite(x) and x>=0 for x in values) or self.safety_factor<1 or type(self.audit_every_jumps) is not int or self.audit_every_jumps<1:
            raise ValueError("jump budget must be finite, nonnegative and have a valid audit interval")

    def state_limits(self):return np.array([self.occupancy_abs,self.occupancy_abs,self.sodium_abs_mol,self.sodium_abs_mol,self.temperature_abs_K])


@dataclass(frozen=True)
class LifecycleEconomics:
    buy_price_per_kWh: float = .15
    sell_price_per_kWh: float = .30
    replacement_cost_per_cell: float = 100
    salvage_fraction_of_cost_per_soh: float = .10
    stored_energy_value_per_kWh: float = .15
    source_id: str = "synthetic-lifecycle-accounting-v1"

    def __post_init__(self):
        values=(self.buy_price_per_kWh,self.sell_price_per_kWh,self.replacement_cost_per_cell,self.salvage_fraction_of_cost_per_soh,self.stored_energy_value_per_kWh)
        if not self.source_id or not all(math.isfinite(x) and x>=0 for x in values) or self.salvage_fraction_of_cost_per_soh>1:
            raise ValueError("lifecycle tariffs and residual assumptions require finite synthetic source parameters")


def _cycles(model,state,count,policy,ambient_K):
    state = np.asarray(state,dtype=float).copy()
    phase_records,states,elapsed,energy,thermal = [],[],0.0,0.0,0.0
    completed = 0
    for cycle in range(count):
        for phase,current in (("discharge",policy.discharge_A),("charge",policy.charge_A)):
            result = model.integrate(state,current,policy.phase_duration_s,ambient_K=ambient_K,thermal_W=policy.thermal_W)
            state = result.state.copy()
            phase_records.append({"cycle":cycle,"phase":phase,"policy_id":policy.policy_id,"current_A":current,
                                  "start_s":elapsed,
                                  "state_after":state.tolist(),"thermal_electric_energy_J":result.thermal_management_energy_J,
                                  "cycle_count":1,"execution_mode":"exact_integration",
                                  "elapsed_s":result.elapsed_s,"energy_J":result.energy_J,"events":result.events,
                                  "inventory_residual_mol":result.inventory_residual_mol})
            elapsed += result.elapsed_s
            energy += result.energy_J
            thermal += result.thermal_management_energy_J
            if result.events:
                return {"state":state,"elapsed_s":elapsed,"energy_J":energy,"thermal_management_energy_J":thermal,
                        "completed_cycles":completed,"phases":phase_records,"cycle_states":states,"status":"stopped_constraint"}
        completed += 1
        states.append(state.copy())
    return {"state":state,"elapsed_s":elapsed,"energy_J":energy,"thermal_management_energy_J":thermal,
            "completed_cycles":completed,"phases":phase_records,"cycle_states":states,"status":"completed"}


def cycle_jump_check(model,state,cycles: int,policy: CyclePolicy | None = None,*,ambient_K=298.15,tolerance=1e-4):
    """Screen a linear cycle map against independently executed short cycles."""
    if not isinstance(cycles,int) or not 1 <= cycles <= 20 or tolerance < 0:
        raise ValueError("jump check requires 1..20 cycles and nonnegative tolerance")
    policy = policy or CyclePolicy()
    exact = _cycles(model,state,cycles,policy,ambient_K)
    if not exact["cycle_states"]:
        return {"candidate_status":"unknown","reason":"first_cycle_constraint","reference":exact,
                "execution_mode":"exact_reference","speedup_claim":False}
    start = np.asarray(state,dtype=float)
    candidate = start + cycles*(exact["cycle_states"][0]-start)
    difference = np.abs(candidate-exact["state"])
    # Occupancies are dimensionless; the residual for mol is reported separately.
    scales = np.array([1,1,sum(model.params.site_capacity_mol) if isinstance(model,SiteModel) else .02,
                       sum(model.params.site_capacity_mol) if isinstance(model,SiteModel) else .02,40])
    normalized = float(np.max(difference/scales))
    valid = exact["completed_cycles"]==cycles and np.all(candidate[..., :2]>=0) and np.all(candidate[..., :2]<=1) and np.all(candidate[...,2:4]>=0)
    return {"candidate_status":"within_tolerance" if valid and normalized<=tolerance else "rejected",
            "normalized_max_error":normalized,"component_absolute_error":difference.tolist(),
            "candidate_state":candidate.tolist(),"reference":exact,"execution_mode":"exact_reference","speedup_claim":False}


def _prefix_cycle(result):
    phases=result["phases"][:2]
    state=np.asarray(phases[-1]["state_after"]) if phases else result["state"].copy()
    complete=len(phases)==2 and not any(p["events"] for p in phases)
    return {"state":state,"elapsed_s":sum(p["elapsed_s"] for p in phases),"energy_J":sum(p["energy_J"] for p in phases),
            "thermal_management_energy_J":sum(p["thermal_electric_energy_J"] for p in phases),"completed_cycles":int(complete),
            "phases":phases,"cycle_states":[state] if complete else [],"status":"completed" if complete else "stopped_constraint"}


def _phase_totals(result):
    return [sum(p["energy_J"] for p in result["phases"] if p["phase"]==name) for name in ("discharge","charge")]


def _candidate_guard(model,state,policy,budget):
    cells=(model,) if isinstance(model,SiteModel) else model.cells
    states=[state] if isinstance(model,SiteModel) else state
    for cell,s in zip(cells,states):
        if not np.all(np.isfinite(s)) or np.any(s[:2]<.02) or np.any(s[:2]>.98) or np.any(s[2:4]<0):return "predicted_inventory_or_occupancy_domain"
        p=cell.params
        if not p.temperature_min_K+4*budget.temperature_abs_K<s[4]<p.temperature_max_K-4*budget.temperature_abs_K:return "predicted_temperature_domain_margin"
        for current in (policy.discharge_A,policy.charge_A):
            try:voltage=cell.observe(s,current)["voltage_V"]
            except (ValueError,RuntimeError) as exc:return "predicted_current_root:"+str(exc)
            if not p.voltage_min_V+.05<voltage<p.voltage_max_V-.05:return "predicted_voltage_domain_margin"
    return None


def _append_reference(first,second):
    offset=first["elapsed_s"]
    phases=first["phases"]+[dict(p,cycle=p["cycle"]+first["completed_cycles"],start_s=p["start_s"]+offset) for p in second["phases"]]
    return {"state":second["state"],"elapsed_s":offset+second["elapsed_s"],"energy_J":first["energy_J"]+second["energy_J"],
            "thermal_management_energy_J":first["thermal_management_energy_J"]+second["thermal_management_energy_J"],
            "completed_cycles":first["completed_cycles"]+second["completed_cycles"],"cycle_states":first["cycle_states"]+second["cycle_states"],
            "phases":phases,"status":second["status"]}


def _attempt_jump(model,state,cycles,policy,ambient_K,budget,used_error,used_energy,audit):
    calibration=_cycles(model,state,3,policy,ambient_K)
    fallback=_prefix_cycle(calibration)
    report={"requested_cycles":cycles,"calibration_cycles":calibration["completed_cycles"],"audit_performed":audit,
            "evidence_category":"validated_numerics","strict_error_certificate":False,"execution_mode":"exact_fallback","accepted":False}
    if calibration["completed_cycles"]!=3:
        report["reason"]="calibration_constraint"
        return fallback,report
    s0=np.asarray(state);s1,s2,s3=calibration["cycle_states"]
    d1=s1-s0;d2=s2-2*s1+s0;d3=s3-3*s2+3*s1-s0
    candidate=s0+cycles*d1+cycles*(cycles-1)/2*d2
    cells=(model,) if isinstance(model,SiteModel) else model.cells
    candidate_rows=[candidate] if isinstance(model,SiteModel) else candidate
    start_rows=[s0] if isinstance(model,SiteModel) else s0
    inventory_residuals=[cell.inventory_mol(after)-cell.inventory_mol(before) for cell,after,before in zip(cells,candidate_rows,start_rows)]
    state_error=np.abs(d3)*math.comb(cycles,3)*budget.safety_factor
    # Floating point allowance is explicit rather than a root or state clip.
    state_error+=np.finfo(float).eps*32*np.maximum(1,np.abs(candidate))
    predicted_phase=[];phase_error=[]
    for phase in ("discharge","charge"):
        energies=[p["energy_J"] for p in calibration["phases"] if p["phase"]==phase]
        predicted_phase.append(cycles*energies[0]+cycles*(cycles-1)/2*(energies[1]-energies[0]))
        phase_error.append(abs(energies[2]-2*energies[1]+energies[0])*math.comb(cycles,3)*budget.safety_factor)
    energy_error=sum(phase_error)
    reason=None
    if any(abs(r)>budget.sodium_abs_mol for r in inventory_residuals):reason="macro_inventory_residual_budget"
    if np.any(used_error+state_error>budget.state_limits()) or used_energy+energy_error>budget.electrical_energy_abs_J:reason="estimated_cumulative_error_budget"
    # Check predicted cycle and both phase endpoints, including heterogeneous cells.
    discharge_states=[np.asarray(p["state_after"]) for p in calibration["phases"] if p["phase"]=="discharge"]
    for n in range(1,cycles+1):
        cstate=s0+n*d1+n*(n-1)/2*d2
        ds=discharge_states[0]+(n-1)*(discharge_states[1]-discharge_states[0])+(n-1)*(n-2)/2*(discharge_states[2]-2*discharge_states[1]+discharge_states[0])
        reason=reason or _candidate_guard(model,cstate,policy,budget) or _candidate_guard(model,ds,policy,budget)
    report.update(state_error_estimate=state_error.tolist(),energy_error_estimate_J=energy_error,phase_energy_error_estimate_J=phase_error,
                  inventory_residual_mol=inventory_residuals)
    if reason:
        report["reason"]=reason
        return fallback,report
    reference=None
    if audit:
        tail=_cycles(model,s3,cycles-3,policy,ambient_K)
        reference=_append_reference(calibration,tail)
        actual_error=np.abs(candidate-reference["state"])
        actual_energy_error=abs(sum(predicted_phase)-reference["energy_J"])
        report.update(reference_cycles=reference["completed_cycles"],audited_state_error=actual_error.tolist(),audited_energy_error_J=actual_energy_error)
        state_error=np.maximum(state_error,actual_error)
        energy_error=max(energy_error,actual_energy_error)
        if reference["completed_cycles"]!=cycles or np.any(used_error+state_error>budget.state_limits()) or used_energy+energy_error>budget.electrical_energy_abs_J:
            report["reason"]="reference_audit_constraint_or_error_budget"
            return fallback,report
        # These energies are from actual fine reference execution; audits are not
        # an extra operating sale and never add a second energy ledger entry.
        predicted_phase=_phase_totals(reference)
    phase_records=[]
    for offset,(name,current,energy) in enumerate(zip(("discharge","charge"),(policy.discharge_A,policy.charge_A),predicted_phase)):
        phase_records.append({"cycle":0,"cycle_count":cycles,"phase":name,"policy_id":policy.policy_id,"current_A":current,
                              "start_s":offset*policy.phase_duration_s,"cycle_period_s":2*policy.phase_duration_s,"phase_offset_s":offset*policy.phase_duration_s,
                              "elapsed_s":cycles*policy.phase_duration_s,"energy_J":energy,"events":[],"inventory_residual_mol":None,
                              "thermal_electric_energy_J":calibration["thermal_management_energy_J"]*cycles/6,
                              "execution_mode":"cycle_map_jump","aggregation":"same_phase_across_cycles",
                              "energy_error_estimate_J":0 if audit else phase_error[offset]})
    report.update(accepted=True,execution_mode="cycle_map_jump",reason=None,actual_advanced_cycles=cycles,
                  fine_cycles_evaluated=cycles if audit else 3,unintegrated_cycles=0 if audit else cycles-3,
                  state_error_estimate=state_error.tolist(),energy_error_estimate_J=energy_error,
                  predicted_state=candidate.tolist(),reference_state=reference["state"].tolist() if audit else None)
    return {"state":candidate,"elapsed_s":2*cycles*policy.phase_duration_s,"energy_J":sum(predicted_phase),
            "thermal_management_energy_J":calibration["thermal_management_energy_J"]*cycles/3,
            "completed_cycles":cycles,"phases":phase_records,"cycle_states":[],"status":"completed"},report


def _stored_energy_probe(model,state,protocol,ambient_K):
    """Counterfactual value of current stored energy, without protocol recharging."""
    from naheng.simulation.module import ModuleModel
    cells=(model,) if isinstance(model,SiteModel) else model.cells
    cutoffs=[max(cell.params.voltage_min_V,protocol.cutoff_voltage_V) for cell in cells]
    if isinstance(model,SiteModel):probe=SiteModel(replace(model.params,voltage_min_V=cutoffs[0]))
    else:probe=ModuleModel(tuple(SiteModel(replace(cell.params,voltage_min_V=cutoff)) for cell,cutoff in zip(model.cells,cutoffs)),model.coupling_W_per_K)
    try:result=probe.integrate(state,protocol.discharge_current_A,protocol.maximum_duration_s,ambient_K=ambient_K)
    except (ValueError,RuntimeError) as exc:return {"status":"unknown","energy_J":None,"reason":str(exc),"counterfactual_valuation_only":True}
    ended=any(event["name"]=="voltage_low" for event in result.events)
    return {"status":"computed" if ended else "right_censored","energy_J":result.energy_J if ended else None,
            "lower_bound_J":result.energy_J,"elapsed_s":result.elapsed_s,"events":result.events,"effective_cutoffs_V":cutoffs,"counterfactual_valuation_only":True}


def run_lifecycle(model=None,initial_state=None,*,cycles=5,protocol: CapacityProtocol | None = None,
                  policy_provider: Callable[[dict],CyclePolicy] | None = None,maximum_replacements=0,
                  ambient_K=298.15,jump_check_cycles=1,jump_budget: CycleJumpBudget | None = None,
                  economics: LifecycleEconomics | None = None,wall_budget_s=120):
    if not isinstance(cycles,int) or not 1 <= cycles <= 1000 or maximum_replacements < 0:
        raise ValueError("lifecycle budget must be bounded and nonnegative")
    if not isinstance(jump_check_cycles,int) or not 1 <= jump_check_cycles <= 20:
        raise ValueError("jump check batch must contain 1..20 cycles")
    if not math.isfinite(wall_budget_s) or wall_budget_s<=0:raise ValueError("wall budget must be positive")
    started=time.monotonic()
    model = model or SiteModel()
    state = model.initial_state() if initial_state is None else np.asarray(initial_state,dtype=float).copy()
    cells = (model,) if isinstance(model,SiteModel) else model.cells
    protocol = protocol or CapacityProtocol()
    budget=jump_budget or CycleJumpBudget()
    accounting=economics or LifecycleEconomics()
    pristine_cache = {}
    diagnostic_cache={}
    def capacity_rows(current):
        rows = []
        states = [current] if isinstance(model,SiteModel) else current
        for cell,s in zip(cells,states):
            if protocol.cutoff_voltage_V<cell.params.voltage_min_V:
                baseline=measured={"status":"unknown","capacity_C":None,"reason":"protocol_cutoff_below_declared_cell_domain","protocol_id":protocol.protocol_id}
            else:
                if cell.params not in pristine_cache:
                    pristine_cache[cell.params] = protocol_capacity(cell,cell.initial_state(),protocol)
                baseline = pristine_cache[cell.params]
                key=(cell.params,np.asarray(s,dtype=float).tobytes())
                if key not in diagnostic_cache:diagnostic_cache[key]=protocol_capacity(cell,s,protocol)
                measured=diagnostic_cache[key]
            valid = baseline.get("status")==measured.get("status")=="computed" and baseline.get("capacity_C",0)>0
            rows.append({"protocol":measured,"pristine_capacity_C":baseline.get("capacity_C"),
                         "soh":measured["capacity_C"]/baseline["capacity_C"] if valid else None})
        return rows
    elapsed,energy,thermal,completed,replacements = 0.0,0.0,0.0,0,0
    traces,phases,maintenance,jump_reports = [],[],[],[]
    status,retirement_interval = "right_censored",None
    previous_check = 0.0
    used_error=np.zeros_like(state)
    used_energy_error=0.0
    accepted_jumps=0
    initial_diagnostic=capacity_rows(state)
    initial_energy_value=_stored_energy_probe(model,state,protocol,ambient_K)
    birth_times=[0.0]*len(cells)
    retirement_records=[]
    while completed < cycles:
        if time.monotonic()-started>wall_budget_s:
            status="budget_exhausted"
            break
        diagnostic = capacity_rows(state)
        traces.append({"cycle":completed,"time_s":elapsed,"cells":diagnostic,"state":state.tolist()})
        unknown = [i for i,row in enumerate(diagnostic) if row["soh"] is None]
        if unknown:
            status = "unknown_capacity"
            break
        retired = [i for i,row in enumerate(diagnostic) if row["soh"]<=protocol.retirement_ratio]
        if retired:
            retirement_interval = [previous_check,elapsed]
            for index in retired:
                retirement_records.append({"cell_id":f"cell-{index+1}","time_interval_s":retirement_interval,
                                           "birth_time_s":birth_times[index],"age_interval_s":[max(0,previous_check-birth_times[index]),elapsed-birth_times[index]],
                                           "protocol_id":protocol.protocol_id,"soh":diagnostic[index]["soh"],"evidence_category":"empirical"})
            if replacements+len(retired)>maximum_replacements:
                status = "retired"
                break
            for index in retired:
                old = state if isinstance(model,SiteModel) else state[index]
                new = cells[index].initial_state(temperature_K=ambient_K)
                maintenance.append({"cell_id":f"cell-{index+1}","time_s":elapsed,"kind":"replacement",
                                    "discarded_inventory_mol":cells[index].inventory_mol(old),
                                    "introduced_inventory_mol":cells[index].inventory_mol(new),
                                    "retired_soh":diagnostic[index]["soh"],"replacement_cost":accounting.replacement_cost_per_cell,
                                    "salvage_value":accounting.replacement_cost_per_cell*accounting.salvage_fraction_of_cost_per_soh*diagnostic[index]["soh"],
                                    "source_id":accounting.source_id,"currency":"CNY","provenance_type":"synthetic"})
                if isinstance(model,SiteModel):
                    state = new
                    used_error=np.zeros_like(state)
                else:
                    state[index] = new
                    used_error[index]=0
                replacements += 1
                birth_times[index]=elapsed
            diagnostic = capacity_rows(state)
            accepted_jumps=0
        context = {"cycle":completed,"time_s":elapsed,"soh":[row["soh"] for row in diagnostic],"replacement_count":replacements,
                   "cell_age_s":[elapsed-birth for birth in birth_times],
                   "numerical_state_error_estimate":used_error.tolist(),"diagnostic_source":"synthetic_capacity_protocol"}
        policy = policy_provider(context) if policy_provider else CyclePolicy(hold_cycles=20)
        if not isinstance(policy,CyclePolicy): raise ValueError("policy provider must return CyclePolicy")
        batch = min(jump_check_cycles,policy.hold_cycles,cycles-completed)
        previous_check = elapsed
        cycle_offset,time_offset = completed,elapsed
        report=None
        if batch>=4 and all(row["soh"]>protocol.retirement_ratio+budget.retirement_margin for row in diagnostic):
            try:
                result,report=_attempt_jump(model,state,batch,policy,ambient_K,budget,used_error,used_energy_error,
                                            audit=accepted_jumps%budget.audit_every_jumps==0)
                if report["accepted"]:
                    candidate_diagnostic=capacity_rows(result["state"])
                    if any(row["soh"] is None or row["soh"]<=protocol.retirement_ratio+budget.retirement_margin for row in candidate_diagnostic):
                        report.update(accepted=False,reason="candidate_capacity_unknown_or_retirement_margin",execution_mode="exact_fallback")
                        result=_cycles(model,state,1,policy,ambient_K)
                    else:
                        used_error+=np.asarray(report["state_error_estimate"])
                        used_energy_error+=report["energy_error_estimate_J"]
                        accepted_jumps+=1
            except (ValueError,RuntimeError) as exc:
                report={"accepted":False,"execution_mode":"exact_fallback","reason":"jump_calibration_numerical_failure:"+str(exc)}
                result=_cycles(model,state,1,policy,ambient_K)
            report.update(cycle_start=completed,time_start_s=elapsed)
            jump_reports.append(report)
        else:
            if jump_check_cycles>1:
                jump_reports.append({"accepted":False,"cycle_start":completed,"execution_mode":"exact_fallback",
                                     "reason":"policy_hold_window_or_retirement_margin_or_short_tail"})
            result = _cycles(model,state,1,policy,ambient_K)
        state = result["state"]
        elapsed += result["elapsed_s"]
        energy += result["energy_J"]
        thermal += result["thermal_management_energy_J"]
        completed += result["completed_cycles"]
        for phase in result["phases"]:
            phase = dict(phase)
            local_start = phase["start_s"]
            phase["cycle"] += cycle_offset
            phase["start_s"] += time_offset
            phase["events"] = [dict(event,time_s=event["time_s"]+time_offset+local_start) for event in phase["events"]]
            phases.append(phase)
        if result["status"]!="completed":
            status = result["status"]
            break
    if completed==cycles:
        final_diagnostic = capacity_rows(state)
        traces.append({"cycle":completed,"time_s":elapsed,"cells":final_diagnostic,"state":state.tolist()})
        if any(row["soh"] is None for row in final_diagnostic): status="unknown_capacity"
        elif any(row["soh"]<=protocol.retirement_ratio for row in final_diagnostic):
            status="retired"
            retirement_interval=[previous_check,elapsed]
            for index,row in enumerate(final_diagnostic):
                if row["soh"]<=protocol.retirement_ratio:
                    retirement_records.append({"cell_id":f"cell-{index+1}","time_interval_s":retirement_interval,
                                               "birth_time_s":birth_times[index],"age_interval_s":[max(0,previous_check-birth_times[index]),elapsed-birth_times[index]],
                                               "protocol_id":protocol.protocol_id,"soh":row["soh"],"evidence_category":"empirical"})
    else:final_diagnostic=capacity_rows(state)
    final_energy_value=_stored_energy_probe(model,state,protocol,ambient_K) if time.monotonic()-started<wall_budget_s else {"status":"unknown","energy_J":None,"reason":"wall_budget_exhausted","counterfactual_valuation_only":True}
    exact_ledger=[];projected_ledger=[]
    for phase in phases:
        e=phase["energy_J"];thermal_e=phase["thermal_electric_energy_J"]
        entry={"cycle_start":phase["cycle"],"cycle_count":phase["cycle_count"],"phase":phase["phase"],"policy_id":phase["policy_id"],
               "energy_J":e,"exported_energy_J":max(e,0),"imported_energy_J":max(-e,0),"thermal_electric_energy_J":thermal_e,
               "sales":max(e,0)/3600000*accounting.sell_price_per_kWh,"purchases":max(-e,0)/3600000*accounting.buy_price_per_kWh,
               "thermal_cost":thermal_e/3600000*accounting.buy_price_per_kWh,"source_id":accounting.source_id,"provenance_type":"synthetic",
               "energy_error_estimate_J":phase.get("energy_error_estimate_J",0),"currency":"CNY"}
        entry["net_cashflow"]=entry["sales"]-entry["purchases"]-entry["thermal_cost"]
        entry["cash_error_estimate"]=entry["energy_error_estimate_J"]/3600000*max(accounting.buy_price_per_kWh,accounting.sell_price_per_kWh)
        (projected_ledger if phase["execution_mode"]=="cycle_map_jump" else exact_ledger).append(entry)
    def totals(entries):return {key:sum(row[key] for row in entries) for key in ("energy_J","sales","purchases","thermal_cost","net_cashflow","cash_error_estimate")}
    initial_asset=sum(row["soh"] for row in initial_diagnostic if row["soh"] is not None)*accounting.replacement_cost_per_cell*accounting.salvage_fraction_of_cost_per_soh
    final_asset=None if any(row["soh"] is None for row in final_diagnostic) else sum(row["soh"] for row in final_diagnostic)*accounting.replacement_cost_per_cell*accounting.salvage_fraction_of_cost_per_soh
    stored_adjustment=None
    if initial_energy_value["status"]==final_energy_value["status"]=="computed":
        stored_adjustment=(final_energy_value["energy_J"]-initial_energy_value["energy_J"])/3600000*accounting.stored_energy_value_per_kWh
    maintenance_cash=sum(row["salvage_value"]-row["replacement_cost"] for row in maintenance)
    conditional_value=None if final_asset is None or stored_adjustment is None else totals(exact_ledger)["net_cashflow"]+totals(projected_ledger)["net_cashflow"]+maintenance_cash+stored_adjustment+final_asset-initial_asset
    return {"status":status,"completed_cycles":completed,"elapsed_s":elapsed,"final_state":state.tolist(),
            "electrical_energy_J":energy,"thermal_management_energy_J":thermal,"phases":phases,"trace":traces,
            "maintenance":maintenance,"replacement_count":replacements,"retirement_interval_s":retirement_interval,
            "retirement_records":retirement_records,"cell_age_s":[elapsed-birth for birth in birth_times],
            "retirement_detection":"protocol_checkpoints","jump_checks":jump_reports,
            "retirement_interval_kind":"detection_interval_in_numerical_trajectory; macro_error_not_a_certified_RUL_time_bound",
            "exact_phase_ledger":exact_ledger,"macro_projected_ledger":projected_ledger,
            "numerical":{"state_error_estimate":used_error.tolist(),"energy_error_estimate_J":used_energy_error,"budget":vars(budget),
                         "strict_error_certificate":False,"accepted_jumps":sum(bool(r.get("accepted")) for r in jump_reports),
                         "fine_cycles_avoided":sum(r.get("unintegrated_cycles",0) for r in jump_reports if r.get("accepted")),
                         "error_scope":"local_calibration_and_periodic_audits; estimates are not mathematical global bounds"},
            "economics":{"source_id":accounting.source_id,"assumptions":vars(accounting),"exact_phase_totals":totals(exact_ledger),
                         "macro_projected_totals":totals(projected_ledger),"maintenance_net_cashflow":maintenance_cash,
                         "initial_asset_residual":initial_asset,"final_asset_residual":final_asset,"asset_residual_adjustment":None if final_asset is None else final_asset-initial_asset,
                         "initial_stored_energy_probe":initial_energy_value,"final_stored_energy_probe":final_energy_value,
                         "stored_energy_value_adjustment":stored_adjustment,"conditional_comparison_value":conditional_value,
                         "terminal_probe_energy_in_operating_sales":False,"valuation_is_realized_revenue":False,
                         "scope":"synthetic accounting fixture; macro values are projected; no real tariff or revenue advantage validation"},
            "walltime_s":time.monotonic()-started,"wall_budget_s":wall_budget_s,"final_protocol_diagnostics":final_diagnostic,
            "provenance_type":"synthetic","accelerated_synthetic":any(cell.params.accelerated_synthetic for cell in cells),
            "uncalibrated":True,"topology":"single_cell" if isinstance(model,SiteModel) else model.topology}
