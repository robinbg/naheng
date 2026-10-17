"""Synthetic evaluator environment. Controllers receive EnvironmentStep only."""
from __future__ import annotations
from dataclasses import dataclass

from naheng.domain.contracts import Action, Observation
from naheng.models.site_model import SiteModel
from .sensors import SensorModel


@dataclass(frozen=True)
class EnvironmentStep:
    observation: Observation
    energy_J: float
    elapsed_s: float
    events: list[dict]
    thermal_management_energy_J: float


class ReferenceRecorder:
    """Evaluator-only storage; never attached to observations or controller steps."""
    def __init__(self):
        self.records: list[dict] = []

    def record(self, *, run_id: str, timestamp_s: float, state, readout, inventory_residual_mol: float):
        self.records.append({"run_id": run_id, "timestamp_s": timestamp_s,
                             "state": [float(x) for x in state], "readout": dict(readout),
                             "inventory_residual_mol": float(inventory_residual_mol), "provenance_type": "synthetic"})


class SimulationEnvironment:
    def __init__(self, run_id: str, model: SiteModel | None = None, sensor: SensorModel | None = None,
                 soc: float = 0.6, ambient_K: float = 298.15, evaluator: ReferenceRecorder | None = None):
        self.run_id = run_id
        self._model = model or SiteModel()
        self._sensor = sensor or SensorModel()
        self._state = self._model.initial_state(soc=soc, temperature_K=ambient_K)
        self._time_s = 0.0
        self.ambient_K = ambient_K
        self._evaluator = evaluator

    def initial_observation(self) -> Observation:
        return self._sensor.measure(self._model.observe(self._state, 0), run_id=self.run_id, timestamp_s=self._time_s)

    def step(self, action: Action) -> EnvironmentStep:
        if abs(action.start_s - self._time_s) > 1e-6:
            raise ValueError("action must start at the current simulated time")
        if action.current_A is None:
            raise ValueError("power control adapter not implemented; explicit current command required")
        result = self._model.integrate(self._state, action.current_A, action.duration_s,
                                       ambient_K=self.ambient_K, thermal_W=action.thermal_W)
        self._state = result.state.copy()
        self._time_s += result.elapsed_s
        readout = self._model.observe(self._state, action.current_A)
        observation = self._sensor.measure(readout, run_id=self.run_id, timestamp_s=self._time_s)
        if self._evaluator is not None:
            self._evaluator.record(run_id=self.run_id, timestamp_s=self._time_s, state=self._state,
                                   readout=readout, inventory_residual_mol=result.inventory_residual_mol)
        return EnvironmentStep(observation, result.energy_J, result.elapsed_s, result.events,
                               result.thermal_management_energy_J)


SyntheticEnvironment = SimulationEnvironment
