"""Bounded nonlinear nominal MPC with represented-posterior candidate checks.

Only the first proposed action may be executed. All trajectories are genuine
SiteModel integrations, not real-cell predictions or strict risk certificates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from scipy.optimize import minimize

from naheng.domain.contracts import Action, PosteriorSnapshot
from naheng.estimation.particle_filter import particle_model
from naheng.models.site_model import DomainError, InfeasibleError, SiteModel, SiteParameters
from naheng.risk.admission import check
from naheng.runtime.process_tree import ProcessTree








from naheng.control.mpc import MPCParameters, MPCPlan, MPCStage as BaseMPCStage

@dataclass(frozen=True)
class MPCStage(BaseMPCStage):
    min_current_A: float | None = None
    max_current_A: float | None = None

    def __post_init__(self):
        # Base values describe the fixed external timeline, never optimized tariffs.
        if any(type(v) not in (float,int) for v in (self.duration_s,self.buy_price_per_kWh,self.sell_price_per_kWh,self.ambient_K)):
            raise ValueError('Nonboolean external timeline values required')
        values=(self.duration_s,self.buy_price_per_kWh,self.sell_price_per_kWh,self.ambient_K)
        if not all(math.isfinite(v) for v in values) or not 0<self.duration_s<=3600:
            raise ValueError('Finite MPC stage and positive duration<=3600s required')
        if self.ambient_K<=0 or min(self.buy_price_per_kWh,self.sell_price_per_kWh)<0:
            raise ValueError('Positive Kelvin ambient and nonnegative tariffs required')
        if (self.min_current_A is None) != (self.max_current_A is None):
            raise ValueError('Both explicit current permission endpoints are required')
        if self.min_current_A is not None:
            if (any(type(v) not in (float,int) or not math.isfinite(v) for v in (self.min_current_A,self.max_current_A))
                    or self.min_current_A > self.max_current_A):
                raise ValueError('Finite ordered stage current permission required')

def stage_current_bounds(stage, current_limit):
    low=max(-current_limit, stage.min_current_A if stage.min_current_A is not None else -current_limit)
    high=min(current_limit, stage.max_current_A if stage.max_current_A is not None else current_limit)
    if low>high:raise ValueError('Stage permissions have no intersection with common current bounds')
    return low,high

CURRENT_COMMAND_RESOLUTION_A = 1e-8

def quantize_current_towards_zero(value):
    """Declared command resolution; final commands are re-simulated below."""
    if not math.isfinite(value):raise ValueError('Finite current command required')
    ticks=math.floor(abs(value)/CURRENT_COMMAND_RESOLUTION_A)
    magnitude=ticks*CURRENT_COMMAND_RESOLUTION_A
    return math.copysign(math.nextafter(magnitude,0.),value) if magnitude else 0.


class _Budget(Exception):
    pass


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def plan(snapshot: PosteriorSnapshot, model: SiteModel, package: dict, stages,
         *, start_s: float | None = None, parameters: MPCParameters | None = None,
         admission_mode: str = "empirical", runtime_binding=None,
         accept_verified_incumbent: bool = False) -> MPCPlan:
    """Hard-bound optimizer/ODE computation in one owned subprocess tree.

    Inputs contain only the permitted posterior, model/parameter package and
    declared exogenous schedule. Caller executes action then assimilates and
    replans; future planned actions are never an execution history.
    """
    started = time.monotonic()
    parameters = parameters or MPCParameters()
    if type(accept_verified_incumbent) is not bool:
        raise ValueError("Explicit boolean incumbent policy required")
    if accept_verified_incumbent and not (parameters.max_iterations == 1 and parameters.max_candidate_evaluations <= 24):
        # Incumbent acceptance stays limited to the declared low computation
        # work budget. The wall-clock backstop is deliberately not part of this
        # guard: it depends on host load, and a guard that flips with load turns
        # the same candidate into a different scientific label.
        raise ValueError("Incumbent acceptance is limited to the declared low computation work budget")
    stages = tuple(stages)
    if not 2 <= len(stages) <= 8 or any(not isinstance(stage, MPCStage) for stage in stages):
        raise ValueError("MPC requires 2..8 explicit prediction stages")
    if not isinstance(snapshot, PosteriorSnapshot) or type(model) is not SiteModel:
        raise TypeError("MPC accepts a posterior snapshot and the declared SiteModel")
    start_s = snapshot.obs_until_s if start_s is None else start_s
    if not math.isfinite(start_s) or abs(start_s - snapshot.obs_until_s) > 1e-8:
        raise ValueError("MPC start must equal the posterior observation time")
    base = {"algorithm": "scipy_SLSQP_nonlinear_nominal_MPC", "risk_certificate": False,
            "evidence_category": "empirical", "tariff_source": parameters.tariff_source,
            "provenance_type": "synthetic", "horizon_steps": len(stages),
            "wall_budget_s": parameters.wall_budget_s, "max_iterations": parameters.max_iterations,
            "max_candidate_evaluations": parameters.max_candidate_evaluations,
            "model_parameters_hash": _hash(asdict(model.params)),
            "mpc_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "uncovered_events": {"fire": "unknown_no_mechanism", "sodium_plating": "unknown_no_mechanism"}}

    def stopped(status, reason, extra=None):
        return MPCPlan(status, reason, snapshot.snapshot_id, (),
                       {**base, **(extra or {}), "wall_s": time.monotonic()-started})

    if package.get("parameter_revision") != snapshot.parameter_revision:
        return stopped("unknown", "Snapshot and model package parameter revision differ")
    if package.get("package_id") != snapshot.model_package_id:
        return stopped("unknown", "Snapshot belongs to another model package")
    if not package.get("parameters") or _hash(package["parameters"]) != base["model_parameters_hash"]:
        return stopped("unknown", "Package parameters are not bound to the prediction model")
    if len(snapshot.state_names) != len(set(snapshot.state_names)) or any(
            name not in snapshot.state_names for name in model.state_names):
        return stopped("unknown", "Prediction state semantics are missing or ambiguous")
    if any(snapshot.state_units[snapshot.state_names.index(name)] != unit
           or package.get("state_definition", {}).get(name) != unit
           for name, unit in zip(model.state_names, model.state_units)):
        return stopped("unknown", "Prediction state units do not match the declared model package")
    if len(snapshot.samples) > 256:
        return stopped("unknown", "Represented scenario count exceeds the declared 256-scenario resource bound")
    zero = Action(action_id="mpc-applicability-probe", snapshot_id=snapshot.snapshot_id,
                  start_s=start_s, duration_s=stages[0].duration_s, current_A=0)
    admission = check(snapshot, zero, package, stages[0].ambient_K, mode=admission_mode, runtime_binding=runtime_binding)
    if admission["decision"] != "accept":
        return stopped("infeasible" if admission["decision"] == "reject" else "unknown",
                       admission["reason"], {"admission": admission})
    for stage in stages:
        if not package["domain"]["temperature_K"][0] <= stage.ambient_K <= package["domain"]["temperature_K"][1]:
            return stopped("infeasible", "A scheduled ambient lies outside the declared model domain")
    payload = {"snapshot": snapshot.model_dump(mode="json"), "model_parameters": asdict(model.params),
               "package": package, "stages": [asdict(stage) for stage in stages],
               "parameters": asdict(parameters), "start_s": start_s,
               "accept_verified_incumbent": accept_verified_incumbent}
    base["input_hash"] = _hash(payload)
    encoded = json.dumps(payload, allow_nan=False).encode()
    if len(encoded) > 4*1024*1024:
        return stopped("unknown", "MPC input exceeds the declared byte budget")
    remaining = parameters.wall_budget_s - (time.monotonic()-started)
    if remaining <= 0:
        return stopped("unknown", "MPC budget exhausted before worker launch")
    argv = [sys.executable, "-m", __package__ + ".strategy_mpc", "--worker"]
    options = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=os.name != "nt", env={**os.environ, "PYTHONPATH": os.pathsep.join([str(Path(__file__).resolve().parents[1]), str(Path(__import__("naheng").__file__).resolve().parents[1])]),
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}, **options)
    tree = ProcessTree(proc)
    base.update(worker_argv=argv, owned_pid=proc.pid)
    try:
        try:
            stdout, stderr = proc.communicate(encoded, timeout=max(0.001, parameters.wall_budget_s-(time.monotonic()-started)))
        except subprocess.TimeoutExpired:
            killed = tree.terminate()
            stdout, stderr = proc.communicate(timeout=10)
            return stopped("unknown", "Owned MPC optimizer/integrator process exceeded its wall budget",
                           {"timed_out": True, "termination": killed, "worker_returncode": proc.returncode,
                            "worker_stderr": stderr.decode(errors="replace")[-32768:]})
        base.update(worker_returncode=proc.returncode, worker_stderr=stderr.decode(errors="replace")[-32768:], timed_out=False)
        if proc.returncode != 0:
            return stopped("unknown", "MPC numerical worker failed", {"worker_stdout": stdout.decode(errors="replace")[-8192:]})
        try:
            result = json.loads(stdout)
        except (ValueError, UnicodeError):
            return stopped("unknown", "MPC worker returned invalid calculation evidence")
        diagnostics = {**base, **result["diagnostics"], "wall_s": time.monotonic()-started}
        if result["status"] != "feasible":
            return MPCPlan(result["status"], result["reason"], snapshot.snapshot_id, (), diagnostics)
        actions = []
        offset = 0.0
        for index, (stage, command) in enumerate(zip(stages, result["commands"])):
            actions.append(Action(action_id=f"mpc-{base['input_hash'][:20]}-{index}", snapshot_id=snapshot.snapshot_id,
                start_s=start_s+offset, duration_s=stage.duration_s, current_A=command[0], thermal_W=command[1]))
            offset += stage.duration_s
        final_admission = check(snapshot, actions[0], package, stages[0].ambient_K,
                                mode=admission_mode, runtime_binding=runtime_binding)
        diagnostics["admission"] = final_admission
        if final_admission["decision"] != "accept":
            return MPCPlan("unknown" if final_admission["decision"] == "unknown" else "infeasible",
                           final_admission["reason"], snapshot.snapshot_id, (), diagnostics)
        return MPCPlan("feasible", result["reason"], snapshot.snapshot_id, tuple(actions), diagnostics)
    finally:
        tree.close()


def _solve(payload):
    snapshot = PosteriorSnapshot.model_validate(payload["snapshot"])
    model = SiteModel(SiteParameters(**payload["model_parameters"]))
    params = MPCParameters(**payload["parameters"])
    accept_incumbent=payload.get("accept_verified_incumbent",False)
    if type(accept_incumbent) is not bool or (accept_incumbent and not (params.max_iterations == 1 and params.max_candidate_evaluations <= 24)):
        raise ValueError("Invalid bounded incumbent work policy")
    stages = [MPCStage(**row) for row in payload["stages"]]
    package = payload["package"]
    started = time.monotonic()
    counters = {"candidate_evaluations": 0, "integration_calls": 0, "completed_integrations": 0}
    diagnostics = {"budgets": asdict(params), "counters": counters, "optimizer": None,
                   "risk_certificate": False, "optimization_scope": "nominal_model",
                   "verification_scope": "all_represented_posterior_state_parameter_samples"}

    def checkpoint(phase, **extra):
        print("MPC_PROGRESS " + json.dumps({"phase": phase, **counters, **extra}), file=sys.stderr, flush=True)
        if time.monotonic()-started >= params.wall_budget_s:
            raise _Budget("Worker solver-boundary wall budget exhausted")

    names = snapshot.state_names
    indices = [names.index(name) for name in model.state_names]
    samples = np.asarray(snapshot.samples)
    weights = np.asarray(snapshot.weights)
    rate = names.index("rate_scale") if "rate_scale" in names else None
    side = names.index("side_rate_scale") if "side_rate_scale" in names else None
    models = [particle_model(model, row[rate] if rate is not None else 1.0,
                             row[side] if side is not None else 1.0) for row in samples]
    nominal_state = np.average(samples[:, indices], axis=0, weights=weights)
    nominal_model = particle_model(model, np.average(samples[:, rate], weights=weights) if rate is not None else 1.0,
                                   np.average(samples[:, side], weights=weights) if side is not None else 1.0)
    p = model.params
    low_t = max(p.temperature_min_K, package["domain"]["temperature_K"][0],
                params.temperature_min_K if params.temperature_min_K is not None else p.temperature_min_K)
    high_t = min(p.temperature_max_K, package["domain"]["temperature_K"][1],
                 params.temperature_max_K if params.temperature_max_K is not None else p.temperature_max_K)
    low_v = max(p.voltage_min_V+params.voltage_margin_V, params.voltage_min_V if params.voltage_min_V is not None else p.voltage_min_V)
    high_v = min(p.voltage_max_V-params.voltage_margin_V, params.voltage_max_V if params.voltage_max_V is not None else p.voltage_max_V)
    if low_t >= high_t or low_v >= high_v:
        return {"status": "infeasible", "reason": "Policy and model output ranges do not intersect", "diagnostics": diagnostics}
    current_limit = min(params.current_limit_A, package["domain"]["max_current_A"])
    if not math.isfinite(current_limit) or current_limit <= 0:
        return {"status": "infeasible", "reason": "No positive declared current action range", "diagnostics": diagnostics}
    capacity = np.asarray(p.site_capacity_mol)

    def soc(state):
        return np.asarray(state)[..., :2] @ capacity / capacity.sum()

    def band_limit(value, current):
        matching = []
        lower = 0.0
        for upper, charge, discharge in params.soc_bands:
            if lower-1e-12 <= value <= upper+1e-12:
                matching.append(charge if current < 0 else discharge)
            lower = upper
        return min([current_limit, *matching]) if matching else 0.0

    def rollout(sampled_model, initial, commands, label, nominal=False):
        state = initial.copy()
        initial_soc = float(soc(initial))
        terminal_floor = initial_soc if params.terminal_soc_min is None else params.terminal_soc_min
        if nominal:
            terminal_floor += params.nominal_terminal_buffer
        observed_soc = [initial_soc]
        margins, output = [], []
        net_cashflow, trapped_increment = 0.0, 0.0
        for index, (stage, (current, thermal)) in enumerate(zip(stages, commands)):
            counters["integration_calls"] += 1
            checkpoint("integrating", scenario=label, stage=index)
            result = sampled_model.integrate(state, float(current), stage.duration_s,
                ambient_K=stage.ambient_K, thermal_W=float(thermal), max_step_s=params.prediction_max_step_s)
            counters["completed_integrations"] += 1
            checkpoint("integrated", scenario=label, stage=index)
            values = soc(result.states)
            observed_soc.extend(values.tolist())
            stage_margin = [float(values.min()-params.soc_min), float(params.soc_max-values.max()),
                float((result.voltages_V.min()-low_v)/(high_v-low_v)), float((high_v-result.voltages_V.max())/(high_v-low_v)),
                float((result.states[:, 4].min()-low_t)/(high_t-low_t)), float((high_t-result.states[:, 4].max())/(high_t-low_t)),
                float(result.states[:, 3].min()/max(p.reservoir_initial_mol, 1e-12)),
                min(band_limit(float(value), current)-abs(current) for value in values)/current_limit,
                (result.elapsed_s-stage.duration_s)/stage.duration_s,
                -float(bool(result.events)),
                (float(current)-stage_current_bounds(stage,current_limit)[0])/current_limit,
                (stage_current_bounds(stage,current_limit)[1]-float(current))/current_limit]
            margins.extend(stage_margin)
            thermal_energy = result.thermal_management_energy_J
            predicted_sales = max(result.energy_J, 0)/3_600_000*stage.sell_price_per_kWh
            predicted_purchase = max(-result.energy_J, 0)/3_600_000*stage.buy_price_per_kWh
            predicted_thermal_cost = thermal_energy/3_600_000*stage.buy_price_per_kWh
            cashflow = predicted_sales-predicted_purchase-predicted_thermal_cost
            net_cashflow += cashflow
            trapped_increment += result.state[2]-state[2]
            output.append({"stage": index, "duration_s": stage.duration_s, "elapsed_s": result.elapsed_s,
                "current_A": float(current), "thermal_W": float(thermal), "ambient_K": stage.ambient_K,
                "initial_state": state.tolist(), "final_state": result.state.tolist(),
                "soc_range": [float(values.min()), float(values.max())],
                "voltage_range_V": [float(result.voltages_V.min()), float(result.voltages_V.max())],
                "temperature_range_K": [float(result.states[:,4].min()), float(result.states[:,4].max())],
                "predicted_energy_J": result.energy_J, "predicted_thermal_electric_energy_J": thermal_energy,
                "predicted_cashflow": cashflow, "predicted_sales": predicted_sales,
                "predicted_purchases": predicted_purchase, "predicted_thermal_cost": predicted_thermal_cost,
                "events": result.events, "normalized_constraint_margins": stage_margin,
                "inventory_residual_mol": result.inventory_residual_mol,
                "scope": "model_prediction_not_executed_cashflow"})
            state = result.state
        margins += [float(soc(state))-terminal_floor, params.max_dod-(max(observed_soc)-min(observed_soc))]
        return {"status": "computed", "stages": output, "initial_soc": initial_soc,
                "terminal_soc": float(soc(state)), "terminal_soc_floor": terminal_floor,
                "predicted_net_cashflow": net_cashflow, "predicted_trapped_increment_mol": trapped_increment,
                "margins": margins, "constraint_sampling": "solver_nodes_and_dense_model_samples; no continuous-support certificate"}

    cache = {}
    search_phase = accept_incumbent
    failed_candidates = []
    iteration_history = []

    def commands_of(vector):
        # Third coordinate is an epigraph bound on abs(net heat). It is an
        # optimization variable, never an additional executed thermal device.
        coordinates = np.asarray(vector).reshape(-1, 3)
        return coordinates[:, :2]

    def evaluate(vector):
        key = tuple(vector)
        if key in cache:
            return cache[key]
        # Reserve one original evaluation for the finally quantized command.
        evaluation_limit=params.max_candidate_evaluations-int(search_phase)
        if counters["candidate_evaluations"] >= evaluation_limit:
            raise _Budget("Candidate evaluation budget exhausted")
        counters["candidate_evaluations"] += 1
        checkpoint("candidate")
        try:
            value = rollout(nominal_model, nominal_state, commands_of(vector), "nominal", nominal=True)
            coordinates = np.asarray(vector).reshape(-1, 3)
            effort_margins = []
            planning_cashflow = 0.0
            scale = max(abs(params.thermal_min_W), abs(params.thermal_max_W), 1e-12)
            for stage, coordinates_row, predicted in zip(stages, coordinates, value["stages"]):
                thermal, effort = float(coordinates_row[1]), float(coordinates_row[2])
                effort_margins.extend([(effort-thermal)/scale, (effort+thermal)/scale])
                effort_cost = effort*stage.duration_s/nominal_model.params.thermal_cop/3_600_000*stage.buy_price_per_kWh
                planning_cashflow += predicted["predicted_sales"]-predicted["predicted_purchases"]-effort_cost
                predicted.update(planning_thermal_effort_W=effort, planning_thermal_epigraph_cost=effort_cost)
            value["margins"] = value["margins"][:-2]+effort_margins+value["margins"][-2:]
            value["planning_cashflow_with_thermal_epigraph"] = planning_cashflow
            value["objective_scaled"] = 3_600_000*(-planning_cashflow + params.degradation_shadow_CNY_per_mol*value["predicted_trapped_increment_mol"])
        except (DomainError, InfeasibleError) as exc:
            failed_candidates.append({"candidate": counters["candidate_evaluations"], "status": "infeasible", "reason": str(exc)})
            value = {"status": "infeasible", "margins": [-1.0]*(14*len(stages)+2), "objective_scaled": 1e6+float(np.dot(vector, vector))}
        cache[key] = value
        return value

    charge_seed = min(current_limit, params.nominal_terminal_buffer*capacity.sum()*p.faraday_C_per_mol/sum(stage.duration_s for stage in stages)*1.5)
    seed_rows = []
    for stage in stages:
        thermal_seed = 0.0
        if ((params.temperature_max_K is not None and stage.ambient_K > high_t)
                or (params.temperature_min_K is not None and stage.ambient_K < low_t)):
            # A physically computed starting point holds nominal initial T.
            # The optimizer still integrates and optimizes every future move.
            thermal_seed = -float(nominal_model.rhs(0, nominal_state, -charge_seed,
                                  ambient_K=stage.ambient_K)[4])*p.thermal_capacity_J_per_K
            thermal_seed = min(params.thermal_max_W, max(params.thermal_min_W, thermal_seed))
        low_current,high_current=stage_current_bounds(stage,current_limit)
        seed_rows.append([min(high_current,max(low_current,-charge_seed)), thermal_seed, abs(thermal_seed)])
    seed = np.asarray(seed_rows).ravel()
    bounds = [limit for stage in stages for limit in (stage_current_bounds(stage,current_limit), (params.thermal_min_W, params.thermal_max_W),
              (0, max(abs(params.thermal_min_W), abs(params.thermal_max_W))))]
    def iteration(vector):
        value = evaluate(vector)
        iteration_history.append({"iteration": len(iteration_history)+1, "commands": commands_of(vector).tolist(),
                                  "objective_scaled": value["objective_scaled"], "minimum_margin": min(value["margins"])})
        diagnostics["optimization_iterations"] = iteration_history
        checkpoint("optimizer_iteration", iteration=len(iteration_history))
    try:
        checkpoint("optimizer_started")
        optimized=None
        try:
            optimized = minimize(lambda vector: evaluate(vector)["objective_scaled"], seed, method="SLSQP", bounds=bounds,
                constraints=[{"type": "ineq", "fun": lambda vector: np.asarray(evaluate(vector)["margins"])}],
                callback=iteration, options={"maxiter": params.max_iterations, "ftol": 1e-7, "eps": 1e-5})
        except _Budget as error:
            if not accept_incumbent:raise
            diagnostics["optimizer_interruption"]=str(error)
        finally:
            search_phase=False
        diagnostics["optimizer"] = ({"success": bool(optimized.success), "status": int(optimized.status),
            "message": str(optimized.message), "nit": int(optimized.nit), "nfev": int(optimized.nfev), "njev": int(optimized.njev)}
            if optimized is not None else {"success":False,"status":None,"message":"Low computation search stopped at original budget","nit":None,"nfev":None,"njev":None})
        if accept_incumbent:
            checkpoint("incumbent_selection")
            feasible=[(key,value) for key,value in cache.items() if value["status"]=="computed" and min(value["margins"])>=-params.feasibility_tolerance]
            diagnostics["incumbent_policy"]={"mode":"fully_verified_incumbent_v1","nominal_feasible_cached_count":len(feasible),
                "optimizer_converged":bool(optimized is not None and optimized.success),"optimality_proven":False,
                "acceptance_requires":"quantized nominal and every represented posterior rollout; original guards and budgets"}
            if not feasible:
                return {"status":"unknown","reason":"Low computation search has no verified feasible nominal incumbent","diagnostics":diagnostics}
            selected=min(feasible,key=lambda row:row[1]["objective_scaled"])
            raw_vector=np.asarray(selected[0]).copy()
        else:
            raw_vector=np.asarray(optimized.x).copy()
        final_vector=raw_vector.copy()
        for coordinate in range(0,len(final_vector),3):
            final_vector[coordinate]=quantize_current_towards_zero(float(final_vector[coordinate]))
        diagnostics['command_resolution']={'current_A':CURRENT_COMMAND_RESOLUTION_A,
            'rounding':'towards_zero','raw_commands':commands_of(raw_vector).tolist(),
            'final_commands':commands_of(final_vector).tolist(),
            'final_commands_reverified':False,'consumes_original_candidate_budget':True}
        if accept_incumbent:
            # Consume the reserved evaluation even if quantization left bytes unchanged.
            cache.pop(tuple(final_vector),None)
        candidate = evaluate(final_vector)
        diagnostics.update(nominal_prediction=candidate, failed_candidates=failed_candidates)
        if candidate["status"] != "computed" or min(candidate["margins"]) < -params.feasibility_tolerance:
            return {"status": "infeasible", "reason": "Bounded local search did not produce a feasible nominal sequence; global infeasibility is not proved", "diagnostics": diagnostics}
        if not accept_incumbent and not optimized.success:
            return {"status": "unknown", "reason": "Optimizer did not converge; feasible candidate is withheld", "diagnostics": diagnostics}
        commands = commands_of(final_vector)
        scenarios = []
        for index, (row, sampled_model) in enumerate(zip(samples, models)):
            try:
                value = rollout(sampled_model, row[indices], commands, f"posterior-{index}")
                value.update(posterior_index=index, weight=float(weights[index]))
            except (DomainError, InfeasibleError) as exc:
                value = {"status": "infeasible", "posterior_index": index, "weight": float(weights[index]), "reason": str(exc)}
            scenarios.append(value)
        diagnostics["scenario_predictions"] = scenarios
        diagnostics["event_coverage"] = {"represented_scenarios": len(samples), "computed_scenarios": sum(row["status"] == "computed" for row in scenarios),
            "native_model_events": ["voltage_low", "voltage_high", "temperature_low", "temperature_high", "reservoir_depleted"],
            "risk_certificate": False, "population_calibration": "not_performed"}
        all_computed = all(row["status"] == "computed" for row in scenarios)
        diagnostics["event_predictions"] = {}
        for name in diagnostics["event_coverage"]["native_model_events"]:
            indicators = [any(event["name"] == name for stage in row.get("stages", []) for event in stage["events"])
                          for row in scenarios]
            diagnostics["event_predictions"][name] = {
                "status": "estimated" if all_computed else "unknown",
                "posterior_weighted_probability": sum(float(weight)*event for weight, event in zip(weights, indicators)) if all_computed else None,
                "event_count": sum(indicators), "represented_scenarios": len(samples),
                "scope": "candidate-policy model prediction with first-native-event stopping; not independently calibrated operational probability",
                "risk_certificate": False}
        if any(row["status"] != "computed" or min(row["margins"]) < -params.feasibility_tolerance for row in scenarios):
            return {"status": "infeasible", "reason": "Candidate failed at least one represented posterior scenario; no automatic fallback was assumed feasible", "diagnostics": diagnostics}
        checkpoint("all_final_scenarios_verified")
        diagnostics['command_resolution']['final_commands_reverified']=True
        diagnostics["wall_s_worker"] = time.monotonic()-started
        return {"status": "feasible", "reason": ("Low computation incumbent: quantized nominal and all represented posterior checks passed; optimizer convergence is not required and optimality is not proved" if accept_incumbent else "Converged multi-step nominal optimization and all represented posterior candidate checks passed; empirical scope only"),
                "commands": commands.tolist(), "diagnostics": diagnostics}
    except _Budget as exc:
        diagnostics.update(failed_candidates=failed_candidates, wall_s_worker=time.monotonic()-started)
        return {"status": "unknown", "reason": str(exc), "diagnostics": diagnostics}
    except (ValueError, RuntimeError, FloatingPointError) as exc:
        diagnostics.update(numerical_failure=f"{type(exc).__name__}: {exc}", wall_s_worker=time.monotonic()-started)
        return {"status": "unknown", "reason": "A forward calculation or numerical optimization failed", "diagnostics": diagnostics}


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("This module's CLI is the controlled MPC worker only")
    payload = json.loads(sys.stdin.buffer.read(4*1024*1024+1))
    print(json.dumps(_solve(payload), allow_nan=False))
