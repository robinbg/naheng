"""E-T (theory) suite worker: one bounded measurement run from a frozen registration.

Invoked as an owned subprocess by the suite session, mirroring the other
experiments/*.py workers:

    python experiments/theory.py --root <project> --registration <registration.json> \\
        --output <artifacts/.../result>

The worker refuses before measuring anything unless the frozen preregistration
authorizes suite E-T. At revision 5 it does not, so this exits 2 and writes no
result — which is the intended behaviour, not a failure to be worked around.
"""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--registration', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--wall-budget-s', type=float, default=1.0)
    parser.add_argument('--skip-heldout', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / 'src'))
    from naheng.experiments.et_runner import execute
    result = execute(root, args.registration, args.output,
                     wall_budget_s=args.wall_budget_s, heldout=not args.skip_heldout)
    print(json.dumps({'suite': 'E-T', 'exit_code': result['exit_code'],
                      'status': result['status'],
                      'experiment_executed': result['experiment_executed'],
                      'new_independent_scientific_N': result['new_independent_scientific_N'],
                      'reason': result.get('reason')}))
    return result['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
