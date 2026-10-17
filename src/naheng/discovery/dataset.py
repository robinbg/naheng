"""Reproducible structural families, first-freeze roles and training-only feedback."""
from fractions import Fraction
from pathlib import Path
import itertools,json,random,math
from .grammar import canonical_sha,parse_candidate,parameter,total_rate_expr,DOMAIN,CandidateError
from .counterexamples import evaluate_candidate,parse_model

ROLE_STRUCTURES={'train':[(2,[2]),(3,[3]),(4,[2,2])],
                 'validation':[(5,[3,2]),(6,[2,2,2])],'test':[(7,[4,3]),(8,[2,3,3])]}

def structural_descriptor(n,sizes,shared_r,shared_c):
    return {'n_sites':n,'group_sizes':sizes,'shared_total_rate':shared_r,'shared_side_rate':shared_c}

def build_dataset(seed=20261014):
    rng=random.Random(seed);roles={r:[] for r in ROLE_STRUCTURES}
    for role,structures in ROLE_STRUCTURES.items():
        for n,sizes in structures:
            groups=[g for g,size in enumerate(sizes) for _ in range(size)]
            for shared_r,shared_c in itertools.product([True,False],repeat=2):
                structural=structural_descriptor(n,sizes,shared_r,shared_c)
                family='family-'+canonical_sha(structural)
                for variant in range(2):
                    base_r=[Fraction(rng.randint(6,12),2) for _ in sizes]
                    base_c=[Fraction(rng.randint(1,3),10) for _ in sizes]
                    params={k:[] for k in ('N','a','b','c')};local=[0]*len(sizes)
                    for i,g in enumerate(groups):
                        ri=base_r[g]+(Fraction(local[g],3) if not shared_r else 0)
                        ci=base_c[g]+(Fraction(local[g],30) if not shared_c else 0)
                        split=Fraction(rng.randint(1,3),4)
                        params['N'].append(Fraction(rng.randint(1,9),1000))
                        params['a'].append((ri-ci)*split);params['b'].append((ri-ci)*(1-split));params['c'].append(ci);local[g]+=1
                    raw={'schema_version':1,'model_id':'model-'+canonical_sha({'family':family,'variant':variant,'parameters':{k:list(map(str,v)) for k,v in params.items()}}),
                         'structural_family_id':family,'role':role,'groups':groups,
                         'parameters':{k:list(map(str,v)) for k,v in params.items()},
                         'units':{'N':'mol','a':'s^-1','b':'s^-1','c':'s^-1'},'fixed_external_rates':True}
                    parse_model(raw);roles[role].append(raw)
    return {'schema_version':1,'seed':seed,'role_structures':ROLE_STRUCTURES,'roles':roles}

def expected_family_roles():
    return {'family-'+canonical_sha(structural_descriptor(n,sizes,r,c)):role
            for role,structures in ROLE_STRUCTURES.items() for n,sizes in structures
            for r,c in itertools.product([True,False],repeat=2)}

def actual_structural_family_id(model):
    params=parse_model(model);groups=model['groups'];n=len(groups)
    sizes=[groups.count(g) for g in sorted(set(groups))]
    r=[a+b+c for a,b,c in zip(params['a'],params['b'],params['c'])]
    shared_r=all(r[i]==r[j] for i in range(n) for j in range(i) if groups[i]==groups[j])
    shared_c=all(params['c'][i]==params['c'][j] for i in range(n) for j in range(i) if groups[i]==groups[j])
    return 'family-'+canonical_sha(structural_descriptor(n,sizes,shared_r,shared_c))

def validate_roles(dataset):
    expected=expected_family_roles();seen={};ids=set()
    if set(dataset['roles'])!=set(ROLE_STRUCTURES):raise CandidateError('Three frozen nonempty roles required')
    for role,models in dataset['roles'].items():
        if not models:raise CandidateError('Empty structural role')
        for model in models:
            parse_model(model);family=model['structural_family_id']
            if model['role']!=role or expected.get(family)!=role or actual_structural_family_id(model)!=family:raise CandidateError('Frozen structural-family role cannot be relabelled')
            if family in seen and seen[family]!=role:raise CandidateError('Structural family leaked across roles')
            if model['model_id'] in ids:raise CandidateError('Duplicate model identity')
            seen[family]=role;ids.add(model['model_id'])
    return True

def freeze_dataset(directory,dataset):
    validate_roles(dataset);directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    identity=canonical_sha(dataset);freeze=directory/'freeze.json'
    if freeze.exists():
        saved=json.loads(freeze.read_text())
        if saved['dataset_sha256']!=identity:raise CandidateError('First dataset freeze is immutable')
        for role,sha in saved['role_sha256'].items():
            if canonical_sha(json.loads((directory/(role+'.json')).read_text()))!=sha:raise CandidateError('Frozen role artifact was changed')
        return saved
    record={'schema_version':1,'dataset_sha256':identity,'seed':dataset['seed'],
            'role_sha256':{role:canonical_sha(models) for role,models in dataset['roles'].items()},
            'role_model_counts':{role:len(models) for role,models in dataset['roles'].items()},
            'structural_family_roles':expected_family_roles(),'test_used_for_search':False}
    for role,models in dataset['roles'].items():
        with (directory/(role+'.json')).open('x',encoding='utf-8') as out:json.dump(models,out,indent=2)
    with freeze.open('x',encoding='utf-8') as out:json.dump(record,out,indent=2)
    return record

def candidate_templates():
    relations=[{'kind':'within_group_equal','expression':total_rate_expr()},
               {'kind':'within_group_equal','expression':parameter('c')}]
    templates=[]
    for subset in itertools.product([False,True],repeat=2):
        raw={'parameter_relations':[r for r,take in zip(relations,subset) if take],'target':{'kind':'joint_rates'}}
        templates.append({'template_id':'template-'+canonical_sha(raw),**raw})
    for target,rs in [({'kind':'linear_readout','weight_expression':parameter('a')},relations),({'kind':'trapping_rate'},[])]:
        raw={'parameter_relations':rs,'target':target};templates.append({'template_id':'template-'+canonical_sha(raw),**raw})
    return templates

def instantiate(template,model):
    raw={'schema_version':1,'n_sites':len(model['groups']),'groups':model['groups'],'domain':DOMAIN,
         'parameter_relations':template['parameter_relations'],'target':template['target']}
    return parse_candidate(raw).to_dict()

def search_feedback(templates,models,wall_budget_s=1.):
    expected=expected_family_roles()
    if any(m['role']!='train' or expected.get(m['structural_family_id'])!='train' or actual_structural_family_id(m)!=m['structural_family_id'] for m in models):
        raise CandidateError('Heldout structural models forbidden in search/acquisition feedback')
    feedback=[]
    for model in models:
        for template in templates:
            row=evaluate_candidate(instantiate(template,model),model,wall_budget_s)
            row.update(template_id=template['template_id'],model_sha256=canonical_sha(model),used_for_search=True)
            feedback.append(row)
    return feedback

def _feedback_context(dataset=None,templates=None):
    """Construct identities from frozen generated inputs, never feedback flags.

    An explicit dataset must be the whole reproducible first-freeze dataset
    for its seed. The default is the original pilot, including heldout models
    so their actual IDs/hashes cannot be relabelled as training observations.
    Explicit templates may use the existing full bounded grammar; their ID
    is recomputed from the actual structure rather than trusted as a label.
    """
    data=build_dataset() if dataset is None else dataset
    if (not isinstance(data,dict) or type(data.get('seed')) is not int
            or not 0<=data['seed']<2**31):
        raise CandidateError('Frozen feedback dataset context required')
    validate_roles(data)
    if canonical_sha(data)!=canonical_sha(build_dataset(data['seed'])):
        raise CandidateError('Frozen feedback model content cannot be substituted')
    models={m['model_id']:m for role in data['roles'].values() for m in role}
    declared=candidate_templates() if templates is None else templates
    if not isinstance(declared,list) or not declared:
        raise CandidateError('Frozen feedback template context required')
    template_map={}
    for template in declared:
        if not isinstance(template,dict) or set(template)!={'template_id','parameter_relations','target'}:
            raise CandidateError('Frozen feedback template structure required')
        structure={key:template[key] for key in ('parameter_relations','target')}
        expected='template-'+canonical_sha(structure)
        if template['template_id']!=expected or expected in template_map:
            raise CandidateError('Frozen feedback template identity mismatch')
        # Type/domain admission retains the existing grammar; no new fixed
        # relation or target whitelist is used as a substitute for parsing.
        instantiate(template,data['roles']['train'][0])
        template_map[expected]=template
    return models,template_map,canonical_sha(data)

def training_feedback_rows(feedback,*,dataset=None,templates=None):
    models,template_map,dataset_sha=_feedback_context(dataset,templates)
    if not isinstance(feedback,list):
        raise CandidateError('Actual feedback rows must be a list')
    adopted=[]
    for row in feedback:
        if not isinstance(row,dict) or row.get('role')!='train' or row.get('used_for_search') is not True:
            raise CandidateError('Heldout feedback cannot enter acquisition or training')
        if not isinstance(row.get('model_id'),str) or not isinstance(row.get('template_id'),str):
            raise CandidateError('Frozen feedback model/template identity must be text')
        model=models.get(row.get('model_id'))
        if (model is None or model['role']!='train'
                or expected_family_roles().get(model['structural_family_id'])!='train'
                or row.get('structural_family_id')!=model['structural_family_id']
                or row.get('model_sha256')!=canonical_sha(model)):
            raise CandidateError('Heldout feedback or substituted frozen model identity')
        template=template_map.get(row.get('template_id'))
        if template is None:
            raise CandidateError('Frozen feedback template identity mismatch')
        structure=instantiate(template,model)
        candidate=parse_candidate(structure)
        if row.get('candidate_id')!=candidate.candidate_id:
            raise CandidateError('Frozen feedback candidate structure identity mismatch')
        for key,expected in [('model_context',model),('candidate_context',structure),('template_context',template)]:
            if key in row and canonical_sha(row[key])!=canonical_sha(expected):
                raise CandidateError('Frozen feedback '+key+' was substituted')
        # Pure exact-rational evaluation verifies features and decisive labels.
        # It performs no solve_ivp/ODE replay and retains the original measured
        # cost instead of substituting the cost of this adoption check.
        exact=evaluate_candidate(structure,model,wall_budget_s=120,numeric_replay=False)
        if canonical_sha(row.get('features'))!=canonical_sha(exact['features']):
            raise CandidateError('Feedback features do not match frozen candidate/model')
        status=row.get('status')
        if status not in ('verified_condition','counterexample_found','condition_not_satisfied','timeout_unknown'):
            raise CandidateError('Feedback status is inconsistent with a valid frozen candidate/model')
        if status!='timeout_unknown':
            if (status!=exact['status'] or row.get('condition_satisfied') is not exact['condition_satisfied']
                    or canonical_sha(row.get('witness'))!=canonical_sha(exact['witness'])):
                raise CandidateError('Feedback label/witness does not match actual frozen equations')
        elif row.get('condition_satisfied') is not None and row.get('condition_satisfied') is not exact['condition_satisfied']:
            raise CandidateError('Unknown feedback cannot claim contrary parameter conditions')
        if row.get('nontrivial_output') is not exact['nontrivial_output']:
            raise CandidateError('Feedback target output identity mismatch')
        if row.get('kernel_checked') is not False:
            raise CandidateError('Analytic feedback cannot assert kernel proof completion')
        cost=row.get('wall_s')
        if type(cost) not in (int,float) or not math.isfinite(cost) or cost<0:
            raise CandidateError('Actual feedback cost must be finite and nonnegative')
        adopted.append({'candidate_id':candidate.candidate_id,'template_id':template['template_id'],
            'features':dict(exact['features']),'status':status,'wall_s':cost,
            'condition_satisfied':row.get('condition_satisfied'),'kernel_checked':False,
            'scope':exact['scope'],'nontrivial_output':exact['nontrivial_output'],
            'model_id':model['model_id'],'model_sha256':canonical_sha(model),
            'structural_family_id':model['structural_family_id'],'role':'train',
            'dataset_sha256':dataset_sha,'candidate_sha256':canonical_sha(structure),
            'template_sha256':canonical_sha({k:template[k] for k in ('parameter_relations','target')})})
    return adopted

def freeze_selection(templates,feedback,*,dataset=None):
    if not feedback:raise CandidateError('Nonempty real training feedback required before selection freeze')
    training_feedback_rows(feedback,dataset=dataset,templates=templates)
    return {'schema_version':1,'frozen':True,'templates_sha256':canonical_sha(templates),
            'training_feedback_sha256':canonical_sha(feedback),'candidate_selection_scope':'fixed enumeration baseline, not a learned A01 selector'}

def evaluate_holdout(selection,templates,models,role,wall_budget_s=1.):
    if role not in ('validation','test') or not selection.get('frozen') or selection['templates_sha256']!=canonical_sha(templates):
        raise CandidateError('Heldout evaluation requires frozen candidate templates')
    expected=expected_family_roles()
    if any(m['role']!=role or expected.get(m['structural_family_id'])!=role or actual_structural_family_id(m)!=m['structural_family_id'] for m in models):raise CandidateError('Heldout role mismatch')
    rows=[]
    for model in models:
        for template in templates:
            r=evaluate_candidate(instantiate(template,model),model,wall_budget_s)
            r.update(template_id=template['template_id'],model_sha256=canonical_sha(model),used_for_search=False)
            rows.append(r)
    return rows

def load_profile(path):
    profile=json.loads(Path(path).read_text(encoding='utf-8'))
    if (profile.get('schema_version')!=1 or profile.get('profile')!='finite_affine_sites_v1'
            or type(profile.get('seed')) is not int or not 0<=profile['seed']<2**31
            or profile.get('max_sites')!=16 or profile.get('max_expression_nodes')!=32
            or profile.get('max_expression_depth')!=5 or profile.get('variants_per_structural_family')!=2
            or profile.get('train_n_sites')!=[2,3,4] or profile.get('validation_n_sites')!=[5,6]
            or profile.get('test_n_sites')!=[7,8] or profile.get('test_allowed_for_search_or_training') is not False
            or profile.get('kernel_checked') is not False
            or profile.get('candidate_selector')!='fixed_enumeration_baseline_not_A01_learning'
            or type(profile.get('single_evaluation_wall_s')) not in (int,float) or not 0<profile.get('single_evaluation_wall_s',0)<=120
            or profile.get('worker_hard_timeout_s')!=120 or profile.get('memory_limit_gib')!=8):
        raise CandidateError('Typed v1 profile/role/resource freeze mismatch')
    return profile
