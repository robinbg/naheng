from dataclasses import replace
import pytest
from naheng.models.thermal import thermal_balance
from naheng.models.degradation import FilmParameters, integrate_film
from naheng.models.site_model import SiteModel, SiteParameters


def test_explicit_heat_balance_and_cooling():
    result = thermal_balance(current_A=2,temperature_K=310,ambient_K=300,trapped_rate_mol_per_s=1e-6,
                             resistance_ohm=.1,reaction_heat_J_per_mol=5000,conductance_W_per_K=.1,
                             capacity_J_per_K=40,management_W=-.2)
    assert result.ohmic_W == pytest.approx(.4)
    assert result.residual_W == pytest.approx(0,abs=1e-15)
    assert result.temperature_rate_K_per_s == pytest.approx((.4+.005-.2-1)/40)


def test_temperature_and_management_change_actual_trapping():
    model = SiteModel()
    initial = model.initial_state()
    normal = model.integrate(initial,.2,120)
    hot = model.integrate(initial,.2,120,thermal_W=2)
    assert hot.state[4] > normal.state[4]
    assert hot.state[2] > normal.state[2]
    assert abs(hot.inventory_residual_mol)<1e-11
    assert hot.thermal_management_energy_J == pytest.approx(2*hot.elapsed_s)


def test_real_film_ode_matches_declared_integral():
    parameters = FilmParameters(1e-12,1e-7,1e-5,1000)
    result = integrate_film(1e-8,1000,parameters)
    assert result["thickness_m"] > 1e-8
    assert abs(result["integral_residual"]) < 1e-7


def test_heat_flow_electrical_cost_uses_declared_cop():
    model = SiteModel(replace(SiteParameters(), thermal_cop=2))
    result = model.integrate(model.initial_state(), .1, 10, thermal_W=-1)
    assert result.thermal_management_energy_J == pytest.approx(5)
    assert model.params.units["thermal_cop"] == "1"
