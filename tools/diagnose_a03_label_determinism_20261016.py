"""Read-only diagnosis: is an A03 training label determined by the candidate?

The three-arm comparison (learned / random / uncertainty) shares one frozen
initial design, because ``Limits.seed`` and ``BOUNDS`` are identical for every
arm.  This tool re-reads the *already sealed* arm artifacts and reports, for
every ordinal whose candidate is byte-identical across arms, whether the arms
agreed on the execution outcome.

It writes no new simulation, changes no source, and invents no label.  It only
compares recorded evidence, so its exit code reports whether the shared
training oracle is reproducible on identical inputs:

    0  every shared-input ordinal produced the same status in every arm
    1  at least one shared input produced different statuses  (not reproducible)
    2  the sealed artifacts needed for the comparison are missing
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ARMS = {
    'learned': 'artifacts/optimization/public-9593-20261016-c',
    'random': 'artifacts/full-policy-random-6fc49921be',
    'uncertainty': 'artifacts/full-policy-uncertainty-6ecf182273',
}


def load_events(arm_dir: Path):
    checkpoint = arm_dir / 'checkpoint.json'
    if not checkpoint.is_file():
        raise FileNotFoundError(checkpoint)
    return json.loads(checkpoint.read_text(encoding='utf-8'))['state']['events']


def plan_trace(case_dir: Path):
    """Per-step planner verdicts actually recorded for one execution."""
    steps = []
    for index in range(64):
        path = case_dir / f'plan-{index}.json'
        if not path.is_file():
            break
        record = json.loads(path.read_text(encoding='utf-8'))
        diagnostics = record.get('diagnostics') or {}
        counters = diagnostics.get('counters') or {}
        steps.append({
            'step': index,
            'plan_status': record.get('status'),
            'plan_wall_s': diagnostics.get('wall_s'),
            'worker_wall_s': diagnostics.get('wall_s_worker'),
            'timed_out': diagnostics.get('timed_out'),
            'declared_wall_budget_s': diagnostics.get('wall_budget_s'),
            'declared_max_iterations': diagnostics.get('max_iterations'),
            'declared_max_candidate_evaluations': diagnostics.get('max_candidate_evaluations'),
            'candidate_evaluations': counters.get('candidate_evaluations'),
            'completed_integrations': counters.get('completed_integrations'),
            'reason': record.get('reason'),
        })
    return steps


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=None,
                        help='project-owned artifact path for the JSON report')
    arguments = parser.parse_args()

    arms = {}
    for name, relative in DEFAULT_ARMS.items():
        arm_dir = ROOT / relative
        try:
            arms[name] = {'dir': arm_dir, 'events': load_events(arm_dir)}
        except (FileNotFoundError, KeyError, json.JSONDecodeError) as error:
            print(json.dumps({'status': 'missing_sealed_evidence', 'arm': name,
                              'dir': relative, 'error': repr(error)}))
            return 2

    names = tuple(arms)
    shared = min(len(arms[name]['events']) for name in names)
    rows, divergences = [], []
    for ordinal in range(shared):
        per_arm = {name: arms[name]['events'][ordinal] for name in names}
        identities = {name: row['candidate_id'] for name, row in per_arm.items()}
        fidelities = {name: row['fidelity'] for name, row in per_arm.items()}
        timeouts = {name: row.get('timeout_s') for name, row in per_arm.items()}
        same_input = (len(set(identities.values())) == 1
                      and len(set(fidelities.values())) == 1
                      and len(set(timeouts.values())) == 1)
        statuses = {name: row['result']['status'] for name, row in per_arm.items()}
        costs = {name: row['result']['cost_s'] for name, row in per_arm.items()}
        row = {
            'ordinal': ordinal,
            'candidate_id': next(iter(identities.values())),
            'fidelity': next(iter(fidelities.values())),
            'timeout_s': next(iter(timeouts.values())),
            'identical_declared_input': same_input,
            'status_per_arm': statuses,
            'measured_cost_s_per_arm': costs,
            'statuses_agree': len(set(statuses.values())) == 1,
        }
        if same_input and not row['statuses_agree']:
            detail = {}
            for name in names:
                case = arms[name]['dir'] / 'cases' / f'{ordinal:03d}-{row["fidelity"]}'
                detail[name] = plan_trace(case) if case.is_dir() else 'case_dir_absent'
            row['plan_trace_per_arm'] = detail
            divergences.append(row)
        rows.append(row)

    report = {
        'tool': Path(__file__).name,
        'scope': 'read-only comparison of sealed A03 arm artifacts; no new execution',
        'arms': {name: str(arms[name]['dir'].relative_to(ROOT)).replace('\\', '/') for name in names},
        'shared_initial_design_ordinals': shared,
        'identical_input_ordinals': sum(row['identical_declared_input'] for row in rows),
        'divergent_ordinals': [row['ordinal'] for row in divergences],
        'labels_reproducible_on_identical_input': not divergences,
        'rows': rows,
        'scientific_N_added': 0,
        'risk_certificate': False,
        'invented_labels': 0,
    }
    if arguments.out:
        out = Path(arguments.out).resolve()
        if not out.is_relative_to(ROOT / 'artifacts'):
            raise ValueError('Project-owned artifact output required')
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'out': str(out.relative_to(ROOT)).replace('\\', '/'),
                          'divergent_ordinals': report['divergent_ordinals'],
                          'labels_reproducible_on_identical_input': report['labels_reproducible_on_identical_input']}))
    else:
        print(json.dumps({k: report[k] for k in ('shared_initial_design_ordinals',
                                                 'identical_input_ordinals', 'divergent_ordinals',
                                                 'labels_reproducible_on_identical_input')}))
    return 0 if not divergences else 1


if __name__ == '__main__':
    raise SystemExit(main())
