"""Repeat one sealed A03 candidate and require an identical training label.

The sealed three-arm comparison contains an ordinal whose declared input is
byte-identical across arms but whose recorded outcome is not: the same
candidate completed in one arm and was reported unknown in the other two
because an inner wall-clock guard pre-empted identical declared work.

This probe re-executes such a candidate several times through the real owned
oracle worker and requires the *same* status every time, plus the same per-step
planner verdict and work counters. It invents no label: a repeat that cannot
finish inside the declared per-query timeout is recorded as unknown and counted
as a disagreement, exactly as the training loop would.

Exit codes
    0  every repetition returned the same status and the same per-step work
       sequence
    1  repetitions disagreed, so the label is still not candidate-determined
    2  the probe never tested a label: missing sealed input, blocked calibration,
       or no repetition reached the planner (agreement on "unknown" caused by a
       setup failure is not evidence of determinism)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from naheng.learning.operational_oracle import OperationalOracle  # noqa: E402
from naheng.learning.policy_space import fixed_world  # noqa: E402


def sealed_request(arm_dir: Path, ordinal: int, fidelity: str):
    path = arm_dir / 'cases' / f'{ordinal:03d}-{fidelity}' / 'request.json'
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding='utf-8'))
    return payload['request']


def probe_one(request, packet: Path, out_root: Path, repetitions: int):
    rows = []
    for index in range(repetitions):
        out = out_root / f'rep-{index:02d}-{uuid.uuid4().hex[:8]}'
        out.mkdir(parents=True, exist_ok=False)
        oracle = OperationalOracle(out, packet=packet, world=fixed_world())
        started = time.monotonic()
        try:
            response = oracle.evaluate(request)
        except Exception as error:  # recorded, never converted into a label
            response = {'status': 'unknown', 'utility': None, 'constraint_margin': None,
                        'cost_s': None, 'reason': f'{type(error).__name__}: {error}'}
        case = out / f"{request['ordinal']:03d}-{request['fidelity']}"
        steps = []
        for step in range(64):
            plan_path = case / f'plan-{step}.json'
            if not plan_path.is_file():
                break
            record = json.loads(plan_path.read_text(encoding='utf-8'))
            diagnostics = record.get('diagnostics') or {}
            counters = diagnostics.get('counters') or {}
            steps.append({'plan_status': record.get('status'),
                          'candidate_evaluations': counters.get('candidate_evaluations'),
                          'completed_integrations': counters.get('completed_integrations'),
                          'worker_wall_s': diagnostics.get('wall_s_worker'),
                          'plan_wall_s': diagnostics.get('wall_s'),
                          'timed_out': diagnostics.get('timed_out')})
        result_path = case / 'result.json'
        actual = json.loads(result_path.read_text(encoding='utf-8')) if result_path.is_file() else {}
        rows.append({'repetition': index, 'status': response['status'],
                     'reason': response.get('reason'), 'utility': response.get('utility'),
                     'constraint_margin': response.get('constraint_margin'),
                     'measured_cost_s': time.monotonic() - started,
                     'reported_cost_s': response.get('cost_s'),
                     'case_status': actual.get('status'),
                     'completed_sensor_replans': actual.get('completed_sensor_replans'),
                     'plans': steps})
    return rows


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', default='artifacts/full-policy-uncertainty-6ecf182273')
    parser.add_argument('--ordinal', type=int, default=6)
    parser.add_argument('--fidelity', default='low', choices=['low', 'high'])
    parser.add_argument('--repetitions', type=int, default=5)
    parser.add_argument('--packet', default=None,
                        help='reuse one sealed packet; by default a packet bound to the current source is built')
    parser.add_argument('--out', required=True)
    arguments = parser.parse_args()
    if not 2 <= arguments.repetitions <= 12:
        raise ValueError('Two to twelve repetitions are supported')

    arm_dir = (ROOT / arguments.arm).resolve()
    out_root = (ROOT / arguments.out).resolve()
    if not arm_dir.is_relative_to(ROOT / 'artifacts'):
        raise ValueError('Project-owned sealed input required')
    if not out_root.is_relative_to(ROOT / 'artifacts'):
        raise ValueError('Project-owned artifact output required')
    try:
        request = sealed_request(arm_dir, arguments.ordinal, arguments.fidelity)
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({'status': 'missing_sealed_request', 'error': repr(error)}))
        return 2
    out_root.mkdir(parents=True, exist_ok=False)

    # A calibration packet is bound to the ROOT code hash, so a packet sealed
    # against older source is correctly refused. Build one for this source.
    packet_built = None
    if arguments.packet:
        packet = (ROOT / arguments.packet).resolve()
        if not packet.is_relative_to(ROOT / 'artifacts'):
            raise ValueError('Project-owned declared calibration packet required')
    else:
        import naheng.learning
        from naheng.estimation.calibration_session import run_calibration
        from naheng.runtime.artifacts import atomic_json
        packet = ROOT / 'artifacts' / 'calibration' / f'a03-determinism-{uuid.uuid4().hex[:10]}'
        request_path = Path(naheng.learning.__file__).parent / 'calibration_request.json'
        started = time.monotonic()
        preflight = run_calibration(ROOT, request_path, packet)
        packet_built = {'preflight': preflight, 'elapsed_s': time.monotonic() - started}
        atomic_json(out_root / 'calibration-preflight.json', preflight)
        if preflight['exit_code'] != 0:
            print(json.dumps({'status': 'blocked_calibration', 'calibration': preflight}))
            return 2
    if not (packet / 'manifest.json').is_file() or not (packet / 'result.json').is_file():
        print(json.dumps({'status': 'missing_calibration_packet', 'packet': str(packet)}))
        return 2

    rows = probe_one(request, packet, out_root, arguments.repetitions)
    statuses = {row['status'] for row in rows}
    # Compare the per-step sequence, not a flattened set: the four MPC steps of
    # one execution legitimately consume different amounts of declared work, so
    # a set over all steps would report disagreement inside a single repetition.
    sequences = {tuple((step['plan_status'], step['candidate_evaluations'],
                        step['completed_integrations']) for step in row['plans'])
                 for row in rows}
    utilities = {row['utility'] for row in rows if row['status'] == 'completed'}
    margins = {row['constraint_margin'] for row in rows if row['status'] == 'completed'}
    worker_walls = [step['worker_wall_s'] for row in rows for step in row['plans']
                    if step['worker_wall_s'] is not None]
    plan_steps = [len(row['plans']) for row in rows]
    # Agreeing on "unknown" proves nothing when the planner was never reached,
    # so a probe that never exercised the declared work is not a pass.
    reached_planner = bool(plan_steps) and min(plan_steps) >= 1
    reproducible = (reached_planner and len(statuses) == 1 and len(sequences) == 1
                    and len(utilities) <= 1 and len(margins) <= 1)
    report = {
        'tool': Path(__file__).name,
        'sealed_input': {'arm': arguments.arm, 'ordinal': arguments.ordinal,
                         'fidelity': arguments.fidelity,
                         'candidate_id': request['candidate_id'],
                         'reservation_id': request['reservation_id'],
                         'timeout_s': request['timeout_s'],
                         'parameters': request['parameters']},
        'calibration_packet': str(packet.relative_to(ROOT)).replace('\\', '/'),
        'calibration_packet_built_for_current_source': packet_built,
        'repetitions': arguments.repetitions,
        'distinct_statuses': sorted(statuses),
        'distinct_plan_step_sequences': sorted(json.dumps([list(step) for step in sequence])
                                               for sequence in sequences),
        'distinct_completed_utilities': sorted(str(u) for u in utilities),
        'distinct_completed_margins': sorted(str(m) for m in margins),
        'plan_steps_per_repetition': plan_steps,
        'every_repetition_reached_the_planner': reached_planner,
        'label_determined_by_candidate': reproducible,
        'worker_wall_s_observed': {'min': min(worker_walls) if worker_walls else None,
                                   'max': max(worker_walls) if worker_walls else None,
                                   'declared_wall_backstop_s': 25.0},
        'rows': rows,
        'scope': 'repeated execution of one sealed synthetic training candidate',
        'scientific_N_added': 0, 'risk_certificate': False, 'invented_labels': 0,
    }
    (out_root / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('distinct_statuses', 'distinct_plan_step_sequences',
                                             'distinct_completed_utilities', 'plan_steps_per_repetition',
                                             'every_repetition_reached_the_planner',
                                             'label_determined_by_candidate', 'worker_wall_s_observed')}, indent=1))
    exit_code = 0 if reproducible else (2 if not reached_planner else 1)
    print(json.dumps({'out': str(out_root.relative_to(ROOT)).replace('\\', '/'),
                      'exit_code': exit_code,
                      'exit_meaning': {0: 'identical label on every repetition',
                                       1: 'repetitions disagreed; label still not candidate-determined',
                                       2: 'planner never reached; the probe did not test the label'}[exit_code]}))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
