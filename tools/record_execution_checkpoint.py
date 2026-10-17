"""Record actual receipts without promoting unfinished task status."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid
import yaml
from naheng.runtime.artifacts import code_hash

ROOT = Path(__file__).resolve().parents[1]


def main():
    requested = Path(sys.argv[1]).resolve()
    assert requested.is_relative_to(ROOT / 'artifacts') and requested.is_file()
    update = json.loads(requested.read_text(encoding='utf-8'))
    tasks = yaml.safe_load((ROOT / 'TASKS.yaml').read_text(encoding='utf-8'))
    requirements_sha = hashlib.sha256((ROOT / 'REQUIREMENTS.yaml').read_bytes()).hexdigest()
    assert len(tasks['tasks']) == 45
    assert len(yaml.safe_load((ROOT / 'REQUIREMENTS.yaml').read_text(encoding='utf-8'))['requirements']) == 18
    rows = {t['id']: t for t in tasks['tasks']}
    original_status = {k: t['status'] for k, t in rows.items()}
    original_gates = {k: (t['depends_on'], t['acceptance'], t['validation_commands'], t['required']) for k, t in rows.items()}
    receipts = {}
    for task_id, summary in update['tasks'].items():
        assert task_id in rows
        for name in summary['evidence']:
            path = (ROOT / name).resolve()
            assert path.is_relative_to(ROOT) and path.is_file(), name
            item = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            if path.name == 'command.json':
                command = json.loads(path.read_text(encoding='utf-8'))
                terminal = command.get('status', 'completed')
                assert terminal in {'completed', 'passed'}
                if terminal == 'passed':
                    # The newer trusted validation runner records its actual
                    # terminal state as passed, rather than completed. Require
                    # its complete native/resource receipt; never rewrite it.
                    assert type(command.get('native_exit_code')) is int and command['native_exit_code'] == 0
                    assert command['exit_code'] == 0 and command['executed'] is True
                    assert command['timed_out'] is False and command['resource_cleanup_confirmed'] is True
                # CLI outcomes use 0/1/2, but native tools have their own real
                # codes (for example pytest usage errors are 4). Preserve them.
                # Both actual receipt producers are retained without rewriting:
                # run_owned_validation uses argv; validation_process uses command.
                native_argv = command.get('argv', command.get('command'))
                assert type(command['exit_code']) is int and isinstance(native_argv, list) and native_argv
                timing_field = 'wall_s' if 'wall_s' in command else 'elapsed_s'
                duration = command[timing_field]
                assert isinstance(duration, (int, float)) and duration >= 0
                item.update(exit_code=command['exit_code'], argv=native_argv,
                            wall_s=duration, source_timing_field=timing_field,
                            timed_out=command.get('timed_out', False))
            receipts[name] = item
    out = ROOT / 'artifacts/progress' / ('actual-checkpoint-' + uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    for name in ('TASKS.yaml', 'PLANS.md', 'docs/STATUS.md'):
        (out / Path(name).name).write_bytes((ROOT / name).read_bytes())
    (out / 'input.json').write_bytes(requested.read_bytes())
    for task_id, summary in update['tasks'].items():
        row = rows[task_id]
        for name in summary['evidence']:
            if name not in row.setdefault('evidence', []):
                row['evidence'].append(name)
        row['local_acceptance_scope'] = summary['scope']
        row['blocker'] = summary['blocker']
    tasks['status_note'] = update['status_note']
    assert original_status == {k: t['status'] for k, t in rows.items()}
    assert original_gates == {k: (t['depends_on'], t['acceptance'], t['validation_commands'], t['required']) for k, t in rows.items()}
    assert requirements_sha == hashlib.sha256((ROOT / 'REQUIREMENTS.yaml').read_bytes()).hexdigest()
    (ROOT / 'TASKS.yaml').write_text(yaml.safe_dump(tasks, allow_unicode=True, sort_keys=False), encoding='utf-8')
    timestamp = datetime.now(timezone.utc).isoformat()
    note = '## 实际执行检查点 ' + timestamp + '\n\n' + update['note'] + '\n\n'
    note += '记录：' + (out / 'checkpoint.json').relative_to(ROOT).as_posix() + '\n\n'
    note += '下一条具体执行命令（由 Codex 执行）：`' + update['next_command'] + '`\n\n'
    for name in ('PLANS.md', 'docs/STATUS.md'):
        path = ROOT / name
        path.write_text(note + path.read_text(encoding='utf-8'), encoding='utf-8')
    result = {'utc': timestamp, 'exit_code': 0, 'code_hash': code_hash(ROOT),
        'task_count': 45, 'requirement_count': 18, 'requirements_sha256': requirements_sha,
        'counts': dict(Counter(t['status'] for t in tasks['tasks'])),
        'unchanged_task_status_and_acceptance': True, 'receipts': receipts,
        'full_acceptance_complete': False}
    (out / 'checkpoint.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checkpoint': (out / 'checkpoint.json').relative_to(ROOT).as_posix(), 'exit_code': 0}))


if __name__ == '__main__':
    main()
