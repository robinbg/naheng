"""Pure saved-report/aggregate calibration. No raw scan or actual worker spawn."""
from pathlib import Path
from datetime import datetime,timezone
import copy,hashlib,importlib.util,io,json,sys,types,unittest
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
STAGE=ROOT/'artifacts/handoff/d02-capacity-public-entry-20261014-a'
OLD=ROOT/'artifacts/handoff/d02-capacity-protocol-20261014-a'
sys.path.insert(0,str(ROOT/'src'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
spec=importlib.util.spec_from_file_location('naheng.runtime.independent_public_capacity_candidate',STAGE/'runtime/public_capacity_session.py')
session=importlib.util.module_from_spec(spec);sys.modules[spec.name]=session;spec.loader.exec_module(session)
split_path=ROOT/'data/splits/zenodo13836819-eight-provenance-20261013-c.json'
split=read(split_path);saved=read(OLD/'actual-frozen-report.json')
before={p.relative_to(ROOT).as_posix():sha(p) for p in [
    STAGE/'runtime/public_capacity_session.py',STAGE/'experiments/public_capacity.py',STAGE/'handoff.json',
    OLD/'protocol_capacity_measurement.py',OLD/'actual-frozen-report.json',split_path]}
for m in split['members']:
    p=ROOT/m['view_manifest']['path'];before[p.relative_to(ROOT).as_posix()]=sha(p)
base={'phase':'capacity','exit_code':0,'execution_completed':True,'D02_complete':False,
      'scientific_external_acceptance_passed':False,'new_model_fits':0,'heldout_tuning':False,
      'new_independent_scientific_N':0,'source_current':True,'protected_inputs_unchanged':True,
      'scanner_sha256':session.REVIEWED_SCANNER_SHA256,'code_hash':'review-digest','code_hash_after':'review-digest',
      'complete_member_count':len(split['members']),'original_row_count':split['total_rows'],
      'frozen_role_row_counts':split['role_row_counts'],'frozen_cohort_id':split['cohort_id'],
      'manifest_sha256':sha(split_path),'unique_raw_content_count':7,
      'members':copy.deepcopy(saved['members']),'computed_file_count':5,'unknown_file_count':3,
      'registered_bindings':{m['raw']['path']:m['raw']['sha256'] for m in split['members']}}
for m in split['members']:base['registered_bindings'][m['view_manifest']['path']]=m['view_manifest']['sha256']
base['registered_bindings'][split_path.relative_to(ROOT).as_posix()]=sha(split_path)
for key in ['catalog_ref','policy_ref']:
    ref=split[key];base['registered_bindings'][ref['path']]=ref['sha256']
for ref in split['protected_refs']:base['registered_bindings'][ref['path']]=ref['sha256']
base['registered_bindings'].update(split['public_source_hashes'])
for m in split['members']:
    ref=m['observations'];base['registered_bindings'][ref['path']]=ref['sha256']
for path in ['data/manifests/public_sodium.yaml','data/manifests/sources.yaml']:
    base['registered_bindings'][path]=sha(ROOT/path)
for source in read(ROOT/'data/manifests/sources.yaml')['sources']:
    if source['source_id'] in {m['source_id'] for m in split['members']}:
        ref=source['author_metadata'];base['registered_bindings'][ref['path']]=ref['sha256']
base['registered_bindings']['src/naheng/data/protocol_capacity_measurement.py']=session.REVIEWED_SCANNER_SHA256
base.update(module_source_sha256=sha(STAGE/'experiments/public_capacity.py'),
    source_provenance='public_measurement',physical_independence_status=split['physical_independence_status'],
    IID=split['IID'],independent_physical_cell_count=split['confirmed_independent_physical_cells'])
computed_index=next(i for i,m in enumerate(base['members']) if m['status']=='computed')
unknown_index=next(i for i,m in enumerate(base['members']) if m['status']=='unknown')
cases=[]
def case(name,mutate,expected=False):
    report=copy.deepcopy(base);mutate(report)
    try:actual=session.validate_capacity_completion(report,split,'review-digest',0);error=None
    except Exception as exc:actual=None;error=type(exc).__name__+': '+str(exc)
    cases.append({'name':name,'expected_accepted':expected,'actual_accepted':actual,
                  'guard_met':actual is expected,'error':error})
case('valid_full_saved_shape',lambda r:None,True)
def valid_multiple(r):
    m=r['members'][computed_index]
    completed=next(a for a in m['protocol_attempts'] if a['status']=='computed')
    m['protocol_attempts'].append(copy.deepcopy(completed))
    m['complete_protocol_count']=2;m['actual_capacity_Ah']=None
    m['reasons']=['multiple_complete_protocols_use_per_protocol_results']
case('valid_multiple_protocols_null_scalar',valid_multiple,True)
for name,value in [('computed_null',None),('computed_nan',float('nan')),('computed_inf',float('inf')),
                   ('computed_string','10.4'),('computed_boolean',True)]:
    case(name,lambda r,v=value:r['members'][computed_index].__setitem__('actual_capacity_Ah',v))
case('computed_capacity_missing',lambda r:r['members'][computed_index].pop('actual_capacity_Ah'))
case('computed_negative_capacity',lambda r:r['members'][computed_index].__setitem__('actual_capacity_Ah',-1.))
case('computed_no_complete_protocol',lambda r:r['members'][computed_index].__setitem__('protocol_attempts',[]))
case('computed_complete_count_wrong',lambda r:r['members'][computed_index].__setitem__('complete_protocol_count',2))
case('computed_fake_attempt_unknown',lambda r:next(a for a in r['members'][computed_index]['protocol_attempts'] if a['status']=='computed').__setitem__('status','unknown'))
case('computed_attempt_value_disagrees',lambda r:next(a for a in r['members'][computed_index]['protocol_attempts'] if a['status']=='computed').__setitem__('actual_capacity_Ah',1.))
case('computed_attempt_nonfinite',lambda r:next(a for a in r['members'][computed_index]['protocol_attempts'] if a['status']=='computed').__setitem__('actual_capacity_Ah',float('nan')))
case('unknown_zero_filled',lambda r:r['members'][unknown_index].__setitem__('actual_capacity_Ah',0.))
case('unit_current_changed',lambda r:r['members'][computed_index]['units'].__setitem__('source_current','mA'))
case('unit_temperature_changed',lambda r:r['members'][computed_index]['units'].__setitem__('canonical_temperature','degC'))
case('canonical_current_sign_reversed',lambda r:r['members'][computed_index].__setitem__('canonical_current_sign','positive_charge'))
case('vendor_sign_no_longer_matches_view',lambda r:r['members'][computed_index].__setitem__('vendor_current_sign','positive_discharge'))
case('diagnostic_protocol_changed',lambda r:r['members'][computed_index]['policy'].__setitem__('discharge_C_rate',.1))
case('diagnostic_protocol_ID_changed',lambda r:r['members'][computed_index]['policy'].__setitem__('protocol_id','different_protocol'))
case('frozen_source_protocol_changed',lambda r:r['members'][computed_index].__setitem__('source_protocol',{}))
case('nominal_source_metadata_changed',lambda r:r['members'][computed_index].__setitem__('nominal_capacity_Ah',.003))
case('source_provenance_relabelled',lambda r:r['members'][computed_index].__setitem__('source_provenance','synthetic'))
case('manifest_SHA_wrong',lambda r:r.__setitem__('manifest_sha256','wrong'))
case('raw_registered_binding_wrong',lambda r:r['registered_bindings'].__setitem__(split['members'][computed_index]['raw']['path'],'wrong'))
case('unique_content_count_wrong',lambda r:r.__setitem__('unique_raw_content_count',8))
case('row_count_wrong',lambda r:r['members'][computed_index].__setitem__('rows',0))
case('role_changed',lambda r:r['members'][computed_index].__setitem__('role','test'))
case('duplicate_member',lambda r:r['members'].__setitem__(1,copy.deepcopy(r['members'][0])))
case('D02_promoted',lambda r:r.__setitem__('D02_complete',True))
case('raw_SHA_wrong',lambda r:r['members'][computed_index].__setitem__('raw_sha256','wrong'))
aggregate=[]
for ve,ce,elapsed in [(2,0,50),(1,0,50),(2,1,50),(0,0,50),(2,0,1801),(2,0,float('nan'))]:
    v={'exit_code':ve,'execution_completed':ve!=1,'material_mapping':'UNKNOWN','nested':{'unchanged':[1,2]}}
    c={'exit_code':ce,'execution_completed':ce!=1};v0=copy.deepcopy(v);c0=copy.deepcopy(c)
    a=session.aggregate_public_data_phases(v,c,elapsed)
    aggregate.append({'voltage_exit':ve,'capacity_exit':ce,'elapsed_repr':repr(elapsed),
        'aggregate_exit':a['exit_code'],'completed':a['execution_completed'],
        'budget_exceeded':a['aggregate_budget_exceeded'],'inputs_unmutated':v==v0 and c==c0,
        'phase_original_dicts_retained':a['phases']['voltage']==v0 and a['phases']['capacity']==c0,
        'D02_complete':a['D02_complete']})
# Candidate runtime exit projection is executed from its exact AST, so no
# Popen/resource/API calls happen. It exposes a native1 being projected to2.
import ast
parsed=ast.parse((STAGE/'runtime/public_capacity_session.py').read_text(encoding='utf-8'))
fn=next(n for n in parsed.body if isinstance(n,ast.FunctionDef) and n.name=='run_public_capacity')
assignment=next(n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='actual_code' for t in n.targets))
ns={'code':1,'complete':False}
exec(compile(ast.Module(body=[assignment],type_ignores=[]),'candidate_exit_projection','exec'),ns)
native_projection={'simulated':True,'actual_native_worker_exit':1,'completion_validated':False,
    'candidate_returned_phase_exit':ns['actual_code'],'expected_returned_phase_exit':1,
    'worker_processes_spawned':0,'guard_met':ns['actual_code']==1}
after={name:sha(ROOT/name) for name in before}
result={'created_at_utc':datetime.now(timezone.utc).isoformat(),'mode':'pure_saved_report_and_AST_exit_projection_calibration',
    'source_before':before,'source_after':after,'source_unchanged':before==after,
    'cases':cases,'case_count':len(cases),'guard_failures':[c['name'] for c in cases if not c['guard_met']],
    'aggregate_cases':aggregate,'native1_projection':native_projection,
    'computed_member_shape':{'required_numeric':'Every computed attempt finite nonnegative int/float capacity, excludes bool; scalar tied to single complete attempt; legal multiple complete protocols preserve scalar null and per-protocol values',
        'units_example':base['members'][computed_index]['units'],
        'policy_example':base['members'][computed_index]['policy'],
        'current_signs':{k:base['members'][computed_index][k] for k in ['vendor_current_sign','canonical_current_sign']},
        'protocol_binding':'source_protocol equals frozen member protocol; diagnostic policy/ID fixed by reviewed scanner',
        'source_bindings':'raw/view/observations/split/catalog/policy/protected refs/public source hashes/active/source registry/author metadata/reviewed scanner; source_id/author_group/role/nominal/rows/SHA and derived unique content count'},
    'non_gate':'Post-stop temperature observation remains nongate; no new raw or boundary requirement',
    'raw_replays':0,'worker_processes_spawned':0,'Lean_invocations':0,'UI_tested':False,
    'scope':'Wrapper completion/aggregation guard calibration only, no public CLI acceptance',
    'exit_code':1 if any(not c['guard_met'] for c in cases) or not native_projection['guard_met'] else 0}
(OUT/'guard-results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'positive-full-report.json').write_text(json.dumps(base,indent=2,ensure_ascii=False),encoding='utf-8')
multiple=copy.deepcopy(base);valid_multiple(multiple)
(OUT/'positive-multiple-report.json').write_text(json.dumps(multiple,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps({'exit_code':result['exit_code'],'cases':len(cases),'guard_failures':result['guard_failures'],
    'native1_projection':native_projection,'source_unchanged':before==after}))
raise SystemExit(result['exit_code'])
