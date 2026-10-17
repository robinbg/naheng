import pytest
from pydantic import ValidationError
from naheng.domain.contracts import Observation, Action, ForecastQuery, Evidence

def test_observation_has_no_hidden_state_and_rejects_identity():
    base = dict(run_id="r",timestamp_s=0,current_A=1,voltage_V=3,temperature_K=298)
    with pytest.raises(ValidationError): Observation(**base, true_soc=.9)
    with pytest.raises(ValidationError): Observation(**base,chemistry_id="lithium")

def test_conditioned_query_and_conflicting_action():
    with pytest.raises(ValidationError): ForecastQuery(snapshot_id="s",horizon_s=50)
    with pytest.raises(ValidationError): Action(action_id="a",snapshot_id="s",start_s=0,duration_s=10,current_A=1,power_W=3)

def test_proof_claim_requires_artifacts():
    with pytest.raises(ValidationError): Evidence(evidence_id="e",statement_text="balance",status="checked",category="formal_kernel",applicability="applicable")
