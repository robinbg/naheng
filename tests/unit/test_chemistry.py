from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import pytest
import numpy as np

from naheng.domain.chemistry import ChemistryError, Reaction, load_chemistry
from naheng.models.site_model import SiteModel

CONFIG = Path(__file__).resolve().parents[2] / "configs/models/two_site_research.yaml"


def test_exact_inventory_charge_and_effective_product():
    chemistry = load_chemistry(CONFIG)
    chemistry.validate()
    formal = chemistry.formal_input()
    assert formal["reactions"][0]["stoichiometry"]["electron"] == "-1"
    assert {s.name for s in chemistry.species} >= {"Na_plus", "electron", "P1", "P2"}
    for p in chemistry.parameters.values(): assert p.source_id and p.unit


def test_unbalanced_inventory_and_charge_rejected():
    chemistry = load_chemistry(CONFIG)
    with pytest.raises(ChemistryError, match="element"):
        replace(chemistry, reactions=(Reaction("bad", {"Na_plus": Fraction(-1), "S1": Fraction(-1), "NaS1": Fraction(2)}),)).validate()
    with pytest.raises(ChemistryError, match="charge"):
        replace(chemistry, reactions=(Reaction("bad", {"Na_plus": Fraction(-1), "S1": Fraction(-1), "NaS1": Fraction(1)}),)).validate()


def test_numerical_implementation_matches_declared_ast():
    chemistry, model = load_chemistry(CONFIG), SiteModel()
    state = model.initial_state(soc=.42)
    state[1] = .63
    state[4] = 310
    drive = model.solve_drive(state, .15)
    values = {name: p.value for name, p in chemistry.parameters.items()}
    values.update(dict(zip(("x1", "x2", "trapped_mol", "reservoir_mol", "T"), state)))
    values["u"] = drive
    actual = model.rhs(0, state, .15)
    expected = [chemistry.dynamics[name].evaluate(values) for name in ("x1", "x2", "trapped_mol", "reservoir_mol")]
    assert np.allclose(actual[:4], expected, rtol=1e-12, atol=1e-14)
