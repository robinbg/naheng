"""Run one trusted validation with native exit and owned-tree cleanup receipts."""
from datetime import datetime,timezone
import argparse,json,os,sys,uuid
from pathlib import Path
from naheng.runtime.artifacts import atomic_json
from naheng.runtime.validation_process import run_validation_command
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--label',required=True)
    parser.add_argument('--timeout',type=int,default=120);parser.add_argument('--cwd',default='.')
    parser.add_argument('command',nargs=argparse.REMAINDER);a=parser.parse_args()
    assert 0<a.timeout<=1800 and a.label and all(c.isalnum() or c in '-_' for c in a.label)
    command=a.command[1:] if a.command[:1]==['--'] else a.command
    assert command
    cwd=(ROOT/a.cwd).resolve();assert cwd.is_relative_to(ROOT)
    out=ROOT/'artifacts/validation'/(a.label+'-'+uuid.uuid4().hex[:8]);out.mkdir(parents=True,exist_ok=False)
    stdout=out/'stdout.log';stderr=out/'stderr.log'
    r=run_validation_command(command,cwd,stdout,stderr,timeout_s=a.timeout,env=dict(os.environ))
    r.update(utc=datetime.now(timezone.utc).isoformat(),argv=command,cwd=str(cwd),stdout=str(stdout),stderr=str(stderr),
             native_status=r['status'],status='completed')
    atomic_json(out/'command.json',r)
    print(stdout.read_text(encoding='utf-8',errors='replace')[-2400:])
    print(stderr.read_text(encoding='utf-8',errors='replace')[-1200:])
    print(json.dumps({'receipt':str((out/'command.json').relative_to(ROOT)),**r}))
    return r['exit_code']
if __name__=='__main__':raise SystemExit(main())
