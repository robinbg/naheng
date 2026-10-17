"""Public-ready bounded full-policy training entry; no heldout selection."""
from dataclasses import asdict
import json
from pathlib import Path
import time
import uuid
from naheng.runtime.artifacts import atomic_json, code_hash
from naheng.estimation.calibration_session import run_calibration
from .constrained_bo import Search, Limits, BudgetExhausted, digest
from .operational_oracle import OperationalOracle, SOURCE_ID, implementation_hashes, sha
from .policy_space import BOUNDS, UNITS, SPACE_ID, fixed_world


def run_pilot(root, out=None, *, profile='pilot', resume=False, limits=None, calibration_dir=None):
    root=Path(root).resolve()
    if profile!='pilot':raise ValueError('Only the declared bounded pilot profile is supported')
    limits=limits or Limits()
    if type(limits) is not Limits:raise ValueError('Explicit typed limits required')
    started=time.monotonic()
    out=Path(out or root/'artifacts'/('optimize-full-policy-'+uuid.uuid4().hex[:8])).resolve()
    if not out.is_relative_to(root/'artifacts'):raise ValueError('Project-owned artifact output required')
    if resume:
        saved=json.loads((out/'protocol.json').read_text(encoding='utf-8'))
        calibration_dir=Path(calibration_dir or saved['calibration_packet'])
    else:
        out.mkdir(parents=True,exist_ok=False)
        if calibration_dir is None:
            calibration_dir=root/'artifacts/calibration'/('learning-current-'+uuid.uuid4().hex[:12])
            calibration=run_calibration(root,Path(__file__).parent/'calibration_request.json',calibration_dir)
            atomic_json(out/'calibration-preflight.json',calibration)
            if calibration['exit_code']!=0:
                result={'exit_code':2,'status':'blocked_calibration','calibration':calibration,'out':str(out)}
                atomic_json(out/'result.json',result);return result
    calibration_dir=Path(calibration_dir).resolve()
    protocol={'schema_version':1,'space_id':SPACE_ID,'bounds':BOUNDS,'units':UNITS,
        'sources':{SOURCE_ID:'train','heldout-full-policy-2026101411':'test'},'limits':asdict(limits),
        'implementations':implementation_hashes(),'code_hash':code_hash(root),'world':fixed_world(),
        'calibration_packet':str(calibration_dir),'calibration_manifest_sha256':sha(calibration_dir/'manifest.json'),
        'scope':'Nine-coordinate policy in one fixed synthetic world; computational effort levels only',
        'unknown_handling':'Unknown/refused/incomplete executions consume budget but never receive numeric fit labels',
        'scientific_N_added':0,'risk_certificate':False,'physical_reference_calls':0,'A03_complete':False}
    if resume:
        if digest(saved)!=digest(protocol):raise ValueError('Resume source, world, or protocol changed')
        expected=Search(BOUNDS,protocol['sources'],limits)
        search=Search.restore(out/'checkpoint.json',expected.protocol_sha256)
    else:
        atomic_json(out/'protocol.json',protocol)
        search=Search(BOUNDS,protocol['sources'],limits)
        search.previous_wall=time.monotonic()-started
    oracle=OperationalOracle(out/'cases',packet=calibration_dir,world=protocol['world'])
    if search.pending:
        pending=next(iter(search.pending.values()))
        case=out/'cases'/(f"{pending['ordinal']:03d}-"+pending['fidelity'])
        response_path=case/'response.json'
        if response_path.is_file():
            response=json.loads(response_path.read_text(encoding='utf-8'))
            if response['status']=='completed' and sha(case/'result.json')!=response['evidence_sha256']:
                raise ValueError('Interrupted execution evidence no longer matches')
        else:
            response={'status':'unknown','utility':None,'constraint_margin':None,'cost_s':None,'source_id':SOURCE_ID,
                'run_id':pending['reservation_id'],'evidence_sha256':sha(out/'checkpoint.json'),
                'reason':'Interrupted execution has no completed response; no target invented'}
        search.tell(pending,response);search.checkpoint(out/'checkpoint.json')
    while True:
        if (out/'cancel').exists():
            atomic_json(out/'stopped.json',{'status':'cancelled','completed_queries':len(search.events)})
            return {'exit_code':2,'status':'cancelled','out':str(out)}
        try:request=search.ask()
        except BudgetExhausted:break
        search.checkpoint(out/'checkpoint.json')
        atomic_json(out/'progress.json',{'stage':'evaluating','completed':len(search.events),
            'fidelity':request['fidelity'],'elapsed_s':search.elapsed(),'dimensions':len(BOUNDS)})
        try:response=oracle.evaluate(request)
        except Exception as error:
            response={'status':'unknown','utility':None,'constraint_margin':None,'cost_s':None,'source_id':SOURCE_ID,
                'run_id':request['reservation_id'],'evidence_sha256':sha(out/'checkpoint.json'),'reason':repr(error)}
        search.tell(request,response);search.checkpoint(out/'checkpoint.json')
    search._fit();best=search.best()
    expected_queries=limits.initial_points+limits.iterations
    source_check_error=None
    try:
        source_unchanged=(code_hash(root)==protocol['code_hash'] and implementation_hashes()==protocol['implementations']
            and sha(calibration_dir/'manifest.json')==protocol['calibration_manifest_sha256']
            and digest(json.loads((out/'protocol.json').read_text(encoding='utf-8')))==digest(protocol))
    except (OSError,ValueError) as error:
        source_unchanged=False;source_check_error=repr(error)
    elapsed=search.elapsed()
    within_wall_budget=elapsed<=limits.wall_s
    complete=len(search.events)==expected_queries and best is not None and within_wall_budget and source_unchanged
    result={'exit_code':0 if complete else 2,
        'status':'completed' if complete else 'budget_exhausted' if not within_wall_budget else 'source_changed' if not source_unchanged else 'insufficient_completed_evidence',
        'within_wall_budget':within_wall_budget,'source_unchanged':source_unchanged,'source_check_error':source_check_error,
        'requested_queries':expected_queries,'actual_reserved_queries':len(search.events),
        'completed_results':sum(e['result']['status']=='completed' for e in search.events),
        'unknown_results':sum(e['result']['status']!='completed' for e in search.events),
        'high_calls':sum(e['fidelity']=='high' for e in search.events),'best_training_candidate':best if complete else None,
        'diagnostic_best_training_candidate':best,
        'utility_model':search.utility.state(),'constraint_model':search.constraint.state(),
        'elapsed_s':elapsed,'protocol_sha256':sha(out/'protocol.json'),'checkpoint_sha256':sha(out/'checkpoint.json'),
        'scientific_N_added':0,'risk_certificate':False,'physical_reference_calls':0,'A03_complete':False,
        'scope':protocol['scope'],'out':str(out)}
    atomic_json(out/'result.json',result)
    atomic_json(out/'frozen-training-selection.json',{'best':best if complete else None,'diagnostic_best':best,'selection_admissible':complete,'checkpoint_sha256':result['checkpoint_sha256'],
        'heldout_results_seen':False,'risk_certificate':False})
    return result
