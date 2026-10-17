from fastapi.testclient import TestClient
import pytest
from naheng.api.app import create_app,RunRequest
from naheng.domain.contracts import ForecastQuery
from naheng.domain.expressions import parse_expression,ExpressionError


def test_process_secret_canary_is_not_published(tmp_path,monkeypatch):
    canary='synthetic-security-canary-not-a-real-secret'
    monkeypatch.setenv('NAHENG_SECRET_SECURITY_TEST',canary)
    client=TestClient(create_app(tmp_path,dispatch=False))
    for url in ('/api/health','/openapi.json','/api/runs'):
        response=client.get(url);assert response.status_code==200
        assert canary not in response.text and 'NAHENG_SECRET_SECURITY_TEST' not in response.text
    assert client.get('/api/evaluator/reference_trace').status_code==404


def test_client_cannot_select_source_code_or_proof_authority():
    for data in ({'source_dir':'untrusted'},{'code_hash':'0'*64},{'proof_root':'untrusted'},{'hardware_write':True}):
        with pytest.raises(ValueError):RunRequest(**data)
    with pytest.raises(ValueError):
        ForecastQuery(snapshot_id='s',future_policy_id='p',environment_id='e',horizon_s=1,endpoint_protocol='x',sample_budget=1,current_A=0,certificate={'status':'PASS'})


def test_upload_bound_and_html_path_controls(tmp_path):
    client=TestClient(create_app(tmp_path,dispatch=False))
    assert client.post('/api/datasets/import',content=b' '*(3*1024*1024+1),headers={'Content-Type':'application/json'}).status_code==413
    packet={'filename':'../../outside.csv','source':'<script>synthetic-control</script>','chemistry_id':'unmapped_sodium','provenance_type':'synthetic','current_sign':'positive_discharge','units':{'timestamp_s':'s','voltage_V':'V','current_A':'A','temperature_K':'K'},'csv_text':'timestamp_s,voltage_V,current_A,temperature_K\n0,3,1,298\n1,3,1,298\n'}
    response=client.post('/api/datasets/import',json=packet);assert response.status_code==201
    identifier=response.json()['dataset_id'];preview=client.get('/api/datasets/'+identifier+'/report-preview')
    assert '<script>' not in preview.text and '&lt;script&gt;' in preview.text
    assert "default-src 'none'" in preview.headers['content-security-policy']
    assert not (tmp_path.parent/'outside.csv').exists()


@pytest.mark.parametrize('text',["__import__('os')","x.__class__","open('secret')","x[0]","1e309"])
def test_uploaded_expression_cannot_escape_numeric_ast(text):
    with pytest.raises(ExpressionError):parse_expression(text,{'x'})
