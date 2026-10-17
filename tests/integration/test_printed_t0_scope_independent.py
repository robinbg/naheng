"""Independent negative calibration using actual Lean #print propositions.

These are validator tests, not newly executed Lean proofs or product paths.
"""
import json
from pathlib import Path
import re
import shutil

import pytest

from naheng.formal.chemistry_binding import _statement_scope

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "artifacts/formal/foundation-20261012-seventeen/manifest.json"
TARGETS = (
    "Naheng.Chemistry.element_stoichiometry_balanced",
    "Naheng.Chemistry.charge_stoichiometry_balanced",
    "Naheng.Chemistry.element_rate_from_ports",
    "Naheng.Chemistry.charge_rate_from_ports",
)
ROWS = {row["declaration"]: row for row in json.loads(MANIFEST.read_text(encoding="utf-8"))["evidence"]}


@pytest.mark.parametrize("target", TARGETS)
def test_actual_printed_forall_type_is_accepted_without_logic_changes(target):
    row = ROWS[target]
    assert " : ∀ " in row["statement"]
    assert row["status"] == "checked"
    _statement_scope(ROOT, target, row["statement"])


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("mutation", (
    "false_binder", "extra_true_binder", "false_implication", "existential",
    "inequality_conclusion", "conclusion_or_true",
))
def test_extra_hypothesis_quantifier_or_conclusion_cannot_enter_printed_allowlist(target, mutation):
    original = ROWS[target]["statement"]
    if mutation == "false_binder":
        altered = original.replace(" : ∀ ", " : ∀ (h : False) ", 1)
    elif mutation == "extra_true_binder":
        altered = original.replace(" : ∀ ", " : ∀ (h : True) ", 1)
    elif mutation == "false_implication":
        altered = original.replace(" : ∀ ", " : False → ∀ ", 1)
    elif mutation == "existential":
        altered = original.replace(" : ∀ ", " : ∃ ", 1)
    elif mutation == "inequality_conclusion":
        altered = re.sub(r"\s=\s", " ≤ ", original, count=1)
    else:
        altered = original + " ∨ True"
    assert altered != original, "Negative calibration must actually alter its input"
    with pytest.raises(ValueError, match="outside the approved T0 statement scope"):
        _statement_scope(ROOT, target, altered)


@pytest.mark.parametrize("target", TARGETS)
def test_source_hypothesis_check_stays_independent_of_printer_calibration(tmp_path, target):
    name = target.rsplit(".", 1)[1]
    relative = "formal/Naheng/Chemistry/Reaction.lean" if "stoichiometry" in name else "formal/Naheng/Chemistry/Balance.lean"
    destination = tmp_path / relative
    destination.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / relative, destination)
    original = destination.read_text(encoding="utf-8")
    altered = original.replace("theorem " + name, "theorem " + name + " (h : False)", 1)
    assert altered != original
    destination.write_text(altered, encoding="utf-8")
    with pytest.raises(ValueError, match="hypotheses/conclusion differ"):
        _statement_scope(tmp_path.resolve(), target, ROWS[target]["statement"])
