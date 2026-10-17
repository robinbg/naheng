"""Exact stoichiometric bookkeeping for declared effective chemistry."""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Mapping

import yaml

from .expressions import Expression, parse_expression


class ChemistryError(ValueError):
    pass


@dataclass(frozen=True)
class Species:
    name: str
    elements: Mapping[str, int]
    charge: int
    description: str = ""


@dataclass(frozen=True)
class Reaction:
    name: str
    stoichiometry: Mapping[str, Fraction]


@dataclass(frozen=True)
class ChemicalParameter:
    value: float
    unit: str
    source_id: str


@dataclass(frozen=True)
class ChemistryDefinition:
    chemistry_id: str
    model_kind: str
    species: tuple[Species, ...]
    reactions: tuple[Reaction, ...]
    parameters: Mapping[str, ChemicalParameter]
    dynamics: Mapping[str, Expression] = field(default_factory=dict)
    source_id: str = ""

    def validate(self) -> None:
        if not self.chemistry_id or not self.source_id:
            raise ChemistryError("chemistry identity and source are required")
        species = {x.name: x for x in self.species}
        if len(species) != len(self.species) or not species:
            raise ChemistryError("species must be finite, nonempty and uniquely named")
        for item in species.values():
            if not item.name.isidentifier() or any(type(n) is not int or n < 0 for n in item.elements.values()):
                raise ChemistryError("invalid species or element count")
        elements = {el for item in species.values() for el in item.elements}
        names = set()
        for reaction in self.reactions:
            if reaction.name in names or not reaction.stoichiometry:
                raise ChemistryError("reactions must be uniquely named and nonempty")
            names.add(reaction.name)
            if set(reaction.stoichiometry) - set(species):
                raise ChemistryError(f"unknown species in {reaction.name}")
            for element in elements:
                residual = sum(Fraction(coef) * species[name].elements.get(element, 0) for name, coef in reaction.stoichiometry.items())
                if residual:
                    raise ChemistryError(f"element {element} not balanced in {reaction.name}: {residual}")
            charge = sum(Fraction(coef) * species[name].charge for name, coef in reaction.stoichiometry.items())
            if charge:
                raise ChemistryError(f"charge not balanced in {reaction.name}: {charge}")
        for name, parameter in self.parameters.items():
            if not parameter.unit or not parameter.source_id:
                raise ChemistryError(f"parameter {name} lacks unit or source")

    def formal_input(self) -> dict:
        """Same exact coefficients consumed by numerical registration and proof inputs."""
        self.validate()
        return {"chemistry_id": self.chemistry_id, "source_id": self.source_id,
                "species": [{"name": x.name, "elements": dict(x.elements), "charge": x.charge} for x in self.species],
                "reactions": [{"name": r.name, "stoichiometry": {n: str(Fraction(c)) for n, c in r.stoichiometry.items()}} for r in self.reactions],
                "dynamics_ast": {name: expr.to_dict() for name, expr in self.dynamics.items()}}


def load_chemistry(path: str | Path) -> ChemistryDefinition:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    params = {name: ChemicalParameter(**value) for name, value in data["parameters"].items()}
    variables = set(params) | set(data.get("state_names", [])) | {"u", "T"}
    chemistry = ChemistryDefinition(
        chemistry_id=data["chemistry_id"], model_kind=data["model_kind"], source_id=data["source_id"],
        species=tuple(Species(**item) for item in data["species"]),
        reactions=tuple(Reaction(item["name"], {name: Fraction(str(coef)) for name, coef in item["stoichiometry"].items()}) for item in data["reactions"]),
        parameters=params, dynamics={name: parse_expression(value, variables) for name, value in data.get("dynamics", {}).items()})
    chemistry.validate()
    return chemistry
