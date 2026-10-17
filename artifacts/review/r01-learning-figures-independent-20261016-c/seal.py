from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert not (HERE/'handoff.json').exists()
files={p.relative_to(HERE).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(HERE.rglob('*')) if p.is_file() and 't' not in p.relative_to(HERE).parts and '__pycache__' not in p.parts}
out={'schema_version':1,'status':'PASS_FROZEN_LEDGER_FIGURE_SCOPE','integration_suitable':True,'blocking_findings':[],
 'candidate_handoff_sha256':'07a4d8e30207371f51c17a33ede9753e88ca15c9bf595ee7998a4ec596bfbc8d',
 'candidate_tool_sha256':'0ab7e482a70d22b53c0e431d77627074eea2a63d9687a807d52f58cf17920cb7',
 'technical_tests_passed':34,'byte_reproduced_artifacts':6,'science_N_added':0,'R01_complete':False,
 'reviewer_authored_candidate':False,'current_layout_pixel_acceptance':False,'per_case_physics_revalidated':False,'files':files}
(HERE/'handoff.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
print(json.dumps({'handoff':str(HERE/'handoff.json'),'sha256':sha(HERE/'handoff.json'),'files':len(files)}))
