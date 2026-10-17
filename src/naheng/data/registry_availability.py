"""Whether the frozen public dataset's derived evidence is present locally.

The data-integration registry (`data/manifests/sources.yaml`) pins SHA256 for a
chain of evidence receipts, and that chain ends in normalized unit views derived
from a third-party public sodium-ion dataset. Those derived views total roughly
400 MiB and are **not redistributed** with this repository, for the same reason
the retrieved raw members under `data/raw/` are not: they are someone else's
measurement data under their own license. `data/manifests/` records provenance,
license and per-member SHA256 so a reader can re-download and re-derive them.

Registry-provenance tests therefore have an external data dependency. This module
makes that dependency explicit and checkable, so the tests can distinguish three
states that must never be conflated:

* **available** — the pinned views are present; the tests run and assert;
* **absent** — the dataset was not distributed here; the tests skip with a reason
  that points at the re-download manifests. A skip is never reported as a pass;
* **present but different** — the bytes do not match the frozen pins; the tests
  fail, exactly as they should.

Nothing here weakens an assertion. It only decides whether the precondition for
running one exists.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / 'data' / 'manifests' / 'sources.yaml'
REOPENED_STATUS = 'seven_complete_member_unit_views_reopened'


def _registry():
    if not REGISTRY.is_file():
        return None
    try:
        return json.loads(REGISTRY.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def pinned_unit_view_paths(root: Path | None = None) -> list[str]:
    """Registry-relative paths of the unit views the reopened claim depends on."""
    root = Path(root) if root is not None else ROOT
    registry = _registry()
    if not registry:
        return []
    paths: list[str] = []
    for source in registry.get('sources', []):
        if source.get('canonical_import_status') != REOPENED_STATUS:
            continue
        for member in source.get('raw_members', []):
            view = member.get('canonical_view')
            if not isinstance(view, dict):
                continue
            for key in ('view', 'member_manifest', 'actual_reopened_audit'):
                value = view.get(key)
                if isinstance(value, str) and value:
                    paths.append(value.replace('\\', '/'))
        acceptance = source.get('canonical_view_acceptance', {})
        for role in ('normal_entry_handoff', 'independent_review'):
            reference = acceptance.get(role)
            if isinstance(reference, dict) and isinstance(reference.get('path'), str):
                paths.append(reference['path'].replace('\\', '/'))
    return sorted(set(paths))


def _present(root: Path, relative: str) -> bool:
    """A pinned reference may name a file or a directory holding a unit view.

    A view directory ships with its small `manifest.json` but not with the
    derived `observations.jsonl.gz` payload, which is several MiB per member and
    is not redistributed. Directory existence alone would therefore report the
    dataset as present in a checkout that cannot actually run the validation, so
    a directory counts as present only when its payload is there too.
    """
    path = root / relative
    if path.is_file():
        return True
    if not path.is_dir():
        return False
    return any(path.glob('*.jsonl.gz'))


def missing_unit_view_evidence(root: Path | None = None) -> list[str]:
    """Pinned evidence absent from this checkout. Empty means the data is present."""
    root = Path(root) if root is not None else ROOT
    return [relative for relative in pinned_unit_view_paths(root)
            if not _present(root, relative)]


def unit_view_evidence_available(root: Path | None = None) -> bool:
    """True only when every pinned unit-view receipt is present."""
    paths = pinned_unit_view_paths(root)
    return bool(paths) and not missing_unit_view_evidence(root)


SKIP_REASON = (
    'the frozen public dataset\'s derived unit views are not redistributed with this '
    'repository; see data/manifests/ for provenance, license and re-download. Absent '
    'data is a documented skip, never a pass, and a present-but-different byte still '
    'fails the assertion.')


def availability_report(root: Path | None = None) -> dict:
    """Self-describing status for doctor output, CI summaries and skip reasons."""
    root = Path(root) if root is not None else ROOT
    paths = pinned_unit_view_paths(root)
    missing = missing_unit_view_evidence(root)
    return {'registry_present': REGISTRY.is_file(),
            'pinned_unit_view_count': len(paths),
            'missing_count': len(missing),
            'missing_examples': missing[:5],
            'available': bool(paths) and not missing,
            'redistributed': False,
            'reason_if_absent': SKIP_REASON if missing else None}
