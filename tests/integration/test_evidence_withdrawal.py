"""P03 private gate: real state decisions, no fake scientific/calibration outcome."""

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

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
from naheng.packages.validity_monitor import Bounds,Envelope,Residual,MonitorInput,ValidityMonitor,offline_research_request,identity
from naheng.runtime.revalidation import Assessment,Candidate,revalidate_and_select,record_actual_service,observe_p02_binding,envelope_from_p02_projection,persist_validity_event


def initial(**kwargs):
    e=Envelope((('x1','1',Bounds(.4,.6)),('x2','1',Bounds(.3,.7)),('temperature_K','K',Bounds(297.,299.))),
               (('rate_scale','1',Bounds(.8,1.2)),),('original-correlated-set-sha',))
    return replace(MonitorInput('frozen-job',0.,'1'*64,'2'*64,'PASS','PASS',('old-proof',),e),**kwargs)


def incident():
    start=initial();monitor=ValidityMonitor(start,allowed_candidates=tuple((name,'4'*64) for name in ('upgrade','backup','candidate','actual-domain-backup')))
    return monitor.observe(replace(start,time_s=1.,residuals=(Residual('voltage','V',3.5,3.0,.025),)))


def test_normal_then_sensor_bias_expands_both_sets_and_revokes():
    start=initial();monitor=ValidityMonitor(start);normal=monitor.observe(start)
    assert normal.status=='CURRENT' and normal.current_actions_permitted
    bad=monitor.observe(replace(start,time_s=1.,residuals=(Residual('voltage','V',3.5,3.0,.025),)))
    assert bad.status=='WITHDRAWN' and bad.revoked_ids==('old-proof',) and not bad.current_actions_permitted
    assert bad.envelope.encloses(start.envelope)
    assert all(new.lower<old.lower and new.upper>old.upper for (_,_,new),(_,_,old) in zip(bad.envelope.states,start.envelope.states))
    assert bad.envelope.parameters[0][2].lower<start.envelope.parameters[0][2].lower
    assert start.envelope.states[0][2]==Bounds(.4,.6)


def test_persistent_side_reaction_diagnostic_and_recovery_do_not_restore_old_proof():
    start=initial();monitor=ValidityMonitor(start)
    a=monitor.observe(replace(start,time_s=1.,residuals=(Residual('side_reaction_diagnostic','A',.4,.1,.01),)))
    b=monitor.observe(replace(start,time_s=2.,residuals=(Residual('side_reaction_diagnostic','A',.4,.1,.01),)))
    c=monitor.observe(replace(start,time_s=3.))
    assert 'persistent_residual:side_reaction_diagnostic' in b.reasons
    assert c.status=='WITHDRAWN' and c.envelope.encloses(b.envelope) and b.envelope.encloses(a.envelope)
    assert c.record()['new_theory_auto_adopted'] is False


@pytest.mark.parametrize('field,value,reason',[('parameter_sha256','3'*64,'parameter_identity_changed'),('source_sha256','3'*64,'source_identity_changed'),('domain_status','FAIL','domain_fail'),('binding_status','UNKNOWN','binding_unknown'),('checked_ids',('other-proof',),'selected_evidence_changed')])
def test_all_identity_and_domain_invalidations_propagate(field,value,reason):
    start=initial();monitor=ValidityMonitor(start)
    decision=monitor.observe(replace(start,time_s=1.,**{field:value}))
    assert reason in decision.reasons and 'old-proof' in decision.revoked_ids and decision.revalidation_required


def test_initial_unknown_does_not_need_fake_pass_to_monitor():
    start=initial(binding_status='UNKNOWN',checked_ids=())
    result=ValidityMonitor(start).observe(start)
    assert result.status=='WITHDRAWN' and not result.current_actions_permitted


def test_wrong_units_and_repeated_timestamp_leave_no_partial_update():
    start=initial();monitor=ValidityMonitor(start);bad=replace(start,envelope=replace(start.envelope,states=(('x1','mol',Bounds(.4,.6)),*start.envelope.states[1:])))
    with pytest.raises(ValueError):monitor.observe(bad)
    assert monitor.observe(start).sequence==1
    with pytest.raises(ValueError):monitor.observe(start)


def assessment(decision,request,model='4'*64,status='accept',proof='PASS',ids=(),whole=True):
    return Assessment(decision.sha256,decision.envelope.sha256,model,status,proof,ids,'actual deterministic test assessment',whole,request.sha256)


def test_upgrade_then_backup_is_deterministic_and_records_failures():
    decision=incident();calls=[]
    def denied(e,d,r):calls.append('upgrade');return assessment(d,r,status='reject')
    def backup(e,d,r):calls.append('backup');return assessment(d,r)
    result=revalidate_and_select(decision,[Candidate('backup','fallback','4'*64,backup),Candidate('upgrade','upgrade','4'*64,denied)],requested_power_W=100.,duration_s=4.)
    assert calls==['upgrade','backup'] and result['selected_candidate']=='backup'
    assert result['delivered_energy_J'] is None and result['unserved_energy_J'] is None
    actual=record_actual_service(result,delivered_energy_J=120.)
    assert actual['requested_energy_J']==400. and actual['unserved_energy_J']==280.
    with pytest.raises(ValueError):record_actual_service(actual,delivered_energy_J=120.)


@pytest.mark.parametrize('case',['unknown','stale','narrow','old-proof','exception'])
def test_bad_or_missing_backup_explicitly_stops_without_hiding_unserved_energy(case):
    decision=incident()
    def assess(e,d,r):
        if case=='exception':raise ArithmeticError('actual solver failed')
        result=assessment(d,r,status='unknown' if case=='unknown' else 'accept',ids=('old-proof',) if case=='old-proof' else (),whole=case!='narrow')
        return replace(result,decision_sha256='0'*64) if case=='stale' else result
    result=revalidate_and_select(decision,[Candidate('candidate','fallback','4'*64,assess)],requested_power_W=90.,duration_s=4.)
    assert result['response']=='stop_automatic_actions' and not result['action_permitted']
    assert result['delivered_energy_J']==0. and result['unserved_energy_J']==360.


def test_no_fallback_is_a_stop_not_zero_loss():
    result=revalidate_and_select(incident(),[],requested_power_W=90.,duration_s=4.)
    assert result['unserved_energy_J']==360. and result['service_status']=='stopped_unserved'


def test_real_existing_domain_admission_sees_expanded_support_not_old_mean():
    from naheng.risk.admission import check
    from naheng.domain.contracts import Action
    d=incident()
    def assess(envelope,decision,request):
        # Existing domain checker checks separable state bounds; both endpoints
        # give the full axis-aligned domain check, not a probability claim.
        names=['x1','x2','trapped_mol','reservoir_mol','temperature_K']
        samples=[]
        bounds={n:b for n,_,b in envelope.states}
        for edge in ('lower','upper'):
            samples.append([getattr(bounds['x1'],edge),getattr(bounds['x2'],edge),0.,.025,getattr(bounds['temperature_K'],edge)])
        snap=SimpleNamespace(snapshot_id='expanded-support',state_names=names,samples=samples)
        action=Action(action_id='checked-backup',snapshot_id=snap.snapshot_id,start_s=1.,duration_s=4.,current_A=.01)
        package={'domain':{'temperature_K':[296.,300.],'max_current_A':.05,'channel_rates':[.001,.001]},'evidence_refs':[],'error_contracts':[]}
        actual=check(snap,action,package,ambient_K=298.,mode='empirical')
        # The deterministic example backup declares this full rate-scale range;
        # no posterior mean is substituted for the expanded parameter set.
        parameter_domain=all(n=='rate_scale' and u=='1' and .5<=b.lower<=b.upper<=1.5 for n,u,b in envelope.parameters)
        status=actual['decision'] if parameter_domain else 'reject'
        return Assessment(decision.sha256,envelope.sha256,'4'*64,status,'PASS',(),actual['reason'],True,request.sha256)
    result=revalidate_and_select(d,[Candidate('actual-domain-backup','fallback','4'*64,assess)],requested_power_W=30.,duration_s=4.)
    # 297..299 K expanded to 296..300 remains within the actual backup domain.
    assert result['response']=='revalidated_fallback' and result['safety_certificate']=='UNKNOWN'


def test_train_only_offline_queue_cannot_adopt_in_current_job():
    d=incident();request=offline_research_request(d,[{'id':'training-observation-1','role':'train','sha256':'a'*64}])
    assert request['state']=='pending' and request['automatic_adoption'] is False and request['requires_new_job_and_independent_acceptance']
    for role in ('validation','test','stress','online'):
        with pytest.raises(ValueError):offline_research_request(d,[{'id':'holdout','role':role,'sha256':'a'*64}])
    assert offline_research_request(d,[]) is None


def test_unregistered_research_candidate_and_old_request_cannot_authorize_action():
    d=incident();called=[]
    def new(e,d,r):called.append(True);return assessment(d,r)
    result=revalidate_and_select(d,[Candidate('new-offline-theory','upgrade','4'*64,new)],requested_power_W=90.,duration_s=4.)
    assert not called and result['response']=='stop_automatic_actions'
    def wrong_request(e,d,r):return replace(assessment(d,r),request_sha256='0'*64)
    result=revalidate_and_select(d,[Candidate('candidate','fallback','4'*64,wrong_request)],requested_power_W=90.,duration_s=4.)
    assert not result['action_permitted'] and result['unserved_energy_J']==360.


def test_real_p02_revalidation_parameter_change_reaches_monitor():
    from naheng.packages import current_class as cc
    from naheng.models.site_model import SiteModel
    model=SiteModel();manifest=ROOT/'artifacts/formal/core-required-public-20261014-b/manifest.json'
    binding=cc.bind(model,'p03-integration',manifest,model_package_id='p03-review',proof_root=ROOT)
    assert binding.record['proof']['status']=='PASS'
    start=initial(parameter_sha256=cc.parameter_hash(model),source_sha256=identity(cc.source_hashes()),checked_ids=tuple(binding.record['proof']['used_checked_ids']))
    monitor=ValidityMonitor(start)
    changed=SiteModel(replace(model.params,side_rate_s_inv=tuple(2*x for x in model.params.side_rate_s_inv)))
    result=observe_p02_binding(monitor,replace(start,time_s=1.),binding,changed,'p03-integration','PASS')
    assert result.status=='WITHDRAWN' and 'parameter_identity_changed' in result.reasons and 'binding_fail' in result.reasons
    assert set(result.revoked_ids)==set(start.checked_ids)


def test_real_immutable_p02_projection_keeps_full_correlated_component_references():
    from naheng.packages import current_class as cc,transition as tr
    from naheng.models.site_model import SiteModel,SiteParameters
    from naheng.domain.contracts import PosteriorSnapshot
    model=SiteModel(SiteParameters(site_capacity_mol=(1/64,1/128),rate_s_inv=(.001,.001),equilibrium_drive_V=(0.,0.),side_rate_s_inv=(2e-7,2e-7)))
    binding=cc.bind(model,'p03-projection',ROOT/tr.SELECTED_CORE,model_package_id='p03-projection',proof_root=ROOT)
    assert binding.record['proof']['status']=='PASS'
    rows=[[.5,.25,0.,.025,298.15],[.375,.5,0.,.025,298.15]]
    snap=PosteriorSnapshot(snapshot_id='p03-permitted',run_id='p03-review',model_package_id='p03-projection',parameter_revision='p03-projection',obs_until_s=0.,state_names=list(model.state_names),state_units=list(model.state_units),samples=rows,weights=[.3,.7],mean=dict(zip(model.state_names,rows[0])),quantiles={},ess=1.7)
    raw=cc.project_posterior(snap,model,binding);projection=tr._freeze_projection(raw,model,binding,snap)
    params=(('rate_scale','1',Bounds(.8,1.2)),)
    envelope=envelope_from_p02_projection(projection,model,binding,params)
    lift=tr.lift_grouped_posterior(projection,model,binding)
    assert envelope.retained_components==tuple(identity(component) for component in lift['sets'])
    assert envelope.states[0][2].lower<=.375 and envelope.states[0][2].upper>=.5
    assert envelope.parameters==params and all(part['unique_detailed_vector'] is None for part in lift['sets'])
    with pytest.raises(TypeError):envelope_from_p02_projection(raw,model,binding,params)


def test_existing_jobstore_persists_withdrawal_and_unserved_energy(tmp_path):
    from naheng.runtime.jobs import JobStore
    store=JobStore(tmp_path/'j');job=store.create({'mode':'interactive','test_kind':'P03_private'})
    start=replace(initial(),job_id=job['run_id']);monitor=ValidityMonitor(start)
    d=monitor.observe(replace(start,time_s=1.,binding_status='FAIL'))
    response=revalidate_and_select(d,[],requested_power_W=90.,duration_s=4.)
    event=persist_validity_event(store,d,response)
    persist_validity_event(store,d,response)
    saved=JobStore(tmp_path/'j').events(job['run_id'])
    rows=[row for row in saved if row.get('validity_event_id')==event['validity_event_id']]
    assert len(rows)==1 and rows[0]['type']=='validity_withdrawal'
    assert rows[0]['physical_stop_required'] and rows[0]['response']['unserved_energy_J']==360.
    assert store.get(job['run_id'])['state']=='queued'
    with pytest.raises(ValueError):persist_validity_event(store,d,dict(response,decision_sha256='0'*64))


def test_mutable_nested_coordinate_rows_cannot_change_envelope_after_hash():
    mutable=['x1','1',Bounds(.1,.9)]
    with pytest.raises(ValueError):Envelope((mutable,),(('rate','1',Bounds(.8,1.2)),))
    with pytest.raises(ValueError):Envelope((('x1','1',Bounds(.1,.9)),),(["rate","1",Bounds(.8,1.2)],))
    valid=Envelope((('x1','1',Bounds(.1,.9)),),(('rate','1',Bounds(.8,1.2)),))
    old=valid.sha256
    with pytest.raises(TypeError):valid.states[0][2]=Bounds(.3,.5)
    assert valid.sha256==old


def test_finite_factors_with_overflowing_energy_product_are_rejected_before_assessor():
    called=[]
    def assess(e,d,r):called.append(True);return assessment(d,r)
    with pytest.raises(ValueError):revalidate_and_select(incident(),[Candidate('candidate','fallback','4'*64,assess)],requested_power_W=1e308,duration_s=1e308)
    assert not called


def test_first_observation_cannot_precede_initial_time_and_equal_start_is_valid():
    start=initial(time_s=100.);monitor=ValidityMonitor(start)
    with pytest.raises(ValueError):monitor.observe(replace(start,time_s=99.))
    assert monitor.observe(start).sequence==1
