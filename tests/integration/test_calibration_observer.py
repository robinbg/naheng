"""A selected calibration may initialize a new observer, never a fake future sensor."""
import json
from pathlib import Path
import numpy as np
import pytest

from naheng.control.rules import RuleParameters, propose
from naheng.domain.contracts import Observation
from naheng.estimation.calibration_session import run_calibration
from naheng.estimation.particle_filter import particle_model
from naheng.runtime.calibration_consumer import _packet
from naheng.runtime.calibration_observer import fork_calibrated_observer
from naheng.runtime.artifacts import sha256_file

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def current_packet():
    import uuid
    out = ROOT / 'artifacts/calibration' / ('observer-test-' + uuid.uuid4().hex[:8])
    result = run_calibration(ROOT, ROOT / 'tests/fixtures/calibration_builtin/request.json', out)
    assert result['exit_code'] == 0
    return out


def test_fork_preserves_joint_distribution_and_requires_a_real_new_sensor(current_packet):
    before = {p.name: sha256_file(p) for p in current_packet.iterdir() if p.is_file()}
    observer, adoption = fork_calibrated_observer(ROOT, current_packet)
    loaded = _packet(ROOT, current_packet)
    snapshot = observer.snapshot
    assert adoption['samples_and_weights_preserved'] and snapshot.obs_until_s == 40
    assert adoption['future_sensor_assimilated'] is False
    assert snapshot.samples == loaded['snapshot'].samples and snapshot.weights == loaded['snapshot'].weights
    action = propose(snapshot, price=.30, start_s=40, duration_s=5,
                     parameters=RuleParameters(current_limit_A=.02))
    # Only the evaluator below sees this posterior draw and its internal state.
    index = int(np.random.default_rng(20261102).choice(len(snapshot.samples), p=snapshot.weights))
    row = np.asarray(snapshot.samples[index])
    plant = particle_model(loaded['model'], row[-2], row[-1])
    actual = plant.integrate(row[:5], action.current_A, action.duration_s, ambient_K=299.15, thermal_W=action.thermal_W)
    assert actual.elapsed_s == 5
    sensor = plant.observe(actual.state, action.current_A)
    observation = Observation(run_id=snapshot.run_id, timestamp_s=45, current_A=action.current_A,
                              voltage_V=sensor['voltage_V'], temperature_K=sensor['temperature_K'])
    next_snapshot = observer.update(observation, duration_s=5, ambient_K=299.15, thermal_W=action.thermal_W)
    assert next_snapshot.obs_until_s == 45 and next_snapshot.snapshot_id != snapshot.snapshot_id
    assert next_snapshot.parameter_revision == snapshot.parameter_revision
    assert observer.update_diagnostics[-1]['unique_forward_solves'] >= 1
    with pytest.raises(ValueError, match='timestamps must increase'):
        observer.update(observation, duration_s=5)
    assert before == {p.name: sha256_file(p) for p in current_packet.iterdir() if p.is_file()}
    assert loaded['snapshot'].obs_until_s == 40


def test_two_forks_are_independent_and_repeat_the_same_sensor_update(current_packet):
    first, _ = fork_calibrated_observer(ROOT, current_packet)
    second, _ = fork_calibrated_observer(ROOT, current_packet)
    assert first is not second and first.snapshot.model_dump() == second.snapshot.model_dump()
    before = second.export_checkpoint()
    model = first.model
    row = np.asarray(first.snapshot.samples[np.argmax(first.snapshot.weights)])
    plant = particle_model(model, row[-2], row[-1])
    actual = plant.integrate(row[:5], .02, 5, ambient_K=299.15)
    reading = plant.observe(actual.state, .02)
    sensor = Observation(run_id=first.run_id, timestamp_s=45, current_A=.02,
                         voltage_V=reading['voltage_V'], temperature_K=reading['temperature_K'])
    one = first.update(sensor, duration_s=5, ambient_K=299.15)
    assert second.export_checkpoint() == before
    two = second.update(sensor, duration_s=5, ambient_K=299.15)
    assert one.model_dump() == two.model_dump()


def test_new_observer_refuses_a_stale_packet_without_rewriting_it(current_packet):
    import copy, uuid
    from naheng.runtime.calibration_consumer import ConsumerUnknown
    dest = ROOT / 'artifacts/calibration' / ('observer-stale-' + uuid.uuid4().hex[:8])
    dest.mkdir()
    for original in current_packet.iterdir():
        if original.is_file(): (dest / original.name).write_bytes(original.read_bytes())
    manifest = json.loads((dest / 'manifest.json').read_text(encoding='utf-8'))
    manifest['code_hash'] = '0' * 64
    (dest / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    original = (dest / 'manifest.json').read_bytes()
    with pytest.raises(ConsumerUnknown, match='implementation differs'):
        fork_calibrated_observer(ROOT, dest)
    assert (dest / 'manifest.json').read_bytes() == original


@pytest.mark.parametrize('alternative', ['correlated', 'biased'])
def test_valid_other_likelihood_needs_its_own_observer(alternative):
    import uuid
    token = uuid.uuid4().hex[:8]
    source = ROOT / 'artifacts/calibration' / ('observer-input-' + token + '.json')
    body = json.loads((ROOT / 'tests/fixtures/calibration_builtin/request.json').read_text(encoding='utf-8'))
    if alternative == 'correlated':
        body['noise']['covariance'][0][1] = body['noise']['covariance'][1][0] = .003125
    else:
        body['noise']['bias'] = [.01, .02]
    body['noise']['assumption_text'] = 'Declared synthetic negative observer control: ' + alternative + ' total-error likelihood'
    source.write_text(json.dumps(body), encoding='utf-8')
    out = ROOT / 'artifacts/calibration' / ('observer-other-likelihood-' + token)
    assert run_calibration(ROOT, source, out)['exit_code'] == 0
    with pytest.raises(ValueError, match='different covariance or bias'):
        fork_calibrated_observer(ROOT, out)
