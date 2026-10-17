"""Opt-in validity gate used by the existing public simulation worker.

Only observed PF diagnostics and posterior/model identities enter this module.
It owns no simulator, estimator, planner, or actuator and cannot restart a run.
"""
from dataclasses import asdict
import math
from pathlib import Path
import time
from naheng.packages import current_class as cc
from naheng.packages.domain_check import check_domain
from naheng.packages.validity_monitor import Bounds,Envelope,Residual,MonitorInput,ValidityMonitor,identity
from .artifacts import atomic_json,code_hash
from .revalidation import revalidate_and_select,persist_validity_event


class ValidityStop(RuntimeError):
    """This frozen run must stop without any next automatic action."""


def validate_profiles(config):
    profile=config.get('validity_profile','off')
    sensor=config.get('synthetic_sensor_profile','baseline')
    if profile not in ('off','engineering-residual-v1'):raise ValueError('Unknown validity profile')
    if sensor not in ('baseline','voltage-bias-after-first-v1'):raise ValueError('Unknown synthetic sensor profile')
    if sensor!='baseline' and profile=='off':raise ValueError('Declared sensor stress profile requires explicit validity monitoring')
    power=config.get('requested_service_power_W',.04)
    if type(power) not in (int,float) or not math.isfinite(power) or not 0<=power<=10:
        raise ValueError('Finite service request in [0,10] W required')
    return profile!='off'


def voltage_bias(config,time_s):
    """Generate the declared new synthetic observation; never edit saved input."""
    return .35 if config.get('synthetic_sensor_profile')=='voltage-bias-after-first-v1' and time_s>=config['step_s'] else 0.


class RuntimeValidityGate:
    def __init__(self,project,source_root,store,run_id,config,model,package,pf,snapshot):
        self.project,self.source_root,self.store,self.run_id=Path(project),Path(source_root),store,run_id
        self.config,self.model,self.package,self.pf=config,model,package,pf
        self.dest=store.root/run_id;self.started=time.monotonic();self.stopped=False
        self.checks=[];self.service=[];self.stop_record=None;self.failures=[]
        self.binding=cc.bind(model,pf.parameter_revision,self.project/'artifacts/formal/core-required-public-20261014-b/manifest.json',
                             model_package_id=package['package_id'],proof_root=self.project)
        initial=self._input(snapshot,config['ambient_K'],False)
        self.monitor=ValidityMonitor(initial,residual_limit=3.,expansion_factor=2.,minimum_padding=1e-6,allowed_candidates=())
        self.persist()

    def _input(self,snapshot,ambient_K,residuals):
        binding=cc.revalidate(self.binding,self.model,self.pf.parameter_revision)
        domain=[row for row in check_domain(self.package,snapshot,ambient_K) if row['name']!='chemical_reduction']
        status='FAIL' if any(row['status']=='FAIL' for row in domain) else 'UNKNOWN' if any(row['status']!='PASS' for row in domain) else 'PASS'
        rows=snapshot.samples;names=snapshot.state_names
        bound=lambda name:Bounds(float(min(row[names.index(name)] for row in rows)),float(max(row[names.index(name)] for row in rows)))
        envelope=Envelope(tuple((name,unit,bound(name)) for name,unit in zip(self.model.state_names,self.model.state_units)),
            tuple((name,'1',bound(name)) for name in ('rate_scale','side_rate_scale')),(identity(snapshot.model_dump(mode='json')),))
        residual=()
        if residuals and snapshot.obs_until_s>0:
            diagnostics=self.pf.update_diagnostics[-1]
            residual=(Residual('voltage','V',diagnostics['voltage_innovation_V'],0.,diagnostics['voltage_innovation_scale_V']),
                      Residual('temperature','K',diagnostics['temperature_innovation_K'],0.,diagnostics['temperature_innovation_scale_K']))
        return MonitorInput(self.run_id,time.monotonic()-self.started,cc.parameter_hash(self.model),
            identity({'code_hash':code_hash(self.source_root),'mapping_sources':cc.source_hashes()}),status,binding['status'],
            tuple(binding['used_checked_ids']),envelope,residual)

    def check(self,snapshot,ambient_K,phase,*,residuals=True):
        if self.stopped:raise ValidityStop('Validity-latched run cannot execute a next action')
        inputs=self._input(snapshot,ambient_K,residuals)
        decision=self.monitor.observe(inputs)
        self.checks.append({'phase':phase,'observation_time_s':snapshot.obs_until_s,'snapshot_id':snapshot.snapshot_id,
            'inputs':asdict(inputs),'decision':decision.record()})
        if decision.revalidation_required:
            self.stopped=True
            remaining=max(0.,self.config['duration_s']-snapshot.obs_until_s)
            if remaining>0:
                response=revalidate_and_select(decision,[],requested_power_W=self.config.get('requested_service_power_W',.04),duration_s=remaining)
            else:
                # The final sensor can withdraw validity after all requested
                # service time elapsed. Record withdrawal without inventing a
                # positive service interval or bypassing the latched stop.
                response={'decision_sha256':decision.sha256,'envelope_sha256':decision.envelope.sha256,
                    'response':'stop_automatic_actions','selected_candidate':None,'action_permitted':False,
                    'attempts':[],'requested_energy_J':0.,'delivered_energy_J':0.,'unserved_energy_J':0.,
                    'service_status':'stopped_no_remaining_service','old_evidence_revoked':list(decision.revoked_ids),
                    'automatic_theory_adoption':False,'safety_certificate':'UNKNOWN',
                    'scope':'Final observation withdrew validity with no remaining requested service; future automatic actions stay forbidden'}
            self.stop_record={'reason':list(decision.reasons),'response':response,'remaining_duration_s':remaining}
            persist_validity_event(self.store,decision,response)
            self.persist()
            raise ValidityStop('Validity withdrawn; no feasible frozen fallback: '+', '.join(decision.reasons))
        persist_validity_event(self.store,decision);self.persist()

    def record_execution(self,action,actual,ledger):
        entries=[entry for entry in ledger.entries if entry['execution_id']==action.action_id]
        if len(entries)!=1:raise ValueError('One actual ledger entry is required before service accounting')
        if any(row['action_id']==action.action_id for row in self.service):raise ValueError('Actual service already accounted')
        entry=entries[0];requested=self.config.get('requested_service_power_W',.04)*entry['duration_s']
        self.service.append({'action_id':action.action_id,'execution_id':entry['execution_id'],'duration_s':entry['duration_s'],
            'requested_energy_J':requested,'actual_electrical_energy_J':entry['energy_J'],
            'delivered_export_energy_J':max(0.,entry['energy_J']),'unserved_energy_J':max(0.,requested-max(0.,entry['energy_J'])),
            'scope':'actual synthetic execution, not optimizer-predicted energy'})
        self.persist()

    def no_feasible_action(self,snapshot,reason):
        self.stopped=True;remaining=max(0.,self.config['duration_s']-snapshot.obs_until_s)
        self.stop_record={'reason':[reason],'remaining_duration_s':remaining,'response':{
            'response':'stop_automatic_actions','action_permitted':False,'selected_candidate':None,
            'attempts':[],'requested_energy_J':self.config.get('requested_service_power_W',.04)*remaining,
            'delivered_energy_J':0.,'unserved_energy_J':self.config.get('requested_service_power_W',.04)*remaining,
            'automatic_theory_adoption':False,'service_status':'stopped_unserved','scope':'No feasible frozen fallback registered'}}
        self.store.event(self.run_id,{'type':'validity_execution_stopped','reason':reason,'stop':self.stop_record})
        self.persist();raise ValidityStop(reason)

    def failure(self,error,*,execution_pending):
        # In-memory latch comes first, even when every write below fails.
        self.stopped=True
        self.failures.append({'type':type(error).__name__,'reason':str(error),'execution_pending':execution_pending,
            'unrecorded_execution_energy_J':None,'unserved_energy_J':None,'scope':'Unknown receipt is never zero energy'})
        try:self.persist()
        except Exception:pass

    def persist(self):
        atomic_json(self.dest/'validity.json',{'schema_version':1,'run_id':self.run_id,'profile':self.config['validity_profile'],
            'sensor_profile':self.config.get('synthetic_sensor_profile','baseline'),'stopped':self.stopped,
            'engineering_detection':{'residual_limit':3.,'scale':'1.4826 MAD with observer noise floor','false_alarm_probability':None},
            'checks':self.checks,'actual_service':self.service,'stop':self.stop_record,'failures':self.failures,
            'new_theory_auto_adopted':False,'new_independent_scientific_N':0})
