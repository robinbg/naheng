"""Bootstrap particle filtering on sensor observations and executed current.

The model and prior are synthetic research assumptions. The estimator has no
reference trace, file path, future-observation, or environment-state interface.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from copy import deepcopy
import hashlib
import json

import numpy as np

from naheng.domain.contracts import Observation, PosteriorSnapshot
from .diagnostics import effective_sample_size, systematic_resample, weighted_quantiles


def particle_model(model, rate_scale: float, side_rate_scale: float):
    """Carry the same sampled dynamics into estimation and conditional forecasts."""
    params = replace(
        model.params,
        rate_s_inv=tuple(v * rate_scale for v in model.params.rate_s_inv),
        side_rate_s_inv=tuple(v * side_rate_scale for v in model.params.side_rate_s_inv),
    )
    return type(model)(params)


def model_parameter_hash(model):
    return hashlib.sha256(json.dumps(asdict(model.params),sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()


def rekey_snapshot(snapshot: dict, run_id: str) -> dict:
    """Reidentify an unchanged posterior for a recovery lineage, without assimilation."""
    result=deepcopy(snapshot)
    result["run_id"]=run_id
    payload={key:result[key] for key in ("run_id","obs_until_s","samples","weights","parameter_revision")}
    result["snapshot_id"]="snapshot-"+hashlib.sha256(json.dumps(payload,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()[:24]
    return result



def _innovation_record(innovations, voltage_noise_V, temperature_noise_K):
    """Actual pre-assimilation residuals; engineering scale, not calibrated risk."""
    values=np.asarray(innovations,dtype=float)
    center=np.median(values,axis=0)
    spread=1.4826*np.median(np.abs(values-center),axis=0)
    scales=np.sqrt(spread**2+np.array([voltage_noise_V,temperature_noise_K])**2)
    return {'innovation_source':'current_sensor_minus_pre_assimilation_model_prediction',
        'innovation_scope':'feasible_represented_particles_engineering_diagnostic_not_probability',
        'innovation_particles':len(values),'voltage_innovation_V':float(center[0]),
        'temperature_innovation_K':float(center[1]),'voltage_innovation_scale_V':float(scales[0]),
        'temperature_innovation_scale_K':float(scales[1])}


class ParticleFilter:
    def __init__(self, run_id: str, model, seed: int = 20261009, particles: int = 64,
                 voltage_noise_V: float = 0.025, temperature_noise_K: float = 0.25):
        if not run_id or particles < 4 or voltage_noise_V <= 0 or temperature_noise_K <= 0:
            raise ValueError("Run, particle count and positive noise scales required")
        self.run_id, self.model = run_id, model
        self.rng = np.random.default_rng(seed)
        self.voltage_noise_V, self.temperature_noise_K = voltage_noise_V, temperature_noise_K
        self.state_names = list(model.state_names) + ["rate_scale", "side_rate_scale"]
        self.state_units = list(model.state_units) + ["1", "1"]
        def initial_particle(soc, temperature, rate, side):
            state = model.initial_state(soc=float(soc), temperature_K=float(temperature))
            ratio = model.params.site_capacity_mol[0] / model.params.site_capacity_mol[1]
            lower = max(-soc, -(1 - soc) / ratio)
            upper = min(1 - soc, soc / ratio)
            shift = self.rng.uniform(lower, upper)
            state[0], state[1] = soc + shift, soc - ratio * shift
            # Preserve total sodium while giving an unobserved initial trapped
            # inventory a genuine prior rather than assuming a known SOH.
            trapped = self.rng.uniform(0.0, 0.01 * sum(model.params.site_capacity_mol))
            state[2], state[3] = trapped, state[3] - trapped
            return list(state) + [float(rate), float(side)]
        self._samples = np.asarray([
            initial_particle(soc, temp, rate, side)
            for soc, temp, rate, side in zip(
                self.rng.uniform(0.15, 0.9, particles), self.rng.normal(298.15, 1.5, particles),
                self.rng.lognormal(0, 0.12, particles), self.rng.lognormal(0, 0.35, particles))
        ])
        self._weights = np.full(particles, 1 / particles)
        self._models = [particle_model(model, row[-2], row[-1]) for row in self._samples]
        self._last_timestamp = None
        self._last_snapshot = None
        self.update_diagnostics = []
        self.parameter_revision = "synthetic-prior-v2-" + hashlib.sha256(
            json.dumps({"model_parameters":asdict(model.params),
                "prior":"independent_composition_inventory_v2",
                "voltage_noise_V":voltage_noise_V, "temperature_noise_K":temperature_noise_K},
                sort_keys=True).encode()).hexdigest()[:12]

    def update(self, observation: Observation, duration_s: float | None = None, *,
               ambient_K: float = 298.15, thermal_W: float = 0.0) -> PosteriorSnapshot:
        if not isinstance(observation, Observation):
            raise TypeError("Estimator accepts Observation only")
        if observation.run_id != self.run_id:
            raise ValueError("Observation belongs to another run")
        if self._last_timestamp is not None and observation.timestamp_s <= self._last_timestamp:
            raise ValueError("Future or repeated assimilation order is invalid; timestamps must increase")
        elapsed = 0.0 if self._last_timestamp is None else observation.timestamp_s - self._last_timestamp
        if self._last_timestamp is None and observation.timestamp_s != 0:
            raise ValueError("Initial observation must be at time zero; missing action history cannot be guessed")
        if duration_s is not None and not np.isclose(duration_s, elapsed):
            raise ValueError("Duration must equal the observed interval")
        predicted = self._samples.copy()
        initial_assimilation = self._last_timestamp is None
        if initial_assimilation:
            # A uniform prior over the declared temperature domain, proposed
            # from its temperature-measurement posterior. The corresponding
            # temperature likelihood is cancelled below, so the observation
            # is not counted twice. This supports legitimate warm starts.
            lower, upper = self.model.params.temperature_min_K, self.model.params.temperature_max_K
            for row in predicted:
                accepted = False
                for _ in range(10000):
                    proposed = self.rng.normal(observation.temperature_K, self.temperature_noise_K)
                    if lower < proposed < upper:
                        row[4] = proposed
                        accepted = True
                        break
                if not accepted:
                    raise ValueError("Initial temperature is incompatible with the model domain")
        log_weights = np.log(np.maximum(self._weights, np.finfo(float).tiny))
        rejected = 0
        innovations = []
        calculation_cache = {}
        reused_calculations = 0
        unique_forward_solves = 0
        for index, (row, model) in enumerate(zip(predicted, self._models)):
            try:
                cache_key = (tuple(row), observation.current_A, elapsed, ambient_K, thermal_W)
                if cache_key in calculation_cache:
                    cached_state, sensed = calculation_cache[cache_key]
                    row[:5] = cached_state
                    reused_calculations += 1
                else:
                    if elapsed:
                        integrated = model.integrate(row[:5], observation.current_A, elapsed,
                                                     ambient_K=ambient_K, thermal_W=thermal_W)
                        unique_forward_solves += 1
                        if integrated.elapsed_s < elapsed - 1e-6:
                            raise ValueError("Particle action terminated before the sensor timestamp")
                        row[:5] = integrated.state
                    sensed = model.observe(row[:5], observation.current_A)
                    calculation_cache[cache_key] = (row[:5].copy(), sensed.copy())
                innovation = [observation.voltage_V - sensed["voltage_V"],
                              observation.temperature_K - sensed["temperature_K"]]
                innovations.append(innovation)
                log_weights[index] -= 0.5 * (
                    (innovation[0] / self.voltage_noise_V)**2
                    + (0 if initial_assimilation else (innovation[1] / self.temperature_noise_K)**2))
            except ValueError:
                log_weights[index] = -np.inf
                rejected += 1
        if not np.isfinite(log_weights).any():
            raise ValueError("Filter degenerated: every sampled model is infeasible")
        stabilized = np.exp(log_weights - np.max(log_weights))
        weights = stabilized / stabilized.sum()
        pre_resample_ess = effective_sample_size(weights)
        flags = ["site_composition_not_identified_by_single_voltage",
                 "side_reaction_rate_not_identified_by_short_trace",
                 "synthetic_parameter_prior_uncalibrated",
                 "initial_temperature_uniform_domain_prior_measurement_proposal"]
        if observation.quality:
            flags.extend("observation_quality:" + flag for flag in observation.quality)
        if rejected:
            flags.append(f"infeasible_particles:{rejected}")
        # The published snapshot is the weighted posterior before resampling.
        # It therefore exposes actual ESS and retains tails rather than hiding
        # degeneracy behind the reset-to-uniform resampled weights.
        if pre_resample_ess < len(weights) / 2:
            flags.append("low_ess_resampling_required")
        names = self.state_names
        means = dict(zip(names, np.average(predicted, axis=0, weights=weights).tolist()))
        capacities = np.asarray(self.model.params.site_capacity_mol)
        soc = predicted[:, :2] @ capacities / capacities.sum()
        means["soc"] = float(np.dot(weights, soc))
        quantiles = {name: weighted_quantiles(predicted[:, j], weights) for j, name in enumerate(names)}
        quantiles["soc"] = weighted_quantiles(soc, weights)
        payload = {"run_id": self.run_id, "obs_until_s": observation.timestamp_s,
                   "samples": predicted.tolist(), "weights": weights.tolist(),
                   "parameter_revision": self.parameter_revision}
        snapshot_id = "snapshot-" + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
        snapshot = PosteriorSnapshot(snapshot_id=snapshot_id, run_id=self.run_id,
            parameter_revision=self.parameter_revision, obs_until_s=observation.timestamp_s,
            state_names=names.copy(), state_units=self.state_units.copy(),
            samples=predicted.tolist(), weights=weights.tolist(), mean=means,
            quantiles=quantiles, ess=pre_resample_ess, identifiability=flags)
        self._samples, self._weights = predicted.copy(), weights.copy()
        if pre_resample_ess < len(weights) / 2:
            indices = systematic_resample(weights, self.rng)
            self._samples = predicted[indices].copy()
            self._weights = np.full(len(weights), 1 / len(weights))
            self._models = [self._models[int(index)] for index in indices]
        self._last_timestamp = observation.timestamp_s
        self._last_snapshot = snapshot.model_copy(deep=True)
        self.update_diagnostics.append({"timestamp_s": observation.timestamp_s,
            "ess_before_resampling": pre_resample_ess, "infeasible_particles": rejected,
            "resampled": pre_resample_ess < len(weights) / 2,
            "particles": len(weights), "unique_forward_solves": unique_forward_solves,
            "reused_calculations": reused_calculations,
            "independent_operational_trajectories": 0,
            **_innovation_record(innovations,self.voltage_noise_V,self.temperature_noise_K)})
        return snapshot.model_copy(deep=True)

    @property
    def snapshot(self) -> PosteriorSnapshot | None:
        return None if self._last_snapshot is None else self._last_snapshot.model_copy(deep=True)

    def export_checkpoint(self) -> dict:
        """Export estimator-owned state only; simulator reference state is never accepted."""
        return deepcopy({"schema_version":1,"run_id":self.run_id,
            "state_names":self.state_names,"state_units":self.state_units,
            "parameter_revision":self.parameter_revision,
            "model_parameter_hash":model_parameter_hash(self.model),
            "samples":self._samples.tolist(),"weights":self._weights.tolist(),
            "rng_state":self.rng.bit_generator.state,
            "voltage_noise_V":self.voltage_noise_V,"temperature_noise_K":self.temperature_noise_K,
            "last_timestamp":self._last_timestamp,
            "last_snapshot":None if self._last_snapshot is None else self._last_snapshot.model_dump(mode="json"),
            "update_diagnostics":self.update_diagnostics})

    @classmethod
    def from_checkpoint(cls,run_id:str,model,payload:dict):
        """Restore exact post-resampling particles/RNG without an initialization draw."""
        expected={"schema_version","run_id","state_names","state_units","parameter_revision",
            "model_parameter_hash","samples","weights","rng_state","voltage_noise_V",
            "temperature_noise_K","last_timestamp","last_snapshot","update_diagnostics"}
        if not run_id or set(payload)!=expected or payload["schema_version"]!=1:
            raise ValueError("Invalid estimator checkpoint schema")
        if payload["model_parameter_hash"]!=model_parameter_hash(model):
            raise ValueError("Estimator checkpoint model parameters changed")
        names=list(model.state_names)+["rate_scale","side_rate_scale"]
        units=list(model.state_units)+["1","1"]
        if payload["state_names"]!=names or payload["state_units"]!=units:
            raise ValueError("Estimator checkpoint state contract changed")
        samples=np.asarray(payload["samples"],dtype=float)
        weights=np.asarray(payload["weights"],dtype=float)
        if samples.ndim!=2 or samples.shape[1]!=len(names) or len(samples)<4:
            raise ValueError("Invalid checkpoint particle dimensions")
        if weights.shape!=(len(samples),) or not np.isfinite(samples).all() or not np.isfinite(weights).all():
            raise ValueError("Nonfinite or mismatched checkpoint particles")
        if (weights<0).any() or not np.isclose(weights.sum(),1,rtol=0,atol=1e-12) or (samples[:,-2:]<=0).any():
            raise ValueError("Invalid checkpoint weights or nuisance parameters")
        noise=[payload["voltage_noise_V"],payload["temperature_noise_K"]]
        if not all(np.isfinite(value) and value>0 for value in noise):
            raise ValueError("Invalid checkpoint noise scales")
        revision="synthetic-prior-v2-"+hashlib.sha256(json.dumps({"model_parameters":asdict(model.params),
            "prior":"independent_composition_inventory_v2","voltage_noise_V":noise[0],
            "temperature_noise_K":noise[1]},sort_keys=True).encode()).hexdigest()[:12]
        if payload["parameter_revision"]!=revision:
            raise ValueError("Estimator checkpoint prior revision changed")
        if payload["rng_state"].get("bit_generator")!="PCG64":
            raise ValueError("Unsupported estimator RNG checkpoint")
        last=payload["last_timestamp"]
        if last is not None and (not np.isfinite(last) or last<0):
            raise ValueError("Invalid checkpoint assimilation time")
        old_snapshot=payload["last_snapshot"]
        if (last is None)!=(old_snapshot is None):
            raise ValueError("Checkpoint timestamp and snapshot disagree")
        if old_snapshot is not None:
            validated=PosteriorSnapshot.model_validate(old_snapshot)
            if validated.run_id!=payload["run_id"] or validated.obs_until_s!=last or validated.parameter_revision!=revision:
                raise ValueError("Checkpoint posterior identity mismatch")
        result=cls.__new__(cls)
        result.run_id,result.model=run_id,model
        result.voltage_noise_V,result.temperature_noise_K=noise
        result.state_names,result.state_units=names,units
        result._samples,result._weights=samples.copy(),weights.copy()
        result._models=[particle_model(model,row[-2],row[-1]) for row in samples]
        for row,particle in zip(samples,result._models): particle.observe(row[:5],0)
        result.rng=np.random.Generator(np.random.PCG64())
        result.rng.bit_generator.state=deepcopy(payload["rng_state"])
        result.parameter_revision=revision
        result._last_timestamp=last
        result._last_snapshot=None if old_snapshot is None else PosteriorSnapshot.model_validate(rekey_snapshot(old_snapshot,run_id))
        result.update_diagnostics=deepcopy(payload["update_diagnostics"])
        return result
