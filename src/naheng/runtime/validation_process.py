"""Bound a trusted validation command and retain native outcomes, not authority."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import time
from .process_tree import ProcessTree


def _memory_limit(tree, amount):
    if os.name != 'nt' or tree.job is None:
        raise RuntimeError('Validation requires an owned Windows Job Object')
    class Basic(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),
            ('flags',wintypes.DWORD),('minimum_ws',ctypes.c_size_t),('maximum_ws',ctypes.c_size_t),
            ('active_limit',wintypes.DWORD),('affinity',ctypes.c_size_t),
            ('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
    class Counters(ctypes.Structure):
        _fields_=[(n,ctypes.c_ulonglong) for n in
            ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class Extended(ctypes.Structure):
        _fields_=[('basic',Basic),('io',Counters),('process_memory',ctypes.c_size_t),
            ('job_memory',ctypes.c_size_t),('peak_process_memory',ctypes.c_size_t),('peak_job_memory',ctypes.c_size_t)]
    limits=Extended();limits.basic.flags=0x2000|0x100|0x200
    limits.process_memory=limits.job_memory=amount
    if not tree.api.SetInformationJobObject(tree.job,9,ctypes.byref(limits),ctypes.sizeof(limits)):
        raise ctypes.WinError(ctypes.get_last_error())
    query=tree.api.QueryInformationJobObject
    query.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p]
    query.restype=wintypes.BOOL
    actual=Extended()
    if not query(tree.job,9,ctypes.byref(actual),ctypes.sizeof(actual),None):
        raise ctypes.WinError(ctypes.get_last_error())
    if actual.basic.flags != limits.basic.flags or actual.process_memory != amount or actual.job_memory != amount:
        raise RuntimeError('Validation Job limits readback differs')


def _finish_owned_job(tree,record):
    """Confirm this Job has no active processes before closing its handle."""
    if os.name!='nt' or tree.job is None:
        tree.close()
        return
    class Accounting(ctypes.Structure):
        _fields_=[('user',ctypes.c_longlong),('kernel',ctypes.c_longlong),
            ('period_user',ctypes.c_longlong),('period_kernel',ctypes.c_longlong),
            ('faults',wintypes.DWORD),('total',wintypes.DWORD),
            ('active',wintypes.DWORD),('terminated',wintypes.DWORD)]
    record['owned_final_tree_stop']=tree.terminate()
    if record['owned_final_tree_stop']['exit_code']!=0:
        raise RuntimeError('Owned final tree termination failed')
    query=tree.api.QueryInformationJobObject
    query.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p]
    query.restype=wintypes.BOOL
    deadline=time.monotonic()+5
    while True:
        actual=Accounting()
        if not query(tree.job,1,ctypes.byref(actual),ctypes.sizeof(actual),None):
            raise ctypes.WinError(ctypes.get_last_error())
        record['owned_active_processes_after_cleanup']=actual.active
        if actual.active==0:break
        if time.monotonic()>=deadline:raise RuntimeError('Owned Job processes have not exited')
        time.sleep(.02)
    if not tree.api.CloseHandle(tree.job):raise ctypes.WinError(ctypes.get_last_error())
    tree.job=None
    record['owned_job_handle_closed']=True


def run_validation_command(argv,root,stdout_path,stderr_path,*,timeout_s,env):
    """Only trusted registered validation commands. Not an OS permission sandbox."""
    if not 0 < timeout_s <= 1800:raise ValueError('Validation batch timeout out of range')
    started=time.monotonic()
    record={'command':argv,'exit_code':2,'timed_out':False,'executed':False,
        'timeout_s':timeout_s,'memory_limit_bytes':8*1024**3,'memory_limit_enforced':False,
        'is_code_execution_sandbox':False,'cleanup_errors':[],
        'startup_resource_assignment':'trusted command starts before Job assignment; not candidate isolation'}
    proc=tree=None
    def poll_owned():
        try:return proc.poll()
        except Exception as error:
            record['cleanup_errors'].append('Owned exit query unknown: '+repr(error))
            return None
    def stop_owned():
        try:
            if tree is not None:
                record['owned_tree_stop']=tree.terminate()
            elif os.name=='nt':
                stopped=subprocess.run(['taskkill.exe','/PID',str(proc.pid),'/T','/F'],
                    capture_output=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                record['owned_tree_stop']={'method':'owned_pid_taskkill','exit_code':stopped.returncode}
            else:
                import signal
                os.killpg(proc.pid,signal.SIGKILL)
                record['owned_tree_stop']={'method':'owned_process_group','exit_code':0}
            if record['owned_tree_stop']['exit_code']!=0 and poll_owned() is None:
                record['cleanup_errors'].append('Owned tree termination did not report success')
        except Exception as error:
            record['cleanup_errors'].append('Owned tree termination: '+repr(error))
        try:proc.wait(timeout=15)
        except Exception as error:
            record['cleanup_errors'].append('Owned primary exit unknown: '+repr(error))
    with Path(stdout_path).open('wb') as stdout,Path(stderr_path).open('wb') as stderr:
        try:
            proc=subprocess.Popen(argv,cwd=root,env=env,stdout=stdout,stderr=stderr,
                start_new_session=os.name!='nt')
        except OSError as error:
            record['setup_error']=repr(error)
        else:
            record.update(executed=True,owned_pid=proc.pid)
            try:
                tree=ProcessTree(proc)
                _memory_limit(tree,record['memory_limit_bytes'])
                record['memory_limit_enforced']=True
                remaining=max(0,timeout_s-(time.monotonic()-started))
                try:record['exit_code']=proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    record['timed_out']=True
                    stop_owned()
            except Exception as error:
                record['setup_error']=repr(error)
                stop_owned()
            finally:
                if poll_owned() is None:stop_owned()
                if tree is not None:
                    try:
                        _finish_owned_job(tree,record)
                    except Exception as error:
                        record['cleanup_errors'].append('Owned Job close: '+repr(error))
                record['native_exit_code']=poll_owned()
    if record['cleanup_errors'] or (record['executed'] and record.get('native_exit_code') is None):
        record['exit_code']=2
    record['wall_s']=time.monotonic()-started
    record['resource_cleanup_confirmed']=not record['cleanup_errors'] and (not record['executed'] or record.get('native_exit_code') is not None)
    record['status']='passed' if record['exit_code']==0 else 'blocked' if record['exit_code']==2 else 'failed'
    return record
