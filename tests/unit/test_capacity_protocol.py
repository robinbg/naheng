import numpy as np
import pytest
from naheng.models.site_model import SiteModel, SiteParameters
from naheng.lifecycle.capacity_protocol import CapacityProtocol, protocol_capacity


def model():
    return SiteModel(SiteParameters(site_capacity_mol=(0.00012,0.00008),
        rate_s_inv=(0.01,0.006), side_rate_s_inv=(2e-8,4e-8)))


def test_real_discharge_cutoff_integral_and_inventory_balance():
    chemistry=model()
    state=chemistry.initial_state()
    result=protocol_capacity(chemistry,state)
    assert result["status"] == "computed"
    assert result["capacity_C"] > 0
    assert result["capacity_C"] == result["elapsed_s"]*CapacityProtocol().discharge_current_A
    assert result["capacity_Ah"] == pytest.approx(result["capacity_C"]/3600)
    assert any(event["name"] == "voltage_low" and event["value"] == pytest.approx(2.8)
               for event in result["events"])
    assert abs(result["inventory_residual_mol"]) < 1e-9
    assert result["uncalibrated"] and result["provenance_type"] == "synthetic"
    assert result["capacity_C"] != pytest.approx(
        np.dot(chemistry.params.site_capacity_mol,state[:2])*chemistry.params.faraday_C_per_mol)


def test_trapped_inventory_changes_protocol_capacity_via_declared_initialization():
    chemistry=model()
    fresh=chemistry.initial_state()
    trapped=fresh.copy()
    trapped[2] = 0.5*sum(chemistry.params.site_capacity_mol)
    trapped[3] -= trapped[2]
    assert chemistry.inventory_mol(fresh) == pytest.approx(chemistry.inventory_mol(trapped))
    initial=protocol_capacity(chemistry,fresh)
    aged=protocol_capacity(chemistry,trapped)
    assert aged["status"] == "computed"
    assert aged["capacity_C"] < 0.8*initial["capacity_C"]
    assert aged["initialization_assumption"] == "trapped_accessibility_v1"


def test_short_diagnostic_is_censored_and_insufficient_initial_inventory_is_unknown():
    chemistry=model()
    short=protocol_capacity(chemistry,chemistry.initial_state(),
                            CapacityProtocol(maximum_duration_s=0.01))
    assert short["status"] == "right_censored" and short["capacity_C"] is None
    assert short["capacity_lower_bound_C"] == pytest.approx(0.01)
    depleted=np.array([0.1,0.1,0,0,298.15])
    unavailable=protocol_capacity(chemistry,depleted)
    assert unavailable["status"] == "unknown" and unavailable["capacity_C"] is None
    assert unavailable["reason"] == "insufficient_inventory_for_protocol_initialization"


def test_invalid_protocol_parameters_do_not_produce_capacities():
    for values in [{"discharge_current_A":-1},{"retirement_ratio":1},{"initial_occupancy":2},
                   {"maximum_duration_s":float("nan")}]:
        with pytest.raises(ValueError):
            CapacityProtocol(**values)
