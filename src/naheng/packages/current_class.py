"""Artifact-only exact coefficient grouping and empirical posterior forecasting.

No physical equation, package authority, public source, or task status is changed.
The checked-declaration reader fails closed on stale source/export/object bytes.
The fixture evaluator can compare a proposed grouped solver while normal runtime
falls back to the original detailed SiteModel whenever proof authority is absent.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
import hashlib
import inspect
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq
from naheng.domain.contracts import PosteriorSnapshot, ForecastQuery
from naheng.estimation.particle_filter import particle_model
from naheng.models.site_model import SiteModel, DomainError, InfeasibleError
from naheng.models.degradation import temperature_rate_factor
from naheng.models.thermal import thermal_balance
from naheng.packages.evidence_import import load_evidence
from naheng.risk.forecast import estimate_events

ROOT = Path(__file__).resolve().parents[3]
TARGETS = (
    'Naheng.Reduction.class_readout_sufficient_iff_shared_coefficients',
    'Naheng.Reduction.same_class_state_preserves_exact_current_chemical_outputs',
)
FORMAL_SOURCES = ('Exact', 'ClassSufficiency', 'FixedCurrentReadout', 'CurrentClassBridge')
MODEL_SOURCES = ('src/naheng/models/site_model.py', 'src/naheng/models/thermal.py',
                 'src/naheng/models/degradation.py', 'src/naheng/packages/evidence_import.py')
# Audited Python mapping bytes from the actual 5c55cb69 receipt and independent
# review b. A fresh bind cannot silently approve changed equations/importer.
AUDITED_IMPORTED_SOURCE_SHA256=(
    '24f387d276d349884eb1a863f04489f4182b2ca7296d1c7a1fc2bec8a25f80d5',
    '26aa374a71e5542c178989dcfc03d6a35054d3dab46ba7c102d7441510e2f815',
    'ab69e7a7d9cfabc2ee329ed63f20e30e09b2ef27f1df3378f25ff672a4ae5413',
    'e02aed63e4042db101de9b16d975b2ed0cadda18efa86e5b95f17860cd799ba4',
)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def parameter_hash(model):
    return digest(asdict(model.params))

def source_hashes():
    # Hash the actual imported implementation, including a frozen worker copy.
    objects=(SiteModel,thermal_balance,temperature_rate_factor,load_evidence)
    paths={Path(inspect.getsourcefile(obj)).resolve() for obj in objects} | {Path(__file__).resolve()}
    return {str(path):sha(path) for path in sorted(paths)}

MAPPING_VERSION = 'site-scalar-float64-reviewed-v2'
MAPPING_REVIEW_ID = 'p02-physical-mapping-root-20261016-c'
MAPPING_REVIEW_RELATIVE = 'artifacts/review/p02-physical-mapping-root-20261016-c/review.json'
MAPPING_REVIEW_SHA256 = '286f387fedd542e3bc591121e3b45dd510c77436cc57ee42a97fe8e7d1f1286c'

def reviewed_mapping_source(proof_root):
    """Only the fixed server review identity authorizes this new mapping version."""
    path = Path(proof_root) / MAPPING_REVIEW_RELATIVE
    try:
        if sha(path) != MAPPING_REVIEW_SHA256:
            return False
        review = json.loads(path.read_text(encoding='utf-8'))
        return (review['review_id'] == MAPPING_REVIEW_ID
            and review['decision'] == 'APPROVE_RESTRICTED_MAPPING_EQUIVALENCE_FOR_NEW_PRIVATE_FACTORY_DEVELOPMENT'
            and review['approved_source_tuple'] == list(AUDITED_IMPORTED_SOURCE_SHA256))
    except (OSError, ValueError, KeyError, TypeError):
        return False

def audited_imported_sources(proof_root=None):
    objects=(SiteModel,thermal_balance,temperature_rate_factor,load_evidence)
    return all(sha(inspect.getsourcefile(obj))==expected for obj,expected in zip(objects,AUDITED_IMPORTED_SOURCE_SHA256)) and reviewed_mapping_source(proof_root or ROOT)

def condition(name, status, reason):
    return {'condition': name, 'status': status, 'reason': reason}

def coefficient_groups(model, proposed=None):
    if type(model) is not SiteModel:
        return (), [condition('model_kind', 'FAIL', 'Only the current synthetic builtin SiteModel is bound')]
    p = model.params
    if not all(math.isfinite(v) for v in asdict(p).values() if isinstance(v,(int,float))):
        return (), [condition('finite_parameters', 'FAIL', 'All actual scalar model parameters must be finite')]
    keys = [tuple(Fraction(v) for v in (k, bias, c)) for k, bias, c in
            zip(p.rate_s_inv, p.equilibrium_drive_V, p.side_rate_s_inv)]
    if proposed is None:
        groups = []
        for i, key in enumerate(keys):
            found = next((g for g in groups if keys[g[0]] == key), None)
            if found is None: groups.append([i])
            else: found.append(i)
        proposed = tuple(tuple(g) for g in groups)
    groups = tuple(tuple(g) for g in proposed)
    checks = []
    if sorted(i for g in groups for i in g) != list(range(2)) or any(not g for g in groups):
        return groups, [condition('partition', 'FAIL', 'Every site must occur exactly once')]
    checks.append(condition('partition', 'PASS', 'Every original site retained once'))
    for g in groups:
        shared = all(keys[i] == keys[g[0]] for i in g)
        checks.append(condition('shared_k_bias_c_' + str(g), 'PASS' if shared else 'FAIL',
            'Exact represented coefficient equality; no tolerance coalescing'))
    positive = (all(n > 0 for n in p.site_capacity_mol) and all(k > 0 for k in p.rate_s_inv)
                and all(c >= 0 for c in p.side_rate_s_inv) and p.drive_scale_V > 0 and p.faraday_C_per_mol > 0)
    checks.append(condition('positive_parameters', 'PASS' if positive else 'FAIL', 'N/k/F/scale positive; c nonnegative'))
    checks.append(condition('common_temperature_factor', 'PASS', 'Actual SiteModel rates use one positive temperature_rate_factor(T) and one scale'))
    return groups, checks

def read_declarations(manifest_path, *, proof_root=None):
    record = {'status': 'UNKNOWN', 'used_checked_ids': [], 'historical_references': [],
              'manifest': str(manifest_path) if manifest_path else None, 'reason': 'No selected current proof publication',
              'bound_source_and_object_hashes': {}}
    if manifest_path is None: return record
    path = Path(manifest_path).resolve()
    proof_root=Path(proof_root or ROOT).resolve()
    try:
        if not path.is_relative_to(proof_root): raise ValueError('Controlled project proof manifest required')
        manifest = json.loads(path.read_text(encoding='utf-8'))
        records = manifest.get('evidence', [])
        if not isinstance(records, list): records = [records]
        selected = {r.get('declaration'): r for r in records if isinstance(r, dict) and r.get('declaration') in TARGETS}
        record['historical_references'] = [{'declaration': t, 'evidence_id': r.get('evidence_id'),
            'claimed_historical_status': r.get('status')} for t, r in selected.items()]
        if set(selected) != set(TARGETS): raise ValueError('Required class and current bridge declarations missing')
        if manifest.get('checked') is not True or manifest.get('exit_code') != 0:
            raise ValueError('Actual successful checked publication missing')
        commands = manifest.get('commands', [])
        if len(commands) < 2 or any(c.get('exit_code') != 0 or c.get('timed_out') for c in commands):
            raise ValueError('Successful actual build and declaration audit receipts missing')
        loaded = load_evidence(proof_root, path)  # full artifact revalidation, never a subset exemption
        loaded_selected = {r['declaration']: r for r in loaded['records'] if r['declaration'] in TARGETS}
        artifact_map = {}
        for r in loaded_selected.values(): artifact_map.update(r['artifacts'])
        artifact_map.update(manifest.get('artifact_hashes', {}))
        # Current checker binds root objects separately from frozen source
        # artifacts; load_evidence above revalidates every declared object.
        artifact_map.update(manifest.get('compiled_object_hashes', {}))
        record['bound_source_hashes'] = {}
        record['bound_object_hashes'] = {}
        for module in FORMAL_SOURCES:
            names = ('formal/Naheng/Reduction/' + module + '.lean',
                     'formal/.lake/build/lib/lean/Naheng/Reduction/' + module + '.olean')
            for name in names:
                expected = artifact_map.get(name)
                if not isinstance(expected, str): raise ValueError('Publication does not bind current root source/object: ' + name)
                if sha(proof_root/name) != expected: raise ValueError('Current root source/object changed: ' + name)
                record['bound_source_and_object_hashes'][name] = expected
                record['bound_object_hashes' if name.endswith('.olean') else 'bound_source_hashes'][name] = expected
        record.update(status='PASS', used_checked_ids=[loaded_selected[t]['evidence_id'] for t in TARGETS],
            manifest_sha256=sha(path), reason='Current actual checked declarations, all recorded proof artifacts, sources and root objects verified')
    except (ValueError, KeyError, TypeError, OSError) as error:
        record.update(status='UNKNOWN', used_checked_ids=[], reason=str(error))
    return record

@dataclass(frozen=True)
class GroupBinding:
    record_json: str

    @property
    def record(self): return json.loads(self.record_json)

def bind(model, parameter_revision, manifest_path=None, proposed_groups=None, *, model_package_id, proof_root=None):
    if not isinstance(model_package_id,str) or not model_package_id: raise ValueError('Explicit model package identity required')
    groups, checks = coefficient_groups(model, proposed_groups)
    proof_root=Path(proof_root or ROOT).resolve()
    proof = read_declarations(manifest_path,proof_root=proof_root)
    if not audited_imported_sources(proof_root):
        proof.update(status='UNKNOWN',used_checked_ids=[],reason='Imported mapping source differs from audited Python equations/reader; re-review mapping before a new class binding')
    record = {'schema_version': 1, 'model_package_id':model_package_id, 'parameter_revision': parameter_revision,
        'parameter_sha256': parameter_hash(model), 'source_hashes': source_hashes(),
        'groups': groups, 'checks': checks, 'proof': proof, 'proof_root':str(proof_root),
        'mathematical_conditions': 'FAIL' if any(c['status'] == 'FAIL' for c in checks) else 'PASS',
        'numerical_root_certificate': 'UNKNOWN', 'numerical_ode_certificate': 'UNKNOWN',
        'closed_loop_continuous_certificate': 'UNKNOWN', 'operating_probability_certificate': 'UNKNOWN',
        'strict_admission': 'UNKNOWN', 'provenance_type': 'synthetic'}
    record.update(mapping_version=MAPPING_VERSION, mapping_review_id=MAPPING_REVIEW_ID, mapping_review_sha256=MAPPING_REVIEW_SHA256,
                  mapping_review_verified_at_bind=reviewed_mapping_source(proof_root))
    record['binding_sha256'] = digest(record)
    return GroupBinding(json.dumps(record, sort_keys=True, allow_nan=False))

def revalidate(binding, model, revision):
    if not isinstance(binding, GroupBinding): raise TypeError('Server-produced immutable GroupBinding required')
    old = binding.record
    if old.get('mapping_version') != MAPPING_VERSION or old.get('mapping_review_sha256') != MAPPING_REVIEW_SHA256:
        return {'status':'FAIL','reason':'Reviewed mapping identity/source withdrawn','used_checked_ids':[]}
    if old['parameter_revision'] != revision or old['parameter_sha256'] != parameter_hash(model):
        return {'status': 'FAIL', 'reason': 'Parameter/revision changed; prior evidence not inherited', 'used_checked_ids': []}
    if old['source_hashes'] != source_hashes():
        return {'status': 'FAIL', 'reason': 'Runtime/model equation implementation changed; binding stale', 'used_checked_ids': []}
    if old['mathematical_conditions'] != 'PASS':
        return {'status': 'FAIL', 'reason': 'Shared coefficient grouping conditions failed', 'used_checked_ids': []}
    if not reviewed_mapping_source(old['proof_root']):
        # Missing authority on first bind permits only the existing detailed
        # fallback. Previously established review authority may not disappear.
        verified=old.get('mapping_review_verified_at_bind',old['proof']['status']=='PASS') or old['proof']['status']=='PASS'
        return {'status':'FAIL' if verified else 'UNKNOWN',
                'reason':'Reviewed mapping identity/source withdrawn' if verified else 'Mapping review was not verified at initial bind; detailed fallback only',
                'used_checked_ids':[]}
    proof = read_declarations(old['proof']['manifest'],proof_root=old['proof_root'])
    if old['proof']['status']!='PASS' or proof.get('manifest_sha256')!=old['proof'].get('manifest_sha256'):
        return {'status':'UNKNOWN','reason':'Initial selected publication absent or its bytes changed; explicitly rebind before reuse','used_checked_ids':[]}
    return {'status': proof['status'], 'reason': proof['reason'], 'used_checked_ids': proof['used_checked_ids']}

def project_posterior(snapshot, model, binding):
    if not isinstance(snapshot, PosteriorSnapshot): raise TypeError('Only permitted PosteriorSnapshot input, never evaluator truth')
    identity = revalidate(binding, model, snapshot.parameter_revision)
    if identity['status'] == 'FAIL': raise ValueError(identity['reason'])
    record = binding.record
    if snapshot.model_package_id != record['model_package_id']: raise ValueError('Posterior model package identity mismatch')
    groups = tuple(tuple(g) for g in record['groups'])
    names = snapshot.state_names
    if len(names)!=len(set(names)): raise ValueError('Duplicate posterior state names are ambiguous')
    for name,unit in zip(model.state_names,model.state_units):
        if name not in names or snapshot.state_units[names.index(name)]!=unit:
            raise ValueError('Posterior state unit/semantics mismatch: '+name)
    indices = [names.index(n) for n in model.state_names]
    extras = [n for n in names if n not in model.state_names]
    if set(extras) - {'rate_scale', 'side_rate_scale'}: raise ValueError('Unsupported posterior uncertainty semantics')
    if any(snapshot.state_units[names.index(n)]!='1' for n in extras):
        raise ValueError('Posterior multiplicative uncertainty units must be dimensionless')
    samples = []
    for row in snapshot.samples:
        state = model._validate_state([row[i] for i in indices])
        if not model.params.temperature_min_K <= state[4] <= model.params.temperature_max_K:
            raise ValueError('A represented posterior state lies outside declared temperature domain')
        extra = [row[names.index(n)] for n in extras]
        if any(not math.isfinite(v) or (v <= 0 if name=='rate_scale' else v < 0) for name,v in zip(extras,extra)):
            raise ValueError('Sampled reversible scale positive; side scale nonnegative; both finite')
        q = [math.fsum(model.params.site_capacity_mol[i]*state[i] for i in g) for g in groups]
        samples.append(q + list(state[2:]) + extra)
    result = {'snapshot_id': snapshot.snapshot_id, 'source_snapshot_sha256': digest(snapshot.model_dump(mode='json')),
        'parameter_revision': snapshot.parameter_revision, 'parameter_sha256': parameter_hash(model),
        'groups': groups, 'state_names': ['q_class_' + str(j) for j in range(len(groups))] + list(model.state_names[2:]) + extras,
        'state_units': ['mol']*len(groups) + list(model.state_units[2:]) + ['1']*len(extras),
        'samples': samples, 'weights': list(snapshot.weights), 'binding_sha256': record['binding_sha256'],
        'posterior_scope': 'represented weighted samples only; no full-support or hidden truth claim',
        'numeric_mapping_certificate': 'UNKNOWN', 'identity': identity}
    result['projection_sha256'] = digest(result)
    result['source_snapshot_id'] = snapshot.snapshot_id
    result['projected_snapshot_id'] = 'grouped-' + result['projection_sha256'][:24]
    return result

def lift_constraints(grouped_state, model, groups):
    q = np.asarray(grouped_state[:len(groups)], float)
    constraints, bounds = [], []
    for j, g in enumerate(groups):
        cap = math.fsum(model.params.site_capacity_mol[i] for i in g)
        if not 0 <= q[j] <= cap: raise DomainError('Group amount outside physical capacity')
        constraints.append({'sites': list(g), 'weights_mol': [model.params.site_capacity_mol[i] for i in g],
                            'rhs_mol': float(q[j]), 'relation': 'sum(N_i*x_i)=q_class'})
        for i in g:
            n = model.params.site_capacity_mol[i]
            bounds.append({'site': i, 'lower': max(0., (q[j]-(cap-n))/n), 'upper': min(1., q[j]/n)})
    return {'kind': 'correlated_linear_constraint_set', 'constraints': constraints, 'occupancy_bounds': bounds,
        'ambiguous': any(len(g)>1 for g in groups), 'unique_detailed_vector': None,
        'numeric_set_certificate': 'UNKNOWN', 'scope': 'Retains equality correlations; marginal interval product is not the lift set'}

class GroupedModel:
    """Direct grouped equations; no guessed/lifted site vector is evaluated."""
    def __init__(self, model, groups):
        _, checks = coefficient_groups(model, groups)
        if any(c['status'] == 'FAIL' for c in checks): raise ValueError('Invalid grouped chemistry conditions')
        self.model, self.params, self.groups = model, model.params, tuple(tuple(g) for g in groups)
        self.capacity = np.array([math.fsum(self.params.site_capacity_mol[i] for i in g) for g in self.groups])
        self.representatives = [g[0] for g in self.groups]

    def _validate(self, state):
        state = np.asarray(state, float)
        m = len(self.groups)
        if state.shape != (m+3,) or not np.isfinite(state).all(): raise DomainError('Finite grouped state required')
        tol = self.capacity*1e-8
        if np.any(state[:m] < -tol) or np.any(state[:m] > self.capacity+tol) or np.any(state[m:m+2]<-1e-8) or state[-1]<=0:
            raise DomainError('Grouped physical domain violated')
        return state

    def solve_drive(self, state, current_A):
        state = self._validate(state); p = self.params; q = state[:len(self.groups)]
        if not math.isfinite(current_A): raise DomainError('Finite current required')
        theta = temperature_rate_factor(state[-1])
        insertion = p.faraday_C_per_mol*theta*math.fsum(p.rate_s_inv[i]*math.exp(-p.equilibrium_drive_V[i]/p.drive_scale_V)*(cap-amount)
            for i,cap,amount in zip(self.representatives,self.capacity,q))
        removal = p.faraday_C_per_mol*theta*math.fsum(p.rate_s_inv[i]*math.exp(p.equilibrium_drive_V[i]/p.drive_scale_V)*amount
            for i,amount in zip(self.representatives,q))
        def residual(u): return removal*math.exp(-u/p.drive_scale_V)-insertion*math.exp(u/p.drive_scale_V)-current_A
        lo, hi = residual(p.drive_min_V), residual(p.drive_max_V)
        if lo == 0: return p.drive_min_V
        if hi == 0: return p.drive_max_V
        if lo*hi > 0: raise InfeasibleError('Grouped current root absent; no drive clamping')
        return float(brentq(residual,p.drive_min_V,p.drive_max_V,xtol=1e-12,rtol=1e-12))

    def observe(self, state, current_A):
        state = self._validate(state)
        return {'voltage_V': self.params.base_voltage_V+self.solve_drive(state,current_A)-current_A*self.params.resistance_ohm,
                'temperature_K': float(state[-1]), 'current_A': float(current_A)}

    def rhs(self, t, state, current_A, ambient_K=298.15, thermal_W=0.):
        state=self._validate(state); m=len(self.groups); q=state[:m]
        a,b,c=self.model.rates(self.solve_drive(state,current_A),state[-1])
        a,b,c=(v[self.representatives] for v in (a,b,c))
        reversible=a*(self.capacity-q)-b*q; trapped=float(np.dot(c,q))
        thermal=thermal_balance(current_A=current_A,temperature_K=float(state[-1]),ambient_K=ambient_K,
            trapped_rate_mol_per_s=trapped,resistance_ohm=self.params.resistance_ohm,
            reaction_heat_J_per_mol=self.params.side_heat_J_per_mol,conductance_W_per_K=self.params.thermal_conductance_W_per_K,
            capacity_J_per_K=self.params.thermal_capacity_J_per_K,management_W=thermal_W)
        return np.r_[reversible-c*q,trapped,-float(reversible.sum()),thermal.temperature_rate_K_per_s]

    def integrate(self, state, current_A, duration_s, ambient_K=298.15, thermal_W=0.):
        initial=self._validate(state).copy(); self.observe(initial,current_A)
        if not math.isfinite(duration_s) or duration_s<=0: raise DomainError('Positive finite horizon required')
        p=self.params; m=len(self.groups)
        names=('voltage_low','voltage_high','temperature_low','temperature_high','reservoir_depleted')
        def values(state):
            v=self.observe(state,current_A)['voltage_V']
            return (v-p.voltage_min_V,p.voltage_max_V-v,state[-1]-p.temperature_min_K,p.temperature_max_K-state[-1],state[m+1])
        events=[]
        for index in range(5):
            def event(t,s,index=index): return values(s[:-1])[index]
            event.direction=-1; event.terminal=True; events.append(event)
        initial_values=values(initial)
        already=[i for i,v in enumerate(initial_values) if v<=0]
        if already:
            return {'status':'computed','state':initial.tolist(),'energy_J':0.,'elapsed_s':0.,
                'events':[{'name':names[i],'time_s':0.} for i in already], 'observable':self.observe(initial,current_A)}
        def augmented(t,s): return np.r_[self.rhs(t,s[:-1],current_A,ambient_K,thermal_W),current_A*self.observe(s[:-1],current_A)['voltage_V']]
        solved=solve_ivp(augmented,(0,duration_s),np.r_[initial,0.],rtol=1e-7,atol=1e-10,max_step=min(60.,duration_s),events=events)
        if not solved.success: raise RuntimeError(solved.message)
        final=solved.y[:-1,-1]
        return {'status':'computed','state':final.tolist(),'energy_J':float(solved.y[-1,-1]),'elapsed_s':float(solved.t[-1]),
            'events':[{'name':names[i],'time_s':float(t)} for i,times in enumerate(solved.t_events) for t in times],
            'observable':self.observe(final,current_A),'solver':'scipy.solve_ivp/RK45','nfev':solved.nfev,
            'numerical_error_certificate':'UNKNOWN','strict_safety':False}

def predict(snapshot, query, model, binding, *, exploratory_fixture=False, wall_budget_s=110.):
    if not isinstance(snapshot,PosteriorSnapshot) or not isinstance(query,ForecastQuery): raise TypeError('Typed posterior/query only')
    if snapshot.snapshot_id!=query.snapshot_id: raise ValueError('Snapshot/query identity mismatch')
    if not 0<wall_budget_s<=120: raise ValueError('Prediction wall budget <=120 s required')
    identity=revalidate(binding,model,snapshot.parameter_revision)
    if identity['status']=='FAIL': raise ValueError(identity['reason'])
    projected=project_posterior(snapshot,model,binding)
    # Projection performs the final actual revalidation. A later UNKNOWN must
    # withdraw grouped authority rather than reuse the earlier PASS/IDs.
    identity=projected['identity']
    groups=tuple(tuple(g) for g in projected['groups'])
    reduced=len(groups)<2
    use_grouped=reduced and (identity['status']=='PASS' or exploratory_fixture)
    route='exploratory_grouped_fixture' if use_grouped and identity['status']!='PASS' else 'checked_grouped' if use_grouped else 'detailed_fallback'
    rows=np.asarray(snapshot.samples); names=snapshot.state_names
    indices=[names.index(n) for n in model.state_names]
    rng=np.random.default_rng(query.seed)
    chosen=rng.choice(len(rows),size=query.sample_budget,replace=True,p=snapshot.weights)
    paths=[]; started=time.monotonic()
    for sample_index in chosen:
        if time.monotonic()-started>=wall_budget_s: raise TimeoutError('Forecast budget reached at solver boundary')
        row=rows[sample_index]
        rate=float(row[names.index('rate_scale')]) if 'rate_scale' in names else 1.
        side=float(row[names.index('side_rate_scale')]) if 'side_rate_scale' in names else 1.
        current_model=particle_model(model,rate,side)
        if use_grouped:
            backend=GroupedModel(current_model,groups)
            result=backend.integrate(projected['samples'][sample_index][:len(groups)+3],query.current_A,query.horizon_s,query.ambient_K)
        else:
            actual=current_model.integrate(row[indices],query.current_A,query.horizon_s,query.ambient_K)
            result={'status':'computed','state':actual.state.tolist(),'energy_J':actual.energy_J,'elapsed_s':actual.elapsed_s,
                    'events':actual.events,'observable':current_model.observe(actual.state,query.current_A)}
        result.update(posterior_sample_index=int(sample_index),route=route,
            particle_parameter_sha256=parameter_hash(current_model),rate_scale=rate,side_rate_scale=side,
            used_checked_ids=identity['used_checked_ids'] if route=='checked_grouped' else [])
        paths.append(result)
    return {'status':'computed','snapshot_id':snapshot.snapshot_id,'snapshot_sha256':projected['source_snapshot_sha256'],
        'query_sha256':digest(query.model_dump(mode='json')),'parameter_sha256':parameter_hash(model),
        'binding_sha256':binding.record['binding_sha256'],'route':route,'full_dimension':5,
        'executed_state_dimension':len(groups)+3 if use_grouped else 5,'projection':projected,'paths':paths,
        'risk':estimate_events(paths,model),'formal_condition_evaluation':identity,
        'used_checked_ids':identity['used_checked_ids'] if route=='checked_grouped' else [],
        'numerical_root_certificate':'UNKNOWN','numerical_ode_certificate':'UNKNOWN',
        'closed_loop_continuous_certificate':'UNKNOWN','strict_admission':'UNKNOWN',
        'provenance_type':'synthetic','wall_s':time.monotonic()-started}
