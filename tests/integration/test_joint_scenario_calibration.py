"""Public correlated-sensor loop, genuine artifacts and independent Bayes."""

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

import hashlib
import json
import math
from pathlib import Path
import sys
import uuid
import pytest

from naheng.estimation.calibration_session import run_calibration
from naheng.formal.checker import run_command
from naheng.runtime.joint_scenario_calibration import run_joint_scenario

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope='module')
def current_packet():
    out = ROOT / 'artifacts/calibration' / ('joint-loop-input-' + uuid.uuid4().hex[:8])
    result = run_calibration(ROOT, ROOT / 'tests/fixtures/calibration_builtin/request_joint_gaussian.json', out)
    assert result['exit_code'] == 0
    return out


def test_public_cli_replans_from_actual_correlated_biased_sensors(current_packet):
    out = ROOT / 'artifacts/joint_scenario_calibration' / ('public-loop-test-' + uuid.uuid4().hex[:8])
    log = ROOT / 'artifacts/validation' / ('joint-cli-test-' + uuid.uuid4().hex[:8]) / 'cli.log'
    original_packet = {p.name: sha(p) for p in current_packet.iterdir() if p.is_file()}
    command = [sys.executable, '-m', 'naheng.cli', 'joint-scenario-calibration',
               '--calibration-dir', str(current_packet), '--out', str(out)]
    actual = run_command(command, ROOT, log, timeout=150)
    assert actual['exit_code'] == 0 and not actual['timed_out']
    result, registration, ledger = (read(out / name) for name in ('result.json', 'registration.json', 'ledger.json'))
    assert result['completed_sensor_replans'] == 2 and result['exit_code'] == 0
    assert result['risk_certificate'] is False and result['independent_operational_trajectories'] == 0
    assert result['scientific_profit_comparability'] is False
    assert all(row['source_and_packet_unchanged'] for row in result['source_verification_boundaries'])
    assert original_packet == {p.name: sha(p) for p in current_packet.iterdir() if p.is_file()}
    covariance, bias = registration['noise']['covariance'], registration['noise']['bias']
    assert covariance[0][1] != 0 and any(bias)
    a, b, c = covariance[0][0], covariance[0][1], covariance[1][1]
    determinant = a * c - b * b
    assert determinant > 0
    parent = read(current_packet / 'result.json')['calibration']['posterior_contract']
    for index, step in enumerate(result['steps']):
        sensor, posterior, diagnostic, execution = (read(out / f'{name}-{index}.json') for name in
            ('sensor', 'posterior', 'observer-diagnostics', 'evaluator/execution'))
        assert sensor['run_id'] == posterior['run_id'] == ledger['entries'][index]['run_id'] == result['run_id']
        assert sensor['timestamp_s'] == parent['obs_until_s'] + execution['elapsed_s'] == posterior['obs_until_s']
        assert step['observer_updated'] and step['next_snapshot_id'] == posterior['snapshot_id']
        assert all(step['actual_constraint_checks'].values()) and step['future_planned_actions_executed'] == 0
        assert diagnostic['prior_weights'] == parent['weights']
        assert len(diagnostic['predictions']) == diagnostic['represented_forward_solves'] == len(parent['samples'])
        scores = []
        for prediction in diagnostic['predictions']:
            r0, r1 = sensor['voltage_V'] - prediction[0] - bias[0], sensor['temperature_K'] - prediction[1] - bias[1]
            # Independently invert the scalar 2x2 covariance; do not call the
            # production Gaussian fit, observer or matrix solve.
            scores.append(-.5 * (c*r0*r0 - 2*b*r0*r1 + a*r1*r1) / determinant)
        supported = [math.log(w) + score if w > 0 else -math.inf
                     for w, score in zip(parent['weights'], scores)]
        peak = max(supported)
        raw = [math.exp(v - peak) if math.isfinite(v) else 0. for v in supported]
        expected = [v/sum(raw) for v in raw]
        assert posterior['weights'] == pytest.approx(expected, rel=1e-10, abs=1e-13)
        assert posterior['ess'] == pytest.approx(1/sum(w*w for w in expected), rel=1e-10)
        assert all(after[-2:] == before[-2:] for after, before in zip(posterior['samples'], parent['samples']))
        assert ledger['entries'][index]['energy_J'] == execution['energy_J']
        assert ledger['entries'][index]['duration_s'] == execution['elapsed_s']
        if index:
            assert step['input_snapshot_id'] == parent['snapshot_id']
        parent = posterior
    assert len(ledger['entries']) == 2 and ledger['forecast_energy_booked'] is False
    assert ledger['terminal_value_booked'] is False
    assert read(out / 'worker-command.json')['exit_code'] == read(out / 'manifest.json')['exit_code'] == 0
    with pytest.raises(FileExistsError):
        run_joint_scenario(ROOT, current_packet, out)


@pytest.mark.parametrize('packet,out', [
    ('artifacts/evaluator/calibration', 'artifacts/joint_scenario_calibration/unused'),
    ('artifacts/calibration/unused', 'artifacts/evaluator/unused'),
    ('artifacts/calibration/unused', 'docs/unused-output'),
])
def test_joint_public_entry_rejects_private_or_uncontrolled_paths(packet, out):
    with pytest.raises(ValueError):
        run_joint_scenario(ROOT, ROOT / packet, ROOT / out)
