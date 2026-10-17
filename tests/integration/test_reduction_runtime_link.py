"""Original P02 integration gate candidate. Public adoption has not run it yet.

The known endpoint case deliberately uses the production capacity protocol;
the handoff's 2-second protocol calibration is not a substitute for this test.
"""

# --- published-formal-evidence guard (see docs/adr/0027) ---------------------
import pytest as _pytest_publication_guard
from naheng.formal.publication_availability import (  # noqa: E402
    SKIP_REASON as _PUBLICATION_SKIP_REASON,
    publication_evidence_available as _publication_evidence_available)

pytestmark = _pytest_publication_guard.mark.skipif(
    not _publication_evidence_available(), reason=_PUBLICATION_SKIP_REASON)
# ---------------------------------------------------------------------------

from dataclasses import asdict, replace
import json
from pathlib import Path
import numpy as np
import pytest

from naheng.domain.contracts import PosteriorSnapshot, ForecastQuery
from naheng.models.site_model import SiteModel, SiteParameters
from naheng.packages.registry import ModelRegistry
from naheng.packages.transition import ForecastExecution,make_theory_selection,lift_grouped_posterior
from naheng.lifecycle.forecast import forecast

ROOT=Path(__file__).resolve().parents[2]

def inputs(homogeneous=True,known_endpoint=False):
    model=SiteModel(SiteParameters(site_capacity_mol=(1/64,1/128),rate_s_inv=(.001,.001),
        equilibrium_drive_V=(0.,0.),side_rate_s_inv=(2e-7,2e-7),source_id='synthetic-p02-public-gate-v1')) if homogeneous else SiteModel()
    raw=json.loads((ROOT/'model_packages/research_base/package.json').read_text(encoding='utf-8'))
    raw.update(package_id='p02-gate-homogeneous' if homogeneous else 'p02-gate-heterogeneous',
               parameter_revision='p02-gate-v1',parameters=asdict(model.params))
    registry=ModelRegistry(ROOT);registry.register(raw);package=registry.packages[raw['package_id']]
    rows=[[.5,.25,0.,.025,298.15,1.,1.],[.375,.5,0.,.025,298.15,1.2,.5]]
    names=list(model.state_names)+['rate_scale','side_rate_scale']
    posterior=PosteriorSnapshot(snapshot_id='p02-original-gate-'+str(homogeneous),run_id='p02-synthetic-gate',
        model_package_id=package['package_id'],parameter_revision=package['parameter_revision'],obs_until_s=0.,
        state_names=names,state_units=list(model.state_units)+['1','1'],samples=rows,weights=[.5,.5],
        mean=dict(zip(names,np.mean(rows,axis=0))),quantiles={},ess=2.,identifiability=['correlated set required'])
    query=ForecastQuery(snapshot_id=posterior.snapshot_id,future_policy_id='fixed-current-v1',
        environment_id='constant-ambient-v1',horizon_s=120. if known_endpoint else 2.,sample_budget=2 if known_endpoint else 1,
        endpoint_protocol='synthetic_capacity_v1' if known_endpoint else 'unidentified-endpoint',current_A=.1,ambient_K=298.15)
    return model,package,posterior,query

def test_nontrivial_chemical_result_drives_real_conditional_lifecycle_and_protocol():
    model,package,posterior,query=inputs(known_endpoint=True)
    selected=make_theory_selection(ROOT)
    assert selected['initial_status']=='PASS','Actual selected full core/source/object evidence is required; do not mock checked IDs'
    execution=ForecastExecution(model,posterior,package,selected,proof_root=ROOT)
    result=forecast(posterior,query,model,wall_budget_s=110.,execution_context=execution)
    assert result['budget']['completed_paths']==query.sample_budget
    for path in result['paths']:
        assert path['theory_execution']['route']=='checked_grouped'
        assert path['executed_state_dimension']==4
        assert len(path['theory_execution']['used_checked_ids'])==2
        assert path['capacity_baseline_protocol'] is not None
        aging=path['capacity_baseline_protocol']['theory_aging_contract']
        assert aging['used_checked_ids'] and aging['capacity_order']=='UNKNOWN'
        assert path['theory_output_contract']['used_checked_ids']==path['theory_execution']['used_checked_ids']
        assert path['theory_output_contract']['voltage_error_bound_V'] is None
        assert path['final_state_representation']['unique_detailed_vector'] is None
    assert result['rul']['monotonic_capacity_status']=='unknown'
    assert result['rul']['first_passage_error_bound_status']=='unknown'
    assert result['risk']['risk_certificate'] is False
    assert result['theory_runtime']['strict_admission']=='UNKNOWN'

@pytest.mark.parametrize('homogeneous,selected',[(False,True),(True,False)])
def test_default_heterogeneous_or_missing_proof_keeps_actual_detailed_fallback(homogeneous,selected):
    model,package,posterior,query=inputs(homogeneous)
    execution=ForecastExecution(model,posterior,package,make_theory_selection(ROOT) if selected else None,proof_root=ROOT)
    result=forecast(posterior,query,model,wall_budget_s=110.,execution_context=execution)
    path=result['paths'][0]
    assert path['status']=='computed' and path['executed_state_dimension']==5
    assert path['theory_execution']['route']=='detailed_fallback'
    assert path['theory_execution']['used_checked_ids']==[]

def test_actual_parameter_hash_change_cannot_inherit_a_registered_receipt():
    model,package,posterior,query=inputs()
    changed=SiteModel(replace(model.params,rate_s_inv=(.002,.002)))
    with pytest.raises(ValueError,match='parameter hash'):
        ForecastExecution(changed,posterior,package,make_theory_selection(ROOT),proof_root=ROOT)

def test_low_high_transition_returns_correlated_weighted_sets_without_hidden_truth():
    model,package,posterior,query=inputs()
    execution=ForecastExecution(model,posterior,package,make_theory_selection(ROOT),proof_root=ROOT)
    execution.prepare(posterior,query,model)
    lifted=lift_grouped_posterior(execution.projected,model,execution.binding)
    assert lifted['unique_detailed_snapshot'] is None
    assert [part['weight'] for part in lifted['sets']]==posterior.weights
    for part in lifted['sets']:
        assert part['kind']=='correlated_linear_constraint_set'
        assert part['unique_detailed_vector'] is None
        assert part['constraints'][0]['relation']=='sum(N_i*x_i)=q_class'

@pytest.mark.parametrize('name,wrong',[('x1','mol'),('temperature_K','C'),('rate_scale','s^-1')])
def test_units_are_checked_at_actual_lifecycle_transition(name,wrong):
    model,package,posterior,query=inputs()
    damaged=posterior.model_dump(mode='json');damaged['state_units'][damaged['state_names'].index(name)]=wrong
    bad=PosteriorSnapshot.model_validate(damaged)
    execution=ForecastExecution(model,bad,package,make_theory_selection(ROOT),proof_root=ROOT)
    with pytest.raises(ValueError,match='unit'):
        execution.prepare(bad,query,model)
