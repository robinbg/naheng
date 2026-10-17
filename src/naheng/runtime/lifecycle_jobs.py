"""Durable lifecycle workbench jobs; frozen inputs, owned workers and real artifacts."""
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .artifacts import atomic_json, code_hash, sha256_file
from .jobs import JobStore, TERMINAL
from .process_tree import ProcessTree


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def source_run(store, run_id):
    row = store.get(run_id)
    if row['config'].get('task_kind') != 'lifecycle-finance':
        raise ValueError('Not a lifecycle finance job')
    source = row['config'].get('replay_source', run_id)
    original = store.get(source)
    if original['config'].get('task_kind') != 'lifecycle-finance':
        raise ValueError('Lifecycle replay source mismatch')
    return row, original, store.root / source


def read_lifecycle_result(store, run_id):
    row, original, dest = source_run(store, run_id)
    if row['state'] not in TERMINAL:
        raise ValueError('Lifecycle result is still running')
    manifest = _read(dest / 'manifest.json')
    path = dest / 'result.json'
    if sha256_file(path) != manifest['artifact_sha256']['result']:
        raise ValueError('Lifecycle result artifact checksum changed')
    result = _read(path)
    if result['source_run_id'] != original['run_id'] or result['code_hash'] != original['config']['code_hash']:
        raise ValueError('Lifecycle result source identity mismatch')
    if manifest['code_hash'] != result['code_hash'] or code_hash(Path(original['config']['source_dir'])) != result['code_hash']:
        raise ValueError('Lifecycle frozen source changed')
    for case in result['cases']:
        if not case['valid_execution']: continue
        report = (store.root.parent.parent / case['report_path']).resolve()
        receipt = (store.root.parent.parent / case['receipt']).resolve()
        if not report.is_relative_to((dest/'experiment').resolve()) or not receipt.is_relative_to((dest/'experiment').resolve()):
            raise ValueError('Lifecycle case evidence path changed')
        if sha256_file(report)!=case['report_sha256'] or sha256_file(receipt)!=case['receipt_sha256']:
            raise ValueError('Lifecycle case receipt checksum changed')
        for name, sha in case['execution']['artifacts'].items():
            if Path(name).name!=name or sha256_file(report.parent/name)!=sha:
                raise ValueError('Lifecycle case result checksum changed')
    return {**result, 'display_run_id': run_id, 'mode': row['config']['mode'],
            'reused_from': row['config'].get('replay_source'), 'job_state':row['state'],
            'run_complete':row['state']=='succeeded' and manifest['complete'], 'independent_sample': False}


def public_packet(root, experiment, run_id, mode, parameters):
    """Adopt authenticated saved reports, never fabricate a result from a fixture."""
    root, experiment = Path(root), Path(experiment)
    manifest = _read(experiment / 'manifest.json')
    for name, sha in manifest['artifacts'].items():
        if Path(name).name != name or sha256_file(experiment / name) != sha:
            raise ValueError('Lifecycle experiment artifact checksum changed')
    registration = _read(experiment / 'registration.json')
    if sha256_file(experiment / 'registration.json') != manifest['registration_sha256']:
        raise ValueError('Lifecycle registration checksum changed')
    from .lifecycle_finance_session import adopt_worker_report
    cases = []
    for item in manifest['receipts']:
        case = {**item, 'finance': None, 'endpoints': None, 'execution': None}
        if item['valid_execution']:
            report_path = (root / item['report_path']).resolve()
            receipt_path = (root / item['receipt']).resolve()
            if not report_path.is_relative_to(experiment.resolve()) or not receipt_path.is_relative_to(experiment.resolve()):
                raise ValueError('Lifecycle evidence path outside owned experiment')
            report = adopt_worker_report(report_path.parent, root=root, digest=manifest['code_hash'],
                registered_sha=manifest['registration_sha256'], case_id=item['case_id'], policy_id=item['policy_id'],
                mode=item['mode'], child_code=_read(receipt_path)['exit_code'])
            case.update(finance=_read(report_path.parent / 'finance.json'),
                        endpoints=_read(report_path.parent / 'endpoints.json'), execution=report,
                        report_sha256=sha256_file(report_path),receipt_sha256=sha256_file(receipt_path))
        cases.append(case)
    return {'schema_version': 1, 'source_run_id': run_id, 'mode': mode, 'code_hash': manifest['code_hash'],
            'provenance_type': 'synthetic', 'parameters': parameters, 'registration_sha256': manifest['registration_sha256'],
            'registration': registration, 'experiment_manifest': manifest,
            'frontier': _read(experiment / 'frontier.json'), 'cases': cases,
            'independent_sample': False, 'independent_operating_n': 0,
            'real_income_claim': False, 'scope': manifest['scope']}


def render_report(packet):
    """Export the same persisted financial and source data that the UI displays."""
    rows = []
    for case in packet['cases']:
        f = case['finance'] or {}
        rows.append('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in (
            case['mode'], case['policy_id'], case['case_id'], case['valid_execution'],
            f.get('realized_cash_CNY'), f.get('conditional_comparison_value_CNY'), case['adoption_error']))+'</tr>')
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>钠衡生命周期运行报告</title>'
        '<style>body{max-width:1100px;margin:32px auto;font:16px sans-serif}td,th{padding:8px;border:1px solid #bbb}'
        'table{border-collapse:collapse}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
        '<h1>钠衡生命周期运行报告</h1><p>RunID: '+html.escape(packet['source_run_id'])+'</p>'
        '<p>作业状态: '+html.escape(str(packet.get('job_state')))+'；完整运行: '+str(packet.get('run_complete'))+
        '；未完成原因: '+html.escape(str(packet.get('failure_reason')))+'</p>'
        '<p>合成模型、合成电价；实际执行现金流、条件终值、宏步预测分别记录。未知寿命和运营概率不补零，运营独立 N=0。</p>'
        '<p>代码: '+html.escape(packet['code_hash'])+'</p><table><tr><th>模式</th><th>策略</th><th>案例</th>'
        '<th>真实执行完成</th><th>实际现金 CNY</th><th>条件比较 CNY</th><th>缺失原因</th></tr>'+''.join(rows)+'</table>'
        '<details><summary>完整来源、前沿与逐资产终端核算</summary><pre>'+html.escape(json.dumps(packet, ensure_ascii=False, indent=2))+'</pre></details></html>')


def finalize_lifecycle_job(store, run_id, dest, packet, manifest):
    """Serialize cancel and publication with the same authoritative job transaction."""
    with store.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row=store._row(connection,run_id)
        if row['state'] in TERMINAL: raise ValueError('Terminal lifecycle work cannot republish')
        cancelled=bool(row['cancel'])
        complete=manifest['exit_code']==0 and not cancelled
        state='cancelled' if cancelled else 'succeeded' if complete else 'failed'
        reason='Cancelled; partial cases retained' if cancelled else None if complete else 'Required lifecycle cases incomplete or source invalid'
        manifest.update(complete=complete,exit_code=0 if complete else 2,failure_reason=reason)
        packet.update(job_state=state,run_complete=complete,failure_reason=reason)
        atomic_json(dest/'result.json',packet)
        (dest/'report.html').write_text(render_report(packet),encoding='utf-8')
        manifest['artifact_sha256']={key:sha256_file(dest/name) for key,name in manifest['artifact_index'].items()}
        atomic_json(dest/'manifest.json',manifest)
        connection.execute('UPDATE jobs SET state=?,progress=?,error=?,updated=? WHERE run_id=?',
                (state,1 if complete else row['progress'],reason,store.now(),run_id))
        store._event(connection,run_id,{'type':state,'progress':1 if complete else row['progress'],'error':reason,
                     'artifact_sha256':manifest['artifact_sha256'],'source_code_hash':manifest['code_hash']})
    return manifest['exit_code']


def execute_lifecycle_job(root, store, run_id):
    root = Path(root).resolve()
    if not store.try_start(run_id, owner_pid=os.getpid()):
        return 2
    started = time.monotonic()
    job = store.get(run_id)
    dest = store.root / run_id
    try:
        config = job['config']
        source = Path(config['source_dir']).resolve()
        if config['task_kind'] != 'lifecycle-finance' or source != (dest/'source_snapshot').resolve():
            raise ValueError('Owned frozen lifecycle source required')
        if code_hash(source) != config['code_hash']:
            raise ValueError('Frozen lifecycle source changed')
        from .lifecycle_finance_session import run_lifecycle_finance
        def on_case(count, item):
            store.event(run_id, {'type': 'lifecycle_case', 'completed_cases': count, 'total_cases': 8, **item})
            if not store.get(run_id)['cancel']:
                store.state(run_id, 'running', progress=count/8)
        result = run_lifecycle_finance(root, (dest/'experiment').relative_to(root), source=source,
                parameters=config['parameters'], cancelled=lambda:bool(store.get(run_id)['cancel']), on_case=on_case)
        packet = public_packet(root, dest/'experiment', run_id, config['mode'], config['parameters'])
        (dest/'points.csv').write_bytes((dest/'experiment/points.csv').read_bytes())
        manifest = {'run_id': run_id, 'experiment_id': run_id, 'role': 'engineering', 'mode': config['mode'],
            'provenance_type': 'synthetic', 'code_hash': config['code_hash'],
            'independent_sample': False, 'independent_operating_n': 0, 'real_income_claim': False,
            'dependency_lock_hash': sha256_file(source/'uv.lock'), 'input_hash': job['input_hash'],
            'registration_sha256': packet['registration_sha256'], 'wall_s': time.monotonic()-started,
            'utc': datetime.now(timezone.utc).isoformat(), 'exit_code': result['exit_code'],
            'artifact_index': {'report':'report.html','result':'result.json','points':'points.csv'}}
        return finalize_lifecycle_job(store,run_id,dest,packet,manifest)
    except Exception as error:
        atomic_json(dest/'failure.json', {'run_id': run_id, 'code_hash': job['config'].get('code_hash'),
                    'exit_code': 2, 'error': repr(error), 'wall_s':time.monotonic()-started, 'complete':False})
        if (dest/'manifest.json').is_file():
            failure_manifest=_read(dest/'manifest.json')
            failure_manifest.update(complete=False,exit_code=2,failure_reason=str(error))
            atomic_json(dest/'manifest.json',failure_manifest)
        store.state(run_id, 'cancelled' if store.get(run_id)['cancel'] else 'failed', error=str(error))
        return 2


def spawn_lifecycle_job(root, store, run_id):
    config = store.get(run_id)['config']
    log_path = store.root/run_id/'worker.log'
    with log_path.open('ab') as log:
        proc = subprocess.Popen([sys.executable, '-m', 'naheng.runtime.lifecycle_jobs', str(root), run_id], cwd=root,
            stdout=log, stderr=log, env={**os.environ, 'PYTHONPATH':str(Path(config['source_dir'])/'src'),
                'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'},
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    store.bind_worker_owner(run_id, proc.pid)
    return proc


def monitor_lifecycle_job(proc, store, run_id, timeout_s=960):
    tree = ProcessTree(proc)
    started = time.monotonic()
    try:
        while proc.poll() is None and time.monotonic()-started < timeout_s:
            time.sleep(.2)
        if proc.poll() is None:
            store.event(run_id, {'type':'owned_lifecycle_tree_stop', 'timeout_s':timeout_s, **tree.terminate()})
            proc.wait(timeout=15)
        store.event(run_id, {'type':'lifecycle_worker_exit','exit_code':proc.returncode,'wall_s':time.monotonic()-started})
        current = store.get(run_id)
        if current['state'] not in TERMINAL:
            store.state(run_id, 'cancelled' if current['cancel'] else 'failed',
                        error='Lifecycle worker exited without authenticated terminal publication')
    finally:
        tree.close()


if __name__ == '__main__':
    project = Path(sys.argv[1])
    raise SystemExit(execute_lifecycle_job(project, JobStore(project/'artifacts/runs'), sys.argv[2]))
