"""X01 protocol registration. Registration never executes an experiment.

Missing scientific identities/runners are recorded as blockers, not supplied by
defaults. A persisted blocked registration cannot later turn itself into an
authorization; changed inputs, code or decisions require a new revision.
"""
from __future__ import annotations
import hashlib,json,math,re
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel,ConfigDict,Field,model_validator
from naheng.runtime.artifacts import code_hash

BASELINES=('B0','B1','B2','B3','B4','B5','B6')
THEORY=('manual_conditions','classical_aggregation','random_enumeration','learned_without_counterexamples','counterexample_without_learning','full_feedback')
LINKAGE=('L0','L1','L2','L3','L4','L5','L6','badge_only_negative_control')
DEPENDENCIES=('G04','C02','A03','P03','D02','W02')
ROLES=('train','validation','test')
FAILURES=('numerical_failure','timeout','cancelled','out_of_domain','refused','interrupted','incomplete')
# Adding a callable experiment runner requires a separately reviewed code change.
# A user-supplied file reference is a frozen input, never executable authority.
REGISTERED_ADAPTERS={}
class UniqueSafeLoader(yaml.SafeLoader):pass
def _unique_mapping(loader,node,deep=False):
    result={}
    for key_node,value_node in node.value:
        key=loader.construct_object(key_node,deep=deep)
        if key in result:raise ValueError('Duplicate YAML field: '+str(key))
        result[key]=loader.construct_object(value_node,deep=deep)
    return result
UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,_unique_mapping)
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def inside(root,value):
    p=(root/Path(value)).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if not p.is_relative_to(root):raise ValueError('Path must remain inside the project')
    return p
class Strict(BaseModel):model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)
class Ref(Strict):
    path:str
    sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
class SeedBlock(Strict):
    start:int=Field(ge=0)
    count:int=Field(ge=1,le=100000)
class Budget(Strict):
    offline_data_rows:int=Field(ge=1)
    fit_calls:int=Field(ge=1)
    initial_queries:int=Field(ge=1)
    adaptive_queries:int=Field(ge=0)
    high_fidelity_queries:int=Field(ge=1)
    proof_attempts:int=Field(ge=1)
    single_call_timeout_s:int=Field(ge=1,le=120)
    memory_limit_bytes:int=Field(ge=1,le=8589934592)
    batch_wall_s:int=Field(ge=1,le=1800)
    online_deadline_s:float=Field(gt=0,le=120)
class Common(Strict):
    observations:list[str]
    evaluator_only:list[str]
    tuning_roles:list[str]
    seed_blocks:dict[str,SeedBlock]
    budget:Budget
    optimization_event_probability_budget:float=Field(gt=0,lt=1)
    common_initial_terminal_task:Literal[True]
    paired_scenarios:Literal[True]
    world_inputs_immutable:Literal[True]
class Arm(Strict):
    id:str
    definition:str
    tuned_frontier:bool
    runner:Ref|None=None
    tuning_ref:Ref|None=None
class Suite(Strict):
    id:Literal['E-T','E-A','E-L']
    hypothesis:str
    primary_metrics:list[str]
    secondary_metrics:list[str]
    runner:Ref|None=None
class Data(Strict):
    public_manifest:Ref
    theory_family_manifest:Ref|None=None
    physical_mapping:Ref|None=None
    independent_risk_queue:Ref|None=None
class Statistics(Strict):
    family_alpha:float=Field(gt=0,lt=1)
    allocation:Literal['bonferroni']
    risk_target:float=Field(gt=0,lt=1)
    events:list[str]
    claim_small_risk:bool
    sampling_unit:Literal['independent_complete_trajectory']
    stopping_rule:Literal['fixed_before_test_no_optional_stopping']
class Failures(Strict):
    include_all_requested:Literal[True]
    statuses:list[str]
    policy:Literal['retain_denominator_report_separately_and_count_unknown_as_event_in_sensitivity']
    retry_policy:Literal['same_identity_no_new_independent_sample']
class Censoring(Strict):
    policy:Literal['retain_last_observed_time_and_right_censor_without_imputed_event']
    capacity_protocol_required:Literal[True]
    conditional_future_policy_required:Literal[True]
class Economics(Strict):
    currency:Literal['CNY']
    energy_unit:Literal['J']
    terms:list[str]
    scope:Literal['actual_executed_flows_only']
    shadow_price_booked_as_cash:Literal[False]
    unsupported_services_enabled:Literal[False]
    common_terminal_rule:Literal['same_initial_inventory_terminal_inventory_capacity_remaining_life_and_early_exit_accounting']
class Protocol(Strict):
    schema_version:Literal[1]
    protocol_id:str=Field(pattern=r'^[a-z][a-z0-9-]{2,79}$')
    revision:int=Field(ge=1)
    supersedes:Ref|None=None
    profile:Literal['pilot','release']
    purpose:str
    common:Common
    baselines:list[Arm]
    theory_methods:list[str]
    linkage_ablations:list[str]
    suites:list[Suite]
    data:Data
    statistics:Statistics
    failures:Failures
    censoring:Censoring
    economics:Economics
    @model_validator(mode='after')
    def complete(self):
        if [a.id for a in self.baselines]!=list(BASELINES):raise ValueError('All B0-B6 arms in fixed order required')
        if not self.baselines[0].tuned_frontier:raise ValueError('B0 must be a tuned frontier, not a weak single point')
        if self.baselines[0].tuning_ref is None:raise ValueError('B0 needs an explicit frozen multi-configuration tuning grid')
        if self.theory_methods!=list(THEORY) or self.linkage_ablations!=list(LINKAGE):raise ValueError('Complete theory and linkage controls required')
        if [s.id for s in self.suites]!=['E-T','E-A','E-L']:raise ValueError('All three experiment suites required')
        if any(not s.hypothesis or not s.primary_metrics or not s.secondary_metrics for s in self.suites):raise ValueError('Hypotheses and primary/secondary metrics required')
        if self.common.observations!=['voltage_V','current_A','temperature_K','timestamp_s']:raise ValueError('Common sensor-only observation contract required')
        if self.common.evaluator_only!=['reference_internal_state','reference_future','event_labels']:raise ValueError('Reference truth must be evaluator-only')
        if self.common.tuning_roles!=['train','validation']:raise ValueError('Test role may never tune parameters or select policies')
        if set(self.common.seed_blocks)!=set(ROLES):raise ValueError('Train/validation/test seeds required')
        sets=[set(range(self.common.seed_blocks[r].start,self.common.seed_blocks[r].start+self.common.seed_blocks[r].count)) for r in ROLES]
        if any(sets[i]&sets[j] for i in range(3) for j in range(i)):raise ValueError('Seed-role overlap forbidden')
        if self.statistics.events!=['voltage_limit','temperature_limit']:raise ValueError('Event-specific operational limits required; no invented fire/plating labels')
        if self.failures.statuses!=list(FAILURES):raise ValueError('Every failure category must remain in the denominator')
        expected=['purchase','sale','thermal_management','maintenance','replacement','residual_value','unserved_energy','early_exit']
        if self.economics.terms!=expected:raise ValueError('Complete common cashflow/terminal accounting required')
        if self.profile=='pilot' and self.statistics.claim_small_risk:raise ValueError('Pilot cannot make a small-risk claim')
        if (self.revision==1)!=(self.supersedes is None):raise ValueError('Each noninitial revision needs its exact predecessor')
        if self.statistics.claim_small_risk and self.common.seed_blocks['test'].count<self.required_zero_event_n:raise ValueError('Fixed test sample count is insufficient for allocated alpha')
        return self
    @property
    def per_claim_alpha(self):return self.statistics.family_alpha/(len(self.baselines)*len(self.statistics.events))
    @property
    def required_zero_event_n(self):return math.ceil(math.log(self.per_claim_alpha)/math.log1p(-self.statistics.risk_target))

class DependencyBlocked(ValueError):pass
def _bind(root,ref,bindings):
    path=inside(root,ref.path)
    if not path.is_file():raise DependencyBlocked('Missing referenced file: '+ref.path)
    actual=file_hash(path)
    if actual!=ref.sha256:raise DependencyBlocked('Referenced file hash changed: '+ref.path)
    bindings[path.relative_to(root).as_posix()]=actual
    return path
def _read_ref(root,ref,bindings):return json.loads(_bind(root,ref,bindings).read_text(encoding='utf-8-sig'))

def inspect_inputs(root,protocol):
    """Read identities and hash bytes; do not fit to or expose held-out rows."""
    bindings={};blockers=[];public=None;role_map=[]
    def missing(code,detail,suites=('E-T','E-A','E-L')):blockers.append({'code':code,'detail':detail,'suites':list(suites)})
    try:
        grid=_read_ref(root,protocol.baselines[0].tuning_ref,bindings)
        rules=[x for x in grid['candidates'] if x['kind']=='rules']
        if len({digest(x) for x in rules})<2 or len(rules)>protocol.common.budget.fit_calls:raise ValueError('B0 must scan multiple frozen rule configurations within its fit budget')
    except (DependencyBlocked,ValueError,KeyError,TypeError) as error:missing('B0_TUNING_GRID_INVALID',str(error))
    try:
        public=_read_ref(root,protocol.data.public_manifest,bindings)
        components={};contents={};seen=set();roles=set()
        for row in public['members']:
            role=row['role'];member=row['member_id'];component=row['leakage_component_id']
            if role not in ROLES or member in seen:raise ValueError('Unique members with explicit train/validation/test roles required')
            seen.add(member);roles.add(role)
            if component in components and components[component]!=role:raise ValueError('Leakage component crosses roles')
            for key in ('raw','observations'):
                _bind(root,Ref.model_validate(row[key]),bindings)
                content=row[key]['sha256']
                if content in contents and contents[content]!=role:raise ValueError('Identical raw or observations content crosses roles')
                contents[content]=role
            content=row['raw']['sha256']
            components[component]=role
            role_map.append({'member_id':member,'role':role,'component':component,'raw_sha256':content,'observations_sha256':row['observations']['sha256']})
        if roles!=set(ROLES):raise ValueError('Public manifest must contain all three roles')
    except (DependencyBlocked,KeyError,ValueError,TypeError) as error:
        missing('PUBLIC_DATA_IDENTITY_INVALID',str(error),('E-A',))
    if protocol.data.theory_family_manifest is None:missing('THEORY_FAMILY_SPLIT_MISSING','No frozen structural/generative train-validation-test family manifest',('E-T',))
    else:
        try:
            families=_read_ref(root,protocol.data.theory_family_manifest,bindings)
            if families.get('split_unit')!='reaction_structure_or_generation_rule' or set(families.get('roles',{}))!=set(ROLES):raise ValueError('Theory family split contract missing')
            groups=[set(families['roles'][r]) for r in ROLES]
            if any(not x for x in groups) or any(groups[i]&groups[j] for i in range(3) for j in range(i)):raise ValueError('Theory families overlap or are empty')
        except (DependencyBlocked,ValueError,KeyError,TypeError) as error:missing('THEORY_FAMILY_SPLIT_INVALID',str(error),('E-T',))
    if protocol.data.physical_mapping is None:missing('D02_PHYSICAL_MAPPING_MISSING','The measured cohort has no accepted same-cohort identity/parameter mapping',('E-A',))
    else:
        try:
            mapping=_read_ref(root,protocol.data.physical_mapping,bindings)
            if public is None or mapping.get('cohort_id')!=public.get('cohort_id') or mapping.get('status')!='verified' or mapping.get('scope')!='same_cohort_physical_parameter_mapping':raise ValueError('Physical mapping does not bind this exact measured cohort')
            _bind(root,Ref.model_validate(mapping['independent_review']),bindings)
            if public.get('D02_complete') is not True or public.get('physical_independence_status')!='verified':raise ValueError('Source cohort physical identity is still unknown')
        except (DependencyBlocked,ValueError,KeyError,TypeError) as error:missing('D02_PHYSICAL_MAPPING_INVALID',str(error),('E-A',))
    if protocol.data.independent_risk_queue is None:missing('INDEPENDENT_RISK_QUEUE_MISSING','No post-policy-freeze independent operational trajectory queue',('E-A',))
    else:
        try:
            queue=_read_ref(root,protocol.data.independent_risk_queue,bindings)
            if queue.get('sampling_unit')!='independent_complete_trajectory' or queue.get('population_kind')!='operational' or queue.get('independence_status')!='verified':raise ValueError('Stress/replay/unknown rows cannot establish independent operational risk')
            if queue.get('drawn_after_policy_freeze') is not True:raise ValueError('Risk queue must be drawn after policy freeze')
            frozen=_read_ref(root,Ref.model_validate(queue['policy_freeze']),bindings)
            if frozen.get('status')!='frozen_before_test' or frozen.get('selection_roles')!=['train','validation'] or set(frozen.get('strategy_hashes',{}))!=set(BASELINES):
                raise ValueError('All seven selected policies must be frozen from train/validation before test')
            if any(not isinstance(x,str) or re.fullmatch('[0-9a-f]{64}',x) is None for x in frozen['strategy_hashes'].values()):raise ValueError('Selected policy hashes required')
            _bind(root,Ref.model_validate(queue['independent_review']),bindings)
            entries=queue['entries'];ids=[x['independent_unit_id'] for x in entries];seeds=[x['seed'] for x in entries]
            if len(entries)!=protocol.common.seed_blocks['test'].count or len(set(ids))!=len(ids) or len(set(seeds))!=len(seeds):raise ValueError('Risk queue must have the fixed count of unique independent trajectory identities/seeds')
            if seeds!=list(range(protocol.common.seed_blocks['test'].start,protocol.common.seed_blocks['test'].start+len(seeds))):raise ValueError('Risk queue seed order differs from registration')
            if any(x.get('state')!='not_started' for x in entries):raise ValueError('Already viewed outcomes cannot become a fresh risk queue')
        except (DependencyBlocked,ValueError,KeyError,TypeError) as error:missing('INDEPENDENT_RISK_QUEUE_INVALID',str(error),('E-A',))
    for item in [*protocol.baselines,*protocol.suites]:
        if item.runner is None:missing('RUNNER_UNREGISTERED',item.id+' has a declared comparison but no frozen executable experiment adapter',tuple(s.id for s in protocol.suites) if isinstance(item,Arm) else (item.id,))
        else:
            try:
                _bind(root,item.runner,bindings)
                if REGISTERED_ADAPTERS.get(item.id)!=item.runner.sha256:
                    missing('RUNNER_ADAPTER_NOT_INSTALLED',item.id+' has no reviewed dispatch adapter matching its file digest')
            except DependencyBlocked as error:missing('RUNNER_IDENTITY_INVALID',str(error))
    return bindings,blockers,role_map

def _expected_registration(root,config_path):
    """Recompute every field from live frozen inputs, never from a saved claim."""
    raw=config_path.read_bytes();protocol=Protocol.model_validate(yaml.load(raw.decode('utf-8-sig'),Loader=UniqueSafeLoader))
    for ref in [protocol.supersedes,*protocol.data.__dict__.values(),*(x.runner for x in [*protocol.baselines,*protocol.suites]),*(x.tuning_ref for x in protocol.baselines)]:
        if ref is not None:inside(root,ref.path)
    config=protocol.model_dump(mode='json');bindings,blockers,roles=inspect_inputs(root,protocol)
    bindings[config_path.relative_to(root).as_posix()]=hashlib.sha256(raw).hexdigest()
    tasks=yaml.safe_load((root/'TASKS.yaml').read_text(encoding='utf-8'))['tasks']
    requirements=yaml.safe_load((root/'REQUIREMENTS.yaml').read_text(encoding='utf-8'))['requirements']
    if len(tasks)!=45 or len(requirements)!=18:raise ValueError('Original 45 tasks / 18 requirements must remain present')
    bindings['TASKS.yaml']=file_hash(root/'TASKS.yaml')
    bindings['REQUIREMENTS.yaml']=file_hash(root/'REQUIREMENTS.yaml')
    states={x['id']:x['status'] for x in tasks}
    dependency_snapshot={name:states.get(name,'missing') for name in DEPENDENCIES}
    for name,state in dependency_snapshot.items():
        if state!='done':blockers.append({'code':'ORIGINAL_DEPENDENCY_INCOMPLETE','detail':name+': '+state,'suites':['E-T','E-A','E-L']})
    if protocol.supersedes:
        previous=_read_ref(root,protocol.supersedes,bindings)
        if previous.get('protocol_id')!=protocol.protocol_id or previous.get('revision')!=protocol.revision-1:raise ValueError('Revision must identify the exact previous protocol revision')
    identity={'protocol':config,'config_path':config_path.relative_to(root).as_posix(),
              'config_sha256':hashlib.sha256(raw).hexdigest(),'code_hash':code_hash(root),
              'registration_implementation_sha256':file_hash(Path(__file__).resolve()),'input_bindings':bindings,'dependency_snapshot':dependency_snapshot}
    registration_id=digest(identity)
    result={'schema_version':1,'protocol_id':protocol.protocol_id,'revision':protocol.revision,'profile':protocol.profile,
        'registration_id':registration_id,'status':'blocked' if blockers else 'registered','exit_code':2 if blockers else 0,
        'identity':identity,'blockers':blockers,'data_roles':roles,'task_count':len(tasks),'requirement_count':len(requirements),
        'suite_authorization':{s.id:not any(s.id in b['suites'] for b in blockers) for s in protocol.suites},
        'alpha_per_event_policy_claim':protocol.per_claim_alpha,'zero_event_required_n':protocol.required_zero_event_n,
        'fixed_test_trajectory_count':protocol.common.seed_blocks['test'].count,
        'risk_target':protocol.statistics.risk_target,'optimization_risk_budget_distinct_from_statistical_alpha':True,
        'experiment_executed':False,'new_independent_scientific_N':0,'X01_complete':False,
        'scope':'Immutable preregistration and authorization checks only; no experiment or result is fabricated'}
    result['content_sha256']=digest(result)
    return result,config,raw

def _canonical_path(root,protocol):
    return inside(root,Path('artifacts/experiments/preregistrations')/protocol['protocol_id']/('r'+str(protocol['revision'])))

def _check_existing(target,result,config,raw):
    """A matching self-hash is insufficient: compare the full computed record."""
    if any(parent.exists() and not parent.is_dir() for parent in target.parents):
        raise ValueError('Registration destination has an existing non-directory parent')
    if not target.exists():return False
    if not target.is_dir() or {p.name for p in target.iterdir()}!={'registration.json','protocol.json','protocol.source.yaml'}:
        raise ValueError('Existing registration output was modified or is not an empty destination')
    try:
        existing=json.loads((target/'registration.json').read_text(encoding='utf-8'))
        if existing.get('registration_id')!=result['registration_id']:
            raise ValueError('Frozen revision already exists with different inputs/code; create a new revision')
        if existing!=result or json.loads((target/'protocol.json').read_text(encoding='utf-8'))!=config or (target/'protocol.source.yaml').read_bytes()!=raw:
            raise ValueError('Existing registration was modified')
    except (OSError,UnicodeError,TypeError,AttributeError) as error:
        raise ValueError('Existing registration was modified or unreadable') from error
    return True

def _write_registration(target,result,config,raw):
    target.mkdir(parents=True,exist_ok=False)
    with (target/'registration.json').open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
    with (target/'protocol.json').open('x',encoding='utf-8') as stream:json.dump(config,stream,ensure_ascii=False,indent=2,allow_nan=False)
    with (target/'protocol.source.yaml').open('xb') as stream:stream.write(raw)

def preregister(root,config_path,out=None):
    root=Path(root).resolve();config_path=inside(root,config_path)
    result,config,raw=_expected_registration(root,config_path)
    canonical=_canonical_path(root,config)
    target=inside(root,out) if out is not None else canonical
    if target!=canonical and (target.is_relative_to(canonical) or canonical.is_relative_to(target)):
        raise ValueError('Export destination must not contain or be contained by the canonical registration')
    # Preflight both destinations before writing either. A different --out never
    # creates another authority for the same project/protocol/revision.
    canonical_exists=_check_existing(canonical,result,config,raw)
    target_exists=canonical_exists if target==canonical else _check_existing(target,result,config,raw)
    if not canonical_exists:_write_registration(canonical,result,config,raw)
    if target!=canonical and not target_exists:_write_registration(target,result,config,raw)
    return result

def require_authorization(root,registration_path,suite):
    """Future runners call before execution; blocked/stale/tampered input denies."""
    root=Path(root).resolve()
    if suite not in ('E-T','E-A','E-L'):raise ValueError('Unknown experiment suite')
    saved=json.loads(inside(root,registration_path).read_text(encoding='utf-8'))
    if saved.get('content_sha256')!=digest({k:v for k,v in saved.items() if k!='content_sha256'}):raise DependencyBlocked('Registration content was changed')
    identity=saved['identity']
    if saved.get('registration_id')!=digest(identity):raise DependencyBlocked('Registration identity was changed')
    try:
        config_path=inside(root,identity['config_path'])
        expected,config,raw=_expected_registration(root,config_path)
        if expected['status']!='registered' or expected['suite_authorization'].get(suite) is not True:
            raise DependencyBlocked('Live dependency/adapter evidence does not authorize execution')
        if saved!=expected:raise DependencyBlocked('Registration differs from current frozen inputs or computed fields')
        canonical=_canonical_path(root,config)
        if not _check_existing(canonical,expected,config,raw):raise DependencyBlocked('Canonical frozen registration is missing')
    except (ValueError,KeyError,OSError) as error:
        if isinstance(error,DependencyBlocked):raise
        raise DependencyBlocked('Frozen registration cannot authorize execution: '+str(error)) from error
    return {'registration_id':saved['registration_id'],'suite':suite,'authorized':True,'protocol':identity['protocol']}
