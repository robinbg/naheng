"""Bounded public experiment entry; calculated partial results retain exit 2."""
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


class BasicLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong), ('flags', wintypes.DWORD),
        ('minimum_ws', ctypes.c_size_t), ('maximum_ws', ctypes.c_size_t), ('active_limit', wintypes.DWORD),
        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]


class Counters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
        ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', BasicLimits), ('io', Counters), ('process_memory', ctypes.c_size_t),
        ('job_memory', ctypes.c_size_t), ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]


def run_public_data(root, manifest=None, output=None):
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
    packet = root / suite['default_manifest'] if manifest is None else Path(manifest)
    packet = (root / packet).resolve()
    if (not packet.is_relative_to(root) or not packet.is_file()
            or any(p.casefold() == 'evaluator' for p in packet.parts)
            or sha256_file(packet) != suite['default_manifest_sha256']):
        raise ValueError('The registered immutable public cohort is required')
    out = (root / suite['default_output_parent'] / ('pilot-' + uuid.uuid4().hex[:12])
           if output is None else root / Path(output)).resolve()
    if (not out.is_relative_to(root / 'artifacts') or out == root / 'artifacts'
            or packet.is_relative_to(out) or any(p.casefold() == 'evaluator' for p in out.parts)):
        raise ValueError('Fresh public controlled experiment output required')
    out.mkdir(parents=True, exist_ok=False)
    job_dir = out / 'execution'
    job_dir.mkdir()
    script = root / 'experiments/public_sodium.py'
    digest = code_hash(root)
    argv = [sys.executable, str(script), '--root', str(root), '--manifest', str(packet), '--output', str(out / 'result')]
    record = {'argv': argv, 'cwd': str(root), 'utc': datetime.now(timezone.utc).isoformat(),
        'status': 'started', 'exit_code': None, 'timeout_s': 120, 'memory_limit_bytes': 8 * 1024**3,
        'code_hash': digest, 'module_sha256': sha256_file(script), 'suite_sha256': sha256_file(suite_path),
        'manifest_sha256': sha256_file(packet), 'stdout': str(job_dir / 'stdout.log'), 'stderr': str(job_dir / 'stderr.log')}
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
                    and report.get('exit_code') == code)
    actual_code = code if complete else 2
    atomic_json(out / 'manifest.json', {'exit_code': actual_code, 'execution_completed': complete,
        'code_hash': digest, 'source_unchanged': stable, 'D02_complete': False,
        'worker_receipt': {'path': (job_dir / 'command.json').relative_to(root).as_posix(),
                           'sha256': sha256_file(job_dir / 'command.json')},
        'report': {'path': report_path.relative_to(root).as_posix(), 'sha256': sha256_file(report_path)}})
    return {'exit_code': actual_code, 'execution_completed': complete,
            'artifact_dir': out.as_posix(), 'D02_complete': False,
            'scope': 'Actual frozen public-data voltage transfer; same-cell physical reference mapping remains blocked'}
