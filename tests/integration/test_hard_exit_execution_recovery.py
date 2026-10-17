"""Actual child hard exit after integration must not restore an older boundary."""
import json
from pathlib import Path
import sys
import uuid

import pytest
import yaml
from naheng.formal.checker import run_command
from naheng.runtime.artifacts import sha256_file
from naheng.runtime.freezing import freeze_source
from naheng.runtime.jobs import JobStore
from naheng.runtime.recovery import load_recovery_checkpoint, config_digest
from naheng.runtime.resumption import prepare_recovery

ROOT = Path(__file__).resolve().parents[2]

def test_real_integrated_flow_survives_child_hard_exit_and_blocks_old_pointer():
    out = ROOT / 'artifacts/validation' / ('actual-hard-exit-' + uuid.uuid4().hex[:8])
    store = JobStore(out / 'runs')
    config = yaml.safe_load((ROOT / 'configs/scenarios/acceptance_loop.yaml').read_text(encoding='utf-8'))
    config.update(duration_s=5, step_s=5, filter_particles=8, forecast_paths=2, forecast_horizon_s=10)
    job = store.create(config)
    source, digest = freeze_source(ROOT, store.root / job['run_id'])
    store.bind_frozen_config(job['run_id'], {**config, 'source_dir': str(source), 'code_hash': digest})
    program = '''import os,sys
from pathlib import Path
project, source, store_root, run_id = sys.argv[1:]
sys.path.insert(0, str(Path(source)/'src'))
from naheng.runtime.runner import execute
from naheng.runtime.jobs import JobStore
from naheng.runtime.artifacts import atomic_json
import naheng.formal.inventory_check as inventory
original = inventory.check_sodium_interval
store = JobStore(Path(store_root))
def hard_exit_after_real_check(*args, **kwargs):
    actual = original(*args, **kwargs)
    assert actual['status'] == 'PASS'
    atomic_json(store.root/run_id/'actual-preexit-check.json', actual)
    os._exit(7)
inventory.check_sodium_interval = hard_exit_after_real_check
execute(Path(project), store, run_id)
'''
    receipt = run_command([sys.executable, '-c', program, str(ROOT), str(source), str(store.root), job['run_id']],
                          ROOT, out / 'actual-hard-exit-worker.log', timeout=120)
    assert receipt['exit_code'] == 7 and not receipt['timed_out']
    dest = store.root / job['run_id']
    ledger = json.loads((dest / 'executed_ledger.json').read_bytes())
    actual = json.loads((store.root / 'evaluator' / job['run_id'] / 'execution-0.json').read_bytes())
    assert json.loads((dest / 'actual-preexit-check.json').read_bytes())['status'] == 'PASS'
    assert len(ledger['entries']) == 1 and ledger['entries'][0]['executed']
    assert ledger['entries'][0]['energy_J'] == actual['energy_J'] != 0
    assert ledger['entries'][0]['duration_s'] == actual['elapsed_s'] == 5
    old = json.loads((dest / 'checkpoint.json').read_bytes())
    assert old['step'] == 0 and old['recoverable'] is True
    assert not any(e.get('type') == 'unassimilated_execution' for e in store.events(job['run_id']))
    assert any(e.get('type') == 'execution_started' for e in store.events(job['run_id']))
    assert store.get(job['run_id'])['state'] == 'running'
    assert store.recover_interrupted() == 1
    assert store.get(job['run_id'])['state'] == 'interrupted'
    with pytest.raises(ValueError, match='Uncheckpointed execution intent'):
        prepare_recovery(ROOT, store, job['run_id'])
    with pytest.raises(ValueError, match='Uncheckpointed execution intent'):
        load_recovery_checkpoint(store, job['run_id'], expected_code_hash=digest,
            expected_lock_hash=sha256_file(source / 'uv.lock'), expected_input_hash=config_digest(config),
            new_run_id='explicit-old-hard-exit-pointer', checkpoint=old)
    assert len(store.list()) == 1
