"""Labelled method controls; stub protocol/forward results, no real-cell/ODE/N."""
import importlib
from types import SimpleNamespace
import numpy as np
from naheng.domain.contracts import ForecastQuery,PosteriorSnapshot
from naheng.models.site_model import SiteModel,SiteParameters

module=importlib.import_module('naheng.lifecycle.forecast')

def controlled_forecast(monkeypatch,kind):
    model=SiteModel(SiteParameters(site_capacity_mol=(.00012,.00008),
        rate_s_inv=(.01,.006),side_rate_s_inv=(2e-8,4e-8)))
    state=model.initial_state()
    def integrate(state,current,duration_s,ambient_K=None):
        final=np.asarray(state).copy();final[2]+=duration_s*1e-8
        return SimpleNamespace(state=final,events=[],elapsed_s=float(duration_s),
            energy_J=0.,inventory_residual_mol=0.)
    monkeypatch.setattr(model,'integrate',integrate)
    monkeypatch.setattr(model,'observe',lambda state,current:{'voltage_V':3.4,'temperature_K':float(state[4])})
    monkeypatch.setattr(module,'particle_model',lambda original,rate,side:original)
    calls=[]
    def protocol_result(model,state,protocol):
        index=len(calls)
        sequence={'invalid_all':[100.,1.,1.,1.],
            'invalid_final':[100.,90.,85.,10.],
            'invalid_probe':[100.,90.,85.,70.]}[kind]
        value=sequence[index] if index<len(sequence) else 60.
        status='computed';events=[{'name':'voltage_low','time_s':value}]
        if kind=='invalid_all':
            status='unknown';events+=[{'name':'temperature_high','time_s':value}]
        elif kind=='invalid_final' and index>=3:
            events+=[{'name':'temperature_high','time_s':value}]
        elif kind=='invalid_probe' and index>=4:
            status='unknown';events+=[{'name':'temperature_high','time_s':value}]
        result={'status':status,'capacity_C':value,'elapsed_s':value,'events':events,
            'reason':'labelled_synthetic_protocol_control'}
        calls.append(result);return result
    monkeypatch.setattr(module,'protocol_capacity',protocol_result)
    snapshot=PosteriorSnapshot(snapshot_id='invalid-protocol-method-snapshot',
        run_id='labelled-method-no-physical-run',obs_until_s=0,
        state_names=list(model.state_names),state_units=list(model.state_units),
        samples=[state.tolist()],weights=[1.],mean={},quantiles={},ess=1)
    query=ForecastQuery(snapshot_id=snapshot.snapshot_id,future_policy_id='labelled-stub',
        environment_id='constant-298K',horizon_s=8,endpoint_protocol='synthetic_capacity_v1',
        sample_budget=1,current_A=.001,seed=3)
    result=module.forecast(snapshot,query,model)
    path=result['paths'][0]
    assert path['rul_s'] is None and result['rul']['samples_s']==[]
    assert result['rul']['right_censored_count']==0
    assert len(result['paths'])==result['rul']['observation_requested_path_denominator']==1
    assert result['budget']['independent_operational_trajectories']==0
    return result,path,calls

def test_unknown_numeric_protocol_values_cannot_create_crossing_interval(monkeypatch):
    result,path,_=controlled_forecast(monkeypatch,'invalid_all')
    assert all(entry['capacity_C'] is None for entry in path['capacity_observations'])
    assert path['capacity_initial_C'] is None and path['capacity_final_C'] is None
    assert path['observation_status']=='observation_unknown'
    assert path.get('observed_crossing_bracket_s') is None
    assert path.get('first_passage_enclosure_s') is None
    assert path['right_censored'] is None and path['censoring']!='interval'

def test_competing_numeric_final_protocol_cannot_create_crossing_interval(monkeypatch):
    result,path,_=controlled_forecast(monkeypatch,'invalid_final')
    assert path['capacity_initial_C']==90. and path['capacity_final_C'] is None
    assert path['observation_status']=='observation_partial'
    assert path.get('observed_crossing_bracket_s') is None
    assert path.get('first_passage_enclosure_s') is None
    assert path['right_censored'] is None and path['censoring']!='interval'

def test_invalid_numeric_bracket_probe_cannot_shrink_verified_upper_witness(monkeypatch):
    result,path,_=controlled_forecast(monkeypatch,'invalid_probe')
    assert path['capacity_final_C']==70.
    below=[entry['actual_observation_time_s'] for entry in path['capacity_observations']
        if entry['status']=='observed' and entry['at_or_below_threshold'] is True]
    assert below and min(below)==8.
    enclosure=path.get('first_passage_enclosure_s')
    assert enclosure is None or enclosure[1]>=min(below)
