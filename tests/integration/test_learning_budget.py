"""Original A03 public-target acceptance: budgeted fitted search and full policy mapping."""
from copy import deepcopy
import json
import numpy as np
import pytest
from naheng.learning.constrained_bo import Search, Limits, BudgetExhausted, digest
from naheng.learning.multifidelity import GaussianProcess
from naheng.learning.policy_space import BOUNDS, fixed_world, map_policy, validate
from naheng.learning.strategy_mpc import quantize_current_towards_zero


def result(request,status='completed'):
    return {'status':status,'utility':-float(np.square(np.asarray(request['x'])-.6).sum()) if status=='completed' else None,
        'constraint_margin':-.1 if status=='completed' else None,'cost_s':.1,'source_id':'train',
        'run_id':'mathematical-control-'+request['reservation_id'],'evidence_sha256':'1'*64,
        'reason':None if status=='completed' else 'synthetic interruption control'}


def test_real_fitted_nine_coordinate_search_counts_pending_unknown_and_completed():
    s=Search(BOUNDS,{'train':'train','test':'test'},Limits(initial_points=3,iterations=3,high_fidelity_calls=2))
    for index in range(6):
        request=s.ask()
        with pytest.raises(ValueError):s.ask()
        s.tell(request,result(request,'unknown' if index==0 else 'completed'))
    assert len(s.events)==6 and sum(e['fidelity']=='high' for e in s.events)<=2
    assert s.events[0]['result']['utility'] is None
    with pytest.raises(BudgetExhausted):s.ask()
    s._fit()
    assert len(s.utility.low.y)+len(s.utility.delta.y)==5
    assert s.utility.low.x.shape[1]==9


def test_full_policy_preserves_common_world_but_changes_all_required_controls():
    low={n:b[0] for n,b in BOUNDS.items()};high={n:b[1] for n,b in BOUNDS.items()}
    a,b=map_policy(low),map_policy(high)
    assert a['world']==b['world']==fixed_world() and a['world_sha256']==b['world_sha256']
    assert a['policy_mpc_parameters']['soc_bands']!=b['policy_mpc_parameters']['soc_bands']
    for field in ('voltage_max_V','max_dod','thermal_min_W','thermal_max_W'):
        assert a['policy_mpc_parameters'][field]!=b['policy_mpc_parameters'][field]
    assert all(s['min_current_A']<0<s['max_current_A'] for s in a['stages'])
    assert all(s['min_current_A']==s['max_current_A']==0 for s in b['stages'][:2])
    assert sum(s['duration_s'] for s in a['stages'][:4])==10
    assert a['world']['stages']==b['world']['stages']


@pytest.mark.parametrize('duration,expected',[(0.,0.),(1.24,0.),(1.25,2.5),(2.5,2.5),(3.75,5.),(5.,5.)])
def test_timing_quantization_is_explicit_and_does_not_shift_prices(duration,expected):
    p={n:sum(b)/2 for n,b in BOUNDS.items()};p['rest_duration_s']=duration
    mapped=map_policy(p)
    assert mapped['timing']['effective_rest_s']==expected
    assert mapped['world']==fixed_world()


def test_bad_policy_or_world_never_enters_mpc():
    p={n:sum(b)/2 for n,b in BOUNDS.items()}
    for name in BOUNDS:
        bad={**p,name:True}
        with pytest.raises(ValueError):validate(bad)
    badworld=deepcopy(fixed_world());badworld['stages'][0]['sell_price_per_kWh']*=2
    with pytest.raises(ValueError):map_policy(p,world=badworld)
    with pytest.raises(ValueError):GaussianProcess(17)
    with pytest.raises(ValueError):GaussianProcess(True)
    assert GaussianProcess(9).dimension==9


def test_heldout_and_corrupt_pending_checkpoint_cannot_fit(tmp_path):
    s=Search(BOUNDS,{'train':'train','test':'test'},Limits(initial_points=2,iterations=2,high_fidelity_calls=1))
    request=s.ask();bad=result(request);bad['source_id']='test'
    with pytest.raises(ValueError):s.tell(request,bad)
    path=tmp_path/'checkpoint.json';s.checkpoint(path)
    valid=json.loads(path.read_text())
    for field,value in [('ordinal',99),('candidate_id','0'*64),('protocol_sha256','0'*64),('timeout_s',121.)]:
        invalid=deepcopy(valid);next(iter(invalid['state']['pending'].values()))[field]=value
        invalid['state_sha256']=digest(invalid['state']);path.write_text(json.dumps(invalid))
        with pytest.raises(ValueError):Search.restore(path,s.protocol_sha256)
    path.write_text(json.dumps(valid));restored=Search.restore(path,s.protocol_sha256)
    restored.tell(request,result(request))
    assert len(restored.events)==1


def test_unknown_cost_never_becomes_fake_objective_label():
    s=Search(BOUNDS,{'train':'train'},Limits(initial_points=1,iterations=0,high_fidelity_calls=0))
    request=s.ask();response=result(request,'unknown');response['cost_s']=None
    s.tell(request,response);s._fit()
    assert s.utility.low.factor is None and s.utility.delta.factor is None
    assert s.events[0]['result']['utility'] is None


def test_explicit_current_resolution_never_rounds_outwards():
    for value in (0.,1e-12,-1e-12,.010000000000433398,-.010000000000433398,.01712345678,-.01712345678):
        actual=quantize_current_towards_zero(value)
        assert abs(actual)<=abs(value)
        assert abs(value)-abs(actual)<1.0000001e-8
        assert actual==0 or np.sign(actual)==np.sign(value)
    assert quantize_current_towards_zero(.010000000000433398)<=.01
