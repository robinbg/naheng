from dataclasses import replace
import pytest

from naheng.domain.contracts import Action
from naheng.models.site_model import SiteModel, SiteParameters
from naheng.simulation.environment import ReferenceRecorder, SimulationEnvironment
from naheng.simulation.sensors import SensorModel, SensorParameters


def test_event_crossing_between_output_samples():
    model = SiteModel(replace(SiteParameters(), temperature_max_K=298.20))
    result = model.integrate(model.initial_state(), .1, 20, thermal_W=2)
    event = result.events[0]
    assert event["name"] == "temperature_high"
    assert 0 < event["time_s"] < 5
    assert result.elapsed_s == pytest.approx(event["time_s"])
    assert event["value"] == pytest.approx(298.20, abs=1e-7)
    assert result.state[4] == pytest.approx(298.20, abs=1e-7)


def test_sensor_reference_separation_and_seed_reproducibility():
    first, second = SensorModel(seed=11), SensorModel(seed=11)
    readout = {"current_A": .1, "voltage_V": 3.1, "temperature_K": 298.15}
    assert first.measure(readout, run_id="r", timestamp_s=0) == second.measure(readout, run_id="r", timestamp_s=0)
    with pytest.raises(ValueError): first.measure(dict(readout, x1=.5), run_id="r", timestamp_s=0)
    evaluator = ReferenceRecorder()
    environment = SimulationEnvironment("r", evaluator=evaluator,
                                        sensor=SensorModel(SensorParameters(0, 0, 0)))
    result = environment.step(Action(action_id="a", snapshot_id="s", start_s=0, duration_s=60, current_A=.1))
    assert "state" not in result.observation.model_dump()
    assert evaluator.records[0]["state"] and result.energy_J > 0
    assert result.observation.timestamp_s == 60
