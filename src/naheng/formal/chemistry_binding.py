"""Concrete, coefficient-only binding of the two-site DSL to T0 evidence.

PASS means that the declared E, z and S agree with the checked finite
reaction template. It grants neither kinetic reduction nor output safety.
The actual runtime parameter and source identities are retained even though
these algebraic statements do not constrain a particular rate constant.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
from typing import Literal, Mapping

from naheng.domain.chemistry import ChemistryDefinition, ChemistryError, load_chemistry
from naheng.models.site_model import SiteParameters
from naheng.packages.evidence_import import load_evidence

Status = Literal["PASS", "FAIL", "UNKNOWN"]
_SPECIES = {
    "Na_plus": ({"Na": 1}, 1), "electron": ({}, -1),
    "S1": ({"site1": 1}, 0), "S2": ({"site2": 1}, 0),
    "NaS1": ({"Na": 1, "site1": 1}, 0),
    "NaS2": ({"Na": 1, "site2": 1}, 0),
    "P1": ({"Na": 1}, 0), "P2": ({"Na": 1}, 0),
}
_PROJECTION = {"Na_plus": "sodiumIon", "electron": "electron",
               "S1": "vacantSite", "S2": "vacantSite",
               "NaS1": "occupiedSite", "NaS2": "occupiedSite",
               "P1": "trappedProduct", "P2": "trappedProduct"}
_ELEMENT_PROJECTION = {"Na": "sodium", "site1": "site", "site2": "site"}
_COMPOSITION = {("sodium", "sodiumIon"): 1, ("sodium", "occupiedSite"): 1,
                ("sodium", "trappedProduct"): 1, ("site", "vacantSite"): 1,
                ("site", "occupiedSite"): 1}
_CHARGE = {"sodiumIon": 1, "electron": -1}
_TEMPLATE_S = {
    "insertion": {"sodiumIon": -1, "electron": -1, "vacantSite": -1, "occupiedSite": 1},
    "extraction": {"sodiumIon": 1, "electron": 1, "vacantSite": 1, "occupiedSite": -1},
    "trapping": {"occupiedSite": -1, "vacantSite": 1, "trappedProduct": 1},
}
_DECLARATIONS = {
    "Naheng.Chemistry.element_stoichiometry_balanced": ("composition", "stoichiometry"),
    "Naheng.Chemistry.charge_stoichiometry_balanced": ("charge", "stoichiometry"),
    "Naheng.Chemistry.element_rate_from_ports": ("composition", "amountRate"),
    "Naheng.Chemistry.charge_rate_from_ports": ("charge", "amountRate"),
}
_FORMAL_FILES = ("formal/Naheng/Chemistry/Species.lean",
                 "formal/Naheng/Chemistry/Reaction.lean",
                 "formal/Naheng/Chemistry/Balance.lean", "formal/lean-toolchain")
_SHA = re.compile(r"[0-9a-f]{64}")
_APPROVED_STATEMENTS = {
    "element_stoichiometry_balanced": "(element : Element) (reaction : Reaction) : (∑ species : Species, composition element species * stoichiometry species reaction) = 0",
    "charge_stoichiometry_balanced": "(reaction : Reaction) : (∑ species : Species, charge species * stoichiometry species reaction) = 0",
    "element_rate_from_ports": "(element : Element) (v : Reaction → ℝ) (b : PortFlux) : (∑ species : Species, composition element species * amountRate v b species) = ∑ species : Species, composition element species * b species",
    "charge_rate_from_ports": "(v : Reaction → ℝ) (b : PortFlux) : (∑ species : Species, charge species * amountRate v b species) = ∑ species : Species, charge species * b species",
}
# Actual Lean 4.19 #print expands declaration binders to a forall type. These
# four exact propositions retain the same quantifiers and conclusions; source
# statement validation above remains independent of this printer calibration.
_APPROVED_PRINTED_TYPES = {
    "element_stoichiometry_balanced": ": ∀ (element : Element) (reaction : Reaction), (∑ species : Species, composition element species * stoichiometry species reaction) = 0",
    "charge_stoichiometry_balanced": ": ∀ (reaction : Reaction), (∑ species : Species, charge species * stoichiometry species reaction) = 0",
    "element_rate_from_ports": ": ∀ (element : Element) (v : Reaction → ℝ) (b : PortFlux), (∑ species : Species, composition element species * amountRate v b species) = ∑ species : Species, composition element species * b species",
    "charge_rate_from_ports": ": ∀ (v : Reaction → ℝ) (b : PortFlux), (∑ species : Species, charge species * amountRate v b species) = ∑ species : Species, charge species * b species",
}


@dataclass(frozen=True)
class BindingCheck:
    name: str
    status: Status
    reason: str


@dataclass(frozen=True)
class DeclarationReference:
    evidence_id: str
    declaration: str
    statement_hash: str


@dataclass(frozen=True)
class ChannelProjection:
    channel: int
    species: tuple[tuple[str, str], ...]
    reactions: tuple[tuple[str, str], ...]
    coefficients: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class BindingIdentity:
    package_id: str
    package_hash: str
    chemistry_id: str
    model_kind: str
    source_id: str
    backend: str
    parameter_revision: str
    parameter_hash: str
    source_hashes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ChemistryBinding:
    status: Status
    checks: tuple[BindingCheck, ...]
    identity: BindingIdentity | None = None
    channels: tuple[ChannelProjection, ...] = ()
    declarations: tuple[DeclarationReference, ...] = ()
    proof_artifact_hashes: tuple[tuple[str, str], ...] = ()
    scope: str = "T0 declared synthetic stoichiometry and instantaneous open-port bookkeeping only"
    grants_reduction: bool = False
    grants_strict_safety: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _content_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _controlled(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name:
        raise ValueError("Controlled project source path required")
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Bound source/artifact is outside the project or missing")
    return path


def _fresh_hashes(root: Path, hashes: Mapping[str, str]) -> None:
    if not hashes:
        raise ValueError("Actual source hashes are required")
    for name, expected in hashes.items():
        if not isinstance(expected, str) or not _SHA.fullmatch(expected):
            raise ValueError("Invalid source/artifact hash")
        if hashlib.sha256(_controlled(root, name).read_bytes()).hexdigest() != expected:
            raise ValueError("Stale bound source/artifact hash")


def _identity(root: Path, package: Mapping, parameters: SiteParameters) -> BindingIdentity:
    for name in ("package_id", "package_hash", "parameter_revision", "parameter_hash"):
        if not isinstance(package.get(name), str) or not package[name]:
            raise ValueError("Registered package identity/hash/revision is required")
    dynamics = package.get("dynamics_ast", {})
    if package.get("chemistry_id") != "synthetic_two_site" or parameters.model_kind != "theory_fixture":
        raise ValueError("Chemistry/model identity is outside the synthetic template")
    if dynamics.get("model") != "two_site_current_adapter_v1":
        raise ValueError("Dynamics backend has no binding to the two-site chemistry")
    actual_parameter_hash = _content_hash(asdict(parameters))
    if package["parameter_hash"] != actual_parameter_hash:
        raise ValueError("Actual runtime parameters differ from registered parameter hash")
    hashes = package.get("binding_hashes", {})
    required = {dynamics.get("source"), "src/naheng/models/site_model.py",
                "src/naheng/models/thermal.py", "src/naheng/models/degradation.py"}
    if not isinstance(hashes, dict) or not required.issubset(hashes):
        raise ValueError("Registered chemistry and executable dependency hashes are required")
    _fresh_hashes(root, hashes)
    return BindingIdentity(package["package_id"], package["package_hash"], package["chemistry_id"],
                           parameters.model_kind, parameters.source_id, dynamics["model"],
                           package["parameter_revision"], actual_parameter_hash, tuple(sorted(hashes.items())))


def _project_chemistry(chemistry: ChemistryDefinition) -> tuple[ChannelProjection, ...]:
    chemistry.validate()
    if (chemistry.chemistry_id, chemistry.model_kind, chemistry.source_id) != (
            "synthetic_two_site", "theory_fixture", "synthetic-two-site-v1"):
        raise ValueError("DSL chemistry/model/source identity does not match the template")
    species = {item.name: item for item in chemistry.species}
    if set(species) != set(_SPECIES):
        raise ValueError("Expected exactly the eight declared two-site species")
    for name, (elements, charge) in _SPECIES.items():
        item = species[name]
        if dict(item.elements) != elements or item.charge != charge:
            raise ValueError(f"Element or charge coefficients differ for {name}")
        projected = {}
        for element, count in item.elements.items():
            target = _ELEMENT_PROJECTION[element]
            projected[target] = projected.get(target, 0) + count
        expected = {element: count for (element, sp), count in _COMPOSITION.items()
                    if sp == _PROJECTION[name]}
        if projected != expected or item.charge != _CHARGE.get(_PROJECTION[name], 0):
            raise ValueError("Element/charge projection differs from the five-species template")
    reactions = {item.name: item for item in chemistry.reactions}
    if set(reactions) != {"insertion1", "insertion2", "trapping1", "trapping2"}:
        raise ValueError("Expected exactly four declared insertion/trapping reactions")
    channels = []
    for channel in (1, 2):
        local = {"Na_plus": "sodiumIon", "electron": "electron", f"S{channel}": "vacantSite",
                 f"NaS{channel}": "occupiedSite", f"P{channel}": "trappedProduct"}
        coefficients = []
        for kind in ("insertion", "trapping"):
            name = f"{kind}{channel}"
            actual = {sp: Fraction(value) for sp, value in reactions[name].stoichiometry.items() if value}
            expected = {sp: Fraction(_TEMPLATE_S[kind].get(target, 0))
                        for sp, target in local.items() if _TEMPLATE_S[kind].get(target, 0)}
            if actual != expected:
                raise ValueError(f"Exact stoichiometry or channel identity differs for {name}")
            coefficients.extend((name, local[sp], str(value)) for sp, value in sorted(actual.items()))
        channels.append(ChannelProjection(channel, tuple(sorted(local.items())),
            ((f"insertion{channel}", "insertion"), (f"trapping{channel}", "trapping")),
            tuple(coefficients)))
    return tuple(channels)


def _definition(text: str, name: str) -> str:
    text = re.sub(r"/\-.*?\-/|--[^\n]*", "", text, flags=re.DOTALL)
    match = re.search(r"\bdef " + re.escape(name) + r"\b(.*?)(?=\n(?:def|abbrev|theorem|end)\b)", text, re.DOTALL)
    if not match or "ℝ" not in match[1]:
        raise ValueError("Unsupported formal template definition")
    return match[1]


def _formal_template(root: Path) -> None:
    """Parse only the finite integer table grammar; no arbitrary Lean execution."""
    species = _controlled(root, _FORMAL_FILES[0]).read_text(encoding="utf-8")
    reaction = _controlled(root, _FORMAL_FILES[1]).read_text(encoding="utf-8")
    _finite_constructors(species, "Species", tuple(_TEMPLATE_S["insertion"]) + ("trappedProduct",))
    _finite_constructors(species, "Element", ("sodium", "site"))
    _finite_constructors(reaction, "Reaction", ("insertion", "extraction", "trapping"))
    composition = _finite_rows(_definition(species, "composition"), ": Element → Species → ℝ", 2)
    charge = _finite_rows(_definition(species, "charge"), ": Species → ℝ", 1)
    stoichiometry = _finite_rows(_definition(reaction, "stoichiometry"), ": Species → Reaction → ℝ", 2)
    if composition != _COMPOSITION:
        raise ValueError("Formal element table differs from the supported template")
    if charge != _CHARGE:
        raise ValueError("Formal charge table differs from the supported template")
    expected = {(species, kind): coefficient for kind, table in _TEMPLATE_S.items()
                for species, coefficient in table.items()}
    if stoichiometry != expected:
        raise ValueError("Formal stoichiometric table differs from the supported template")


def _finite_constructors(source: str, name: str, expected: tuple[str, ...]) -> None:
    source = re.sub(r"/\-.*?\-/|--[^\n]*", "", source, flags=re.DOTALL)
    match = re.search(r"\binductive\s+" + name + r"\b(.*?)\bderiving\b", source, re.DOTALL)
    if not match:
        raise ValueError("Formal finite type is missing")
    members = re.findall(r"\|\s*(\w+)", match[1])
    if (len(members) != len(expected) or set(members) != set(expected)
            or re.sub(r"\|\s*\w+", "", match[1]).strip()):
        raise ValueError("Formal finite constructors differ from the supported template")


def _finite_rows(table: str, signature: str, arity: int) -> dict:
    lines = [line.strip() for line in table.splitlines() if line.strip()]
    if not lines or re.sub(r"\s", "", lines[0]) != re.sub(r"\s", "", signature):
        raise ValueError("Unsupported formal finite table signature")
    pattern = (r"\|\s*\.(\w+)\s*,\s*\.(\w+)\s*=>\s*(-?\d+)" if arity == 2
               else r"\|\s*\.(\w+)\s*=>\s*(-?\d+)")
    default = r"\|\s*_,\s*_\s*=>\s*0" if arity == 2 else r"\|\s*_\s*=>\s*0"
    if len(lines) < 2 or not re.fullmatch(default, lines[-1]):
        raise ValueError("Formal finite table lacks its final zero default")
    rows = {}
    for line in lines[1:-1]:
        match = re.fullmatch(pattern, line)
        if not match:
            raise ValueError("Unsupported formal table expression; exact integer cases required")
        values = match.groups()
        key = tuple(values[:-1]) if arity == 2 else values[0]
        if key in rows:
            raise ValueError("Duplicate formal table case")
        rows[key] = int(values[-1])
    return rows


def _canonical_statement(text: str) -> str:
    # Normalize printer qualification, binder notation and layout, not logic.
    text = text.replace("Naheng.Chemistry.", "").replace("Real", "ℝ")
    text = re.sub(r"∑\s+(\w+)\s*:\s*Species\s*,", r"∑\1,", text)
    return re.sub(r"[\s()]", "", text)


def _statement_scope(root: Path, declaration: str, statement: str) -> None:
    name = declaration.rsplit(".", 1)[1]
    path = _FORMAL_FILES[1] if "stoichiometry" in name else _FORMAL_FILES[2]
    source = _controlled(root, path).read_text(encoding="utf-8")
    source = re.sub(r"/\-.*?\-/|--[^\n]*", "", source, flags=re.DOTALL)
    matches = re.findall(r"\btheorem\s+" + re.escape(name) + r"\b(.*?)(?=\s*:=)", source, re.DOTALL)
    if len(matches) != 1 or _canonical_statement(matches[0]) != _canonical_statement(_APPROVED_STATEMENTS[name]):
        raise ValueError("Formal declaration hypotheses/conclusion differ from the approved T0 statement")
    expected = "theorem " + declaration + " " + _APPROVED_STATEMENTS[name]
    printed = "theorem " + declaration + " " + _APPROVED_PRINTED_TYPES[name]
    if _canonical_statement(statement) not in {_canonical_statement(expected), _canonical_statement(printed)}:
        raise ValueError("Elaborated declaration is outside the approved T0 statement scope")


def bind_chemistry(root: Path, package: Mapping, parameters: SiteParameters,
                   manifest_path: Path | None = None,
                   *, expected_identity: BindingIdentity | None = None) -> ChemistryBinding:
    """Bind an already registered package and the actual worker parameters.

    Missing checked declarations returns UNKNOWN. Invalid chemistry, identity,
    or stale artifacts returns FAIL. Empirical fallback is a caller decision;
    this function never grants a reduction or strict output-error certificate.
    """
    root = Path(root).resolve()
    checks = []
    identity = None
    channels = ()
    try:
        identity = _identity(root, package, parameters)
        if expected_identity is not None and identity != expected_identity:
            raise ValueError("Runtime model/package/parameter/source identity changed")
        chemistry = load_chemistry(_controlled(root, package["dynamics_ast"]["source"]))
        if chemistry.source_id != parameters.source_id:
            raise ValueError("Actual runtime parameter source differs from the DSL")
        channels = _project_chemistry(chemistry)
        _formal_template(root)
    except (ValueError, ChemistryError, KeyError, TypeError, OSError) as error:
        return ChemistryBinding("FAIL", (BindingCheck("chemical_template", "FAIL", str(error)),), identity)
    checks.append(BindingCheck("chemical_template", "PASS", "Exact E, z and S match both explicit channel projections"))
    if manifest_path is None or not Path(manifest_path).is_file():
        checks.append(BindingCheck("foundation_declarations", "UNKNOWN", "No checked declaration manifest is available"))
        return ChemistryBinding("UNKNOWN", tuple(checks), identity, channels)
    try:
        imported = load_evidence(root, manifest_path)
        rows = {row["declaration"]: row for row in imported["records"]}
        if not set(_DECLARATIONS).issubset(rows):
            checks.append(BindingCheck("foundation_declarations", "UNKNOWN", "Required T0 coefficient/open-port declarations are absent; other theorem scopes cannot substitute"))
            return ChemistryBinding("UNKNOWN", tuple(checks), identity, channels)
        references = []
        artifacts = {}
        toolchain = _controlled(root, "formal/lean-toolchain").read_text(encoding="utf-8").strip()
        for declaration, symbols in _DECLARATIONS.items():
            row = rows[declaration]
            if row.get("toolchain") != toolchain:
                raise ValueError("Declaration toolchain differs from the project lock")
            if any(not re.search(r"\b" + symbol + r"\b", row["statement"]) for symbol in symbols):
                raise ValueError("Declaration statement does not have the required T0 chemical scope")
            _statement_scope(root, declaration, row["statement"])
            if not set(_FORMAL_FILES).issubset(row["artifacts"]):
                raise ValueError("Declaration is not bound to the actual formal chemistry source tables")
            for name, value in row["artifacts"].items():
                if name in artifacts and artifacts[name] != value:
                    raise ValueError("Declaration artifact identities conflict")
                artifacts[name] = value
            references.append(DeclarationReference(row["evidence_id"], declaration, row["statement_hash"]))
        path = Path(manifest_path).resolve()
        artifacts[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    except (ValueError, KeyError, TypeError, OSError) as error:
        status = "UNKNOWN" if str(error) in {"Unverified evidence", "No exported proof evidence"} else "FAIL"
        checks.append(BindingCheck("foundation_declarations", status, str(error)))
        return ChemistryBinding(status, tuple(checks), identity, channels)
    checks.append(BindingCheck("foundation_declarations", "PASS", "Imported individual T0 declarations retain statement, source and axiom-audit identities"))
    return ChemistryBinding("PASS", tuple(checks), identity, channels, tuple(references), tuple(sorted(artifacts.items())))


def revalidate_binding(root: Path, binding: ChemistryBinding, package: Mapping,
                       parameters: SiteParameters) -> BindingCheck:
    """Call before a proof-backed runtime use; byte/parameter changes withdraw it."""
    if binding.status != "PASS" or binding.identity is None:
        return BindingCheck("chemical_binding_freshness", "UNKNOWN", "No applicable checked T0 binding")
    root = Path(root).resolve()
    try:
        if _identity(root, package, parameters) != binding.identity:
            raise ValueError("Runtime model/package/parameter/source identity changed")
        _fresh_hashes(root, dict(binding.proof_artifact_hashes))
    except (ValueError, KeyError, TypeError, OSError) as error:
        return BindingCheck("chemical_binding_freshness", "FAIL", str(error))
    return BindingCheck("chemical_binding_freshness", "PASS", "Actual model, parameters and imported T0 artifacts remain bound")
