"""Deterministic response selection using fresh server-owned feasibility calls.

This file dispatches no actuator. Assessors must compute on the complete widened
envelope and return current model identity; UNKNOWN cannot authorize an action.
"""
from dataclasses import dataclass
import math
import re
from naheng.packages.validity_monitor import Bounds,Decision,Envelope,identity,finite


@dataclass(frozen=True)
class ServiceRequest:
    requested_power_W: float
    duration_s: float

    def __post_init__(self):
        finite(self.requested_power_W,nonnegative=True)
        if finite(self.duration_s,nonnegative=True)<=0:raise ValueError('Positive service duration required')

    @property
    def sha256(self):return identity({'requested_power_W':self.requested_power_W,'duration_s':self.duration_s})


@dataclass(frozen=True)
class Assessment:
    decision_sha256: str
    envelope_sha256: str
    model_sha256: str
    status: str
    binding_status: str
    used_ids: tuple[str,...]
    reason: str
    whole_envelope_checked: bool
    request_sha256: str

    def __post_init__(self):
        if any(not isinstance(v,str) or re.fullmatch('[0-9a-f]{64}',v) is None for v in (self.decision_sha256,self.envelope_sha256,self.model_sha256,self.request_sha256)):raise ValueError('Assessment must bind actual input/model/request SHA256')
        if self.status not in {'accept','reject','unknown'} or self.binding_status not in {'PASS','FAIL','UNKNOWN'}:raise ValueError('Explicit assessment states required')
        if type(self.whole_envelope_checked) is not bool or type(self.used_ids) is not tuple or any(not isinstance(x,str) or not x for x in self.used_ids) or len(set(self.used_ids))!=len(self.used_ids):raise ValueError('Explicit coverage and unique immutable evidence IDs required')


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    kind: str
    model_sha256: str
    assess: object

    def __post_init__(self):
        if not self.candidate_id or self.kind not in {'upgrade','fallback'} or not callable(self.assess):raise ValueError('Server candidate with callable assessor required')
        if not isinstance(self.model_sha256,str) or re.fullmatch('[0-9a-f]{64}',self.model_sha256) is None:raise ValueError('Current candidate model SHA256 required')


def revalidate_and_select(decision:Decision,candidates,*,requested_power_W,duration_s):
    if type(decision) is not Decision:raise TypeError('Monitor decision required')
    power=finite(requested_power_W,nonnegative=True);duration=finite(duration_s,nonnegative=True)
    if duration<=0:raise ValueError('Positive service duration required')
    requested=finite(power*duration,nonnegative=True)
    request=ServiceRequest(power,duration)
    offered=tuple(candidates)
    if any(type(c) is not Candidate for c in offered) or len({c.candidate_id for c in offered})!=len(offered):raise ValueError('Unique typed candidates required')
    attempts=[];chosen=None
    # Upgrades precede backups; supplied order is retained within each kind.
    for c in sorted(offered,key=lambda x:0 if x.kind=='upgrade' else 1):
        if (c.candidate_id,c.model_sha256) not in decision.allowed_candidates:
            attempts.append({'candidate_id':c.candidate_id,'kind':c.kind,'accepted':False,'reason':'Candidate was not registered in this frozen job'})
            continue
        try:
            a=c.assess(decision.envelope,decision,request)
            valid=(type(a) is Assessment and a.decision_sha256==decision.sha256 and a.envelope_sha256==decision.envelope.sha256
                   and a.model_sha256==c.model_sha256 and a.request_sha256==request.sha256 and a.status=='accept' and a.binding_status=='PASS'
                   and type(a.whole_envelope_checked) is bool and a.whole_envelope_checked
                   and type(a.used_ids) is tuple and not set(a.used_ids).intersection(decision.revoked_ids))
            attempts.append({'candidate_id':c.candidate_id,'kind':c.kind,'accepted':valid,'assessment':None if type(a) is not Assessment else {
                'status':a.status,'binding_status':a.binding_status,'reason':a.reason,'used_ids':list(a.used_ids),
                'whole_envelope_checked':a.whole_envelope_checked,'decision_sha256':a.decision_sha256,'envelope_sha256':a.envelope_sha256,'model_sha256':a.model_sha256,'request_sha256':a.request_sha256}})
        except Exception as error:
            valid=False;attempts.append({'candidate_id':c.candidate_id,'kind':c.kind,'accepted':False,'error_type':type(error).__name__,'reason':str(error)})
        if valid:chosen=c;break
    return {'decision_sha256':decision.sha256,'envelope_sha256':decision.envelope.sha256,'request_sha256':request.sha256,
            'response':'stop_automatic_actions' if chosen is None else 'revalidated_'+chosen.kind,
            'selected_candidate':None if chosen is None else chosen.candidate_id,
            'action_permitted':chosen is not None,'attempts':attempts,
            'requested_energy_J':requested,'delivered_energy_J':0. if chosen is None else None,
            'unserved_energy_J':requested if chosen is None else None,
            'service_status':'stopped_unserved' if chosen is None else 'awaiting_actual_execution',
            'old_evidence_revoked':list(decision.revoked_ids),'automatic_theory_adoption':False,
            'safety_certificate':'UNKNOWN','scope':'server revalidation decision; no physical service reported before execution'}


def record_actual_service(response,*,delivered_energy_J):
    """Never infer delivery from a scheduled action; account actual service once."""
    if response.get('service_status')!='awaiting_actual_execution':raise ValueError('Only a selected, not-yet-accounted action can record service')
    delivered=finite(delivered_energy_J,nonnegative=True);requested=finite(response['requested_energy_J'],nonnegative=True)
    if delivered>requested:raise ValueError('Service delivery cannot exceed requested service energy')
    out=dict(response);out.update(delivered_energy_J=delivered,unserved_energy_J=requested-delivered,service_status='actual_service_recorded')
    return out


def observe_p02_binding(monitor,inputs,binding,model,revision,domain_status):
    """Use P02's real per-use revalidation; do not accept a client proof status."""
    from dataclasses import replace
    from naheng.packages import current_class
    state=current_class.revalidate(binding,model,revision)
    fresh=replace(inputs,parameter_sha256=current_class.parameter_hash(model),
                  source_sha256=identity(current_class.source_hashes()),domain_status=domain_status,
                  binding_status=state['status'],checked_ids=tuple(state['used_checked_ids']))
    return monitor.observe(fresh)


def envelope_from_p02_projection(projection,model,binding,parameter_bounds):
    """Read the immutable P02 lift without selecting a fictitious fine state.

    Marginal bounds are only an outer set for conservative validity checks.
    Complete weighted correlated components remain in the P02 artifact and are
    referenced by their full canonical digest, not replaced by fake particles.
    """
    from naheng.packages.transition import lift_grouped_posterior
    lifted=lift_grouped_posterior(projection,model,binding)
    states=[]
    for index,(name,unit) in enumerate(zip(model.state_names,model.state_units)):
        limits=[]
        for component in lifted['sets']:
            if index<2:
                matches=[row for row in component['occupancy_bounds'] if row['site']==index]
                if len(matches)!=1:raise ValueError('Each original site needs one correlated-lift bound')
                limits.append((matches[0]['lower'],matches[0]['upper']))
            else:
                value=component['preserved_non_site_state'][name];limits.append((value,value))
        # P02 may emit NumPy scalar float64 bounds; explicitly transfer their
        # finite values without broadening the external JSON numeric contract.
        states.append((name,unit,Bounds(float(min(x[0] for x in limits)),float(max(x[1] for x in limits)))))
    refs=tuple(identity(component) for component in lifted['sets'])
    return Envelope(tuple(states),parameter_bounds,refs)


def persist_validity_event(store,decision,response=None):
    """Append one auditable event to the existing job store, never delete proof.

    The run coordinator remains responsible for stopping physical execution.
    This function cannot change a failed job into success or adopt new theory.
    """
    if type(decision) is not Decision:raise TypeError('Typed validity decision required')
    store.get(decision.job_id)
    if response is not None and (type(response) is not dict or response.get('decision_sha256')!=decision.sha256
                               or response.get('envelope_sha256')!=decision.envelope.sha256):
        raise ValueError('Response must bind this exact validity decision')
    event={'type':'validity_withdrawal' if decision.revalidation_required else 'validity_observation',
           'decision':decision.record(),'decision_sha256':decision.sha256,'response':response,
           'physical_stop_required':bool(response and response.get('response')=='stop_automatic_actions'),
           'global_formal_theorems_deleted':False}
    event['validity_event_id']='validity-'+identity(event)
    existing=next((x for x in store.events(decision.job_id) if x.get('validity_event_id')==event['validity_event_id']),None)
    if existing is None:store.event(decision.job_id,event)
    return event
