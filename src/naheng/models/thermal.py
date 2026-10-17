"""Declared lumped synthetic energy balance; no measured-cell calibration."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ThermalBalance:
    ohmic_W: float
    reaction_W: float
    management_W: float
    ambient_outflow_W: float
    storage_W: float
    temperature_rate_K_per_s: float

    @property
    def residual_W(self) -> float:
        return self.ohmic_W+self.reaction_W+self.management_W-self.ambient_outflow_W-self.storage_W


def thermal_balance(*, current_A: float, temperature_K: float, ambient_K: float,
                    trapped_rate_mol_per_s: float, resistance_ohm: float,
                    reaction_heat_J_per_mol: float, conductance_W_per_K: float,
                    capacity_J_per_K: float, management_W: float = 0) -> ThermalBalance:
    values = (current_A,temperature_K,ambient_K,trapped_rate_mol_per_s,resistance_ohm,
              reaction_heat_J_per_mol,conductance_W_per_K,capacity_J_per_K,management_W)
    if not all(math.isfinite(x) for x in values) or min(temperature_K,ambient_K,capacity_J_per_K) <= 0:
        raise ValueError("thermal balance requires finite SI values and positive temperatures/capacity")
    if min(trapped_rate_mol_per_s,resistance_ohm,conductance_W_per_K) < 0:
        raise ValueError("passive parameters and irreversible product flux must be nonnegative")
    ohmic = current_A**2*resistance_ohm
    reaction = reaction_heat_J_per_mol*trapped_rate_mol_per_s
    outflow = conductance_W_per_K*(temperature_K-ambient_K)
    storage = ohmic+reaction+management_W-outflow
    return ThermalBalance(ohmic,reaction,management_W,outflow,storage,storage/capacity_J_per_K)
