import json
import pytest
from fastapi.testclient import TestClient
from naheng.api.app import create_app
from naheng.formal.active_evidence import select_core
from naheng.runtime.artifacts import atomic_json,sha256_file

def test_missing_core_reports_unverified_without_runtime_permission(tmp_path):
    client=TestClient(create_app(tmp_path,dispatch=False))
    packet=client.get('/api/capabilities').json()['formal_core']
    assert packet['status']=='unverified' and packet['target_count']==0
    assert client.get('/api/evidence/core').json()['checked'] is False

@pytest.mark.parametrize('name',['../external.json','artifacts/formal/../../outside.json','C:/external.json'])
def test_core_pointer_cannot_select_uncontrolled_path(tmp_path,name):
    atomic_json(tmp_path/'artifacts/formal/active_core.json',{'manifest':name,'sha256':'0'*64})
    assert select_core(tmp_path)[0] is None

def test_hash_matching_checked_label_without_declarations_does_not_publish_core(tmp_path):
    file=tmp_path/'artifacts/formal/fake/manifest.json'
    atomic_json(file,{'suite':'core','checked':True,'exit_code':0,'status':'checked','evidence':[]})
    atomic_json(tmp_path/'artifacts/formal/active_core.json',{'manifest':'artifacts/formal/fake/manifest.json','sha256':sha256_file(file)})
    client=TestClient(create_app(tmp_path,dispatch=False))
    assert client.get('/api/capabilities').json()['formal_core']['status']=='unverified'
    assert client.get('/api/evidence/core').json()['checked'] is False
    file.write_text('{}',encoding='utf-8');assert select_core(tmp_path)[0] is None
