"""Actual saved Lean proof import and posterior rate-constraint integration.

No compiler result is mocked or generated here; the explicit active project
manifest must exist and pass all original artifact/statement checks.
"""

# --- published-formal-evidence guard (see docs/adr/0027) ---------------------
# These tests verify that runtime behaviour is bound to *published* formal
# evidence: active pointers, the compiled objects they name, and the runtime
# refresh. That evidence is a build product and is not redistributed, so a fresh
# clone cannot verify a binding that has not been built yet. Skipping is visible
# and reasoned; present-but-inconsistent evidence still fails the assertion.
import pytest as _pytest_publication_guard
from naheng.formal.publication_availability import (  # noqa: E402
    SKIP_REASON as _PUBLICATION_SKIP_REASON,
    publication_evidence_available as _publication_evidence_available)

pytestmark = _pytest_publication_guard.mark.skipif(
    not _publication_evidence_available(), reason=_PUBLICATION_SKIP_REASON)
# ---------------------------------------------------------------------------

from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction
import json
from pathlib import Path
import pytest

from naheng.domain.contracts import Action, Observation
from naheng.estimation.particle_filter import ParticleFilter
from naheng.formal.active_evidence import select_reduction_residual
from naheng.formal.reduction_binding import (exact_rate_margin, load_reduction_binding,
    revalidate_reduction_binding, evaluate_posterior_rate, PosteriorRateEvaluation, ReductionBinding)
from naheng.models.site_model import SiteModel
from naheng.packages.registry import ModelRegistry
from naheng.risk.admission import check
from naheng.runtime.freezing import freeze_source

ROOT = Path(__file__).resolve().parents[2]

def actual_case(tmp_path):
    model=SiteModel(); pf=ParticleFilter('actual-rate-test',model,seed=29,particles=8)
    sensed=model.observe(model.initial_state(),0)
    snapshot=pf.update(Observation(run_id=pf.run_id,timestamp_s=0,current_A=0,
        voltage_V=sensed['voltage_V'],temperature_K=sensed['temperature_K']),duration_s=0)
    payload=json.loads((ROOT/'model_packages/research_base/package.json').read_text(encoding='utf-8'))
    payload.update(parameters=asdict(model.params),parameter_revision=pf.parameter_revision)
    registry=ModelRegistry(ROOT); item=registry.register(payload); package=registry.packages[item['package_id']]
    source,_=freeze_source(ROOT,tmp_path/'run')
    manifest,_=select_reduction_residual(ROOT)
    assert manifest is not None, 'Actual residual publication/activation is required, not skipped'
    binding=load_reduction_binding(ROOT,source,package,model,manifest)
    assert binding.record['status']=='PASS', binding.record['reason']
    action=Action(action_id='posterior-rate-action',snapshot_id=snapshot.snapshot_id,start_s=0,duration_s=10,current_A=.1)
    return model,snapshot,package,source,manifest,binding,action

def test_exact_nominal_false_pass_is_rejected_when_the_derived_budget_is_retained():
    row=exact_rate_margin([1,1],[1,2],[1,2],[0,0],[1,1],5,-5)
    assert (row['detailed_rate_mol_per_s'],row['nominal_rate_mol_per_s'],row['budget_mol_per_s'])==('-3','-7','4')
    assert row['nominal_only_pass'] and not row['retaining_budget_pass'] and not row['detailed_point_pass']

def test_real_audited_identity_and_permitted_posterior_can_gate_a_point_constraint(tmp_path):
    model,snapshot,package,source,manifest,binding,action=actual_case(tmp_path)
    result=evaluate_posterior_rate(snapshot,action,model,binding,.001)
    assert result.record['status']=='PASS' and len(result.record['samples'])==8
    assert len(result.record['evidence_refs'])==3
    assert all(abs(Fraction(r['residual_mol_per_s']))<=Fraction(r['budget_mol_per_s']) for r in result.record['samples'])
    empirical=check(snapshot,action,package,rate_evaluation=result)
    assert empirical['decision']=='accept' and empirical['model_selected']=='detailed'
    assert check(snapshot,action,package,rate_evaluation=result,mode='strict')['decision']=='unknown'
    assert not binding.record['grants_future_reduction'] and not binding.record['grants_strict_safety']
    rejected=evaluate_posterior_rate(snapshot,action,model,binding,-.001)
    assert rejected.record['status']=='FAIL'
    assert check(snapshot,action,package,rate_evaluation=rejected)['decision']=='reject'

def test_missing_proof_cannot_silently_drop_a_requested_rate_constraint(tmp_path):
    model,snapshot,package,source,_,_,action=actual_case(tmp_path)
    missing=load_reduction_binding(ROOT,source,package,model)
    evaluated=evaluate_posterior_rate(snapshot,action,model,missing,.001)
    assert missing.record['status']=='UNKNOWN'
    assert check(snapshot,action,package,rate_evaluation=evaluated)['decision']=='unknown'

def test_changed_frozen_source_and_parameters_withdraw_binding(tmp_path):
    model,snapshot,package,source,_,binding,action=actual_case(tmp_path)
    changed=SiteModel(replace(model.params,side_rate_s_inv=(1e-6,1e-6)))
    assert evaluate_posterior_rate(snapshot,action,changed,binding,.001).record['status']=='UNKNOWN'
    target=source/'formal/Naheng/Reduction/Residual.lean'
    target.write_text(target.read_text(encoding='utf-8')+'\n-- changed frozen source\n',encoding='utf-8')
    stale=revalidate_reduction_binding(ROOT,source,binding,package,model)
    assert stale.record['status']!='PASS' and stale.record['evidence_refs']==[]

def test_posterior_revision_mismatch_and_client_dictionary_do_not_authorize_rate_limit(tmp_path):
    model,snapshot,package,source,_,binding,action=actual_case(tmp_path)
    altered=snapshot.model_copy(update={'parameter_revision':'wrong-parameters'})
    assert evaluate_posterior_rate(altered,action,model,binding,.001).record['status']=='UNKNOWN'
    valid=evaluate_posterior_rate(snapshot,action,model,binding,.001)
    with pytest.raises(ValueError,match='Typed'):check(snapshot,action,package,rate_evaluation=valid.record)
    with pytest.raises(ValueError,match='identity'):evaluate_posterior_rate(snapshot,action.model_copy(update={'snapshot_id':'other'}),model,binding,.001)


@pytest.mark.parametrize('field,value', [('current_A', -.7), ('duration_s', 20), ('thermal_W', 2)])
def test_same_action_id_cannot_reuse_a_different_action_evaluation(tmp_path, field, value):
    model,snapshot,package,_,_,binding,action=actual_case(tmp_path)
    result=evaluate_posterior_rate(snapshot,action,model,binding,.001)
    changed=action.model_copy(update={field:value})
    assert changed.action_id == action.action_id
    with pytest.raises(ValueError,match='input identity'):
        check(snapshot,changed,package,rate_evaluation=result)


@pytest.mark.parametrize('field', ['samples', 'weights', 'state_units'])
def test_same_snapshot_id_cannot_reuse_changed_posterior_contents(tmp_path, field):
    model,snapshot,package,_,_,binding,action=actual_case(tmp_path)
    result=evaluate_posterior_rate(snapshot,action,model,binding,.001)
    changed=snapshot.model_copy(deep=True)
    if field == 'samples': changed.samples[0][0] += .01
    elif field == 'weights': changed.weights[0] += .01
    else: changed.state_units[0] = 'other-unit'
    assert changed.snapshot_id == snapshot.snapshot_id
    with pytest.raises(ValueError,match='input identity'):
        check(changed,action,package,rate_evaluation=result)


def test_nested_records_are_detached_and_corruption_is_rejected(tmp_path):
    model,snapshot,package,_,_,binding,action=actual_case(tmp_path)
    result=evaluate_posterior_rate(snapshot,action,model,binding,.001)
    detached=result.record
    detached['samples'][0]['budget_mol_per_s']='0'
    detached['status']='FAIL'
    detached_binding=binding.record
    detached_binding['identity']['parameter_hash']='bad'
    detached_binding['evidence_refs'].clear()
    assert result.record['status']=='PASS' and len(binding.record['evidence_refs'])==3
    assert check(snapshot,action,package,rate_evaluation=result)['decision']=='accept'
    with pytest.raises(ValueError,match='record integrity'):
        check(snapshot,action,package,rate_evaluation=PosteriorRateEvaluation(detached,binding))
    with pytest.raises(ValueError,match='binding integrity'):
        check(snapshot,action,package,rate_evaluation=PosteriorRateEvaluation(result.record,ReductionBinding(detached_binding)))

@pytest.mark.parametrize('occupancy', ['-1/10','11/10'])
def test_outside_formal_occupation_domain_cannot_claim_a_budget(occupancy):
    with pytest.raises(ValueError):exact_rate_margin([1],[1],[2],[0],[occupancy],3,0)

def test_recovery_preserves_actual_parent_rate_record_and_marks_new_display_identity():
    from naheng.runtime.recovery import rekey_history
    row={'snapshot_id':'parent-s','run_id':'parent','obs_until_s':0,'samples':[[.6]],'weights':[1.],
         'parameter_revision':'r'}
    rate={'snapshot_id':'parent-s','action_id':'parent-a','record_sha256':'a'*64,'samples':[{'budget_mol_per_s':'1/10'}]}
    bundle={'run_id':'parent','step':1,'sensor':[],'posterior':[row],
            'actions':[{'action_id':'parent-a','snapshot_id':'parent-s'}],
            'cashflows':[{'action_id':'parent-a','snapshot_id':'parent-s','execution_id':'parent-a'}],
            'decisions':[{'action_id':'parent-a','snapshot_id':'parent-s','rate_diagnostics':deepcopy(rate)}]}
    result=rekey_history(bundle,'child'); decision=result['decisions'][0]
    assert decision['rate_diagnostics']==rate
    assert decision['rate_diagnostics_lineage']['source_action_id']=='parent-a'
    assert decision['rate_diagnostics_lineage']['current_action_id']==decision['action_id']!='parent-a'
    assert decision['rate_diagnostics_lineage']['independent_sample'] is False
