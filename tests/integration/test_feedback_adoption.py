"""Frozen-source adoption tests use pure rational checks, not new ODE runs."""
from copy import deepcopy
import pytest
from naheng.discovery.grammar import CandidateError,canonical_sha
from naheng.discovery.counterexamples import evaluate_candidate
from naheng.discovery.dataset import build_dataset,candidate_templates,instantiate,training_feedback_rows,freeze_selection

def row(role='train',index=0,template_index=0,dataset=None):
    data=build_dataset() if dataset is None else dataset
    model=data['roles'][role][index];template=candidate_templates()[template_index]
    result=evaluate_candidate(instantiate(template,model),model,numeric_replay=False)
    result.update(template_id=template['template_id'],model_sha256=canonical_sha(model),used_for_search=role=='train')
    return result

def test_actual_frozen_training_is_adopted_and_no_oracle_field_enters_features():
    actual=row();adopted=training_feedback_rows([actual])[0]
    assert adopted['model_id']==actual['model_id'] and adopted['features']==actual['features']
    assert adopted['features'] is not actual['features']
    assert not set(adopted['features'])&{'status','condition_satisfied','model_id','witness','wall_s'}
    assert adopted['candidate_sha256']==actual['candidate_id'].removeprefix('candidate-')

@pytest.mark.parametrize('role',['validation','test'])
def test_heldout_flags_and_family_cannot_replace_actual_frozen_model_identity(role):
    forged=row(role);train=row();forged.update(role='train',used_for_search=True,
        structural_family_id=train['structural_family_id'],features=deepcopy(train['features']))
    with pytest.raises(CandidateError):training_feedback_rows([forged])

@pytest.mark.parametrize('field',['model_id','model_sha256','candidate_id','template_id','structural_family_id'])
def test_swapping_one_actual_identity_cannot_adopt_other_feedback(field):
    actual=row();other=row(index=1,template_index=5)
    actual[field]=other[field] if field!='structural_family_id' else row('test')[field]
    with pytest.raises(CandidateError):training_feedback_rows([actual])

@pytest.mark.parametrize('context',['model_context','candidate_context','template_context'])
def test_attached_context_must_match_the_frozen_structural_source(context):
    actual=row();held=build_dataset()['roles']['test'][0];template=candidate_templates()[0]
    if context=='model_context':actual[context]=held
    elif context=='candidate_context':actual[context]=instantiate(template,held)
    else:
        bad=deepcopy(template);bad['target']={'kind':'trapping_rate'};actual[context]=bad
    with pytest.raises(CandidateError):training_feedback_rows([actual])

def test_actual_context_round_trip_and_parameter_substitution():
    actual=row();model=build_dataset()['roles']['train'][0];template=candidate_templates()[0]
    actual.update(model_context=deepcopy(model),candidate_context=instantiate(template,model),template_context=deepcopy(template))
    assert len(training_feedback_rows([actual]))==1
    actual['model_context']['parameters']['N'][0]='1/100'
    with pytest.raises(CandidateError):training_feedback_rows([actual])

@pytest.mark.parametrize('mutation',['hidden_feature','counterfeit_label','counterfeit_kernel','counterfeit_nontrivial','nonfinite_cost'])
def test_feedback_values_are_checked_against_actual_equations(mutation):
    actual=next(row(index=i) for i in range(24) if row(index=i)['status']=='counterexample_found')
    if mutation=='hidden_feature':actual['features']['oracle_heldout_label']=1
    elif mutation=='counterfeit_label':actual.update(status='verified_condition',witness=None)
    elif mutation=='counterfeit_kernel':actual['kernel_checked']=True
    elif mutation=='counterfeit_nontrivial':actual['nontrivial_output']=False
    else:actual['wall_s']=float('nan')
    with pytest.raises(CandidateError):training_feedback_rows([actual])

@pytest.mark.parametrize('field,value',[('model_id',[]),('template_id',None),('model_sha256','unknown')])
def test_malformed_feedback_identity_rejects_as_candidate_error(field,value):
    actual=row();actual[field]=value
    with pytest.raises(CandidateError):training_feedback_rows([actual])

def test_explicit_other_seed_context_is_content_bound_and_default_does_not_adopt_it():
    data=build_dataset(seed=20261015);actual=row(dataset=data)
    with pytest.raises(CandidateError):training_feedback_rows([actual])
    assert len(training_feedback_rows([actual],dataset=data))==1
    altered=deepcopy(data);altered['roles']['train'][0]['parameters']['N'][0]='1/100'
    with pytest.raises(CandidateError):training_feedback_rows([actual],dataset=altered)
    assert freeze_selection(candidate_templates(),[actual],dataset=data)['frozen']

def test_explicit_valid_new_template_uses_existing_grammar_without_fixed_template_whitelist():
    model=build_dataset()['roles']['train'][0]
    structure={'parameter_relations':[],'target':{'kind':'stored_amount_rate'}}
    template={'template_id':'template-'+canonical_sha(structure),**structure}
    actual=evaluate_candidate(instantiate(template,model),model,numeric_replay=False)
    actual.update(template_id=template['template_id'],model_sha256=canonical_sha(model),used_for_search=True)
    with pytest.raises(CandidateError):training_feedback_rows([actual])
    assert len(training_feedback_rows([actual],templates=[template]))==1
    altered=deepcopy(template);altered['target']={'kind':'trapping_rate'}
    with pytest.raises(CandidateError):training_feedback_rows([actual],templates=[altered])

def test_actual_timeout_stays_unknown_instead_of_becoming_false_or_verified():
    model=build_dataset()['roles']['train'][0];template=candidate_templates()[0]
    actual=evaluate_candidate(instantiate(template,model),model,wall_budget_s=0,numeric_replay=False)
    actual.update(template_id=template['template_id'],model_sha256=canonical_sha(model),used_for_search=True)
    adopted=training_feedback_rows([actual])[0]
    assert adopted['status']=='timeout_unknown' and adopted['condition_satisfied'] is None and not adopted['kernel_checked']

