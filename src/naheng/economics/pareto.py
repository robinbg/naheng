"""Comparable risk/conditional-value frontiers with a fixed full denominator."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math

from scipy.stats import beta


def _name(value):
    if not isinstance(value,str) or not value.strip(): raise ValueError('Explicit frozen comparison identity required')


@dataclass(frozen=True)
class ComparisonContext:
    frozen_protocol_sha256: str
    event_definition: str
    risk_scope: str
    alpha: float
    information_permissions_sha256: str
    terminal_rule_sha256: str
    financial_assumptions_sha256: str
    registered_case_ids: tuple[str,...]
    scheduled_horizon_s: float
    risk_metric: str = 'independent_operating_upper_bound'
    failure_rule: str = 'keep_all_unknown_conservative_no_probability_claim'

    def __post_init__(self):
        for name in ('frozen_protocol_sha256','information_permissions_sha256','terminal_rule_sha256','financial_assumptions_sha256'):
            value=getattr(self,name)
            if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('Frozen comparison SHA required: '+name)
        _name(self.event_definition); _name(self.risk_scope)
        if type(self.alpha) not in (int,float) or not math.isfinite(self.alpha) or not 0<self.alpha<1:
            raise ValueError('Same explicit statistical alpha in (0,1) required')
        if type(self.scheduled_horizon_s) not in (int,float) or not math.isfinite(self.scheduled_horizon_s) or self.scheduled_horizon_s<=0:
            raise ValueError('Explicit common positive horizon required')
        if type(self.registered_case_ids) is not tuple or len(set(self.registered_case_ids))!=len(self.registered_case_ids):
            raise ValueError('Unique frozen full case denominator required; empty remains UNKNOWN')
        for value in self.registered_case_ids: _name(value)
        if self.risk_metric not in ('independent_operating_upper_bound','conservative_registered_case_fraction'):
            raise ValueError('Explicit probability vs finite registered-case frontier required')
        if self.failure_rule!='keep_all_unknown_conservative_no_probability_claim': raise ValueError('Supported explicit failure denominator rule required')


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    status: str
    conditional_comparison_value_CNY: float | None
    event_occurred: bool | None
    source_ref: str
    independent_operating_trajectory: bool = False

    def __post_init__(self):
        _name(self.case_id); _name(self.source_ref)
        if self.status not in ('complete','early_exit','failed','cancelled','unknown'): raise ValueError('Explicit whole-case outcome required')
        if self.conditional_comparison_value_CNY is not None and (type(self.conditional_comparison_value_CNY) not in (int,float) or not math.isfinite(self.conditional_comparison_value_CNY)):
            raise ValueError('Finite actual evaluated conditional value or unknown required')
        if self.event_occurred is not None and type(self.event_occurred) is not bool: raise ValueError('Event result is boolean or unknown')
        if type(self.independent_operating_trajectory) is not bool: raise ValueError('Independent operating evidence scope must be explicit')


@dataclass(frozen=True)
class PolicyOutcome:
    policy_id: str
    context: ComparisonContext
    cases: tuple[CaseOutcome,...]

    def __post_init__(self):
        _name(self.policy_id)
        if type(self.context) is not ComparisonContext or type(self.cases) is not tuple or any(type(case) is not CaseOutcome for case in self.cases):
            raise TypeError('Typed immutable frozen context and whole cases required')
        if tuple(case.case_id for case in self.cases)!=self.context.registered_case_ids:
            raise ValueError('Every registered case must remain in its original denominator/order, including failures')


def pareto_frontier(outcomes):
    """Compare only one frozen protocol; unknown probability/finance stay unknown.

Finite-case conservative fractions are explicitly empirical engineering scores,
not operating probabilities or accident bounds. Both retain every frozen case.
"""
    outcomes=tuple(outcomes)
    if not outcomes or any(type(value) is not PolicyOutcome for value in outcomes): raise TypeError('Nonempty typed policy outcomes required')
    if len({value.policy_id for value in outcomes})!=len(outcomes): raise ValueError('Duplicate policy outcome')
    context=outcomes[0].context
    if any(value.context!=context for value in outcomes):
        raise ValueError('Different protocol/event/risk scope/alpha/information/terminal rules cannot be compared')
    records=[]
    for outcome in outcomes:
        n=len(outcome.cases)
        complete=[case for case in outcome.cases if case.status=='complete' and case.event_occurred is not None]
        k=sum(case.event_occurred is True for case in outcome.cases)
        conservative=sum(case.event_occurred is True or case.status!='complete' or case.event_occurred is None for case in outcome.cases)
        independent_n=sum(case.independent_operating_trajectory for case in outcome.cases)
        valid_probability=n>0 and len(complete)==n and independent_n==n
        upper=(1. if k==n else float(beta.ppf(1-context.alpha,k+1,n-k))) if valid_probability else None
        values=[case.conditional_comparison_value_CNY for case in outcome.cases]
        value=None if n==0 or any(v is None for v in values) else sum(values)/n
        fraction=conservative/n if n else None
        score=upper if context.risk_metric=='independent_operating_upper_bound' else fraction
        reasons=[]
        if not valid_probability: reasons.append('operating_probability_UNKNOWN_N0_or_incomplete_or_nonindependent')
        if value is None: reasons.append('comparison_value_UNKNOWN_no_success_only_mean')
        records.append({'policy_id':outcome.policy_id,'full_registered_n':n,'independent_operating_n':independent_n,
            'complete_known_event_n':len(complete),'observed_event_k':k,'conservative_case_count':conservative,
            'conservative_registered_case_fraction':fraction,'operating_probability_upper_bound':upper,
            'mean_conditional_comparison_value_CNY':value,'frontier_risk_score':score,
            'frontier_eligible':score is not None and value is not None,'unknown_reasons':reasons,
            'cases':[asdict(case) for case in outcome.cases]})
    eligible=[row for row in records if row['frontier_eligible']]
    frontier=[]
    for row in eligible:
        dominated=any(other['frontier_risk_score']<=row['frontier_risk_score'] and
                      other['mean_conditional_comparison_value_CNY']>=row['mean_conditional_comparison_value_CNY'] and
                      (other['frontier_risk_score']<row['frontier_risk_score'] or
                       other['mean_conditional_comparison_value_CNY']>row['mean_conditional_comparison_value_CNY']) for other in eligible)
        if not dominated: frontier.append(row['policy_id'])
    result={'comparison_context':asdict(context),'records':records,'frontier_policy_ids':sorted(frontier),
        'risk_metric_is_operating_probability':context.risk_metric=='independent_operating_upper_bound',
        'no_failed_cases_dropped':True,'terminal_comparison_is_realized_revenue':False,
        'scope':'Deterministic same-protocol frontier; caller verifies actual sources, frozen selection and independent operating distribution'}
    result['content_sha256']=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return result
