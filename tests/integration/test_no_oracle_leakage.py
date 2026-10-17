import inspect
import pytest
from naheng.domain.contracts import Observation
from naheng.estimation.particle_filter import ParticleFilter
from naheng.models.site_model import SiteModel


def test_estimator_has_sensor_only_boundary_and_rejects_true_state():
    model = SiteModel()
    estimator = ParticleFilter("sensor-run", model, particles=8)
    forbidden = {"true_state", "reference_trace", "future_observations", "truth_path"}
    assert forbidden.isdisjoint(inspect.signature(estimator.update).parameters)
    assert forbidden.isdisjoint(Observation.model_fields)
    with pytest.raises(TypeError, match="Observation"):
        estimator.update({"true_state": model.initial_state().tolist()})
    observed = model.observe(model.initial_state(), 0)
    snapshot = estimator.update(Observation(run_id="sensor-run", timestamp_s=0,
        current_A=0, voltage_V=observed["voltage_V"], temperature_K=observed["temperature_K"]))
    assert snapshot.samples and not forbidden.intersection(snapshot.model_dump())
