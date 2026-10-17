"""Registered conditional synthetic tuning, freezing and paired execution.

Selection reads training executions only. Evaluation cannot select a policy.
Cash is actual energy cash, without terminal/lifecycle settlement or risk proof.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import html
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

from naheng.control.mpc import MPCParameters, MPCStage
from naheng.control.execution import integrate_guarded_action, GuardedExecutionRejected
from naheng.control.scenario_mpc import plan as scenario_plan
from naheng.domain.contracts import Observation
from naheng.economics.ledger import EnergyLedger
from naheng.estimation.particle_filter import ParticleFilter, particle_model
from naheng.formal.checker import run_command
from .artifacts import atomic_json, code_hash, sha256_file
from .calibration_consumer import _packet
from .calibration_observer import fork_calibrated_observer
from .execution_receipts import stop_status


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _controlled(root, path):
    path = Path(path)
    if any(part.casefold() == 'evaluator' for part in path.parts):
        raise ValueError('Public inputs cannot enter evaluator')
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root) or any(part.casefold() == 'evaluator' for part in resolved.parts):
        raise ValueError('Public path must stay inside project outside evaluator')
    return resolved


def parse_protocol(value):
    from naheng.control.fixed_baseline import FixedBaselinePolicy
    required = {'schema_version', 'protocol_id', 'candidates', 'training_seeds', 'evaluation_seeds',
                'execution_steps', 'prediction_steps', 'stages', 'parameters', 'terminal_soc_tolerance',
                'case_timeout_s', 'batch_wall_budget_s'}
    if not isinstance(value, dict) or set(value) != required or value['schema_version'] != 1:
        raise ValueError('Exact version-one frontier protocol fields required')
    if (not isinstance(value['protocol_id'], str) or not 1 <= len(value['protocol_id']) <= 80
            or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in value['protocol_id'])):
        raise ValueError('Explicit bounded protocol ID required')
    for key in ('training_seeds', 'evaluation_seeds'):
        seeds = value[key]
        if (not isinstance(seeds, list) or not 1 <= len(seeds) <= 4
                or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds) or len(set(seeds)) != len(seeds)):
            raise ValueError('Each phase needs 1..4 distinct integer seeds')
    if set(value['training_seeds']) & set(value['evaluation_seeds']):
        raise ValueError('Training and evaluation seeds must be disjoint')
    for key in ('execution_steps', 'prediction_steps'):
        if type(value[key]) is not int or not 2 <= value[key] <= 4:
            raise ValueError('Bounded 2..4 execution and prediction steps required')
    for key, lo, hi in (('terminal_soc_tolerance', 0, .001), ('case_timeout_s', 5, 120), ('batch_wall_budget_s', 10, 1800)):
        number = value[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not lo <= number <= hi:
            raise ValueError('Invalid bounded ' + key)
    if not isinstance(value['parameters'], dict):
        raise ValueError('Explicit common MPCParameters required')
    def no_boolean_numbers(v):
        if isinstance(v, bool):
            raise ValueError('Boolean is not a numeric physical parameter')
        if isinstance(v, dict):
            for element in v.values(): no_boolean_numbers(element)
        elif isinstance(v, (list, tuple)):
            for element in v: no_boolean_numbers(element)
    no_boolean_numbers(value['parameters'])
    try:
        parameters = MPCParameters(**value['parameters'])
        stages = [MPCStage(**v) for v in value['stages']]
        policies = [FixedBaselinePolicy(**v) for v in value['candidates']]
    except (TypeError, KeyError) as error:
        raise ValueError('Invalid protocol parameter fields') from error
    if (not 2 <= len(policies) <= 12 or len({v.policy_id for v in policies}) != len(policies)
            or any(v.policy_id == 'scenario-comparator' for v in policies)):
        raise ValueError('2..12 uniquely identified baseline candidates required')
    if any(not 1 <= len(v.policy_id) <= 80 or v.policy_id.casefold() == 'evaluator'
           or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in v.policy_id) for v in policies):
        raise ValueError('Safe bounded policy IDs without directory/private components required')
    shapes = [{k: v for k, v in asdict(p).items() if k != 'policy_id'} for p in policies]
    if len({_hash(v) for v in shapes}) != len(shapes):
        raise ValueError('Candidate parameter vectors must actually differ')
    if len(stages) != value['execution_steps'] + value['prediction_steps'] - 1 or any(v.duration_s > 60 for v in stages):
        raise ValueError('Explicit executed and future tariff stages, <=60 seconds each, required')
    if parameters.wall_budget_s >= value['case_timeout_s']:
        raise ValueError('Planner budget must leave case time for execution and sensors')
    # Model-dependent intersections are checked again by each actual policy.
    return {'schema_version': 1, 'protocol_id': value['protocol_id'], 'candidates': [asdict(v) for v in policies],
            'training_seeds': list(value['training_seeds']), 'evaluation_seeds': list(value['evaluation_seeds']),
            'execution_steps': value['execution_steps'], 'prediction_steps': value['prediction_steps'],
            'stages': [asdict(v) for v in stages], 'parameters': asdict(parameters),
            'terminal_soc_tolerance': float(value['terminal_soc_tolerance']),
            'case_timeout_s': float(value['case_timeout_s']), 'batch_wall_budget_s': float(value['batch_wall_budget_s'])}


def select_training_frontier(points):
    """Exact Pareto relation: minimize conservative events/refusals, maximize cash."""
    if any(v.get('phase') != 'training' for v in points):
        raise ValueError('Selection cannot read evaluation results')
    valid = [v for v in points if v['eligible_for_training_selection']]
    ids = []
    for a in valid:
        def dominates(b):
            weak = (b['conservative_event_fraction'] <= a['conservative_event_fraction']
                    and b['refused_or_failed_fraction'] <= a['refused_or_failed_fraction']
                    and b['mean_actual_energy_cash_CNY'] >= a['mean_actual_energy_cash_CNY'])
            strict = (b['conservative_event_fraction'] < a['conservative_event_fraction']
                      or b['refused_or_failed_fraction'] < a['refused_or_failed_fraction']
                      or b['mean_actual_energy_cash_CNY'] > a['mean_actual_energy_cash_CNY'])
            return a.get('policy_kind') == b.get('policy_kind') and weak and strict
        if not any(dominates(b) for b in valid):
            ids.append(a['policy_id'])
    return sorted(ids)


def aggregate_cases(phase, policy_id, cases):
    if not cases:
        raise ValueError('All preregistered cases, including failures, are required')
    if any(v['phase'] != phase or v['policy_id'] != policy_id for v in cases):
        raise ValueError('Case identity or phase mismatch')
    if len({v.get('policy_kind') for v in cases}) != 1:
        raise ValueError('A fixed policy cannot change its algorithm family')
    n = len(cases)
    complete = [v for v in cases if v.get('complete_trace')]
    events = sum(bool(v.get('trajectory_event')) for v in cases)
    unknown = sum(not v.get('complete_trace') for v in cases)
    terminal = sum(v.get('terminal_pass') is True for v in cases)
    cash = [v.get('actual_energy_cash_CNY', 0.) for v in cases]
    if not all(type(x) in (int, float) and math.isfinite(x) for x in cash):
        raise ValueError('Actual finite ledger cash required')
    return {'phase': phase, 'policy_id': policy_id, 'policy_kind': cases[0].get('policy_kind'),
            'registered_cases': n, 'complete_cases': len(complete),
            'observed_event_cases': events, 'unknown_or_incomplete_cases': unknown,
            'conservative_event_fraction': (events + sum(not v.get('complete_trace') and not v.get('trajectory_event') for v in cases)) / n,
            'refused_or_failed_fraction': unknown / n, 'terminal_pass_cases': terminal,
            'eligible_for_training_selection': phase == 'training' and len(complete) == terminal == n,
            'mean_actual_energy_cash_CNY': sum(cash) / n, 'sum_actual_energy_cash_CNY': sum(cash),
            'executed_seconds': sum(v.get('executed_seconds', 0.) for v in cases),
            'unserved_seconds': sum(v.get('unserved_seconds', 0.) for v in cases),
            'end_soc_deltas': [v.get('terminal_soc_delta') for v in cases],
            'whole_trajectory_event_fraction': events / n if len(complete) == n else None,
            'risk_certificate': False, 'cash_scope': 'raw_executed_energy_cash_without_terminal_or_lifecycle_settlement',
            'operational_probability': None, 'scientific_profit_comparability': False}


def _execution_constraints(actual, action, plant, parameters, package, accumulated_soc):
    capacity = np.asarray(plant.params.site_capacity_mol)
    soc = actual.states[:, :2] @ capacity / capacity.sum()
    temperature = actual.states[:, 4]
    registered = package['parameters']
    low_t = max(plant.params.temperature_min_K, registered['temperature_min_K'], package['domain']['temperature_K'][0],
                parameters.temperature_min_K if parameters.temperature_min_K is not None else plant.params.temperature_min_K)
    high_t = min(plant.params.temperature_max_K, registered['temperature_max_K'], package['domain']['temperature_K'][1],
                 parameters.temperature_max_K if parameters.temperature_max_K is not None else plant.params.temperature_max_K)
    # Planning reserves have no operational-event meaning. Only explicit common
    # limits intersect the registered/model/package bounds, as the guard does.
    low_v = max(plant.params.voltage_min_V, registered['voltage_min_V'],
                parameters.voltage_min_V if parameters.voltage_min_V is not None else plant.params.voltage_min_V)
    high_v = min(plant.params.voltage_max_V, registered['voltage_max_V'],
                 parameters.voltage_max_V if parameters.voltage_max_V is not None else plant.params.voltage_max_V)
    if 'voltage_V' in package['domain']:
        low_v = max(low_v, package['domain']['voltage_V'][0])
        high_v = min(high_v, package['domain']['voltage_V'][1])
    band_ok = True
    for x in soc:
        lower, limits = 0., []
        for upper, charge, discharge in parameters.soc_bands:
            if lower - 1e-12 <= x <= upper + 1e-12:
                limits.append(charge if action.current_A < 0 else discharge)
            lower = upper
        band_ok &= bool(limits) and abs(action.current_A) <= min(parameters.current_limit_A, *limits) + 1e-8
    all_soc = [*accumulated_soc, *soc.tolist()]
    checks = {'SOC': bool(soc.min() >= parameters.soc_min - 1e-8 and soc.max() <= parameters.soc_max + 1e-8),
              'temperature': bool(temperature.min() >= low_t - 1e-8 and temperature.max() <= high_t + 1e-8),
              'voltage': bool(actual.voltages_V.min() >= low_v - 1e-8 and actual.voltages_V.max() <= high_v + 1e-8),
              'current_and_SOC_bands': bool(band_ok), 'DoD': max(all_soc) - min(all_soc) <= parameters.max_dod + 1e-8,
              'thermal_action': parameters.thermal_min_W <= action.thermal_W <= parameters.thermal_max_W}
    return checks, soc.tolist()


def _case_worker(root, packet, case_file, out):
    from naheng.control.fixed_baseline import FixedBaselinePolicy, propose
    started, digest = time.monotonic(), code_hash(root)
    case = json.loads(case_file.read_text(encoding='utf-8'))
    protocol = parse_protocol(case['protocol'])
    parameters = MPCParameters(**protocol['parameters'])
    case_id = 'frontier-' + _hash({k: case[k] for k in ('registration_sha256', 'phase', 'policy_id', 'seed')})[:24]
    ledger = EnergyLedger(case_id, tariff_source=parameters.tariff_source)
    rows, events, violations, all_soc = [], [], [], []
    plant = state = initial_soc = None
    actual_count, observer_count, completed = 0, 0, 0
    protected = {}
    reason, status, code = None, 'unknown', 2
    target_seconds = sum(v['duration_s'] for v in protocol['stages'][:protocol['execution_steps']])
    result = {'phase': case['phase'], 'policy_id': case['policy_id'], 'seed': case['seed'], 'complete_trace': False}
    try:
        loaded = _packet(root, packet)
        protected = loaded['hashes']
        observer, adopted = fork_calibrated_observer(root, packet)
        parent_snapshot = observer.snapshot
        parent_checkpoint = observer.export_checkpoint()
        observer = ParticleFilter.from_checkpoint(run_id=case_id, model=loaded['model'], payload=parent_checkpoint)
        fork_checkpoint = observer.export_checkpoint()
        parent_joint_hash = _hash({'samples': parent_checkpoint['samples'], 'weights': parent_checkpoint['weights']})
        fork_joint_hash = _hash({'samples': fork_checkpoint['samples'], 'weights': fork_checkpoint['weights']})
        if (parent_joint_hash != fork_joint_hash or parent_checkpoint['rng_state'] != fork_checkpoint['rng_state']
                or observer.snapshot.obs_until_s != parent_snapshot.obs_until_s):
            raise ValueError('New case identity changed the initial posterior, time or RNG')
        adopted.update(case_run_id=case_id, source_calibration_run_id=loaded['snapshot'].run_id,
            parent_observer_snapshot_id=parent_snapshot.snapshot_id,
            parent_observer_snapshot_content_sha256=adopted['observer_snapshot_content_sha256'],
            observer_snapshot_id=observer.snapshot.snapshot_id,
            observer_snapshot_content_sha256=_hash(observer.snapshot.model_dump(mode='json')),
            parent_joint_samples_weights_sha256=parent_joint_hash, fork_joint_samples_weights_sha256=fork_joint_hash,
            parent_rng_sha256=_hash(parent_checkpoint['rng_state']), fork_rng_sha256=_hash(fork_checkpoint['rng_state']),
            identity_fork_without_new_assimilation=True)
        atomic_json(out / 'adoption.json', adopted)
        sensor_source = json.loads((root / loaded['request'].training_source.path).read_text(encoding='utf-8'))
        world_seed, sensor_seed = np.random.SeedSequence(case['seed']).spawn(2)
        noise = np.random.default_rng(sensor_seed).normal(size=(protocol['execution_steps'], 2))
        atomic_json(out / 'evaluator/noise.json', {'time_indexed_standard_normal': noise.tolist(),
            'source_voltage_noise_V': sensor_source['voltage_noise_V'], 'source_temperature_noise_K': sensor_source['temperature_noise_K']})
        policy = FixedBaselinePolicy(**case['policy']) if case['policy'] is not None else None
        for index in range(protocol['execution_steps']):
            if (time.monotonic() - started >= protocol['case_timeout_s'] - 5 or code_hash(root) != digest
                    or any(sha256_file(path) != sha for path, sha in protected.items())):
                raise TimeoutError('Case wall budget or source identity changed')
            snapshot = observer.snapshot
            stages = [MPCStage(**v) for v in protocol['stages'][index:index + protocol['prediction_steps']]]
            response = (scenario_plan(snapshot, loaded['model'], loaded['package'], stages, parameters=parameters)
                        if policy is None else propose(snapshot, loaded['model'], loaded['package'], stages,
                                                       policy=policy, parameters=parameters))
            atomic_json(out / f'plan-{index}.json', response.to_dict())
            if any(sha256_file(path) != sha for path, sha in protected.items()):
                raise ValueError('Calibration/physical data changed before action execution')
            if response.action is None:
                reason, status, code = response.reason, 'refused_' + response.status, 0
                break
            action = response.action
            if action.snapshot_id != snapshot.snapshot_id or action.start_s != snapshot.obs_until_s or action.duration_s != stages[0].duration_s:
                raise ValueError('Only the actual current first action may execute')
            if plant is None:
                posterior_index = int(np.random.default_rng(world_seed).choice(len(snapshot.samples), p=snapshot.weights))
                sample = np.asarray(snapshot.samples[posterior_index])
                plant = particle_model(loaded['model'], sample[-2], sample[-1])
                state = sample[:5].copy()
                capacity = np.asarray(plant.params.site_capacity_mol)
                initial_soc = float(state[:2] @ capacity / capacity.sum())
                all_soc = [initial_soc]
                atomic_json(out / 'evaluator/initial.json', {'posterior_index': posterior_index, 'joint_sample': sample.tolist(),
                    'after_first_policy_proposal': True, 'supplied_to_controller': False,
                    'scope': 'Conditional synthetic posterior draw, not an independent real cell'})
            try:
                guarded = integrate_guarded_action(plant, state, action, loaded['package'], parameters, stages[0].ambient_K)
            except GuardedExecutionRejected as error:
                atomic_json(out / f'evaluator/refusal-{index}.json', error.receipt)
                reason, status, code = str(error), 'refused_execution_constraints', 0
                break
            actual = guarded.result
            actual_count += 1
            state = actual.state.copy()
            entry = ledger.append(action, execution_id=f'actual-{index}', energy_J=actual.energy_J,
                thermal_energy_J=actual.thermal_management_energy_J, buy_price_per_kWh=stages[0].buy_price_per_kWh,
                sell_price_per_kWh=stages[0].sell_price_per_kWh, duration_s=actual.elapsed_s,
                reason='Actual first action; future planned energy never booked')
            atomic_json(out / 'ledger.json', {'entries': ledger.entries, 'summary': ledger.summary(),
                'forecast_energy_booked': False, 'terminal_value_booked': False})
            atomic_json(out / f'evaluator/guard-{index}.json', guarded.receipt)
            row = {'input_snapshot_id': snapshot.snapshot_id, 'action': action.model_dump(mode='json'),
                   'ledger_entry': entry, 'next_snapshot_id': None, 'sensor_timestamp_s': None,
                   'observer_updated': False, 'future_planned_actions_executed': 0}
            rows.append(row)
            atomic_json(out / 'steps.json', rows)
            atomic_json(out / f'evaluator/execution-{index}.json', {'elapsed_s': actual.elapsed_s,
                'energy_J': actual.energy_J, 'thermal_management_energy_J': actual.thermal_management_energy_J,
                'times_s': actual.times_s.tolist(), 'states': actual.states.tolist(), 'voltages_V': actual.voltages_V.tolist(),
                'solver': actual.solver, 'events': actual.events, 'inventory_residual_mol': actual.inventory_residual_mol,
                'event_scopes': guarded.receipt['native_events_with_scope']})
            checks, soc_values = _execution_constraints(actual, action, plant, parameters, loaded['package'], all_soc)
            all_soc.extend(soc_values)
            violations.extend(name for name, passed in checks.items() if not passed)
            events.extend(actual.events)
            atomic_json(out / 'evaluator/event-progress.json', {'events': events, 'violations': violations})
            stopping = stop_status(guarded.receipt, actual, action.duration_s, checks)
            if stopping:
                reason, status, code = 'Actual execution stopped: ' + stopping, stopping, 0
                row['status'] = stopping
                break
            reading = plant.observe(state, action.current_A)
            sensor = Observation(run_id=snapshot.run_id, timestamp_s=snapshot.obs_until_s + actual.elapsed_s,
                current_A=action.current_A, voltage_V=float(reading['voltage_V'] + noise[index, 0] * sensor_source['voltage_noise_V']),
                temperature_K=float(reading['temperature_K'] + noise[index, 1] * sensor_source['temperature_noise_K']))
            atomic_json(out / f'sensor-{index}.json', sensor.model_dump(mode='json'))
            next_snapshot = observer.update(sensor, duration_s=actual.elapsed_s, ambient_K=stages[0].ambient_K, thermal_W=action.thermal_W)
            observer_count += 1
            completed += 1
            row.update(next_snapshot_id=next_snapshot.snapshot_id, sensor_timestamp_s=sensor.timestamp_s,
                       observer_updated=True, observer_diagnostics=observer.update_diagnostics[-1])
            atomic_json(out / f'posterior-{index}.json', next_snapshot.model_dump(mode='json'))
            atomic_json(out / 'steps.json', rows)
        if completed == protocol['execution_steps']:
            status, code = 'completed', 0
    except Exception as error:
        import traceback
        traceback.print_exc()
        reason, code = str(error), 2 if isinstance(error, (OSError, TimeoutError)) else 1
    finally:
        summary = ledger.summary()
        atomic_json(out / 'ledger.json', {'entries': ledger.entries, 'summary': summary,
            'forecast_energy_booked': False, 'terminal_value_booked': False})
        end_soc = float(state[:2] @ np.asarray(plant.params.site_capacity_mol) / sum(plant.params.site_capacity_mol)) if state is not None else None
        terminal_pass = end_soc + protocol['terminal_soc_tolerance'] >= initial_soc if end_soc is not None else None
        executed = sum(v['duration_s'] for v in ledger.entries)
        result.update(exit_code=code, status=status, reason=reason, code_hash=digest, run_id=case_id,
            same_current_source=code_hash(root) == digest, complete_trace=completed == protocol['execution_steps'] and code == 0,
            completed_sensor_replans=completed, steps=rows, trajectory_event=bool(events or violations),
            native_events=events, common_constraint_violations=sorted(set(violations)),
            actual_energy_cash_CNY=summary['net_cashflow'], executed_seconds=executed,
            unserved_seconds=max(0., target_seconds-executed), initial_actual_soc=initial_soc, terminal_actual_soc=end_soc,
            terminal_soc_delta=end_soc-initial_soc if end_soc is not None else None, terminal_pass=terminal_pass,
            terminal_tolerance=protocol['terminal_soc_tolerance'], actual_plant_integrations=actual_count,
            actual_observer_updates=observer_count, risk_certificate=False, operational_probability=None,
            scientific_profit_comparability=False, independent_operational_trajectories=0,
            wall_s=time.monotonic()-started, scope='Conditional synthetic trajectory; cash without terminal/lifecycle settlement')
        if not result['same_current_source'] or any(sha256_file(path) != sha for path, sha in protected.items()):
            result['exit_code'], result['complete_trace'] = 2, False
        atomic_json(out / 'result.json', result)
    return result['exit_code']


def _run_case(root, packet, out, registration, protocol, phase, policy, seed, timeout):
    out.mkdir(parents=True, exist_ok=False)
    policy_id = policy['policy_id'] if policy else 'scenario-comparator'
    case = {'phase': phase, 'policy_id': policy_id, 'policy': policy, 'seed': seed, 'protocol': protocol,
            'registration_sha256': registration}
    atomic_json(out / 'case.json', case)
    case_sha = sha256_file(out / 'case.json')
    argv = [sys.executable, '-m', 'naheng.runtime.baseline_frontier', '--case-worker', str(root), str(packet), str(out/'case.json'), str(out)]
    atomic_json(out / 'started.json', {'argv': argv, 'timeout_s': timeout, 'code_hash': code_hash(root)})
    receipt = run_command(argv, root, out / 'worker.log', timeout=timeout)
    atomic_json(out / 'worker-command.json', {k:v for k,v in receipt.items() if k not in ('stdout', 'stderr')})
    valid = not receipt['timed_out'] and (out/'result.json').is_file()
    result = json.loads((out/'result.json').read_text(encoding='utf-8')) if valid else {}
    valid &= (sha256_file(out/'case.json') == case_sha
              and result.get('exit_code') == receipt['exit_code'] and result.get('code_hash') == code_hash(root)
              and result.get('phase') == phase and result.get('policy_id') == policy_id and result.get('seed') == seed)
    if not valid:
        ledger = json.loads((out/'ledger.json').read_text(encoding='utf-8')) if (out/'ledger.json').is_file() else None
        executed = sum(v['duration_s'] for v in ledger['entries']) if ledger else 0.
        progress = json.loads((out/'evaluator/event-progress.json').read_text(encoding='utf-8')) if (out/'evaluator/event-progress.json').is_file() else {}
        result = {'phase': phase, 'policy_id': policy_id, 'seed': seed, 'exit_code': 2, 'status': 'unknown_owned_worker_incomplete',
            'complete_trace': False, 'terminal_pass': None, 'actual_energy_cash_CNY': ledger['summary']['net_cashflow'] if ledger else 0.,
            'trajectory_event': bool(progress.get('events') or progress.get('violations')),
            'executed_seconds': executed, 'unserved_seconds': sum(v['duration_s'] for v in protocol['stages'][:protocol['execution_steps']])-executed}
    result['artifact_dir'] = out.relative_to(root).as_posix()
    result['case_worker_started'] = True
    result['policy_kind'] = policy['kind'] if policy else 'scenario'
    atomic_json(out/'manifest.json', {'receipt_exit_code': receipt['exit_code'], 'receipt_timed_out': receipt['timed_out'],
        'complete_worker_receipt': valid, 'result': result,
        'files': {v.relative_to(out).as_posix(): sha256_file(v) for v in sorted(out.rglob('*')) if v.is_file()}})
    return result


def _report(out, result):
    points = result['training_points'] + result['evaluation_points']
    columns = ['phase', 'policy_id', 'registered_cases', 'complete_cases', 'mean_actual_energy_cash_CNY',
               'conservative_event_fraction', 'refused_or_failed_fraction', 'terminal_pass_cases', 'unserved_seconds']
    with (out/'points.csv').open('w', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, columns, extrasaction='ignore'); writer.writeheader(); writer.writerows(points)
    cells = ''.join('<tr>'+''.join('<td>'+html.escape(str(v[c]))+'</td>' for c in columns)+'</tr>' for v in points)
    markup = '<!doctype html><meta charset="utf-8"><title>钠衡：固定基线扫描与冻结评估</title>'
    markup += '<h1>条件合成实验：训练选择与冻结配对评估</h1><p>现金仅来自实际执行电能；风险是整轨迹模型事件及未完成的保守频数，无现实风险证书。期末SOC为共同约束，尚无终端/生命周期货币结算；不宣称收益优势。</p>'
    markup += '<p>仅训练阶段选出的前沿：'+html.escape(', '.join(result['frozen_frontier_policy_ids']) or '无合格基线')+'</p>'
    markup += '<table border="1"><thead><tr>'+''.join('<th>'+c+'</th>' for c in columns)+'</tr></thead><tbody>'+cells+'</tbody></table>'
    markup += '<p>完整原始产物：<a href="result.json">结果</a> · <a href="registration.json">预登记</a> · <a href="freeze.json">训练冻结</a> · <a href="points.csv">所有数值</a></p>'
    (out/'report.html').write_text(markup, encoding='utf-8')


def run_frontier(root, calibration_dir, input_path, output_path):
    root = Path(root).resolve()
    packet, source, out = [_controlled(root, v) for v in (calibration_dir, input_path, output_path)]
    if (not out.is_relative_to(root/'artifacts') or out == root/'artifacts' or out.is_relative_to(packet)
            or packet.is_relative_to(out) or source.is_relative_to(out) or source.stat().st_size > 1024*1024):
        raise ValueError('Fresh controlled output, disjoint calibration and bounded protocol required')
    protocol = parse_protocol(json.loads(source.read_text(encoding='utf-8')))
    out.mkdir(parents=True, exist_ok=False)
    digest, started = code_hash(root), time.monotonic()
    cases, training, evaluation = [], [], []
    freeze_ids, errors = [], []
    registered = {'utc': datetime.now(timezone.utc).isoformat(), 'protocol': protocol, 'protocol_content_sha256': _hash(protocol),
        'input_sha256': sha256_file(source), 'code_hash': digest, 'calibration_dir': str(packet.relative_to(root)),
        'calibration_manifest_sha256': sha256_file(packet/'manifest.json'), 'calibration_result_sha256': sha256_file(packet/'result.json'),
        'selection_rule': 'Training only Pareto within each registered baseline algorithm family: maximize actual energy cash, minimize conservative trajectory event and failure/refusal fractions; all cases complete and terminal guard required',
        'terminal_rule': 'Each actual trajectory own initial SOC, tolerance in dimensionless SOC; no terminal value booked',
        'evaluation_rule': 'Frozen training-frontier policies and preregistered fixed scenario comparator; no evaluation selection',
        'randomness': 'Separate seed streams: conditional world and time-indexed sensor shocks; same seed across policies is one paired scenario',
        'risk_certificate': False, 'independent_operational_trajectories': 0, 'full_C01_complete': False}
    atomic_json(out/'registration.json', registered)
    registration = sha256_file(out/'registration.json')
    freeze_sha = None

    def run(phase, policy, seed):
        remaining = protocol['batch_wall_budget_s'] - (time.monotonic()-started)
        policy_id = policy['policy_id'] if policy else 'scenario-comparator'
        identity = (code_hash(root) == digest and sha256_file(source) == registered['input_sha256']
                    and sha256_file(out/'registration.json') == registration)
        if not identity or remaining < 5:
            reason = 'Source/protocol/registration changed after registration' if not identity else 'Registered local batch budget exhausted'
            if not any(v.get('reason') == reason for v in errors):
                errors.append({'type': 'RegisteredCaseNotStarted', 'reason': reason})
            result = {'phase': phase, 'policy_id': policy_id, 'seed': seed, 'exit_code': 2,
                'status': 'registered_not_started', 'reason': reason, 'case_worker_started': False,
                'policy_kind': policy['kind'] if policy else 'scenario',
                'complete_trace': False, 'terminal_pass': None, 'actual_energy_cash_CNY': 0.,
                'trajectory_event': False, 'executed_seconds': 0.,
                'unserved_seconds': sum(v['duration_s'] for v in protocol['stages'][:protocol['execution_steps']]),
                'receipt': None, 'scope': 'Registered but never executed; no worker receipt fabricated'}
        else:
            result = _run_case(root, packet, out/'cases'/phase/policy_id/str(seed), registration, protocol, phase, policy, seed,
                               min(protocol['case_timeout_s'], remaining))
        cases.append(result)
        atomic_json(out/'progress.json', {'registered_total_training_cases': len(protocol['candidates'])*len(protocol['training_seeds']),
            'started_case_workers': sum(v['case_worker_started'] for v in cases), 'registered_cases_accounted': len(cases),
            'cases': cases, 'code_hash': digest})
        return result

    try:
        for policy in protocol['candidates']:
            rows = [run('training', policy, seed) for seed in protocol['training_seeds']]
            training.append(aggregate_cases('training', policy['policy_id'], rows))
        freeze_ids = select_training_frontier(training)
        frozen = {'registration_sha256': registration, 'code_hash': digest, 'selected_policy_ids': freeze_ids,
            'selected_policies': [v for v in protocol['candidates'] if v['policy_id'] in freeze_ids],
            'training_points': training, 'training_case_manifests': {v['artifact_dir']+'/manifest.json': sha256_file(root/v['artifact_dir']/'manifest.json') for v in cases if v['case_worker_started']},
            'evaluation_results_seen': False, 'full_C01_complete': False}
        atomic_json(out/'freeze.json', frozen)
        freeze_sha = sha256_file(out/'freeze.json')
        for policy in [*frozen['selected_policies'], None]:
            policy_id = policy['policy_id'] if policy else 'scenario-comparator'
            rows = [run('evaluation', policy, seed) for seed in protocol['evaluation_seeds']]
            if sha256_file(out/'freeze.json') != freeze_sha:
                raise ValueError('Frozen policies changed during evaluation')
            evaluation.append(aggregate_cases('evaluation', policy_id, rows))
    except Exception as error:
        errors.append({'type': type(error).__name__, 'reason': str(error)})
    final_identity = (code_hash(root) == digest and sha256_file(source) == registered['input_sha256']
        and sha256_file(packet/'manifest.json') == registered['calibration_manifest_sha256']
        and sha256_file(packet/'result.json') == registered['calibration_result_sha256']
        and sha256_file(out/'registration.json') == registration
        and freeze_sha is not None and sha256_file(out/'freeze.json') == freeze_sha)
    if not final_identity:
        errors.append({'type': 'IdentityChangedOrIncomplete', 'reason': 'Final source/protocol/calibration/registration/freeze binding failed'})
    complete = not errors and len(training) == len(protocol['candidates']) and len(evaluation) == len(freeze_ids)+1
    receipt_failures = [v for v in cases if v['exit_code'] != 0]
    result = {'exit_code': 0 if complete and freeze_ids and not receipt_failures else 2, 'workflow_complete': complete,
        'code_hash': digest, 'protocol_id': protocol['protocol_id'], 'training_points': training, 'evaluation_points': evaluation,
        'frozen_frontier_policy_ids': freeze_ids, 'cases': cases, 'errors': errors, 'receipt_failures': len(receipt_failures),
        'registered_training_seeds': protocol['training_seeds'], 'registered_evaluation_seeds': protocol['evaluation_seeds'],
        'case_workers': sum(v['case_worker_started'] for v in cases), 'registered_cases_accounted': len(cases),
        'unique_training_paired_scenarios': len(protocol['training_seeds']),
        'unique_evaluation_paired_scenarios': len(protocol['evaluation_seeds']), 'independent_operational_trajectories': 0,
        'scientific_profit_comparability': False, 'risk_certificate': False, 'full_C01_complete': False,
        'scope': 'Bounded conditional synthetic baseline tuning and frozen evaluation; full action/lifecycle/statistical/UI gates remain',
        'wall_s': time.monotonic()-started}
    atomic_json(out/'result.json', result)
    _report(out, result)
    atomic_json(out/'manifest.json', {'exit_code': result['exit_code'], 'code_hash': digest,
        'same_source_at_finish': code_hash(root) == digest, 'final_all_identity_bindings': final_identity, 'full_C01_complete': False,
        'files': {v.relative_to(out).as_posix(): sha256_file(v) for v in sorted(out.rglob('*')) if v.is_file()}})
    return {'exit_code': result['exit_code'], 'artifact_dir': str(out), 'workflow_complete': complete,
            'training_candidates': len(training), 'evaluation_policies': len(evaluation), 'full_C01_complete': False}


if __name__ == '__main__':
    if len(sys.argv) != 6 or sys.argv[1] != '--case-worker':
        raise SystemExit('Owned case worker arguments required')
    raise SystemExit(_case_worker(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5])))
