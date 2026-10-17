"""Replayable choose -> actual A00 evaluation -> posterior update session."""
from pathlib import Path
import copy,hashlib,json,random,time
from collections import Counter
from .grammar import CandidateError,canonical_sha,parse_candidate
from .counterexamples import evaluate_candidate
from .dataset import candidate_templates,instantiate
from .learner import BayesianLearner,trusted_registry,prediction_features,validate_feedback
from .acquisition import DEFAULT_CONFIG,validate_config,rank_pool,realized_utility

def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8');temp.replace(path)

def load_data(data):
    if isinstance(data,dict):return copy.deepcopy(data)
    path=Path(data);freeze=json.loads((path/'freeze.json').read_text(encoding='utf-8'))
    roles={r:json.loads((path/(r+'.json')).read_text(encoding='utf-8')) for r in ('train','validation','test')}
    from .dataset import ROLE_STRUCTURES
    result={'schema_version':1,'seed':freeze['seed'],'role_structures':ROLE_STRUCTURES,'roles':roles}
    if canonical_sha(result)!=freeze['dataset_sha256']:raise CandidateError('Frozen data content hash mismatch')
    return result

def make_pool(data,registry):
    pool=[]
    for model in data['roles']['train']:
        for template in candidate_templates():
            candidate=instantiate(template,model);c=parse_candidate(candidate)
            identity={'candidate_id':c.candidate_id,'model_sha256':canonical_sha(model),'template_id':template['template_id']}
            pool.append({'item_id':'item-'+canonical_sha(identity),**identity,'model_id':model['model_id'],
                'structural_family_id':model['structural_family_id'],'role':'train','candidate':candidate,
                'features':prediction_features(candidate,model)})
    if len({x['item_id'] for x in pool})!=len(pool):raise CandidateError('Duplicate pool identity')
    return sorted(pool,key=lambda x:x['item_id'])

def bound_feedback(item,row,registry):
    row=copy.deepcopy(row)
    # Evaluator metadata must bind to the selected item. Only provenance fields absent from A00 are added.
    row.update(template_id=item['template_id'],model_sha256=item['model_sha256'],used_for_search=True)
    validate_feedback(item,row,registry);return row

def deterministic_actual_ops(row):
    if row['status'] in ('timeout_unknown','invalid_syntax'):return None
    replay=row.get('numeric_replay')
    return 1+(sum(s['evaluations'] for s in replay['solves']) if replay else 0)

def run_pilot(root,data,out,config=None,*,stop_after=None,evaluate_fn=None,strategy='learned'):
    """Public small session API; root registers CLI. No holdout labels used."""
    root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    config=validate_config(copy.deepcopy(DEFAULT_CONFIG if config is None else config))
    if strategy not in ('learned','random','enumeration'):raise CandidateError('Unknown baseline strategy')
    data=load_data(data);registry=trusted_registry(data);pool=make_pool(data,registry);byid={i['item_id']:i for i in pool}
    identities={'dataset_sha256':canonical_sha(data),'train_sha256':canonical_sha(data['roles']['train']),
        'config_sha256':canonical_sha(config),'pool_sha256':canonical_sha(pool),'strategy':strategy,
        'implementation_sha256':{name:hashlib.sha256((Path(__file__).parent/(name+'.py')).read_bytes()).hexdigest()
                                 for name in ('learner','acquisition','session')},
        'feature_scope':'pre_evaluation_AST_and_raw_capacity_continuous_rate_spread_only',
        'kernel_checked':False}
    target=min(len(pool),config['initial_points']+config['iterations']);end=target if stop_after is None else min(target,stop_after)
    if type(end) is not int or end<0:raise CandidateError('Invalid stop limit')
    checkpoint=out/'checkpoint.json';events=[];rng=random.Random(config['seed'])
    initial=rng.sample([i['item_id'] for i in pool],min(config['initial_points'],len(pool)))
    random_tail=[i['item_id'] for i in pool if i['item_id'] not in initial];rng.shuffle(random_tail)
    learner=BayesianLearner(config['prior_precision'],config['observation_noise'])
    if checkpoint.exists():
        saved=json.loads(checkpoint.read_text(encoding='utf-8'))
        if saved['identities']!=identities:raise CandidateError('Resume config/data/pool identity mismatch')
        if saved['state_sha256']!=canonical_sha(saved['state']):raise CandidateError('Checkpoint payload hash mismatch')
        state=saved['state'];events=state['events'];learner=BayesianLearner.restore(state['learner'])
        # Rebuild posterior from trusted input and retained measured feedback rather than accept arbitrary matrices.
        rebuilt=BayesianLearner(config['prior_precision'],config['observation_noise'])
        for event in events:
            item=byid.get(event['item_id'])
            if item is None:raise CandidateError('Checkpoint item absent from pool')
            rebuilt.update(item,event['feedback'],registry)
        if rebuilt.state()!=learner.state():raise CandidateError('Checkpoint fitting provenance differs from actual feedback')
        if len(events)!=len(learner.observed):raise CandidateError('Checkpoint event/update count differs')
    else:
        write_json(out/'pre-evaluation-pool.json',{'identities':identities,'config':config,'pool':pool,
                    'initial_item_ids':initial,'heldout_labels_read':False})
    evaluator=evaluate_candidate if evaluate_fn is None else evaluate_fn
    started=time.perf_counter()
    while len(events)<end:
        seen={e['item_id'] for e in events};pending=[i for i in pool if i['item_id'] not in seen]
        step=len(events);scores=rank_pool(pending,learner,config,registry)
        if step<len(initial):chosen=initial[step];phase='initial'
        elif strategy=='learned':chosen=scores[0]['item_id'];phase='acquisition'
        elif strategy=='random':chosen=random_tail[step-len(initial)];phase='baseline_random'
        else:chosen=sorted(i['item_id'] for i in pending)[0];phase='baseline_enumeration'
        item=byid[chosen];remaining=[i for i in pending if i['item_id']!=chosen]
        oldnext=rank_pool(remaining,learner,config,registry)
        selection_sha=canonical_sha({'step':step,'scores':scores,'chosen':chosen,'posterior':learner.state()})
        # Persist selection before evaluator call: outcome cannot influence this choice.
        write_json(out/'pending-selection.json',{'step':step,'item_id':chosen,'selection_sha256':selection_sha,
                    'score_sha256':canonical_sha(scores),'top_scores':scores[:5]})
        before=canonical_sha(learner.state());wall_start=time.perf_counter()
        row=evaluator(item['candidate'],registry[item['model_id']]['model'],wall_budget_s=config['single_evaluation_wall_s'],numeric_replay=True)
        elapsed=time.perf_counter()-wall_start;row=bound_feedback(item,row,registry)
        targets=learner.update(item,row,registry);newnext=rank_pool(remaining,learner,config,registry)
        event={'step':step,'phase':phase,'item_id':chosen,'model_id':item['model_id'],
            'selection_sha256':selection_sha,'score_sha256':canonical_sha(scores),'top_scores':scores[:5],
            'selected_score':next(r for r in scores if r['item_id']==chosen),
            'feedback':row,'feedback_sha256':canonical_sha(row),'targets':targets,
            'posterior_before_sha256':before,'posterior_after_sha256':canonical_sha(learner.state()),
            'counterfactual_next_before_update':oldnext[0]['item_id'] if oldnext else None,
            'next_after_update':newnext[0]['item_id'] if newnext else None,
            'choice_changed_by_this_feedback':bool(oldnext and newnext and oldnext[0]['item_id']!=newnext[0]['item_id']),
            'actual_evaluation_wall_s':elapsed,'actual_rhs_plus_analytic_ops':deterministic_actual_ops(row),
            'realized_utility':realized_utility(item,row,config)}
        events.append(event);state={'events':events,'learner':learner.state(),'initial_item_ids':initial,'rng_state':rng.getstate()}
        write_json(checkpoint,{'identities':identities,'state_sha256':canonical_sha(state),'state':state})
    counts=dict(Counter(e['feedback']['status'] for e in events))
    report={'scope':'A01 fitted finite synthetic rational-model ranking; no new Lean theorem/real cell/LLM',
        **identities,'requested_budget':config['initial_points']+config['iterations'],'requested_pool_count':len(pool),
        'actual_evaluations':len(events),'initial_completed':min(len(events),len(initial)),
        'acquisition_completed':max(0,len(events)-len(initial)),'complete':len(events)==target,
        'pool_exhausted':target<len(initial)+config['iterations'],'status_counts':counts,
        'unknown_count':counts.get('timeout_unknown',0),'inapplicable_count':counts.get('condition_not_satisfied',0),
        'all_evaluated_denominator':len(events),'verified_nontrivial_count':sum(e['feedback']['status']=='verified_condition' and e['feedback'].get('nontrivial_output') is True for e in events),
        'new_feedback_choice_changes':sum(e['choice_changed_by_this_feedback'] for e in events),
        'acquisition_feedback_choice_changes':sum(e['phase']=='acquisition' and e['choice_changed_by_this_feedback'] for e in events),
        'total_realized_utility':sum(e['realized_utility'] for e in events),
        'actual_evaluation_wall_s':sum(e['actual_evaluation_wall_s'] for e in events),
        'invocation_wall_s':time.perf_counter()-started,
        'actual_rhs_plus_analytic_ops':sum(e['actual_rhs_plus_analytic_ops'] or 0 for e in events),
        'cost_scope':'actual recorded RHS counts + one analytic evaluation; proxy not speed or monetary cost',
        'unknown_cost_not_imputed':True,'posterior_sha256':canonical_sha(learner.state()),
        'total_ops_scope':'sum of known completed evaluation operation counts; unknown cost omitted, not asserted zero',
        'selected_sequence_sha256':canonical_sha([e['item_id'] for e in events]),
        'trained_head_counts':{k:len(h.y) for k,h in learner.heads.items()},
        'validation_used_for_training_or_acquisition':False,'test_used_for_training_or_acquisition':False,
        'scientific_N_added':0,'kernel_checked':False,'new_theorem_claim':False}
    write_json(out/'report.json',report);return report
