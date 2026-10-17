"""Keep incomplete numerical evidence out of terminal finance and probability."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from naheng.lifecycle.capacity_protocol import CapacityProtocol
from naheng.models.site_model import SiteModel
from naheng.runtime.lifecycle_finance_endpoints import storage_probe, capacity_diagnostic, adopt_endpoints
from naheng.runtime.lifecycle_finance_session import _validate_registration, run_lifecycle_finance
from naheng.runtime.lifecycle_finance_session import adopt_worker_report
from naheng.economics.lifecycle import FinancialAssumptions, from_lifecycle_result
from naheng.runtime.artifacts import atomic_json, sha256_file

ROOT = Path(__file__).resolve().parents[2]
SAVED = ROOT / 'tests/fixtures/lifecycle_finance/compare_cycle_maps.json'


def test_counterfactual_probe_requires_unique_cutoff_and_matching_time():
    good = {'status': 'computed', 'elapsed_s': 2., 'energy_J': 3.,
            'events': [{'name': 'voltage_low', 'time_s': 2.}]}
    assert storage_probe(good, 10.)['energy_J'] == 3.
    for events in ([{'name': 'voltage_low', 'time_s': 1.}],
                   [{'name': 'voltage_low', 'time_s': float('nan')}],
                   [{'name': 'voltage_low', 'time_s': 2.}, {'name': 'temperature_high', 'time_s': 2.}]):
        assert storage_probe({**good, 'events': events}, 10.)['energy_J'] is None
    assert storage_probe({**good, 'events': [], 'elapsed_s': 2.}, 10.)['status'] == 'unknown'
    assert storage_probe({**good, 'events': [], 'elapsed_s': 10.}, 10.)['status'] == 'right_censored'


def test_actual_saved_s04_capacity_adoption_rejects_competing_exits_and_fake_charge():
    saved = json.loads(SAVED.read_bytes())
    row = saved['fine']['trace'][0]['cells'][0]
    protocol = CapacityProtocol()
    assert capacity_diagnostic(row, protocol)[0] == row['protocol']['capacity_C']
    for key, value in [('capacity_C', row['protocol']['capacity_C'] + 1.), ('events', [])]:
        bad = deepcopy(row); bad['protocol'][key] = value
        assert capacity_diagnostic(bad, protocol) == (None, None)
    bad = deepcopy(row)
    bad['protocol']['events'].append({'name': 'temperature_high', 'time_s': bad['protocol']['elapsed_s']})
    assert capacity_diagnostic(bad, protocol) == (None, None)


def test_actual_saved_endpoints_keep_rul_none_and_macro_projection():
    saved = json.loads(SAVED.read_bytes())
    for name in ('fine', 'macro'):
        initial, final, events, audit = adopt_endpoints(saved[name], source_ref='saved-S04', model=SiteModel(), protocol=CapacityProtocol())
        assert initial.stored_energy_J == saved[name]['economics']['initial_stored_energy_probe']['energy_J']
        assert initial.assets[0].capacity_C == saved[name]['trace'][0]['cells'][0]['protocol']['capacity_C']
        assert final.assets[0].rul_s is None and events == ()
        assert (final.evidence_kind == 'conditional_projection') == (name == 'macro')
        assert audit['capacity_source'].startswith('declared numerical')


def test_budget_without_initial_trace_withholds_capacity_instead_of_faking_it():
    saved = json.loads(SAVED.read_bytes())['fine']
    saved['trace'] = []; saved['status'] = 'budget_exhausted'
    initial, final, _, audit = adopt_endpoints(saved, source_ref='budget', model=SiteModel(), protocol=CapacityProtocol())
    assert initial.soc is None and initial.assets[0].capacity_C is None
    assert initial.assets[0].pristine_capacity_C is None and final.status == 'unknown'
    assert audit['initial_capacity_diagnostic_missing']


@pytest.mark.parametrize('field,value', [('cycles', True), ('cycles', 100000), ('alpha', .9),
                                        ('worker_timeout_s', 121), ('worker_memory_limit_bytes', 0)])
def test_finance_pilot_rejects_changed_budget_and_comparison_registration(field, value):
    registration = json.loads((ROOT / 'configs/experiments/lifecycle-finance-pilot-v1.json').read_bytes())
    registration[field] = value
    with pytest.raises(ValueError):
        _validate_registration(registration)


def test_finance_output_refuses_evaluator_and_existing_artifacts(tmp_path):
    config = tmp_path / 'configs/experiments/lifecycle-finance-pilot-v1.json'
    config.parent.mkdir(parents=True)
    config.write_bytes((ROOT / 'configs/experiments/lifecycle-finance-pilot-v1.json').read_bytes())
    existing = tmp_path / 'artifacts/existing'; existing.mkdir(parents=True)
    with pytest.raises(ValueError):
        run_lifecycle_finance(tmp_path, tmp_path / 'artifacts/evaluator/rejected')
    with pytest.raises(FileExistsError):
        run_lifecycle_finance(tmp_path, existing)


def _saved_method_packet(tmp_path):
    # Actual saved S04 values, with explicitly constructed receipt metadata for
    # adoption-method tests only. This is not a new operating/simulation Run.
    from dataclasses import asdict, replace
    path = tmp_path / 'method-case'; path.mkdir()
    source = json.loads(SAVED.read_bytes())['fine']
    source_ref = (path / 'lifecycle.json').relative_to(tmp_path).as_posix()
    initial, final, events, audit = adopt_endpoints(source, source_ref=source_ref, model=SiteModel(), protocol=CapacityProtocol())
    assumptions = FinancialAssumptions('method synthetic', 'common-method', 48.)
    def calculate(values, shadow=()):
        return from_lifecycle_result(source, run_id='method-only', initial=initial, final=final,
                  assumptions=values, source_ref=source_ref, cash_events=events, planning_shadow_costs=shadow).to_dict()
    finance = calculate(assumptions)
    for name, value in {'started.json': {'registration_sha256': 'b'*64, 'code_hash': 'a'*64},
        'lifecycle.json': source, 'finance.json': finance,
        'endpoints.json': {'initial': asdict(initial), 'final': asdict(final), 'audit': audit},
        'rul-required-unknown.json': calculate(replace(assumptions, rul_value_CNY_per_s=.001)),
        'shadow-separate.json': calculate(assumptions, (1.,))}.items():
        atomic_json(path / name, value)
    report = {'code_hash': 'a'*64, 'exit_code': 0, 'case_id': 'method-case', 'policy_id': 'method-policy',
        'mode': 'exact', 'source_unchanged': True, 'execution_completed': True, 'independent_operating_trajectory': False,
        'independent_operating_n': 0, 'source_ref': source_ref, 'whole_case_status': 'complete', 'event_occurred': False,
        'finance_value': finance['conditional_comparison_value_CNY'],
        'artifacts': {f.name: sha256_file(f) for f in path.glob('*.json')}}
    atomic_json(path / 'report.json', report)
    return path, report


def test_saved_method_packet_adopts_only_matching_finance_files(tmp_path):
    path, report = _saved_method_packet(tmp_path)
    adopted = adopt_worker_report(path, root=tmp_path, digest='a'*64, registered_sha='b'*64,
                                  case_id='method-case', policy_id='method-policy', mode='exact', child_code=0)
    assert adopted['finance_value'] == report['finance_value']


@pytest.mark.parametrize('field,value', [('artifacts', None), ('artifacts', []), ('artifacts', {}),
                                        ('event_occurred', 'yes'), ('whole_case_status', 'made-up'),
                                        ('finance_value', float('inf')), ('finance_value', 1000.),
                                        ('independent_operating_trajectory', True)])
def test_malformed_or_fabricated_report_is_not_a_success(tmp_path, field, value):
    path, report = _saved_method_packet(tmp_path)
    # json.dumps permits Infinity here solely to probe parser refusal, never for
    # production artifact emission (atomic_json disallows nonfinite values).
    report[field] = value
    (path / 'report.json').write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(ValueError):
        adopt_worker_report(path, root=tmp_path, digest='a'*64, registered_sha='b'*64,
                            case_id='method-case', policy_id='method-policy', mode='exact', child_code=0)
