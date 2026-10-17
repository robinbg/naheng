"""Real saved S04 result and explicit bad periodic metadata; no new simulation."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

if os.environ.get('NAHENG_FINANCE_CANDIDATE'):
    spec=importlib.util.spec_from_file_location('finance_periodic_candidate',os.environ['NAHENG_FINANCE_CANDIDATE'])
    F=importlib.util.module_from_spec(spec);sys.modules[spec.name]=F;spec.loader.exec_module(F)
else:
    from naheng.economics import lifecycle as F

ROOT=Path(os.environ.get('NAHENG_FINANCE_ROOT',Path(__file__).resolve().parents[2]))
SAVED=ROOT/'artifacts/lifecycle_validation/compare_cycle_maps.json'


def saved():
    raw=SAVED.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='46e623cf1d3abfa5035ea9b0265e5814bb52035024a188d0ea34556ad3c178cb'
    return json.loads(raw)


def endpoints(result,mode):
    def assets(rows,part):
        return tuple(F.AssetEndpoint('cell-'+str(i+1)+'-g0',row['protocol'].get('capacity_C'),
            row.get('pristine_capacity_C'),None,str(SAVED)+'#'+mode+'/'+part+'/'+str(i),'unknown')
            for i,row in enumerate(rows))
    economic=result['economics']
    initial=F.TerminalState(0.,'initial',None,economic['initial_stored_energy_probe'].get('energy_J'),
        assets(result['trace'][0]['cells'],'initial'),str(SAVED)+'#'+mode+'/initial')
    final=F.TerminalState(result['elapsed_s'],'right_censored',None,economic['final_stored_energy_probe'].get('energy_J'),
        assets(result['final_protocol_diagnostics'],'final'),str(SAVED)+'#'+mode+'/final',
        'conditional_projection' if result['macro_projected_ledger'] else 'actual')
    assumption=F.FinancialAssumptions('explicit_synthetic_saved_fixture','common_terminal_review',result['elapsed_s'])
    return dict(run_id='saved-'+mode,initial=initial,final=final,assumptions=assumption,source_ref=str(SAVED)+'#'+mode)


def adapted(result,mode):
    return F.from_lifecycle_result(result,**endpoints(result,mode)).to_dict()


def test_genuine_saved_fine_and_macro_keep_original_cash_and_projected_energy():
    raw=saved();fine=adapted(raw['fine'],'fine');macro=adapted(raw['macro'],'macro')
    assert len(fine['actual_energy_entries'])==24 and fine['projected_cash_CNY']==0
    assert fine['realized_cash_CNY']==pytest.approx(6.286906741555551e-7,abs=1e-18)
    assert len(macro['projected_energy_entries'])==4 and macro['realized_cash_CNY']==0
    assert macro['projected_cash_CNY']==pytest.approx(raw['macro']['economics']['macro_projected_totals']['net_cashflow'],abs=1e-18)
    assert [row['energy_J'] for row in macro['projected_energy_entries']]==[row['energy_J'] for row in raw['macro']['macro_projected_ledger']]
    assert all('per_cycle_energy_J' not in row for row in macro['projected_energy_entries'])
    assert all(row['classification']=='projected' for row in macro['projected_energy_entries'])


def test_saved_macro_periodic_support_is_source_layout_not_contiguous_aggregate_box():
    macro=adapted(saved()['macro'],'macro');rows=macro['projected_energy_entries']
    assert rows[0]['exposure_intervals_s']==[[0.,2.],[4.,6.],[8.,10.],[12.,14.],[16.,18.],[20.,22.]]
    assert rows[1]['exposure_intervals_s']==[[2.,4.],[6.,8.],[10.,12.],[14.,16.],[18.,20.],[22.,24.]]
    assert rows[0]['duration_s']==12 and rows[0]['last_exposure_end_s']==22
    assert rows[1]['duration_s']==12 and rows[1]['last_exposure_end_s']==24
    support=sorted(interval for row in rows for interval in row['exposure_intervals_s'])
    assert support==[[float(i),float(i+2)] for i in range(0,48,2)]
    assert sum(b-a for a,b in support)==48.
    assert all(first[1]==second[0] for first,second in zip(support,support[1:]))


@pytest.mark.parametrize('field,value',[('cycle_period_s',0.),('cycle_period_s',3.),('phase_offset_s',1.),
    ('cycle_count',5),('cycle_count',True),('aggregation','unknown_layout')])
def test_changed_source_period_count_offset_or_aggregation_is_rejected(field,value):
    raw=deepcopy(saved()['macro']);raw['phases'][0][field]=value
    with pytest.raises(ValueError):adapted(raw,'macro')


def test_changed_cycle_indices_cannot_relabel_missing_or_repeated_periodic_cycles():
    raw=deepcopy(saved()['macro'])
    for phase in raw['phases'][:2]:phase['cycle']=1
    for row in raw['macro_projected_ledger'][:2]:row['cycle_start']=1
    with pytest.raises(ValueError,match='cycle'):adapted(raw,'macro')


def test_periodic_phase_pair_anchor_and_ledger_metadata_must_match_source():
    raw=deepcopy(saved()['macro']);raw['phases'][1]['start_s']+=.25
    with pytest.raises(ValueError,match='anchor'):adapted(raw,'macro')
    raw=deepcopy(saved()['macro']);raw['macro_projected_ledger'][0]['cycle_period_s']=999.
    with pytest.raises(ValueError,match='metadata'):adapted(raw,'macro')


def test_forged_exposure_array_cannot_hide_overlap_or_convert_aggregate_to_contiguous():
    raw=saved()['macro'];good=adapted(raw,'macro');params=endpoints(raw,'macro');params.pop('source_ref')
    altered=deepcopy(good['projected_energy_entries'][0]);altered['exposure_intervals_s']=[[0.,12.]]
    with pytest.raises(ValueError,match='Exposure'):
        F.settle_lifecycle([],**params,projected_entries=(altered,))
    altered=deepcopy(good['projected_energy_entries'][0]);altered['exposure_intervals_s'][1]=[2.,4.]
    with pytest.raises(ValueError,match='Exposure'):
        F.settle_lifecycle([],**params,projected_entries=(altered,))


def test_duplicate_periodic_time_under_alias_is_still_rejected():
    raw=saved()['macro'];good=adapted(raw,'macro');params=endpoints(raw,'macro');params.pop('source_ref')
    original=good['projected_energy_entries'][0];alias={**original,'execution_id':'alias-new-id'}
    with pytest.raises(ValueError,match='Overlapping'):
        F.settle_lifecycle([],**params,projected_entries=(original,alias))


def test_actual_and_periodic_projection_support_check_union_not_bounding_boxes():
    raw=saved();fine=adapted(raw['fine'],'fine');macro=adapted(raw['macro'],'macro')
    params=endpoints(raw['macro'],'macro');params.pop('source_ref');params['run_id']='same-accounting-fixture'
    projection={**macro['projected_energy_entries'][0],'run_id':params['run_id']}
    actual_charge={**fine['actual_energy_entries'][1],'run_id':params['run_id']}
    actual_discharge={**fine['actual_energy_entries'][0],'run_id':params['run_id']}
    safe=F.settle_lifecycle((actual_charge,),**params,projected_entries=(projection,)).to_dict()
    assert safe['realized_cash_CNY']==actual_charge['net_cashflow']
    assert safe['projected_cash_CNY']==projection['net_cashflow']
    with pytest.raises(ValueError,match='intervals overlap'):
        F.settle_lifecycle((actual_discharge,),**params,projected_entries=(projection,))


def test_missing_period_and_false_actual_aggregate_are_not_accepted():
    raw=deepcopy(saved()['macro']);del raw['phases'][0]['cycle_period_s']
    with pytest.raises(ValueError):adapted(raw,'macro')
    raw=deepcopy(saved()['macro']);raw['phases'][0]['execution_mode']='exact_integration'
    with pytest.raises(ValueError):adapted(raw,'macro')
