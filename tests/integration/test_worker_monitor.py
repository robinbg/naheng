import json,subprocess,sys
import pytest
from naheng.runtime.artifacts import atomic_json
from naheng.runtime.jobs import JobStore
from naheng.runtime.dispatch import monitor

@pytest.mark.parametrize("cancel",[False,True])
def test_real_owned_process_timeout_invalidates_publication_window(tmp_path,cancel):
    store=JobStore(tmp_path/"runs"); job=store.create({"mode":"interactive"})
    store.state(job["run_id"],"running",.9)
    dest=store.root/job["run_id"]
    atomic_json(dest/"manifest.json",{"complete":True,"scope":"technical publication-window fixture"})
    store.checkpoint(job["run_id"],{"complete":True,"step":1})
    if cancel: store.cancel(job["run_id"])
    proc=subprocess.Popen([sys.executable,"-c","import time; time.sleep(10)"],creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    monitor(proc,store,job["run_id"],timeout_s=.05)
    assert store.get(job["run_id"])["state"]==("cancelled" if cancel else "failed")
    assert json.loads((dest/"manifest.json").read_text())["complete"] is False
    assert json.loads((dest/"checkpoint.json").read_text())["complete"] is False
    assert proc.poll() is not None

def test_zero_exit_without_complete_state_is_not_success(tmp_path):
    store=JobStore(tmp_path/"runs"); job=store.create({"mode":"interactive"})
    store.try_start(job["run_id"])
    proc=subprocess.Popen([sys.executable,"-c","pass"],creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    monitor(proc,store,job["run_id"],timeout_s=10)
    assert store.get(job["run_id"])["state"]=="failed"
def test_windows_hard_budget_terminates_owned_grandchild(tmp_path):
    import os,time
    if os.name!="nt": pytest.skip("Windows-owned-process-tree verification")
    store=JobStore(tmp_path/"runs"); job=store.create({"mode":"interactive"}); store.try_start(job["run_id"])
    sentinel=tmp_path/"escaped.txt"; ready=tmp_path/"ready.txt"
    grandchild=f"import time; from pathlib import Path; time.sleep(1.2); Path({str(sentinel)!r}).write_text('escaped')"
    parent=f"import subprocess,sys,time; from pathlib import Path; subprocess.Popen([sys.executable,'-c',{grandchild!r}]); Path({str(ready)!r}).write_text('ready'); time.sleep(10)"
    proc=subprocess.Popen([sys.executable,"-c",parent],creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    deadline=time.monotonic()+3
    while not ready.exists() and time.monotonic()<deadline: time.sleep(.02)
    assert ready.exists()
    monitor(proc,store,job["run_id"],timeout_s=.05)
    time.sleep(1.3)
    assert not sentinel.exists()
    event=next(e for e in store.events(job["run_id"]) if e["type"]=="owned_worker_tree_termination")
    assert event["command"]==["taskkill","/PID",str(proc.pid),"/T","/F"]
    assert event["exit_code"]==0