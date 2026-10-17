import copy,json
import numpy as np
import pytest
from naheng.discovery.grammar import CandidateError,canonical_sha
from naheng.discovery.dataset import build_dataset
from naheng.discovery.counterexamples import evaluate_candidate
from naheng.discovery.learner import (BayesianLearner,FEATURE_NAMES,trusted_registry,
    feature_vector,feedback_targets,validate_feedback)
from naheng.discovery.acquisition import DEFAULT_CONFIG,rank_pool,realized_utility
from naheng.discovery.session import make_pool,bound_feedback,run_pilot

@pytest.fixture
def inputs():
    data=build_dataset();registry=trusted_registry(data);pool=make_pool(data,registry)
    return data,registry,pool

def cfg():
    c=copy.deepcopy(DEFAULT_CONFIG);c.update(initial_points=3,iterations=4);return c

def actual(item,registry):
    return bound_feedback(item,evaluate_candidate(item['candidate'],registry[item['model_id']]['model'],numeric_replay=True),registry)

def test_no_answer_features_and_real_model_training(inputs):
    data,registry,pool=inputs;learner=BayesianLearner();item=pool[0];row=actual(item,registry)
    assert set(item['features'])==set(FEATURE_NAMES)
    for key in ['status','condition_satisfied','nontrivial_output','residual','equal_coefficients']:
        bad={**item['features'],key:1}
        with pytest.raises(CandidateError):feature_vector(bad)
    before=learner.state();targets=learner.update(item,row,registry)
    assert targets and learner.state()!=before
    head=learner.heads['coverage'];X=np.array(head.X);y=np.array(head.y)
    expected=np.linalg.solve(np.eye(len(FEATURE_NAMES))+X.T@X,X.T@y)
    assert np.allclose(head.state()['mean'],expected)

def test_relabelled_heldout_feedback_and_acquisition_rejected(inputs):
    data,registry,pool=inputs;item=pool[0];row=actual(item,registry)
    heldout=data['roles']['test'][0]
    for field,value in [('model_id',heldout['model_id']),('model_sha256',canonical_sha(heldout)),
                        ('structural_family_id',heldout['structural_family_id'])]:
        forged=copy.deepcopy(row);forged[field]=value;forged['role']='train';forged['used_for_search']=True
        with pytest.raises(CandidateError):validate_feedback(item,forged,registry)
    fake=copy.deepcopy(item);fake.update(model_id=heldout['model_id'],role='train')
    with pytest.raises(CandidateError):rank_pool([fake],BayesianLearner(),cfg(),registry)

def test_feedback_features_not_trusted(inputs):
    _,registry,pool=inputs;row=actual(pool[0],registry);row['features']={'status_label':1,'residual':0}
    a=BayesianLearner();a.update(pool[0],row,registry)
    assert a.heads['coverage'].X[0]==feature_vector(pool[0]['features']).tolist()

@pytest.mark.parametrize('status',['timeout_unknown','invalid_syntax'])
def test_unknown_invalid_not_false_training(inputs,status):
    _,registry,pool=inputs;row=actual(pool[0],registry);row.update(status=status,condition_satisfied=None)
    learner=BayesianLearner();assert learner.update(pool[0],row,registry)=={}
    assert learner.observed==[pool[0]['item_id']]
    assert all(not h.y for h in learner.heads.values())

def test_inapplicable_not_success_and_zero_output_no_value(inputs):
    _,registry,pool=inputs;row=actual(pool[0],registry)
    row.update(status='condition_not_satisfied',condition_satisfied=False)
    assert feedback_targets(row)=={'coverage':0.}
    assert realized_utility(pool[0],row,cfg())==0
    row.update(status='verified_condition',condition_satisfied=True,nontrivial_output=False,numeric_replay=None)
    assert feedback_targets(row)['nontrivial']==0
    assert realized_utility(pool[0],row,cfg())==0

def test_posterior_checkpoint_matrix_tamper_rejected(inputs):
    _,registry,pool=inputs;a=BayesianLearner();a.update(pool[0],actual(pool[0],registry),registry)
    state=a.state();state['heads']['coverage']['mean'][0]+=1
    with pytest.raises(CandidateError):BayesianLearner.restore(state)

def test_real_resume_same_choices_and_posteriors(inputs,tmp_path):
    data,_,_=inputs;c=cfg();full=run_pilot('.',data,tmp_path/'full',c)
    partial=run_pilot('.',data,tmp_path/'resume',c,stop_after=4);assert not partial['complete']
    resumed=run_pilot('.',data,tmp_path/'resume',c)
    assert resumed['complete'] and full['selected_sequence_sha256']==resumed['selected_sequence_sha256']
    assert full['posterior_sha256']==resumed['posterior_sha256']
    changed=copy.deepcopy(c);changed['beta']+=.1
    with pytest.raises(CandidateError):run_pilot('.',data,tmp_path/'resume',changed)

def test_timeout_keeps_denominator_and_resume(inputs,tmp_path):
    data,_,_=inputs
    def timeout(candidate,model,**kw):
        row=evaluate_candidate(candidate,model,wall_budget_s=0)
        assert row['status']=='timeout_unknown';return row
    first=run_pilot('.',data,tmp_path,cfg(),stop_after=2,evaluate_fn=timeout)
    second=run_pilot('.',data,tmp_path,cfg(),evaluate_fn=timeout)
    assert first['unknown_count']==2 and second['unknown_count']==7
    assert second['all_evaluated_denominator']==7 and sum(second['trained_head_counts'].values())==0
    assert not second['kernel_checked']

def test_actual_numeric_counterexample_is_measured(inputs):
    _,registry,pool=inputs
    found=next((row for item in pool if (row:=actual(item,registry))['status']=='counterexample_found'),None)
    assert found is not None and found['numeric_replay']['matches_exact_instantaneous_difference']
    assert all(s['success'] and s['evaluations']>0 for s in found['numeric_replay']['solves'])
