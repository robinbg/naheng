"""A declared, uncalibrated synthetic protocol using real discharge integration."""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
import numpy as np


@dataclass(frozen=True)
class CapacityProtocol:
    protocol_id: str = "synthetic_capacity_v1"
    initial_occupancy: float = 0.95
    temperature_K: float = 298.15
    discharge_current_A: float = 1.0
    cutoff_voltage_V: float = 2.8
    maximum_duration_s: float = 3600.0
    retirement_ratio: float = 0.8

    def __post_init__(self):
        values = (self.initial_occupancy, self.temperature_K, self.discharge_current_A,
                  self.cutoff_voltage_V, self.maximum_duration_s, self.retirement_ratio)
        if not all(isfinite(value) for value in values):
            raise ValueError("Protocol values must be finite")
        if not 0 < self.initial_occupancy <= 1 or not 0 < self.retirement_ratio < 1:
            raise ValueError("Occupancy and retirement ratio must be within their domains")
        if self.temperature_K <= 0 or self.discharge_current_A <= 0 or self.maximum_duration_s <= 0:
            raise ValueError("Discharge protocol requires positive temperature, current and duration")


def protocol_capacity(model, state, protocol: CapacityProtocol | None = None) -> dict:
    """Initialize explicitly, preserve sodium inventory, and integrate I dt.

    The relation between trapped inventory and initialized accessible occupancy
    below is an uncalibrated synthetic mapping. It is not an empirical sodium
    capacity law, and q is never reported directly as measured capacity.
    """
    protocol = protocol or CapacityProtocol()
    initial = np.asarray(state, dtype=float).copy()
    total_capacity = sum(model.params.site_capacity_mol)
    active_fraction = max(0.0, 1 - initial[2] / total_capacity)
    total_inventory = model.inventory_mol(initial)
    initial[:2] = protocol.initial_occupancy * active_fraction
    initial[3] = total_inventory - initial[2] - np.dot(model.params.site_capacity_mol, initial[:2])
    initial[4] = protocol.temperature_K
    if initial[3] < 0:
        return {"status": "unknown", "reason": "insufficient_inventory_for_protocol_initialization",
                "capacity_C": None, "protocol_id": protocol.protocol_id}
    if active_fraction == 0:
        return {"status": "computed", "capacity_C": 0.0, "capacity_Ah": 0.0,
                "elapsed_s": 0.0, "protocol_id": protocol.protocol_id,
                "provenance_type": "synthetic", "initialization_assumption": "trapped_accessibility_v1"}
    diagnostic_model = type(model)(replace(model.params, voltage_min_V=protocol.cutoff_voltage_V))
    try:
        result = diagnostic_model.integrate(initial, protocol.discharge_current_A,
            protocol.maximum_duration_s, ambient_K=protocol.temperature_K)
    except (ValueError, RuntimeError) as error:
        return {"status": "unknown", "reason": str(error), "capacity_C": None,
                "protocol_id": protocol.protocol_id}
    ended_at_cutoff = any(event["name"] == "voltage_low" for event in result.events)
    value = protocol.discharge_current_A * result.elapsed_s
    return {"status": "computed" if ended_at_cutoff else "right_censored",
            "capacity_C": value if ended_at_cutoff else None,
            "capacity_lower_bound_C": value,
            "capacity_Ah": value / 3600 if ended_at_cutoff else None,
            "elapsed_s": result.elapsed_s, "events": result.events,
            "inventory_residual_mol": result.inventory_residual_mol,
            "protocol_id": protocol.protocol_id, "provenance_type": "synthetic",
            "initialization_assumption": "trapped_accessibility_v1",
            "uncalibrated": True}
