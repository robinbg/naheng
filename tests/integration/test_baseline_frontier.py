"""Registered selection guards and actual conditional paired execution."""

# --- published-formal-evidence guard (see docs/adr/0027) ---------------------
# These tests verify that runtime behaviour is bound to *published* formal
# evidence: active pointers, the compiled objects they name, and the runtime
# refresh. That evidence is a build product and is not redistributed, so a fresh
# clone cannot verify a binding that has not been built yet. Skipping is visible
# and reasoned; present-but-inconsistent evidence still fails the assertion.
import pytest as _pytest_publication_guard
from naheng.formal.publication_availability import (  # noqa: E402
    SKIP_REASON as _PUBLICATION_SKIP_REASON,
    publication_evidence_available as _publication_evidence_available)

pytestmark = _pytest_publication_guard.mark.skipif(
    not _publication_evidence_available(), reason=_PUBLICATION_SKIP_REASON)
# ---------------------------------------------------------------------------

from copy import deepcopy
import json
from pathlib import Path
import sys
import uuid

import pytest
from naheng.estimation.calibration_session import run_calibration
from naheng.formal.checker import run_command
from naheng.runtime import baseline_frontier as F

ROOT = Path(__file__).resolve().parents[2]


def protocol():
    value = json.loads((ROOT/'configs/experiments/fixed-baseline-frontier-v1.json').read_text(encoding='utf-8'))
    value['candidates'] = [value['candidates'][0], value['candidates'][2]]
    value['training_seeds'], value['evaluation_seeds'] = [2026101401], [2026101411]
    value['protocol_id'] = 'integration-small-fixed-frontier'
    value['batch_wall_budget_s'] = 120
    return value


@pytest.mark.parametrize('policy_id', ['../../escape', 'C:/escape', 'evaluator', 'a/b', 'a\\b'])
def test_candidate_ids_cannot_create_public_or_private_paths(policy_id):
    value = protocol(); value['candidates'][0]['policy_id'] = policy_id
    with pytest.raises(ValueError, match='policy IDs'): F.parse_protocol(value)


def test_registration_rejects_eval_reuse_duplicate_vectors_and_boolean_units():
    value = protocol(); value['evaluation_seeds'] = value['training_seeds']
    with pytest.raises(ValueError, match='disjoint'): F.parse_protocol(value)
    value = protocol(); value['candidates'][1] = {**value['candidates'][0], 'policy_id': 'duplicate-vector'}
    with pytest.raises(ValueError, match='actually differ'): F.parse_protocol(value)
    value = protocol(); value['parameters']['current_limit_A'] = True
    with pytest.raises(ValueError, match='Boolean'): F.parse_protocol(value)
    value = protocol(); value['training_seeds'] = [[1]]
    with pytest.raises(ValueError, match='integer seeds'): F.parse_protocol(value)


def test_selection_never_reads_evaluation_and_keeps_tradeoffs_and_equal_points():
    def point(name, cash, risk, refused):
        return {'phase': 'training', 'policy_id': name, 'eligible_for_training_selection': True,
                'mean_actual_energy_cash_CNY': cash, 'conservative_event_fraction': risk, 'refused_or_failed_fraction': refused}
    points = [point('lowrisk', 1, .01, 0), point('highcash', 2, .02, 0), point('dominated', .5, .02, .1), point('tied', 2, .02, 0)]
    assert F.select_training_frontier(points) == ['highcash', 'lowrisk', 'tied']
    points[0]['phase'] = 'evaluation'
    with pytest.raises(ValueError, match='cannot read evaluation'): F.select_training_frontier(points)


def test_partial_execution_and_unknown_remain_in_registered_denominator():
    rows = [{'phase': 'training', 'policy_id': 'p', 'complete_trace': True, 'terminal_pass': True,
             'trajectory_event': False, 'actual_energy_cash_CNY': 4., 'executed_seconds': 10., 'unserved_seconds': 0.},
            {'phase': 'training', 'policy_id': 'p', 'complete_trace': False, 'terminal_pass': None,
             'trajectory_event': True, 'actual_energy_cash_CNY': -1., 'executed_seconds': 5., 'unserved_seconds': 5.}]
    result = F.aggregate_cases('training', 'p', rows)
    assert result['registered_cases'] == 2 and result['complete_cases'] == 1
    assert result['mean_actual_energy_cash_CNY'] == 1.5
    assert result['conservative_event_fraction'] == result['refused_or_failed_fraction'] == .5
    assert result['whole_trajectory_event_fraction'] is None
    assert result['eligible_for_training_selection'] is False


def test_each_baseline_family_keeps_its_own_tuned_frontier_for_frozen_eval():
    base = {'phase': 'training', 'eligible_for_training_selection': True, 'conservative_event_fraction': 0., 'refused_or_failed_fraction': 0.}
    points = [{**base, 'policy_id': 'rule-high', 'policy_kind': 'rules', 'mean_actual_energy_cash_CNY': 3.},
              {**base, 'policy_id': 'rule-low', 'policy_kind': 'rules', 'mean_actual_energy_cash_CNY': 2.},
              {**base, 'policy_id': 'nominal-high', 'policy_kind': 'nominal', 'mean_actual_energy_cash_CNY': 1.},
              {**base, 'policy_id': 'nominal-low', 'policy_kind': 'nominal', 'mean_actual_energy_cash_CNY': .5}]
    assert F.select_training_frontier(points) == ['nominal-high', 'rule-high']


def test_public_cli_scans_actual_training_freezes_then_executes_paired_eval():
    token = uuid.uuid4().hex[:8]
    packet = ROOT/'artifacts/calibration'/('frontier-test-' + token)
    assert run_calibration(ROOT, ROOT/'tests/fixtures/calibration_builtin/request.json', packet)['exit_code'] == 0
    inputs = ROOT/'artifacts/baseline_frontier'/('test-input-' + token); inputs.mkdir(parents=True)
    source = inputs/'protocol.json'; source.write_text(json.dumps(protocol()), encoding='utf-8')
    out = ROOT/'artifacts/baseline_frontier'/('test-output-' + token)
    receipt = run_command([sys.executable, '-m', 'naheng.cli', 'baseline-frontier', '--input', str(source),
                           '--calibration-dir', str(packet), '--out', str(out)], ROOT, inputs/'cli.log', timeout=120)
    assert receipt['exit_code'] == 0 and not receipt['timed_out'], receipt['stdout']+receipt['stderr']
    result = json.loads((out/'result.json').read_text(encoding='utf-8'))
    freeze = json.loads((out/'freeze.json').read_text(encoding='utf-8'))
    assert result['workflow_complete'] and result['full_C01_complete'] is False
    assert freeze['evaluation_results_seen'] is False
    assert freeze['selected_policy_ids'] == F.select_training_frontier(freeze['training_points'])
    assert all('/training/' in path for path in freeze['training_case_manifests'])
    assert [r['policy_id'] for r in result['evaluation_points']] == [*freeze['selected_policy_ids'], 'scenario-comparator']
    assert len({v['run_id'] for v in result['cases']}) == len(result['cases'])
    for case in result['cases']:
        dest = ROOT/case['artifact_dir']
        actual = json.loads((dest/'result.json').read_text(encoding='utf-8'))
        ledger = json.loads((dest/'ledger.json').read_text(encoding='utf-8'))
        adoption = json.loads((dest/'adoption.json').read_text(encoding='utf-8'))
        assert actual['run_id'] == ledger['summary']['run_id'] == adoption['case_run_id']
        assert adoption['parent_joint_samples_weights_sha256'] == adoption['fork_joint_samples_weights_sha256']
        assert adoption['parent_rng_sha256'] == adoption['fork_rng_sha256']
        for index in range(2):
            assert json.loads((dest/f'sensor-{index}.json').read_text(encoding='utf-8'))['run_id'] == actual['run_id']
            assert json.loads((dest/f'posterior-{index}.json').read_text(encoding='utf-8'))['run_id'] == actual['run_id']
        assert case['actual_energy_cash_CNY'] == ledger['summary']['net_cashflow']
        assert actual['completed_sensor_replans'] == 2
        assert actual['steps'][1]['input_snapshot_id'] == actual['steps'][0]['next_snapshot_id']
        assert all(s['observer_updated'] and s['future_planned_actions_executed'] == 0 for s in actual['steps'])
        assert actual['independent_operational_trajectories'] == 0 and actual['risk_certificate'] is False
    assert (out/'points.csv').is_file() and '<table' in (out/'report.html').read_text(encoding='utf-8')
    with pytest.raises(FileExistsError): F.run_frontier(ROOT, packet, source, out)


def test_budget_not_started_cases_have_no_fabricated_worker_receipt(monkeypatch):
    token = uuid.uuid4().hex[:8]
    base = ROOT/'artifacts/baseline_frontier'/('budget-control-' + token); base.mkdir(parents=True)
    source = base/'protocol.json'; source.write_text(json.dumps(protocol()), encoding='utf-8')
    clock = iter([0., 200., 201., 202., 203., 204.])
    monkeypatch.setattr(F.time, 'monotonic', lambda: next(clock, 205.))
    def forbidden(*args, **kwargs): raise AssertionError('Expired budget cannot start a worker')
    monkeypatch.setattr(F, '_run_case', forbidden)
    summary = F.run_frontier(ROOT, ROOT/'artifacts/calibration/builtin-calibration-current-20261014-f', source, base/'out')
    result = json.loads((base/'out/result.json').read_text(encoding='utf-8'))
    assert summary['exit_code'] == 2 and summary['workflow_complete'] is False
    assert result['case_workers'] == 0 and result['registered_cases_accounted'] == 3
    assert all(v['status'] == 'registered_not_started' and v['receipt'] is None for v in result['cases'])
    assert all(v['registered_cases'] == 1 and v['refused_or_failed_fraction'] == 1 for v in result['training_points']+result['evaluation_points'])
    assert not list((base/'out').glob('cases/**/worker-command.json'))
