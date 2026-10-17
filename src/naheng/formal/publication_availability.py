"""Whether the published formal evidence is present in this checkout.

Several integration tests verify that runtime behaviour is actually bound to
published formal publications: the active publication pointers, the compiled
`.olean` objects they name, and the runtime refresh that binds them. Those
artifacts are build products — `.lake/build` is deliberately not redistributed —
so a fresh clone cannot verify a binding that has not been built yet.

That is an external dependency, not a regression, and it must be visible instead
of silent. The three states stay separate, exactly as for the isolated proof
backend and the registry dataset:

* **available** — the pointers and objects are present; the tests run and assert;
* **absent** — the core has not been built here; the tests skip with the command
  that produces it. A skip is never reported as a pass;
* **present but different** — a pointer names an object that is missing, or the
  bytes under a pointer changed; the tests fail, because that is a real defect.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FORMAL = ROOT / 'artifacts' / 'formal'


def _missing_compiled_objects(manifests) -> list[str]:
    """Objects named by a publication manifest that are absent locally."""
    missing = []
    for manifest in manifests:
        hashes = manifest.get('compiled_object_hashes') or {}
        for path in hashes:
            if isinstance(path, str) and not (ROOT / path).is_file():
                missing.append(path.replace('\\', '/'))
    return missing


def _missing_referenced_objects(pointers) -> list[str]:
    """Follow each active pointer to its manifest and check the objects it names."""
    missing = []
    for pointer in pointers:
        try:
            payload = json.loads(pointer.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            missing.append(str(pointer.relative_to(ROOT)).replace('\\', '/') + ' (unreadable)')
            continue
        referenced = payload.get('manifest')
        if isinstance(referenced, str):
            manifest_path = ROOT / referenced
            if not manifest_path.is_file():
                missing.append(referenced.replace('\\', '/'))
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                missing.append(referenced.replace('\\', '/') + ' (unreadable)')
                continue
            missing += _missing_compiled_objects([manifest])
        evidence = payload.get('evidence') or []
        for row in evidence if isinstance(evidence, list) else []:
            path = row.get('olean_path') or row.get('object_path')
            if isinstance(path, str) and path and not (ROOT / path).is_file():
                missing.append(path.replace('\\', '/'))
    return missing


def missing_publication_evidence() -> list[str]:
    """Pointers and compiled objects referenced by the active publications that
    are absent from this checkout. Empty means the formal core is published here."""
    missing: list[str] = []
    pointers = [FORMAL / 'active_core.json', FORMAL / 'active_foundation.json',
                FORMAL / 'active_reduction_residual.json']
    for pointer in pointers:
        if not pointer.is_file():
            missing.append(str(pointer.relative_to(ROOT)).replace('\\', '/'))
    missing += _missing_referenced_objects([p for p in pointers if p.is_file()])
    return sorted(set(missing))


def publication_evidence_available() -> bool:
    """True only when the active pointers and every object they name exist."""
    pointers = [FORMAL / 'active_core.json', FORMAL / 'active_foundation.json']
    if not all(pointer.is_file() for pointer in pointers):
        return False
    return not missing_publication_evidence()


SKIP_REASON = (
    'the published formal evidence (active pointers and compiled objects) is a build '
    'product and is not redistributed. Run `naheng formal check --suite core` with the '
    'Lean 4.19 toolchain to produce it, then re-run. Absent evidence is a documented '
    'skip, never a pass; present-but-inconsistent evidence still fails.')


def availability_report() -> dict:
    """Self-describing status for doctor output, CI summaries and skip reasons."""
    missing = missing_publication_evidence()
    return {'active_pointers_present': all((FORMAL / name).is_file() for name in
                                           ('active_core.json', 'active_foundation.json')),
            'missing_references': missing[:5],
            'missing_count': len(missing),
            'available': publication_evidence_available(),
            'reason_if_absent': SKIP_REASON if missing else None}
