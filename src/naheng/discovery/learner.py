"""Bayesian linear sufficient statistics from measured training feedback only."""
from dataclasses import dataclass
import math
import numpy as np
from .grammar import CandidateError, canonical_sha, parse_candidate
from .counterexamples import parse_model
from .dataset import validate_roles, actual_structural_family_id

FEATURE_NAMES = ('intercept','sites_scaled','class_fraction','relations_scaled',
    'nodes_scaled','joint_output','side_output','linear_readout',
    'capacity_mol_scaled','total_rate_spread_scaled','side_rate_spread_scaled')
HEADS = ('accuracy','nontrivial','coverage','cost')
STATUSES = ('verified_condition','counterexample_found','condition_not_satisfied',
            'timeout_unknown','invalid_syntax')

def trusted_registry(data):
    validate_roles(data)
    return {m['model_id']:{'role':role,'family':actual_structural_family_id(m),
            'sha256':canonical_sha(m),'model':m}
            for role,models in data['roles'].items() for m in models}

def prediction_features(candidate,model):
    """Only AST and raw physical parameter context; no evaluator/labels/residuals."""
    c=parse_candidate(candidate); p=parse_model(model); f=c.features();groups=model['groups']
    n=len(groups);r=[a+b+c for a,b,c in zip(p['a'],p['b'],p['c'])]
    # Continuous parameter ranges are declared context, not coefficient comparisons.
    rs=max([abs(r[i]-r[j]) for i in range(n) for j in range(i) if groups[i]==groups[j]],default=0)
    cs=max([abs(p['c'][i]-p['c'][j]) for i in range(n) for j in range(i) if groups[i]==groups[j]],default=0)
    values=[1.,n/16.,f['n_groups']/n,f['relation_count']/6.,f['expression_nodes']/32.,
            float(f['joint_output']),float(f['side_output']),float(f['linear_readout']),
            float(sum(p['N']))/.1,float(rs)/10.,float(cs)]
    if not all(math.isfinite(v) for v in values):raise CandidateError('Nonfinite prediction feature')
    return dict(zip(FEATURE_NAMES,values))

def feature_vector(features):
    if set(features)!=set(FEATURE_NAMES):raise CandidateError('Prediction feature whitelist mismatch; labels/residuals forbidden')
    x=np.array([features[k] for k in FEATURE_NAMES],dtype=float)
    if x.shape!=(len(FEATURE_NAMES),) or not np.isfinite(x).all():raise CandidateError('Invalid feature vector')
    return x

def validate_feedback(item,row,registry):
    """Do not trust caller role flags or caller feature columns."""
    record=registry.get(row.get('model_id'))
    if (record is None or record['role']!='train' or row.get('role')!='train'
        or row.get('used_for_search') is not True or row.get('model_sha256')!=record['sha256']
        or row.get('structural_family_id')!=record['family']
        or row.get('model_id')!=item['model_id'] or row.get('model_sha256')!=item['model_sha256']
        or row.get('candidate_id')!=item['candidate_id'] or row.get('template_id')!=item['template_id']):
        raise CandidateError('Feedback does not bind to frozen training model/candidate identity')
    if row.get('status') not in STATUSES or row.get('kernel_checked') is not False:
        raise CandidateError('Unknown feedback status or false kernel claim')
    # Feature values used for fitting come from original trusted input, never row.features.
    expected=prediction_features(item['candidate'],record['model'])
    if item['features']!=expected:raise CandidateError('Pool features differ from frozen raw input')
    if row['status'] in ('verified_condition','counterexample_found') and row.get('condition_satisfied') is not True:
        raise CandidateError('Known applicable feedback missing actual condition check')
    if row['status']=='condition_not_satisfied' and row.get('condition_satisfied') is not False:
        raise CandidateError('Inapplicable feedback contradicts condition check')
    return True

def feedback_targets(row):
    status=row['status']; targets={}
    # Unknown/invalid are retained in requested denominator and never negative supervision.
    if status in ('timeout_unknown','invalid_syntax'):return targets
    targets['coverage']=0. if status=='condition_not_satisfied' else 1.
    if status in ('verified_condition','counterexample_found'):
        targets['accuracy']=float(status=='verified_condition')
        if type(row.get('nontrivial_output')) is not bool:raise CandidateError('Measured output nontriviality required')
        targets['nontrivial']=float(row['nontrivial_output'])
        replay=row.get('numeric_replay'); calls=1
        if replay is not None:
            solves=replay.get('solves',[])
            if len(solves)!=2 or any(type(s.get('evaluations')) is not int or s['evaluations']<1 for s in solves):
                raise CandidateError('Actual solver RHS counts missing')
            calls+=sum(s['evaluations'] for s in solves)
        targets['cost']=math.log1p(calls)
    return targets

@dataclass
class BayesianHead:
    alpha:float
    noise:float
    X:list
    y:list

    def posterior(self):
        if getattr(self,'_cached_n',None)==len(self.y):return self._cached
        d=len(FEATURE_NAMES); X=np.asarray(self.X,dtype=float).reshape((-1,d)); y=np.asarray(self.y,dtype=float)
        precision=self.alpha*np.eye(d)+(X.T@X)/self.noise
        covariance=np.linalg.inv(precision); rhs=(X.T@y)/self.noise
        mean=covariance@rhs
        self._cached_n=len(self.y);self._cached=(mean,covariance,precision,rhs)
        return self._cached

    def predict(self,x):
        mean,covariance,_,_=self.posterior()
        return float(x@mean),float(math.sqrt(max(0.,x@covariance@x)))

    def state(self):
        mean,cov,precision,rhs=self.posterior()
        return {'alpha':self.alpha,'noise':self.noise,'X':self.X,'y':self.y,
                'precision':precision.tolist(),'rhs':rhs.tolist(),'mean':mean.tolist(),'covariance':cov.tolist()}

class BayesianLearner:
    def __init__(self,alpha=1.,noise=1.):
        if not alpha>0 or not noise>0:raise CandidateError('Positive prior/noise required')
        self.heads={name:BayesianHead(float(alpha),float(noise),[],[]) for name in HEADS}
        self.observed=[]

    def update(self,item,row,registry):
        validate_feedback(item,row,registry)
        if item['item_id'] in self.observed:raise CandidateError('Duplicate feedback update')
        x=feature_vector(item['features']).tolist();targets=feedback_targets(row)
        for head,target in targets.items():
            self.heads[head].X.append(x);self.heads[head].y.append(target)
        self.observed.append(item['item_id']);return targets

    def predict(self,features):
        x=feature_vector(features)
        return {name:dict(zip(('mean','sd'),head.predict(x))) for name,head in self.heads.items()}

    def state(self):
        return {'model':'four_bayesian_linear_heads','feature_names':list(FEATURE_NAMES),
                'observed':self.observed,'heads':{name:head.state() for name,head in self.heads.items()}}

    @classmethod
    def restore(cls,state):
        if state.get('feature_names')!=list(FEATURE_NAMES):raise CandidateError('Checkpoint feature identity mismatch')
        first=state['heads']['accuracy'];obj=cls(first['alpha'],first['noise'])
        for name in HEADS:
            s=state['heads'][name];h=obj.heads[name];h.X=s['X'];h.y=s['y']
            if h.state()!=s:raise CandidateError('Checkpoint posterior not consistent with retained fitting matrix')
        obj.observed=state['observed'];return obj
