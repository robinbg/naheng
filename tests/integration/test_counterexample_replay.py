from copy import deepcopy
import pytest
from naheng.discovery.grammar import CandidateError,canonical_sha
from naheng.discovery.counterexamples import evaluate_candidate,replay_counterexample
from naheng.discovery.dataset import build_dataset,candidate_templates,instantiate,validate_roles,freeze_dataset,search_feedback,training_feedback_rows,freeze_selection,evaluate_holdout,load_profile

def test_multiple_positive_and_negative_models_have_exact_and_numeric_feedback():
    data=build_dataset();template=candidate_templates()[0];rows=[]
    for model in data['roles']['train']:
        row=evaluate_candidate(instantiate(template,model),model)
        rows.append(row)
        assert row['kernel_checked'] is False
        if row['status']=='counterexample_found':
            assert row['witness']['physical_cube'] and row['numeric_replay']['matches_exact_instantaneous_difference']
            assert all(s['success'] and s['elapsed_s']==.05 for s in row['numeric_replay']['solves'])
    assert sum(r['status']=='verified_condition' for r in rows)>=6
    assert sum(r['status']=='counterexample_found' for r in rows)>=12
    assert len({tuple(r['witness']['x']) for r in rows if r['witness']})>=5
    assert {r['features']['n_sites'] for r in rows}=={2,3,4}

def test_illegal_counterexample_nonapplicability_and_timeout_are_not_false_labels():
    data=build_dataset();models=data['roles']['train'];templates=candidate_templates()
    model=models[0];raw=instantiate(templates[0],model)
    bad=deepcopy(raw);bad['target']['kind']='arbitrary_python'
    assert evaluate_candidate(bad,model)['status']=='invalid_syntax'
    assert evaluate_candidate(raw,model,wall_budget_s=0)['status']=='timeout_unknown'
    differing=next(m for m in models if evaluate_candidate(instantiate(templates[0],m),m,numeric_replay=False)['status']=='counterexample_found')
    constrained=evaluate_candidate(instantiate(templates[3],differing),differing)
    assert constrained['status']=='condition_not_satisfied' and constrained['witness'] is None
    assert constrained['kernel_checked'] is False

def test_tampered_replay_witness_is_rejected_by_actual_equations():
    data=build_dataset();template=candidate_templates()[0]
    model=next(m for m in data['roles']['train'] if evaluate_candidate(instantiate(template,m),m,numeric_replay=False)['status']=='counterexample_found')
    raw=instantiate(template,model);row=evaluate_candidate(raw,model)
    bad=deepcopy(row['witness']);bad['difference']='0'
    with pytest.raises(CandidateError,match='claimed difference'):replay_counterexample(raw,model,bad)
    bad=deepcopy(row['witness']);bad['x'][0]='2'
    with pytest.raises(CandidateError,match='physical domain'):replay_counterexample(raw,model,bad)

def test_dataset_generation_and_first_freeze_roles_reproduce(tmp_path):
    data=build_dataset();same=build_dataset();different=build_dataset(seed=20261015)
    assert canonical_sha(data)==canonical_sha(same)!=canonical_sha(different)
    assert validate_roles(data)
    frozen=freeze_dataset(tmp_path/'frozen',data)
    assert frozen==freeze_dataset(tmp_path/'frozen',same)
    with pytest.raises(CandidateError,match='immutable'):freeze_dataset(tmp_path/'frozen',different)
    assert frozen['role_model_counts']=={'train':24,'validation':16,'test':16}
    families=[set(m['structural_family_id'] for m in data['roles'][role]) for role in ('train','validation','test')]
    assert not families[0]&families[1] and not families[0]&families[2] and not families[1]&families[2]

def test_heldout_and_forged_family_roles_never_enter_training_or_acquisition():
    data=build_dataset();templates=candidate_templates()
    with pytest.raises(CandidateError,match='Heldout'):search_feedback(templates,data['roles']['test'])
    with pytest.raises(CandidateError,match='Heldout'):search_feedback(templates,data['roles']['validation'])
    forged=deepcopy(data['roles']['test'][0]);forged['role']='train';forged['structural_family_id']=data['roles']['train'][0]['structural_family_id']
    with pytest.raises(CandidateError,match='Heldout'):search_feedback(templates,[forged])
    rows=search_feedback(templates,data['roles']['train'][:2]);selection=freeze_selection(templates,rows)
    heldout=evaluate_holdout(selection,templates,data['roles']['test'][:1],'test')
    with pytest.raises(CandidateError,match='Heldout feedback'):training_feedback_rows(rows+heldout)
    assert all(row['role']=='train' for row in training_feedback_rows(rows))
    assert all(not row['used_for_search'] for row in heldout)

def test_heldout_requires_preexisting_frozen_template_identity():
    data=build_dataset();templates=candidate_templates()
    with pytest.raises(CandidateError,match='frozen'):evaluate_holdout({},templates,data['roles']['test'][:1],'test')
    rows=search_feedback(templates,data['roles']['train'][:1]);selection=freeze_selection(templates,rows)
    modified=deepcopy(templates);modified.pop()
    with pytest.raises(CandidateError,match='frozen'):evaluate_holdout(selection,modified,data['roles']['test'][:1],'test')
    with pytest.raises(CandidateError,match='Nonempty'):freeze_selection(templates,[])

def test_profile_is_actually_loaded_and_role_edits_rejected(tmp_path):
    import json
    from pathlib import Path
    profile=load_profile(Path(__file__).parents[2]/'configs/discovery/pilot-v1.json')
    assert profile['seed']==20261014 and profile['test_allowed_for_search_or_training'] is False
    profile['test_n_sites']=[2,3]
    path=tmp_path/'bad-profile.json';path.write_text(json.dumps(profile))
    with pytest.raises(CandidateError,match='freeze mismatch'):load_profile(path)

def test_malformed_model_is_invalid_rather_than_false_candidate():
    data=build_dataset();model=deepcopy(data['roles']['train'][0]);raw=instantiate(candidate_templates()[0],model)
    model['groups']=None
    result=evaluate_candidate(raw,model)
    assert result['status']=='invalid_syntax' and result['kernel_checked'] is False

def test_exact_derived_witness_is_not_rejected_by_raw_literal_denominator_bound():
    from naheng.discovery.counterexamples import derived_rational
    from naheng.discovery.grammar import rational
    with pytest.raises(CandidateError):rational('1/2040000')
    assert str(derived_rational('1/2040000'))=='1/2040000'
    data=build_dataset();template=candidate_templates()[0]
    rows=[evaluate_candidate(instantiate(template,m),m) for m in data['roles']['validation']]
    assert all(r['status'] in ('counterexample_found','verified_condition') for r in rows)
    assert all(r['numeric_replay']['matches_exact_instantaneous_difference'] for r in rows if r['numeric_replay'])

def test_training_features_use_actual_model_coefficients_and_zero_output_is_marked():
    data=build_dataset();template=candidate_templates()[0];model=deepcopy(data['roles']['train'][0])
    real=evaluate_candidate(instantiate(template,model),model)
    assert real['nontrivial_output'] is True and real['features']['model_total_capacity_mol']>0
    for name in ['a','b','c']:model['parameters'][name]=['0']*len(model['groups'])
    zero=evaluate_candidate(instantiate(template,model),model)
    assert zero['status']=='verified_condition' and zero['nontrivial_output'] is False
    assert zero['kernel_checked'] is False
