"""Rebuild and audit existing runtime proof suites after the exports change."""
import json
from pathlib import Path
import uuid
from naheng.formal.checker import check

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / 'artifacts/formal' / ('readout-runtime-refresh-' + uuid.uuid4().hex[:8])
out.mkdir(parents=True, exist_ok=False)
rows = []
for suite in ('foundation', 'reduction_residual'):
    result = check(suite, out=out / suite)
    rows.append({'suite': suite, 'exit_code': result['exit_code'],
                 'manifest': (out / suite / 'manifest.json').relative_to(ROOT).as_posix()})
    (out / 'progress.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    print(json.dumps(rows[-1]), flush=True)
code = 1 if any(r['exit_code'] == 1 for r in rows) else 2 if any(r['exit_code'] == 2 for r in rows) else 0
(out / 'manifest.json').write_text(json.dumps({'exit_code': code, 'checks': rows,
    'scope': 'Actual unchanged existing proof suites freshly rebuilt/audited; no new targets or full core/T3 grant'}, indent=2), encoding='utf-8')
print(json.dumps({'manifest': (out / 'manifest.json').relative_to(ROOT).as_posix(), 'exit_code': code}), flush=True)
raise SystemExit(code)
