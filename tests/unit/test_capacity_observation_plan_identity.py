from dataclasses import asdict, replace

import pytest

from naheng.domain.contracts import ForecastQuery
from naheng.lifecycle.capacity_protocol import CapacityProtocol
from naheng.lifecycle.forecast import _observation_plan_hash
from naheng.models.site_model import SiteParameters


def query():
    return ForecastQuery(snapshot_id="original-snapshot", future_policy_id="fixed-current-v1",
                         environment_id="constant-ambient-v1", horizon_s=120,
                         endpoint_protocol="synthetic_capacity_v1", sample_budget=2,
                         current_A=.1, ambient_K=298.15, seed=20261014)


def test_plan_survives_rekeyed_snapshot_while_full_query_identity_differs():
    original = query()
    resumed = original.model_copy(update={"snapshot_id": "resumed-snapshot"})
    parameters = asdict(SiteParameters())
    assert original.model_dump() != resumed.model_dump()
    assert _observation_plan_hash(original, CapacityProtocol(), parameters) == _observation_plan_hash(resumed, CapacityProtocol(), parameters)


@pytest.mark.parametrize("change", [{"current_A": .12}, {"ambient_K": 303.15},
                                   {"horizon_s": 240}, {"sample_budget": 3},
                                   {"seed": 20261015}, {"endpoint_protocol": "unregistered"}])
def test_actual_future_or_protocol_plan_changes_identity(change):
    original = query()
    altered = original.model_copy(update=change)
    parameters = asdict(SiteParameters())
    assert _observation_plan_hash(original, CapacityProtocol(), parameters) != _observation_plan_hash(altered, CapacityProtocol(), parameters)


def test_actual_parameters_and_retirement_protocol_change_identity():
    original = query()
    parameters = asdict(SiteParameters())
    changed = {**parameters, "site_capacity_mol": tuple(x * 1.01 for x in parameters["site_capacity_mol"])}
    baseline = _observation_plan_hash(original, CapacityProtocol(), parameters)
    assert baseline != _observation_plan_hash(original, CapacityProtocol(), changed)
    assert baseline != _observation_plan_hash(original, replace(CapacityProtocol(), retirement_ratio=.7), parameters)
