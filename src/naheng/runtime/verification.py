from __future__ import annotations
import datetime, json, os, subprocess, sys, time, uuid
from pathlib import Path
import yaml
from .artifacts import atomic_json
from .artifacts import code_hash,sha256_file
from .validation_process import run_validation_command

def verify(root:Path,profile:str,out:Path|None=None):
    cfg=yaml.safe_load((root/"configs/gates.yaml").read_text(encoding="utf-8"))
    gates=cfg["profiles"].get(profile)
    if gates is None: raise ValueError("Unknown verification profile")
    run=root/"artifacts/verification"/(profile+"-"+uuid.uuid4().hex[:10]); run.mkdir(parents=True)
    source_before=code_hash(root)
    gates_hash=sha256_file(root/'configs/gates.yaml')
    temp_parent=os.environ.get('NAHENG_VALIDATION_TEMP_ROOT')
    if temp_parent:
        selected=Path(temp_parent)
        if not selected.is_absolute() or selected.resolve()==Path(selected.anchor).resolve():
            raise ValueError('Explicit absolute dedicated validation temporary parent required')
        temp_owner=selected.resolve()/run.name
        temp_owner.mkdir(parents=True,exist_ok=False)
    else:temp_owner=run
    auxiliary=temp_owner/'auxiliary';auxiliary.mkdir(exist_ok=False)
    records=[];batch_start=time.monotonic();cleanup_unknown=False
    for gate in gates:
        argv=[str(a).replace("{python}",sys.executable).replace("{root}",str(root)).replace("{temp}",str(temp_owner/"pytest")) for a in gate["command"]]
        timeout=gate.get('timeout_s',120)
        if cleanup_unknown:
            record={'command':argv,'exit_code':2,'status':'blocked','executed':False,
                'reason':'Previous owned validation cleanup is unknown; further execution withheld','wall_s':0}
        elif time.monotonic()-batch_start+timeout>1800:
            record={'command':argv,'exit_code':2,'status':'blocked','executed':False,
                'reason':'Remaining 1800s batch budget cannot admit this gate','wall_s':0}
        else:
            env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONPATH':str(root/'src'),
                'TEMP':str(auxiliary),'TMP':str(auxiliary),'PYTHONDONTWRITEBYTECODE':'1'}
            record=run_validation_command(argv,root,run/(gate['id']+'.stdout.log'),
                run/(gate['id']+'.stderr.log'),timeout_s=timeout,env=env)
            cleanup_unknown=not record['resource_cleanup_confirmed']
        records.append({**record,'id':gate['id'],'logs':str(run)})
        atomic_json(run/'progress.json',{'profile':profile,'checks':records,'source_hash':source_before})
    code=1 if any(r["status"]=="failed" for r in records) else 2 if any(r["status"]=="blocked" for r in records) else 0
    unchanged=source_before==code_hash(root) and gates_hash==sha256_file(root/'configs/gates.yaml')
    if not unchanged:code=2
    result={"profile":profile,"exit_code":code,"status":"passed" if code==0 else "failed" if code==1 else "blocked","checks":records,"scope":"Only listed gates; smoke is not release","utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'code_hash':source_before,'source_and_gates_unchanged':unchanged,'gates_sha256':gates_hash,
        'temporary_owner':str(temp_owner),'aggregate_wall_s':time.monotonic()-batch_start}
    atomic_json(run/"audit.json",result)
    if out: atomic_json(out,result)
    return result
