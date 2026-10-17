import copy,json
import pytest
from naheng.discovery.grammar import CandidateError,canonical_sha
from naheng.discovery.dataset import build_dataset,candidate_templates,instantiate
from naheng.discovery.counterexamples import evaluate_candidate
from naheng.discovery.providers import refine_conditions,emit_theorem,external_provider
from naheng.discovery.proof_worker import register_checked

def test_actual_counterexample_refines_parameter_conditions_only():
    model=next(m for m in build_dataset()['roles']['train'] if len(m['groups'])==3 and len(set(m['parameters']['c']))>1)
    candidate=instantiate(candidate_templates()[0],model)
    row=evaluate_candidate(candidate,model,numeric_replay=True)
    assert row['status']=='counterexample_found' and row['numeric_replay']['matches_exact_instantaneous_difference']
    refined=refine_conditions(candidate,row)
    assert refined['added_parameter_relations'] and refined['nonempty_domain_witness']
    assert refined['candidate']['groups']==candidate['groups'] and refined['candidate']['domain']==candidate['domain']
    assert all(r['kind']=='within_group_equal' for r in refined['added_parameter_relations'])
    # The same heterogeneous model becomes inapplicable, not an artificially verified success.
    after=evaluate_candidate(refined['candidate'],model)
    assert after['status']=='condition_not_satisfied' and not after['kernel_checked']

def test_analytic_pass_unknown_failed_cannot_register():
    for status in ['verified_condition','timeout_unknown','proof_failed']:
        with pytest.raises(CandidateError):register_checked([],{'status':status,'kernel_checked':False})

def test_provider_does_not_accept_user_code_or_conclusion_premise():
    model=build_dataset()['roles']['train'][0];c=instantiate(candidate_templates()[0],model)
    with pytest.raises(CandidateError):emit_theorem(c,'x\naxiom False : False')
    malicious=copy.deepcopy(c);malicious['parameter_relations']=[{'kind':'within_group_equal','expression':{'op':'param','value':'output'}}]
    with pytest.raises(CandidateError):emit_theorem(malicious,'Attempt_000')
    assert external_provider({'enabled':False})['actual_calls']==0
    with pytest.raises(CandidateError):external_provider({'enabled':True})

def test_unique_targets_not_true_and_no_desired_equality_assumption():
    model=build_dataset()['roles']['train'][0];c=instantiate(candidate_templates()[3],model)
    source=emit_theorem(c,'Attempt_001')
    assert 'ClassRHSTrappingSufficient' in source and 'True' not in source
    before=source.split(' :\n  ClassRHSTrappingSufficient')[0]
    assert 'ClassRHSTrappingSufficient' not in before
    assert 'PhysicalOccupation' not in before  # full cube lives in genuine Class predicate
