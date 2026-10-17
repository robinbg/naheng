from __future__ import annotations
import os,subprocess,sys,threading
from pathlib import Path
from .jobs import JobStore,TERMINAL

def spawn(project:Path,store:JobStore,run_id:str):
    job=store.get(run_id); run_dir=store.root/run_id
    run_dir.mkdir(parents=True,exist_ok=True)
    log=(run_dir/"worker.log").open("ab")
    try:
        proc=subprocess.Popen([sys.executable,"-m","naheng.runtime.worker",str(project),run_id],cwd=project,
            stdout=log,stderr=log,env={**os.environ,"PYTHONPATH":str(Path(job["config"]["source_dir"])/"src"),"PYTHONIOENCODING":"utf-8"},
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        store.bind_worker_owner(run_id,proc.pid)
    finally: log.close()
    return proc

def monitor(proc,store,run_id,timeout_s=120):
    reason=None
    try: proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        if os.name=="nt":
            command=["taskkill","/PID",str(proc.pid),"/T","/F"]
            stopped=subprocess.run(command,capture_output=True,timeout=10,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            store.event(run_id,{"type":"owned_worker_tree_termination","command":command,"exit_code":stopped.returncode,"stdout":stopped.stdout.decode(errors="replace"),"stderr":stopped.stderr.decode(errors="replace")})
            if proc.poll() is None: proc.kill()
        else: proc.kill()
        proc.wait(timeout=10)
        reason="Hard worker budget exceeded; partial result is not a complete trajectory"
    else:
        if store.get(run_id)["state"] not in TERMINAL:
            reason=f"Worker exited {proc.returncode} without terminal completion"
    if reason is not None:
        job=store.get(run_id)
        if job["state"]=="succeeded": return
        from .publication import record_incomplete
        dest=store.root/run_id
        steps=0
        try:
            import json
            steps=json.loads((dest/"checkpoint.json").read_text(encoding="utf-8")).get("step",0)
        except (OSError,ValueError): pass
        record_incomplete(store,run_id,dest,RuntimeError(reason),steps=steps,sensor=[])
        if job["state"] not in TERMINAL:
            store.state(run_id,"cancelled" if job["cancel"] else "failed",error=reason)
