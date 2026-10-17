"""Public cohort refusal and experiment source identity in saved Runs."""
import json
from pathlib import Path
import uuid

import pytest
from naheng.runtime.artifacts import code_hash
from naheng.runtime.freezing import freeze_source
from naheng.runtime.public_sodium_session import run_public_data

ROOT = Path(__file__).resolve().parents[2]

def test_experiment_changes_invalidate_code_hash_and_are_frozen(tmp_path):
    (tmp_path / 'experiments').mkdir()
    source = tmp_path / 'experiments/public_sodium.py'
    source.write_text('value = 1\n', encoding='utf-8')
    before = code_hash(tmp_path)
    frozen, digest = freeze_source(tmp_path, tmp_path / 'run')
    assert digest == before
    assert (frozen / 'experiments/public_sodium.py').read_bytes() == source.read_bytes()
    source.write_text('value = 2\n', encoding='utf-8')
    assert code_hash(tmp_path) != before
    assert code_hash(frozen) == before

@pytest.mark.parametrize('output', ['artifacts', 'data/output', '../outside', 'artifacts/evaluator/new'])
def test_public_output_cannot_replace_protected_or_private_paths(output):
    with pytest.raises(ValueError, match='controlled experiment output'):
        run_public_data(ROOT, output=output)

def test_alternate_cohort_cannot_replace_frozen_role_assignment():
    out = ROOT / 'artifacts/public_validation' / ('refused-' + uuid.uuid4().hex[:8])
    with pytest.raises(ValueError, match='immutable public cohort'):
        run_public_data(ROOT, manifest='TASKS.yaml', output=out)
    assert not out.exists()

def test_existing_output_is_not_overwritten(tmp_path):
    # This directory is controlled and persistent; no worker is launched.
    out = ROOT / 'artifacts/public_validation' / ('existing-' + uuid.uuid4().hex[:8])
    out.mkdir(parents=True)
    marker = out / 'marker.txt'
    marker.write_text('preserve', encoding='utf-8')
    with pytest.raises(FileExistsError):
        run_public_data(ROOT, output=out)
    assert marker.read_text(encoding='utf-8') == 'preserve'
    assert not (out / 'execution').exists()

def test_default_output_parent_is_resolved_before_containment(tmp_path):
    config = json.loads((ROOT / 'configs/experiments/public-data-pilot-v1.json').read_bytes())
    config['default_output_parent'] = 'artifacts/../../escaped-default'
    config['default_manifest'] = 'cohort.json'
    cohort = tmp_path / 'cohort.json'
    cohort.write_text('{}', encoding='utf-8')
    from naheng.runtime.artifacts import sha256_file
    config['default_manifest_sha256'] = sha256_file(cohort)
    directory = tmp_path / 'configs/experiments'
    directory.mkdir(parents=True)
    (directory / 'public-data-pilot-v1.json').write_text(json.dumps(config), encoding='utf-8')
    with pytest.raises(ValueError, match='controlled experiment output'):
        run_public_data(tmp_path)
    assert not (tmp_path / 'artifacts').exists()

def test_truncated_worker_report_is_recorded_as_incomplete(tmp_path):
    # Actual tiny child/owned Job control, distinct from scientific-data runs.
    config = json.loads((ROOT / 'configs/experiments/public-data-pilot-v1.json').read_bytes())
    config['default_manifest'] = 'cohort.json'
    cohort = tmp_path / 'cohort.json'
    cohort.write_text('{}', encoding='utf-8')
    from naheng.runtime.artifacts import sha256_file
    config['default_manifest_sha256'] = sha256_file(cohort)
    directory = tmp_path / 'configs/experiments'
    directory.mkdir(parents=True)
    (directory / 'public-data-pilot-v1.json').write_text(json.dumps(config), encoding='utf-8')
    (tmp_path / 'experiments').mkdir()
    (tmp_path / 'experiments/public_sodium.py').write_text(
        "import pathlib, sys\np=pathlib.Path(sys.argv[-1]); p.mkdir(parents=True); "
        "(p/'report.json').write_text('{truncated')\nraise SystemExit(2)\n", encoding='utf-8')
    result = run_public_data(tmp_path, output='artifacts/partial')
    assert result['exit_code'] == 2 and result['execution_completed'] is False
    saved = json.loads((tmp_path / 'artifacts/partial/execution/command.json').read_bytes())
    assert saved['exit_code'] == 2 and saved['memory_limit_enforced'] is True
    assert saved['owned_pid'] > 0 and saved['report_error']
    aggregate = json.loads((tmp_path / 'artifacts/partial/manifest.json').read_bytes())
    assert aggregate['exit_code'] == 2 and not aggregate['D02_complete']
