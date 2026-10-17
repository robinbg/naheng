"""Bounded explicit synthetic scenario planning with real sensor replanning."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
import numpy as np

from naheng.control.mpc import MPCParameters, MPCStage
from naheng.control.execution import integrate_guarded_action, GuardedExecutionRejected
from naheng.control.scenario_mpc import plan
from naheng.domain.contracts import Observation
from naheng.economics.ledger import EnergyLedger
from naheng.estimation.particle_filter import particle_model
from naheng.formal.checker import run_command
from .artifacts import atomic_json, code_hash, sha256_file
from .calibration_consumer import _packet
from .calibration_observer import fork_calibrated_observer
from .baseline_frontier import _execution_constraints
from .execution_receipts import stop_status


def _worker(root, packet, out):
    started, initial_hash = time.monotonic(), code_hash(root)
    completed, rows = 0, []
    try:
        loaded = _packet(root, packet)
        observer, adopted = fork_calibrated_observer(root, packet)
        atomic_json(out / 'adoption.json', adopted)
        source = json.loads((root / loaded['request'].training_source.path).read_text(encoding='utf-8'))
        parameters = MPCParameters(current_limit_A=.02, thermal_min_W=0, thermal_max_W=0,
            nominal_terminal_buffer=0, prediction_max_step_s=5, max_iterations=25,
            max_candidate_evaluations=120, wall_budget_s=15, tariff_source='declared_synthetic_two_stage_prices')
        ledger = EnergyLedger('scenario-' + out.name, tariff_source=parameters.tariff_source)
        sensor_rng = np.random.default_rng(20261104)
        plant, state, all_soc = None, None, []
        atomic_json(out / 'source.json', {'calibration_dir': str(packet), 'code_hash': initial_hash,
            'source_snapshot_id': loaded['snapshot'].snapshot_id, 'parameters': asdict(parameters),
            'independent_operational_trajectories': 0, 'saved_Run_or_old_PF_modified': False})
        for iteration in range(2):
            if time.monotonic() - started >= 105 or code_hash(root) != initial_hash:
                raise TimeoutError('Scenario loop total budget or source identity changed')
            snapshot = observer.snapshot
            stages = ([MPCStage(5, .05, .04, 299.15), MPCStage(5, .15, .40, 299.15)] if iteration == 0
                      else [MPCStage(5, .15, .40, 299.15), MPCStage(5, .05, .04, 299.15)])
            response = plan(snapshot, loaded['model'], loaded['package'], stages, parameters=parameters)
            atomic_json(out / f'plan-{iteration}.json', response.to_dict())
            if response.status != 'feasible' or response.action is None:
                break
            action = response.action  # Every future planned action is discarded.
            if plant is None:
                index = int(np.random.default_rng(20261103).choice(len(snapshot.samples), p=snapshot.weights))
                row = np.asarray(snapshot.samples[index])
                plant = particle_model(loaded['model'], row[-2], row[-1])
                state = row[:5].copy()
                all_soc = [float(state[:2] @ np.asarray(plant.params.site_capacity_mol) / sum(plant.params.site_capacity_mol))]
                atomic_json(out / 'evaluator/initial.json', {'posterior_index': index, 'joint_sample': row.tolist(),
                    'private_draw_after_first_plan': True, 'supplied_to_controller': False,
                    'scope': 'Synthetic conditional posterior draw; no real-cell truth'})
            try:
                guarded = integrate_guarded_action(plant, state, action, loaded['package'], parameters, stages[0].ambient_K)
            except GuardedExecutionRejected as error:
                atomic_json(out / f'evaluator/refusal-{iteration}.json', error.receipt)
                break
            actual = guarded.result
            state = actual.state.copy()
            entry = ledger.append(action, execution_id=f'executed-{iteration}', energy_J=actual.energy_J,
                thermal_energy_J=actual.thermal_management_energy_J, buy_price_per_kWh=stages[0].buy_price_per_kWh,
                sell_price_per_kWh=stages[0].sell_price_per_kWh, executed=True, duration_s=actual.elapsed_s,
                reason='Only first action actually integrated')
            # Preserve executed flow even if the following sensor/update fails.
            atomic_json(out / 'ledger.json', {'entries': ledger.entries, 'summary': ledger.summary(),
                'forecast_energy_booked': False, 'terminal_value_booked': False})
            atomic_json(out / f'evaluator/guard-{iteration}.json', guarded.receipt)
            pending = {'input_snapshot_id': snapshot.snapshot_id, 'action': action.model_dump(mode='json'),
                'sensor_timestamp_s': None, 'next_snapshot_id': None, 'ledger_entry': entry,
                'observer_updated': False, 'future_planned_actions_executed': 0}
            rows.append(pending)
            atomic_json(out / f'evaluator/execution-{iteration}.json', {'energy_J': actual.energy_J,
                'elapsed_s': actual.elapsed_s, 'thermal_management_energy_J': actual.thermal_management_energy_J,
                'times_s': actual.times_s.tolist(), 'states': actual.states.tolist(),
                'voltages_V': actual.voltages_V.tolist(), 'solver': actual.solver, 'events': actual.events,
                'event_scopes': guarded.receipt['native_events_with_scope']})
            checks, soc_values = _execution_constraints(actual, action, plant, parameters, loaded['package'], all_soc)
            all_soc.extend(soc_values)
            pending['actual_constraint_checks'] = checks
            stopping = stop_status(guarded.receipt, actual, action.duration_s, checks)
            if stopping:
                pending['status'] = stopping
                break
            # Only voltage/current/temperature/time cross the evaluator boundary.
            reading = plant.observe(state, action.current_A)
            sensor = Observation(run_id=snapshot.run_id, timestamp_s=snapshot.obs_until_s + actual.elapsed_s,
                current_A=action.current_A,
                voltage_V=float(reading['voltage_V'] + sensor_rng.normal(0, source['voltage_noise_V'])),
                temperature_K=float(reading['temperature_K'] + sensor_rng.normal(0, source['temperature_noise_K'])))
            atomic_json(out / f'sensor-{iteration}.json', sensor.model_dump(mode='json'))
            next_snapshot = observer.update(sensor, duration_s=actual.elapsed_s,
                                           ambient_K=stages[0].ambient_K, thermal_W=action.thermal_W)
            atomic_json(out / f'posterior-{iteration}.json', next_snapshot.model_dump(mode='json'))
            completed += 1
            pending.update(sensor_timestamp_s=sensor.timestamp_s, next_snapshot_id=next_snapshot.snapshot_id,
                           next_observer_diagnostics=observer.update_diagnostics[-1], observer_updated=True)
        atomic_json(out / 'ledger.json', {'entries': ledger.entries, 'summary': ledger.summary(),
            'forecast_energy_booked': False, 'terminal_value_booked': False})
        result = {'exit_code': 0 if completed == 2 else 2, 'completed_sensor_replans': completed, 'steps': rows,
            'same_current_source': code_hash(root) == initial_hash, 'code_hash': initial_hash,
            'saved_Run_or_old_PF_modified': False, 'risk_certificate': False, 'independent_experiment': False,
            'scope': 'Two real first-action integrations and noisy synthetic sensor updates; finite scenario planning, no full C01/T3/UI/real profit acceptance'}
        if not result['same_current_source']: result['exit_code'] = 2
    except Exception as error:
        import traceback
        traceback.print_exc()
        result = {'exit_code': 2 if isinstance(error, (OSError, TimeoutError)) else 1,
                  'reason': str(error), 'completed_sensor_replans': completed, 'steps': rows,
                  'saved_Run_or_old_PF_modified': False, 'risk_certificate': False}
    atomic_json(out / 'result.json', result)
    return result['exit_code']


def run_scenario(root, calibration_dir, output_path):
    if any(p.casefold() == 'evaluator' for path in (calibration_dir, output_path) for p in Path(path).parts):
        raise ValueError('Public scenario paths cannot enter private evaluator')
    root, packet, out = Path(root).resolve(), Path(calibration_dir).resolve(), Path(output_path).resolve()
    if (not out.is_relative_to(root / 'artifacts') or out == root / 'artifacts'
            or out.is_relative_to(packet) or packet.is_relative_to(out)
            or any(p.casefold() == 'evaluator' for p in out.parts)):
        raise ValueError('Fresh controlled, nonoverlapping scenario output required')
    out.mkdir(parents=True, exist_ok=False)
    digest = code_hash(root)
    argv = [sys.executable, '-m', 'naheng.runtime.scenario_calibration', '--worker', str(root), str(packet), str(out)]
    atomic_json(out / 'started.json', {'argv': argv, 'code_hash': digest, 'timeout_s': 120})
    record = run_command(argv, root, out / 'worker.log', timeout=120)
    atomic_json(out / 'worker-command.json', {k:v for k,v in record.items() if k not in ('stdout', 'stderr')})
    result_path = out / 'result.json'
    complete = not record['timed_out'] and result_path.is_file() and code_hash(root) == digest
    result = json.loads(result_path.read_text(encoding='utf-8')) if complete else {'exit_code': 2}
    code = result['exit_code'] if complete and result['exit_code'] == record['exit_code'] else 2
    atomic_json(out / 'manifest.json', {'exit_code': code, 'complete': complete, 'code_hash': digest,
        'files': {p.relative_to(out).as_posix(): sha256_file(p) for p in sorted(out.rglob('*')) if p.is_file()},
        'saved_Run_or_old_PF_modified': False, 'full_C01_complete': False})
    return {'exit_code': code, 'complete': complete, 'artifact_dir': str(out),
            'completed_sensor_replans': result.get('completed_sensor_replans', 0)}


if __name__ == '__main__':
    if len(sys.argv) != 5 or sys.argv[1] != '--worker': raise SystemExit('Owned worker arguments required')
    raise SystemExit(_worker(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))
