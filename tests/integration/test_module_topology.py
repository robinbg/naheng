from dataclasses import replace
import numpy as np
import pytest
from naheng.models.site_model import DomainError, SiteModel, SiteParameters
from naheng.simulation.module import ModuleModel


def test_series_current_voltage_and_inventory_are_consistent():
    module = ModuleModel()
    state = module.initial_state()
    assert module.observe(state,.2)["voltage_V"] == pytest.approx(4*SiteModel().observe(state[0],.2)["voltage_V"])
    result = module.integrate(state,.2,30)
    assert result.topology == "4s"
    assert max(abs(x) for x in result.inventory_residual_mol) < 1e-11
    assert result.energy_J == pytest.approx(4*SiteModel().integrate(state[0],.2,30).energy_J,rel=1e-7)
    with pytest.raises(DomainError): ModuleModel(cells=(SiteModel(),))


def test_thermal_coupling_conserves_heat_and_changes_evolution():
    coupled,uncoupled = ModuleModel(coupling_W_per_K=.1),ModuleModel(coupling_W_per_K=0)
    state = coupled.initial_state(temperature_K=[310,298.15,298.15,298.15])
    assert sum(coupled.coupling_heat_W(state)) == pytest.approx(0,abs=1e-15)
    together = coupled.integrate(state,.1,60)
    apart = uncoupled.integrate(state,.1,60)
    assert together.state[0,4] < apart.state[0,4]
    assert together.state[1,4] > apart.state[1,4]


def test_weak_cell_constraint_limits_whole_series_module():
    cells = (SiteModel(),SiteModel(replace(SiteParameters(),temperature_max_K=298.18)),SiteModel(),SiteModel())
    module = ModuleModel(cells)
    result = module.integrate(module.initial_state(),.1,60,thermal_W=4)
    assert result.elapsed_s < 5
    assert result.events[0]["cell_id"] == "cell-2"
    assert result.events[0]["name"] == "temperature_high"


def test_heterogeneous_capacity_and_soc_change_weak_cell_voltage_constraint():
    cells=(SiteModel(replace(SiteParameters(),site_capacity_mol=(.006,.004),voltage_min_V=3.05)),SiteModel(),SiteModel(),SiteModel())
    module=ModuleModel(cells)
    state=module.initial_state(soc=[.3,.6,.6,.6])
    result=module.integrate(state,.2,1000)
    assert result.events[0]["cell_id"]=="cell-1"
    assert result.events[0]["name"]=="voltage_low"
    assert result.elapsed_s<1000
    assert max(abs(r) for r in result.inventory_residual_mol)<1e-10
    homogeneous=ModuleModel(tuple(SiteModel(replace(SiteParameters(),voltage_min_V=3.05)) for _ in range(4)))
    control=homogeneous.integrate(homogeneous.initial_state(),.2,1000)
    assert not control.events and control.elapsed_s==1000


@pytest.mark.parametrize("field,value",[("duration_s",float("nan")),("max_step_s",float("inf")),("ambient_K",0)])
def test_module_rejects_invalid_si_inputs(field,value):
    module=ModuleModel()
    args={"current_A":.1,"duration_s":10,field:value}
    with pytest.raises(DomainError):module.integrate(module.initial_state(),**args)
