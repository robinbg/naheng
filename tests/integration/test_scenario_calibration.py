"""Actual public two-cycle flow and persistence of an executed partial failure."""
import json
from pathlib import Path
import uuid
import pytest

from naheng.estimation.calibration_session import run_calibration
from naheng.runtime.scenario_calibration import run_scenario
from naheng.runtime import scenario_calibration as S

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def current_packet():
    out = ROOT / 'artifacts/calibration' / ('scenario-loop-input-' + uuid.uuid4().hex[:8])
    assert run_calibration(ROOT, ROOT / 'tests/fixtures/calibration_builtin/request.json', out)['exit_code'] == 0
    return out


def test_owned_two_cycle_loop_replans_only_after_actual_new_sensors(current_packet):
    out = ROOT / 'artifacts/scenario_calibration' / ('loop-test-' + uuid.uuid4().hex[:8])
    summary = run_scenario(ROOT, current_packet, out)
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    assert summary['exit_code'] == 0 and summary['completed_sensor_replans'] == 2
    assert [s['sensor_timestamp_s'] for s in result['steps']] == [45, 50]
    assert result['steps'][1]['input_snapshot_id'] == result['steps'][0]['next_snapshot_id']
    assert all(s['future_planned_actions_executed'] == 0 and s['observer_updated'] for s in result['steps'])
    assert result['risk_certificate'] is False and result['independent_experiment'] is False
    ledger = json.loads((out / 'ledger.json').read_text(encoding='utf-8'))
    assert len(ledger['entries']) == 2 and ledger['forecast_energy_booked'] is False
    for i, step in enumerate(result['steps']):
        execution = json.loads((out / f'evaluator/execution-{i}.json').read_text(encoding='utf-8'))
        assert step['ledger_entry']['energy_J'] == execution['energy_J']
        assert step['ledger_entry']['duration_s'] == execution['elapsed_s']
    with pytest.raises(FileExistsError):
        run_scenario(ROOT, current_packet, out)


def test_executed_energy_survives_a_following_sensor_update_failure(current_packet, monkeypatch):
    original = S.fork_calibrated_observer
    class RefusedSensor:
        def __init__(self, observer): self.observer = observer
        @property
        def snapshot(self): return self.observer.snapshot
        def update(self, *args, **kwargs): raise ValueError('Synthetic test: actual sensor update refused')
    def failure(root, packet):
        observer, record = original(root, packet)
        return RefusedSensor(observer), record
    monkeypatch.setattr(S, 'fork_calibrated_observer', failure)
    out = ROOT / 'artifacts/scenario_calibration' / ('failed-update-' + uuid.uuid4().hex[:8])
    out.mkdir(parents=True)
    assert S._worker(ROOT, current_packet, out) == 1
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    ledger = json.loads((out / 'ledger.json').read_text(encoding='utf-8'))
    execution = json.loads((out / 'evaluator/execution-0.json').read_text(encoding='utf-8'))
    assert result['completed_sensor_replans'] == 0 and len(result['steps']) == 1
    assert result['steps'][0]['observer_updated'] is False and result['steps'][0]['next_snapshot_id'] is None
    assert len(ledger['entries']) == 1 and ledger['entries'][0]['executed'] is True
    assert ledger['entries'][0]['energy_J'] == execution['energy_J'] != 0
    assert result['steps'][0]['ledger_entry'] == ledger['entries'][0]
