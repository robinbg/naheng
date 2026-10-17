from pathlib import Path
import importlib.util,json,os,subprocess,sys,time
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from naheng.runtime.process_tree import ProcessTree
spec=importlib.util.spec_from_file_location('review_memory',ROOT/'tools/run_owned_validation.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
cmd=[str(ROOT/'.venv/Scripts/python.exe'),'-B',str(OUT/'calibrate_guards.py')]
record={'argv':cmd,'cwd':str(ROOT),'timeout_s':120,'memory_limit_bytes':8*1024**3,
        'scope':'Pure saved-report guard calibration, no raw/native worker/Lean/GUI'}
started=time.monotonic()
with (OUT/'stdout.log').open('wb') as stdout,(OUT/'stderr.log').open('wb') as stderr:
    proc=subprocess.Popen(cmd,cwd=ROOT,stdout=stdout,stderr=stderr,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    tree=ProcessTree(proc)
    try:
        helper.memory_limit(tree,record['memory_limit_bytes']);record['memory_limit_enforced']=True
        try:code=proc.wait(timeout=max(0,120-(time.monotonic()-started)))
        except subprocess.TimeoutExpired:
            record['timed_out']=True;record['owned_stop']=tree.terminate();proc.wait(timeout=15);code=2
    except (OSError,RuntimeError) as e:
        record['setup_error']=str(e);record['owned_stop']=tree.terminate();proc.wait(timeout=15);code=2
    finally:tree.close()
record.update(exit_code=code,wall_s=time.monotonic()-started)
(OUT/'command.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record));raise SystemExit(code)
