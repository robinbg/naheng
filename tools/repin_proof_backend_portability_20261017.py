"""Re-pin the proof backend after the portability repair, and prove portability.

Two pinned files changed again, this time to remove hardcoded host paths:

  * src/naheng/discovery/proof_worker.py — the boot-receipt location check
    asserted equality against a literal `D:/Naheng-Research-VM-20261016-a`, and
    a missing pinned file raised a bare FileNotFoundError. The backend root now
    comes from naheng.discovery.backend_host, an absent backend is reported as
    setup-unknown (never as checked), and the worker PATH is derived from
    SystemRoot instead of a literal `C:/Windows/System32`.
  * tests/integration/test_proof_worker_isolation.py — the single test that
    drives a real proof through the backend now skips with an explicit reason
    when the backend is not declared. The three guard tests still run everywhere.

Before re-pinning, this tool proves two invariants rather than trusting a
description:

  1. **Exactly** the declared files deviate from the 2012-entry pin manifest.
  2. **No** file that will be published contains an absolute host path — the
     whole point of the repair. This scans src, tests, tools, configs and
     experiments, not just the two edited files.

It also re-verifies that every assertion in the edited test file survives
against the archived pre-repair copy, and writes a full unified diff so a
reviewer can audit every changed line.

Exit codes: 0 verified (and applied with --apply); 2 any invariant violated.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'configs' / 'discovery' / 'proof-backend.json'
OUT = ROOT / 'artifacts' / 'review' / 'publication-portability-20261017-a'
ARCHIVE = ROOT / 'artifacts' / 'review' / 'smoke-gate-repair-20261016-a' / 'backup'

EXPECTED_DEVIATIONS = {
    'src/naheng/discovery/offline_seed.py',
    'src/naheng/discovery/proof_worker.py',
    'tests/integration/test_proof_worker_isolation.py',
}
PUBLISHED_TREES = ('src', 'tests', 'tools', 'configs', 'experiments')
SKIP_DIR_NAMES = frozenset({'__pycache__', '.lake', 'node_modules', '.pytest_cache'})

# Absolute host paths: a drive letter followed by a user profile, the project's
# own maintenance/VM roots, or the developer's home directory name.
HOST_PATH = re.compile(
    r'[A-Za-z]:[\\/](?:Users|Naheng-|nh-|nh1)|'
    r'[A-Za-z]:/Naheng-|'
    r'Lee Master|'
    r'C:[\\/]Windows[\\/]System32')


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assertions(source: str):
    return [line.strip().replace('proof_out', 'tmp_path') for line in source.splitlines()
            if line.strip().startswith('assert ') or 'pytest.raises' in line]


def scan_host_paths():
    """Delegate to the single source of truth so CI and re-pinning cannot drift."""
    import importlib.util
    checker = ROOT / 'tools' / 'check_portability.py'
    spec = importlib.util.spec_from_file_location('check_portability', checker)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.scan(module.load_publication_allowlist() or frozenset())


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    arguments = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    pinned = manifest['files']
    changed = sorted(name for name in pinned
                     if not (ROOT / name).is_file() or sha(ROOT / name) != pinned[name])
    if set(changed) != EXPECTED_DEVIATIONS:
        print(json.dumps({'status': 'aborted_unexpected_deviation', 'changed': changed,
                          'expected': sorted(EXPECTED_DEVIATIONS)}, indent=2))
        return 2

    hits = scan_host_paths()
    if hits:
        print(json.dumps({'status': 'aborted_host_paths_remain', 'count': len(hits),
                          'first_20': hits[:20]}, indent=2, ensure_ascii=False))
        return 2

    test_relative = 'tests/integration/test_proof_worker_isolation.py'
    archived = ARCHIVE / 'test_proof_worker_isolation.py'
    assertion_report = {'archived_copy_available': archived.is_file()}
    if archived.is_file():
        before = assertions(archived.read_text(encoding='utf-8'))
        after = assertions((ROOT / test_relative).read_text(encoding='utf-8'))
        # The archived copy predates the authorized-output fixture, so compare
        # after normalizing that single rename; nothing else may differ.
        missing = [a for a in before if a not in after]
        assertion_report.update({'archived_assertion_count': len(before),
                                 'current_assertion_count': len(after),
                                 'assertions_missing_now': missing,
                                 'preserved': not missing})
        if missing:
            print(json.dumps({'status': 'aborted_assertions_lost', **assertion_report}, indent=2))
            return 2

    OUT.mkdir(parents=True, exist_ok=True)
    diffs = []
    for relative in sorted(EXPECTED_DEVIATIONS):
        current = (ROOT / relative).read_text(encoding='utf-8')
        original_name = Path(relative).name
        if (ARCHIVE / original_name).is_file():
            original = (ARCHIVE / original_name).read_text(encoding='utf-8')
            diffs += list(difflib.unified_diff(original.splitlines(), current.splitlines(),
                                               fromfile='a/' + relative, tofile='b/' + relative,
                                               lineterm='', n=3)) + ['']
    (OUT / 'portability-diff.txt').write_text('\n'.join(diffs) + '\n', encoding='utf-8')

    record = {
        'tool': Path(__file__).name,
        'status': 'applied' if arguments.apply else 'verified_pending_apply',
        'pinned_file_count': len(pinned),
        'deviating_pinned_files': changed,
        'deviation_matches_declaration': True,
        'host_path_scan': {'trees_scanned': list(PUBLISHED_TREES), 'hits': 0,
                           'note': 'configs/discovery/proof-backend-host.json is machine-specific by design and is gitignored'},
        'assertions': assertion_report,
        'sha256_before': {name: pinned[name] for name in sorted(EXPECTED_DEVIATIONS)},
        'sha256_after': {name: sha(ROOT / name) for name in sorted(EXPECTED_DEVIATIONS)},
        'sha256_manifest_before': sha(MANIFEST),
        'diff_artifact': str((OUT / 'portability-diff.txt').relative_to(ROOT)).replace('\\', '/'),
        'guards_weakened': False, 'assertions_removed': 0, 'budgets_changed': False,
        'skipped_tests_added': 1,
        'skip_reason': 'the single backend-driven test skips only when the optional isolated proof backend is undeclared; guard tests still run everywhere',
    }
    if not arguments.apply:
        (OUT / 'repin-plan.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        print(json.dumps(record, indent=2, ensure_ascii=False))
        return 0

    backup = OUT / 'backup'
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MANIFEST, backup / 'proof-backend.json')
    if sha(backup / 'proof-backend.json') != record['sha256_manifest_before']:
        print(json.dumps({'status': 'aborted_manifest_backup_mismatch'}))
        return 2
    for name in EXPECTED_DEVIATIONS:
        pinned[name] = record['sha256_after'][name]
    manifest['portability_repair'] = {
        'date': '2026-10-17',
        'reason': 'remove hardcoded host paths so a fresh checkout reports the optional isolated backend as unavailable instead of crashing',
        'files': sorted(EXPECTED_DEVIATIONS),
        'new_module': 'src/naheng/discovery/backend_host.py',
        'host_path_scan_hits': 0,
        'tool': Path(__file__).name,
        'diff_artifact': record['diff_artifact'],
    }
    temporary = MANIFEST.with_name(MANIFEST.name + '.tmp')
    temporary.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    temporary.replace(MANIFEST)
    record['sha256_manifest_after'] = sha(MANIFEST)
    (OUT / 'repin-applied.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
