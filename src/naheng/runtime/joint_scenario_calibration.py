"""Explicit finite-support joint likelihood in a real bounded synthetic loop."""
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
from naheng.estimation.calibration import content_hash
from naheng.estimation.joint_gaussian_observer import JointGaussianObserver, JointObserverUnknown
from naheng.estimation.particle_filter import particle_model
from naheng.formal.checker import run_command
from .artifacts import atomic_json, code_hash, sha256_file
from .baseline_frontier import _execution_constraints
from .calibration_consumer import ConsumerUnknown, _packet
from .execution_receipts import stop_status

SCOPE = ('Two actual first-action integrations and explicitly biased, correlated synthetic sensors; '
         'finite-support conditional Bayesian updates, no real-cell coverage, risk or profit certificate')


def _worker(root, packet, out):
    started, digest = time.monotonic(), code_hash(root)
    rows, ledger, completed = [], None, 0
    try:
        loaded = _packet(root, packet)
        protected = dict(loaded['hashes'])
        boundaries = []

        def stable(boundary):
            if time.monotonic() - started >= 105:
                raise TimeoutError('Joint scenario total budget reached')
            okay = code_hash(root) == digest and all(sha256_file(path) == expected
                                                    for path, expected in protected.items())
            boundaries.append({'boundary': boundary, 'source_and_packet_unchanged': okay})
            if not okay:
                raise ConsumerUnknown('Current source/calibration packet changed during joint execution')

        original = loaded['snapshot']
        # Each fresh invocation has its own public identity. Rekeying preserves
        # the physical posterior; no new observation is claimed at adoption.
        run_id = 'joint-' + content_hash({'packet': sha256_file(packet / 'manifest.json'),
                                         'code_hash': digest, 'out': out.relative_to(root).as_posix()})[:24]
        observer = JointGaussianObserver(original, loaded['model'], loaded['request'].noise,
                                         run_id=run_id, wall_budget_s=100)
        noise = loaded['request'].noise
        covariance, bias = np.asarray(noise.covariance), np.asarray(noise.bias)
        cholesky = np.linalg.cholesky(covariance)
        parameters = MPCParameters(current_limit_A=.02, thermal_min_W=0, thermal_max_W=0,
            nominal_terminal_buffer=0, prediction_max_step_s=5, max_iterations=25,
            max_candidate_evaluations=120, wall_budget_s=15,
            tariff_source='declared_synthetic_joint_observer_two_stage_prices')
        ledger = EnergyLedger(run_id, tariff_source=parameters.tariff_source)
        sensor_rng = np.random.default_rng(20261124)
        atomic_json(out / 'registration.json', {'run_id': run_id, 'code_hash': digest,
            'calibration_dir': packet.relative_to(root).as_posix(),
            'calibration_manifest_sha256': sha256_file(packet / 'manifest.json'),
            'candidate_sha256': loaded['candidate'].content_sha256,
            'protected_source_and_packet_hashes': {path.relative_to(root).as_posix(): expected
                                                  for path, expected in protected.items()},
            'source_snapshot_id': original.snapshot_id, 'source_snapshot_sha256': content_hash(original),
            'noise': noise.model_dump(mode='json'), 'noise_sha256': content_hash(noise),
            'parameters': asdict(parameters), 'world_seed': 20261123, 'sensor_seed': 20261124,
            'executed_steps': 2, 'prediction_steps': 2, 'step_duration_s': 5,
            'independent_operational_trajectories': 0, 'no_resampling': True, 'scope': SCOPE})
        atomic_json(out / 'adoption.json', {'source_snapshot_id': original.snapshot_id,
            'observer_snapshot_id': observer.snapshot.snapshot_id, 'run_id': run_id,
            'samples_and_weights_preserved': observer.snapshot.samples == original.samples
                and observer.snapshot.weights == original.weights,
            'timestamps_preserved': observer.snapshot.obs_until_s == original.obs_until_s,
            'physical_parameter_revision': original.parameter_revision,
            'future_sensor_assimilated': False, 'existing_filter_or_run_modified': False,
            'likelihood': noise.model_dump(mode='json')})
        plant, state, all_soc = None, None, []
        for iteration in range(2):
            stable(f'before-plan-{iteration}')
            snapshot = observer.snapshot
            stages = ([MPCStage(5, .05, .04, 299.15), MPCStage(5, .15, .40, 299.15)]
                      if iteration == 0 else [MPCStage(5, .15, .40, 299.15), MPCStage(5, .05, .04, 299.15)])
            response = plan(snapshot, loaded['model'], loaded['package'], stages, parameters=parameters)
            atomic_json(out / f'plan-{iteration}.json', response.to_dict())
            if response.status != 'feasible' or response.action is None:
                break
            action = response.action
            if plant is None:
                index = int(np.random.default_rng(20261123).choice(len(snapshot.samples), p=snapshot.weights))
                selected = np.asarray(snapshot.samples[index])
                plant = particle_model(loaded['model'], selected[-2], selected[-1])
                state = selected[:5].copy()
                all_soc = [float(state[:2] @ np.asarray(plant.params.site_capacity_mol)
                                 / sum(plant.params.site_capacity_mol))]
                atomic_json(out / 'evaluator/initial.json', {'posterior_index': index,
                    'joint_sample': selected.tolist(), 'private_draw_after_first_plan': True,
                    'supplied_to_controller': False, 'scope': 'Conditional synthetic evaluator world'})
            try:
                guarded = integrate_guarded_action(plant, state, action, loaded['package'], parameters, stages[0].ambient_K)
            except GuardedExecutionRejected as error:
                atomic_json(out / f'evaluator/refusal-{iteration}.json', error.receipt)
                break
            actual = guarded.result
            state = actual.state.copy()
            entry = ledger.append(action, execution_id=f'executed-{iteration}', energy_J=actual.energy_J,
                thermal_energy_J=actual.thermal_management_energy_J,
                buy_price_per_kWh=stages[0].buy_price_per_kWh, sell_price_per_kWh=stages[0].sell_price_per_kWh,
                executed=True, duration_s=actual.elapsed_s, reason='Actual first-action integration only')
            atomic_json(out / 'ledger.json', {'entries': ledger.entries, 'summary': ledger.summary(),
                'forecast_energy_booked': False, 'terminal_value_booked': False})
            atomic_json(out / f'evaluator/guard-{iteration}.json', guarded.receipt)
            pending = {'input_snapshot_id': snapshot.snapshot_id, 'action': action.model_dump(mode='json'),
                'ledger_entry': entry, 'observer_updated': False, 'future_planned_actions_executed': 0,
                'sensor_timestamp_s': None, 'next_snapshot_id': None}
            rows.append(pending)
            atomic_json(out / f'evaluator/execution-{iteration}.json', {'energy_J': actual.energy_J,
                'elapsed_s': actual.elapsed_s, 'thermal_management_energy_J': actual.thermal_management_energy_J,
                'times_s': actual.times_s.tolist(), 'states': actual.states.tolist(),
                'voltages_V': actual.voltages_V.tolist(), 'solver': actual.solver, 'events': actual.events,
                'event_scopes': guarded.receipt['native_events_with_scope']})
            checks, soc_values = _execution_constraints(actual, action, plant, parameters, loaded['package'], all_soc)
            all_soc.extend(soc_values)
            pending['actual_constraint_checks'] = checks
            stable(f'after-execution-{iteration}')
            stopping = stop_status(guarded.receipt, actual, action.duration_s, checks)
            if stopping:
                pending['status'] = stopping
                break
            reading = plant.observe(state, action.current_A)
            error = bias + cholesky @ sensor_rng.standard_normal(2)
            sensor = Observation(run_id=run_id, timestamp_s=snapshot.obs_until_s + actual.elapsed_s,
                current_A=action.current_A, voltage_V=float(reading['voltage_V'] + error[0]),
                temperature_K=float(reading['temperature_K'] + error[1]))
            atomic_json(out / f'sensor-{iteration}.json', sensor.model_dump(mode='json'))
            next_snapshot = observer.update(sensor, duration_s=actual.elapsed_s,
                                            ambient_K=stages[0].ambient_K, thermal_W=action.thermal_W)
            atomic_json(out / f'posterior-{iteration}.json', next_snapshot.model_dump(mode='json'))
            atomic_json(out / f'observer-diagnostics-{iteration}.json', observer.update_diagnostics[-1])
            completed += 1
            pending.update(sensor_timestamp_s=sensor.timestamp_s, next_snapshot_id=next_snapshot.snapshot_id,
                           observer_updated=True)
            stable(f'after-observer-{iteration}')
        stable('before-result')
        result = {'exit_code': 0 if completed == 2 else 2, 'completed_sensor_replans': completed,
            'steps': rows, 'run_id': run_id, 'code_hash': digest, 'same_current_source': code_hash(root) == digest,
            'noise_sha256': content_hash(noise), 'saved_Run_or_old_PF_modified': False,
            'source_verification_boundaries': boundaries,
            'risk_certificate': False, 'independent_operational_trajectories': 0,
            'scientific_profit_comparability': False, 'scope': SCOPE}
        if not result['same_current_source']:
            result['exit_code'] = 2
    except Exception as error:
        import traceback
        traceback.print_exc()
        result = {'exit_code': 2 if isinstance(error, (OSError, TimeoutError, ConsumerUnknown, JointObserverUnknown)) else 1,
                  'reason': str(error), 'completed_sensor_replans': completed, 'steps': rows,
                  'saved_Run_or_old_PF_modified': False, 'risk_certificate': False, 'scope': SCOPE}
    atomic_json(out / 'result.json', result)
    return result['exit_code']


def run_joint_scenario(root, calibration_dir, output_path):
    if any(part.casefold() == 'evaluator' for path in (calibration_dir, output_path) for part in Path(path).parts):
        raise ValueError('Public joint scenario paths cannot enter private evaluator')
    root, packet, out = Path(root).resolve(), Path(calibration_dir).resolve(), Path(output_path).resolve()
    if (not packet.is_relative_to(root / 'artifacts') or not (packet / 'manifest.json').is_file()
            or not out.is_relative_to(root / 'artifacts') or out == root / 'artifacts'
            or out.is_relative_to(packet) or packet.is_relative_to(out)
            or any(part.casefold() == 'evaluator' for part in out.parts)):
        raise ValueError('Controlled calibration packet and fresh nonoverlapping joint output required')
    out.mkdir(parents=True, exist_ok=False)
    digest = code_hash(root)
    argv = [sys.executable, '-m', 'naheng.runtime.joint_scenario_calibration', '--worker', str(root), str(packet), str(out)]
    atomic_json(out / 'started.json', {'argv': argv, 'code_hash': digest, 'timeout_s': 120})
    command = run_command(argv, root, out / 'worker.log', timeout=120)
    atomic_json(out / 'worker-command.json', {k:v for k,v in command.items() if k not in ('stdout', 'stderr')})
    result_path = out / 'result.json'
    complete = not command['timed_out'] and result_path.is_file() and code_hash(root) == digest
    result = json.loads(result_path.read_text(encoding='utf-8')) if complete else {'exit_code': 2}
    code = result['exit_code'] if complete and result['exit_code'] == command['exit_code'] else 2
    atomic_json(out / 'manifest.json', {'exit_code': code, 'complete': complete, 'code_hash': digest,
        'files': {p.relative_to(out).as_posix(): sha256_file(p) for p in sorted(out.rglob('*')) if p.is_file()},
        'saved_Run_or_old_PF_modified': False, 'full_E02_complete': False, 'scope': SCOPE})
    return {'exit_code': code, 'complete': complete, 'artifact_dir': out.as_posix(),
            'completed_sensor_replans': result.get('completed_sensor_replans', 0), 'scope': SCOPE}


if __name__ == '__main__':
    if len(sys.argv) != 5 or sys.argv[1] != '--worker':
        raise SystemExit('Owned worker arguments required')
    raise SystemExit(_worker(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))
