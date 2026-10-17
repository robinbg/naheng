from dataclasses import replace
import numpy as np
import pytest
from naheng.models.site_model import DomainError, InfeasibleError, SiteModel, SiteParameters


def test_current_port_inventory_and_energy():
    model = SiteModel()
    initial = model.initial_state()
    result = model.integrate(initial, .2, 300)
    assert abs(result.inventory_residual_mol) < 1e-11
    assert result.state[3]-initial[3] == pytest.approx(.2*result.elapsed_s/model.params.faraday_C_per_mol, abs=1e-11)
    assert result.state[2] > initial[2]
    assert result.energy_J == pytest.approx(np.trapezoid(.2*result.voltages_V, result.times_s), rel=1e-5)
    assert result.elapsed_s == 300


def test_actions_and_parameters_affect_actual_trajectory():
    model = SiteModel()
    initial = model.initial_state()
    discharge = model.integrate(initial, .2, 120)
    charge = model.integrate(initial, -.2, 120)
    warmer = model.integrate(initial, .2, 120, thermal_W=2)
    faster = SiteModel(replace(model.params, rate_s_inv=(.004, .001))).integrate(initial, .2, 120)
    assert discharge.energy_J > 0 > charge.energy_J
    assert np.dot(model.params.site_capacity_mol, discharge.state[:2]) < np.dot(model.params.site_capacity_mol, charge.state[:2])
    assert warmer.state[4] > discharge.state[4]
    assert not np.allclose(faster.state[:2], discharge.state[:2])


def test_root_infeasible_not_clipped():
    model = SiteModel(replace(SiteParameters(), drive_min_V=-.01, drive_max_V=.01))
    with pytest.raises(InfeasibleError): model.integrate(model.initial_state(), 1e4, 10)
    with pytest.raises(DomainError): model.integrate(model.initial_state(), .1, 0)
    with pytest.raises(DomainError): model.initial_state(soc=1.01)


def test_instantaneous_conservation_and_current_balance():
    model = SiteModel()
    state = model.initial_state(.3, 310)
    derivative = model.rhs(0, state, -.3)
    assert np.dot(model.params.site_capacity_mol, derivative[:2])+sum(derivative[2:4]) == pytest.approx(0, abs=1e-15)
    assert derivative[3]*model.params.faraday_C_per_mol == pytest.approx(-.3, abs=1e-9)


def test_adaptive_step_preserves_capacity_energy_and_continuous_event():
    model = SiteModel(replace(SiteParameters(), voltage_min_V=2.8))
    initial = model.initial_state(.95)
    reference = model.integrate(initial, 1.0, 3600, max_step_s=5)
    adaptive = model.integrate(initial, 1.0, 3600, max_step_s=60)
    assert adaptive.events[0]["name"] == reference.events[0]["name"] == "voltage_low"
    assert adaptive.elapsed_s == pytest.approx(reference.elapsed_s, rel=2e-6)
    assert adaptive.energy_J == pytest.approx(reference.energy_J, rel=2e-6)
    assert np.allclose(adaptive.state, reference.state, rtol=2e-6, atol=2e-8)
    assert abs(adaptive.inventory_residual_mol) < 1e-11
