"""Real protocol flow plus explicit adversarial method controls; no cell/N claims."""
import importlib,json,os
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from naheng.domain.contracts import ForecastQuery,PosteriorSnapshot
from naheng.models.site_model import SiteModel,SiteParameters

module=importlib.import_module('naheng.lifecycle.forecast')

def fixture(paths=2,horizon=5):
    model=SiteModel(SiteParameters(site_capacity_mol=(.00012,.00008),
        rate_s_inv=(.01,.006),side_rate_s_inv=(2e-8,4e-8)))
    state=model.initial_state()
    snapshot=PosteriorSnapshot(snapshot_id='obs-shared',run_id='obs-run',obs_until_s=0,
        state_names=list(model.state_names),state_units=list(model.state_units),
        samples=[state.tolist()],weights=[1.],mean={},quantiles={},ess=1)
    query=ForecastQuery(snapshot_id=snapshot.snapshot_id,future_policy_id='fixed-discharge',
        environment_id='constant-298K',horizon_s=horizon,endpoint_protocol='synthetic_capacity_v1',
        sample_budget=paths,current_A=.001,seed=3)
    return model,snapshot,query

def test_real_nonorigin_protocol_grid_is_censored_only_on_observed_grid():
    model,snapshot,query=fixture()
    result=module.forecast(snapshot,query,model)
    output=os.environ.get('NH_E01_REAL_RESULT')
    if output:
        Path(output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    assert result['rul']['capacity_observation_grid_s']==[0.,2.5,5.]
    assert result['rul']['grid_right_censored_count']==2
    assert result['rul']['right_censored_count']==0 and result['rul']['unknown_first_passage_count']==2
    assert result['rul']['samples_s']==[] and result['rul']['monotonic_capacity_status']=='unknown'
    assert result['rul']['capacity_observation_scope']==module.OBSERVATION_SCOPE
    for path in result['paths']:
        entries=path['capacity_observations']
        assert [e['actual_observation_time_s'] for e in entries]==[0.,2.5,5.]
        assert all(e['status']=='observed' and e['capacity_C']>e['threshold_C'] for e in entries)
        assert all(e['protocol_result']['status']=='computed' and any(v['name']=='voltage_low' for v in e['protocol_result']['events']) for e in entries)
        assert all(e['capacity_C']==e['protocol_result']['elapsed_s'] for e in entries) # actual 1A capacity integral
        assert path['observation_censor_time_s']==5. and path['observation_unmeasured_grid_s']==[]
        assert path['rul_s'] is None and path['right_censored'] is None
        assert path['first_passage_status']=='unknown'
    assert result['budget']['unique_solves']<8 and result['budget']['reused_calculations']>=4
    assert result['budget']['capacity_protocol_solves']==4 and result['budget']['forward_integrations']==2
    assert result['budget']['independent_operational_trajectories']==0

def test_observation_plan_hash_is_reproducible_and_query_specific():
    model,snapshot,query=fixture(paths=1)
    a=module.forecast(snapshot,query,model);b=module.forecast(snapshot,query,model)
    c=module.forecast(snapshot,query.model_copy(update={'horizon_s':6}),model)
    assert a['rul']['capacity_observation_plan_hash']==b['rul']['capacity_observation_plan_hash']
    assert a['paths']==b['paths']
    assert a['rul']['capacity_observation_plan_hash']!=c['rul']['capacity_observation_plan_hash']

def test_protocol_unknown_keeps_all_requested_paths_in_observation_denominator(monkeypatch):
    model,snapshot,query=fixture()
    monkeypatch.setattr(module,'protocol_capacity',lambda *args:{'status':'unknown','capacity_C':None,'reason':'competing_protocol_exit'})
    result=module.forecast(snapshot,query,model)
    assert result['rul']['observation_requested_path_denominator']==2==len(result['paths'])
    assert result['rul']['observation_unknown_path_count']==2 and result['rul']['grid_right_censored_count']==0
    assert all(p['observation_last_time_s'] is None and p['observation_unmeasured_grid_s']==[0.,2.5,5.] for p in result['paths'])
    assert result['rul']['samples_s']==[]

def test_a_protocol_exception_keeps_actual_earlier_observation_and_unmeasured_point(monkeypatch):
    model,snapshot,query=fixture(paths=1)
    real=module.protocol_capacity;calls=[0]
    def controlled_error(*args):
        calls[0]+=1
        if calls[0]==3:raise RuntimeError('injected protocol failure at middle observation')
        return real(*args)
    monkeypatch.setattr(module,'protocol_capacity',controlled_error)
    result=module.forecast(snapshot,query,model);path=result['paths'][0]
    assert path['observation_status']=='observation_partial' and path['observation_right_censored'] is None
    assert path['observation_unmeasured_grid_s']==[2.5] and path['observation_last_time_s']==5.
    assert any(e['status']=='protocol_unknown' and e['reason']=='capacity_solver_failed' for e in path['capacity_observations'])
    assert result['rul']['observation_requested_path_denominator']==1 and result['rul']['observation_partial_path_count']==1

def fake_completed_capacity(*args):
    return {'status':'computed','capacity_C':100.,'elapsed_s':100.,'events':[{'name':'voltage_low','time_s':100.}]}

def event_control(monkeypatch,exit_time):
    monkeypatch.setattr(module,'protocol_capacity',fake_completed_capacity)
    def integrate(self,state,current,duration_s,**kwargs):
        elapsed=min(duration_s,exit_time);s=np.array(state).copy();s[0]=elapsed
        return SimpleNamespace(state=s,events=[{'name':'voltage_low','time_s':elapsed}] if elapsed<duration_s else [],
            energy_J=3.2*current*elapsed,elapsed_s=elapsed,inventory_residual_mol=0.)
    monkeypatch.setattr(SiteModel,'integrate',integrate)
    monkeypatch.setattr(SiteModel,'observe',lambda *args:{'voltage_V':3.2})

@pytest.mark.parametrize('exit_time,unmeasured',[ (3.,[5.,10.]), (5.,[10.]), (10.-1e-7,[10.]) ])
def test_terminal_event_records_actual_time_never_requested_horizon(monkeypatch,exit_time,unmeasured):
    event_control(monkeypatch,exit_time)
    model,snapshot,query=fixture(paths=1,horizon=10)
    result=module.forecast(snapshot,query,model);path=result['paths'][0]
    assert path['elapsed_s']==exit_time and path['observation_last_time_s']==exit_time
    assert path['observation_unmeasured_grid_s']==unmeasured and path['observation_status']=='observation_partial'
    assert path['observation_right_censored'] is None and path['observation_censor_time_s'] is None
    assert max(e['actual_observation_time_s'] for e in path['capacity_observations'] if e['status']=='observed')==exit_time
    assert result['rul']['grid_right_censored_count']==0 and result['rul']['right_censored_count']==0

def test_budget_after_completed_initial_protocol_retains_real_measurement(monkeypatch):
    model,snapshot,query=fixture();real=module.protocol_capacity;calls=[0];exhausted=[False]
    def finish_before_budget(*args):
        result=real(*args);calls[0]+=1
        if calls[0]==2:exhausted[0]=True
        return result
    monkeypatch.setattr(module,'protocol_capacity',finish_before_budget)
    monkeypatch.setattr(module.time,'monotonic',lambda:2. if exhausted[0] else 0.)
    result=module.forecast(snapshot,query,model,wall_budget_s=1.)
    first,second=result['paths']
    assert first['status']=='budget_interrupted' and first['capacity_observations'][0]['status']=='observed'
    assert first['observation_last_time_s']==0. and first['observation_unmeasured_grid_s']==[2.5,5.]
    assert first['observation_status']=='observation_partial' and first['observation_right_censored'] is None
    assert second['status']=='not_run_budget' and second['observation_last_time_s'] is None
    assert result['rul']['observation_requested_path_denominator']==2 and result['rul']['observation_unknown_path_count']==2
    assert result['risk']['events']['voltage_low']['probability'] is None

def test_incomplete_protocol_values_do_not_become_observations_or_origin_rul(monkeypatch):
    model,snapshot,query=fixture(paths=1)
    calls=[0]
    def bad_result(*args):
        calls[0]+=1
        return {'status':'computed','capacity_C':100. if calls[0]==1 else 1.,'elapsed_s':1.,'events':[]}
    monkeypatch.setattr(module,'protocol_capacity',bad_result)
    result=module.forecast(snapshot,query,model);path=result['paths'][0]
    assert path['observation_last_time_s'] is None and not path['observation_grid_complete']
    assert path['rul_s'] is None and result['rul']['samples_s']==[]
    assert path['capacity_initial_C'] is None and path['capacity_final_C'] is None
    assert all(e['capacity_C'] is None for e in path['capacity_observations'])

def test_unknown_endpoint_protocol_has_no_fabricated_grid_values():
    model,snapshot,query=fixture(paths=1)
    result=module.forecast(snapshot,query.model_copy(update={'endpoint_protocol':'not-declared'}),model)
    path=result['paths'][0]
    assert path['capacity_observations']==[] and path['observation_last_time_s'] is None
    assert path['observation_unmeasured_grid_s']==[0.,2.5,5.]
    assert result['rul']['observation_unknown_path_count']==1 and result['rul']['samples_s']==[]
