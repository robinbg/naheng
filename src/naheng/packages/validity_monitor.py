"""Server-side validity incidents; uncertainty sets are not new probabilities.

The caller supplies predictions and domains from the existing model/admission
path. This monitor never reads evaluator truth, runs a solver, or adopts theory.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import re


def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def finite(value, *, nonnegative=False):
    if type(value) not in (int,float) or not math.isfinite(value) or (nonnegative and value<0):
        raise ValueError('Finite numeric value required')
    return float(value)


@dataclass(frozen=True)
class Bounds:
    lower: float
    upper: float

    def __post_init__(self):
        finite(self.lower);finite(self.upper)
        if self.lower>self.upper:raise ValueError('Ordered bounds required')


@dataclass(frozen=True)
class Envelope:
    """Outer set with units and retained correlated components, no probability."""
    states: tuple[tuple[str,str,Bounds], ...]
    parameters: tuple[tuple[str,str,Bounds], ...]
    retained_components: tuple[str, ...] = ()

    def __post_init__(self):
        for values in (self.states,self.parameters):
            if type(values) is not tuple or not values:raise ValueError('Nonempty immutable bounds required')
            if any(type(row) is not tuple or len(row)!=3 for row in values):raise ValueError('Every coordinate row must be an immutable triple')
            if len({v[0] for v in values})!=len(values):raise ValueError('Unique coordinates required')
            for name,unit,bounds in values:
                if not isinstance(name,str) or not name or not isinstance(unit,str) or not unit or type(bounds) is not Bounds:
                    raise ValueError('Named unit-bound coordinates required')
        if type(self.retained_components) is not tuple or any(not isinstance(x,str) or not x for x in self.retained_components):
            raise ValueError('Immutable retained component identifiers required')

    def record(self):
        convert=lambda rows:[{'name':n,'unit':u,'lower':b.lower,'upper':b.upper} for n,u,b in rows]
        return {'states':convert(self.states),'parameters':convert(self.parameters),
                'retained_components':list(self.retained_components),'coverage':'outer_set_not_calibrated_probability'}

    @property
    def sha256(self):return identity(self.record())

    def hull(self,other):
        def merge(left,right):
            if [(x[0],x[1]) for x in left]!=[(x[0],x[1]) for x in right]:raise ValueError('Envelope coordinates/units changed')
            return tuple((n,u,Bounds(min(b.lower,c.lower),max(b.upper,c.upper))) for (n,u,b),(_,_,c) in zip(left,right))
        return Envelope(merge(self.states,other.states),merge(self.parameters,other.parameters),
                        tuple(dict.fromkeys(self.retained_components+other.retained_components)))

    def widen(self,factor,minimum_padding):
        if finite(factor)<1 or finite(minimum_padding,nonnegative=True)<=0:raise ValueError('Expansion factor>=1 and positive pad required')
        def expand(values):
            return tuple((n,u,Bounds(b.lower-max((b.upper-b.lower)*(factor-1)/2,minimum_padding),
                                    b.upper+max((b.upper-b.lower)*(factor-1)/2,minimum_padding))) for n,u,b in values)
        # No clipping to a physical domain: doing so could hide the incident.
        return Envelope(expand(self.states),expand(self.parameters),self.retained_components)

    def encloses(self,other):
        def includes(left,right):
            return len(left)==len(right) and all(n==m and u==v and b.lower<=c.lower and b.upper>=c.upper
                 for (n,u,b),(m,v,c) in zip(left,right))
        return includes(self.states,other.states) and includes(self.parameters,other.parameters) and set(other.retained_components)<=set(self.retained_components)


@dataclass(frozen=True)
class Residual:
    channel: str
    unit: str
    observed: float
    predicted: float
    scale: float

    def __post_init__(self):
        finite(self.observed);finite(self.predicted)
        if finite(self.scale)<=0 or not self.channel or not self.unit:raise ValueError('Residual channel/unit and positive scale required')

    @property
    def standardized(self):return (self.observed-self.predicted)/self.scale


@dataclass(frozen=True)
class MonitorInput:
    job_id: str
    time_s: float
    parameter_sha256: str
    source_sha256: str
    domain_status: str
    binding_status: str
    checked_ids: tuple[str, ...]
    envelope: Envelope
    residuals: tuple[Residual, ...] = ()

    def __post_init__(self):
        finite(self.time_s,nonnegative=True)
        if not self.job_id or self.domain_status not in {'PASS','FAIL','UNKNOWN'} or self.binding_status not in {'PASS','FAIL','UNKNOWN'}:raise ValueError('Explicit server validity statuses required')
        if any(not isinstance(v,str) or re.fullmatch('[0-9a-f]{64}',v) is None for v in (self.parameter_sha256,self.source_sha256)):raise ValueError('Actual SHA256 identities required')
        if type(self.checked_ids) is not tuple or len(set(self.checked_ids))!=len(self.checked_ids) or any(not isinstance(x,str) or not x for x in self.checked_ids):raise ValueError('Unique immutable evidence identifiers required')
        if type(self.envelope) is not Envelope or type(self.residuals) is not tuple or any(type(r) is not Residual for r in self.residuals):raise TypeError('Typed uncertainty/residual inputs required')
        if len({r.channel for r in self.residuals})!=len(self.residuals):raise ValueError('Duplicate residual channels')


@dataclass(frozen=True)
class Decision:
    job_id: str
    sequence: int
    time_s: float
    status: str
    reasons: tuple[str,...]
    revoked_ids: tuple[str,...]
    envelope: Envelope
    revalidation_required: bool
    current_actions_permitted: bool
    allowed_candidates: tuple[tuple[str,str], ...] = ()

    def record(self):
        return {'job_id':self.job_id,'sequence':self.sequence,'time_s':self.time_s,'status':self.status,
                'reasons':list(self.reasons),'revoked_ids':list(self.revoked_ids),'envelope':self.envelope.record(),
                'envelope_sha256':self.envelope.sha256,'revalidation_required':self.revalidation_required,
                'current_actions_permitted':self.current_actions_permitted,'allowed_candidates':[list(x) for x in self.allowed_candidates],
                'new_theory_auto_adopted':False}

    @property
    def sha256(self):return identity(self.record())


class ValidityMonitor:
    """Incidents latch for this frozen job; a new job must explicitly rebind.

    Supplied scales/thresholds are engineering settings, not calibrated claims.
    A single large residual holds actions; repeated residuals record persistence.
    """
    def __init__(self,initial:MonitorInput,*,residual_limit=3.,persistent_count=2,expansion_factor=2.,minimum_padding=1e-6,allowed_candidates=()):
        if type(initial) is not MonitorInput:raise ValueError('An explicit initial server identity is required')
        if finite(residual_limit)<=0 or type(persistent_count) is not int or persistent_count<1:raise ValueError('Positive residual policy required')
        initial.envelope.widen(expansion_factor,minimum_padding)
        if type(allowed_candidates) is not tuple or any(type(row) is not tuple or len(row)!=2 or not isinstance(row[0],str) or not row[0]
             or not isinstance(row[1],str) or re.fullmatch('[0-9a-f]{64}',row[1]) is None for row in allowed_candidates):raise ValueError('Frozen server candidate identities required')
        if len({row[0] for row in allowed_candidates})!=len(allowed_candidates):raise ValueError('Unique frozen candidate IDs required')
        self.allowed_candidates=allowed_candidates
        self.initial=initial;self.residual_limit=residual_limit;self.persistent_count=persistent_count
        self.factor=expansion_factor;self.padding=minimum_padding;self._envelope=initial.envelope
        self._last_time=None;self._sequence=0;self._counts={};self._reasons=[];self._revoked=set()

    def observe(self,inputs:MonitorInput)->Decision:
        if type(inputs) is not MonitorInput or inputs.job_id!=self.initial.job_id:raise ValueError('Same frozen job required')
        if inputs.time_s<self.initial.time_s:raise ValueError('Observation cannot precede the initial monitor time')
        if self._last_time is not None and inputs.time_s<=self._last_time:raise ValueError('Observation time must increase')
        # Validate before committing any internal state.
        outer=self._envelope.hull(inputs.envelope);reasons=[];counts=dict(self._counts)
        if inputs.parameter_sha256!=self.initial.parameter_sha256:reasons.append('parameter_identity_changed')
        if inputs.source_sha256!=self.initial.source_sha256:reasons.append('source_identity_changed')
        if inputs.domain_status!='PASS':reasons.append('domain_'+inputs.domain_status.lower())
        if inputs.binding_status!='PASS':reasons.append('binding_'+inputs.binding_status.lower())
        if inputs.checked_ids!=self.initial.checked_ids:reasons.append('selected_evidence_changed')
        present=set()
        for residual in inputs.residuals:
            present.add(residual.channel)
            count=counts.get(residual.channel,0)+1 if abs(residual.standardized)>self.residual_limit else 0
            counts[residual.channel]=count
            if count:reasons.append('residual_exceeded:'+residual.channel)
            if count>=self.persistent_count:reasons.append('persistent_residual:'+residual.channel)
        for channel in set(counts)-present:counts[channel]=0
        if reasons:outer=outer.widen(self.factor,self.padding)
        combined=list(dict.fromkeys(self._reasons+reasons))
        revoked=set(self._revoked)
        if combined:revoked.update(self.initial.checked_ids);revoked.update(inputs.checked_ids)
        self._sequence+=1;self._last_time=inputs.time_s;self._counts=counts;self._envelope=outer;self._reasons=combined;self._revoked=revoked
        return Decision(inputs.job_id,self._sequence,inputs.time_s,'WITHDRAWN' if combined else 'CURRENT',tuple(combined),tuple(sorted(revoked)),outer,bool(combined),not combined,self.allowed_candidates)


def offline_research_request(decision,training_refs):
    """Queueable description only. No execution, network or current-job adoption."""
    if type(decision) is not Decision or not decision.revalidation_required:return None
    refs=[]
    for ref in training_refs:
        if type(ref) is not dict or set(ref)!={'id','role','sha256'} or ref['role']!='train':raise ValueError('Only explicit train-role references may enter offline research')
        if not isinstance(ref['id'],str) or not ref['id'] or not isinstance(ref['sha256'],str) or re.fullmatch('[0-9a-f]{64}',ref['sha256']) is None:raise ValueError('Training artifact identity required')
        refs.append(dict(ref))
    if not refs:return None
    return {'kind':'offline_validity_research','incident_sha256':decision.sha256,'job_id':decision.job_id,
            'training_refs':refs,'reasons':list(decision.reasons),'state':'pending',
            'automatic_adoption':False,'requires_new_job_and_independent_acceptance':True}
