"""Apply the declared sodium coefficients to an actually integrated interval.

The residual criterion is an empirical numerical check, not a T3 error bound.
The shared reservoir and total trapped product each enter exactly once.
"""
from __future__ import annotations
import math
import numpy as np


def check_sodium_interval(model, initial, result, current_A, ambient_K, thermal_W,
                          *, evidence_refs=()):
    weights = np.array([*model.params.site_capacity_mol, 1.0, 1.0, 0.0])
    initial = np.asarray(initial, dtype=float)
    states = np.asarray(result.states, dtype=float)
    final = np.asarray(result.state, dtype=float)
    if initial.shape != (5,) or final.shape != (5,) or states.ndim != 2 or states.shape[1] != 5:
        raise ValueError("Actual five-state interval required for sodium accounting")
    if not np.all(np.isfinite(initial)) or not np.all(np.isfinite(states)) or not np.all(np.isfinite(final)):
        raise ValueError("Nonfinite state cannot establish numerical inventory validity")
    before = float(weights @ initial)
    residuals = states @ weights - before
    final_residual = float(weights @ final - before)
    # This scales the solver's documented local tolerance as a review criterion.
    # It is not a proven global bound, nor evidence about an actual battery.
    scale = np.maximum(np.abs(initial), np.max(np.abs(np.vstack([states, final])), axis=0))
    tolerance = float(np.abs(weights) @ (1e-10 + 1e-7 * scale))
    rhs_residuals = [float(weights @ model.rhs(float(t), state, current_A, ambient_K, thermal_W))
                     for t, state in zip(result.times_s, states, strict=True)]
    max_residual = max(abs(final_residual), float(np.max(np.abs(residuals))))
    max_rate_residual = max(map(abs, rhs_residuals), default=math.inf)
    reported = float(result.inventory_residual_mol)
    reported_matches = math.isfinite(reported) and abs(reported - final_residual) <= 1e-14
    passed = max_residual <= tolerance and max_rate_residual <= 1e-12 and reported_matches
    return {"name": "sodium_interval_inventory", "status": "PASS" if passed else "FAIL",
            "initial_inventory_mol": before, "final_inventory_mol": float(weights @ final),
            "final_residual_mol": final_residual, "max_sampled_residual_mol": max_residual,
            "max_sampled_rhs_residual_mol_per_s": max_rate_residual,
            "reported_residual_matches": reported_matches, "sample_count": len(states),
            "state_coefficients": weights.tolist(), "expected_external_sodium_delta_mol": 0.0,
            "numerical_review_tolerance_mol": tolerance, "evidence_refs": list(evidence_refs),
            "scope": "Declared closed sodium system including one shared reservoir; sampled numerical consistency",
            "error_bound_category": "empirical solver review criterion; not a global or T3 certificate",
            "charge_inventory": "UNKNOWN: worker has no separate electron inventory state"}
