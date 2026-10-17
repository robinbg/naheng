from copy import deepcopy
import json
from pathlib import Path
import pytest
from naheng.runtime.public_capacity_session import validate_capacity_completion, aggregate_public_data_phases

ROOT=Path(__file__).resolve().parents[2]
SPLIT=json.loads((ROOT/'data/splits/zenodo13836819-eight-provenance-20261013-c.json').read_text(encoding='utf-8'))
FIXTURES=ROOT/'artifacts/review/d02-public-entry-review-a'

def fixture(name='positive-full-report.json'):
    return json.loads((FIXTURES/name).read_text(encoding='utf-8'))

def valid(report):return validate_capacity_completion(report,SPLIT,report['code_hash'],0)

def test_saved_shape_and_multiple_individual_protocols_remain_valid_diagnostics():
    assert valid(fixture())
    assert valid(fixture('positive-multiple-report.json'))

@pytest.mark.parametrize('value',[None,0,-1,True,'10',float('nan'),float('inf')])
def test_single_capacity_cannot_be_missing_zero_negative_boolean_string_or_nonfinite(value):
    report=fixture();next(m for m in report['members'] if m['status']=='computed')['actual_capacity_Ah']=value
    assert not valid(report)

@pytest.mark.parametrize('field',['units','policy','source_protocol','nominal_capacity_Ah','vendor_current_sign','canonical_current_sign','source_provenance','protocol_attempts','complete_protocol_count'])
def test_computed_member_missing_required_source_or_protocol_evidence_rejected(field):
    report=fixture();next(m for m in report['members'] if m['status']=='computed').pop(field,None)
    assert not valid(report)

@pytest.mark.parametrize('field',['manifest_sha256','registered_bindings','unique_raw_content_count'])
def test_missing_top_source_bindings_rejected(field):
    report=fixture();report.pop(field,None);assert not valid(report)

@pytest.mark.parametrize('field,value',[('actual_capacity_Ah',None),('strict_capacity_certificate',True),('SOC_label',.9),('RUL_label',2)])
def test_attempt_cannot_promote_unknown_label_or_drop_capacity(field,value):
    report=fixture();member=next(m for m in report['members'] if m['status']=='computed')
    attempt=next(a for a in member['protocol_attempts'] if a['status']=='computed');attempt[field]=value
    assert not valid(report)

def test_diagnostic_success_never_overwrites_old_material_mapping_and_scientific_gate():
    old={'exit_code':2,'execution_completed':True,'material_mapping':'UNKNOWN','D02_complete':False}
    saved=deepcopy(old)
    packet=aggregate_public_data_phases(old,{'exit_code':0,'execution_completed':True},160)
    assert old==saved and packet['phases']['voltage']==saved and packet['exit_code']==2
    assert packet['D02_complete'] is False
    failed=aggregate_public_data_phases(old,{'exit_code':1,'execution_completed':False},10)
    assert failed['exit_code']==1 and not failed['execution_completed']
