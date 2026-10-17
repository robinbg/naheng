"""Bounded trusted deterministic capacity phase; aggregate retains original gates."""
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .artifacts import atomic_json, code_hash, sha256_file


from .public_sodium_session import ExtendedLimits

REVIEWED_SCANNER_SHA256='0f5f3e7f60497604c485a1fc430e5386170374b79cdee2933379ed900651e381'


def validate_capacity_completion(report,split,code_digest,worker_exit):
    """Diagnostic completion only; does not override any original scientific gate."""
    if not isinstance(report,dict) or worker_exit!=0:return False
    required={'phase':'capacity','exit_code':0,'execution_completed':True,
        'D02_complete':False,'scientific_external_acceptance_passed':False,
        'new_model_fits':0,'heldout_tuning':False,'new_independent_scientific_N':0,
        'source_current':True,'protected_inputs_unchanged':True,
        'scanner_sha256':REVIEWED_SCANNER_SHA256,'code_hash':code_digest,'code_hash_after':code_digest,
        'complete_member_count':len(split['members']),'original_row_count':split['total_rows'],
        'frozen_role_row_counts':split['role_row_counts'],'frozen_cohort_id':split['cohort_id']}
    if any(report.get(k)!=v or type(report.get(k)) is not type(v) for k,v in required.items()):return False
    from dataclasses import asdict
    import math
    from naheng.data.protocol_capacity_measurement import Policy
    def positive_number(value):
        return type(value) in (int,float) and math.isfinite(value) and value>0
    if report.get('manifest_sha256')!='c86f34c674f77fe7972f614ad1b88d0cf37531dc51d457479b17b4f837a4b539':return False
    unique=len({m['raw']['sha256'] for m in split['members']})
    if type(report.get('unique_raw_content_count')) is not int or report['unique_raw_content_count']!=unique:return False
    bindings=report.get('registered_bindings')
    if not isinstance(bindings,dict):return False
    refs=[split['catalog_ref'],split['policy_ref'],*split['protected_refs']]
    refs.extend({'path':name,'sha256':digest} for name,digest in split['public_source_hashes'].items())
    for member in split['members']:refs.extend(member[key] for key in ('raw','observations','view_manifest'))
    refs.append({'path':'src/naheng/data/protocol_capacity_measurement.py','sha256':REVIEWED_SCANNER_SHA256})
    if any(bindings.get(ref['path'])!=ref['sha256'] for ref in refs):return False
    if any(not isinstance(name,str) or Path(name).is_absolute() or '..' in Path(name).parts
        or not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest)
        for name,digest in bindings.items()):return False
    policy=asdict(Policy())
    units={'source_time':'s','source_current':'A','source_voltage':'V','source_capacity':'Ah','source_temperature':'degC','canonical_temperature':'K'}
    actual=report.get('members')
    if not isinstance(actual,list) or len(actual)!=len(split['members']):return False
    if not all(isinstance(m,dict) and isinstance(m.get('member_id'),str) for m in actual):return False
    if len({m['member_id'] for m in actual})!=len(actual):return False
    registered={m['member_id']:m for m in split['members']}
    for member in actual:
        if not isinstance(member,dict):return False
        expected=registered.get(member.get('member_id'))
        if expected is None or any(member.get(k)!=expected[k] for k in ('source_id','role','author_group','raw','view_manifest')):return False
        if member.get('rows')!=expected['row_count'] or member.get('raw_sha256')!=expected['raw']['sha256'] or member.get('raw_unchanged') is not True:return False
        if member.get('role_unchanged') is not True or member.get('status') not in ('computed','unknown'):return False
        if member['status']=='unknown' and (member.get('actual_capacity_Ah') is not None or not member.get('reasons')):return False
        if (member.get('units')!=units or member.get('canonical_current_sign')!='positive_discharge'
            or member.get('vendor_current_sign')!='positive_charge' or member.get('policy')!=policy
            or member.get('nominal_capacity_Ah')!=expected['nominal_capacity_Ah']
            or member.get('source_protocol')!=expected['protocol'] or member.get('source_provenance')!='public_measurement'
            or member.get('no_fit') is not True or member.get('heldout_tuning') is not False
            or member.get('D02_complete') is not False or member.get('scientific_external_acceptance_passed') is not False):return False
        attempts=member.get('protocol_attempts')
        if not isinstance(attempts,list) or any(not isinstance(a,dict) or a.get('status') not in ('computed','unknown') for a in attempts):return False
        completed=[]
        for attempt in attempts:
            if attempt.get('protocol_id')!=policy['protocol_id']:return False
            if attempt['status']=='unknown':
                if attempt.get('actual_capacity_Ah') is not None or not attempt.get('reasons'):return False
                continue
            completed.append(attempt)
            if (not positive_number(attempt.get('actual_capacity_Ah')) or attempt.get('reasons')!=[]
                or attempt.get('protocol_capacity_linear_estimate_Ah')!=attempt['actual_capacity_Ah']
                or attempt.get('nominal_capacity_Ah')!=expected['nominal_capacity_Ah']
                or attempt.get('full_protocol_capacity_is_estimate') is not True
                or attempt.get('strict_capacity_certificate') is not False
                or any(attempt.get(key,'missing') is not None for key in ('SOC_label','SOH_label','RUL_label'))):return False
            clocks=attempt.get('clock_validation')
            if not isinstance(clocks,dict) or any(not isinstance(clocks.get(key),dict)
                or clocks[key].get('valid') is not True or clocks[key].get('violations')!=[]
                for key in ('charge','rest','discharge')):return False
            boundary=attempt.get('boundaries');counter=attempt.get('counter_crosscheck')
            if (not isinstance(boundary,dict) or boundary.get('physical_onset_time_s','missing') is not None
                or boundary.get('physical_first_cutoff_time_s','missing') is not None
                or not isinstance(counter,dict) or counter.get('independent_truth') is not False):return False
        if member['status']=='computed':
            if not completed or type(member.get('complete_protocol_count')) is not int or member['complete_protocol_count']!=len(completed):return False
            if len(completed)==1:
                if not positive_number(member.get('actual_capacity_Ah')) or member['actual_capacity_Ah']!=completed[0]['actual_capacity_Ah'] or member.get('reasons')!=[]:return False
            elif member.get('actual_capacity_Ah') is not None or member.get('reasons')!=['multiple_complete_protocols_use_per_protocol_results']:return False
        elif completed:return False
    return (report.get('computed_file_count')==sum(m['status']=='computed' for m in actual)
        and report.get('unknown_file_count')==sum(m['status']=='unknown' for m in actual))


def aggregate_public_data_phases(voltage,capacity,elapsed_s):
    """Keep the old phase result intact; no diagnostic0 can promote D02 to0."""
    import copy
    import math
    if not isinstance(voltage,dict) or not isinstance(capacity,dict):raise ValueError('Two explicit phase results required')
    if any(phase.get('exit_code') not in (0,1,2) for phase in (voltage,capacity)):raise ValueError('Known phase exit statuses required')
    valid_elapsed=type(elapsed_s) in (float,int) and math.isfinite(elapsed_s) and elapsed_s>=0
    budget_exceeded=not valid_elapsed or elapsed_s>1800
    return {'schema_version':1,'suite':'public-data','profile':'pilot',
        'exit_code':1 if any(p['exit_code']==1 for p in (voltage,capacity)) else 2,
        'execution_completed':all(p.get('execution_completed') is True for p in (voltage,capacity)) and not budget_exceeded,
        'D02_complete':False,'scientific_external_acceptance_passed':False,
        'aggregate_wall_budget_s':1800,'aggregate_elapsed_s':elapsed_s if valid_elapsed else None,'aggregate_budget_exceeded':budget_exceeded,
        'original_voltage_required_exit_code':voltage['exit_code'],
        'phases':{'voltage':copy.deepcopy(voltage),'capacity':copy.deepcopy(capacity)},
        'scope':'Original voltage and material-mapping gates retained; capacity is a separate conditional measurement diagnostic'}

def run_public_capacity(root, manifest=None, output=None):
    root = Path(root).resolve()
    suite_path = root / 'configs/experiments/public-data-pilot-v1.json'
    suite = json.loads(suite_path.read_text(encoding='utf-8'))
    if suite['suite'] != 'public-data' or suite['profile'] != 'pilot':
        raise ValueError('Registered public-data pilot suite required')
    if (type(suite['worker_timeout_s']) is not int or suite['worker_timeout_s'] != 120
            or type(suite['worker_memory_limit_bytes']) is not int
            or suite['worker_memory_limit_bytes'] != 8 * 1024**3
            or type(suite['ridge_alpha']) not in (int, float) or suite['ridge_alpha'] != 1.0
            or type(suite['max_gap_s']) not in (int, float) or suite['max_gap_s'] != 60.0
            or type(suite['batch_rows']) is not int or suite['batch_rows'] != 4096
            or suite['missing_physical_mapping_exit_code'] != 2 or suite['D02_complete'] is not False):
        raise ValueError('Frozen pilot numerical settings and bounded worker limits required')
    if type(suite.get('batch_wall_budget_s')) is not int or suite['batch_wall_budget_s']!=1800:
        raise ValueError('Original aggregate1800s budget is required')
    packet = root / suite['default_manifest'] if manifest is None else Path(manifest)
    packet = (root / packet).resolve()
    if (not packet.is_relative_to(root) or not packet.is_file()
            or any(p.casefold() == 'evaluator' for p in packet.parts)
            or sha256_file(packet) != suite['default_manifest_sha256']):
        raise ValueError('The registered immutable public cohort is required')
    out = (root / suite['default_output_parent'] / ('capacity-' + uuid.uuid4().hex[:12])
           if output is None else root / Path(output)).resolve()
    if (not out.is_relative_to(root / 'artifacts') or out == root / 'artifacts'
            or packet.is_relative_to(out) or any(p.casefold() == 'evaluator' for p in out.parts)):
        raise ValueError('Fresh public controlled experiment output required')
    out.mkdir(parents=True, exist_ok=False)
    job_dir = out / 'execution'
    job_dir.mkdir()
    script = root / 'experiments/public_capacity.py'
    digest = code_hash(root)
    argv = [sys.executable, str(script), '--root', str(root), '--manifest', str(packet), '--output', str(out / 'result')]
    record = {'argv': argv, 'cwd': str(root), 'utc': datetime.now(timezone.utc).isoformat(),
        'status': 'started', 'exit_code': None, 'timeout_s': 120, 'memory_limit_bytes': 8 * 1024**3,
        'code_hash': digest, 'module_sha256': sha256_file(script), 'suite_sha256': sha256_file(suite_path),
        'manifest_sha256': sha256_file(packet), 'stdout': str(job_dir / 'stdout.log'), 'stderr': str(job_dir / 'stderr.log')}
    record.update(phase='capacity', worker_kind='trusted_deterministic_diagnostic', is_code_execution_sandbox=False)
    started, job, proc, code = time.monotonic(), None, None, 2
    with (job_dir / 'stdout.log').open('wb') as stdout, (job_dir / 'stderr.log').open('wb') as stderr:
        try:
            if os.name != 'nt':
                raise RuntimeError('This local entry requires the verified Windows owned Job memory adapter')
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            api.CreateJobObjectW.restype = wintypes.HANDLE
            api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            api.SetInformationJobObject.restype = wintypes.BOOL
            api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            api.AssignProcessToJobObject.restype = wintypes.BOOL
            api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            api.TerminateJobObject.restype = wintypes.BOOL
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            api.CloseHandle.restype = wintypes.BOOL
            job = api.CreateJobObjectW(None, None)
            limits = ExtendedLimits()
            limits.basic.flags = 0x2300
            limits.process_memory = limits.job_memory = record['memory_limit_bytes']
            if not job or not api.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise OSError(ctypes.get_last_error(), 'Cannot enforce owned Job memory limit')
            proc = subprocess.Popen(argv, cwd=root, stdout=stdout, stderr=stderr,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1',
                     'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'},
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            record['owned_pid'] = proc.pid
            if not api.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle))):
                proc.kill()
                proc.wait(timeout=10)
                raise OSError(ctypes.get_last_error(), 'Owned Job assignment failed; worker stopped')
            record.update(memory_limit_enforced=True, ownership='windows_job_object')
            atomic_json(job_dir / 'started.json', record)
            try:
                code = proc.wait(timeout=120)
                record['timed_out'] = False
            except subprocess.TimeoutExpired:
                if not api.TerminateJobObject(job, 2):
                    raise OSError(ctypes.get_last_error(), 'Owned Job termination failed')
                proc.wait(timeout=10)
                code, record['timed_out'] = 2, True
        except Exception as error:
            record['runner_error'] = repr(error)
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
        finally:
            if job is not None and job:
                api.CloseHandle(job)
    stable = (digest == code_hash(root) and record['module_sha256'] == sha256_file(script)
              and record['suite_sha256'] == sha256_file(suite_path) and record['manifest_sha256'] == sha256_file(packet))
    record.update(status='completed', exit_code=code, wall_s=time.monotonic()-started, source_unchanged=stable)
    report_path = out / 'result/report.json'
    report = None
    try:
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding='utf-8'))
            if not isinstance(report, dict):
                raise ValueError('Worker report must be an object')
    except (OSError, UnicodeError, ValueError) as error:
        report = None
        record['report_error'] = repr(error)
    atomic_json(job_dir / 'command.json', record)
    complete = bool(stable and not record.get('runner_error') and not record.get('timed_out', False) and report
                    and report.get('code_hash') == digest and report.get('code_hash_after') == digest
                    and report.get('source_current') and report.get('execution_completed')
                    and report.get('exit_code') == code and validate_capacity_completion(report, json.loads(packet.read_text(encoding='utf-8-sig')), digest, code))
    actual_code = 1 if code==1 else code if complete else 2
    atomic_json(out / 'manifest.json', {'exit_code': actual_code, 'execution_completed': complete,
        'code_hash': digest, 'source_unchanged': stable, 'D02_complete': False,
        'worker_receipt': {'path': (job_dir / 'command.json').relative_to(root).as_posix(),
                           'sha256': sha256_file(job_dir / 'command.json')},
        'report': {'path': report_path.relative_to(root).as_posix(), 'sha256': sha256_file(report_path) if report_path.is_file() else None}, 'phase': 'capacity'})
    return {'exit_code': actual_code, 'execution_completed': complete,
            'artifact_dir': out.as_posix(), 'D02_complete': False,
            'phase': 'capacity', 'scope': 'Observed conditional protocol-capacity diagnostic; original voltage/material gates remain separate'}


def run_public_data_phases(root, manifest=None, output=None):
    """Two separately bounded phases; original scientific gate stays explicit."""
    from .public_sodium_session import run_public_data
    root=Path(root).resolve()
    parent=(root/'artifacts/public_validation'/('combined-pilot-'+uuid.uuid4().hex[:12])
        if output is None else root/Path(output)).resolve()
    if (not parent.is_relative_to(root/'artifacts') or parent==root/'artifacts'
            or any(p.casefold()=='evaluator' for p in parent.parts)):
        raise ValueError('Fresh controlled public experiment output required')
    parent.mkdir(parents=True,exist_ok=False)
    start=time.monotonic()
    voltage=run_public_data(root,manifest,parent/'voltage')
    if 1800-(time.monotonic()-start)>=150:
        capacity=run_public_capacity(root,manifest,parent/'capacity')
    else:
        capacity={'phase':'capacity','exit_code':2,'execution_completed':False,
            'D02_complete':False,'reason':'Aggregate1800s budget cannot admit another bounded worker'}
    result=aggregate_public_data_phases(voltage,capacity,time.monotonic()-start)
    result.update(artifact_dir=parent.as_posix(),code_hash=code_hash(root),
        phase_manifests={key:{'path':(parent/key/'manifest.json').relative_to(root).as_posix(),
            'sha256':sha256_file(parent/key/'manifest.json')} for key in ('voltage','capacity')})
    atomic_json(parent/'manifest.json',result)
    return result
