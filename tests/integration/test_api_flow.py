from pathlib import Path
from fastapi.testclient import TestClient
from naheng.api.app import create_app
def test_queue_budget_validation_and_no_reference_route():
    root=Path(__file__).resolve().parents[2]
    c=TestClient(create_app(root,dispatch=False))
    assert c.get("/api/health").status_code==200
    assert c.post("/api/runs",json={"ambient_K":20}).status_code==422
    assert c.post("/api/runs",json={"scenario_id":"other"}).status_code==422
    assert c.get("/api/runs/no-such-id").status_code==404
    assert c.get("/api/evaluator/reference_trace").status_code==404
    assert c.get("/api/model-packages/research_base-v1").json()["chemistry_id"]=="synthetic_two_site"


def test_rate_query_schema_does_not_accept_nonfinite_or_client_certificates():
    from naheng.api.app import RunRequest
    from pydantic import ValidationError
    import pytest
    assert RunRequest(stored_sodium_rate_upper_mol_per_s=.001).stored_sodium_rate_upper_mol_per_s==.001
    assert RunRequest().stored_sodium_rate_upper_mol_per_s is None
    for value in (float('inf'),float('nan')):
        with pytest.raises(ValidationError):RunRequest(stored_sodium_rate_upper_mol_per_s=value)
    with pytest.raises(ValidationError):RunRequest(rate_evaluation={'status':'PASS'})
