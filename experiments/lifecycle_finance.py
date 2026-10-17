"""One bounded actual S04 lifecycle case from a frozen source/registration."""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    for name in ('root', 'source-dir', 'registration', 'out', 'case-id', 'policy-id'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--mode', choices=('exact', 'macro', 'early-exit', 'thermal', 'module'), default='exact')
    args = parser.parse_args()
    root, frozen, out = Path(args.root), Path(args.source_dir), Path(args.out)
    sys.path.insert(0, str(frozen / 'src'))
    from naheng.economics.lifecycle import FinancialAssumptions, from_lifecycle_result
    from naheng.lifecycle.capacity_protocol import CapacityProtocol
    from naheng.lifecycle.runner import CyclePolicy, LifecycleEconomics, run_lifecycle
    from naheng.models.site_model import SiteModel, SiteParameters
    from naheng.runtime.artifacts import atomic_json, code_hash, sha256_file
    from naheng.runtime.lifecycle_finance_endpoints import adopt_endpoints
    registration = json.loads(Path(args.registration).read_text(encoding='utf-8'))
    digest = code_hash(frozen)
    case = next(x for x in registration['cases'] if x['case_id'] == args.case_id)
    policy_spec = next(x for x in registration['policies'] if x['policy_id'] == args.policy_id)
    if args.mode == 'thermal':
        policy_spec = {**policy_spec, 'thermal_W': registration['thermal_audit']['thermal_W']}
    overrides = dict(case['model_overrides'])
    if 'side_rate_s_inv' in overrides:
        overrides['side_rate_s_inv'] = tuple(overrides['side_rate_s_inv'])
    model = SiteModel(replace(SiteParameters(), **overrides))
    if args.mode == 'module':
        from naheng.simulation.module import ModuleModel
        cells = []
        for cell_overrides in registration['module_audit']['cell_overrides']:
            values = dict(cell_overrides)
            if 'side_rate_s_inv' in values:
                values['side_rate_s_inv'] = tuple(values['side_rate_s_inv'])
            cells.append(SiteModel(replace(SiteParameters(), **values)))
        model = ModuleModel(tuple(cells), coupling_W_per_K=registration['module_audit']['coupling_W_per_K'])
    protocol = CapacityProtocol(**(registration['macro_audit']['protocol'] if args.mode == 'macro' else registration['protocol']))
    policy = CyclePolicy(**policy_spec, phase_duration_s=registration['phase_duration_s'],
                         hold_cycles=6 if args.mode == 'macro' else 1)
    economics = LifecycleEconomics(**registration['energy_economics'])
    assumptions = FinancialAssumptions(**registration['financial_assumptions'])
    out.mkdir(parents=True, exist_ok=False)
    atomic_json(out / 'started.json', {'code_hash': digest, 'registration_sha256': sha256_file(Path(args.registration)),
                'case_id': args.case_id, 'policy_id': args.policy_id, 'mode': args.mode,
                'model_parameters': asdict(model.params) if isinstance(model, SiteModel) else
                    {'cells': [asdict(cell.params) for cell in model.cells], 'topology': model.topology,
                     'coupling_W_per_K': model.coupling_W_per_K}, 'protocol': asdict(protocol),
                'policy': asdict(policy), 'same_information': 'fixed policy ignores all callback diagnostic fields'})
    result = run_lifecycle(model, cycles=registration['cycles'], protocol=protocol,
                policy_provider=lambda _context: policy,
                maximum_replacements=registration['early_exit_audit']['maximum_replacements'] if args.mode == 'early-exit' else registration['maximum_replacements'],
                jump_check_cycles=6 if args.mode == 'macro' else 1,
                economics=economics, wall_budget_s=110)
    atomic_json(out / 'lifecycle.json', result)  # Preserve actual phases before finance adoption.
    source_ref = (out / 'lifecycle.json').relative_to(root).as_posix()
    initial, final, cash, endpoint_audit = adopt_endpoints(result, source_ref=source_ref, model=model, protocol=protocol)
    run_id = ':'.join((args.mode, args.case_id, args.policy_id))
    finance = from_lifecycle_result(result, run_id=run_id, initial=initial, final=final,
                                    assumptions=assumptions, source_ref=source_ref, cash_events=cash).to_dict()
    atomic_json(out / 'finance.json', finance)
    atomic_json(out / 'endpoints.json', {'initial': asdict(initial), 'final': asdict(final),
                                       'cash_events': [asdict(e) for e in cash], 'audit': endpoint_audit})
    # Enabled future RUL valuation is explicitly UNKNOWN, not a horizon proxy.
    future_assumptions = replace(assumptions, rul_value_CNY_per_s=.001)
    future = from_lifecycle_result(result, run_id=run_id, initial=initial, final=final,
                                   assumptions=future_assumptions, source_ref=source_ref, cash_events=cash).to_dict()
    atomic_json(out / 'rul-required-unknown.json', future)
    shadow = from_lifecycle_result(result, run_id=run_id, initial=initial, final=final,
                     assumptions=assumptions, source_ref=source_ref, cash_events=cash, planning_shadow_costs=(1.,)).to_dict()
    atomic_json(out / 'shadow-separate.json', shadow)
    if (future['conditional_comparison_value_CNY'] is not None or shadow['planning_shadow_deducted_CNY'] != 0
            or shadow['conditional_comparison_value_CNY'] != finance['conditional_comparison_value_CNY']):
        raise ValueError('Unknown RUL or no-double-shadow invariant failed')
    event = bool(result['retirement_records'] or any(p['events'] for p in result['phases']))
    stable = digest == code_hash(frozen)
    complete = result['completed_cycles'] == registration['cycles'] and result['status'] == 'right_censored'
    atomic_json(out / 'report.json', {'exit_code': 0 if stable else 2, 'execution_completed': True,
        'code_hash': digest, 'source_unchanged': stable, 'case_id': args.case_id, 'policy_id': args.policy_id,
        'mode': args.mode, 'lifecycle_status': result['status'], 'completed_cycles': result['completed_cycles'],
        'accepted_jumps': result['numerical']['accepted_jumps'], 'elapsed_s': result['elapsed_s'],
        'thermal_management_energy_J': result['thermal_management_energy_J'],
        'topology': result['topology'], 'cell_count': len(final.assets), 'replacement_count': result['replacement_count'],
        'whole_case_status': 'complete' if complete else 'unknown' if result['status'] in ('unknown_capacity', 'budget_exhausted') else 'early_exit',
        'event_occurred': None if result['status'] in ('unknown_capacity', 'budget_exhausted') else event,
        'independent_operating_trajectory': False, 'independent_operating_n': 0,
        'finance_value': finance['conditional_comparison_value_CNY'], 'source_ref': source_ref,
        'artifacts': {path.name: sha256_file(path) for path in out.glob('*.json') if path.name != 'report.json'},
        'scope': 'actual synthetic numerical lifecycle; counterfactual endpoint valuation; no physical income/lifetime/risk certificate'})
    return 0 if stable else 2


if __name__ == '__main__':
    raise SystemExit(main())
