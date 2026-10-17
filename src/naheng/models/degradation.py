"""Explicit synthetic trapping and declared reaction/diffusion film example."""
from dataclasses import dataclass
import math
import numpy as np
from scipy.integrate import solve_ivp


def temperature_rate_factor(temperature_K: float, reference_K: float = 298.15, scale_K: float = 40.0) -> float:
    if temperature_K <= 0 or scale_K <= 0 or not all(math.isfinite(x) for x in (temperature_K,reference_K,scale_K)):
        raise ValueError("invalid synthetic temperature-rate parameters")
    return math.exp((temperature_K-reference_K)/scale_K)


def trapped_sodium_rate_mol_per_s(capacities_mol, occupancies, rates_s_inv) -> float:
    capacities, occupancies, rates = map(lambda v: np.asarray(v,dtype=float), (capacities_mol,occupancies,rates_s_inv))
    if capacities.shape != occupancies.shape or rates.shape != occupancies.shape:
        raise ValueError("trapping arrays must have identical shape")
    if not all(np.all(np.isfinite(v)) for v in (capacities,occupancies,rates)) or np.any(capacities <= 0) or np.any(rates < 0) or np.any(occupancies < 0) or np.any(occupancies > 1):
        raise ValueError("trapping requires nonnegative physical inventory and rates")
    return float(np.dot(capacities,rates*occupancies))


@dataclass(frozen=True)
class FilmParameters:
    diffusion_m2_per_s: float
    reaction_m_per_s: float
    molar_volume_m3_per_mol: float
    concentration_difference_mol_per_m3: float
    source_id: str = "synthetic-reaction-diffusion-v1"

    def __post_init__(self):
        values = (self.diffusion_m2_per_s,self.reaction_m_per_s,self.molar_volume_m3_per_mol,self.concentration_difference_mol_per_m3)
        if not self.source_id or not all(math.isfinite(x) and x>0 for x in values):
            raise ValueError("film parameters must be positive with a source")


def film_rate_m_per_s(thickness_m: float, p: FilmParameters) -> float:
    if thickness_m < 0 or not math.isfinite(thickness_m):
        raise ValueError("film thickness must be finite and nonnegative")
    return p.molar_volume_m3_per_mol*p.concentration_difference_mol_per_m3/(1/p.reaction_m_per_s+thickness_m/p.diffusion_m2_per_s)


def integrate_film(initial_thickness_m: float, duration_s: float, p: FilmParameters) -> dict:
    film_rate_m_per_s(initial_thickness_m,p)
    if not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("film duration must be positive")
    result = solve_ivp(lambda t,l: [film_rate_m_per_s(float(l[0]),p)],(0,duration_s),[initial_thickness_m],rtol=1e-9,atol=1e-14)
    if not result.success: raise RuntimeError(result.message)
    final = float(result.y[0,-1])
    integral = (final-initial_thickness_m)/p.reaction_m_per_s+(final**2-initial_thickness_m**2)/(2*p.diffusion_m2_per_s)
    source = p.molar_volume_m3_per_mol*p.concentration_difference_mol_per_m3*duration_s
    return {"thickness_m":final,"integral_residual":integral-source,"elapsed_s":duration_s,"source_id":p.source_id,
            "provenance_type":"synthetic","constant_parameter_isothermal_example":True}
