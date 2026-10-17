"""Normalize machine-specific path prefixes in two test fixtures, in place.

`tests/fixtures/calibration_builtin/manifest.json` records the provenance of the
fixture files it pins, and `tests/fixtures/evidence_report/legacy-command.json`
is a real historical command receipt. Both therefore embed the absolute path of
the machine that produced them, including the developer's home directory.

Neither file's bytes are asserted by a test:

  * `tests/integration/test_calibration_runtime.py` hashes the files *listed in*
    `manifest['files']`, not `manifest.json` itself, so rewriting the `original`
    provenance strings leaves every recorded SHA256 valid;
  * `tests/unit/test_evidence_report.py` compares values derived from the receipt
    against the receipt's own fields, so both sides move together.

This tool applies exactly the rules the publication builder uses, backs up both
originals with their SHA256, and then re-runs the two affected tests is left to
the caller so the exit codes stay attributable.

Exit codes: 0 normalized (or already clean); 2 a rule matched nothing, which
would mean the fixtures drifted and the rules need review.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / 'artifacts' / 'review' / 'publication-portability-20261017-a' / 'backup'

TARGETS = (
    'tests/fixtures/calibration_builtin/manifest.json',
    'tests/fixtures/evidence_report/legacy-command.json',
)


def load_rules():
    """Reuse the publication builder's rules so the two cannot drift apart."""
    builder = ROOT / 'tools' / 'build_publication_bundle.py'
    spec = importlib.util.spec_from_file_location('publication_builder', builder)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.NORMALIZATION_RULES


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    apply = '--apply' in sys.argv[1:]
    rules = load_rules()
    BACKUP.mkdir(parents=True, exist_ok=True)
    record = {}
    unmatched = 0
    for relative in TARGETS:
        path = ROOT / relative
        original_bytes = path.read_bytes()
        text = original_bytes.decode('utf-8')
        rewritten = text
        for pattern, replacement in rules:
            rewritten = pattern.sub(replacement, rewritten)
        backup = BACKUP / path.name
        if not backup.exists():
            shutil.copy2(path, backup)
        entry = {
            'sha256_before': hashlib.sha256(original_bytes).hexdigest(),
            'backup': str(backup.relative_to(ROOT)).replace('\\', '/'),
            'changed': rewritten != text,
            'host_prefix_occurrences_before': sum(1 for _ in __import__('re').finditer(
                r'Lee Master', text)),
            'host_prefix_occurrences_after': sum(1 for _ in __import__('re').finditer(
                r'Lee Master', rewritten)),
        }
        if not entry['changed']:
            unmatched += 1
        if apply and entry['changed']:
            path.write_bytes(rewritten.encode('utf-8'))
            entry['sha256_after'] = hashlib.sha256(path.read_bytes()).hexdigest()
        record[relative] = entry
    report = {'tool': Path(__file__).name, 'applied': apply, 'files': record,
              'rules_reused_from': 'tools/build_publication_bundle.py',
              'rule_count': len(rules)}
    (BACKUP / 'fixture-normalization.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if unmatched == len(TARGETS):
        print(json.dumps({'status': 'no_rule_matched_any_target',
                          'hint': 'the fixtures drifted; review the normalization rules'}))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
