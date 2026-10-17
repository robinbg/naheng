"""Independent bounded suite checks; no complete-core or runtime promotion."""
from pathlib import Path
import json
import uuid
from naheng.formal.checker import check
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/formal'/('trajectory-publication-'+uuid.uuid4().hex[:8]);out.mkdir(parents=True)
results=[]
for suite in ('reduction_trajectory','reduction_residual','foundation'):
    result=check(suite,out=out/suite)
    row={'suite':suite,'exit_code':result['exit_code'],'manifest':(out/suite/'manifest.json').relative_to(ROOT).as_posix()}
    results.append(row);print(json.dumps(row),flush=True)
code=1 if any(r['exit_code']==1 for r in results) else 2 if any(r['exit_code']==2 for r in results) else 0
(out/'manifest.json').write_text(json.dumps({'exit_code':code,'checks':results,'full_core_complete':False},indent=2),encoding='utf-8')
print(json.dumps({'manifest':str(out/'manifest.json'),'exit_code':code}),flush=True)
raise SystemExit(code)
