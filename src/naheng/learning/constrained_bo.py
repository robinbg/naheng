"""Bounded ask/tell constrained BO; only declared training executions fit models."""
from copy import deepcopy
from dataclasses import dataclass, asdict
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid

import numpy as np
from scipy.optimize import minimize
from scipy.stats import qmc

from .multifidelity import MultiFidelity
from .query_policy import score


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class BudgetExhausted(RuntimeError): pass


@dataclass(frozen=True)
class Limits:
    initial_points: int = 12
    iterations: int = 24
    high_fidelity_calls: int = 24
    single_execution_s: float = 120.
    wall_s: float = 1800.
    retry_limit: int = 2
    seed: int = 20261016

    def __post_init__(self):
        if (type(self.initial_points) is not int or not 1 <= self.initial_points <= 64
            or type(self.iterations) is not int or not 0 <= self.iterations <= 192
            or type(self.high_fidelity_calls) is not int or not 0 <= self.high_fidelity_calls <= self.initial_points+self.iterations
            or type(self.single_execution_s) not in (int,float) or not math.isfinite(self.single_execution_s)
            or type(self.wall_s) not in (int,float) or not math.isfinite(self.wall_s)
            or not 0 < self.single_execution_s <= 120 or not 0 < self.wall_s <= 1800
            or type(self.retry_limit) is not int or not 0 <= self.retry_limit <= 2):
            raise ValueError('Invalid bounded search limits')


class Search:
    def __init__(self, bounds, source_registry, limits=None):
        self.bounds = deepcopy(bounds); self.sources = deepcopy(source_registry)
        self.limits = limits or Limits(); self.names = tuple(sorted(bounds))
        if not 1 <= len(self.names) <= 16:
            raise ValueError('Declare 1..16 finite parameter intervals')
        for name in self.names:
            a, b = bounds[name]
            if not isinstance(name, str) or not name or any(type(v) not in (int,float) for v in (a,b)) or not np.isfinite([a,b]).all() or a >= b:
                raise ValueError('Invalid named design interval')
        if not self.sources or any(not isinstance(k,str) or not k or v not in ('train', 'validation', 'test') for k,v in self.sources.items()):
            raise ValueError('Declare source identities and immutable roles')
        self.protocol = {'bounds': self.bounds, 'source_registry': self.sources, 'limits': asdict(self.limits)}
        self.protocol_sha256 = digest(self.protocol)
        self.rng = np.random.default_rng(self.limits.seed)
        self.initial = qmc.LatinHypercube(len(self.names), seed=self.limits.seed).random(self.limits.initial_points)
        self.events = []; self.pending = {}; self.started = time.monotonic(); self.previous_wall = 0.
        self.utility = MultiFidelity(len(self.names)); self.constraint = MultiFidelity(len(self.names))

    def elapsed(self): return self.previous_wall + time.monotonic() - self.started

    def _candidate(self, x):
        x = np.asarray(x, float)
        if x.shape != (len(self.names),) or not np.isfinite(x).all() or np.any(x<0) or np.any(x>1):
            raise ValueError('Candidate outside normalized design space')
        values = {n: self.bounds[n][0] + float(x[i])*(self.bounds[n][1]-self.bounds[n][0]) for i,n in enumerate(self.names)}
        return {'candidate_id': digest(values), 'parameters': values, 'x': x.tolist()}

    def _used(self): return self.events + list(self.pending.values())

    def _fit(self):
        arrays = {}
        for fidelity in ('low', 'high'):
            rows = [r for r in self.events if r['fidelity']==fidelity and r['result']['status']=='completed']
            arrays[fidelity] = (np.asarray([r['x'] for r in rows], float).reshape(-1,len(self.names)),
                np.asarray([r['result']['utility'] for r in rows]), np.asarray([r['result']['constraint_margin'] for r in rows]))
        self.utility.fit(arrays['low'][0], arrays['low'][1], arrays['high'][0], arrays['high'][1])
        self.constraint.fit(arrays['low'][0], arrays['low'][2], arrays['high'][0], arrays['high'][2])

    def best(self):
        rows = [r for r in self.events if r['fidelity']=='high' and r['result']['status']=='completed' and r['result']['constraint_margin']<=0]
        return deepcopy(max(rows, key=lambda r:r['result']['utility'])) if rows else None

    def _pair_probe_needed(self):
        low_ids={r['candidate_id'] for r in self.events if r['fidelity']=='low' and r['result']['status']=='completed'}
        high_ids={r['candidate_id'] for r in self.events if r['fidelity']=='high' and r['result']['status']=='completed'}
        high_tried={r['candidate_id'] for r in self._used() if r['fidelity']=='high'}
        return len(low_ids & high_ids)<min(3,self.limits.high_fidelity_calls) and bool(low_ids-high_tried)

    def _failure_probe_needed(self):
        low=[row for row in self.events if row['fidelity']=='low']
        if not low:return False
        failed=sum(row['result']['status']!='completed' for row in low)
        # Availability checks spend the same finite high-fidelity budget as
        # every other request. Unknowns, retries and pending work all count;
        # a missing successful response must not starve normal acquisition.
        high_attempts=sum(row['fidelity']=='high' for row in self._used())
        return failed*2>=len(low) and high_attempts<min(3,self.limits.high_fidelity_calls)

    def ask(self, retry_of=None):
        used = self._used()
        if self.pending:
            raise ValueError('One outstanding execution at a time prevents budget oversubscription')
        if len(used) >= self.limits.initial_points+self.limits.iterations or self.elapsed()>=self.limits.wall_s:
            raise BudgetExhausted('Search budget consumed; no additional execution reserved')
        high_remaining = self.limits.high_fidelity_calls-sum(r['fidelity']=='high' for r in used)
        info = {}
        if retry_of is not None:
            prior = next((r for r in self.events if r['reservation_id']==retry_of), None)
            if prior is None or prior['result']['status']=='completed':
                raise ValueError('Only an actual unknown or failed attempt can be retried')
            same = [r for r in used if r['candidate_id']==prior['candidate_id'] and r['fidelity']==prior['fidelity']]
            if len(same)>self.limits.retry_limit: raise BudgetExhausted('Retry budget consumed')
            if prior['fidelity']=='high' and high_remaining<=0: raise BudgetExhausted('High-fidelity budget consumed')
            candidate = self._candidate(prior['x']); fidelity = prior['fidelity']; info['retry_of'] = retry_of
        elif len(used)<self.limits.initial_points:
            candidate = self._candidate(self.initial[len(used)]); fidelity = 'low'; info['selection'] = 'initial_latin_hypercube'
        elif high_remaining>0 and self._pair_probe_needed():
            # Obtain paired data before availability probes consume high budget.
            self._fit()
            low_only=[r for r in self.events if r['fidelity']=='low' and r['result']['status']=='completed'
                      and not any(v['candidate_id']==r['candidate_id'] and v['fidelity']=='high' for v in used)]
            selected=max(low_only,key=lambda r:self.utility.predict([r['x']])[1][0])
            candidate=self._candidate(selected['x']);fidelity='high'
            info.update(selection='paired_high_fidelity_discrepancy_identification',paired_low_reservation=selected['reservation_id'],
                completed_pairs_before=self.utility.paired_count,model_feasibility_is_risk_certificate=False)
        elif high_remaining>0 and self._failure_probe_needed():
            # Availability evidence guides where to compute, never a physical label.
            self._fit()
            low=[row for row in self.events if row['fidelity']=='low']
            missing=[row for row in low if row['result']['status']!='completed'
                     and not any(v['candidate_id']==row['candidate_id'] and v['fidelity']=='high' for v in used)]
            if missing:
                candidate=self._candidate(missing[0]['x'])
                probe_source=missing[0]['reservation_id']
            else:
                candidate=self._candidate(self.rng.random(len(self.names)))
                while any(v['candidate_id']==candidate['candidate_id'] and v['fidelity']=='high' for v in used):
                    candidate=self._candidate(self.rng.random(len(self.names)))
                probe_source=None
            fidelity='high'
            info.update(selection='failure_dominated_high_fidelity_probe',low_failure_probe_of=probe_source,
                failed_low_attempts=sum(r['result']['status']!='completed' for r in low),
                completed_low_attempts=sum(r['result']['status']=='completed' for r in low),
                low_failure_is_physical_label=False,multifidelity_discrepancy_identified=False,
                rho_fitted_from_pairs={'utility':self.utility.rho_fitted_from_pairs,'constraint':self.constraint.rho_fitted_from_pairs},
                fitted_models={'utility':self.utility.state(),'constraint':self.constraint.state()},
                model_feasibility_is_risk_certificate=False)
        else:
            self._fit()
            done_high = [r for r in self.events if r['fidelity']=='high' and r['result']['status']=='completed']
            low_only = [r for r in self.events if r['fidelity']=='low' and r['result']['status']=='completed'
                        and not any(v['candidate_id']==r['candidate_id'] and v['fidelity']=='high' for v in used)]
            incumbent = self.best()
            best_value = incumbent['result']['utility'] if incumbent else 0.
            measured_costs = {f:[r['result']['cost_s'] for r in self.events if r['fidelity']==f and r['result']['cost_s'] is not None] for f in ('low','high')}
            costs = {f:max(.001,float(np.median(measured_costs[f]))) if measured_costs[f] else (1. if f=='low' else 5.) for f in ('low','high')}
            pool = np.vstack([self.rng.random((48,len(self.names))), np.asarray([r['x'] for r in self.events])])
            choices = []
            for f in ('low','high'):
                if f=='high' and high_remaining<=0: continue
                acquisition = lambda x: float(score(self.utility, self.constraint, np.asarray(x).reshape(1,-1),
                    best_value, f, costs, incumbent is not None)[0][0])
                # Score all unqueried starts, not just optimizer stationary points.
                # A repeated optimum does not exhaust a continuous design space.
                available = [x for x in pool if not any(v['candidate_id']==self._candidate(x)['candidate_id']
                    and v['fidelity']==f for v in used)]
                for x in available:
                    choices.append((acquisition(x), f, self._candidate(x)))
                starts = sorted(available, key=acquisition, reverse=True)[:4]
                for start in starts:
                    optimized = minimize(lambda x:-acquisition(x), start, method='L-BFGS-B',
                        bounds=[(0.,1.)]*len(self.names), options={'maxiter':40})
                    for x in (start, np.clip(optimized.x,0.,1.)):
                        c = self._candidate(x)
                        if any(v['candidate_id']==c['candidate_id'] and v['fidelity']==f for v in used): continue
                        choices.append((acquisition(x), f, c))
            if high_remaining>0 and self.utility.paired_count<min(3,self.limits.high_fidelity_calls) and low_only:
                # Paired observations identify the discrepancy before free fidelity choice.
                selected = max(low_only, key=lambda r:self.utility.predict([r['x']])[1][0])
                candidate = self._candidate(selected['x']); fidelity = 'high'
                info['selection'] = 'paired_high_fidelity_discrepancy_identification'
            else:
                if not choices: raise BudgetExhausted('No unqueried design remains')
                value, fidelity, candidate = max(choices, key=lambda r:r[0])
                info.update(selection='optimized_constrained_expected_improvement_per_cost', acquisition=float(value))
            info.update(cost_estimates_s=costs, fitted_models={'utility':self.utility.state(),'constraint':self.constraint.state()},
                        model_feasibility_is_risk_certificate=False)
        remaining=self.limits.wall_s-self.elapsed()
        if remaining<=0:
            raise BudgetExhausted('Selection consumed remaining wall budget; no execution reserved')
        reservation = {**candidate, **info, 'fidelity': fidelity, 'reservation_id': uuid.uuid4().hex,
                       'ordinal':len(used), 'protocol_sha256':self.protocol_sha256,
                       'timeout_s':min(self.limits.single_execution_s,remaining)}
        self.pending[reservation['reservation_id']] = deepcopy(reservation)
        return deepcopy(reservation)

    def tell(self, reservation, result):
        identity = reservation.get('reservation_id')
        if self.pending.get(identity) != reservation:
            raise ValueError('Execution result is not bound to the exact pending request')
        required = {'status','utility','constraint_margin','cost_s','source_id','run_id','evidence_sha256','reason'}
        if not isinstance(result,dict) or set(result)!=required or result['status'] not in ('completed','unknown','failed'):
            raise ValueError('Complete typed execution result required')
        if self.sources.get(result['source_id'])!='train':
            raise ValueError('Validation/test or undeclared source cannot fit or select a policy')
        if result['cost_s'] is None and result['status'] != 'completed':
            pass  # Interrupted work may have no trustworthy elapsed-time receipt.
        elif type(result['cost_s']) not in (int,float) or not math.isfinite(result['cost_s']) or result['cost_s']<0:
            raise ValueError('Actual finite nonnegative execution cost required')
        if result['status']=='completed':
            if any(type(result[k]) not in (int,float) or not math.isfinite(result[k]) for k in ('utility','constraint_margin')):
                raise ValueError('Completed executions need measured finite utility and margin')
            if (not isinstance(result['run_id'],str) or not result['run_id']
                or not isinstance(result['evidence_sha256'],str) or len(result['evidence_sha256'])!=64
                or any(c not in '0123456789abcdef' for c in result['evidence_sha256'])):
                raise ValueError('Completed execution needs run and evidence identity')
            if result['cost_s']>reservation['timeout_s']:
                raise ValueError('Over-budget execution cannot be accepted as completed')
        elif result['utility'] is not None or result['constraint_margin'] is not None or not result['reason']:
            raise ValueError('Unknown/failed execution must remain unlabelled with a reason')
        self.events.append({**self.pending.pop(identity), 'result':deepcopy(result)})
        return deepcopy(self.events[-1])

    def checkpoint(self, path):
        state = {'protocol':self.protocol, 'protocol_sha256':self.protocol_sha256, 'events':self.events,
                 'pending':self.pending, 'rng_state':self.rng.bit_generator.state, 'used_wall_s':self.elapsed()}
        path = Path(path); temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex[:8])
        temporary.write_text(json.dumps({'state':state,'state_sha256':digest(state)},indent=2),encoding='utf-8')
        os.replace(temporary,path)

    @classmethod
    def restore(cls, path, expected_protocol_sha256):
        saved = json.loads(Path(path).read_text(encoding='utf-8')); state = saved['state']
        if digest(state)!=saved['state_sha256'] or digest(state['protocol'])!=expected_protocol_sha256 or state['protocol_sha256']!=expected_protocol_sha256:
            raise ValueError('Checkpoint or frozen protocol identity changed')
        search = cls(state['protocol']['bounds'],state['protocol']['source_registry'],Limits(**state['protocol']['limits']))
        if (len(state['events'])+len(state['pending'])>search.limits.initial_points+search.limits.iterations
            or len(state['pending'])>1 or not 0<=state['used_wall_s']<=search.limits.wall_s):
            raise ValueError('Checkpoint budgets are inconsistent')
        seen_ids = set()
        def validate_request(request, ordinal):
            candidate = search._candidate(request['x'])
            identity = request.get('reservation_id')
            if (type(ordinal) is not int or type(request.get('ordinal')) is not int
                or request['ordinal'] != ordinal or request.get('protocol_sha256') != expected_protocol_sha256
                or request.get('candidate_id') != candidate['candidate_id'] or request.get('parameters') != candidate['parameters']
                or request.get('fidelity') not in ('low','high')
                or not isinstance(identity,str) or len(identity)!=32 or any(c not in '0123456789abcdef' for c in identity)
                or identity in seen_ids or type(request.get('timeout_s')) not in (float,int)
                or not math.isfinite(request['timeout_s']) or not 0<request['timeout_s']<=search.limits.single_execution_s):
                raise ValueError('Checkpoint execution identity or budget changed')
            same = [r for r in search.events if r['candidate_id']==request['candidate_id'] and r['fidelity']==request['fidelity']]
            if same:
                prior = next((r for r in same if r['reservation_id']==request.get('retry_of')),None)
                if prior is None or prior['result']['status']=='completed' or len(same)>search.limits.retry_limit:
                    raise ValueError('Checkpoint contains an unauthorized duplicate execution')
            if request['fidelity']=='high' and sum(r['fidelity']=='high' for r in search.events)>=search.limits.high_fidelity_calls:
                raise ValueError('Checkpoint exceeds high-fidelity budget')
            seen_ids.add(identity)
        for ordinal, row in enumerate(state['events']):
            request = {k:v for k,v in row.items() if k!='result'}
            validate_request(request, ordinal)
            search.pending = {row['reservation_id']: request}
            search.tell(request, row['result'])
        for identity, request in state['pending'].items():
            if identity != request.get('reservation_id'):
                raise ValueError('Checkpoint pending key differs from execution identity')
            validate_request(request, len(search.events))
        search.pending = deepcopy(state['pending'])
        search.rng.bit_generator.state = state['rng_state']; search.previous_wall = state['used_wall_s']
        return search
