# Public-layout adapter; the reviewed D assertions below are unchanged.
from pathlib import Path
import importlib.util,sys
_spec=importlib.util.spec_from_file_location('evidence_report',Path(__file__).resolve().parents[2]/'tools/evidence_report.py')
_module=importlib.util.module_from_spec(_spec);sys.modules['evidence_report']=_module;_spec.loader.exec_module(_module)
from copy import deepcopy
import hashlib,json
from pathlib import Path
import pytest
from evidence_report import EvidenceError,build_report,compile_data

@pytest.fixture
def example(tmp_path):
    (tmp_path/'artifacts').mkdir();source=tmp_path/'artifacts/source.json'
    source.write_text(json.dumps({'status':'unknown','category':'synthetic','run_id':'r-1','code_hash':'a'*64,'queries':36,'profit':None}))
    entry={'id':'q','task':'A03','title':'example','category':'synthetic','category_basis':{'pointer':['category'],'equals':'synthetic'},
        'path':'artifacts/source.json','sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'outcome':{'kind':'status','pointer':['status']},
        'metrics':[{'name':'queries','pointer':['queries'],'unit':'attempts','role':'attempt_count'}],
        'lineage':{'run_id':['run_id'],'code_hash':['code_hash']}}
    selection={'schema_version':1,'draft':True,'title':'<script>alert(1)</script>','entries':[entry],
        'claims':[{'id':'c','text':'<img src=x onerror=alert(1)>','evidence_ids':['q'],'limitations':'not a completed experiment'}],
        'required_incomplete':['X02','X03','X04','R00']}
    frozen=tmp_path/'artifacts/list.json';frozen.write_text(json.dumps(selection));return tmp_path,source,selection,frozen

def freeze(frozen,selection):frozen.write_text(json.dumps(selection))

def test_unknown_and_attempts_never_become_scientific_n_or_success(example):
    root,source,s,frozen=example;out=root/'artifacts/report';build_report(root,frozen,out)
    data=json.loads((out/'tables.json').read_text());assert data['rows'][0]['outcome']['state']=='unknown'
    assert data['independent_scientific_N'] is None and data['comparative_advantage'] is None
    assert data['rows'][0]['metrics'][0]['value']==36 and data['claims'][0]['assessment']=='not_adjudicated'
    assert data['R01_complete'] is False and data['release_pass'] is False
    assert data['rows'][0]['lineage']['run_id']['value']=='r-1'
    assert b'<script>' not in (out/'report.html').read_bytes() and b'<img' not in (out/'report.html').read_bytes()
    assert (out/'selection.json').read_bytes()==frozen.read_bytes()

@pytest.mark.parametrize('edit',['hash','category','missing_pointer','duplicate_id','duplicate_source','unknown_claim','nan','overflow','oversize_metrics'])
def test_bad_inputs_refuse_without_output(example,edit):
    root,source,s,frozen=example;e=s['entries'][0]
    if edit=='hash':e['sha256']='0'*64
    if edit=='category':e['category_basis']['equals']='public_measurement'
    if edit=='missing_pointer':e['metrics'][0]['pointer']=['missing']
    if edit=='duplicate_id':s['entries'].append(deepcopy(e))
    if edit=='duplicate_source':
        extra=deepcopy(e);extra['id']='duplicate';s['entries'].append(extra)
    if edit=='unknown_claim':s['claims'][0]['evidence_ids']=['missing']
    if edit=='nan':source.write_text('{"status":NaN}');e['sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    if edit=='overflow':source.write_text('{"category":"synthetic","unused":1e9999}');e['sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    if edit=='oversize_metrics':e['metrics']*=65
    freeze(frozen,s);out=root/'artifacts/report'
    with pytest.raises(EvidenceError):build_report(root,frozen,out)
    assert not out.exists()

@pytest.mark.parametrize('path',['../outside.json','C:/secret.json','artifacts/evaluator/raw.json','artifacts/.aws/credentials','artifacts/docs/key.pem','artifacts//x.json'])
def test_private_and_external_inputs_refused(example,path):
    root,_,s,frozen=example;s['entries'][0]['path']=path;freeze(frozen,s)
    with pytest.raises(EvidenceError):build_report(root,frozen,root/'artifacts/report')
    assert not (root/'artifacts/report').exists()

@pytest.mark.parametrize('receipt,state',[({'exit_code':0,'executed':True,'native_exit_code':0,'resource_cleanup_confirmed':True,'timed_out':False},'passed'),({'exit_code':0},'unknown'),({'exit_code':1},'failed'),({'exit_code':2},'blocked'),({'exit_code':None},'unknown'),({'exit_code':0,'timed_out':True},'unknown'),({'exit_code':0,'executed':False},'not_run'),({'exit_code':0,'executed':None},'unknown'),({'exit_code':0,'resource_cleanup_confirmed':False},'unknown')])
def test_command_status_is_limited_to_recorded_outcome(example,receipt,state):
    root,source,s,frozen=example;receipt['category']='synthetic';source.write_text(json.dumps(receipt))
    e=s['entries'][0];e['sha256']=hashlib.sha256(source.read_bytes()).hexdigest();e['outcome']={'kind':'command','pointer':[]};e['metrics']=[];e['lineage']={}
    result=compile_data(root,s);assert result['rows'][0]['outcome']['state']==state
    assert 'Command exit observation' in result['rows'][0]['outcome']['scope']

def test_duplicate_json_keys_rejected(example):
    root,source,s,frozen=example;source.write_text('{"category":"synthetic","category":"public_measurement"}')
    s['entries'][0]['sha256']=hashlib.sha256(source.read_bytes()).hexdigest();freeze(frozen,s)
    with pytest.raises(EvidenceError,match='Duplicate'):build_report(root,frozen,root/'artifacts/report')

def test_existing_output_is_not_replaced(example):
    root,_,s,frozen=example;out=root/'artifacts/report';out.mkdir();(out/'sentinel').write_text('keep')
    with pytest.raises(EvidenceError):build_report(root,frozen,out)
    assert (out/'sentinel').read_text()=='keep'


@pytest.mark.parametrize('field',['executed','native_exit_code','resource_cleanup_confirmed','timed_out'])
@pytest.mark.parametrize('missing',[True,False])
def test_missing_or_null_confirmations_never_pass(field,missing):
    from evidence_report import outcome
    r={'exit_code':0,'executed':True,'native_exit_code':0,'resource_cleanup_confirmed':True,'timed_out':False}
    if missing:r.pop(field)
    else:r[field]=None
    result=outcome(r,{'kind':'command','pointer':[]})
    assert result['state']=='unknown' and result['command_exit_observed']==0

def test_native_mismatch_preserves_both_observed_exit_codes():
    from evidence_report import outcome
    r={'exit_code':0,'executed':True,'native_exit_code':1,'resource_cleanup_confirmed':True,'timed_out':False}
    result=outcome(r,{'kind':'command','pointer':[]})
    assert result['state']=='unknown' and result['command_exit_observed']==0 and result['native_exit_observed']==1
    assert result['native_matches_command'] is False

@pytest.mark.parametrize('code,expected',[(1,'failed'),(2,'blocked')])
def test_old_nonzero_exit_fact_survives_missing_confirmations(code,expected):
    from evidence_report import outcome
    result=outcome({'exit_code':code},{'kind':'command','pointer':[]})
    assert result['state']==expected and result['command_exit_observed']==code
    assert result['execution_confirmed'] is None and result['resource_cleanup_confirmed'] is None

def test_real_legacy_receipt_does_not_claim_execution_cleanup_confirmation():
    from evidence_report import outcome
    path=Path(__file__).resolve().parents[1]/'fixtures/evidence_report/legacy-command.json'
    receipt=json.loads(path.read_text(encoding='utf-8'))
    assert receipt['exit_code']==0 and 'executed' not in receipt and 'resource_cleanup_confirmed' not in receipt
    result=outcome(receipt,{'kind':'command','pointer':[]})
    assert result['state']=='unknown' and result['command_exit_observed']==0
    assert result['execution_confirmed'] is None and result['resource_cleanup_confirmed'] is None
    assert result['log_references']=={key:receipt[key] for key in ('stdout','stderr')}
