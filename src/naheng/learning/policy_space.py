"""Declared synthetic full-strategy search domain and fixed-world mapping."""
from dataclasses import asdict, replace
import hashlib
import json
import math
from .strategy_mpc import MPCParameters, MPCStage

BOUNDS = {
    'charge_low_A': (.006, .020), 'charge_high_A': (.003, .015),
    'discharge_low_A': (.003, .015), 'discharge_high_A': (.006, .020),
    'cutoff_voltage_V': (3.15, 3.40), 'max_dod': (.00002, .002),
    'cooling_permission_W': (0., .02), 'heating_permission_W': (0., .02),
    'rest_duration_s': (0., 5.),
}
SPACE_ID = 'synthetic-site-full-policy-v1'
UNITS = {name: ('A' if name.endswith('_A') else 'V' if name.endswith('_V') else
                'W' if name.endswith('_W') else 's' if name.endswith('_s') else '1') for name in BOUNDS}
SOC_BOUNDARY = .6
CONTROL_STEP_S = 2.5
SERVICE_SECONDS = 10.
PREDICTION_STEPS = 4

# Fidelity is declared in work units only (optimizer iterations and candidate
# evaluations). The wall-clock value passed to the planner is a host resource
# backstop, not part of the effort definition: a training label must follow from
# the candidate and its declared work budget, never from how loaded the machine
# happened to be when the query ran. One query executes four plans and is itself
# bounded by the per-query timeout declared in configs/execution.yaml (120 s,
# of which the case worker reserves 8 s), so the backstop stays below
# (120 - 8) / 4 and cannot pre-empt the declared work under an idle host.
WALL_BACKSTOP_S = 25.
EXECUTION_STEPS = 4
PER_QUERY_TIMEOUT_S = 120.
CASE_OVERHEAD_RESERVE_S = 8.


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate(parameters):
    if not isinstance(parameters, dict) or set(parameters) != set(BOUNDS):
        raise ValueError('The exact nine declared policy coordinates are required')
    for name, (low, high) in BOUNDS.items():
        value=parameters[name]
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('Policy coordinate outside declared synthetic domain: '+name)
    return dict(parameters)


def fixed_world(ambient_K=299.15):
    """Same external prices/environment and control/sensor clock for every policy."""
    if type(ambient_K) not in (int,float) or not math.isfinite(ambient_K) or ambient_K<=0:
        raise ValueError('Finite positive fixed-world Kelvin ambient required')
    # Four 2.5s intervals execute. Three future intervals allow the final MPC
    # four-step forecast without changing the actual ten-second service.
    stages=[]
    for index in range(7):
        high_price=2<=index<4
        stages.append({'duration_s':CONTROL_STEP_S,
            'buy_price_per_kWh':.15 if high_price else .05,
            'sell_price_per_kWh':.4 if high_price else .04,'ambient_K':float(ambient_K)})
    return {'world_id':'synthetic-fixed-tariff-ten-second-service-v1',
            'stages':stages,'execution_steps':4,'prediction_steps':PREDICTION_STEPS,
            'service_seconds':SERVICE_SECONDS,'clock_step_s':CONTROL_STEP_S,
            'tariff_source':'synthetic_frontier_predeclared_tariff_v1',
            'provenance_type':'synthetic','scientific_N_added':0}


def map_policy(parameters, *, fidelity='high', world=None):
    p=validate(parameters)
    if fidelity not in ('low','high'):raise ValueError('Declared low/high computational fidelity required')
    world=fixed_world() if world is None else world
    if world != fixed_world(world['stages'][0]['ambient_K']):
        raise ValueError('The fixed external world/control clock cannot be optimized')
    rest_ticks=int(math.floor(p['rest_duration_s']/CONTROL_STEP_S+.5))
    effective_rest=rest_ticks*CONTROL_STEP_S
    common=MPCParameters(current_limit_A=.02,soc_min=.1,soc_max=.95,max_dod=.7,
        thermal_min_W=-.02,thermal_max_W=.02,nominal_terminal_buffer=1e-5,
        prediction_max_step_s=2.5,tariff_source=world['tariff_source'],
        max_iterations=1 if fidelity=='low' else 25,
        max_candidate_evaluations=24 if fidelity=='low' else 120,
        wall_budget_s=WALL_BACKSTOP_S)
    if not WALL_BACKSTOP_S*EXECUTION_STEPS<=PER_QUERY_TIMEOUT_S-CASE_OVERHEAD_RESERVE_S:
        raise ValueError('Declared wall backstop can pre-empt the per-query execution budget')
    policy=replace(common,max_dod=p['max_dod'],voltage_max_V=p['cutoff_voltage_V'],
        soc_bands=((SOC_BOUNDARY,p['charge_low_A'],p['discharge_low_A']),
                   (1.,p['charge_high_A'],p['discharge_high_A'])),
        thermal_min_W=-p['cooling_permission_W'],thermal_max_W=p['heating_permission_W'])
    stages=[]
    for index, external in enumerate(world['stages']):
        resting=index<rest_ticks
        stages.append(MPCStage(**external,min_current_A=0. if resting else -.02,
                               max_current_A=0. if resting else .02))
    return {'parameters':p,'policy_sha256':digest(p),'world':world,'world_sha256':digest(world),
        'policy_mpc_parameters':asdict(policy),'common_mpc_parameters':asdict(common),
        'stages':[asdict(stage) for stage in stages],
        'timing':{'requested_rest_s':p['rest_duration_s'],'effective_rest_s':effective_rest,
                  'quantization_s':CONTROL_STEP_S,'external_timeline_unchanged':True},
        'current_command_resolution_A':1e-8,
        'effort_semantics':{'fidelity':'declared by work units only',
            'work_budget':{'max_iterations':common.max_iterations,
                           'max_candidate_evaluations':common.max_candidate_evaluations},
            'wall_budget_s':common.wall_budget_s,
            'wall_budget_role':'host resource backstop; not a fidelity definition and not a label input',
            'label_determinism':'identical candidate, fidelity and work budget give an identical status whenever the host completes the declared work inside the per-query timeout',
            'genuine_timeout_still_unknown':True,'execution_steps':EXECUTION_STEPS,
            'per_query_timeout_s':PER_QUERY_TIMEOUT_S,'case_overhead_reserve_s':CASE_OVERHEAD_RESERVE_S},
        'low_incumbent_policy':'fully_verified_incumbent_v1' if fidelity=='low' else None,
        'scope':'computational policy search in an uncalibrated synthetic model; no physical risk certificate'}


def check_policy_action(action, stage, policy_parameters, cumulative_soc):
    """Apply policy permissions in addition to the unchanged common safety guard."""
    if not stage.min_current_A-1e-10<=action.current_A<=stage.max_current_A+1e-10:
        raise ValueError('Actual current violates the declared timing/rest permission')
    if not policy_parameters.thermal_min_W-1e-10<=action.thermal_W<=policy_parameters.thermal_max_W+1e-10:
        raise ValueError('Actual heat flow violates the selected heat/cool permission')
    if cumulative_soc and max(cumulative_soc)-min(cumulative_soc)>policy_parameters.max_dod+1e-8:
        raise ValueError('Actual cumulative SOC excursion exceeds the selected DoD policy')
