"""Fixed, auditable baseline policies under common physical constraints.

Rule trajectories are first-action predictions over all represented joint
particles. Nominal planning uses the existing bounded MPC unchanged. Neither
path is a continuous-support certificate or an executed cashflow history.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from naheng.control.mpc import MPCParameters, MPCPlan, MPCStage, plan as nominal_plan
from naheng.control.rules import RuleParameters, propose as rule_propose
from naheng.domain.contracts import Action, PosteriorSnapshot
from naheng.estimation.particle_filter import particle_model
from naheng.models.site_model import DomainError, InfeasibleError, SiteModel, SiteParameters
from naheng.risk.admission import check
from naheng.runtime import forecast_jobs as physical_binding
from naheng.runtime.process_tree import ProcessTree


@dataclass(frozen=True)
class FixedBaselinePolicy:
    policy_id: str
    kind: str
    current_limit_A: float
    voltage_margin_V: float
    soc_margin: float
    temperature_margin_K: float
    charge_below_price: float = 0.12
    discharge_above_price: float = 0.25
    nominal_terminal_buffer: float | None = None

    def __post_init__(self):
        if not isinstance(self.policy_id, str) or not self.policy_id.strip() or len(self.policy_id) > 128:
            raise ValueError("A nonempty bounded policy identity is required")
        if self.kind not in {"rules", "nominal"}:
            raise ValueError("Fixed baseline kind must be rules or nominal")
        values = [value for name, value in asdict(self).items() if name not in {"policy_id", "kind", "nominal_terminal_buffer"}]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            raise ValueError("Finite numeric policy limits and tariffs are required")
        if self.current_limit_A <= 0 or min(self.voltage_margin_V, self.soc_margin, self.temperature_margin_K) < 0:
            raise ValueError("Positive current and nonnegative fixed margins are required")
        if not 0 <= self.charge_below_price <= self.discharge_above_price:
            raise ValueError("Nonnegative, ordered charge/discharge thresholds are required")
        if self.nominal_terminal_buffer is not None:
            value = self.nominal_terminal_buffer
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("Nominal terminal buffer must be finite, nonboolean and nonnegative, or None")
            if self.kind == "rules" and value != 0:
                raise ValueError("A nonzero nominal terminal buffer is unsupported by the first-action rule policy")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _bind(snapshot, model, package):
    if len(snapshot.state_names) != len(set(snapshot.state_names)):
        raise ValueError("Duplicate posterior column identities are forbidden")
    if len(snapshot.samples) > 256:
        raise ValueError("At most 256 represented joint samples are supported")
    root = Path(physical_binding.__file__).resolve().parents[3]
    bound = physical_binding._package_model(package, root, snapshot)
    if _hash(asdict(bound.params)) != _hash(asdict(model.params)):
        raise ValueError("Supplied physical model differs from registered parameters")
    for name in ("rate_scale", "side_rate_scale"):
        if snapshot.state_names.count(name) != 1 or snapshot.state_units[snapshot.state_names.index(name)] != "1":
            raise ValueError("Explicit dimensionless joint rate and side parameter columns are required")
    for row in snapshot.samples:
        particle_model(model, row[snapshot.state_names.index("rate_scale")], row[snapshot.state_names.index("side_rate_scale")])
    return root


def _tighten(parameters, policy, model, package):
    """Only intersect a fixed policy with the common physical problem."""
    low_t = max(model.params.temperature_min_K, package["domain"]["temperature_K"][0],
        parameters.temperature_min_K if parameters.temperature_min_K is not None else model.params.temperature_min_K)
    high_t = min(model.params.temperature_max_K, package["domain"]["temperature_K"][1],
        parameters.temperature_max_K if parameters.temperature_max_K is not None else model.params.temperature_max_K)
    low_v = max(model.params.voltage_min_V + parameters.voltage_margin_V,
        parameters.voltage_min_V if parameters.voltage_min_V is not None else model.params.voltage_min_V)
    high_v = min(model.params.voltage_max_V - parameters.voltage_margin_V,
        parameters.voltage_max_V if parameters.voltage_max_V is not None else model.params.voltage_max_V)
    low_v = max(low_v, model.params.voltage_min_V + policy.voltage_margin_V)
    high_v = min(high_v, model.params.voltage_max_V - policy.voltage_margin_V)
    low_t, high_t = low_t + policy.temperature_margin_K, high_t - policy.temperature_margin_K
    low_soc, high_soc = parameters.soc_min + policy.soc_margin, parameters.soc_max - policy.soc_margin
    if low_t >= high_t or low_v >= high_v or low_soc >= high_soc:
        raise ValueError("Fixed margins leave no admissible output or SOC range")
    if parameters.terminal_soc_min is not None and not low_soc <= parameters.terminal_soc_min <= high_soc:
        raise ValueError("Fixed SOC margins conflict with the common terminal SOC floor")
    # This fixed tuning knob increases the original nominal reserve only.
    # The original MPC still checks every represented scenario terminal SOC;
    # the reserve does not certify full continuous posterior support.
    nominal_buffer = parameters.nominal_terminal_buffer
    if policy.kind == "nominal" and policy.nominal_terminal_buffer is not None:
        nominal_buffer = max(nominal_buffer, policy.nominal_terminal_buffer)
    return replace(parameters, current_limit_A=min(parameters.current_limit_A, policy.current_limit_A),
        soc_min=low_soc, soc_max=high_soc, temperature_min_K=low_t, temperature_max_K=high_t,
        voltage_min_V=low_v, voltage_max_V=high_v,
        voltage_margin_V=max(parameters.voltage_margin_V, policy.voltage_margin_V),
        nominal_terminal_buffer=nominal_buffer)


def propose(snapshot: PosteriorSnapshot, model: SiteModel, package: dict, stages,
            *, policy: FixedBaselinePolicy, parameters: MPCParameters,
            admission_mode: str = "empirical") -> MPCPlan:
    """Return only an admitted first action, with a bounded, genuine prediction.

The rule policy has no claimed terminal plan. The caller applies the common
realized terminal test after execution. A nominal future plan is never an
execution history. All zero-weight represented rows are checked too.
    """
    started = time.monotonic()
    if type(policy) is not FixedBaselinePolicy or type(parameters) is not MPCParameters:
        raise TypeError("Declared FixedBaselinePolicy and original MPCParameters required")
    policy, parameters = FixedBaselinePolicy(**asdict(policy)), MPCParameters(**asdict(parameters))
    if not isinstance(snapshot, PosteriorSnapshot) or type(model) is not SiteModel:
        raise TypeError("A posterior snapshot and exact declared SiteModel are required")
    snapshot = PosteriorSnapshot.model_validate(snapshot.model_dump(mode="json"))
    package = deepcopy(package)
    stages = tuple(stages)
    if not 2 <= len(stages) <= 8 or any(type(stage) is not MPCStage for stage in stages):
        raise ValueError("2..8 explicit finite MPC stages are required")
    stages = tuple(MPCStage(**asdict(stage)) for stage in stages)
    if admission_mode not in {"empirical", "strict"}:
        raise ValueError("Unsupported admission mode")
    source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    nominal_sha = hashlib.sha256(Path(sys.modules[nominal_plan.__module__].__file__).read_bytes()).hexdigest()
    base = {"algorithm": "fixed_margin_" + policy.kind, "policy": asdict(policy),
        "common_parameters": asdict(parameters), "fixed_baseline_source_sha256": source_sha,
        "nominal_mpc_source_sha256": nominal_sha, "snapshot_id": snapshot.snapshot_id,
        "snapshot_content_sha256": _hash(snapshot.model_dump(mode="json")),
        "model_package_id": snapshot.model_package_id, "parameter_revision": snapshot.parameter_revision,
        "package_hash": package.get("package_hash"), "parameter_hash": package.get("parameter_hash"),
        "physical_source_hashes": deepcopy(package.get("binding_hashes", {})),
        "original_weights": list(snapshot.weights), "joint_state_parameter_rows_sha256": _hash(snapshot.samples),
        "weights_sha256": _hash(snapshot.weights), "risk_certificate": False,
        "evidence_category": "empirical", "provenance_type": "synthetic",
        "prediction_is_executed_cashflow": False, "only_first_action_executable": True,
        "future_plan_is_execution_history": False,
        "terminal_scope": "common realized terminal condition belongs to the caller; rule first-action prediction is not terminal verification",
        "wall_budget_s": parameters.wall_budget_s, "integration_calls": 0}

    def stop(status, reason, extra=None):
        return MPCPlan(status, reason, snapshot.snapshot_id, (), {**base, **(extra or {}), "wall_s": time.monotonic()-started})

    try:
        _bind(snapshot, model, package)
        tight = _tighten(parameters, policy, model, package)
    except (ValueError, OSError, KeyError) as exc:
        return stop("unknown", "Physical/source/fixed-policy applicability failed: " + str(exc))
    base["effective_parameters"] = asdict(tight)
    zero = Action(action_id="fixed-baseline-applicability", snapshot_id=snapshot.snapshot_id,
        start_s=snapshot.obs_until_s, duration_s=stages[0].duration_s, current_A=0)
    admission = check(snapshot, zero, package, stages[0].ambient_K, mode=admission_mode)
    base["admission"] = admission
    if admission["decision"] != "accept":
        return stop("infeasible" if admission["decision"] == "reject" else "unknown", admission["reason"])
    remaining = parameters.wall_budget_s - (time.monotonic()-started)
    if remaining <= 0:
        return stop("unknown", "Fixed baseline budget exhausted before worker launch")
    if policy.kind == "nominal":
        response = nominal_plan(snapshot, model, package, stages,
            parameters=replace(tight, wall_budget_s=remaining), admission_mode=admission_mode)
        diagnostics = {**response.diagnostics, **base,
            "nominal_diagnostics": response.diagnostics,
            "integration_calls": response.diagnostics.get("counters", {}).get("integration_calls", 0)}
        try:
            _bind(snapshot, model, package)
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != source_sha or hashlib.sha256(Path(sys.modules[nominal_plan.__module__].__file__).read_bytes()).hexdigest() != nominal_sha:
                raise ValueError("Baseline or nominal source changed during computation")
        except (ValueError, OSError) as exc:
            return stop("unknown", "Fresh source binding failed before first-action release: " + str(exc), diagnostics)
        if time.monotonic()-started >= parameters.wall_budget_s:
            return stop("unknown", "Common baseline wall budget exhausted; computed candidate withheld", diagnostics)
        return MPCPlan(response.status, response.reason, response.snapshot_id,
            response.planned_actions if response.status == "feasible" else (), {**diagnostics, "wall_s": time.monotonic()-started})

    payload = {"snapshot": snapshot.model_dump(mode="json"), "model_parameters": asdict(model.params),
        "package": package, "policy": asdict(policy), "parameters": asdict(tight),
        "stage": asdict(stages[0]), "admission_mode": admission_mode, "source_sha256": source_sha}
    encoded = json.dumps(payload, allow_nan=False).encode()
    if len(encoded) > 4*1024*1024:
        return stop("unknown", "Fixed baseline input exceeds bounded byte budget")
    argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker"]
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(Path(physical_binding.__file__).resolve().parents[2]),
            "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
        start_new_session=os.name != "nt", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    tree = ProcessTree(proc)
    base.update(worker_argv=argv, owned_pid=proc.pid)
    try:
        try:
            stdout, stderr = proc.communicate(encoded, timeout=max(.001, parameters.wall_budget_s-(time.monotonic()-started)))
        except subprocess.TimeoutExpired:
            killed = tree.terminate()
            stdout, stderr = proc.communicate(timeout=10)
            return stop("unknown", "Owned rule integrator exceeded the common wall budget", {
                "timed_out": True, "termination": killed, "worker_returncode": proc.returncode,
                "worker_stderr": stderr.decode(errors="replace")[-32768:]})
        base.update(worker_returncode=proc.returncode, timed_out=False, worker_stderr=stderr.decode(errors="replace")[-32768:])
        if proc.returncode != 0:
            return stop("unknown", "Rule prediction worker failed")
        try:
            result = json.loads(stdout)
        except (ValueError, UnicodeError):
            return stop("unknown", "Rule worker produced invalid calculation evidence")
        base.update(result["diagnostics"])
        if result["status"] != "feasible":
            return stop(result["status"], result["reason"])
        try:
            _bind(snapshot, model, package)
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != source_sha:
                raise ValueError("Baseline source changed during prediction")
        except (ValueError, OSError) as exc:
            return stop("unknown", "Fresh source binding failed before first-action release: " + str(exc))
        if time.monotonic()-started >= parameters.wall_budget_s:
            return stop("unknown", "Common baseline wall budget exhausted; computed rule withheld")
        action = Action.model_validate(result["action"])
        final = check(snapshot, action, package, stages[0].ambient_K, mode=admission_mode)
        base["admission"] = final
        if final["decision"] != "accept":
            return stop("unknown" if final["decision"] == "unknown" else "infeasible", final["reason"])
        return MPCPlan("feasible", result["reason"], snapshot.snapshot_id, (action,),
            {**base, "wall_s": time.monotonic()-started})
    finally:
        tree.close()


def _rule_worker(payload):
    snapshot = PosteriorSnapshot.model_validate(payload["snapshot"])
    model = SiteModel(SiteParameters(**payload["model_parameters"]))
    policy, params = FixedBaselinePolicy(**payload["policy"]), MPCParameters(**payload["parameters"])
    stage, package = MPCStage(**payload["stage"]), payload["package"]
    diagnostics = {"integration_calls": 0, "completed_integrations": 0, "scenario_predictions": [],
        "constraint_sampling": "solver_nodes_and_dense_model_samples; no continuous-support certificate",
        "tariffs": asdict(stage), "risk_certificate": False}
    try:
        _bind(snapshot, model, package)
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != payload["source_sha256"]:
            raise ValueError("Worker source changed before calculation")
        rule = RuleParameters(current_limit_A=min(params.current_limit_A, package["domain"]["max_current_A"]),
            soc_min=params.soc_min, soc_max=params.soc_max,
            temperature_min_K=params.temperature_min_K, temperature_max_K=params.temperature_max_K,
            cooling_above_K=min(308.15, params.temperature_max_K),
            cooling_W=min(.1, abs(params.thermal_min_W)),
            charge_below_price=policy.charge_below_price,
            discharge_above_price=max(policy.discharge_above_price, stage.buy_price_per_kWh+1))
        # A cheap buy price can trigger charging, regardless of the sell price.
        charge = rule_propose(snapshot, stage.buy_price_per_kWh, snapshot.obs_until_s, stage.duration_s, rule)
        if charge.current_A < 0:
            action, selected = charge, "charge_using_buy_price"
        else:
            # Nonnegative sell tariffs cannot trigger this deliberately disabled charge branch.
            sell_rule = replace(rule, charge_below_price=-1, discharge_above_price=policy.discharge_above_price)
            action = rule_propose(snapshot, stage.sell_price_per_kWh, snapshot.obs_until_s, stage.duration_s, sell_rule)
            selected = "discharge_using_sell_price" if action.current_A > 0 else "idle"
        diagnostics["price_decision"] = selected
        diagnostics["proposed_action"] = action.model_dump(mode="json")
        adm = check(snapshot, action, package, stage.ambient_K, mode=payload["admission_mode"])
        diagnostics["worker_admission"] = adm
        if adm["decision"] != "accept":
            return {"status": "unknown" if adm["decision"] == "unknown" else "infeasible", "reason": adm["reason"], "diagnostics": diagnostics}
        positions = [snapshot.state_names.index(name) for name in model.state_names]
        capacities = np.asarray(model.params.site_capacity_mol)
        tolerance = params.feasibility_tolerance
        for index, (row, weight) in enumerate(zip(snapshot.samples, snapshot.weights)):
            sampled = particle_model(model, row[snapshot.state_names.index("rate_scale")], row[snapshot.state_names.index("side_rate_scale")])
            state = np.asarray([row[i] for i in positions])
            diagnostics["integration_calls"] += 1
            print("FIXED_BASELINE_PROGRESS " + json.dumps({"phase": "integrating", "posterior_index": index,
                "integration_calls": diagnostics["integration_calls"]}), file=sys.stderr, flush=True)
            result = sampled.integrate(state, action.current_A, action.duration_s,
                ambient_K=stage.ambient_K, thermal_W=action.thermal_W, max_step_s=params.prediction_max_step_s)
            diagnostics["completed_integrations"] += 1
            soc_values = result.states[:, :2] @ capacities / capacities.sum()
            band_limits = []
            for value in soc_values:
                lower, matches = 0.0, []
                for upper, charge_limit, discharge_limit in params.soc_bands:
                    if lower-1e-12 <= value <= upper+1e-12:
                        matches.append(charge_limit if action.current_A < 0 else discharge_limit)
                    lower = upper
                band_limits.append(min([params.current_limit_A, *matches]) if matches else 0)
            margins = {"soc_low": float(soc_values.min()-params.soc_min),
                "soc_high": float(params.soc_max-soc_values.max()),
                "voltage_low_V": float(result.voltages_V.min()-params.voltage_min_V),
                "voltage_high_V": float(params.voltage_max_V-result.voltages_V.max()),
                "temperature_low_K": float(result.states[:,4].min()-params.temperature_min_K),
                "temperature_high_K": float(params.temperature_max_K-result.states[:,4].max()),
                "soc_band_current_A": min(band_limits)-abs(action.current_A),
                "max_dod": params.max_dod-float(soc_values.max()-soc_values.min()),
                "elapsed_s": result.elapsed_s-action.duration_s,
                "thermal_low_W": action.thermal_W-params.thermal_min_W,
                "thermal_high_W": params.thermal_max_W-action.thermal_W}
            sales = max(0, result.energy_J)/3_600_000*stage.sell_price_per_kWh
            purchase = max(0, -result.energy_J)/3_600_000*stage.buy_price_per_kWh
            thermal_cost = result.thermal_management_energy_J/3_600_000*stage.buy_price_per_kWh
            good = not result.events and all(value >= -tolerance for value in margins.values())
            diagnostics["scenario_predictions"].append({"posterior_index": index, "weight": weight,
                "joint_row_sha256": _hash(row), "status": "computed" if good else "infeasible",
                "initial_state": state.tolist(), "final_state": result.state.tolist(),
                "initial_soc": float(state[:2] @ capacities/capacities.sum()),
                "final_soc": float(soc_values[-1]), "duration_s": action.duration_s, "elapsed_s": result.elapsed_s,
                "events": result.events, "constraint_margins": margins, "inventory_residual_mol": result.inventory_residual_mol,
                "predicted_energy_J": result.energy_J,
                "predicted_thermal_electric_energy_J": result.thermal_management_energy_J,
                "predicted_sales": sales, "predicted_purchases": purchase,
                "predicted_thermal_cost": thermal_cost, "predicted_cashflow": sales-purchase-thermal_cost,
                "scope": "first_action_model_prediction_not_execution_or_terminal_certificate"})
        if any(row["status"] != "computed" for row in diagnostics["scenario_predictions"]):
            return {"status": "infeasible", "reason": "Fixed rule failed a represented first-action constraint; no fallback released", "diagnostics": diagnostics}
        diagnostics["weighted_first_action_predicted_cashflow_CNY"] = sum(row["weight"]*row["predicted_cashflow"] for row in diagnostics["scenario_predictions"])
        return {"status": "feasible", "reason": "Fixed rule first-action prediction passed every represented joint row; empirical scope only",
            "action": action.model_dump(mode="json"), "diagnostics": diagnostics}
    except (ValueError, OSError, KeyError, DomainError, InfeasibleError) as exc:
        return {"status": "unknown", "reason": "Rule forward calculation or binding failed: " + str(exc), "diagnostics": diagnostics}


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("This module exposes only its controlled prediction worker")
    payload = json.loads(sys.stdin.buffer.read(4*1024*1024+1))
    print(json.dumps(_rule_worker(payload), allow_nan=False))
