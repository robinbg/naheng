"""Bounded typed AST for finite-site chemical candidate conditions.

No Python evaluation, occupation/output assumptions, or restricted singleton
state domains. Accepted candidates have an exact nonempty parameter witness.
"""
from dataclasses import dataclass
from fractions import Fraction
import hashlib,json,itertools

class CandidateError(ValueError):
    status='invalid_syntax'

UNITS={'N':(1,0),'a':(0,-1),'b':(0,-1),'c':(0,-1)} # mol, s exponents
DOMAIN='positive_N_nonnegative_rates_full_unit_cube'
MAX_SITES=16

def rational(value):
    if isinstance(value,bool) or not isinstance(value,(int,str)):
        raise CandidateError('Exact bounded integer or rational string required')
    if isinstance(value,str) and len(value)>64:raise CandidateError('Rational literal too long')
    try:v=Fraction(value)
    except (ValueError,ZeroDivisionError,TypeError) as e:raise CandidateError('Invalid rational literal') from e
    if abs(v)>1000000 or v.denominator>1000000:raise CandidateError('Rational outside finite budget')
    return v

def canonical_sha(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()

@dataclass(frozen=True)
class Expr:
    op:str
    value:str|None
    args:tuple
    unit:tuple
    def to_dict(self):
        d={'op':self.op}
        if self.value is not None:d['value']=self.value
        if self.args:d['args']=[x.to_dict() for x in self.args]
        return d
    def evaluate(self,params,i):
        if self.op=='param':return params[self.value][i]
        if self.op=='const':return rational(self.value)
        v=[x.evaluate(params,i) for x in self.args]
        if self.op=='add':return v[0]+v[1]
        if self.op=='sub':return v[0]-v[1]
        if self.op=='mul':return v[0]*v[1]
        if self.op=='div':return v[0]/v[1]
        if self.op=='neg':return -v[0]
        raise CandidateError('Unsupported AST evaluation')

def expression(data):
    count=[0]
    def visit(d,depth=0):
        count[0]+=1
        if depth>5 or count[0]>32 or not isinstance(d,dict) or set(d)-{'op','value','args'}:
            raise CandidateError('Invalid/excessive finite expression')
        op=d.get('op');args=d.get('args',[])
        if not isinstance(op,str):raise CandidateError('Expression op must be typed text')
        if not isinstance(args,list):raise CandidateError('Expression args must be a list')
        if op=='param':
            if args or not isinstance(d.get('value'),str) or d.get('value') not in UNITS:raise CandidateError('Only N/a/b/c parameters allowed; output assumptions forbidden')
            return Expr(op,d['value'],(),UNITS[d['value']])
        if op=='const':
            if args:raise CandidateError('Constant cannot have args')
            value=rational(d.get('value'));return Expr(op,str(value),(),(0,0))
        if d.get('value') is not None or op not in {'add','sub','mul','div','neg'} or len(args)!=(1 if op=='neg' else 2):
            raise CandidateError('Invalid AST operation/arity')
        nodes=tuple(visit(a,depth+1) for a in args)
        if op in {'add','sub'} and nodes[0].unit!=nodes[1].unit:raise CandidateError('Cannot add different SI dimensions')
        if op=='div' and not (nodes[1].op=='param' and nodes[1].value=='N' or nodes[1].op=='const' and rational(nodes[1].value)>0):
            raise CandidateError('Division requires declared positive N or positive rational denominator')
        unit=nodes[0].unit if op in {'add','sub','neg'} else tuple(a+b if op=='mul' else a-b for a,b in zip(nodes[0].unit,nodes[1].unit))
        if any(abs(u)>2 for u in unit):raise CandidateError('Expression dimensions outside finite language')
        return Expr(op,None,nodes,unit)
    return visit(data)

@dataclass(frozen=True)
class Relation:
    kind:str
    expr:Expr
    def to_dict(self):return {'kind':self.kind,'expression':self.expr.to_dict()}

@dataclass(frozen=True)
class Candidate:
    n_sites:int
    groups:tuple
    relations:tuple
    target_kind:str
    weight:Expr|None
    domain_witness:dict
    def to_dict(self):
        target={'kind':self.target_kind}
        if self.weight is not None:target['weight_expression']=self.weight.to_dict()
        return {'schema_version':1,'n_sites':self.n_sites,'groups':list(self.groups),'domain':DOMAIN,
                'parameter_relations':[r.to_dict() for r in self.relations],'target':target}
    @property
    def candidate_id(self):return 'candidate-'+canonical_sha(self.to_dict())
    def features(self):
        def count(e):return 1+sum(count(a) for a in e.args)
        return {'n_sites':self.n_sites,'n_groups':len(set(self.groups)),
                'reduction_fraction':1-len(set(self.groups))/self.n_sites,
                'relation_count':len(self.relations),'expression_nodes':sum(count(r.expr) for r in self.relations)+(count(self.weight) if self.weight else 0),
                'joint_output':int(self.target_kind=='joint_rates'),'side_output':int(self.target_kind in ('joint_rates','trapping_rate')),
                'linear_readout':int(self.target_kind=='linear_readout')}

def conditions_hold(candidate,params):
    for relation in candidate.relations:
        v=[relation.expr.evaluate(params,i) for i in range(candidate.n_sites)]
        if relation.kind=='within_group_equal':
            if any(v[i]!=v[j] for i in range(candidate.n_sites) for j in range(i) if candidate.groups[i]==candidate.groups[j]):return False
        elif relation.kind=='positive' and any(x<=0 for x in v):return False
        elif relation.kind=='nonnegative' and any(x<0 for x in v):return False
    return True

def parse_candidate(data):
    if not isinstance(data,dict) or set(data)!={'schema_version','n_sites','groups','domain','parameter_relations','target'} or type(data['schema_version']) is not int or data['schema_version']!=1:
        raise CandidateError('Exact candidate schema required')
    n=data['n_sites'];groups=data['groups']
    if type(n) is not int or not 2<=n<=MAX_SITES or not isinstance(groups,list) or len(groups)!=n or any(type(g) is not int or g<0 for g in groups):raise CandidateError('Invalid finite grouping')
    unique=set(groups)
    if unique!=set(range(len(unique))) or not 1<=len(unique)<n:raise CandidateError('Surjective nontrivial finite partition required')
    if data['domain']!=DOMAIN:raise CandidateError('Full nonempty physical cube required; isolated state domains forbidden')
    rs=data['parameter_relations']
    if not isinstance(rs,list) or len(rs)>6:raise CandidateError('Finite parameter relation list required')
    relations=[]
    for r in rs:
        if not isinstance(r,dict) or set(r)!={'kind','expression'} or not isinstance(r['kind'],str) or r['kind'] not in {'within_group_equal','positive','nonnegative'}:raise CandidateError('Output/target equality assumptions forbidden')
        relations.append(Relation(r['kind'],expression(r['expression'])))
    target=data['target']
    if not isinstance(target,dict):raise CandidateError('Typed target required')
    kind=target.get('kind');weight=None
    if not isinstance(kind,str):raise CandidateError('Target kind must be typed text')
    if kind=='linear_readout':
        if set(target)!={'kind','weight_expression'}:raise CandidateError('Typed linear readout required')
        weight=expression(target['weight_expression'])
        if weight.unit not in ((0,0),(0,-1)):raise CandidateError('Readout must be mol or mol/s')
    elif kind not in {'stored_amount_rate','trapping_rate','joint_rates'} or set(target)!={'kind'}:raise CandidateError('Unknown target statement')
    candidate=Candidate(n,tuple(groups),tuple(relations),kind,weight,{})
    # An explicit exact parameter witness proves nonempty admitted conditions.
    # Failure to find one is a language-admission failure, not a proof of emptiness.
    for N,a,b,c in itertools.product([1,2],[0,1,2,3],[0,1,2],[0,1,2]):
        params={'N':[Fraction(N)]*n,'a':[Fraction(a)]*n,'b':[Fraction(b)]*n,'c':[Fraction(c)]*n}
        if conditions_hold(candidate,params):
            witness={k:[str(x) for x in v] for k,v in params.items()}
            return Candidate(n,tuple(groups),tuple(relations),kind,weight,witness)
    raise CandidateError('nonempty_domain_required: no supported exact physical parameter witness; reject overstrong/incompatible premises')

def parameter(name):return {'op':'param','value':name}
def total_rate_expr():return {'op':'add','args':[{'op':'add','args':[parameter('a'),parameter('b')]},parameter('c')]}
