"""Strict parsing of Lean's transitive ``#print axioms`` output."""

from __future__ import annotations

import re
from collections.abc import Iterable

ALLOWED_CORE_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
_AXIOMS = re.compile(r"'([^']+)'\s+depends on axioms:\s*\[([^\]]*)\]", re.MULTILINE)
_NO_AXIOMS = re.compile(r"'([^']+)'\s+does not depend on any axioms", re.MULTILINE)


def audit_axioms(output: str, targets: Iterable[str]) -> dict:
    """Require a complete prover-generated audit for each requested target.

    This does not prove anything by itself: the checker only calls it after
    successful build and Lean execution. Source searches cannot replace it.
    """
    expected = tuple(targets)
    found: dict[str, list[str]] = {}
    duplicate: set[str] = set()
    for name, raw in _AXIOMS.findall(output):
        if name in found:
            duplicate.add(name)
        found[name] = [item.strip() for item in raw.split(",") if item.strip()]
    for name in _NO_AXIOMS.findall(output):
        if name in found:
            duplicate.add(name)
        found[name] = []
    missing = [target for target in expected if target not in found]
    rejected = {
        target: [axiom for axiom in found.get(target, []) if axiom not in ALLOWED_CORE_AXIOMS]
        for target in expected
    }
    rejected = {name: axioms for name, axioms in rejected.items() if axioms}
    duplicates = sorted(duplicate.intersection(expected))
    passed = not (missing or rejected or duplicates)
    return {
        "status": "passed" if passed else "failed",
        "targets": {target: found.get(target) for target in expected},
        "allowed_axioms": sorted(ALLOWED_CORE_AXIOMS),
        "missing": missing,
        "rejected": rejected,
        "duplicates": duplicates,
        "trust_level": "lean_kernel_core" if passed else "unaccepted",
    }
