"""Real lifecycle API/worker inputs, cancellation, immutable output and replay."""
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from naheng.api.app import create_app
from naheng.runtime.artifacts import code_hash
from naheng.runtime.freezing import freeze_source
from naheng.runtime.jobs import JobStore
from naheng.runtime.lifecycle_jobs import read_lifecycle_result

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path):
    frozen,_=freeze_source(ROOT,tmp_path/'initial')
    return frozen


def await_terminal(client,run_id,limit=110):
    started=time.monotonic()
    while time.monotonic()-started<limit:
        row=client.get('/api/runs/'+run_id).json()
        if row['state'] in {'succeeded','failed','cancelled','interrupted'}: return row
        time.sleep(.1)
    raise AssertionError('Actual lifecycle worker did not finish in test budget')


def test_lifecycle_input_rejects_code_paths_nonfinite_and_shared_quota(project):
    client=TestClient(create_app(project,dispatch=False))
    for body in ({'profile':'release'},{'source_dir':'C:/Windows'},{'replacement_cost_CNY':True},
                 {'sell_price_per_kWh':'0.30'},{'buy_price_per_kWh':-1},{'replacement_cost_CNY':100001}):
        assert client.post('/api/lifecycle-jobs',json=body).status_code==422
    first=client.post('/api/lifecycle-jobs',json={'mode':'batch'}).json()
    assert first['config']['task_kind']=='lifecycle-finance'
    assert client.get('/api/runs/'+first['run_id']+'/lifecycle').status_code==409
    assert client.post('/api/runs/'+first['run_id']+'/cancel').json()['state']=='cancelled'
    store=JobStore(project/'artifacts/runs')
    for _ in range(4): store.create({'mode':'interactive'})
    assert client.post('/api/lifecycle-jobs',json={}).status_code==429


def test_actual_lifecycle_worker_export_replay_and_checksum(project):
    with TestClient(create_app(project)) as client:
        created=client.post('/api/lifecycle-jobs',json={'mode':'batch','replacement_cost_CNY':120,
                              'sell_price_per_kWh':.45,'buy_price_per_kWh':.2})
        assert created.status_code==202
        run_id=created.json()['run_id']
        row=await_terminal(client,run_id)
        assert row['state']=='succeeded',row
        response=client.get('/api/runs/'+run_id+'/lifecycle')
        assert response.status_code==200
        packet=response.json()
        assert len(packet['cases'])==8 and all(x['valid_execution'] for x in packet['cases'])
        assert packet['code_hash']==row['config']['code_hash']==code_hash(project)
        assert packet['parameters']['replacement_cost_CNY']==120
        assert packet['registration']['financial_assumptions']['replacement_cost_CNY_per_asset']==120
        assert packet['registration']['energy_economics']['sell_price_per_kWh']==.45
        module=next(x for x in packet['cases'] if x['mode']=='module')
        assert module['execution']['replacement_count']==1
        assert len(module['endpoints']['final']['assets'])==4
        assert module['finance']['cash_events'][0]['cost_CNY']==120
        assert module['finance']['planning_shadow_deducted_CNY']==0
        assert all(a['rul_s'] is None for a in module['endpoints']['final']['assets'])
        assert packet['independent_operating_n']==0 and not packet['independent_sample']
        report=client.get('/api/runs/'+run_id+'/report-preview')
        assert report.status_code==200 and run_id in report.text
        assert 'Content-Security-Policy'.casefold() in {k.casefold() for k in report.headers}
        for artifact in ('result','points','report'):
            assert client.get('/api/runs/'+run_id+'/artifacts/'+artifact).status_code==200
        replay=client.post('/api/replays',json={'run_id':run_id}).json()['run_id']
        replay_result=client.get('/api/runs/'+replay+'/lifecycle').json()
        assert replay_result['mode']=='replay' and replay_result['source_run_id']==run_id
        assert replay_result['cases']==packet['cases'] and not replay_result['independent_sample']
        events=client.get('/api/runs/'+run_id+'/events').json()
        assert len([e for e in events if e['type']=='lifecycle_case'])==8
        dest=project/'artifacts/runs'/run_id
        original_report=(dest/'report.html').read_bytes()
        (dest/'report.html').write_bytes(original_report+b' ')
        assert client.get('/api/runs/'+run_id+'/artifacts/report').status_code==409
        assert client.get('/api/runs/'+run_id+'/report-preview').status_code==409
        (dest/'report.html').write_bytes(original_report)
        original=(dest/'result.json').read_bytes()
        (dest/'result.json').write_bytes(original+b' ')
        assert client.get('/api/runs/'+replay+'/lifecycle').status_code==409
        assert client.get('/api/runs/'+run_id+'/report-preview').status_code==409


def test_lifecycle_cancel_retains_failed_cases_not_success(project):
    with TestClient(create_app(project)) as client:
        run_id=client.post('/api/lifecycle-jobs',json={}).json()['run_id']
        started=time.monotonic()
        while time.monotonic()-started<15:
            if client.get('/api/runs/'+run_id).json()['state']=='running': break
            time.sleep(.05)
        client.post('/api/runs/'+run_id+'/cancel')
        row=await_terminal(client,run_id)
        assert row['state']=='cancelled'
        assert client.post('/api/replays',json={'run_id':run_id}).status_code==409
        store=JobStore(project/'artifacts/runs')
        packet=read_lifecycle_result(store,run_id)
        assert packet['experiment_manifest']['exit_code']==2
        assert not all(x['valid_execution'] for x in packet['cases'])
        assert packet['independent_operating_n']==0
        assert not json.loads((store.root/run_id/'manifest.json').read_bytes())['complete']
        assert not packet['run_complete']
        assert client.get('/api/runs/'+run_id+'/manifest').status_code==200
        assert client.post('/api/reports',json={'run_id':run_id}).status_code==201
        assert 'cancelled' in client.get('/api/runs/'+run_id+'/report-preview').text
        assert client.get('/api/runs/'+run_id+'/artifacts/result').status_code==200


@pytest.mark.parametrize('cancel_before',[True,False])
def test_cancel_publication_transaction_window(project,monkeypatch,cancel_before):
    import threading
    from naheng.runtime import lifecycle_jobs as module
    store=JobStore(project/'artifacts/runs')
    identifier=store.create({'task_kind':'lifecycle-finance','mode':'interactive'})['run_id']
    assert store.try_start(identifier)
    dest=store.root/identifier
    dest.mkdir()
    manifest={'exit_code':0,'code_hash':'0'*64,'artifact_index':{'result':'result.json','report':'report.html'}}
    packet={'source_run_id':identifier,'code_hash':'0'*64,'cases':[]}
    entered,released=threading.Event(),threading.Event()
    actual_atomic=module.atomic_json
    def controlled_write(path,value):
        if path.name=='result.json':
            entered.set()
            assert released.wait(5)
        actual_atomic(path,value)
    monkeypatch.setattr(module,'atomic_json',controlled_write)
    if cancel_before: store.cancel(identifier)
    failures=[]
    def finalize():
        try: module.finalize_lifecycle_job(store,identifier,dest,packet,manifest)
        except Exception as error: failures.append(error)
    writer=threading.Thread(target=finalize)
    writer.start()
    assert entered.wait(5)
    canceller=None
    if not cancel_before:
        canceller=threading.Thread(target=lambda:store.cancel(identifier))
        canceller.start()
    released.set()
    writer.join(5)
    if canceller is not None: canceller.join(5)
    assert not writer.is_alive() and not failures
    row=store.get(identifier)
    assert row['state']==('cancelled' if cancel_before else 'succeeded')
    saved=json.loads((dest/'manifest.json').read_bytes())
    assert saved['complete'] is (not cancel_before)
    assert saved['exit_code']==(2 if cancel_before else 0)
    assert packet['run_complete'] is (not cancel_before)
