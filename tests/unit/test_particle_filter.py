import numpy as np
import pytest
from naheng.domain.contracts import Observation
from naheng.models.site_model import SiteModel, SiteParameters
from naheng.estimation.particle_filter import ParticleFilter


def observation(model, state, time_s=0.0, current=0.01):
    sensed = model.observe(state, current)
    return Observation(run_id="run-filter", timestamp_s=time_s, current_A=current,
                       voltage_V=sensed["voltage_V"], temperature_K=sensed["temperature_K"])


def small_model():
    return SiteModel(SiteParameters(site_capacity_mol=(0.00012, 0.00008),
        rate_s_inv=(0.01, 0.006)))


def test_sensor_assimilation_normalized_posterior_and_parameter_prior():
    model = small_model()
    hidden = model.initial_state()
    pf = ParticleFilter("run-filter", model, seed=7, particles=32)
    initial = pf.update(observation(model, hidden))
    hidden = model.integrate(hidden, 0.01, 2).state
    current = pf.update(observation(model, hidden, 2), duration_s=2)
    assert np.isclose(sum(current.weights), 1)
    assert 0 < current.ess <= 32
    assert current.obs_until_s == 2
    assert "rate_scale" in current.state_names and "side_rate_scale" in current.state_names
    assert any("not_identified" in flag for flag in current.identifiability)
    assert initial.snapshot_id != current.snapshot_id
    assert pf.update_diagnostics[-1]["ess_before_resampling"] == current.ess


def test_large_observation_noise_preserves_soc_uncertainty():
    model = small_model()
    observed = observation(model, model.initial_state())
    narrow = ParticleFilter("run-filter", model, seed=8, particles=64, voltage_noise_V=0.003).update(observed)
    broad = ParticleFilter("run-filter", model, seed=8, particles=64, voltage_noise_V=0.20).update(observed)
    assert broad.quantiles["soc"][-1] - broad.quantiles["soc"][0] > narrow.quantiles["soc"][-1] - narrow.quantiles["soc"][0]


def test_returned_snapshot_cannot_mutate_filter_checkpoint():
    model = small_model()
    pf = ParticleFilter("run-filter", model, particles=8)
    snapshot = pf.update(observation(model, model.initial_state()))
    original = pf.snapshot.samples[0][0]
    snapshot.samples[0][0] = -123
    snapshot.weights[0] = -999
    assert pf.snapshot.samples[0][0] == original
    assert pf.snapshot.weights[0] >= 0


def test_missing_interval_or_out_of_order_observation_rejected():
    model = small_model()
    pf = ParticleFilter("run-filter", model, particles=8)
    with pytest.raises(ValueError, match="time zero"):
        pf.update(observation(model, model.initial_state(), 10))
    pf.update(observation(model, model.initial_state()))
    with pytest.raises(ValueError, match="increase"):
        pf.update(observation(model, model.initial_state()))
    with pytest.raises(ValueError, match="Duration"):
        pf.update(observation(model, model.initial_state(), 2), duration_s=1)


def test_warm_start_and_known_thermal_action_are_assimilated():
    model = small_model()
    state = model.initial_state(temperature_K=310.15)
    estimator = ParticleFilter("run-filter",model,seed=19,particles=32)
    first = estimator.update(observation(model,state))
    assert abs(first.mean["temperature_K"]-310.15) < 0.5
    advanced = model.integrate(state,0.01,5,ambient_K=310.15,thermal_W=-0.1)
    observed = observation(model,advanced.state,5)
    second = estimator.update(observed,duration_s=5,ambient_K=310.15,thermal_W=-0.1)
    assert abs(second.mean["temperature_K"]-advanced.state[4]) < 0.5
    assert second.obs_until_s == 5


def test_exact_duplicate_particles_reuse_computation_without_reducing_distribution():
    model = small_model()
    state = model.initial_state()
    estimator = ParticleFilter("run-filter", model, seed=4, particles=8)
    estimator.update(observation(model,state))
    estimator._samples[:] = estimator._samples[0].copy()
    estimator._models[:] = [estimator._models[0]]*8
    estimator._weights[:] = 1/8
    advanced = model.integrate(state,0.01,2)
    posterior = estimator.update(observation(model,advanced.state,2),duration_s=2)
    assert len(posterior.samples) == 8
    assert estimator.update_diagnostics[-1]["unique_forward_solves"] == 1
    assert estimator.update_diagnostics[-1]["reused_calculations"] == 7
