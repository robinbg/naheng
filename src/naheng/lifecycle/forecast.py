"""Joint conditional lifetime and event forecasting from one posterior."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import time
from typing import Callable
import numpy as np

from naheng.domain.contracts import ForecastQuery, PosteriorSnapshot
from naheng.estimation.particle_filter import particle_model
from naheng.risk.forecast import estimate_events
from .capacity_protocol import CapacityProtocol, protocol_capacity


class ForecastBudgetExceeded(Exception):
    """Soft compute budget observed at solver boundaries."""


OBSERVATION_SCOPE = "finite_observed_protocol_grid_not_continuous_first_passage"


def _observation_plan_hash(query, protocol, parameters):
    """Identify a physical plan independently of its execution lineage.

    The full query hash still binds the immutable snapshot and parameter
    revision. This identifier describes the same plan across a resumed Run;
    it is never used to authenticate or reuse a forecast result.
    """
    content = {"schema": "physical_capacity_observation_plan_v2",
               "query": query.model_dump(exclude={"snapshot_id"}),
               "parameters": parameters,
               "grid_s": [0.0, query.horizon_s / 2.0, float(query.horizon_s)],
               "protocol": asdict(protocol), "scope": OBSERVATION_SCOPE}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _completed_protocol_value(diagnostic, protocol):
    """A capacity observation requires an actually completed cutoff protocol.

    Values alone, horizon delivery and competing exits are not capacity.
    This validates the existing solver result; it is no continuous certificate.
    """
    value, elapsed = diagnostic.get("capacity_C"), diagnostic.get("elapsed_s")
    events = diagnostic.get("events", [])
    if (diagnostic.get("status") != "computed" or value is None or elapsed is None
            or not np.isfinite(value) or not np.isfinite(elapsed) or value < 0 or elapsed < 0
            or elapsed > protocol.maximum_duration_s + 1e-6
            or not np.isclose(value, protocol.discharge_current_A * elapsed, rtol=1e-12, atol=1e-12)
            or not any(event.get("name") == "voltage_low" for event in events)
            or any(event.get("name") != "voltage_low" for event in events)):
        return None
    return float(value)


def forecast(snapshot: PosteriorSnapshot, query: ForecastQuery, model,
             wall_budget_s: float = 120.0,
             cancel_check: Callable[[], bool] | None = None,
             execution_context=None) -> dict:
    if wall_budget_s <= 0:
        raise ValueError("Positive forecast wall budget required")
    if snapshot.snapshot_id != query.snapshot_id:
        raise ValueError("Forecast query and posterior snapshot must match")
    if execution_context is not None:
        execution_context.prepare(snapshot,query,model)
    canonical = {"query": query.model_dump(), "parameters": asdict(model.params),
                 "parameter_revision": snapshot.parameter_revision}
    query_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    rng = np.random.default_rng(query.seed)
    samples = np.asarray(snapshot.samples)
    chosen = rng.choice(len(samples), size=query.sample_budget, replace=True, p=snapshot.weights)
    names = snapshot.state_names
    state_indices = [names.index(name) for name in model.state_names]
    rate_index = names.index("rate_scale") if "rate_scale" in names else None
    side_index = names.index("side_rate_scale") if "side_rate_scale" in names else None
    protocol_known = query.endpoint_protocol == "synthetic_capacity_v1"
    protocol = CapacityProtocol()
    observation_grid = [0.0, query.horizon_s / 2.0, float(query.horizon_s)]
    observation_plan_hash = _observation_plan_hash(query, protocol, asdict(model.params))
    paths = []
    started = time.monotonic()
    capacity_cache, integration_cache = {}, {}
    def check_work():
        if cancel_check is not None and cancel_check():
            raise InterruptedError("Forecast cancelled at a calculation checkpoint")
        if time.monotonic() - started >= wall_budget_s:
            raise ForecastBudgetExceeded("Forecast soft wall budget exhausted at solver boundary")
    cache_counts = {"capacity_protocol_solves":0, "forward_integrations":0, "reused_calculations":0}
    def cached_capacity(sampled_model, state):
        check_work()
        params_key = json.dumps(asdict(sampled_model.params), sort_keys=True, separators=(",", ":"))
        key = (params_key, tuple(np.asarray(state)), json.dumps(asdict(protocol), sort_keys=True))
        if key in capacity_cache:
            cache_counts["reused_calculations"] += 1
            return capacity_cache[key]
        cache_counts["capacity_protocol_solves"] += 1
        value = (execution_context.capacity(sampled_model,state,protocol) if execution_context is not None
                 else protocol_capacity(sampled_model,state,protocol))
        capacity_cache[key] = value
        return value
    def capacity_attempt(sampled_model, state):
        try:
            return cached_capacity(sampled_model, state)
        except (ValueError, RuntimeError) as error:
            return {"status": "unknown", "capacity_C": None,
                    "reason": "capacity_solver_failed", "failure_detail": str(error)}
    def cached_integrate(sampled_model, state, duration_s):
        check_work()
        params_key = json.dumps(asdict(sampled_model.params), sort_keys=True, separators=(",", ":"))
        key = (params_key, tuple(np.asarray(state)), query.current_A, duration_s, query.ambient_K)
        if key in integration_cache:
            cache_counts["reused_calculations"] += 1
            return integration_cache[key]
        cache_counts["forward_integrations"] += 1
        value = sampled_model.integrate(state, query.current_A, duration_s, ambient_K=query.ambient_K)
        integration_cache[key] = value
        return value
    def record_observation(path, actual_time, diagnostic, planned_time, kind="planned_grid"):
        value = _completed_protocol_value(diagnostic, protocol)
        path["capacity_observations"].append({"planned_time_s": planned_time,
            "calculation_order": len(path["capacity_observations"]),
            "actual_observation_time_s": float(actual_time) if value is not None else None,
            "attempted_at_time_s": float(actual_time), "observation_kind": kind,
            "status": "observed" if value is not None else "protocol_unknown",
            "capacity_C": value, "threshold_C": path["capacity_threshold_C"],
            "at_or_below_threshold": value <= path["capacity_threshold_C"]
                if value is not None and path["capacity_threshold_C"] is not None else None,
            "reason": None if value is not None else diagnostic.get("reason", "incomplete_capacity_protocol"),
            "protocol_result": diagnostic})
    def finish_observation_scope(path):
        path["capacity_observations"].sort(key=lambda entry: (entry["attempted_at_time_s"], entry["calculation_order"]))
        observed = [entry for entry in path["capacity_observations"] if entry["status"] == "observed"]
        observed_grid = {entry["planned_time_s"] for entry in observed if entry["observation_kind"] == "planned_grid"}
        unmeasured = [t for t in observation_grid if t not in observed_grid]
        last = max((entry["actual_observation_time_s"] for entry in observed), default=None)
        below = [entry["actual_observation_time_s"] for entry in observed if entry["at_or_below_threshold"] is True]
        complete = not unmeasured and path["capacity_threshold_C"] is not None
        no_crossing = complete and not below
        path.update(observation_last_time_s=last, observation_unmeasured_grid_s=unmeasured,
            observation_first_below_time_s=min(below) if below else None,
            observation_grid_complete=complete,
            observation_right_censored=True if no_crossing else False if complete else None,
            observation_censor_time_s=last if no_crossing else None,
            observation_status="grid_right_censored" if no_crossing else "threshold_seen_on_grid" if complete
                else "observation_partial" if observed else "observation_unknown")
    for path_id, index in enumerate(chosen):
        row = samples[int(index)]
        sampled_model = particle_model(model, row[rate_index] if rate_index is not None else 1.0,
            row[side_index] if side_index is not None else 1.0)
        state = row[state_indices].copy()
        execution_audit=None
        if execution_context is not None:
            sampled_model,state,execution_audit=execution_context.particle(sampled_model,row)
        path = {"path_id": path_id, "posterior_index": int(index), "status": "computed",
                "events": [], "energy_J": 0.0, "elapsed_s": 0.0,
                "rul_s": None, "right_censored": None, "censor_reason": "first_passage_unverified",
                "first_passage_status": "unknown", "censoring": "first_passage_unverified",
                "capacity_initial_C": None, "capacity_final_C": None,
                "final_state": None, "future_policy_id": query.future_policy_id,
                "endpoint_status": "unknown", "capacity_threshold_C": None,
                "capacity_baseline_protocol": None, "capacity_observations": [],
                "observation_plan_hash": observation_plan_hash, "observation_scope": OBSERVATION_SCOPE,
                "observation_last_time_s": None, "observation_unmeasured_grid_s": observation_grid.copy(),
                "observation_first_below_time_s": None, "observation_grid_complete": False,
                "observation_right_censored": None, "observation_censor_time_s": None,
                "observation_status": "observation_unknown"}
        if execution_audit is not None:
            path.update(theory_execution=execution_audit,executed_state_names=list(sampled_model.state_names),
                        executed_state_units=list(sampled_model.state_units),executed_state_dimension=len(state))
        try:
            check_work()
        except ForecastBudgetExceeded:
            path.update(status="not_run_budget", failure_reason="forecast_wall_budget_exhausted",
                        censor_reason="forecast_wall_budget_exhausted")
            paths.append(path)
            continue
        try:
            # All endpoints use an explicit discharge protocol. Missing endpoint
            # information does not prevent the independent event forecast.
            baseline = initial_capacity = None
            if protocol_known:
                pristine = sampled_model.initial_state(soc=protocol.initial_occupancy)
                baseline = capacity_attempt(sampled_model, pristine)
                path["capacity_baseline_protocol"] = baseline
                baseline_value = _completed_protocol_value(baseline, protocol)
                if baseline_value is not None and baseline_value > 0:
                    path["capacity_threshold_C"] = protocol.retirement_ratio * baseline_value
                check_work()
                initial_capacity = capacity_attempt(sampled_model, state)
                record_observation(path, 0.0, initial_capacity, 0.0)
                actual_initial_value = _completed_protocol_value(initial_capacity, protocol)
                path["capacity_initial_C"] = actual_initial_value
                if baseline_value is not None and baseline_value > 0 and actual_initial_value is not None:
                    path["endpoint_status"] = "evaluated"
                    if (baseline_value is not None and baseline_value > 0 and actual_initial_value is not None
                            and actual_initial_value <= protocol.retirement_ratio * baseline_value):
                        path.update(rul_s=0.0, right_censored=False, censor_reason=None,
                                    first_passage_status="observed_at_origin", censoring="observed")
                check_work()
            elif not protocol_known:
                path["censor_reason"] = "unknown_endpoint_protocol"
            result = cached_integrate(sampled_model, state, query.horizon_s)
            path.update(events=result.events, energy_J=result.energy_J, elapsed_s=result.elapsed_s,
                        final_state=result.state.tolist(),
                        final_voltage_V=sampled_model.observe(result.state, query.current_A)["voltage_V"],
                        final_temperature_K=float(result.state[sampled_model.state_names.index("temperature_K")]),
                        inventory_residual_mol=result.inventory_residual_mol)
            if execution_context is not None:
                path.update(execution_context.outputs(sampled_model,result.state,query.current_A))
            check_work()
            if protocol_known:
                middle_time = observation_grid[1]
                if result.elapsed_s >= middle_time:
                    intermediate = cached_integrate(sampled_model, state, middle_time)
                    check_work()
                    middle_capacity = capacity_attempt(sampled_model, intermediate.state)
                    # The time belongs to the integrated state, never the request.
                    middle_reached = intermediate.elapsed_s >= middle_time
                    record_observation(path, intermediate.elapsed_s, middle_capacity,
                        middle_time if middle_reached else None,
                        "planned_grid" if middle_reached else "terminal_event")
                    check_work()
                final_capacity = capacity_attempt(sampled_model, result.state)
                path["capacity_final_C"] = _completed_protocol_value(final_capacity, protocol)
                horizon_reached = result.elapsed_s >= query.horizon_s
                if result.elapsed_s > 0 or not path["capacity_observations"]:
                    record_observation(path, result.elapsed_s, final_capacity,
                        float(query.horizon_s) if horizon_reached else None,
                        "planned_grid" if horizon_reached else "terminal_event")
                check_work()
            if protocol_known and path["rul_s"] is None:
                if (path["capacity_threshold_C"] is not None and path["capacity_final_C"] is not None
                        and path["capacity_initial_C"] is not None):
                    threshold = path["capacity_threshold_C"]
                    if path["capacity_final_C"] <= threshold:
                        # A real local above/below bracket does not identify the
                        # first retirement when protocol-capacity monotonicity
                        # has no certificate. Preserve the observations and a
                        # broad first-passage enclosure, without promoting the
                        # local right endpoint to an exact/precise RUL sample.
                        left, right = 0.0, result.elapsed_s
                        for _ in range(5):
                            middle = (left + right) / 2
                            intermediate = cached_integrate(sampled_model, state, middle)
                            check_work()
                            diagnostic = capacity_attempt(sampled_model, intermediate.state)
                            # These actual extra probes are not planned grid points.
                            record_observation(path, intermediate.elapsed_s, diagnostic, None, "bracket_probe")
                            check_work()
                            diagnostic_value = _completed_protocol_value(diagnostic, protocol)
                            if diagnostic_value is None:
                                break
                            if diagnostic_value <= threshold:
                                right = intermediate.elapsed_s
                            else:
                                left = middle
                        path.update(rul_s=None, observed_crossing_bracket_s=[left, right],
                                    first_passage_enclosure_s=[0.0, right],
                                    right_censored=False, censoring="interval",
                                    first_passage_status="unknown",
                                    censor_reason="protocol_capacity_monotonicity_unverified")
                    elif result.elapsed_s < query.horizon_s - 1e-6:
                        path["censor_reason"] = "operational_event_before_retirement"
                else:
                    path["censor_reason"] = "capacity_protocol_unknown"
                    path["endpoint_status"] = "unknown"
        except ForecastBudgetExceeded as error:
            path.update(status="budget_interrupted", failure_reason=str(error),
                        censor_reason="forecast_wall_budget_exhausted",
                        rul_s=None, right_censored=None, endpoint_status="unknown")
        except (ValueError, RuntimeError) as error:
            path.update(status="failed", failure_reason=str(error), censor_reason="forward_solver_failed",
                        rul_s=None, right_censored=None, endpoint_status="unknown")
        finish_observation_scope(path)
        paths.append(path)
    uncensored = [path["rul_s"] for path in paths if path["rul_s"] is not None]
    computed = [path for path in paths if path["status"] == "computed"]
    result = {"snapshot_id": snapshot.snapshot_id, "run_id": snapshot.run_id,
        "query_hash": query_hash, "query": query.model_dump(),
        "model_package_id": snapshot.model_package_id,
        "parameter_revision": snapshot.parameter_revision,
        "provenance_type": "synthetic", "accelerated_synthetic": model.params.accelerated_synthetic,
        "risk": estimate_events(paths, model),
        "rul": {"status": "conditional" if protocol_known and any(p["first_passage_status"] == "observed_at_origin" for p in computed) else "unknown",
            "endpoint_protocol": query.endpoint_protocol, "threshold_ratio": protocol.retirement_ratio,
            "samples_s": uncensored, "right_censored_count": sum(path["right_censored"] is True for path in paths),
            "unknown_first_passage_count": sum(path["right_censored"] is None for path in paths),
            "failed_path_count": len(paths) - len(computed),
            "interval_censored_count": sum(path.get("censoring") == "interval" for path in paths),
            "horizon_s": query.horizon_s,
            "median_observed_s": float(np.median(uncensored)) if uncensored else None,
            "distribution_complete": bool(paths) and all(path["rul_s"] is not None for path in paths),
            "reason": "unknown_endpoint_protocol" if not protocol_known else "first_passage_or_protocol_monotonicity_unverified",
            "uncalibrated_initialization_mapping": True,
            "monotonic_capacity_status": "unknown",
            "monotonic_capacity_assumption": None,
            "first_passage_error_bound_status": "unknown",
            "endpoint_evaluation_scope": "Actual protocol observations and local crossing brackets; no certified whole-time capacity order or crossing-slope bound",
            "capacity_observation_schema": "finite_protocol_grid_v1",
            "capacity_observation_scope": OBSERVATION_SCOPE,
            "capacity_observation_grid_s": observation_grid,
            "capacity_observation_plan_hash": observation_plan_hash,
            "observation_requested_path_denominator": len(paths),
            "observation_complete_path_count": sum(p["observation_grid_complete"] for p in paths),
            "grid_right_censored_count": sum(p["observation_right_censored"] is True for p in paths),
            "observation_unknown_path_count": sum(p["observation_right_censored"] is None for p in paths),
            "observation_partial_path_count": sum(p["observation_status"] == "observation_partial" for p in paths),
            "future_policy_id": query.future_policy_id, "environment_id": query.environment_id},
        "paths": paths,
        "budget": {"requested_paths": query.sample_budget,
                   "attempted_paths": sum(p["status"] != "not_run_budget" for p in paths),
                   "completed_paths": len(computed), "wall_budget_s": wall_budget_s,
                   "unique_solves": cache_counts["capacity_protocol_solves"] + cache_counts["forward_integrations"],
                   **cache_counts, "independent_operational_trajectories": 0,
                   "cache_scope": "exact_inputs_within_this_query",
                   "budget_check_scope": "before_and_after_protocol_and_forward_solver_calls",
                   "wall_budget_kind": "soft_checked_at_solver_boundaries",
                   "walltime_s": time.monotonic() - started,
                    "exhausted": any(p["status"] in ("not_run_budget","budget_interrupted") for p in paths)},
        "coverage": "conditional_model_predictions_not_real_cell_lifetime_or_safety_guarantee"}
    if execution_context is not None:
        result["theory_runtime"]=execution_context.summary(paths)
    return result
