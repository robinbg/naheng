"""Frozen utility on actually fitted Bayesian predictions; heldout rejected."""
import math
from .grammar import CandidateError,canonical_sha
from .learner import prediction_features

DEFAULT_CONFIG={'schema_version':1,'profile':'bayesian_finite_sites_pilot_v1','seed':20261014,
    'initial_points':12,'iterations':24,'prior_precision':1.,'observation_noise':1.,'beta':1.2,
    'utility_weights':{'accuracy':1.,'nontrivial':1.,'domain_coverage':1.,'complexity':.08,'cost':.04},
    'single_evaluation_wall_s':1.,'kernel_checked':False,'worker_hard_timeout_s':120,'memory_limit_gib':8}

def validate_config(config):
    if set(config)!=set(DEFAULT_CONFIG):raise CandidateError('Config keys differ from predeclared pilot')
    if (config['schema_version']!=1 or config['profile']!=DEFAULT_CONFIG['profile']
        or type(config['seed']) is not int or not 0<=config['seed']<2**31
        or type(config['initial_points']) is not int or config['initial_points']<1
        or type(config['iterations']) is not int or config['iterations']<0
        or not 0<config['single_evaluation_wall_s']<=120 or config['kernel_checked'] is not False
        or config['worker_hard_timeout_s']!=120 or config['memory_limit_gib']!=8
        or not config['prior_precision']>0 or not config['observation_noise']>0
        or not math.isfinite(config['beta']) or config['beta']<0
        or set(config['utility_weights'])!=set(DEFAULT_CONFIG['utility_weights'])
        or any(not math.isfinite(v) or v<0 for v in config['utility_weights'].values())):
        raise CandidateError('Invalid fixed acquisition profile')
    return config

def assert_train_item(item,registry):
    r=registry.get(item.get('model_id'))
    if (r is None or r['role']!='train' or item.get('role')!='train'
        or r['sha256']!=item.get('model_sha256') or r['family']!=item.get('structural_family_id')
        or item['features']!=prediction_features(item['candidate'],r['model'])):
        raise CandidateError('Heldout/tampered candidate prohibited from acquisition')

def score_item(item,learner,config,registry):
    assert_train_item(item,registry);pred=learner.predict(item['features']);w=config['utility_weights']
    # Regression outputs are bounded as estimates, never probability guarantees.
    clipped={k:min(1.,max(0.,pred[k]['mean'])) for k in ('accuracy','nontrivial','coverage')}
    benefit=(w['accuracy']*clipped['accuracy'])*(w['nontrivial']*clipped['nontrivial'])*(w['domain_coverage']*clipped['coverage'])
    reduction=1.-item['features']['class_fraction'];complexity=item['features']['nodes_scaled']+item['features']['relations_scaled']
    cost=max(0.,pred['cost']['mean'])
    exploration=config['beta']*sum(pred[k]['sd'] for k in ('accuracy','nontrivial','coverage'))/3.
    score=benefit*reduction-w['complexity']*complexity-w['cost']*cost+exploration
    return {'item_id':item['item_id'],'score':score,'benefit':benefit,'complexity':complexity,
            'cost_prediction_log_ops':cost,'exploration':exploration,'predictions':pred}

def rank_pool(pool,learner,config,registry):
    rows=[score_item(item,learner,config,registry) for item in pool]
    return sorted(rows,key=lambda row:(-row['score'],row['item_id']))

def realized_utility(item,row,config):
    """Unknown/inapplicable/zero output receive no verified-value credit."""
    from .learner import feedback_targets
    if row['status']!='verified_condition' or row.get('nontrivial_output') is not True:return 0.
    t=feedback_targets(row);f=item['features'];w=config['utility_weights']
    return max(0.,w['accuracy']*w['nontrivial']*w['domain_coverage']*(1.-f['class_fraction'])
               -w['complexity']*(f['nodes_scaled']+f['relations_scaled'])-w['cost']*t['cost'])
