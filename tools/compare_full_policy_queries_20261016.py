"""Actual nine-coordinate random/uncertainty controls under the A03 budgets.

The initial design, training source, conditional plant, observation stream and
service clock match public optimize. No test observations or evaluator state
are supplied to the learned query policy.
"""
from copy import deepcopy
from dataclasses import asdict
import argparse
import json
from pathlib import Path
import time
import uuid
import numpy as np
from naheng.learning.constrained_bo import Search, Limits, BudgetExhausted, digest
from naheng.learning.operational_oracle import OperationalOracle, SOURCE_ID, sha, implementation_hashes
from naheng.learning.policy_space import BOUNDS, UNITS, SPACE_ID, fixed_world
from naheng.estimation.calibration_session import run_calibration
from naheng.runtime.artifacts import atomic_json, code_hash

ROOT=Path(__file__).resolve().parents[1]

class BaselineSearch(Search):
    def __init__(self,*args,strategy,**kwargs):
        super().__init__(*args,**kwargs)
        if strategy not in ('random','uncertainty'):raise ValueError('Unknown comparison')
        self.strategy=strategy

    def ask(self,retry_of=None):
        if retry_of is not None or len(self.events)<self.limits.initial_points:
            return super().ask(retry_of)
        if self.pending:raise ValueError('Pending execution must finish first')
        if len(self.events)>=self.limits.initial_points+self.limits.iterations or self.elapsed()>=self.limits.wall_s:
            raise BudgetExhausted('Common original count/time budget consumed')
        high_remaining=self.limits.high_fidelity_calls-sum(row['fidelity']=='high' for row in self.events)
        if high_remaining and (self._pair_probe_needed() or self._failure_probe_needed()):
            # Availability recovery is common to all three query policies.
            request=super().ask()
            request.update(strategy=self.strategy,shared_pairing_probe=request['selection']=='paired_high_fidelity_discrepancy_identification')
            if request['selection']=='failure_dominated_high_fidelity_probe':request['shared_failure_recovery']=True
            self.pending[request['reservation_id']]=deepcopy(request)
            return deepcopy(request)
        highs=[r for r in self.events if r['fidelity']=='high' and r['result']['status']=='completed']
        lows=[r for r in self.events if r['fidelity']=='low' and r['result']['status']=='completed'
              and not any(v['candidate_id']==r['candidate_id'] and v['fidelity']=='high' for v in self.events)]
        self._fit()
        costs={f:max(.001,float(np.median([r['result']['cost_s'] for r in self.events
                  if r['fidelity']==f and r['result']['cost_s'] is not None])))
                  if any(r['fidelity']==f and r['result']['cost_s'] is not None for r in self.events)
                  else (1. if f=='low' else 5.) for f in ('low','high')}
        if high_remaining and self.utility.paired_count<min(3,self.limits.high_fidelity_calls) and lows:
            chosen=max(lows,key=lambda row:self.utility.predict([row['x']])[1][0])
            candidate=self._candidate(chosen['x']);fidelity='high';selection='paired_high_fidelity_discrepancy_identification'
        elif self.strategy=='random':
            fidelity=str(self.rng.choice(['low','high'] if high_remaining else ['low']))
            candidate=self._candidate(self.rng.random(len(self.names)));selection='uniform_random_query'
        else:
            pool=self.rng.random((48,len(self.names)));choices=[]
            for f in ('low','high'):
                if f=='high' and not high_remaining:continue
                variance=self.utility.predict(pool,f)[1]
                for point,var in zip(pool,variance):
                    candidate=self._candidate(point)
                    if not any(r['candidate_id']==candidate['candidate_id'] and r['fidelity']==f for r in self.events):
                        choices.append((float(var)/costs[f],f,candidate))
            _,fidelity,candidate=max(choices,key=lambda row:row[0]);selection='surrogate_variance_per_measured_cost'
        remaining=self.limits.wall_s-self.elapsed()
        if remaining<=0:
            raise BudgetExhausted('Baseline selection consumed remaining original wall budget')
        request={**candidate,'selection':selection,'strategy':self.strategy,'cost_estimates_s':costs,
            'fidelity':fidelity,'reservation_id':uuid.uuid4().hex,'ordinal':len(self.events),
            'protocol_sha256':self.protocol_sha256,
            'timeout_s':min(self.limits.single_execution_s,remaining)}
        self.pending[request['reservation_id']]=deepcopy(request)
        return deepcopy(request)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--strategy',choices=['random','uncertainty'],required=True)
    args=parser.parse_args();started=time.monotonic();limits=Limits()
    output=ROOT/'artifacts'/('full-policy-'+args.strategy+'-'+uuid.uuid4().hex[:10]);output.mkdir()
    packet=ROOT/'artifacts/calibration'/('comparison-'+args.strategy+'-'+uuid.uuid4().hex[:10])
    import naheng.learning
    request=Path(naheng.learning.__file__).parent/'calibration_request.json'
    calibration=run_calibration(ROOT,request,packet);atomic_json(output/'calibration-preflight.json',calibration)
    if calibration['exit_code']!=0:
        atomic_json(output/'result.json',{'exit_code':2,'status':'blocked_calibration','calibration':calibration})
        return 2
    search=BaselineSearch(BOUNDS,{SOURCE_ID:'train','heldout-full-policy-2026101411':'test'},limits,strategy=args.strategy)
    search.previous_wall=time.monotonic()-started
    protocol={'strategy':args.strategy,'space_id':SPACE_ID,'bounds':BOUNDS,'units':UNITS,
      'sources':search.sources,'limits':asdict(limits),'code_hash':code_hash(ROOT),
      'implementations':implementation_hashes(),'comparison_driver_sha256':sha(Path(__file__)),
      'world':fixed_world(),'calibration_packet':str(packet),'calibration_manifest_sha256':sha(packet/'manifest.json'),
      'scope':'Same fixed conditional synthetic training service; computational effort levels only',
      'common_failure_recovery':'failed low majority probes untried high while total high attempts are below min(3, high cap); shared with main search',
      'heldout_results_seen':False,'scientific_N_added':0,'risk_certificate':False}
    atomic_json(output/'protocol.json',protocol)
    oracle=OperationalOracle(output/'cases',packet=packet,world=protocol['world'])
    while True:
        try:request=search.ask()
        except BudgetExhausted:break
        search.checkpoint(output/'checkpoint.json')
        atomic_json(output/'progress.json',{'strategy':args.strategy,'completed':len(search.events),'elapsed_s':search.elapsed()})
        try:response=oracle.evaluate(request)
        except Exception as error:
            response={'status':'unknown','utility':None,'constraint_margin':None,'cost_s':None,
                      'source_id':SOURCE_ID,'run_id':request['reservation_id'],
                      'evidence_sha256':sha(output/'checkpoint.json'),'reason':repr(error)}
        search.tell(request,response);search.checkpoint(output/'checkpoint.json')
        print(json.dumps({'out':str(output),'completed':len(search.events),'strategy':args.strategy,
                          'status':response['status']}),flush=True)
    search._fit()
    source_check_error=None
    try:
        unchanged=(code_hash(ROOT)==protocol['code_hash'] and sha(Path(__file__))==protocol['comparison_driver_sha256']
            and implementation_hashes()==protocol['implementations']
            and sha(packet/'manifest.json')==protocol['calibration_manifest_sha256']
            and digest(json.loads((output/'protocol.json').read_text(encoding='utf-8')))==digest(protocol))
    except (OSError,ValueError) as error:
        unchanged=False;source_check_error=repr(error)
    elapsed=search.elapsed()
    in_budget=elapsed<=limits.wall_s
    complete=len(search.events)==36 and search.best() is not None and in_budget and unchanged
    accepted_best=search.best() if complete else None
    result={'exit_code':0 if complete else 2,
      'status':'completed' if complete else 'budget_exhausted' if not in_budget else 'source_changed' if not unchanged else 'insufficient_completed_evidence',
      'source_check_error':source_check_error,
      'strategy':args.strategy,'requested_queries':36,'actual_reserved_queries':len(search.events),
      'completed_results':sum(row['result']['status']=='completed' for row in search.events),
      'unknown_results':sum(row['result']['status']!='completed' for row in search.events),
      'high_calls':sum(row['fidelity']=='high' for row in search.events),'best_training_candidate':accepted_best,
      'diagnostic_best_training_candidate':search.best(),'within_original_wall_budget':in_budget,
      'utility_model':search.utility.state(),'constraint_model':search.constraint.state(),
      'protocol_sha256':sha(output/'protocol.json'),'checkpoint_sha256':sha(output/'checkpoint.json'),
      'elapsed_s':elapsed,'source_unchanged':unchanged,'scientific_N_added':0,'risk_certificate':False}
    atomic_json(output/'result.json',result)
    print(json.dumps({'out':str(output),'exit_code':result['exit_code']}),flush=True)
    return result['exit_code']

if __name__=='__main__':raise SystemExit(main())
