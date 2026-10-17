"""Pure-rational feedback adoption controls, not new solver or science runs."""
from copy import deepcopy
import pytest
from naheng.discovery.grammar import CandidateError,canonical_sha
from naheng.discovery.counterexamples import evaluate_candidate
from naheng.discovery.dataset import build_dataset,candidate_templates,instantiate,training_feedback_rows

def feedback_row(role):
    model=build_dataset()['roles'][role][0]
    template=candidate_templates()[0]
    row=evaluate_candidate(instantiate(template,model),model,numeric_replay=False)
    row.update(template_id=template['template_id'],model_sha256=canonical_sha(model),
        used_for_search=role=='train')
    return row

def test_actual_train_feedback_adoption_is_nonempty():
    row=feedback_row('train')
    accepted=training_feedback_rows([row])
    assert len(accepted)==1 and accepted[0]['role']=='train'
    assert accepted[0]['kernel_checked'] is False

def test_honest_heldout_feedback_is_not_training():
    with pytest.raises(CandidateError):training_feedback_rows([feedback_row('test')])

def test_test_feedback_cannot_be_relabelled_as_search_training():
    row=feedback_row('test');row['role']='train';row['used_for_search']=True
    with pytest.raises(CandidateError):training_feedback_rows([row])

def test_known_test_model_hash_cannot_be_hidden_by_forged_family_and_features():
    row=feedback_row('test');train=feedback_row('train')
    row['role']='train';row['used_for_search']=True
    row['structural_family_id']=train['structural_family_id']
    row['features']=deepcopy(train['features'])
    # model_sha256 and any actual model context still bind the heldout source.
    with pytest.raises(CandidateError):training_feedback_rows([row])
