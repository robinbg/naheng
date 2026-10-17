"""Real trusted subprocesses verify timeout cleanup and native failure retention."""
import os
from pathlib import Path
import sys
import time
from naheng.runtime.validation_process import run_validation_command

def test_native_failure_and_both_logs_are_retained(tmp_path):
    out=tmp_path/'out';err=tmp_path/'err'
    result=run_validation_command([sys.executable,'-c',
        "import sys;print('native stdout');print('native stderr',file=sys.stderr);sys.exit(1)"],
        tmp_path,out,err,timeout_s=10,env=dict(os.environ))
    assert result['exit_code']==1 and result['status']=='failed' and not result['timed_out']
    assert result['memory_limit_enforced'] and result['executed']
    assert 'native stdout' in out.read_text() and 'native stderr' in err.read_text()

def test_timeout_stops_owned_descendant_before_later_write(tmp_path):
    marker=tmp_path/'must-not-exist'
    child="import pathlib,time;time.sleep(2);pathlib.Path("+repr(str(marker))+").write_text('unexpected descendant write')"
    parent="import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',"+repr(child)+"]);time.sleep(20)"
    result=run_validation_command([sys.executable,'-c',parent],tmp_path,tmp_path/'out',tmp_path/'err',
        timeout_s=.5,env=dict(os.environ))
    assert result['exit_code']==2 and result['status']=='blocked' and result['timed_out']
    assert result['memory_limit_enforced'] and result['owned_tree_stop']['method']=='windows_job_object'
    assert result['owned_tree_stop']['exit_code']==0
    time.sleep(2)
    assert not marker.exists()


def test_normal_parent_exit_cannot_leave_an_owned_descendant_running(tmp_path):
    marker=tmp_path/'normal-exit-child-must-not-write'
    child="import pathlib,time;time.sleep(2);pathlib.Path("+repr(str(marker))+").write_text('unexpected live descendant')"
    parent="import subprocess,sys;subprocess.Popen([sys.executable,'-c',"+repr(child)+"])"
    result=run_validation_command([sys.executable,'-c',parent],tmp_path,tmp_path/'out',tmp_path/'err',
        timeout_s=10,env=dict(os.environ))
    assert result['exit_code']==result['native_exit_code']==0
    assert result['resource_cleanup_confirmed'] and result['owned_job_handle_closed']
    assert result['owned_active_processes_after_cleanup']==0
    time.sleep(2)
    assert not marker.exists()
