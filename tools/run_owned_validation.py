"""Execute one owned tool tree with explicit time and 8 GiB memory limits."""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from naheng.runtime.artifacts import atomic_json
from naheng.runtime.process_tree import ProcessTree

ROOT = Path(__file__).resolve().parents[1]

def memory_limit(tree, amount):
    if os.name != 'nt' or tree.job is None:
        raise RuntimeError('Owned Windows Job Object required to enforce memory budget')
    class Basic(ctypes.Structure):
        _fields_ = [('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),
            ('flags',wintypes.DWORD),('minimum_ws',ctypes.c_size_t),('maximum_ws',ctypes.c_size_t),
            ('active_limit',wintypes.DWORD),('affinity',ctypes.c_size_t),
            ('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
    class Counters(ctypes.Structure):
        _fields_ = [(name,ctypes.c_ulonglong) for name in
            ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class Extended(ctypes.Structure):
        _fields_ = [('basic',Basic),('io',Counters),('process_memory',ctypes.c_size_t),
            ('job_memory',ctypes.c_size_t),('peak_process_memory',ctypes.c_size_t),
            ('peak_job_memory',ctypes.c_size_t)]
    limits = Extended()
    limits.basic.flags = 0x2000 | 0x100 | 0x200
    limits.process_memory = limits.job_memory = amount
    if not tree.api.SetInformationJobObject(tree.job,9,ctypes.byref(limits),ctypes.sizeof(limits)):
        raise ctypes.WinError(ctypes.get_last_error())

def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser=argparse.ArgumentParser()
    parser.add_argument('--label',required=True)
    parser.add_argument('--timeout',type=int,default=120)
    parser.add_argument('--cwd',default='.')
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    assert 0 < args.timeout <= 1800
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    assert command
    cwd=(ROOT/args.cwd).resolve()
    assert cwd.is_relative_to(ROOT)
    out=ROOT/'artifacts/validation'/(args.label+'-'+uuid.uuid4().hex[:8])
    out.mkdir(parents=True,exist_ok=False)
    record={'argv':command,'cwd':str(cwd),'utc':datetime.now(timezone.utc).isoformat(),
        'stdout':str(out/'stdout.log'),'stderr':str(out/'stderr.log'),
        'timeout_s':args.timeout,'memory_limit_bytes':8*1024**3,'status':'started','exit_code':None}
    started=time.monotonic()
    with (out/'stdout.log').open('wb') as stdout,(out/'stderr.log').open('wb') as stderr:
        try:
            proc=subprocess.Popen(command,cwd=cwd,stdout=stdout,stderr=stderr,
                env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONPATH':str(ROOT/'src')})
        except OSError as error:
            record.update(exit_code=2,status='not_started',executed=False,
                          setup_error=str(error),wall_s=time.monotonic()-started)
            atomic_json(out/'command.json',record)
            print(json.dumps({**record,'receipt':(out/'command.json').relative_to(ROOT).as_posix()}))
            return 2
        tree=ProcessTree(proc)
        record['owned_pid']=proc.pid
        try:
            try:
                memory_limit(tree,record['memory_limit_bytes'])
                record['memory_limit_enforced']=True
                atomic_json(out/'started.json',record)
                try:
                    code=proc.wait(timeout=args.timeout)
                    record['timed_out']=False
                except subprocess.TimeoutExpired:
                    record['owned_tree_stop']=tree.terminate()
                    proc.wait(timeout=15)
                    code=2
                    record['timed_out']=True
            except (OSError,RuntimeError) as error:
                record['memory_limit_enforced']=False
                record['setup_error']=str(error)
                record['owned_tree_stop']=tree.terminate()
                proc.wait(timeout=15)
                code=2
        finally:
            tree.close()
    record.update(exit_code=code,status='completed',wall_s=time.monotonic()-started)
    atomic_json(out/'command.json',record)
    print((out/'stdout.log').read_text(encoding='utf-8',errors='replace')[-1800:])
    print((out/'stderr.log').read_text(encoding='utf-8',errors='replace')[-1200:])
    print(json.dumps({**record,'receipt':(out/'command.json').relative_to(ROOT).as_posix()}))
    return code

if __name__=='__main__':
    raise SystemExit(main())
