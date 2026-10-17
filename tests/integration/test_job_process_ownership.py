"""Real local process ownership and startup recovery, without scientific claims."""
import json
import os
import subprocess
import sys
import pytest
from naheng.runtime.jobs import JobStore
from naheng.runtime.process_identity import capture_process_identity,process_identity_alive


def test_startup_preserves_live_queued_and_running_owners_and_returns_dead_to_incomplete(tmp_path):
    store=JobStore(tmp_path)
    proc=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.buffer.read(1)'],stdin=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        queued=store.create({'scope':'process owner fixture'},owner_pid=proc.pid)['run_id']
        running=store.create({'scope':'process owner fixture running'},owner_pid=proc.pid)['run_id']
        assert store.try_start(running,owner_pid=proc.pid)
        assert store.recover_interrupted()==0
        assert store.get(queued)['state']=='queued' and store.get(running)['state']=='running'
        proc.communicate(input=b'x',timeout=10)
        assert proc.returncode==0
        assert store.recover_interrupted()==2
        assert store.get(queued)['state']==store.get(running)['state']=='interrupted'
        assert not store.try_start(running)
    finally:
        if proc.poll() is None:proc.communicate(input=b'x',timeout=10)


def test_owner_transfer_and_pid_birth_identity_do_not_depend_on_creator_lifetime(tmp_path):
    store=JobStore(tmp_path)
    run=store.create({},owner_pid=os.getpid())['run_id']
    owner=capture_process_identity(os.getpid())
    assert process_identity_alive(owner) is True
    assert store.bind_worker_owner(run,os.getpid())
    assert store.try_start(run,owner_pid=os.getpid())
    assert store.recover_interrupted()==0
    phases=[event['phase'] for event in store.events(run) if event['type']=='owner_claimed']
    assert phases==['queued','dispatched','worker_started']
    # Wrong birth on an actual live PID is a PID-reuse fixture, not a dead child.
    with store.connect() as connection:
        saved=json.loads(connection.execute('SELECT identity FROM job_owners WHERE run_id=?',(run,)).fetchone()[0])
        if saved['platform']=='win32':saved['birth_id']='windows_filetime:1'
        elif saved['platform'].startswith('linux'):saved['birth_id']=saved['birth_id'].rsplit(':',1)[0]+':1'
        else:pytest.fail('This actual host must support process birth evidence')
        connection.execute('UPDATE job_owners SET identity=? WHERE run_id=?',(json.dumps(saved),run))
    assert store.recover_interrupted()==1
    assert store.get(run)['state']=='interrupted'


@pytest.mark.parametrize('case',['unobservable','corrupt'])
def test_unknown_owner_does_not_cancel_possibly_live_work(tmp_path,monkeypatch,case):
    store=JobStore(tmp_path);run=store.create({},owner_pid=os.getpid())['run_id']
    if case=='unobservable':
        monkeypatch.setattr('naheng.runtime.process_identity.process_identity_alive',lambda identity:None)
    else:
        with store.connect() as connection:
            connection.execute('UPDATE job_owners SET identity=? WHERE run_id=?',('invalid-json',run))
    assert store.recover_interrupted()==0 and store.get(run)['state']=='queued'
