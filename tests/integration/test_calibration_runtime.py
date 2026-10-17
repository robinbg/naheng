"""Actual builtin dynamics, source identity, units and worker regressions."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from naheng.estimation.calibration import FrozenPosterior
from naheng.estimation.calibration_session import (
    CalibrationRequest, FileRef, _file, analyze_calibration, run_calibration,
    verify_builtin_forward,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/calibration_builtin'


@pytest.fixture
def bound_input(tmp_path):
    manifest = json.loads((FIXTURE / 'manifest.json').read_text(encoding='utf-8'))
    for name, record in manifest['files'].items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == record['sha256']
    body = json.loads((FIXTURE / 'request.json').read_text(encoding='utf-8'))
    files = {'sensor-source.json': body['training_source']['path'],
             'forward.json': body['batch']['propagation_evidence']['source_ref']}
    for fixture_name, rel in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE / fixture_name, target)
    for rel in body['model_package']['binding_hashes']:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    return tmp_path, body


def request(body):
    return CalibrationRequest.model_validate_json(json.dumps(body))


def test_actual_builtin_forward_updates_one_joint_candidate_without_mutating_prior(bound_input):
    root, body = bound_input
    value = request(body)
    original = value.prior.model_dump_json()
    result = analyze_calibration(root, value)
    assert result['exit_code'] == 0
    assert result['integration_verification']['actual_parent_forward_predictions_recomputed']
    posterior = result['calibration']['candidate']['posterior']
    assert posterior['obs_until_s'] == 40
    assert posterior['snapshot_id'] != value.prior.snapshot_id
    assert posterior['state_units'] == list(value.prior.state_units)
    assert posterior['weights'] != list(value.prior.weights)
    assert all(row[-2:] == list(old[-2:]) for row, old in zip(posterior['samples'], value.prior.samples))
    assert value.prior.model_dump_json() == original
    assert result['existing_run_or_filter_modified'] is False
    assert result['independent_experiment'] is False


def test_relabelled_units_are_rejected_even_with_rebound_parent_hash(bound_input):
    root, body = bound_input
    body['prior']['state_units'][0] = 'V'
    changed = FrozenPosterior.model_validate_json(json.dumps(body['prior']))
    body['batch']['posterior_content_sha256'] = changed.content_sha256
    body['batch']['propagation_evidence']['parent_content_sha256'] = changed.content_sha256
    with pytest.raises(ValueError, match='state units'):
        analyze_calibration(root, request(body))


@pytest.mark.parametrize('field', ['prediction', 'end-state', 'soc'])
def test_caller_arrays_are_recomputed_not_trusted(bound_input, field):
    root, body = bound_input
    if field == 'prediction':
        body['batch']['particle_predictions'][0][0][0] += .2
    elif field == 'end-state':
        body['batch']['propagated_joint_samples'][0][0] += .02
    else:
        body['batch']['propagated_derived_observables'][0]['particle_values'][0] += .02
    with pytest.raises(ValueError, match='actual builtin forward|SOC'):
        analyze_calibration(root, request(body))


@pytest.mark.parametrize('label', ['evaluator', 'Evaluator', 'EVALUATOR'])
def test_evaluator_directory_is_rejected_with_windows_case_variants(tmp_path, label):
    source = tmp_path / 'artifacts' / label / 'sensor.json'
    source.parent.mkdir(parents=True)
    source.write_text('{}', encoding='utf-8')
    ref = FileRef(path=str(source.relative_to(tmp_path)), sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='controlled public'):
        _file(tmp_path, ref, 'artifacts')


def test_registered_descriptor_omission_is_preserved_and_added_defaults_do_not_bypass_hash(bound_input):
    root, body = bound_input
    assert 'schema_version' not in body['model_package']
    assert verify_builtin_forward(root, request(body))['status'] == 'PASS'
    body['model_package']['schema_version'] = 1
    with pytest.raises(ValueError, match='content hash mismatch'):
        verify_builtin_forward(root, request(body))


@pytest.mark.parametrize('label', ['evaluator', 'Evaluator', 'EVALUATOR'])
def test_extra_model_source_binding_cannot_read_private_evaluator(bound_input, label):
    root, body = bound_input
    source = root / 'artifacts' / label / 'synthetic-probe.txt'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('synthetic negative control, no private truth', encoding='utf-8')
    original_package_hash = body['model_package']['package_hash']
    body['model_package']['binding_hashes'][str(source.relative_to(root))] = hashlib.sha256(source.read_bytes()).hexdigest()
    assert body['model_package']['package_hash'] == original_package_hash
    with pytest.raises(ValueError, match='controlled source'):
        verify_builtin_forward(root, request(body))


def test_budget_expiration_before_nominal_solve_stops_without_a_candidate(bound_input, monkeypatch):
    from naheng.estimation import calibration_session
    root, body = bound_input
    ticks = iter([0.] * 9 + [101.])  # start + 8 actual parent solves, then nominal boundary
    monkeypatch.setattr(calibration_session.time, 'monotonic', lambda: next(ticks, 101.))
    with pytest.raises(TimeoutError, match='before nominal solve'):
        analyze_calibration(root, request(body))


def test_owned_worker_saves_actual_result_and_preserves_existing_output(bound_input):
    root, body = bound_input
    source = root / 'input.json'
    source.write_text(json.dumps(body), encoding='utf-8')
    out = root / 'artifacts/session'
    result = run_calibration(root, source, out)
    assert result['exit_code'] == 0 and result['complete'] is True
    manifest = (out / 'manifest.json').read_bytes()
    record = json.loads((out / 'worker-command.json').read_text(encoding='utf-8'))
    saved = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    assert record['exit_code'] == 0 and record['timed_out'] is False
    assert saved['integration_verification']['same_particle_SOC_recomputed']
    assert (out / 'input.json').read_bytes() == source.read_bytes()
    with pytest.raises(FileExistsError):
        run_calibration(root, source, out)
    assert (out / 'manifest.json').read_bytes() == manifest
