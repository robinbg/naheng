"""Actual runner integration; missing-proof runs remain explicitly empirical."""

# --- published-formal-evidence guard (see docs/adr/0027) ---------------------
import pytest as _pytest_publication_guard
from naheng.formal.publication_availability import (  # noqa: E402
    SKIP_REASON as _PUBLICATION_SKIP_REASON,
    publication_evidence_available as _publication_evidence_available)

pytestmark = _pytest_publication_guard.mark.skipif(
    not _publication_evidence_available(), reason=_PUBLICATION_SKIP_REASON)
# ---------------------------------------------------------------------------

from dataclasses import replace
import json
from pathlib import Path
import pytest
import yaml
from naheng.runtime.artifacts import code_hash
from naheng.runtime.jobs import JobStore
from naheng.runtime.runner import execute
from naheng.models.site_model import SiteModel

ROOT=Path(__file__).resolve().parents[2]


def config():
    value=yaml.safe_load((ROOT/'configs/scenarios/acceptance_loop.yaml').read_text(encoding='utf-8'))
    value.update(duration_s=10,step_s=10,filter_particles=16,forecast_paths=2,forecast_horizon_s=10,
                 code_hash=code_hash(ROOT))
    return value


def test_missing_proof_has_real_empirical_result_and_inventory_artifact(tmp_path,monkeypatch):
    monkeypatch.setattr('naheng.formal.active_evidence.select_foundation',lambda project:(None,'No proof in this acceptance case'))
    store=JobStore(tmp_path/'runs'); run_id=store.create(config())['run_id']
    execute(ROOT,store,run_id)
    assert store.get(run_id)['state']=='succeeded'
    dest=store.root/run_id
    binding=json.loads((dest/'chemical_binding.json').read_text(encoding='utf-8'))
    assert binding['status']=='UNKNOWN' and binding['withdrawn'] and binding['evidence_refs']==[]
    decisions=json.loads((dest/'decisions.json').read_text(encoding='utf-8'))
    assert decisions[0]['interval_inventory_check']['status']=='PASS'
    assert decisions[0]['evidence_refs']==[]
    assert json.loads((dest/'manifest.json').read_text(encoding='utf-8'))['artifact_index']['chemical_binding']=='chemical_binding.json'
    report=(dest/'report.html').read_text(encoding='utf-8')
    assert '化学收支与证据适用性' in report and 'UNKNOWN' in report


def test_integrator_inventory_error_prevents_complete_publication(tmp_path,monkeypatch):
    monkeypatch.setattr('naheng.formal.active_evidence.select_foundation',lambda project:(None,'No proof in this failure case'))
    original=SiteModel.integrate
    def drift(self,*args,**kwargs):
        result=original(self,*args,**kwargs)
        final=result.state.copy(); final[3]+=1e-3
        return replace(result,state=final)
    monkeypatch.setattr(SiteModel,'integrate',drift)
    store=JobStore(tmp_path/'runs');run_id=store.create(config())['run_id']
    with pytest.raises(ValueError,match='sodium inventory'):
        execute(ROOT,store,run_id)
    assert store.get(run_id)['state']=='failed'
    assert not (store.root/run_id/'manifest.json').exists()
    result=json.loads((store.root/run_id/'decisions.json').read_text(encoding='utf-8'))
    assert result[0]['interval_inventory_check']['status']=='FAIL'


def test_requested_rate_limit_rejection_is_saved_without_execution_or_complete_result(tmp_path):
    value=config();value['stored_sodium_rate_upper_mol_per_s']=-.001
    store=JobStore(tmp_path/'runs');run_id=store.create(value)['run_id']
    with pytest.raises(ValueError,match='No admitted'):
        execute(ROOT,store,run_id)
    dest=store.root/run_id
    assert store.get(run_id)['state']=='failed' and not (dest/'manifest.json').exists()
    decision=json.loads((dest/'decisions.json').read_text(encoding='utf-8'))[0]
    assert decision['decision']=='reject' and decision['rate_diagnostics']['status']=='FAIL'
    assert len(decision['rate_diagnostics']['samples'])==16
    audit=json.loads((dest/'unexecuted_cashflows.json').read_text(encoding='utf-8'))
    assert audit['complete'] is False and audit['summary']['unexecuted_proposals']==1
    assert audit['summary']['executions']==0 and audit['summary']['energy_J']==0
