"""Real local command and worker integration; synthetic physics is labelled.

The short API test covers lineage, not the separate unchanged default CLI gate.
No proof fixture or numerical result is prewritten for the worker.
"""
import json
from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient
import pytest
import yaml

from naheng.api.app import create_app
from naheng.runtime.artifacts import code_hash
from naheng.runtime.freezing import freeze_source
from naheng.runtime.verification import verify

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('profile,expected', [('smoke',0),('application',1),('formal',2),('release',1)])
def test_profiles_retain_actual_native_codes_and_run_every_required_gate(tmp_path,profile,expected):
    """Technical native-exit controls, never evidence for science/application."""
    project=tmp_path/'technical-command-fixture'
    (project/'configs').mkdir(parents=True)
    profiles={}
    for name,code in [('smoke',0),('application',1),('formal',2),('release',1)]:
        profiles[name]=[{'id':'native_outcome','command':['{python}','-c',
            f"import sys;print('technical native control');sys.exit({code})"],'timeout_s':10},
            {'id':'required_after_outcome','command':['{python}','-c',"print('required followup actually ran')"],'timeout_s':10}]
    (project/'configs/gates.yaml').write_text(yaml.safe_dump({'profiles':profiles}))
    result=verify(project,profile)
    assert result['profile']==profile and result['exit_code']==expected
    assert result['source_and_gates_unchanged']
    assert [r['exit_code'] for r in result['checks']]==[expected,0]
    assert all(r['executed'] and r['memory_limit_enforced'] for r in result['checks'])
    assert not any(r['is_code_execution_sandbox'] for r in result['checks'])
    assert 'required followup actually ran' in (Path(result['checks'][1]['logs'])/'required_after_outcome.stdout.log').read_text()


def test_actual_sensor_to_posterior_action_forecast_cashflow_and_report_share_run(tmp_path):
    project,_=freeze_source(ROOT,tmp_path/'project')
    with TestClient(create_app(project)) as client:
        created=client.post('/api/runs',json={'duration_s':60,'ambient_K':303.15,'sell_price_per_kWh':.35})
        assert created.status_code==202
        run_id=created.json()['run_id']
        start=time.monotonic()
        while time.monotonic()-start<115:
            job=client.get('/api/runs/'+run_id).json()
            if job['state'] in {'succeeded','failed','cancelled','interrupted'}:break
            time.sleep(.1)
        assert job['state']=='succeeded',job
        prefix='/api/runs/'+run_id
        manifest=client.get(prefix+'/manifest').json()
        assert manifest['complete'] and manifest['run_id']==run_id
        assert manifest['code_hash']==job['config']['code_hash']==code_hash(project)
        snapshots=client.get(prefix+'/snapshots').json()
        trace=client.get(prefix+'/trace').json()
        decisions=client.get(prefix+'/decisions').json()
        forecast=client.get(prefix+'/forecast').json()
        economics=client.get(prefix+'/economics').json()
        assert len(snapshots)==len(trace)==2 and len(decisions)==1
        assert all(row['run_id']==run_id for row in trace+snapshots)
        assert trace[-1]['timestamp_s']==snapshots[-1]['obs_until_s']==60
        query=client.get(prefix+'/artifacts/query').json()
        assert query['snapshot_id']==snapshots[-1]['snapshot_id']
        assert forecast['query_hash'] and len(forecast['paths'])==job['config']['forecast_paths']
        assert decisions[0]['snapshot_id']==snapshots[0]['snapshot_id']
        assert decisions[0]['decision']=='accept'
        assert economics['run_id']==run_id
        report=client.get(prefix+'/report-preview')
        assert report.status_code==200 and run_id in report.text
        assert client.post('/api/reports',json={'run_id':run_id}).status_code==201
        replay=client.post('/api/replays',json={'run_id':run_id}).json()['run_id']
        saved=client.get('/api/runs/'+replay+'/manifest').json()
        assert replay!=run_id and saved['run_id']==run_id and saved['reused_from']==run_id
        assert not saved['independent_sample']
