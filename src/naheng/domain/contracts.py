from __future__ import annotations
from typing import Literal
from math import isfinite
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .units import SI_UNITS, validate_units

class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal[1] = 1

class ChemistryIdentity(Contract):
    chemistry_id: str
    model_kind: Literal["theory_fixture", "fast_operational", "reference_sodium", "public_data_case"]
    source_id: str
    parameter_revision: str
    supported_temperature_K: tuple[float, float]

class Observation(Contract):
    run_id: str = Field(min_length=1)
    cell_id: str = "cell-1"
    timestamp_s: float = Field(ge=0)
    current_A: float
    voltage_V: float
    temperature_K: float = Field(gt=0)
    chemistry_id: Literal["synthetic_two_site"] = "synthetic_two_site"
    units: dict[str, str] = Field(default_factory=lambda: SI_UNITS.copy())
    quality: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unit_contract(self):
        validate_units(self.units)
        return self

class PosteriorSnapshot(Contract):
    snapshot_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    model_package_id: str = "research_base-v1"
    parameter_revision: str = "synthetic-v1"
    obs_until_s: float = Field(ge=0)
    state_names: list[str]
    state_units: list[str]
    samples: list[list[float]]
    weights: list[float]
    mean: dict[str, float]
    quantiles: dict[str, list[float]]
    ess: float = Field(gt=0)
    identifiability: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def distribution_contract(self):
        if not self.samples or len(self.samples) != len(self.weights):
            raise ValueError("Nonempty samples and matching weights required")
        if len(self.state_names) != len(self.state_units) or any(len(s) != len(self.state_names) for s in self.samples):
            raise ValueError("State definition mismatch")
        if any(w < 0 or not isfinite(w) for w in self.weights) or abs(sum(self.weights)-1) > 1e-6:
            raise ValueError("Weights must be finite, nonnegative and normalized")
        if self.ess > len(self.samples) + 1e-6:
            raise ValueError("ESS exceeds particle count")
        return self

class Action(Contract):
    action_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    start_s: float = Field(ge=0)
    duration_s: float = Field(gt=0, le=3600)
    current_A: float | None = None
    power_W: float | None = None
    thermal_W: float = Field(default=0, ge=-100, le=100)
    target: str = "cell-1"

    @model_validator(mode="after")
    def single_command(self):
        if (self.current_A is None) == (self.power_W is None):
            raise ValueError("Exactly one of current and power required")
        return self

class ForecastQuery(Contract):
    snapshot_id: str = Field(min_length=1)
    future_policy_id: str = Field(min_length=1)
    environment_id: str = Field(min_length=1)
    horizon_s: float = Field(gt=0, le=86400)
    endpoint_protocol: str = Field(min_length=1)
    sample_budget: int = Field(default=16, ge=1, le=256)
    current_A: float = 0
    ambient_K: float = Field(default=298.15, ge=273.15, le=333.15)
    seed: int = 20261009

class Evidence(Contract):
    evidence_id: str
    statement_text: str
    statement_hash: str | None = None
    formal_target: str | None = None
    status: Literal["proposed", "checking", "checked", "counterexample_found", "timeout_unknown", "blocked", "invalid"]
    category: Literal["formal_kernel", "formal_extended_trust", "validated_numerics", "statistical", "empirical", "none"]
    applicability: Literal["applicable", "inapplicable", "unknown", "stale"]
    assumptions: list[str] = Field(default_factory=list)
    artifact_sha256: str | None = None
    build_log_uri: str | None = None
    dependency_manifest: dict = Field(default_factory=dict)
    uncovered_errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def no_self_certification(self):
        if self.status == "checked" and (not self.artifact_sha256 or not self.build_log_uri or not self.statement_hash):
            raise ValueError("Checked evidence requires real artifact, build log and statement hashes")
        return self

class ModelPackage(Contract):
    package_id: str
    chemistry_id: str
    parameter_revision: str
    state_definition: dict[str, str]
    dynamics_ast: dict
    readout_ast: dict
    reduction_map: dict
    lifting_map: dict
    domain: dict
    error_contracts: list[dict]
    evidence_refs: list[str]
    validity_monitor: dict
    fallback_refs: list[str]
    artifact_hashes: dict[str, str]

    parameters: dict = Field(default_factory=dict)
    package_hash: str | None = None

class RegisteredModelPackage(ModelPackage):
    """Server-derived execution identity, separate from submitted model metadata."""
    validation_status: Literal["metadata_only", "executable"]
    execution_binding: str
    parameter_hash: str | None
    binding_hashes: dict[str, str]
    evidence_validity: str

class RunManifest(Contract):
    run_id: str
    mode: Literal["interactive", "batch", "replay"]
    provenance_type: Literal["synthetic", "reference_simulation", "public_measurement", "replay"]
    model_id: str
    parameter_revision: str
    policy_id: str
    data_id: str
    code_hash: str
    dependency_lock_hash: str | None
    seed_bundle: dict[str, int]
    artifact_index: dict[str, str]
    complete: bool
    role: Literal["train", "validation", "test", "stress"] = "validation"
    accelerated_synthetic: bool = False
    reused_from: str | None = None
    recovered_from: str | None = None
    recovery_step: int | None = None
    independent_sample: bool = True
