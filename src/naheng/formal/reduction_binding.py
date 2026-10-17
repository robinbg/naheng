"""Audited instantaneous site-rate bounds applied to permitted posterior states.

Exact rational arithmetic evaluates the proved real polynomial on represented
IEEE coefficients. Exponential/current-root and ODE rounding remain empirical;
this grants neither a future aggregate model nor strict physical safety.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

from naheng.estimation.particle_filter import particle_model
from naheng.formal.chemistry_binding import bind_chemistry, _content_hash
from naheng.formal.runtime_binding import _file, _package, _sha, _snapshot
from naheng.models.site_model import SiteModel
from naheng.packages.evidence_import import load_evidence

_FORMAL_HASHES = {
    "formal/Naheng/Reduction/Exact.lean": "1b1a53b81ba993ed8ba4cb0edc71bacf14a34bc4f1efb44cf00412faf43de392",
    "formal/Naheng/Reduction/Residual.lean": "0e22d7b8518b8fd231437f29290d6f2effb3ced7189989f1d900061291c385ee",
}
_STATEMENTS = {
    "Naheng.Reduction.detailed_rate_residual_identity": "17e6119da240e698bf89157215d77c568c75ab35424fc200241e621ce456f16c",
    "Naheng.Reduction.detailed_rate_residual_abs_bound": "0c3cdb9d298cbcac00249d2fbafb01060abf0afa10b5ad110dc1dcc35e53d5c3",
    "Naheng.Reduction.robust_rate_upper_bound": "85ed360eb3fa731577b98d84d6560446b389d20888a571ee56b4b1d4441bbc78",
}
_ERRORS = (ValueError, TypeError, KeyError, OSError)


def _canonical(record):
    return json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(record):
    return hashlib.sha256(_canonical(record).encode()).hexdigest()


@dataclass(frozen=True, init=False)
class ReductionBinding:
    _record_json: str

    def __init__(self, record):
        object.__setattr__(self, "_record_json", _canonical(record))

    @property
    def record(self):
        # Callers receive a detached copy, including all nested collections.
        return json.loads(self._record_json)


@dataclass(frozen=True, init=False)
class PosteriorRateEvaluation:
    _record_json: str
    binding: ReductionBinding

    def __init__(self, record, binding):
        object.__setattr__(self, "_record_json", _canonical(record))
        object.__setattr__(self, "binding", binding)

    @property
    def record(self):
        return json.loads(self._record_json)


def _evaluation(record, binding):
    record = dict(record)
    if record["status"] != "PASS":
        record["evidence_refs"] = []
    record["record_sha256"] = _digest(record)
    return PosteriorRateEvaluation(record, binding)


def verify_rate_evaluation(evaluation, snapshot, action):
    """Validate the complete inputs at the admission boundary, not just IDs.

    This protects local producer/consumer integrity; it is not a signature or
    authorization for client-supplied certificates. The API accepts neither
    this Python type nor arbitrary producer code.
    """
    if not isinstance(evaluation, PosteriorRateEvaluation) or not isinstance(evaluation.binding, ReductionBinding):
        raise ValueError("Typed posterior rate evaluation required")
    record = evaluation.record
    checksum = record.pop("record_sha256", None)
    if checksum != _digest(record):
        raise ValueError("Rate evaluation record integrity mismatch")
    if (record["snapshot_id"] != snapshot.snapshot_id or record["action_id"] != action.action_id
            or record["snapshot_sha256"] != _digest(snapshot.model_dump(mode="json"))
            or record["action_sha256"] != _digest(action.model_dump(mode="json"))):
        raise ValueError("Rate constraint/action/posterior input identity mismatch")
    bound = evaluation.binding.record
    if record["binding_sha256"] != _digest(bound):
        raise ValueError("Rate evaluation binding integrity mismatch")
    expected_refs = bound["evidence_refs"] if record["status"] == "PASS" and bound["status"] == "PASS" else []
    if record["evidence_refs"] != expected_refs or (record["status"] == "PASS" and bound["status"] != "PASS"):
        raise ValueError("Rate evaluation authority mismatch")
    record["record_sha256"] = checksum
    return record


def _finish(record, status, reason):
    record.update(status=status, reason=reason, withdrawn=status != "PASS",
                  grants_future_reduction=False, grants_strict_safety=False)
    if status != "PASS":
        record["evidence_refs"] = []
    return ReductionBinding(record)


def load_reduction_binding(project, source_root, package, model, manifest_path=None):
    project, source_root = Path(project).resolve(), Path(source_root).resolve()
    record = {"schema_version": "1.0", "scope": "Instantaneous finite-site stored-sodium rate polynomial only",
              "manifest": None, "manifest_sha256": None, "snapshot": None,
              "identity": None, "evidence_refs": [], "proof_artifact_hashes": {}}
    try:
        record["snapshot"] = _snapshot(source_root, project)
        if type(model) is not SiteModel:
            raise ValueError("Only the audited builtin SiteModel can bind this rate expression")
        _package(package)
        chemical = bind_chemistry(source_root, package, model.params)
        if chemical.status == "FAIL" or chemical.identity is None:
            raise ValueError("Actual source/chemistry/parameters do not match: " + chemical.checks[-1].reason)
        record["identity"] = asdict(chemical.identity)
    except _ERRORS as error:
        return _finish(record, "FAIL", str(error))
    if manifest_path is None:
        return _finish(record, "UNKNOWN", "No active audited residual-rate declaration manifest")
    try:
        path = Path(manifest_path).resolve()
        if not path.is_relative_to(project / "artifacts/formal"):
            raise ValueError("Controlled formal manifest required")
        record["manifest"] = path.relative_to(project).as_posix()
        record["manifest_sha256"] = _sha(path)
        imported = load_evidence(project, path)
        rows = {row["declaration"]: row for row in imported["records"]}
        if not set(_STATEMENTS).issubset(rows):
            raise ValueError("Required residual identity/bound/rate-contract declarations missing")
        lock = _file(source_root, "formal/lean-toolchain").read_text(encoding="utf-8").strip()
        artifacts = {}
        for declaration, expected_statement in _STATEMENTS.items():
            row = rows[declaration]
            if row["statement_hash"] != expected_statement or row["toolchain"] != lock:
                raise ValueError("Residual declaration has an unapproved elaborated type or toolchain")
            for name, expected in _FORMAL_HASHES.items():
                if row["artifacts"].get(name) != expected or _sha(_file(source_root, name)) != expected:
                    raise ValueError("Actual finite-site RHS/derived residual source differs from approved scope")
            for name, expected in row["artifacts"].items():
                if name not in artifacts and name.startswith("formal/") and _sha(_file(source_root, name)) != expected:
                    raise ValueError("Residual proof formal bytes differ from immutable execution snapshot")
                if name in artifacts and artifacts[name] != expected:
                    raise ValueError("Conflicting residual proof artifact identities")
                artifacts[name] = expected
            record["evidence_refs"].append(row["evidence_id"])
        artifacts[record["manifest"]] = record["manifest_sha256"]
        record["proof_artifact_hashes"] = artifacts
    except _ERRORS as error:
        return _finish(record, "UNKNOWN", str(error))
    return _finish(record, "PASS", "Three audited instantaneous residual-rate declarations match actual source and model identity")


def revalidate_reduction_binding(project, source_root, previous, package, model):
    if not isinstance(previous, ReductionBinding):
        raise ValueError("Typed residual binding required")
    old = previous.record
    manifest = Path(project) / old["manifest"] if old.get("manifest") else None
    current = load_reduction_binding(project, source_root, package, model, manifest)
    if old["status"] != "PASS" and current.record["status"] == "PASS":
        return _finish(current.record, "UNKNOWN", "Withdrawn residual authority needs an explicit new binding")
    if old["status"] == current.record["status"] == "PASS":
        for field in ("manifest_sha256", "snapshot", "identity", "proof_artifact_hashes"):
            if old[field] != current.record[field]:
                return _finish(current.record, "UNKNOWN", "Residual binding identity changed before use: " + field)
    return current


def exact_rate_margin(N, a, b, c, x, rbar, upper):
    """Evaluate the particular derived Lean expression, preserving its budget."""
    vectors = tuple(tuple(Fraction(v) for v in values) for values in (N, a, b, c, x))
    N, a, b, c, x = vectors
    rbar, upper = Fraction(rbar), None if upper is None else Fraction(upper)
    if any(len(v) != len(N) for v in vectors) or any(n < 0 for n in N):
        raise ValueError("Equal finite vector lengths and nonnegative capacities required")
    if any(v < 0 for vector in (a, b, c) for v in vector) or any(not 0 <= v <= 1 for v in x):
        raise ValueError("Nonnegative rates and occupations in [0,1] required")
    rates = tuple(aa + bb + cc for aa, bb, cc in zip(a, b, c))
    q = sum((n * xx for n, xx in zip(N, x)), Fraction())
    A = sum((n * aa for n, aa in zip(N, a)), Fraction())
    detailed = sum((n * (aa - rate * xx) for n, aa, rate, xx in zip(N, a, rates, x)), Fraction())
    nominal = A - rbar * q
    residual = -sum((n * (rate - rbar) * xx for n, rate, xx in zip(N, rates, x)), Fraction())
    budget = sum((n * abs(rate - rbar) for n, rate in zip(N, rates)), Fraction())
    if detailed - nominal != residual or abs(residual) > budget:
        raise ValueError("Derived residual expression/domain mismatch")
    retained = upper is not None and nominal + budget <= upper
    if retained and detailed > upper:
        raise ValueError("Derived margin unexpectedly failed")
    return {"q_mol": str(q), "source_mol_per_s": str(A), "rbar_s_inv": str(rbar),
            "detailed_rate_mol_per_s": str(detailed), "nominal_rate_mol_per_s": str(nominal),
            "residual_mol_per_s": str(residual), "budget_mol_per_s": str(budget),
            "limit_mol_per_s": None if upper is None else str(upper),
            "nominal_only_pass": None if upper is None else nominal <= upper,
            "retaining_budget_pass": None if upper is None else bool(retained),
            "detailed_point_pass": None if upper is None else detailed <= upper}


def evaluate_posterior_rate(snapshot, action, model, binding, upper=None):
    """Use only the frozen permitted posterior and sampled model parameters.

    A requested bound must hold after retaining E for every represented sample.
    This is an empirical point constraint, not a whole interval or support bound.
    """
    if not isinstance(binding, ReductionBinding):
        raise ValueError("Typed revalidated residual binding required")
    if action.snapshot_id != snapshot.snapshot_id:
        raise ValueError("Residual query/action posterior identity mismatch")
    if upper is not None and (isinstance(upper, bool) or not math.isfinite(upper)):
        raise ValueError("Finite SI stored-sodium rate upper bound required")
    result = {"scope": "Represented posterior instantaneous stored-sodium rate, mol/s",
              "snapshot_id": snapshot.snapshot_id, "action_id": action.action_id,
              "snapshot_sha256": _digest(snapshot.model_dump(mode="json")),
              "action_sha256": _digest(action.model_dump(mode="json")),
              "binding_sha256": _digest(binding.record),
              "evidence_refs": list(binding.record["evidence_refs"]), "samples": [],
              "upper_mol_per_s": upper, "grants_future_reduction": False, "grants_strict_safety": False,
              "numerical_status": "empirical IEEE rate/root coefficients; exact rational polynomial arithmetic",
              "uncovered": ["root/exponential rounding certificate", "future coefficient/occupation bounds",
                            "closed-loop aggregate drive", "voltage/thermal/capacity readouts", "full posterior support", "physical-cell discrepancy"]}
    if binding.record["status"] != "PASS":
        return _evaluation({**result, "status": "UNKNOWN", "reason": "Residual proof binding is not applicable"}, binding)
    try:
        if type(model) is not SiteModel or action.current_A is None:
            raise ValueError("Audited SiteModel/current action required")
        identity = binding.record['identity']
        if _content_hash(asdict(model.params)) != identity['parameter_hash'] or snapshot.parameter_revision != identity['parameter_revision']:
            raise ValueError("Posterior/model parameters differ from the residual binding")
        names = list(model.state_names) + ["rate_scale", "side_rate_scale"]
        units = list(model.state_units) + ["1", "1"]
        if snapshot.state_names != names or snapshot.state_units != units:
            raise ValueError("Permitted posterior state/parameter semantics do not match sampled SiteModel")
        for index, values in enumerate(snapshot.samples):
            sampled = particle_model(model, values[-2], values[-1])
            state = sampled._validate_state(values[:5])
            drive = sampled.solve_drive(state, action.current_A)
            a, b, c = sampled.rates(drive, float(state[4]))
            represented = lambda values: tuple(Fraction.from_float(float(v)) for v in values)
            N, a, b, c, x = map(represented, (sampled.params.site_capacity_mol, a, b, c, state[:2]))
            total_capacity = sum(N, Fraction())
            rbar = sum((n * (aa + bb + cc) for n, aa, bb, cc in zip(N, a, b, c)), Fraction()) / total_capacity
            row = exact_rate_margin(N, a, b, c, x, rbar, upper)
            row.update(posterior_index=index, weight=snapshot.weights[index], drive_V=drive,
                       temperature_K=float(state[4]), rate_scale=values[-2], side_rate_scale=values[-1])
            result["samples"].append(row)
    except (ValueError, TypeError, OverflowError, ZeroDivisionError) as error:
        return _evaluation({**result, "status": "UNKNOWN", "reason": str(error)}, binding)
    passed = upper is None or all(row["retaining_budget_pass"] for row in result["samples"])
    result.update(status="PASS" if passed else "FAIL",
                  reason="Derived residual budget evaluated for every represented posterior sample" if passed else "Requested point-rate upper constraint fails after retaining the derived residual budget")
    return _evaluation(result, binding)
