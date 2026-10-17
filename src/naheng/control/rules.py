"""Parameterized synthetic baseline, proposed for subsequent admission checks."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import isfinite

from naheng.domain.contracts import Action, PosteriorSnapshot


@dataclass(frozen=True)
class RuleParameters:
    charge_below_price: float = 0.12
    discharge_above_price: float = 0.25
    current_limit_A: float = 0.2
    soc_min: float = 0.15
    soc_max: float = 0.85
    temperature_min_K: float = 273.15
    temperature_max_K: float = 333.15
    cooling_above_K: float = 308.15
    cooling_W: float = 0.1

    def __post_init__(self):
        if self.current_limit_A <= 0 or not 0 <= self.soc_min < self.soc_max <= 1:
            raise ValueError("Invalid synthetic policy limits")
        if self.charge_below_price > self.discharge_above_price:
            raise ValueError("Charge and discharge price regions must not overlap")


def propose(snapshot: PosteriorSnapshot, price: float, start_s: float,
            duration_s: float, parameters: RuleParameters | None = None) -> Action:
    params = parameters or RuleParameters()
    if not isfinite(price):
        raise ValueError("Finite tariff required")
    if start_s < snapshot.obs_until_s:
        raise ValueError("Cannot propose an action before the snapshot")
    interval = snapshot.quantiles.get("soc")
    temperatures = snapshot.quantiles.get("temperature_K")
    if interval is None or temperatures is None:
        raise ValueError("SOC and temperature uncertainty are required")
    current, thermal = 0.0, 0.0
    if temperatures[0] < params.temperature_min_K or temperatures[-1] > params.temperature_max_K:
        # No claim that zero current is safe; admission evaluates this proposal.
        current = 0.0
    elif price <= params.charge_below_price and interval[-1] < params.soc_max:
        current = -params.current_limit_A
    elif price >= params.discharge_above_price and interval[0] > params.soc_min:
        current = params.current_limit_A
    if temperatures[-1] > params.cooling_above_K:
        thermal = -params.cooling_W
    identity = json.dumps([snapshot.snapshot_id, price, start_s, duration_s, current, thermal])
    return Action(action_id="action-" + hashlib.sha256(identity.encode()).hexdigest()[:24],
        snapshot_id=snapshot.snapshot_id, start_s=start_s, duration_s=duration_s,
        current_A=current, thermal_W=thermal)
