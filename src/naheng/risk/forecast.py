"""Event-specific posterior predictive estimates, distinct from guarantees."""
from __future__ import annotations


def estimate_events(paths: list[dict], model) -> dict:
    definitions = {
        "voltage_low": {"observable": "voltage_V", "relation": "<=", "limit": model.params.voltage_min_V},
        "voltage_high": {"observable": "voltage_V", "relation": ">=", "limit": model.params.voltage_max_V},
        "temperature_low": {"observable": "temperature_K", "relation": "<=", "limit": model.params.temperature_min_K},
        "temperature_high": {"observable": "temperature_K", "relation": ">=", "limit": model.params.temperature_max_K},
        "reservoir_depleted": {"observable": "reservoir_mol", "relation": "<=", "limit": 0.0},
    }
    results = {}
    completed = [path for path in paths if path["status"] == "computed"]
    failed_count = len(paths) - len(completed)
    for name, definition in definitions.items():
        count = sum(any(event["name"] == name for event in path["events"]) for path in completed)
        results[name] = {"status": "estimated" if completed and not failed_count else "unknown",
            "probability": count / len(completed) if completed and not failed_count else None,
            "successful_path_probability": count / len(completed) if completed else None,
            "event_count": count, "posterior_predictive_samples": len(completed),
            "definition": definition, "evidence_category": "empirical",
            "reason": ("incomplete_forward_ensemble" if failed_count and completed
                       else None if completed else "no_successful_forward_paths"),
            "observation_scope": "first_terminal_constraint_under_stop_on_event_policy",
            "not_an_independent_operational_risk_certificate": True}
    for name, reason in {
        "sodium_plating": "no_plating_mechanism_or_calibrated_proxy_in_this_model",
        "fire": "no_fire_mechanism_or_incident_labels_in_this_model",
    }.items():
        results[name] = {"status": "unknown", "probability": None, "reason": reason,
                         "evidence_category": "none"}
    return {"events": results, "completed_paths": len(completed),
            "failed_paths": len(paths) - len(completed), "risk_certificate": False,
            "estimator": "posterior_predictive_monte_carlo", "provenance_type": "synthetic"}
