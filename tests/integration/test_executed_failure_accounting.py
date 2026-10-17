"""Actual synthetic integration survives a later injected checking failure."""
import json
from pathlib import Path
import uuid
import sys

import pytest
import yaml
from naheng.runtime.freezing import freeze_source
from naheng.runtime.jobs import JobStore
from naheng.runtime.resumption import prepare_recovery
from naheng.runtime.recovery import load_recovery_checkpoint, config_digest
from naheng.runtime.artifacts import sha256_file
from naheng.formal.checker import run_command

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.parametrize('checkpoint_write_fails', [False, True])
def test_actual_energy_is_saved_and_unassimilated_interval_cannot_resume(checkpoint_write_fails):
    out = ROOT / 'artifacts/validation' / ('actual-check-failure-' + uuid.uuid4().hex[:8])
    store = JobStore(out / 'runs')
    config = yaml.safe_load((ROOT / 'configs/scenarios/acceptance_loop.yaml').read_text(encoding='utf-8'))
    config.update(duration_s=5, step_s=5, filter_particles=8, forecast_paths=2, forecast_horizon_s=10)
    job = store.create(config)
    source, digest = freeze_source(ROOT, store.root / job['run_id'])
    store.bind_frozen_config(job['run_id'], {**config, 'source_dir': str(source), 'code_hash': digest})
    # Load the actually frozen implementation in a separate owned worker, as
    # production dispatch does. The first fixture used a current-root import
    # against a frozen-root package and was correctly rejected before execution.
    program = '''import sys, json
from pathlib import Path
project, source, store_root, run_id, fail_checkpoint = sys.argv[1:]
sys.path.insert(0, str(Path(source)/'src'))
from naheng.runtime.runner import execute
from naheng.runtime.jobs import JobStore
from naheng.runtime.artifacts import atomic_json
import naheng.formal.inventory_check as inventory
import naheng.runtime.publication as publication
original = inventory.check_sodium_interval
store = JobStore(Path(store_root))
if fail_checkpoint == 'True':
    original_write = publication.atomic_json
    def fail_checkpoint_write(path, value):
        if path.name == 'checkpoint.json':
            raise OSError('Injected checkpoint-file invalidation failure')
        return original_write(path, value)
    publication.atomic_json = fail_checkpoint_write
def injected_after_real_check(*args, **kwargs):
    actual = original(*args, **kwargs)
    assert actual['status'] == 'PASS'
    atomic_json(store.root/run_id/'actual-preinjection-check.json', actual)
    atomic_json(store.root/run_id/'previous-recoverable-pointer.json',
        json.loads((store.root/run_id/'checkpoint.json').read_bytes()))
    return {**actual, 'status': 'FAIL', 'scope': 'Injected later review failure; real inventory check passed'}
inventory.check_sodium_interval = injected_after_real_check
try:
    execute(Path(project), store, run_id)
except ValueError as error:
    assert 'inventory consistency' in str(error), str(error)
    print(json.dumps({'expected_failure': str(error), 'scope': 'Actual synthetic integration followed by injected review failure'}))
else:
    raise AssertionError('The injected later check must fail')
'''
    receipt = run_command([sys.executable, '-c', program, str(ROOT), str(source), str(store.root), job['run_id'], str(checkpoint_write_fails)],
                          ROOT, out / 'actual-worker.log', timeout=120)
    assert receipt['exit_code'] == 0 and not receipt['timed_out'], receipt['stdout'] + receipt['stderr']
    dest = store.root / job['run_id']
    saved = json.loads((dest / 'executed_ledger.json').read_bytes())
    actual = json.loads((store.root / 'evaluator' / job['run_id'] / 'execution-0.json').read_bytes())
    check = json.loads((dest / 'actual-preinjection-check.json').read_bytes())
    assert check['status'] == 'PASS' and len(saved['entries']) == 1
    entry = saved['entries'][0]
    assert entry['executed'] is True and entry['duration_s'] == actual['elapsed_s'] == 5
    assert entry['energy_J'] == actual['energy_J'] != 0
    assert entry['thermal_electric_energy_J'] == actual['thermal_management_energy_J']
    assert saved['forecast_energy_booked'] is False and saved['terminal_value_booked'] is False
    checkpoint = json.loads((dest / 'checkpoint.json').read_bytes())
    assert not checkpoint['complete'] and checkpoint['step'] == 0
    if checkpoint_write_fails:
        assert checkpoint['recoverable'] is True
        assert any(e.get('type') == 'artifact_invalidation_error' and e.get('artifact') == 'checkpoint.json'
                   for e in store.events(job['run_id']))
    else:
        assert not checkpoint['recoverable'] and checkpoint['unassimilated_execution'] is True
    assert any(e.get('type') == 'unassimilated_execution' for e in store.events(job['run_id']))
    assert store.get(job['run_id'])['state'] == 'failed'
    with pytest.raises(ValueError, match='Unassimilated actual execution'):
        prepare_recovery(ROOT, store, job['run_id'])
    old = json.loads((dest / 'previous-recoverable-pointer.json').read_bytes())
    assert old['recoverable'] is True
    with pytest.raises(ValueError, match='Unassimilated actual execution'):
        load_recovery_checkpoint(store, job['run_id'], expected_code_hash=digest,
            expected_lock_hash=sha256_file(source / 'uv.lock'), expected_input_hash=config_digest(config),
            new_run_id='old-pointer-retry', checkpoint=old)
    assert len(store.list()) == 1
