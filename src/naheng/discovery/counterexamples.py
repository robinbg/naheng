"""Exact declared finite-site model checks and executable numerical replay.

verified_condition means this rational model's linear coefficient criterion,
never a newly checked Lean theorem, fit, physical-cell or closed-loop claim.
"""
from fractions import Fraction
import time
import numpy as np
from scipy.integrate import solve_ivp
from .grammar import Candidate,CandidateError,parse_candidate,rational,canonical_sha,conditions_hold,DOMAIN

SCOPE='fixed_external_affine_site_model_exact_rational_instance_not_new_Lean_theorem'

def derived_rational(value):
    """Computed witness fractions may exceed raw grammar literal bounds.

    Preserve exact arithmetic with a separate serialization/bit-size budget;
    never round a rational proof witness to make it replayable.
    """
    if isinstance(value,bool) or not isinstance(value,(int,str)) or len(str(value))>4096:
        raise CandidateError('Invalid/excessive derived witness rational')
    try:result=Fraction(value)
    except (ValueError,ZeroDivisionError,TypeError) as error:raise CandidateError('Invalid derived witness rational') from error
    if result.numerator.bit_length()>16384 or result.denominator.bit_length()>16384:
        raise CandidateError('Derived witness bit-size budget exceeded')
    return result

def parse_model(data):
    required={'schema_version','model_id','structural_family_id','role','groups','parameters','units','fixed_external_rates'}
    if not isinstance(data,dict) or set(data)!=required or type(data['schema_version']) is not int or data['schema_version']!=1 or not isinstance(data['role'],str) or data['role'] not in {'train','validation','test'} or data['fixed_external_rates'] is not True:raise CandidateError('Invalid declared model schema')
    if data['units']!={'N':'mol','a':'s^-1','b':'s^-1','c':'s^-1'}:raise CandidateError('Model SI units mismatch')
    params=data['parameters']
    if not isinstance(params,dict) or set(params)!={'N','a','b','c'}:raise CandidateError('Declared finite-site coefficients required')
    groups=data['groups']
    if not isinstance(groups,list):raise CandidateError('Finite model groups must be a list')
    n=len(groups)
    if not isinstance(groups,list) or any(type(g) is not int or g<0 for g in groups) or set(groups)!=set(range(len(set(groups)))) or not 1<=len(set(groups))<n:
        raise CandidateError('Invalid physical model partition')
    if not 2<=n<=16 or any(not isinstance(v,list) or len(v)!=n for v in params.values()):raise CandidateError('Invalid model dimensions')
    parsed={k:[rational(x) for x in v] for k,v in params.items()}
    if any(x<=0 for x in parsed['N']) or any(x<0 for k in ('a','b','c') for x in parsed[k]):raise CandidateError('Nonempty positive-capacity/nonnegative-rate model domain required')
    return parsed

def class_amounts(params,groups,x):
    return [sum(params['N'][i]*x[i] for i in range(len(x)) if groups[i]==g) for g in sorted(set(groups))]

def outputs(params,x):
    r=[a+b+c for a,b,c in zip(params['a'],params['b'],params['c'])]
    return {'stored_amount':sum(n*v for n,v in zip(params['N'],x)),
            'stored_amount_rate':sum(n*(a-ri*v) for n,a,ri,v in zip(params['N'],params['a'],r,x)),
            'trapping_rate':sum(n*c*v for n,c,v in zip(params['N'],params['c'],x))}

def coefficients(candidate,params):
    rate=[a+b+c for a,b,c in zip(params['a'],params['b'],params['c'])]
    if candidate.target_kind=='stored_amount_rate':return {'stored_amount_rate':rate}
    if candidate.target_kind=='trapping_rate':return {'trapping_rate':params['c']}
    if candidate.target_kind=='joint_rates':return {'stored_amount_rate':rate,'trapping_rate':params['c']}
    return {'linear_readout':[candidate.weight.evaluate(params,i) for i in range(candidate.n_sites)]}

def replay_counterexample(candidate_data,model_data,witness,wall_budget_s=1.):
    candidate=parse_candidate(candidate_data);params=parse_model(model_data)
    xq=[derived_rational(v) for v in witness['x']];zq=[derived_rational(v) for v in witness['z']]
    if (len(xq)!=candidate.n_sites or len(zq)!=candidate.n_sites or any(not 0<=v<=1 for v in xq+zq)
            or not conditions_hold(candidate,params) or class_amounts(params,candidate.groups,xq)!=class_amounts(params,candidate.groups,zq)):
        raise CandidateError('Replay witness violates physical domain, declared premises or equal class state')
    target=witness['output'];allowed=coefficients(candidate,params)
    if target not in allowed:raise CandidateError('Replay output outside candidate target')
    if target=='linear_readout':
        expected_x=sum(n*w*v for n,w,v in zip(params['N'],allowed[target],xq));expected_z=sum(n*w*v for n,w,v in zip(params['N'],allowed[target],zq))
    else:expected_x=outputs(params,xq)[target];expected_z=outputs(params,zq)[target]
    if expected_x==expected_z or expected_x!=derived_rational(witness['x_output']) or expected_z!=derived_rational(witness['z_output']) or expected_x-expected_z!=derived_rational(witness['difference']):
        raise CandidateError('Replay claimed difference does not match exact declared model')
    start=time.monotonic();deadline=start+wall_budget_s
    x=np.array(list(map(float,xq)));z=np.array(list(map(float,zq)))
    n=candidate.n_sites;N=np.array(list(map(float,params['N'])));a=np.array(list(map(float,params['a'])))
    c=np.array(list(map(float,params['c'])));r=np.array([float(u+v+w) for u,v,w in zip(params['a'],params['b'],params['c'])])
    def rhs(t,state):
        if time.monotonic()>=deadline:raise TimeoutError('Numeric replay budget exhausted')
        return np.r_[a-r*state[:n],np.dot(N,c*state[:n])]
    solves=[]
    for state in (x,z):
        result=solve_ivp(rhs,(0.,.05),np.r_[state,0.],rtol=1e-10,atol=1e-13,max_step=.01)
        if not result.success:raise RuntimeError(result.message)
        solves.append({'elapsed_s':float(result.t[-1]),'initial_state':state.tolist(),'final_state':result.y[:n,-1].tolist(),
                       'initial_stored_amount':float(np.dot(N,state)),'initial_stored_amount_rate':float(np.dot(N,a-r*state)),
                       'initial_trapping_rate':float(np.dot(N,c*state)),
                       'final_stored_amount':float(np.dot(N,result.y[:n,-1])),'cumulative_trapped_mol':float(result.y[-1,-1]),
                       'solver':'scipy.solve_ivp/RK45','success':True,'evaluations':result.nfev})
    target=witness['output'];exact=float(derived_rational(witness['difference']))
    if target=='linear_readout':
        w=np.array([float(candidate.weight.evaluate(params,i)) for i in range(n)])
        replay_difference=float(np.dot(N*w,x-z))
    else:replay_difference=solves[0]['initial_'+target]-solves[1]['initial_'+target]
    return {'status':'replayed','scope':'Actual numerical integration of declared fixed-rate synthetic equations, not a proof',
            'initial_output_difference':replay_difference,'exact_rational_difference':str(witness['difference']),
            'matches_exact_instantaneous_difference':bool(np.isclose(replay_difference,exact,rtol=1e-10,atol=1e-14)),
            'solves':solves,'wall_s':time.monotonic()-start,'scientific_N_added':0}

def evaluate_candidate(candidate_data,model_data,wall_budget_s=1.,numeric_replay=True):
    start=time.monotonic();candidate=None
    result={'status':'invalid_syntax','scope':SCOPE,'kernel_checked':False,'evidence_category':'analytic_exact_rational_model_check',
            'proof_reference':{'declaration':'Naheng.Reduction.class_readout_sufficient_iff_shared_coefficients','binding_status':'reference_only_root_must_verify'},
            'role':model_data.get('role') if isinstance(model_data,dict) else None,'structural_family_id':model_data.get('structural_family_id') if isinstance(model_data,dict) else None,
            'witness':None,'numeric_replay':None,'features':None,'condition_satisfied':None}
    try:
        candidate=parse_candidate(candidate_data);params=parse_model(model_data)
        result.update(candidate_id=candidate.candidate_id,model_id=model_data['model_id'],features=candidate.features(),
                      exact_nonempty_domain_witness=candidate.domain_witness)
        if candidate.n_sites!=len(params['N']):raise CandidateError('Candidate/model dimensions mismatch')
        r=[a+b+c for a,b,c in zip(params['a'],params['b'],params['c'])]
        def spread(values):
            return max(max(values[i] for i in range(candidate.n_sites) if candidate.groups[i]==g)
                       -min(values[i] for i in range(candidate.n_sites) if candidate.groups[i]==g)
                       for g in set(candidate.groups))
        result['features'].update(model_total_capacity_mol=float(sum(params['N'])),
            model_within_group_total_rate_spread_s_inv=float(spread(r)),
            model_within_group_side_rate_spread_s_inv=float(spread(params['c'])))
        coeffs=coefficients(candidate,params)
        result['nontrivial_output']=any(v!=0 for values in coeffs.values() for v in values)
        if wall_budget_s<=0 or time.monotonic()-start>=wall_budget_s:raise TimeoutError('Candidate budget exhausted before evaluation')
        satisfied=conditions_hold(candidate,params);result['condition_satisfied']=satisfied
        if not satisfied:
            result.update(status='condition_not_satisfied',reason='Declared parameter premises not satisfied; neither false nor verified')
        else:
            target_coefficients=coeffs
            for target,w in target_coefficients.items():
                pair=next(((i,j) for i in range(candidate.n_sites) for j in range(i)
                           if candidate.groups[i]==candidate.groups[j] and w[i]!=w[j]),None)
                if pair is None:continue
                i,j=pair;s=params['N'][i]+params['N'][j]
                x=[Fraction(0)]*candidate.n_sites;z=x.copy();x[i]=params['N'][j]/s;z[j]=params['N'][i]/s
                ox,oz=outputs(params,x),outputs(params,z)
                if target=='linear_readout':
                    ox[target]=sum(n*u*v for n,u,v in zip(params['N'],w,x));oz[target]=sum(n*u*v for n,u,v in zip(params['N'],w,z))
                witness={'x':[str(v) for v in x],'z':[str(v) for v in z],'pair':[i,j],
                    'same_class_amounts':[str(v) for v in class_amounts(params,candidate.groups,x)],
                    'same_total_amount':str(ox['stored_amount']),'output':target,'x_output':str(ox[target]),
                    'z_output':str(oz[target]),'difference':str(ox[target]-oz[target]),
                    'physical_cube':all(0<=v<=1 for v in x+z),'parameter_premises_hold':True}
                assert witness['physical_cube'] and class_amounts(params,candidate.groups,x)==class_amounts(params,candidate.groups,z) and ox[target]!=oz[target]
                result.update(status='counterexample_found',witness=witness,reason='Exact positive-mass within-class analytic witness')
                if numeric_replay:result['numeric_replay']=replay_counterexample(candidate_data,model_data,witness,max(0.,wall_budget_s-(time.monotonic()-start)))
                break
            else:result.update(status='verified_condition',reason='All specified linear output coefficients shared in each class for this exact rational model; no new universal/kernel theorem')
            if time.monotonic()-start>=wall_budget_s:raise TimeoutError('Candidate evaluation budget exhausted')
    except CandidateError as e:result.update(status='invalid_syntax',reason=str(e),witness=None,numeric_replay=None)
    except TimeoutError as e:result.update(status='timeout_unknown',reason=str(e),witness=None,numeric_replay=None)
    result['wall_s']=time.monotonic()-start
    return result
