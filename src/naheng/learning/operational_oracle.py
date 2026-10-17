"""Bounded full-policy MPC/observation/actual-ledger oracle, synthetic only."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
import naheng
from naheng.runtime.artifacts import atomic_json, code_hash
from naheng.runtime.validation_process import run_validation_command
from naheng.runtime.calibration_consumer import _packet
from naheng.runtime.calibration_observer import fork_calibrated_observer
from naheng.runtime.baseline_frontier import _execution_constraints
from naheng.control.execution import integrate_guarded_action, GuardedExecutionRejected
from naheng.domain.contracts import Observation
from naheng.economics.ledger import EnergyLedger
from naheng.estimation.particle_filter import ParticleFilter, particle_model
from .policy_space import map_policy, fixed_world, check_policy_action, digest
from .strategy_mpc import MPCParameters, MPCStage, plan

ROOT=Path(naheng.__file__).resolve().parents[2]
SOURCE_ID='fixed-training-full-policy-world-2026101401'
IMPLEMENTATIONS=('multifidelity.py','query_policy.py','constrained_bo.py','policy_space.py','strategy_mpc.py','operational_oracle.py','pilot.py','calibration_request.json')

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def implementation_hashes():
    return {name:sha(Path(__file__).parent/name) for name in IMPLEMENTATIONS if (Path(__file__).parent/name).is_file()}


class OperationalOracle:
    def __init__(self, output, *, packet=None, world=None):
        self.output=Path(output).resolve()
        if not self.output.is_relative_to(ROOT/'artifacts'):
            raise ValueError('Project-owned output required')
        self.output.mkdir(parents=True,exist_ok=True)
        self.packet=Path(packet or ROOT/'artifacts/calibration/frontier-test-ac037289').resolve()
        if not self.packet.is_relative_to(ROOT/'artifacts'):
            raise ValueError('Project-owned declared calibration packet required')
        self.world=fixed_world() if world is None else world
        self.identities={'code_hash':code_hash(ROOT),'packet_manifest':sha(self.packet/'manifest.json'),
            'packet_result':sha(self.packet/'result.json'),'implementations':implementation_hashes(),
            'fixed_world_sha256':digest(self.world)}

    def evaluate(self, request):
        if self.identities!={'code_hash':code_hash(ROOT),'packet_manifest':sha(self.packet/'manifest.json'),
            'packet_result':sha(self.packet/'result.json'),'implementations':implementation_hashes(),
            'fixed_world_sha256':digest(self.world)}:
            raise ValueError('Frozen source, calibration, or world changed')
        if (type(request.get('timeout_s')) not in (int,float)
            or not np.isfinite(request['timeout_s']) or not 0<request['timeout_s']<=120):
            raise ValueError('Bounded original per-query timeout required')
        if (type(request.get('ordinal')) is not int or request['ordinal']<0
            or request.get('candidate_id')!=digest(request.get('parameters'))
            or not isinstance(request.get('reservation_id'),str) or len(request['reservation_id'])!=32
            or any(c not in '0123456789abcdef' for c in request['reservation_id'])):
            raise ValueError('Exact candidate and execution reservation identity required')
        mapping=map_policy(request['parameters'],fidelity=request['fidelity'],world=self.world)
        case=self.output/(f"{request['ordinal']:03d}-"+request['fidelity'])
        case.mkdir(exist_ok=False)
        payload={'request':request,'mapping':mapping,'identities':self.identities,'packet':str(self.packet),
            'source_id':SOURCE_ID,'seed':2026101401,'inner_wall_s':max(.001,request['timeout_s']-8.)}
        atomic_json(case/'request.json',payload)
        argv=[sys.executable,'-m',__package__+'.operational_oracle','--case-worker',str(case/'request.json'),str(case)]
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',
            PYTHONPATH=os.pathsep.join([str(Path(__file__).resolve().parents[1]),str(Path(naheng.__file__).resolve().parents[1])]))
        started=time.monotonic()
        receipt=run_validation_command(argv,ROOT,case/'stdout.log',case/'stderr.log',timeout_s=request['timeout_s'],env=env)
        atomic_json(case/'command.json',receipt)
        elapsed=time.monotonic()-started
        actual=json.loads((case/'result.json').read_text(encoding='utf-8')) if (case/'result.json').is_file() else {}
        valid=(receipt['exit_code']==0 and not receipt['timed_out'] and receipt['resource_cleanup_confirmed'] is True
            and elapsed<=request['timeout_s'] and actual.get('source_hashes')==self.identities
            and actual.get('request_sha256')==sha(case/'request.json'))
        completed=valid and actual.get('complete_trace') is True
        response={'status':'completed' if completed else 'unknown',
            'utility':actual['actual_energy_cash_CNY'] if completed else None,
            'constraint_margin':actual['constraint_margin'] if completed else None,
            'cost_s':elapsed,'source_id':SOURCE_ID,'run_id':actual.get('run_id',request['reservation_id']),
            'evidence_sha256':sha(case/'result.json') if (case/'result.json').is_file() else sha(case/'command.json'),
            'reason':None if completed else actual.get('reason','Owned worker incomplete or outcome unknown')}
        atomic_json(case/'response.json',response)
        atomic_json(case/'manifest.json',{'response':response,'actual':actual,'receipt':receipt,
            'files':{p.relative_to(case).as_posix():sha(p) for p in case.rglob('*') if p.is_file()},
            'scientific_N_added':0,'physical_reference_calls':0,'risk_certificate':False})
        return response


def run_case(request_path, out):
    payload=json.loads(request_path.read_text(encoding='utf-8'));request=payload['request'];mapping=payload['mapping']
    identity=payload['identities'];started=time.monotonic()
    (out/'evaluator').mkdir(exist_ok=False)
    run_id='full-policy-'+request['reservation_id'];ledger=EnergyLedger(run_id,tariff_source=mapping['world']['tariff_source'])
    status,reason='unknown','No complete execution';rows=[];all_soc=[];plant=state=None;initial_soc=None
    completed=0;violations=[];events=[];noise_rows=[]
    try:
        if code_hash(ROOT)!=identity['code_hash'] or implementation_hashes()!=identity['implementations']:
            raise ValueError('Frozen implementation identity changed before worker')
        packet=Path(payload['packet']);loaded=_packet(ROOT,packet)
        observer,adopted=fork_calibrated_observer(ROOT,packet)
        parent=observer.export_checkpoint();observer=ParticleFilter.from_checkpoint(run_id=run_id,model=loaded['model'],payload=parent)
        atomic_json(out/'adoption.json',adopted)
        sensor_source=json.loads((ROOT/loaded['request'].training_source.path).read_text(encoding='utf-8'))
        world_seed,sensor_seed=np.random.SeedSequence(payload['seed']).spawn(2)
        noise=np.random.default_rng(sensor_seed).normal(size=(mapping['world']['execution_steps'],2))
        atomic_json(out/'fixed-noise.json',{'noise':noise.tolist(),'clock_step_s':mapping['world']['clock_step_s'],
            'same_clock_for_all_strategies':True,'source_voltage_noise_V':sensor_source['voltage_noise_V'],
            'source_temperature_noise_K':sensor_source['temperature_noise_K']})
        params=MPCParameters(**mapping['policy_mpc_parameters']);stages=[MPCStage(**s) for s in mapping['stages']]
        for index in range(mapping['world']['execution_steps']):
            if time.monotonic()-started>=payload['inner_wall_s']:
                raise TimeoutError('Bounded case deadline before next action')
            snapshot=observer.snapshot
            forecast=stages[index:index+mapping['world']['prediction_steps']]
            response=plan(snapshot,loaded['model'],loaded['package'],forecast,parameters=params,
                accept_verified_incumbent=request['fidelity']=='low')
            atomic_json(out/f'plan-{index}.json',response.to_dict())
            if response.action is None:
                reason='Planner '+response.status+': '+response.reason;break
            action=response.action
            if (action.snapshot_id!=snapshot.snapshot_id or action.start_s!=snapshot.obs_until_s
                or action.duration_s!=stages[index].duration_s):
                raise ValueError('Only the bound current first action may execute')
            check_policy_action(action,stages[index],params,all_soc)
            if plant is None:
                particle=int(np.random.default_rng(world_seed).choice(len(snapshot.samples),p=snapshot.weights))
                sample=np.asarray(snapshot.samples[particle]);plant=particle_model(loaded['model'],sample[-2],sample[-1]);state=sample[:5].copy()
                capacity=np.asarray(plant.params.site_capacity_mol);initial_soc=float(state[:2]@capacity/capacity.sum());all_soc=[initial_soc]
                atomic_json(out/'evaluator/initial.json',{'posterior_index':particle,'joint_sample':sample.tolist(),
                    'supplied_to_controller':False,'scope':'conditional synthetic posterior draw'})
            guarded=integrate_guarded_action(plant,state,action,loaded['package'],params,stages[index].ambient_K)
            actual=guarded.result;state=actual.state.copy()
            entry=ledger.append(action,execution_id=f'actual-{index}',energy_J=actual.energy_J,
                thermal_energy_J=actual.thermal_management_energy_J,buy_price_per_kWh=stages[index].buy_price_per_kWh,
                sell_price_per_kWh=stages[index].sell_price_per_kWh,duration_s=actual.elapsed_s,
                reason='Actual first policy-permitted action; no future or terminal value booked')
            checks,soc_values=_execution_constraints(actual,action,plant,params,loaded['package'],all_soc)
            all_soc.extend(soc_values);violations.extend(k for k,v in checks.items() if not v);events.extend(actual.events)
            atomic_json(out/f'evaluator/execution-{index}.json',{'action':action.model_dump(mode='json'),'guard':guarded.receipt,
                'times_s':actual.times_s.tolist(),'states':actual.states.tolist(),'voltages_V':actual.voltages_V.tolist(),
                'energy_J':actual.energy_J,'thermal_electric_energy_J':actual.thermal_management_energy_J,
                'ledger_entry':entry,'policy_mapping_sha256':digest(mapping),'trace_checks':checks})
            if violations or events or actual.elapsed_s!=action.duration_s:
                reason='Observed policy/physical stop; full requested service not complete';break
            reading=plant.observe(state,action.current_A)
            sensor=Observation(run_id=snapshot.run_id,timestamp_s=snapshot.obs_until_s+actual.elapsed_s,current_A=action.current_A,
                voltage_V=float(reading['voltage_V']+noise[index,0]*sensor_source['voltage_noise_V']),
                temperature_K=float(reading['temperature_K']+noise[index,1]*sensor_source['temperature_noise_K']))
            observer.update(sensor,duration_s=actual.elapsed_s,ambient_K=stages[index].ambient_K,thermal_W=action.thermal_W)
            atomic_json(out/f'sensor-{index}.json',sensor.model_dump(mode='json'))
            rows.append({'action':action.model_dump(mode='json'),'next_snapshot':observer.snapshot.model_dump(mode='json')})
            completed+=1
        if completed==mapping['world']['execution_steps']:status,reason='completed','Complete fixed service executed and reobserved'
    except Exception as error:
        reason=f'{type(error).__name__}: {error}'
    final_soc=float(state[:2]@np.asarray(plant.params.site_capacity_mol)/sum(plant.params.site_capacity_mol)) if state is not None else None
    complete=status=='completed'
    margin=max(initial_soc-final_soc-1e-5,1. if events or violations else -1e-12) if complete else None
    source_current=(code_hash(ROOT)==identity['code_hash'] and implementation_hashes()==identity['implementations'])
    result={'run_id':run_id,'status':status,'reason':reason,'complete_trace':complete and source_current,
        'completed_sensor_replans':completed,'source_hashes':identity,'source_unchanged':source_current,
        'request_sha256':sha(request_path),'mapping':mapping,'rows':rows,
        'initial_actual_soc':initial_soc,'terminal_actual_soc':final_soc,'constraint_margin':margin,
        'actual_energy_cash_CNY':ledger.summary()['net_cashflow'],'violations':violations,'native_events':events,
        'scope':'conditional synthetic calculation; unknown/refusal outcomes are unlabelled, no physical safety inference',
        'risk_certificate':False,'scientific_N_added':0,'physical_reference_calls':0,'elapsed_s':time.monotonic()-started}
    atomic_json(out/'ledger.json',{'entries':ledger.entries,'summary':ledger.summary(),'forecast_energy_booked':False,'terminal_value_booked':False})
    atomic_json(out/'result.json',result)
    return 0 if source_current else 2


if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='--case-worker':raise SystemExit('Fixed owned worker entry only')
    raise SystemExit(run_case(Path(sys.argv[2]),Path(sys.argv[3])))
