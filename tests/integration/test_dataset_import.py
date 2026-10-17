import hashlib
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from naheng.api.app import create_app

CSV = 'timestamp_s,voltage_V,current_A,temperature_K\n0,3,2,298.15\n10,3,2,299.15\n'

def payload(**changes):
    return dict(filename='measured.csv', source='User sensor export', chemistry_id='unmapped_sodium',
        provenance_type='public_measurement', current_sign='positive_discharge',
        units={'timestamp_s':'s','voltage_V':'V','current_A':'A','temperature_K':'K'}, csv_text=CSV, **changes)

def create(client, value=None):
    response = client.post('/api/datasets/import', json=value or payload())
    assert response.status_code == 201, response.text
    return response.json()

def test_real_uploaded_rows_source_bytes_accounting_reopen_and_exports(tmp_path):
    client = TestClient(create_app(tmp_path, dispatch=False))
    packet = create(client)
    identifier = packet['dataset_id']
    assert packet['row_count'] == 2
    assert packet['analysis']['discharge_throughput_Ah'] == 20/3600
    assert packet['analysis']['discharge_port_energy_J'] == 60
    assert packet['source_csv_sha256'] == hashlib.sha256(CSV.encode()).hexdigest()
    assert packet['provenance_type'] == 'public_measurement'
    assert packet['provenance_verification'] == 'user_declared_unverified'
    assert packet['model_assimilation']['status'] == 'unknown'
    for key in ('capacity_Ah','SOH','RUL_s','risk_probability'): assert packet['analysis'][key] is None
    assert packet['analysis']['independent_operating_n'] == 0
    reopened = TestClient(create_app(tmp_path, dispatch=False))
    assert reopened.get('/api/datasets/'+identifier).json() == packet
    assert reopened.get('/api/datasets').json()[0]['dataset_id'] == identifier
    for key in ('source','observations','analysis','report'):
        response = reopened.get(f'/api/datasets/{identifier}/artifacts/{key}')
        assert response.status_code == 200
        assert 'attachment' in response.headers['content-disposition']
    assert reopened.get(f'/api/datasets/{identifier}/artifacts/source').content == CSV.encode()
    assert reopened.get(f'/api/datasets/{identifier}/artifacts/analysis').json() == packet

def test_sign_conversion_and_exact_linear_port_product_with_zero_crossing(tmp_path):
    client = TestClient(create_app(tmp_path, dispatch=False))
    value = payload(); value['current_sign']='positive_charge'
    packet = create(client, value)
    assert packet['observations'][0]['current_A'] == -2
    assert packet['analysis']['charge_throughput_Ah'] == 20/3600
    assert packet['analysis']['charge_port_energy_J'] == 60
    value = payload(); value['csv_text']='timestamp_s,voltage_V,current_A,temperature_K\n0,3,1,298.15\n10,4,-1,299.15\n'
    result = create(client, value)['analysis']
    assert result['charge_throughput_Ah'] == pytest.approx(2.5/3600)
    assert result['discharge_throughput_Ah'] == pytest.approx(2.5/3600)
    assert result['discharge_port_energy_J'] == pytest.approx(95/12)
    assert result['charge_port_energy_J'] == pytest.approx(115/12)
    assert result['net_outward_port_energy_J'] == pytest.approx(-5/3)

@pytest.mark.parametrize('patch', [
    {'units':{}}, {'units':{'timestamp_s':'h','voltage_V':'V','current_A':'A','temperature_K':'K'}},
    {'current_sign':'auto'}, {'source':''}, {'chemistry_id':'../../model'}, {'provenance_type':'checked'},
    {'csv_text':CSV.replace('10,3,2','0,3,2')}, {'csv_text':CSV.replace('10,3,2','-1,3,2')},
    {'csv_text':CSV.replace('0,3,2','0,nan,2')}, {'csv_text':CSV.replace('298.15','0')},
    {'csv_text':CSV.replace('0,3,2','0,=2+1,2')}, {'csv_text':CSV.replace('current_A','current_mA')},
    {'csv_text':CSV.splitlines()[0]+'\n0,3,2,298.15\n'}, {'csv_text':CSV.replace('0,3,2,298.15','0,3,2,298.15,7')},
])
def test_invalid_units_clocks_columns_numeric_and_identity_never_create_results(tmp_path, patch):
    client=TestClient(create_app(tmp_path, dispatch=False)); value=payload();value.update(patch)
    assert client.post('/api/datasets/import',json=value).status_code == 422
    assert client.get('/api/datasets').json() == []

def test_bytes_and_rows_bounded_before_analysis(tmp_path):
    client=TestClient(create_app(tmp_path, dispatch=False))
    response=client.post('/api/datasets/import',content=b' '*(3*1024*1024+1),headers={'Content-Type':'application/json'})
    assert response.status_code == 413
    value=payload();value['csv_text']=CSV.splitlines()[0]+'\n'+''.join(f'{i},3,2,298.15\n' for i in range(5001))
    assert client.post('/api/datasets/import',json=value).status_code == 422
    value['csv_text']='x'*(2*1024*1024+1)
    assert client.post('/api/datasets/import',json=value).status_code == 422
    assert client.get('/api/datasets').json() == []

def test_reports_escape_source_and_never_use_filename_as_path(tmp_path):
    client=TestClient(create_app(tmp_path, dispatch=False));value=payload()
    value.update(filename='../../outside.csv',source='<script>alert(1)</script>')
    packet=create(client,value)
    assert not (tmp_path.parent/'outside.csv').exists()
    response=client.get(f"/api/datasets/{packet['dataset_id']}/report-preview")
    assert response.status_code == 200
    assert '<script>' not in response.text and '&lt;script&gt;' in response.text
    assert "default-src 'none'" in response.headers['content-security-policy']
    assert client.get(f"/api/datasets/{packet['dataset_id']}/artifacts/../../outside").status_code == 404
    assert client.get(f"/api/datasets/{packet['dataset_id']}/artifacts/secret").status_code == 404

@pytest.mark.parametrize('filename',['source.csv','analysis.json','observations.csv','report.html'])
def test_tampered_registered_artifacts_fail_closed(tmp_path,filename):
    client=TestClient(create_app(tmp_path,dispatch=False));packet=create(client)
    identifier=packet['dataset_id'];file=tmp_path/'artifacts/datasets'/identifier/filename
    file.write_bytes(file.read_bytes()+b' ')
    key={'source.csv':'source','analysis.json':'analysis','observations.csv':'observations','report.html':'report'}[filename]
    assert client.get(f'/api/datasets/{identifier}/artifacts/{key}').status_code == 409
    if filename in ('source.csv','analysis.json'): assert client.get('/api/datasets/'+identifier).status_code == 409
