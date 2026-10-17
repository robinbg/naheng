from dataclasses import replace
import numpy as np
import pytest
from naheng.formal.inventory_check import check_sodium_interval
from naheng.models.site_model import SiteModel, SiteParameters


@pytest.mark.parametrize("current", [-.1, 0, .1])
def test_actual_closed_inventory_includes_trapped_and_single_reservoir(current):
    model = SiteModel(SiteParameters(site_capacity_mol=(.02, .003)))
    initial = model.initial_state(.6)
    result = model.integrate(initial, current, 10)
    check = check_sodium_interval(model, initial, result, current, 298.15, 0)
    assert check["status"] == "PASS"
    assert check["state_coefficients"] == [.02, .003, 1., 1., 0.]
    assert check["evidence_refs"] == []
    assert "not a global" in check["error_bound_category"]
    assert check["charge_inventory"].startswith("UNKNOWN")


def test_actual_result_drift_and_false_reported_zero_fail():
    model = SiteModel(); initial = model.initial_state()
    result = model.integrate(initial, .1, 10)
    bad = result.state.copy(); bad[3] += 1e-3
    assert check_sodium_interval(model, initial, replace(result, state=bad), .1, 298.15, 0)["status"] == "FAIL"
    bad_states = result.states.copy(); bad_states[len(bad_states)//2, 2] += 1e-3
    assert check_sodium_interval(model, initial, replace(result, states=bad_states), .1, 298.15, 0)["status"] == "FAIL"
    assert check_sodium_interval(model, initial, replace(result, inventory_residual_mol=.01), .1, 298.15, 0)["status"] == "FAIL"


def test_rhs_mismatch_is_not_hidden_by_endpoint_match(monkeypatch):
    model = SiteModel(); initial = model.initial_state(); result = model.integrate(initial, .1, 10)
    original = model.rhs
    def wrong(*args):
        derivative = original(*args).copy(); derivative[3] += 1e-4
        return derivative
    monkeypatch.setattr(model, "rhs", wrong)
    assert check_sodium_interval(model, initial, result, .1, 298.15, 0)["status"] == "FAIL"


def test_nonfinite_result_has_no_valid_inventory():
    model = SiteModel(); initial = model.initial_state(); result = model.integrate(initial, .1, 10)
    bad = result.state.copy(); bad[0] = np.nan
    with pytest.raises(ValueError, match="Nonfinite"):
        check_sodium_interval(model, initial, replace(result, state=bad), .1, 298.15, 0)
