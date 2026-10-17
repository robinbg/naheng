from copy import deepcopy
import pytest
from naheng.domain.contracts import ForecastQuery, PosteriorSnapshot
from naheng.models.site_model import SiteModel, SiteParameters
from naheng.lifecycle.forecast import forecast
from naheng.lifecycle.capacity_protocol import CapacityProtocol, protocol_capacity


def fixture():
    model = SiteModel(SiteParameters(site_capacity_mol=(0.00012, 0.00008),
        rate_s_inv=(0.01, 0.006), side_rate_s_inv=(2e-8, 4e-8)))
    state = model.initial_state()
    snapshot = PosteriorSnapshot(snapshot_id="shared-snapshot", run_id="run-lifetime",
        obs_until_s=0, state_names=list(model.state_names), state_units=list(model.state_units),
        samples=[state.tolist()], weights=[1.0], mean=dict(zip(model.state_names, state.tolist())),
        quantiles={name:[value,value,value] for name,value in zip(model.state_names,state)},
        ess=1, identifiability=["synthetic_uncalibrated"])
    query = ForecastQuery(snapshot_id=snapshot.snapshot_id, future_policy_id="fixed-discharge",
        environment_id="constant-298K", horizon_s=5, endpoint_protocol="synthetic_capacity_v1",
        sample_budget=2, current_A=0.001, seed=3)
    return model, snapshot, query


def test_conditioned_query_is_reproducible_and_censored_endpoint_is_not_faked():
    model, snapshot, query = fixture()
    saved = deepcopy(snapshot.model_dump())
    result = forecast(snapshot, query, model)
    replay = forecast(snapshot, query, model)
    assert result["query_hash"] == replay["query_hash"]
    assert result["paths"] == replay["paths"]
    # An above-threshold final protocol measurement does not exclude an
    # earlier dip without capacity-order evidence. Keep it unknown instead
    # of asserting two mathematically unsupported right-censored lifetimes.
    assert result["rul"]["right_censored_count"] == 0
    assert result["rul"]["unknown_first_passage_count"] == 2
    assert all(p['right_censored'] is None for p in result['paths'])
    assert result['rul']['monotonic_capacity_status'] == 'unknown'
    assert result["rul"]["median_observed_s"] is None
    assert not result["rul"]["distribution_complete"]
    assert snapshot.model_dump() == saved
    assert result["budget"]["requested_paths"] == 2
    assert result["budget"]["completed_paths"] == 2
    assert result["budget"]["reused_calculations"] >= 4
    assert result["budget"]["unique_solves"] < 8
    assert result["budget"]["independent_operational_trajectories"] == 0


def test_policy_and_environment_part_of_identity_and_computation():
    model, snapshot, query = fixture()
    base = forecast(snapshot, query, model)
    charged = forecast(snapshot, query.model_copy(update={"future_policy_id":"fixed-charge", "current_A":-0.001}), model)
    hot = forecast(snapshot, query.model_copy(update={"environment_id":"constant-308K", "ambient_K":308.15}), model)
    assert len({base["query_hash"],charged["query_hash"],hot["query_hash"]}) == 3
    assert base["paths"][0]["energy_J"] > 0 > charged["paths"][0]["energy_J"]
    assert hot["paths"][0]["final_temperature_K"] > base["paths"][0]["final_temperature_K"]


def test_capacity_comes_from_discharge_integral_and_unknown_protocol_remains_unknown():
    model, snapshot, query = fixture()
    measured = protocol_capacity(model, model.initial_state())
    assert measured["status"] == "computed"
    assert measured["capacity_C"] == CapacityProtocol().discharge_current_A * measured["elapsed_s"]
    assert any(event["name"] == "voltage_low" for event in measured["events"])
    assert abs(measured["inventory_residual_mol"]) < 1e-9
    unknown = forecast(snapshot, query.model_copy(update={"endpoint_protocol":"missing-protocol"}), model)
    assert unknown["rul"]["status"] == "unknown"
    assert unknown["rul"]["samples_s"] == []


def test_sampled_parameters_are_carried_into_prediction():
    model, snapshot, query = fixture()
    augmented = snapshot.model_copy(update={
        "state_names":snapshot.state_names+["rate_scale","side_rate_scale"],
        "state_units":snapshot.state_units+["1","1"],
        "samples":[snapshot.samples[0]+[0.5,2.0]]})
    baseline = forecast(snapshot, query, model)
    uncertain = forecast(augmented, query, model)
    assert uncertain["paths"][0]["final_state"] != baseline["paths"][0]["final_state"]


def test_exhausted_budget_is_recorded_and_cannot_claim_complete_risk():
    model, snapshot, query = fixture()
    result = forecast(snapshot, query, model, wall_budget_s=1e-12)
    assert result["budget"]["exhausted"]
    assert result["budget"]["attempted_paths"] == 0
    assert result["rul"]["status"] == "unknown"
    assert result["risk"]["events"]["voltage_low"]["probability"] is None


def test_cancellation_before_and_during_real_calculation_raises_without_fake_output():
    model, snapshot, query = fixture()
    with pytest.raises(InterruptedError,match="cancelled"):
        forecast(snapshot,query,model,cancel_check=lambda:True)
    calls = [0]
    def cancel_midway():
        calls[0] += 1
        return calls[0] >= 4
    saved = deepcopy(snapshot.model_dump())
    with pytest.raises(InterruptedError,match="checkpoint"):
        forecast(snapshot,query,model,cancel_check=cancel_midway)
    assert snapshot.model_dump() == saved


def test_initial_retirement_uses_actual_protocol_capacity_threshold():
    model,snapshot,query=fixture()
    state = model.initial_state()
    state[2] = 0.5*sum(model.params.site_capacity_mol)
    state[3] -= state[2]
    retired = snapshot.model_copy(update={"samples":[state.tolist()],
        "mean":dict(zip(model.state_names,state.tolist())),
        "quantiles":{name:[value,value,value] for name,value in zip(model.state_names,state)}})
    predicted = forecast(retired,query,model)
    assert predicted["rul"]["samples_s"] == [0.0,0.0]
    assert predicted["rul"]["right_censored_count"] == 0
    assert predicted["rul"]["distribution_complete"]
