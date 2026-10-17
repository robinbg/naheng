"""Adversarial nonmonotone protocol curves; no simulated service claim."""
from types import SimpleNamespace
import numpy as np
from naheng.domain.contracts import PosteriorSnapshot, ForecastQuery

def run_curve(monkeypatch, curve):
    import importlib
    module=importlib.import_module('naheng.lifecycle.forecast')
    from naheng.models.site_model import SiteModel
    model=SiteModel()
    state=model.initial_state()
    snapshot=PosteriorSnapshot(snapshot_id='scope-s',run_id='scope-r',obs_until_s=0,
        state_names=list(model.state_names),state_units=list(model.state_units),samples=[state.tolist()],
        weights=[1.],mean={},quantiles={},ess=1)
    query=ForecastQuery(snapshot_id=snapshot.snapshot_id,future_policy_id='fixed-current-v1',
        environment_id='constant-ambient-v1',endpoint_protocol='synthetic_capacity_v1',
        horizon_s=10,current_A=0,sample_budget=1)
    def capacity(sampled,state,protocol):
        # Explicit method control, with the same completed-protocol contract
        # as the real solver; a bare capacity number is no cutoff witness.
        value=100. if state[0]==protocol.initial_occupancy else curve(float(state[0]))
        return {'status':'computed','capacity_C':value,
            'elapsed_s':value/protocol.discharge_current_A,
            'events':[{'name':'voltage_low'}],
            'provenance_type':'synthetic_method_control'}
    def integrate(self,state,current,duration_s,**kwargs):
        final=np.array(state).copy(); final[0]=duration_s
        return SimpleNamespace(state=final,events=[],energy_J=0.,elapsed_s=duration_s,inventory_residual_mol=0.)
    monkeypatch.setattr(module,'protocol_capacity',capacity)
    monkeypatch.setattr(SiteModel,'integrate',integrate)
    monkeypatch.setattr(SiteModel,'observe',lambda self,state,current:{'voltage_V':3.2})
    return module.forecast(snapshot,query,model)

def test_local_late_crossing_cannot_hide_an_earlier_dip_or_become_exact_rul(monkeypatch):
    # Above at origin, below at 1s, recovers, then drops at 9s. Bisection
    # observes a late bracket, so interpreting its right edge as first is wrong.
    result=run_curve(monkeypatch,lambda t:70. if 1<=t<=2 or t>=9 else 100.)
    path=result['paths'][0]
    assert path['rul_s'] is None and path['first_passage_status']=='unknown'
    assert path['observed_crossing_bracket_s'][0]>2
    assert path['first_passage_enclosure_s'][0]==0
    assert result['rul']['samples_s']==[] and not result['rul']['distribution_complete']
    assert result['rul']['interval_censored_count']==1

def test_above_threshold_final_point_does_not_prove_right_censoring(monkeypatch):
    result=run_curve(monkeypatch,lambda t:70. if 1<=t<=2 else 100.)
    assert result['paths'][0]['right_censored'] is None
    assert result['rul']['right_censored_count']==0 and result['rul']['unknown_first_passage_count']==1
    assert result['rul']['median_observed_s'] is None

def test_flat_above_threshold_curve_keeps_first_passage_error_bound_unknown(monkeypatch):
    result=run_curve(monkeypatch,lambda t:100.)
    assert result['rul']['first_passage_error_bound_status']=='unknown'
    assert result['rul']['monotonic_capacity_status']=='unknown'
    assert result['rul']['status']=='unknown'
