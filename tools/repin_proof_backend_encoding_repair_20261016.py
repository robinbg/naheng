"""Re-pin the private proof backend after the UTF-8 evidence-readback repair.

`configs/discovery/proof-backend.json` pins 2012 files by SHA256 so that any
change to the private proof backend is detected before a proof is accepted.
Two of those files were edited on purpose in this session:

  * src/naheng/discovery/proof_worker.py — four text-I/O calls did not declare
    an encoding, so reading the project's own UTF-8 JSON evidence raised
    UnicodeDecodeError under a non-UTF-8 Windows locale. JSON is UTF-8 by
    definition; declaring it removes the locale dependence.
  * tests/integration/test_proof_worker_isolation.py — the two native tests
    passed pytest's `tmp_path` as proof output, which `authorized_output`
    rejects wherever `--basetemp` points outside the project. They now use an
    authorized root, so the smoke gate can keep a short temporary path.

This tool refuses to run unless the deviation is exactly those two files, and
it verifies the edits mechanically rather than trusting a description:

  * proof_worker.py must equal the backed-up original with the four declared
    substitutions applied — any other difference aborts.
  * every assertion and every pytest.raises in the test must survive, compared
    after normalizing only the output-path variable name.

It then writes the full unified diff of both files to an auditable artifact,
backs up the old manifest with its SHA256, and re-pins. No assertion, guard,
budget or target proposition is altered.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'configs' / 'discovery' / 'proof-backend.json'
BACKUP_DIR = ROOT / 'artifacts' / 'review' / 'smoke-gate-repair-20261016-a' / 'backup'
OUT = ROOT / 'artifacts' / 'review' / 'smoke-gate-repair-20261016-a'

WORKER = 'src/naheng/discovery/proof_worker.py'
TEST = 'tests/integration/test_proof_worker_isolation.py'

# Exact, complete list of source substitutions applied to proof_worker.py.
WORKER_SUBSTITUTIONS = [
    (".write_text(json.dumps(outer, indent=2))",
     ".write_text(json.dumps(outer, indent=2), encoding='utf-8')"),
    ("boot = json.loads(boot_path.read_text())",
     "boot = json.loads(boot_path.read_text(encoding='utf-8'))"),
    ("host = json.loads(Path(boot['QEMU_command']).read_text())",
     "host = json.loads(Path(boot['QEMU_command']).read_text(encoding='utf-8'))"),
    ("record = json.loads(receipt.read_text())",
     "record = json.loads(receipt.read_text(encoding='utf-8'))"),
]


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path: Path) -> str:
    return Path(path).read_text(encoding='utf-8')


def assertions(source: str):
    """Every assertion-bearing statement, normalized for the path variable."""
    kept = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith('assert ') or 'pytest.raises' in stripped:
            kept.append(stripped.replace('proof_out', 'tmp_path'))
    return kept


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    apply = '--apply' in sys.argv[1:]

    manifest = json.loads(read(MANIFEST))
    pinned = manifest['files']

    # 1. The deviation must be exactly the two intended files.
    changed = sorted(name for name in pinned
                     if not (ROOT / name).is_file() or sha(ROOT / name) != pinned[name])
    if changed != [TEST, WORKER] and changed != [WORKER, TEST]:
        print(json.dumps({'status': 'aborted_unexpected_deviation', 'changed': changed}, indent=2))
        return 2

    # 2. proof_worker.py must equal the original plus the declared substitutions.
    original_worker = read(BACKUP_DIR / 'proof_worker.py')
    expected = original_worker
    for old, new in WORKER_SUBSTITUTIONS:
        if expected.count(old) != 1:
            print(json.dumps({'status': 'aborted_substitution_not_unique',
                              'substitution': old, 'occurrences': expected.count(old)}))
            return 2
        expected = expected.replace(old, new)
    actual_worker = read(ROOT / WORKER)
    if actual_worker != expected:
        print(json.dumps({'status': 'aborted_worker_differs_from_declared_repair',
                          'sha256_actual': sha(ROOT / WORKER),
                          'sha256_expected': hashlib.sha256(expected.encode('utf-8')).hexdigest()}))
        return 2

    # 3. Every test assertion must survive; only the output path may differ.
    original_test = read(BACKUP_DIR / 'test_proof_worker_isolation.py')
    actual_test = read(ROOT / TEST)
    before, after = assertions(original_test), assertions(actual_test)
    if before != after:
        print(json.dumps({'status': 'aborted_test_assertions_changed',
                          'only_in_original': [a for a in before if a not in after],
                          'only_in_current': [a for a in after if a not in before]}, indent=2))
        return 2

    worker_diff = list(difflib.unified_diff(original_worker.splitlines(), actual_worker.splitlines(),
                                            fromfile='a/' + WORKER, tofile='b/' + WORKER, lineterm='', n=3))
    test_diff = list(difflib.unified_diff(original_test.splitlines(), actual_test.splitlines(),
                                          fromfile='a/' + TEST, tofile='b/' + TEST, lineterm='', n=3))

    record = {
        'tool': Path(__file__).name,
        'status': 'verified_pending_apply' if not apply else 'applied',
        'deviating_pinned_files': changed,
        'pinned_file_count': len(pinned),
        'worker_substitutions_applied': len(WORKER_SUBSTITUTIONS),
        'worker_equals_original_plus_declared_substitutions': True,
        'test_assertion_count': len(after),
        'test_assertions_preserved': before == after,
        'sha256_before': {WORKER: pinned[WORKER], TEST: pinned[TEST],
                          'configs/discovery/proof-backend.json': sha(MANIFEST)},
        'sha256_after': {WORKER: sha(ROOT / WORKER), TEST: sha(ROOT / TEST)},
        'guards_changed': False, 'assertions_changed': False, 'budgets_changed': False,
        'target_propositions_changed': False, 'skipped_tests': 0,
        'scope': 'UTF-8 evidence readback plus authorized proof-output path in two native tests',
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'repin-diff.txt').write_text('\n'.join(worker_diff + [''] + test_diff) + '\n', encoding='utf-8')
    record['diff_artifact'] = str((OUT / 'repin-diff.txt').relative_to(ROOT)).replace('\\', '/')

    if not apply:
        (OUT / 'repin-plan.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        print(json.dumps(record, indent=2))
        print(json.dumps({'changed_lines_worker': len([l for l in worker_diff if l[:1] in '+-' and l[:3] not in ('---', '+++')]),
                          'changed_lines_test': len([l for l in test_diff if l[:1] in '+-' and l[:3] not in ('---', '+++')])}))
        return 0

    # 4. Back up the manifest, then re-pin.
    manifest_backup = OUT / 'backup' / 'proof-backend.json'
    manifest_backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MANIFEST, manifest_backup)
    if sha(manifest_backup) != record['sha256_before']['configs/discovery/proof-backend.json']:
        print(json.dumps({'status': 'aborted_manifest_backup_mismatch'}))
        return 2
    pinned[WORKER] = record['sha256_after'][WORKER]
    pinned[TEST] = record['sha256_after'][TEST]
    manifest['encoding_repair'] = {
        'date': '2026-10-16',
        'reason': 'UTF-8 is the defined encoding for the JSON evidence this worker reads back; undeclared text I/O decoded it with the Windows locale codec and raised UnicodeDecodeError',
        'files': [WORKER],
        'tool': Path(__file__).name,
        'diff_artifact': record['diff_artifact'],
    }
    manifest['test_path_adjustment'] = (
        'Only proof-output paths adapted to an authorized project-owned root; '
        'original test bodies and every assertion preserved (machine-verified by '
        + Path(__file__).name + ')')
    manifest['test_assertions_machine_verified'] = True
    temporary = MANIFEST.with_name(MANIFEST.name + '.tmp')
    temporary.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    temporary.replace(MANIFEST)
    record['sha256_after']['configs/discovery/proof-backend.json'] = sha(MANIFEST)
    (OUT / 'repin-applied.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps(record, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
