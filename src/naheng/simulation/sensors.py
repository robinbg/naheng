"""Observable-only sensor interface, separate from evaluator reference traces."""
from __future__ import annotations
from dataclasses import dataclass
import math

import numpy as np
from naheng.domain.contracts import Observation


@dataclass(frozen=True)
class SensorParameters:
    voltage_noise_std_V: float = 0.004
    temperature_noise_std_K: float = 0.05
    current_noise_std_A: float = 0.001
    voltage_bias_V: float = 0.0
    temperature_bias_K: float = 0.0
    source_id: str = "synthetic-sensor-v1"

    def __post_init__(self):
        for name in ("voltage_noise_std_V", "temperature_noise_std_K", "current_noise_std_A"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError("sensor noise must be finite and nonnegative")


class SensorModel:
    def __init__(self, parameters: SensorParameters | None = None, seed: int = 20261009):
        self.parameters = parameters or SensorParameters()
        self._rng = np.random.default_rng(seed)

    def measure(self, readout: dict[str, float], *, run_id: str, timestamp_s: float, cell_id: str = "cell-1") -> Observation:
        if set(readout) != {"voltage_V", "temperature_K", "current_A"}:
            raise ValueError("sensor input must contain observables only, no reference fields")
        if not all(math.isfinite(x) for x in readout.values()):
            raise ValueError("nonfinite sensor input")
        p = self.parameters
        return Observation(run_id=run_id, cell_id=cell_id, timestamp_s=timestamp_s,
                           voltage_V=readout["voltage_V"]+p.voltage_bias_V+self._rng.normal(0, p.voltage_noise_std_V),
                           temperature_K=readout["temperature_K"]+p.temperature_bias_K+self._rng.normal(0, p.temperature_noise_std_K),
                           current_A=readout["current_A"]+self._rng.normal(0, p.current_noise_std_A),
                           quality=["synthetic_noise", "synthetic_sensor_bias" if p.voltage_bias_V or p.temperature_bias_K else "unbiased"])


Sensors = SensorModel
