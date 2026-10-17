"""Conditional chemistry contracts consumed by protocol and output execution.

Availability of a checked real theorem and applicability to floating execution
remain separate. No missing whole-trajectory or numerical obligation is zero.
"""
from dataclasses import asdict
import math
from pathlib import Path

from naheng.packages.evidence_import import load_evidence
from naheng.packages.current_class import sha

TARGETS=(
    'Naheng.Aging.initialized_occupancy_antitone',
    'Naheng.Contracts.class_trapping_flux_error_from_class_amounts',
    'Naheng.Contracts.cumulative_trapping_error_from_class_amounts',
    'Naheng.Contracts.primitive_state_to_actual_first_retirement_contract',
)

def declarations(proof_root,manifest_path):
    result={'status':'UNKNOWN','used_checked_ids':[],'available_checked_ids':{},'reason':'No current publication'}
    if not manifest_path:return result
    try:
        loaded=load_evidence(Path(proof_root),Path(manifest_path))
        records={r['declaration']:r for r in loaded['records'] if r['declaration'] in TARGETS}
        if set(records)!=set(TARGETS):raise ValueError('Aging/output contract declarations missing')
        result.update(status='PASS',available_checked_ids={t:records[t]['evidence_id'] for t in TARGETS},
                      manifest_sha256=sha(manifest_path),reason='Full current publication verified; theorem premises remain explicit')
    except (ValueError,KeyError,TypeError,OSError) as error:result['reason']=str(error)
    return result

def accessibility_application(model,state,protocol,proof):
    """Apply the declared initialization order at fresh y=0 and this actual y.

    This does not prove order of observed voltage traces, capacity or RUL.
    """
    y=float(state[model.state_names.index('trapped_mol')]);total=math.fsum(model.params.site_capacity_mol)
    theta=protocol.initial_occupancy
    actual=theta*max(0.,1-y/total);fresh=theta
    valid=math.isfinite(y) and y>=0 and total>0 and theta>=0
    key=TARGETS[0];checked=proof['status']=='PASS' and valid
    return {'target':'protocol_initialization_occupancy','status':'PASS' if checked else 'UNKNOWN',
        'input':{'trapped_mol':y,'total_site_capacity_mol':total,'protocol':asdict(protocol)},
        'actual_aged_occupancy':actual,'comparison_fresh_occupancy':fresh,
        'used_checked_ids':[proof['available_checked_ids'][key]] if checked else [],
        'theorem_application_scope':'Real-model initialized_occupancy_antitone with 0<=y and theta>=0',
        'mapping_source':'trapped_accessibility_v1_synthetic_uncalibrated',
        'numerical_certificate':'UNKNOWN','capacity_order':'UNKNOWN','first_retirement':'UNKNOWN',
        'reason':'Initialization order alone supplies no voltage trajectory or capacity-order premise'}

def output_application(model,state,current_A,identity,proof,groups):
    """Expose the actual output and the conditional exact-class contract.

    The same-current class theorem selects the backend. No per-site delta is
    obtained from aggregate q; solver and whole-trajectory obligations stay open.
    """
    observable=model.observe(state,current_A)
    checked=identity['status']=='PASS'
    return {'target':['voltage_V','trapped_mol','protocol_capacity_C','first_retirement_s'],
        'same_current_A':current_A,'actual_observable':observable,'groups':[list(g) for g in groups],
        'exact_class_readout_condition':'PASS' if checked else 'UNKNOWN',
        'used_checked_ids':identity['used_checked_ids'] if checked else [],
        'available_conditional_contract_ids':proof['available_checked_ids'],
        'comparison_reference':'same-parameter detailed SiteModel real solution with same class amounts/input',
        'bound_expression':'exact class readout identity; no floating total error supplied',
        'horizon_scope':'query/protocol execution only; full-trajectory numerical certificate unavailable',
        'per_site_delta_from_total_q':None,
        'cumulative_trapping_error_bound_mol':None,'voltage_error_bound_V':None,
        'capacity_error_bound_C':None,'first_retirement_error_bound_s':None,
        'remaining_obligations':[
            'whole-time solution/domain and shared-input error envelope',
            'certified current-root/Float/ODE error',
            'successful same protocol with no competing exit',
            'voltage cutoff derivative floor and age-capacity derivative/sign conditions',
            'real-cell discrepancy and operational probability evidence'],
        'numerical_error':'UNKNOWN','probabilistic_assumptions':'UNKNOWN','strict_admission':'UNKNOWN'}
