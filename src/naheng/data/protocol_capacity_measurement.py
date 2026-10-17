"""Observed CSV capacity protocol, separate from synthetic model capacity.

No fits, model inference, rescaling, SOC/SOH labels or acceptance certificate.
Boundary interpolation is a stated reconstruction assumption, not true timing.
"""
from dataclasses import asdict, dataclass
import csv
import hashlib
import math
from pathlib import Path


@dataclass(frozen=True)
class Policy:
    protocol_id: str = 'observed_cccv_3p9V_rest1800_0p2C_to1p5V_v1'
    charge_C_rate: float = .5
    charge_cutoff_C_rate: float = .02
    discharge_C_rate: float = .2
    upper_V: float = 3.9
    lower_V: float = 1.5
    rest_s: float = 1800.
    max_gap_s: float = 60.
    bridge_max_s: float = 5.
    zero_current_tolerance_A: float = .01
    current_relative_tolerance: float = .01
    voltage_recognition_tolerance_V: float = 1e-4
    clock_recognition_tolerance_s: float = .05
    counter_tolerance_Ah: float = 1e-8
    minimum_diagnostic_discharge_s: float = 300.


HEADERS = {'sequence':'Data Point', 'time':'Test Time (s)', 'step_time':'Step Time (s)',
    'cycle':'Cycle Index', 'step':'Step Index', 'vendor_I':'Current (A)', 'V':'Voltage (V)',
    'charge_Ah':'Charge Capacity (Ah)', 'discharge_Ah':'Discharge Capacity (Ah)',
    'T_C':'Aux_Temperature_1 (C)'}


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def finite(value):
    try:
        out=float(value)
        return out if math.isfinite(out) else None
    except (ValueError,TypeError):return None


def reference(row):
    if row is None:return None
    return {key:row[key] for key in ('source_row','sequence','time','step_time','cycle','step',
        'vendor_I','I','V','T_K','charge_Ah','discharge_Ah','epoch')}


def read_rows(path, vendor_current_sign):
    factor={'positive_charge':-1., 'positive_discharge':1.}.get(vendor_current_sign)
    rows=[]
    epoch=0
    previous=None
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        if reader.fieldnames is None or len(set(reader.fieldnames))!=len(reader.fieldnames):
            return [],['missing_or_duplicate_CSV_header']
        missing=[v for v in HEADERS.values() if v not in reader.fieldnames]
        if missing:return [],['missing_columns:'+','.join(missing)]
        for source_row, raw in enumerate(reader,1):
            row={key:finite(raw.get(col)) for key,col in HEADERS.items()}
            row.update(source_row=source_row, I=row['vendor_I']*factor if row['vendor_I'] is not None and factor is not None else None,
                T_K=row['T_C']+273.15 if row['T_C'] is not None else None, issues=[],epoch=epoch)
            if None in raw or any(v is None for v in raw.values()):row['issues'].append('malformed_CSV_row')
            for k in HEADERS:
                if row[k] is None:row['issues'].append('missing_or_nonfinite_'+k)
            for k in ('sequence','cycle','step'):
                if row[k] is not None and row[k]!=int(row[k]):row['issues'].append('noninteger_'+k)
            if row['T_K'] is not None and row['T_K']<0:row['issues'].append('below_absolute_zero')
            if row['V'] is not None and row['V']<=0:row['issues'].append('nonpositive_voltage')
            if row['sequence']!=source_row:row['issues'].append('source_sequence_not_row_order')
            if previous is not None:
                if row['time'] is None or previous['time'] is None or row['time']<=previous['time']:
                    epoch+=1
                    row['issues'].append('time_reset_or_nonincreasing')
                if row['sequence'] is None or previous['sequence'] is None or row['sequence']!=previous['sequence']+1:
                    row['issues'].append('source_sequence_gap')
            row['epoch']=epoch
            rows.append(row)
            previous=row
    return rows,[]


def blocks_from(rows):
    blocks=[]
    for row in rows:
        key=(row['epoch'],row['cycle'],row['step'])
        if not blocks or blocks[-1]['key']!=key or 'source_sequence_gap' in row['issues']:
            blocks.append({'key':key,'rows':[]})
        blocks[-1]['rows'].append(row)
    return blocks


def same_interval(a,b,policy):
    return (a['epoch']==b['epoch'] and a['time'] is not None and b['time'] is not None
        and 0<b['time']-a['time']<=policy.max_gap_s and a['sequence'] is not None
        and b['sequence']==a['sequence']+1)


def clock_check(records,policy):
    """Check each within-step clock pair; endpoint cancellation cannot hide faults."""
    violations=[]
    for a,b in zip(records,records[1:]):
        reasons=[]
        if a['step_time'] is None or b['step_time'] is None or b['step_time']<=a['step_time']:
            reasons.append('step_clock_missing_reset_or_nonincreasing')
        if not same_interval(a,b,policy):reasons.append('test_clock_or_sequence_invalid')
        if all(r[k] is not None for r in (a,b) for k in ('time','step_time')):
            if abs((b['time']-a['time'])-(b['step_time']-a['step_time']))>policy.clock_recognition_tolerance_s:
                reasons.append('adjacent_dual_clock_disagreement')
        if reasons:violations.append({'first_source_row':a['source_row'],
            'second_source_row':b['source_row'],'reasons':reasons})
    return {'adjacent_pair_count':max(0,len(records)-1),'valid':not violations,'violations':violations}


def integration(a,b,end_fraction=1.):
    dt=b['time']-a['time']
    current_end=a['I']+end_fraction*(b['I']-a['I'])
    left,right=a['I'],current_end
    if left*right>=0:
        area=(abs(left)+abs(right))*.5
    else:
        # Exact integral of |linear I| for a sign crossing inside this sample pair.
        area=(left*left+right*right)/(2*abs(right-left))
    return area*dt*end_fraction/3600


def observed_throughput(rows,policy):
    result=0.
    intervals=0
    rejected=0
    for a,b in zip(rows,rows[1:]):
        if same_interval(a,b,policy) and all(r['I'] is not None and r['I']>=0 and r['V'] is not None and r['V']>0 for r in (a,b)):
            result+=integration(a,b)
            intervals+=1
        else:rejected+=1
    return {'measured_throughput_Ah':result if intervals else None,'measured_interval_count':intervals,
        'rejected_interval_count':rejected,'scope':'Discharge charge between recorded points only; no initialization or complete capacity assertion'}


def attempt(blocks,index,rows,nominal,policy):
    discharge=blocks[index]['rows']
    first,last=discharge[0],discharge[-1]
    target_I=nominal*policy.discharge_C_rate
    tol=max(policy.zero_current_tolerance_A,target_I*policy.current_relative_tolerance)
    out={'status':'unknown','actual_capacity_Ah':None,'protocol_id':policy.protocol_id,
        'reasons':[],'start_record':reference(first),'end_record':reference(last),
        'nominal_capacity_Ah':nominal,'discharge_target_A':target_I,
        'full_protocol_capacity_is_estimate':True,'strict_capacity_certificate':False,
        'SOC_label':None,'SOH_label':None,'RUL_label':None}
    out.update(observed_throughput(discharge,policy))
    reasons=out['reasons']
    if any(r['I'] is None or abs(r['I']-target_I)>tol for r in discharge):reasons.append('discharge_not_fixed_0p2C')
    if any(r['issues'] for r in discharge):reasons.append('discharge_missing_invalid_or_discontinuous_record')
    if any(not same_interval(a,b,policy) for a,b in zip(discharge,discharge[1:])):reasons.append('discharge_time_or_sequence_gap')
    discharge_clocks=clock_check(discharge,policy)
    out['clock_validation']={'discharge':discharge_clocks}
    if not discharge_clocks['valid']:
        reasons.append('discharge_instrument_clock_mismatch')
    temperatures=[r['T_K'] for r in discharge if r['T_K'] is not None]
    out['measured_temperature_K_range']=[min(temperatures),max(temperatures)] if temperatures else None
    rest_index=index-1
    bridge=None
    if rest_index>=0:
        prior=blocks[rest_index]['rows']
        # At most one short instrument bridge is permitted only at rest current.
        if len(prior)<=2 and all(r['time'] is not None for r in prior) and prior[-1]['time']-prior[0]['time']<=policy.bridge_max_s:
            bridge=prior
            rest_index-=1
    rest=blocks[rest_index]['rows'] if rest_index>=0 else []
    charge=blocks[rest_index-1]['rows'] if rest_index>=1 else []
    out['clock_validation']['rest']=clock_check(rest,policy)
    out['clock_validation']['charge']=clock_check(charge,policy)
    out['initialization']={'charge_first':reference(charge[0]) if charge else None,
        'charge_last':reference(charge[-1]) if charge else None,'rest_first':reference(rest[0]) if rest else None,
        'rest_last':reference(rest[-1]) if rest else None,'bridge_records':[reference(r) for r in bridge] if bridge else [],
        'meaning':'Observed CC-CV signature and instrument step clock, not direct proof of electrochemical full state'}
    if not rest or any(r['I'] is None or abs(r['I'])>policy.zero_current_tolerance_A for r in rest):reasons.append('missing_zero_current_rest')
    if rest:
        if not out['clock_validation']['rest']['valid']:reasons.append('rest_adjacent_clock_invalid')
        observed_rest=(rest[-1]['time']-rest[0]['time']) if rest[-1]['time'] is not None and rest[0]['time'] is not None else None
        out['initialization'].update(rest_recorded_elapsed_s=observed_rest,rest_last_step_time_s=rest[-1]['step_time'])
        if (rest[0]['step_time'] is None or rest[-1]['step_time'] is None or rest[0]['step_time']>policy.max_gap_s
            or rest[-1]['step_time']<policy.rest_s-policy.clock_recognition_tolerance_s):reasons.append('rest_1800s_not_established')
        if any(r['issues'] for r in rest) or any(not same_interval(a,b,policy) for a,b in zip(rest,rest[1:])):reasons.append('rest_missing_invalid_or_discontinuous')
        if observed_rest is None or rest[-1]['step_time'] is None or rest[0]['step_time'] is None or abs(observed_rest-(rest[-1]['step_time']-rest[0]['step_time']))>policy.clock_recognition_tolerance_s:
            reasons.append('rest_instrument_clock_mismatch')
    if bridge and (any(r['I'] is None or abs(r['I'])>policy.zero_current_tolerance_A for r in bridge)
        or any(r['issues'] for r in bridge)):reasons.append('non_rest_or_invalid_pre_discharge_bridge')
    charge_target=nominal*policy.charge_C_rate
    cutoff_target=nominal*policy.charge_cutoff_C_rate
    charge_tol=max(policy.zero_current_tolerance_A,charge_target*policy.current_relative_tolerance)
    cutoff_tol=max(policy.zero_current_tolerance_A,cutoff_target*policy.current_relative_tolerance)
    if not charge:reasons.append('CCCV_initialization_missing')
    else:
        if not out['clock_validation']['charge']['valid']:reasons.append('CCCV_adjacent_clock_invalid')
        if any(r['I'] is None or r['I']>policy.zero_current_tolerance_A or r['issues'] for r in charge):reasons.append('CCCV_invalid_record_or_sign')
        if charge[0]['I'] is None or abs(-charge[0]['I']-charge_target)>charge_tol:reasons.append('initial_charge_not_0p5C')
        end=charge[-1]
        if end['V'] is None or abs(end['V']-policy.upper_V)>policy.voltage_recognition_tolerance_V:reasons.append('charge_3p9V_not_established')
        if end['I'] is None or -end['I']<0 or -end['I']>cutoff_target+cutoff_tol:reasons.append('charge_0p02C_cutoff_not_established')
        cv=[r for r in charge if r['V'] is not None and abs(r['V']-policy.upper_V)<=policy.voltage_recognition_tolerance_V]
        if len(cv)<2 or not any(r['I'] is not None and -r['I']>cutoff_target+cutoff_tol for r in cv[:-1]):reasons.append('CV_taper_not_observed')
        if any(not same_interval(a,b,policy) for a,b in zip(charge,charge[1:])):reasons.append('CCCV_time_or_sequence_gap')
    chain=charge[-1:]+rest+(bridge or [])+discharge[:1]
    if chain and any(not same_interval(a,b,policy) for a,b in zip(chain,chain[1:])):reasons.append('initialization_chain_time_or_sequence_gap')
    crossing=None
    for n,(a,b) in enumerate(zip(discharge,discharge[1:]),1):
        if a['V'] is not None and b['V'] is not None and a['V']>policy.lower_V and b['V']<=policy.lower_V:
            crossing=(n,a,b)
            break
    if first['V'] is None or first['V']<=policy.lower_V:reasons.append('discharge_start_not_above_cutoff')
    if crossing is None:reasons.append('lower_cutoff_not_observed')
    # A known next stop is needed; an EOF at the cutoff is still partial evidence.
    following=rows[last['source_row']] if last['source_row']<len(rows) else None
    if following is None or following['I'] is None or abs(following['I'])>policy.zero_current_tolerance_A or not same_interval(last,following,policy):
        reasons.append('cutoff_stop_not_observed')
    if crossing is not None and crossing[0]!=len(discharge)-1:reasons.append('continued_discharge_after_first_cutoff')
    previous=rows[first['source_row']-2] if first['source_row']>=2 else None
    if previous is None or previous['I'] is None or not same_interval(previous,first,policy):reasons.append('discharge_onset_not_bracketed')
    if previous is not None and (abs(previous['I'] or 0)>policy.zero_current_tolerance_A or previous['issues']):reasons.append('discharge_onset_prior_not_valid_rest')
    endpoint_estimate=None
    interval_count=0
    if crossing is not None and previous is not None and previous['I'] is not None and first['I'] is not None and same_interval(previous,first,policy):
        crossing_index,a,b=crossing
        prefix=[previous]+discharge[:crossing_index]
        fractions=(a['V']-policy.lower_V)/(a['V']-b['V'])
        pairs=list(zip(prefix,prefix[1:]))
        if all(same_interval(x,y,policy) and x['I'] is not None and y['I'] is not None for x,y in pairs) and same_interval(a,b,policy) and a['I'] is not None and b['I'] is not None:
            endpoint_estimate=sum(integration(x,y) for x,y in pairs)+integration(a,b,fractions)
            interval_count=len(pairs)+1
        cutoff_t=a['time']+fractions*(b['time']-a['time'])
        out['boundaries']={'onset_last_pre_record':reference(previous),'onset_first_discharge_record':reference(first),
            'onset_time_bracket_s':[previous['time'],first['time']], 'physical_onset_time_s':None,
            'integration_start_estimate_s':previous['time'],'onset_reconstruction':'Linear measured-current transition across the onset bracket',
            'cutoff_above_record':reference(a),'cutoff_at_or_below_record':reference(b),
            'cutoff_time_bracket_s':[a['time'],b['time']],'physical_first_cutoff_time_s':None,
            'cutoff_time_linear_estimate_s':cutoff_t,'cutoff_fraction':fractions,
            'cutoff_reconstruction':'Linear voltage and current inside the first observed crossing interval',
            'observed_post_cutoff_stop_record':reference(following),
            'boundary_charge_uncertainty_scope':{
                'onset_conditional_charge_span_Ah':max(abs(previous['I']),abs(first['I']))*(first['time']-previous['time'])/3600,
                'cutoff_conditional_charge_span_Ah':max(abs(a['I']),abs(b['I']))*(b['time']-a['time'])/3600,
                'assumptions':'Only an envelope conditional on current staying within measured endpoint extrema and no hidden pulse; not a proven bound',
                'sensor_calibration_error_Ah':None,'between_record_quadrature_error_Ah':None,
                'true_first_crossing_assumptions':'Continuity and no unobserved earlier crossing; not established from sampled data'}}
        selected=[previous]+discharge[:crossing_index+1]
        for x,y in zip(selected,selected[1:]):
            if any(x[k] is None or y[k] is None for k in ('charge_Ah','discharge_Ah')):
                reasons.append('instrument_capacity_counter_missing')
                break
            if y['charge_Ah']<x['charge_Ah']-policy.counter_tolerance_Ah or y['discharge_Ah']<x['discharge_Ah']-policy.counter_tolerance_Ah:
                reasons.append('instrument_capacity_counter_reset')
                break
        if previous['discharge_Ah'] is not None and a['discharge_Ah'] is not None and b['discharge_Ah'] is not None:
            counter=a['discharge_Ah']+fractions*(b['discharge_Ah']-a['discharge_Ah'])-previous['discharge_Ah']
            out['counter_crosscheck']={'linear_boundary_delta_Ah':counter,
                'last_record_delta_Ah':b['discharge_Ah']-previous['discharge_Ah'],
                'estimate_minus_counter_Ah':endpoint_estimate-counter if endpoint_estimate is not None else None,
                'independent_truth':False,'meaning':'Instrument cumulative throughput may share the current sensor; comparison is not capacity accuracy validation'}
            span=out['boundaries']['boundary_charge_uncertainty_scope']
            recognition_slack=max(1e-6,span['onset_conditional_charge_span_Ah']+span['cutoff_conditional_charge_span_Ah'])
            out['counter_crosscheck']['engineering_consistency_slack_Ah']=recognition_slack
            out['counter_crosscheck']['slack_scope']='Recognition guard only, not metrological accuracy tolerance or certified error bound'
            if endpoint_estimate is not None and abs(endpoint_estimate-counter)>recognition_slack:
                reasons.append('counter_crosscheck_outside_conditional_sampling_span')
    out['interval_count']=interval_count
    out['protocol_capacity_linear_estimate_Ah']=endpoint_estimate
    out['reasons']=list(dict.fromkeys(reasons))
    if not out['reasons'] and endpoint_estimate is not None:
        out['status']='computed'
        out['actual_capacity_Ah']=endpoint_estimate
    elif not out['reasons']:out['reasons']=['capacity_interval_not_computable']
    out['capacity_scope']='Observed fixed-protocol capacity estimate reconstructed from measured current; no exact physical capacity, sensor certificate or lifecycle label'
    return out


def scan_csv(path, nominal_capacity_Ah, vendor_current_sign, policy=None):
    path=Path(path)
    policy=policy or Policy()
    try:before=sha256(path)
    except OSError as error:
        return {'schema_version':1,'status':'unknown','actual_capacity_Ah':None,
            'reasons':['raw_file_unavailable:'+type(error).__name__],'raw_sha256':None,
            'rows':0,'raw_unchanged':None,'protocol_attempts':[],
            'no_fit':True,'heldout_tuning':False,'scientific_external_acceptance_passed':False,'D02_complete':False}
    nominal=finite(nominal_capacity_Ah)
    try:rows,errors=read_rows(path,vendor_current_sign)
    except (OSError,UnicodeError,csv.Error) as error:
        rows,errors=[],['raw_CSV_unreadable:'+type(error).__name__]
    if policy!=Policy():errors.append('fixed_policy_revision_mismatch')
    if nominal is None or nominal<=0:errors.append('invalid_nominal_capacity_metadata')
    if vendor_current_sign not in ('positive_charge','positive_discharge'):errors.append('current_sign_not_verified')
    result={'schema_version':1,'status':'unknown','actual_capacity_Ah':None,'reasons':errors,
        'raw_sha256':before,'rows':len(rows),'units':{'source_time':'s','source_current':'A','source_voltage':'V','source_capacity':'Ah','source_temperature':'degC','canonical_temperature':'K'},
        'canonical_current_sign':'positive_discharge','vendor_current_sign':vendor_current_sign,
        'nominal_capacity_Ah':nominal,'policy':asdict(policy),'protocol_attempts':[],
        'no_fit':True,'heldout_tuning':False,'scientific_external_acceptance_passed':False,'D02_complete':False}
    if not errors:
        blocks=blocks_from(rows)
        result['time_epoch_count']=1+max((r['epoch'] for r in rows),default=0)
        result['source_issue_counts']={issue:sum(issue in r['issues'] for r in rows)
            for issue in sorted({issue for r in rows for issue in r['issues']})}
        result['all_contiguous_cycle_step_blocks']=len(blocks)
        for index,block in enumerate(blocks):
            valid=[r['I'] for r in block['rows'] if r['I'] is not None]
            duration=block['rows'][-1]['time']-block['rows'][0]['time'] if block['rows'][-1]['time'] is not None and block['rows'][0]['time'] is not None else None
            if (len(block['rows'])>=2 and duration is not None and duration+policy.clock_recognition_tolerance_s>=policy.minimum_diagnostic_discharge_s
                and valid and max(valid)>policy.zero_current_tolerance_A and all(i>=-policy.zero_current_tolerance_A for i in valid)):
                result['protocol_attempts'].append(attempt(blocks,index,rows,nominal,policy))
        completed=[a for a in result['protocol_attempts'] if a['status']=='computed']
        if completed:
            # Multiple independent protocol estimates are retained, never averaged.
            result['status']='computed'
            result['actual_capacity_Ah']=completed[0]['actual_capacity_Ah'] if len(completed)==1 else None
            result['complete_protocol_count']=len(completed)
            result['reasons']=[] if len(completed)==1 else ['multiple_complete_protocols_use_per_protocol_results']
        else:
            result['reasons']=sorted({reason for a in result['protocol_attempts'] for reason in a['reasons']}) or ['no_discharge_protocol_candidate']
        result['measured_throughput_Ah']=result['protocol_attempts'][0]['measured_throughput_Ah'] if result['protocol_attempts'] else None
    result['raw_unchanged']=sha256(path)==before
    if not result['raw_unchanged']:
        result.update(status='unknown',actual_capacity_Ah=None,reasons=['raw_changed_during_read'])
    return result
