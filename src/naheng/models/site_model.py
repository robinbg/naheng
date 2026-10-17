"""Uncalibrated synthetic two-site model with an explicit current adapter.

The bounded driving potential is an effective insertion drive, not a measured
electrode potential or a calibrated Butler--Volmer model. External sodium and
electron ports and effective neutral trapped products are declared separately.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq
from .thermal import thermal_balance
from .degradation import temperature_rate_factor


class InfeasibleError(ValueError):
    """The requested current has no root in the declared drive domain."""


class DomainError(ValueError):
    pass


@dataclass(frozen=True)
class SiteParameters:
    site_capacity_mol: tuple[float, float] = (0.012, 0.008)
    rate_s_inv: tuple[float, float] = (0.001, 0.0006)
    equilibrium_drive_V: tuple[float, float] = (-0.08, 0.12)
    side_rate_s_inv: tuple[float, float] = (2e-7, 4e-7)
    drive_scale_V: float = 0.12
    drive_min_V: float = -1.0
    drive_max_V: float = 1.0
    base_voltage_V: float = 3.2
    resistance_ohm: float = 0.05
    thermal_capacity_J_per_K: float = 40.0
    thermal_conductance_W_per_K: float = 0.08
    thermal_cop: float = 1.0  # synthetic unity-COP assumption, thermal_W is heat flow
    side_heat_J_per_mol: float = 5000.0
    reservoir_initial_mol: float = 0.025
    faraday_C_per_mol: float = 96485.33212
    voltage_min_V: float = 2.0
    voltage_max_V: float = 4.2
    temperature_min_K: float = 273.15
    temperature_max_K: float = 333.15
    source_id: str = "synthetic-two-site-v1"
    model_kind: str = "theory_fixture"
    accelerated_synthetic: bool = False

    def __post_init__(self):
        for name in ("site_capacity_mol", "rate_s_inv", "side_rate_s_inv", "equilibrium_drive_V"):
            values = getattr(self, name)
            if len(values) != 2 or not all(math.isfinite(x) for x in values):
                raise DomainError(f"{name} must contain two finite values")
        if any(x <= 0 for x in self.site_capacity_mol) or any(x < 0 for x in self.rate_s_inv + self.side_rate_s_inv):
            raise DomainError("capacities must be positive and rates nonnegative")
        if self.drive_scale_V <= 0 or self.thermal_capacity_J_per_K <= 0 or self.faraday_C_per_mol <= 0 or self.thermal_cop <= 0:
            raise DomainError("scale, heat capacity and Faraday constant must be positive")
        if self.resistance_ohm < 0 or self.thermal_conductance_W_per_K < 0 or self.reservoir_initial_mol < 0:
            raise DomainError("negative passive parameter")
        if self.drive_min_V >= self.drive_max_V or self.voltage_min_V >= self.voltage_max_V or self.temperature_min_K >= self.temperature_max_K:
            raise DomainError("invalid domain bounds")
        if not self.source_id:
            raise DomainError("parameter source is required")

    @property
    def units(self) -> dict[str, str]:
        return {"site_capacity_mol": "mol", "rate_s_inv": "s^-1", "side_rate_s_inv": "s^-1",
                "equilibrium_drive_V": "V", "drive_scale_V": "V", "resistance_ohm": "ohm",
                "thermal_capacity_J_per_K": "J/K", "thermal_conductance_W_per_K": "W/K",
                "thermal_cop": "1",
                "side_heat_J_per_mol": "J/mol", "faraday_C_per_mol": "C/mol"}


@dataclass(frozen=True)
class IntegrationResult:
    state: np.ndarray
    energy_J: float
    events: list[dict]
    inventory_residual_mol: float
    times_s: np.ndarray
    states: np.ndarray
    voltages_V: np.ndarray
    elapsed_s: float
    solver: str = "scipy.solve_ivp/RK45"
    model_kind: str = "theory_fixture"
    thermal_management_energy_J: float = 0.0


class SiteModel:
    state_names = ("x1", "x2", "trapped_mol", "reservoir_mol", "temperature_K")
    state_units = ("1", "1", "mol", "mol", "K")

    def __init__(self, params: SiteParameters | None = None):
        self.params = params or SiteParameters()
        self._root_cache_key = None
        self._root_cache_value = None

    def initial_state(self, soc: float = 0.6, temperature_K: float = 298.15) -> np.ndarray:
        result = np.array([soc, soc, 0.0, self.params.reservoir_initial_mol, temperature_K], dtype=float)
        self._validate_state(result)
        return result

    def _validate_state(self, state, numerical_tolerance: float = 0.0) -> np.ndarray:
        state = np.asarray(state, dtype=float)
        if state.shape != (5,) or not all(math.isfinite(value) for value in state):
            raise DomainError("state must be a finite five-vector")
        lower, upper = -numerical_tolerance, 1 + numerical_tolerance
        if (state[0] < lower or state[1] < lower or state[0] > upper or state[1] > upper
                or state[2] < lower or state[3] < lower):
            raise DomainError("occupancy or sodium inventory outside physical domain")
        if state[4] <= 0:
            raise DomainError("temperature must be positive in K")
        return state

    def inventory_mol(self, state) -> float:
        state = np.asarray(state)
        return float(np.dot(self.params.site_capacity_mol, state[:2]) + state[2] + state[3])

    def rates(self, drive_V: float, temperature_K: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        p = self.params
        temperature_factor = temperature_rate_factor(temperature_K)
        argument = (drive_V - np.asarray(p.equilibrium_drive_V)) / p.drive_scale_V
        a = np.asarray(p.rate_s_inv) * np.exp(argument) * temperature_factor
        b = np.asarray(p.rate_s_inv) * np.exp(-argument) * temperature_factor
        c = np.asarray(p.side_rate_s_inv) * temperature_factor
        return a, b, c

    def solve_drive(self, state, current_A: float) -> float:
        state = self._validate_state(state, numerical_tolerance=1e-8)
        if not math.isfinite(current_A):
            raise DomainError("current must be finite")
        p = self.params
        key = (*state[:2], state[4], current_A)
        if key == self._root_cache_key:
            return self._root_cache_value
        # All sites share the declared scale, so the same monotone current
        # balance can be evaluated with scalar coefficients without allocating
        # arrays on every Brent iteration. This is algebraically identical.
        temperature_factor = temperature_rate_factor(state[4])
        insertion = p.faraday_C_per_mol * temperature_factor * sum(n*k*math.exp(-bias/p.drive_scale_V)*(1-x) for n,k,bias,x in zip(p.site_capacity_mol, p.rate_s_inv, p.equilibrium_drive_V, state[:2]))
        removal = p.faraday_C_per_mol * temperature_factor * sum(n*k*math.exp(bias/p.drive_scale_V)*x for n,k,bias,x in zip(p.site_capacity_mol, p.rate_s_inv, p.equilibrium_drive_V, state[:2]))
        def balance(drive):
            return removal*math.exp(-drive/p.drive_scale_V)-insertion*math.exp(drive/p.drive_scale_V)-current_A
        left, right = balance(p.drive_min_V), balance(p.drive_max_V)
        if left == 0: return p.drive_min_V
        if right == 0: return p.drive_max_V
        if left * right > 0:
            raise InfeasibleError(f"current {current_A:g} A has no root in drive [{p.drive_min_V:g}, {p.drive_max_V:g}] V; residuals {left:g}, {right:g} A")
        root = float(brentq(balance, p.drive_min_V, p.drive_max_V, xtol=1e-12, rtol=1e-12))
        self._root_cache_key, self._root_cache_value = key, root
        return root

    def observe(self, state, current_A: float) -> dict[str, float]:
        state = self._validate_state(state, numerical_tolerance=1e-8)
        drive = self.solve_drive(state, current_A)
        return {"voltage_V": self.params.base_voltage_V + drive - current_A * self.params.resistance_ohm,
                "temperature_K": float(state[4]), "current_A": float(current_A)}

    def rhs(self, t: float, state, current_A: float, ambient_K: float = 298.15, thermal_W: float = 0.0) -> np.ndarray:
        state = self._validate_state(state, numerical_tolerance=1e-8)
        if not math.isfinite(ambient_K) or ambient_K <= 0 or not math.isfinite(thermal_W):
            raise DomainError("ambient and thermal command must be finite SI inputs")
        p = self.params
        a, b, c = self.rates(self.solve_drive(state, current_A), state[4])
        reversible = a * (1 - state[:2]) - b * state[:2]
        side = c * state[:2]
        trapped_rate = float(np.dot(p.site_capacity_mol, side))
        reservoir_rate = -float(np.dot(p.site_capacity_mol, reversible))
        balance = thermal_balance(current_A=current_A, temperature_K=float(state[4]), ambient_K=ambient_K,
                                  trapped_rate_mol_per_s=trapped_rate, resistance_ohm=p.resistance_ohm,
                                  reaction_heat_J_per_mol=p.side_heat_J_per_mol, conductance_W_per_K=p.thermal_conductance_W_per_K,
                                  capacity_J_per_K=p.thermal_capacity_J_per_K, management_W=thermal_W)
        temperature_rate = balance.temperature_rate_K_per_s
        return np.array([reversible[0]-side[0], reversible[1]-side[1], trapped_rate, reservoir_rate, temperature_rate])

    def integrate(self, state, current_A: float, duration_s: float, ambient_K: float = 298.15, thermal_W: float = 0.0, *, max_step_s: float = 60.0) -> IntegrationResult:
        initial = self._validate_state(state).copy()
        if not math.isfinite(duration_s) or duration_s <= 0:
            raise DomainError("duration_s must be positive and finite")
        if not math.isfinite(max_step_s) or max_step_s <= 0:
            raise DomainError("max_step_s must be positive and finite")
        self.observe(initial, current_A)  # validate current feasibility before solver launch
        p = self.params
        names = ("voltage_low", "voltage_high", "temperature_low", "temperature_high", "reservoir_depleted")
        limits = (p.voltage_min_V, p.voltage_max_V, p.temperature_min_K, p.temperature_max_K, 0.0)
        last_event_key, last_event_values = None, None
        def values(s):
            nonlocal last_event_key, last_event_values
            key = tuple(s[:5])
            if key == last_event_key:
                return last_event_values
            voltage = self.observe(s[:5], current_A)["voltage_V"]
            last_event_key = key
            last_event_values = [voltage-p.voltage_min_V, p.voltage_max_V-voltage, s[4]-p.temperature_min_K, p.temperature_max_K-s[4], s[3]]
            return last_event_values
        event_functions = []
        for index in range(len(names)):
            def event(t, s, index=index): return values(s)[index]
            event.direction = -1
            event.terminal = True
            event_functions.append(event)
        initial_values = values(initial)
        already = [i for i, value in enumerate(initial_values) if value <= 0]
        if already:
            events = [{"name": names[i], "time_s": 0.0, "value": float(initial_values[i] + limits[i]), "limit": limits[i], "direction": "exit"} for i in already]
            voltage = self.observe(initial, current_A)["voltage_V"]
            return IntegrationResult(initial, 0.0, events, 0.0, np.array([0.]), initial[None,:], np.array([voltage]), 0.0)
        def augmented_rhs(t, s):
            derivatives = self.rhs(t, s[:5], current_A, ambient_K, thermal_W)
            electrical_W = current_A * self.observe(s[:5], current_A)["voltage_V"]
            result = np.empty(6)
            result[:5] = derivatives
            result[5] = electrical_W
            return result
        solution = solve_ivp(augmented_rhs, (0.0, duration_s), np.r_[initial, 0.0], rtol=1e-7, atol=1e-10,
                             max_step=min(max_step_s, duration_s), dense_output=True, events=event_functions)
        if not solution.success:
            raise RuntimeError(f"numerical solver failed: {solution.message}")
        elapsed = float(solution.t[-1])
        times = np.unique(np.r_[np.linspace(0, elapsed, max(2, min(1001, math.ceil(elapsed/5)+1))), solution.t])
        states = solution.sol(times)[:5].T
        voltages = np.array([self.observe(s, current_A)["voltage_V"] for s in states])
        events = []
        for index, crossings in enumerate(solution.t_events):
            for time in crossings:
                state_at_event = solution.sol(time)[:5]
                actual = self.observe(state_at_event, current_A)["voltage_V"] if index < 2 else (float(state_at_event[4]) if index < 4 else float(state_at_event[3]))
                events.append({"name": names[index], "time_s": float(time), "value": actual, "limit": limits[index], "direction": "exit"})
        final = solution.y[:5,-1].copy()
        return IntegrationResult(final, float(solution.y[5,-1]), events, self.inventory_mol(final)-self.inventory_mol(initial),
                                 times, states, voltages, elapsed, thermal_management_energy_J=abs(thermal_W)*elapsed/p.thermal_cop)
