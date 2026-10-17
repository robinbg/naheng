"""Run the complete suite once, sealing source/test identities before and after."""
from datetime import datetime, timezone
import json
import argparse
from pathlib import Path
import sys
import uuid
from naheng.formal.checker import run_command
from naheng.runtime.artifacts import atomic_json, code_hash, iter_source_files, sha256_file

ROOT = Path(__file__).resolve().parents[1]


def identities():
    paths = list(iter_source_files(ROOT)) + sorted((ROOT / 'tests').rglob('*.py'))
    paths += sorted((ROOT / 'tests/fixtures/calibration_builtin').glob('*.json'))
    return {p.relative_to(ROOT).as_posix(): sha256_file(p) for p in paths}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--temp-root', type=Path)
    parser.add_argument('--batch-timeout-s', type=int, default=360)
    options = parser.parse_args()
    assert 1 <= options.batch_timeout_s <= 1800  # engineering batch, not simulation/proof limits
    token = uuid.uuid4().hex[:8]
    out = ROOT / 'artifacts/progress' / ('E02-current-regression-' + token)
    out.mkdir(parents=True, exist_ok=False)
    before, digest = identities(), code_hash(ROOT)
    # Keep the Windows snapshot/forecast paths below MAX_PATH without altering
    # any business test or filesystem policy. Each run gets a new directory.
    temp_root = ROOT.parents[3] if options.temp_root is None else options.temp_root.resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    temp = temp_root / ('.nh-t-' + token)
    assert not temp.exists()
    command = [sys.executable, '-m', 'pytest', '-q', '--basetemp', str(temp)]
    atomic_json(out / 'started.json', {'utc': datetime.now(timezone.utc).isoformat(), 'code_hash': digest,
                'source_and_test_hashes': before, 'argv': command, 'timeout_s': options.batch_timeout_s})
    result = run_command(command, ROOT, out / 'pytest.log', timeout=options.batch_timeout_s)
    after = identities()
    stable = before == after and digest == code_hash(ROOT)
    code = result['exit_code'] if stable else 2
    atomic_json(out / 'manifest.json', {'exit_code': code, 'code_hash_before': digest,
                'code_hash_after': code_hash(ROOT), 'source_and_test_hashes': before,
                'source_and_test_bytes_unchanged': stable, 'actual_command': result,
                'scope': 'Complete current code regression; no GUI, release or scientific acceptance inferred'})
    print(json.dumps({'manifest': (out / 'manifest.json').relative_to(ROOT).as_posix(), 'exit_code': code,
                      'source_stable': stable, 'code_hash': digest}), flush=True)
    raise SystemExit(code)


if __name__ == '__main__':
    main()
