"""Frozen, bounded lifecycle executions and a same-protocol finite-case frontier."""
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import ctypes
from ctypes import wintypes
import hashlib
import html
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from naheng.economics.lifecycle import FinancialAssumptions
from naheng.economics.pareto import ComparisonContext, CaseOutcome, PolicyOutcome, pareto_frontier
from .artifacts import atomic_json, code_hash, sha256_file
from .freezing import freeze_source
from .public_sodium_session import ExtendedLimits


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _worker(argv, *, root, frozen, execution, cancelled=None):
    """Enforce the same owned Windows Job 120-second and 8-GiB limits."""
    execution.mkdir(parents=True, exist_ok=False)
    record = {'argv': argv, 'cwd': str(root), 'utc': datetime.now(timezone.utc).isoformat(),
              'status': 'started', 'exit_code': None, 'timeout_s': 120,
              'memory_limit_bytes': 8 * 1024**3, 'code_hash': code_hash(frozen)}
    started, job, proc, code = time.monotonic(), None, None, 2
    with (execution / 'stdout.log').open('wb') as stdout, (execution / 'stderr.log').open('wb') as stderr:
        try:
            if cancelled is not None and cancelled():
                record.update(cancelled=True, timed_out=False, not_started=True)
                raise InterruptedError('Lifecycle job cancelled before case execution')
            if os.name != 'nt':
                raise RuntimeError('Verified Windows owned Job adapter required')
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.CreateJobObjectW.argtypes, api.CreateJobObjectW.restype = [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE
            api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            api.SetInformationJobObject.restype = wintypes.BOOL
            api.AssignProcessToJobObject.argtypes, api.AssignProcessToJobObject.restype = [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL
            api.TerminateJobObject.argtypes, api.TerminateJobObject.restype = [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL
            api.CloseHandle.argtypes, api.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
            job = api.CreateJobObjectW(None, None)
            limits = ExtendedLimits()
            limits.basic.flags = 0x2300
            limits.process_memory = limits.job_memory = record['memory_limit_bytes']
            if not job or not api.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise OSError(ctypes.get_last_error(), 'Owned worker memory limit failed')
            proc = subprocess.Popen(argv, cwd=root, stdout=stdout, stderr=stderr,
                      env={**os.environ, 'PYTHONPATH': str(frozen / 'src'), 'PYTHONIOENCODING': 'utf-8',
                           'PYTHONDONTWRITEBYTECODE': '1', 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'},
                      creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            record['owned_pid'] = proc.pid
            if not api.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle))):
                proc.kill(); proc.wait(timeout=10)
                raise OSError(ctypes.get_last_error(), 'Owned worker assignment failed')
            record['memory_limit_enforced'], record['ownership'] = True, 'windows_job_object'
            atomic_json(execution / 'started.json', record)
            try:
                if cancelled is None:
                    code = proc.wait(timeout=120)
                else:
                    while proc.poll() is None:
                        if cancelled():
                            if not api.TerminateJobObject(job, 2):
                                raise OSError(ctypes.get_last_error(), 'Owned cancelled worker termination failed')
                            proc.wait(timeout=10)
                            record['cancelled'] = True
                            break
                        if time.monotonic() - started >= 120:
                            raise subprocess.TimeoutExpired(argv, 120)
                        time.sleep(.1)
                    code = proc.returncode
                record['timed_out'] = False
            except subprocess.TimeoutExpired:
                if not api.TerminateJobObject(job, 2):
                    raise OSError(ctypes.get_last_error(), 'Owned worker termination failed')
                proc.wait(timeout=10)
                code, record['timed_out'] = 2, True
        except Exception as error:
            record['runner_error'] = repr(error)
            if proc is not None and proc.poll() is None:
                proc.kill(); proc.wait(timeout=10)
        finally:
            if job:
                api.CloseHandle(job)
    record.update(exit_code=code, status='completed', wall_s=time.monotonic()-started,
                  stdout=(execution / 'stdout.log').relative_to(root).as_posix(),
                  stderr=(execution / 'stderr.log').relative_to(root).as_posix())
    atomic_json(execution / 'command.json', record)
    return record


def _validate_registration(registration):
    if not isinstance(registration, dict):
        raise ValueError('Object registration required')
    if (registration.get('suite') != 'lifecycle-finance' or registration.get('profile') != 'pilot'
            or type(registration.get('schema_version')) is not int or registration['schema_version'] != 1
            or type(registration.get('cycles')) is not int or registration['cycles'] != 12
            or registration.get('phase_duration_s') != 2. or registration.get('alpha') != .05
            or registration.get('worker_timeout_s') != 120 or registration.get('worker_memory_limit_bytes') != 8 * 1024**3
            or registration.get('maximum_replacements') != 1 or registration.get('provenance_type') != 'synthetic'
            or registration.get('risk_metric') != 'conservative_registered_case_fraction'):
        raise ValueError('Explicit registered bounded synthetic lifecycle pilot required')
    if any(type(registration.get(key)) is not int for key in ('maximum_replacements', 'worker_timeout_s', 'worker_memory_limit_bytes')):
        raise ValueError('Nonboolean integer limits required')
    for name, key in (('cases', 'case_id'), ('policies', 'policy_id')):
        rows = registration.get(name)
        if (not isinstance(rows, list) or len(rows) != 2
                or any(not isinstance(r, dict) for r in rows)
                or any(not isinstance(r.get(key), str) or not r[key] or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-' for c in r[key]) for r in rows)
                or len({r[key].casefold() for r in rows}) != len(rows)):
            raise ValueError('Unique registered path-safe full case/policy identities required')
    assumptions = FinancialAssumptions(**registration['financial_assumptions'])
    if assumptions.scheduled_horizon_s != registration['cycles'] * 2 * registration['phase_duration_s']:
        raise ValueError('Common scheduled cycle horizon and terminal assumptions required')
    if registration['macro_audit']['included_in_actual_frontier'] is not False:
        raise ValueError('Macro approximation cannot become an actual operating trajectory')
    if (registration['macro_audit']['case_id'] not in {r['case_id'] for r in registration['cases']}
            or registration['macro_audit']['policy_id'] not in {r['policy_id'] for r in registration['policies']}):
        raise ValueError('Registered macro audit identities required')
    if registration['macro_audit'].get('protocol') != {'protocol_id': 'synthetic_capacity_v1', 'retirement_ratio': .8}:
        raise ValueError('Explicit separate original S04 macro audit protocol required')
    early = registration.get('early_exit_audit')
    if (not isinstance(early, dict) or early.get('included_in_actual_frontier') is not False
            or type(early.get('maximum_replacements')) is not int or early['maximum_replacements'] != 0
            or early.get('case_id') not in {r['case_id'] for r in registration['cases']}
            or early.get('policy_id') not in {r['policy_id'] for r in registration['policies']}):
        raise ValueError('Registered separate early-exit audit required')
    thermal = registration.get('thermal_audit')
    if (not isinstance(thermal, dict) or thermal.get('included_in_actual_frontier') is not False
            or type(thermal.get('thermal_W')) not in (int, float) or thermal['thermal_W'] != .02
            or thermal.get('case_id') not in {r['case_id'] for r in registration['cases']}
            or thermal.get('policy_id') not in {r['policy_id'] for r in registration['policies']}):
        raise ValueError('Registered separate positive thermal audit required')
    module = registration.get('module_audit')
    if (not isinstance(module, dict) or module.get('included_in_actual_frontier') is not False
            or module.get('topology') != '4s' or module.get('coupling_W_per_K') != .04
            or module.get('cell_overrides') != [{'side_rate_s_inv': [.0003, .0004], 'accelerated_synthetic': True}, {}, {}, {}]
            or module.get('case_id') not in {r['case_id'] for r in registration['cases']}
            or module.get('policy_id') not in {r['policy_id'] for r in registration['policies']}):
        raise ValueError('Registered separate four-series-cell lifecycle audit required')
    return assumptions


def adopt_worker_report(path, *, root, digest, registered_sha, case_id, policy_id, mode, child_code):
    """Require saved actual files; malformed results become retained failed cases."""
    report = json.loads((path / 'report.json').read_text(encoding='utf-8'))
    worker_start = json.loads((path / 'started.json').read_text(encoding='utf-8'))
    required = {'started.json', 'lifecycle.json', 'finance.json', 'endpoints.json',
                'rul-required-unknown.json', 'shadow-separate.json'}
    if not isinstance(report, dict) or not isinstance(worker_start, dict):
        raise ValueError('Worker reports and start receipts must be objects')
    artifacts = report.get('artifacts')
    if (not isinstance(artifacts, dict) or not required <= set(artifacts)
            or any(not isinstance(name, str) or Path(name).name != name or name in ('.', '..')
                   or not isinstance(sha, str) or len(sha) != 64 or sha256_file(path / name) != sha
                   for name, sha in artifacts.items())):
        raise ValueError('Complete authenticated finance and execution files required')
    if (report.get('code_hash') != digest or report.get('exit_code') != child_code
            or report.get('case_id') != case_id or report.get('policy_id') != policy_id or report.get('mode') != mode
            or report.get('source_unchanged') is not True or report.get('execution_completed') is not True
            or worker_start.get('registration_sha256') != registered_sha or worker_start.get('code_hash') != digest
            or report.get('independent_operating_trajectory') is not False or report.get('independent_operating_n') != 0
            or report.get('source_ref') != (path / 'lifecycle.json').relative_to(root).as_posix()):
        raise ValueError('Worker source/registration/result identity mismatch')
    if (report.get('whole_case_status') not in ('complete', 'early_exit', 'failed', 'cancelled', 'unknown')
            or report.get('event_occurred') is not None and type(report['event_occurred']) is not bool
            or report.get('finance_value') is not None and (type(report['finance_value']) not in (int, float)
                                                          or not math.isfinite(report['finance_value']))):
        raise ValueError('Explicit valid whole-case outcome required')
    finance, rul, shadow = (json.loads((path / name).read_text(encoding='utf-8')) for name in
                            ('finance.json', 'rul-required-unknown.json', 'shadow-separate.json'))
    if any(not isinstance(value, dict) for value in (finance, rul, shadow)):
        raise ValueError('Finance evidence must be objects')
    if (finance['conditional_comparison_value_CNY'] != report['finance_value']
            or rul['conditional_comparison_value_CNY'] is not None
            or shadow['planning_shadow_deducted_CNY'] != 0
            or shadow['conditional_comparison_value_CNY'] != finance['conditional_comparison_value_CNY']):
        raise ValueError('Saved finance, unknown RUL or separate shadow invariant failed')
    return report


def run_lifecycle_finance(root, output=None, *, source=None, parameters=None, cancelled=None, on_case=None):
    root = Path(root).resolve()
    source = root if source is None else Path(source).resolve()
    suite = source / 'configs/experiments/lifecycle-finance-pilot-v1.json'
    registration = json.loads(suite.read_text(encoding='utf-8'))
    if parameters is not None:
        keys = {'sell_price_per_kWh', 'buy_price_per_kWh', 'replacement_cost_CNY'}
        if set(parameters) != keys or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in parameters.values()):
            raise ValueError('Finite nonnegative declared lifecycle financial inputs required')
        if parameters['sell_price_per_kWh'] > 10 or parameters['buy_price_per_kWh'] > 10 or parameters['replacement_cost_CNY'] > 100000:
            raise ValueError('Lifecycle financial input limits exceeded')
        registration['energy_economics'].update({k: v for k,v in parameters.items() if k != 'replacement_cost_CNY'})
        registration['energy_economics']['replacement_cost_per_cell'] = parameters['replacement_cost_CNY']
        registration['financial_assumptions']['replacement_cost_CNY_per_asset'] = parameters['replacement_cost_CNY']
        registration['workbench_input_parameters'] = dict(parameters)
        registration['workbench_input_revision'] = _hash(parameters)
    assumptions = _validate_registration(registration)
    out = (root / registration['default_output_parent'] / ('pilot-' + uuid.uuid4().hex[:12])
           if output is None else root / Path(output)).resolve()
    if (not out.is_relative_to(root / 'artifacts') or out == root / 'artifacts'
            or any(p.casefold() == 'evaluator' for p in out.parts)):
        raise ValueError('Fresh controlled public finance artifact output required')
    out.mkdir(parents=True, exist_ok=False)
    frozen, digest = freeze_source(source, out)
    registration = {**registration, 'registered_before_execution': True,
                    'code_hash': digest, 'source_configuration_sha256': sha256_file(suite)}
    atomic_json(out / 'registration.json', registration)
    registered_sha = sha256_file(out / 'registration.json')
    context = ComparisonContext(_hash(registration['protocol']), registration['event_definition'],
          registration['risk_scope'], registration['alpha'], _hash(registration['information_permissions']),
          sha256_file(frozen / 'src/naheng/runtime/lifecycle_finance_endpoints.py'), _hash(asdict(assumptions)),
          tuple(x['case_id'] for x in registration['cases']), assumptions.scheduled_horizon_s,
          risk_metric=registration['risk_metric'])
    outcomes, receipts, report_rows, complete = [], [], [], True

    def execute(case_id, policy_id, mode):
        path = out / 'cases' / mode / policy_id / case_id
        argv = [sys.executable, str(frozen / 'experiments/lifecycle_finance.py'), '--root', str(root),
                '--source-dir', str(frozen), '--registration', str(out / 'registration.json'),
                '--out', str(path), '--case-id', case_id, '--policy-id', policy_id, '--mode', mode]
        kwargs = {} if cancelled is None else {'cancelled': cancelled}
        receipt = _worker(argv, root=root, frozen=frozen, execution=path.parent / (case_id + '-execution'), **kwargs)
        report, error = None, None
        try:
            report = adopt_worker_report(path, root=root, digest=digest, registered_sha=registered_sha,
                      case_id=case_id, policy_id=policy_id, mode=mode, child_code=receipt['exit_code'])
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            report, error = None, repr(exc)
        valid = receipt['exit_code'] == 0 and not receipt.get('runner_error') and not receipt.get('timed_out') and report is not None
        item = {'case_id': case_id, 'policy_id': policy_id, 'mode': mode, 'valid_execution': valid,
                'receipt': (path.parent / (case_id + '-execution') / 'command.json').relative_to(root).as_posix(),
                'report_path': (path / 'report.json').relative_to(root).as_posix(), 'adoption_error': error}
        receipts.append(item)
        if on_case is not None:
            on_case(len(receipts), item)
        return report if valid else None

    for policy in registration['policies']:
        cases = []
        for case in registration['cases']:
            report = execute(case['case_id'], policy['policy_id'], 'exact')
            complete &= report is not None
            source_ref = receipts[-1]['report_path']
            cases.append(CaseOutcome(case['case_id'], report['whole_case_status'] if report else 'failed',
                         report['finance_value'] if report else None, report['event_occurred'] if report else None,
                         source_ref, independent_operating_trajectory=False))
            report_rows.append({'policy_id': policy['policy_id'], 'case_id': case['case_id'],
                                'status': report['whole_case_status'] if report else 'failed',
                                'comparison_CNY': report['finance_value'] if report else None,
                                'event': report['event_occurred'] if report else None})
        outcomes.append(PolicyOutcome(policy['policy_id'], context, tuple(cases)))
    macro = registration['macro_audit']
    macro_report = execute(macro['case_id'], macro['policy_id'], 'macro')
    early = registration['early_exit_audit']
    early_report = execute(early['case_id'], early['policy_id'], 'early-exit')
    thermal = registration['thermal_audit']
    thermal_report = execute(thermal['case_id'], thermal['policy_id'], 'thermal')
    module = registration['module_audit']
    module_report = execute(module['case_id'], module['policy_id'], 'module')
    macro_exercised = bool(macro_report and macro_report.get('accepted_jumps', 0) >= 1)
    early_exercised = bool(early_report and early_report.get('whole_case_status') == 'early_exit'
                           and early_report.get('elapsed_s', float('inf')) < assumptions.scheduled_horizon_s)
    thermal_exercised = bool(thermal_report and thermal_report.get('thermal_management_energy_J', 0) > 0)
    module_exercised = bool(module_report and module_report.get('topology') == '4s'
                            and module_report.get('cell_count') == 4 and module_report.get('replacement_count', 0) >= 1)
    complete &= macro_report is not None and early_report is not None and thermal_report is not None and module_report is not None
    frontier = pareto_frontier(outcomes)
    atomic_json(out / 'frontier.json', frontier)
    with (out / 'points.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(report_rows[0])); writer.writeheader(); writer.writerows(report_rows)
    table = ''.join('<tr>' + ''.join('<td>' + html.escape(str(v)) + '</td>' for v in row.values()) + '</tr>' for row in report_rows)
    (out / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>钠衡生命周期核算</title>'
        '<h1>实际合成周期与共同终端核算</h1><p>价格为合成假设；宏步预测单列。RUL未知，运营独立N=0；没有真实收益或事故率结论。</p>'
        '<table border="1"><tr><th>政策</th><th>案例</th><th>状态</th><th>条件比较 CNY</th><th>事件</th></tr>' + table + '</table>', encoding='utf-8')
    stable = (code_hash(source) == digest == code_hash(frozen) and registered_sha == sha256_file(out / 'registration.json'))
    code = 0 if complete and stable and macro_exercised and early_exercised and thermal_exercised and module_exercised else 2
    manifest = {'exit_code': code, 'execution_completed': bool(complete), 'code_hash': digest, 'source_unchanged': stable,
                'registered_before_execution': True, 'registration_sha256': registered_sha, 'receipts': receipts,
                'macro_audit_exercised': macro_exercised, 'early_exit_audit_exercised': early_exercised,
                'thermal_audit_exercised': thermal_exercised,
                'module_audit_exercised': module_exercised,
                'audits_in_actual_frontier': False, 'audits_use_separate_registered_conditions': True,
                'independent_operating_n': 0, 'real_income_claim': False, 'C02_complete': False,
                'artifacts': {name: sha256_file(out / name) for name in ('frontier.json', 'points.csv', 'report.html', 'source_index.json')},
                'scope': 'Engineering execution/finance experiment; unknown/censored life and all full project gates remain'}
    atomic_json(out / 'manifest.json', manifest)
    return {'exit_code': code, 'execution_completed': bool(complete), 'source_unchanged': stable,
            'artifact_dir': out.as_posix(), 'C02_complete': False, 'scope': manifest['scope']}
