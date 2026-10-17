"""Build the current frontend and retain native commands and byte identity."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,shutil,sys,uuid


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--output',type=Path,required=True);p.add_argument('--receipt',type=Path,required=True)
    a=p.parse_args(argv);root=a.project_root.resolve();dest=a.output.resolve();receipt=a.receipt.resolve()
    if dest.exists() or receipt.exists():raise ValueError('New build output and receipt paths required')
    sys.path.insert(0,str(root/'src'))
    from naheng.runtime.validation_process import run_validation_command
    spec=importlib.util.spec_from_file_location('delivery_builder',Path(__file__).with_name('build_delivery.py'));builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    before=builder.frontend_hash(root);node=shutil.which('node')
    if not node:raise ValueError('Node is required; install the frontend lockfile dependencies first')
    logs=receipt.parent/(receipt.stem+'-commands-'+uuid.uuid4().hex[:8]);logs.mkdir(parents=True,exist_ok=False)
    records=[]
    for name,command in [('typescript',[node,str(root/'frontend/node_modules/typescript/bin/tsc'),'--project',str(root/'frontend/tsconfig.json'),'--noEmit','--incremental','false']),('vite',[node,str(root/'frontend/node_modules/vite/bin/vite.js'),'build','--outDir',str(dest)])]:
        result=run_validation_command(command,root/'frontend',logs/(name+'.stdout.log'),logs/(name+'.stderr.log'),timeout_s=120,env=dict(os.environ))
        (logs/(name+'.command.json')).write_text(json.dumps(result,indent=2),encoding='utf-8');records.append(result)
        if result['exit_code']!=0:return result['exit_code']
    if before!=builder.frontend_hash(root):raise ValueError('Frontend source changed during build')
    files={file.relative_to(dest).as_posix():hashlib.sha256(file.read_bytes()).hexdigest() for file in dest.rglob('*') if file.is_file()}
    receipt.parent.mkdir(parents=True,exist_ok=True)
    receipt.write_text(json.dumps({'source_sha256':before,'native_codes':[r['native_exit_code'] for r in records],'artifacts':files,'commands':[str(logs/(name+'.command.json')) for name in ('typescript','vite')]},indent=2),encoding='utf-8')
    print(json.dumps({'output':str(dest),'receipt':str(receipt),'source_sha256':before}));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError) as error:raise SystemExit(str(error))
