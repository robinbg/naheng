from pathlib import Path
from datetime import datetime,timezone
import json,hashlib
OUT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
r=json.loads((OUT/'guard-results.json').read_text(encoding='utf-8'))
c=json.loads((OUT/'command.json').read_text(encoding='utf-8'))
packet={'created_at_utc':datetime.now(timezone.utc).isoformat(),'exit_code':1,
    'actual_calibration_exit':c['exit_code'],'wall_s':c['wall_s'],'timeout_s':c['timeout_s'],
    'memory_limit_bytes':c['memory_limit_bytes'],'memory_limit_enforced':c['memory_limit_enforced'],
    'case_count':r['case_count'],'incorrectly_accepted_bad_reports':len(r['guard_failures']),
    'native1_projection_guard_failed':not r['native1_projection']['guard_met'],
    'candidate_source_hashes':r['source_before'],'read_bytes_unchanged':r['source_unchanged'],
    'scope':'Pure saved report/aggregate validation, not actual public CLI',
    'raw_replays':0,'business_workers_spawned':0,'Lean_invocations':0,'GUI_tested':False,
    'approved_for_public_completion':False,
    'artifact_inventory':{p.relative_to(OUT).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size}
        for p in OUT.rglob('*') if p.is_file() and p.name!='handoff.json'}}
(OUT/'handoff.json').write_text(json.dumps(packet,indent=2),encoding='utf-8')
print(json.dumps({'exit_code':1,'handoff':str(OUT/'handoff.json')}))
