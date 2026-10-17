from pathlib import Path
import os,sys,json,uuid
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];PACK=ROOT/'artifacts/handoff/r01-learning-figures-20261016-a'
sys.path.insert(0,str(ROOT/'src'))
from naheng.runtime.validation_process import run_validation_command
mode=sys.argv[1];out=HERE/('run-'+mode+'-'+uuid.uuid4().hex[:8]);out.mkdir()
argv=[sys.executable,str(HERE/'check.py')] if mode=='check' else [sys.executable,'-m','pytest',str(PACK/'test_figures.py'),'-q','-p','no:cacheprovider','--basetemp',str(HERE/'t')]
r=run_validation_command(argv,ROOT,out/'stdout.log',out/'stderr.log',timeout_s=120,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8'))
(out/'command.json').write_text(json.dumps(r,indent=2),encoding='utf-8');print(json.dumps({'receipt':str(out/'command.json'),**r}));raise SystemExit(r['exit_code'])
