"""Private original-test integration with real offline Linux isolation; no public admission."""
import base64
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

from naheng.formal.audit import audit_axioms
from naheng.runtime.artifacts import code_hash
from naheng.runtime.validation_process import run_validation_command
from .backend_host import BackendUnavailable, backend_root, install_hint
from .grammar import CandidateError, canonical_sha, parse_candidate
from .providers import emit_theorem

ROOT = Path(__file__).resolve().parents[3]
STAGE = ROOT / 'artifacts/discovery'
H = ROOT / 'artifacts/handoff' / 'a02-delegated-backend-20261016-a'
SOURCE_HASH = '142e643fbb376d77e451ae5b7d5136f8aacf1e68c6b955cbc37db0c9049b190c'
# Only this live verified executor may issue an admissible proof report.
_ISSUED_PROOFS = {}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024**2), b''):
            digest.update(block)
    return digest.hexdigest()


def authorized_output(root, out):
    root, original = Path(root).resolve(), Path(out).absolute()
    allowed = (ROOT / 'artifacts/discovery', ROOT / 'artifacts/test-temp')
    if root != ROOT or not any(original.is_relative_to(p) for p in allowed):
        raise CandidateError('Proof output outside authorized discovery/test artifact roots')
    for path in (original, *original.parents):
        if path == ROOT:
            break
        if path.exists() and (path.is_symlink() or path.lstat().st_file_attributes & 0x400):
            raise CandidateError('Reparse points are forbidden in proof output paths')
    resolved = original.resolve()
    if not any(resolved.is_relative_to(p) for p in allowed):
        raise CandidateError('Proof output escapes authorized roots')
    return resolved


def render_source(attempts):
    if not attempts or len(attempts) > 40:
        raise CandidateError('Finite nonempty proof batch required')
    targets = ['Naheng.Discovery.' + a['target'] for a in attempts]
    if len(set(targets)) != len(targets):
        raise CandidateError('Duplicate declaration identity')
    source = 'import Naheng.Reduction.ClassSufficiency\nnamespace Naheng.Discovery\nopen Naheng.Reduction\n'
    for attempt in attempts:
        source += emit_theorem(attempt['candidate'], attempt['target']) + '\n'
    source += 'end Naheng.Discovery\nset_option pp.proofs false\n'
    source += '\n'.join('#print ' + target + '\n#print axioms ' + target for target in targets) + '\n'
    return source, targets


def prepare_batch(root, attempts, out):
    out = authorized_output(root, out)
    source, targets = render_source(attempts)
    if out.exists():
        out = out / ('retry-' + uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    leaf = out / 'Candidates.lean'; leaf.write_bytes(source.encode())
    return leaf, targets


def verify_backend_inputs():
    manifest_path = ROOT / 'configs/discovery/proof-backend.json'
    if not manifest_path.is_file():
        raise BackendUnavailable('No pinned backend manifest at ' + manifest_path.name + '. ' + install_hint())
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    # A fresh checkout does not contain the pinned isolated backend. Report that
    # as an explicit, actionable condition instead of crashing on a missing file,
    # and never treat it as a checked proof.
    absent = next((name for name in manifest['files'] if not (ROOT / name).is_file()), None)
    if absent is not None:
        raise BackendUnavailable('Pinned isolated proof backend is not installed in this '
                                 'checkout; first absent pinned file: ' + absent + '. ' + install_hint())
    for name, expected in manifest['files'].items():
        if sha(ROOT / name) != expected:
            raise CandidateError('Pinned private backend source changed: ' + name)
    # Pin exact imported formal sources; Python additions do not alter those objects.
    # Bind the current complete source identity before and after execution too.
    return hashlib.sha256((sha(manifest_path) + code_hash(ROOT)).encode()).hexdigest()


def run_owned(root, command, cwd, out, timeout_s=120, **kwargs):
    out = authorized_output(root, out)
    if not math.isfinite(timeout_s) or not 0 < timeout_s <= 120:
        raise CandidateError('Hard native limit exceeded')
    if list(map(str, command)) != [str(STAGE / 'missing-Lean.exe')] or Path(cwd).resolve() != ROOT / 'formal':
        raise CandidateError('No arbitrary executable, source, environment or argv accepted')
    out.mkdir(parents=True, exist_ok=True)
    record = {'exit_code': 2, 'status': 'permission_or_setup_unknown', 'executed': False,
              'argv': list(map(str, command)), 'timeout_s': timeout_s, 'memory_limit_enforced': False,
              'reason': 'Exact requested missing executable does not exist; no fallback execution', 'wall_s': 0.0}
    if (STAGE / 'missing-Lean.exe').exists():
        raise CandidateError('Unexpected missing-executable fixture exists')
    (out / 'command.json').write_text(json.dumps(record, indent=2))
    return record


def setup_unknown(out, leaf, targets, source_hash, timeout_s, error, stage, *, persist=True, executed=False, started_at=None, host_command=None):
    record = {'exit_code': 2, 'status': 'permission_or_setup_unknown' if executed is False else 'execution_unknown',
        'executed': executed, 'memory_limit_enforced': False, 'timed_out': False,
        'failure_stage': stage, 'reason': type(error).__name__ + ': ' + str(error),
        'errno': getattr(error, 'errno', None), 'timeout_s': timeout_s,
        'wall_s': time.monotonic()-started_at if started_at is not None else None,
        'resource_cleanup_confirmed': None if executed is None else True}
    if host_command is not None:
        record['host_command'] = host_command
        record['resource_cleanup_confirmed'] = host_command.get('resource_cleanup_confirmed')
    result = {'source': str(leaf) if leaf is not None else None, 'source_sha256': source_hash,
        'targets': targets, 'requested_declarations': len(targets), 'kernel_checked': False,
        'status': record['status'], 'audit': None, 'command': record, 'attempt_count': 0 if executed is False else None,
        'evidence_persisted': False, 'scope': 'Setup/launch evidence only; never an issued proof'}
    if persist:
        try:
            native = out / 'native'; native.mkdir(exist_ok=True)
            receipt = native / 'command.json'; receipt.write_text(json.dumps(record, indent=2), encoding='utf-8')
            result['native_receipt_sha256'] = sha(receipt)
            result['evidence_persisted'] = True
            (out / 'proof-report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        except OSError as persistence_error:
            result['evidence_persisted'] = False
            result['persistence_error'] = type(persistence_error).__name__ + ': ' + str(persistence_error)
    return result


def prove_batch(root, attempts, out, timeout_s=120):
    started_at = time.monotonic()
    if not isinstance(timeout_s, (float, int)) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 120:
        raise CandidateError('Hard native limit exceeded')
    regenerated, targets = render_source(attempts)
    before = hashlib.sha256(regenerated.encode()).hexdigest()
    try:
        leaf, targets = prepare_batch(root, attempts, out); out = leaf.parent
    except OSError as error:
        return setup_unknown(Path(out), None, targets, before, timeout_s, error, 'authorized_output_setup', persist=False, started_at=started_at)
    try:
        pin = verify_backend_inputs()
        from .offline_seed import prepare
        plan, seed_sha = prepare(leaf, targets, timeout_s)
    except (BackendUnavailable, OSError, ImportError) as error:
        # An absent isolated backend means the proof was never executed. It is
        # reported as setup-unknown, never as checked and never as a pass.
        return setup_unknown(out, leaf, targets, before, timeout_s, error, 'verified_dependency_or_seed_setup', started_at=started_at)
    native = out / 'native'
    try:
        native.mkdir()
    except OSError as error:
        return setup_unknown(out, leaf, targets, before, timeout_s, error, 'native_receipt_directory', started_at=started_at)
    environment = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR') if k in os.environ}
    system_root = Path(os.environ.get('SystemRoot') or os.environ.get('WINDIR') or 'C:/Windows')
    environment.update(PATH=str(ROOT / '.venv/Scripts') + os.pathsep + str(system_root / 'System32'), PYTHONPATH=str(ROOT / 'src'),
        PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
        TEMP=str(out), TMP=str(out))
    argv = [str(ROOT / '.venv/Scripts/python.exe'), str(H / 'boot_requested_batch_serial_r2.py'), str(plan), seed_sha]
    try:
        outer = run_validation_command(argv, ROOT, native / 'host.stdout.log', native / 'host.stderr.log', timeout_s=1260, env=environment)
    except OSError as error:
        # A caller cannot infer whether an unexpected driver error happened
        # before or after child creation. Never fabricate a clean nonexecution.
        return setup_unknown(out, leaf, targets, before, timeout_s, error, 'host_driver_invocation', executed=None, started_at=started_at)
    try:
        (native / 'host.command.json').write_text(json.dumps(outer, indent=2), encoding='utf-8')
        stdout_lines = (native / 'host.stdout.log').read_text(encoding='utf-8').splitlines() if (native / 'host.stdout.log').is_file() else []
    except OSError as error:
        return setup_unknown(out, leaf, targets, before, timeout_s, error, 'host_receipt_readback',
            persist=False, executed=False if outer.get('executed') is False else None,
            started_at=started_at, host_command=outer)
    if outer.get('executed') is not True or not stdout_lines:
        failure = RuntimeError('Host driver did not start or supplied no complete result; native proof unconfirmed')
        return setup_unknown(out, leaf, targets, before, timeout_s, failure, 'host_driver_result',
            executed=False if outer.get('executed') is False else None, started_at=started_at, host_command=outer)
    record = {'exit_code': 2, 'executed': None, 'memory_limit_enforced': False,
        'status': 'isolation_setup_unknown', 'timed_out': False, 'host_command': outer, 'timeout_s': timeout_s,
        'backend_input_pin': pin, 'seed_plan': str(plan), 'seed_sha256': seed_sha, 'stdout': '', 'stderr': ''}
    result = {'source': str(leaf), 'source_sha256': before, 'targets': targets, 'requested_declarations': len(targets),
        'kernel_checked': False, 'status': record['status'], 'audit': None, 'command': record,
        'scope': 'checked typed discovery only; model applicability and runtime admission remain separate'}
    try:
        assert outer['resource_cleanup_confirmed'] and not outer['timed_out']
        summary = json.loads((native / 'host.stdout.log').read_text(encoding='utf-8').splitlines()[-1])
        boot_path = Path(summary['result']); boot = json.loads(boot_path.read_text(encoding='utf-8'))
        # Preserve a failed transport's exact evidence without claiming Lean execution.
        record.update(boot_result=str(boot_path),boot_result_sha256=sha(boot_path),
            serial_transport=boot.get('serial_transport'),host_boot_exit_code=boot.get('exit_code'))
        assert boot_path.parent.parent == backend_root()
        assert boot['seed_sha256'] == seed_sha and boot['base_unchanged'] and boot['readonly_payloads_unchanged']
        host = json.loads(Path(boot['QEMU_command']).read_text(encoding='utf-8'))
        assert host['native_exit_code'] == 0 and host['resource_cleanup_confirmed'] and not host['timed_out']
        collected = boot['guest_collected']; assert len(collected['ISOLATION_JSON']) == len(collected['PROOF_RESULT']) == 1
        canary = collected['ISOLATION_JSON'][0]; assert canary['exit_code'] == 0 and all(v is True for v in canary['gates'].values())
        proof = collected['PROOF_RESULT'][0]; assert not proof['delegate_cleanup']['errors']
        for role in ('version', 'import'):
            row = proof['roles'][role]
            assert row['native_exit_code'] == 0 and row['cleanup_confirmed'] and not row['timed_out'] and row['native_started']
        row = proof['roles']['candidate']
        assert row['cleanup_confirmed'] and row['outer_credentials_verified'] and row['stopped_before_assignment']
        assert row['native_started'], 'Native Lean start is not confirmed; no executed claim'
        assert row['limit_readback']['memory.max'] == str(8 * 1024**3) and row['limit_readback']['memory.swap.max'] == '0'
        record.update(exit_code=row['exit_code'], executed=True, memory_limit_enforced=True, timed_out=row['timed_out'],
            actual_isolation=row, boot_result=str(boot_path), boot_result_sha256=sha(boot_path),
            qemu_native_receipt_sha256=sha(boot['QEMU_command']), wall_s=row['wall_s'])
        if row['timed_out']:
            record['status'] = 'timeout_unknown'
        else:
            payload = json.loads(row['stdout'].splitlines()[-1])
            assert payload['role'] == 'candidate' and payload['source_sha256'] == before
            duration = payload['wall_s']
            assert type(duration) in (float, int) and math.isfinite(duration) and 0 <= duration <= timeout_s
            marker = row['native_start_receipt']
            assert payload['Lean_binary_sha256'] == marker['Lean_binary_sha256']
            assert payload['native_started_monotonic'] == marker['started_monotonic']
            assert payload['native_finished_monotonic'] - payload['native_started_monotonic'] == duration
            assert payload['native_finished_monotonic'] <= row['last_completion_observation_monotonic']
            assert row['last_completion_observation_monotonic'] < marker['started_monotonic'] + timeout_s
            for label in ('stdout', 'stderr'):
                assert hashlib.sha256(payload[label].encode()).hexdigest() == payload[label + '_sha256']
                record[label] = payload[label]
                (native / (label + '.log')).write_text(payload[label], encoding='utf-8')
            record['native_Lean_receipt'] = payload
            record['status'] = 'proof_failed'
            if row['native_exit_code'] == payload['native_exit_code'] == 0:
                compiled = base64.b64decode(payload['olean_b64'], validate=True)
                assert hashlib.sha256(compiled).hexdigest() == payload['olean_sha256']
                (out / 'Candidates.olean').write_bytes(compiled)
                audit = audit_axioms(payload['stdout'], targets)
                result['audit'] = audit
                assert before == sha(leaf) and pin == verify_backend_inputs()
                if audit['status'] == 'passed':
                    record['status'] = 'kernel_checked'; result.update(kernel_checked=True, olean_sha256=payload['olean_sha256'])
    except (AssertionError, IndexError, KeyError, ValueError, OSError) as error:
        record['validation_error'] = repr(error)
    result['status'] = record['status']
    (native / 'command.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    result['native_receipt_sha256'] = sha(native / 'command.json')
    result['input_unchanged'] = before == sha(leaf)
    result['attempt_count'] = len(attempts) if record['executed'] else 0 if record['executed'] is False else None
    (out / 'proof-report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if result['kernel_checked']:
        _ISSUED_PROOFS[(str(leaf), result['native_receipt_sha256'])] = deepcopy(result)
    return result


def register_checked(attempts, proof):
    if proof.get('kernel_checked') is not True or proof.get('status') != 'kernel_checked' or (proof.get('audit') or {}).get('status') != 'passed':
        raise CandidateError('Unverified/analytic/unknown candidate cannot be registered checked')
    issuance_key = (proof.get('source'), proof.get('native_receipt_sha256'))
    if _ISSUED_PROOFS.get(issuance_key) != proof:
        raise CandidateError('Report not issued by this live verified executor; imported JSON requires re-execution')
    leaf = Path(proof['source']); authorized_output(ROOT, leaf)
    receipt = leaf.parent / 'native/command.json'; compiled = leaf.parent / 'Candidates.olean'
    source, targets = render_source(attempts)
    if (leaf.read_bytes() != source.encode() or sha(leaf) != proof['source_sha256']
            or sha(receipt) != proof['native_receipt_sha256'] or sha(compiled) != proof['olean_sha256']):
        raise CandidateError('Compiled source/native/olean mismatch')
    record = json.loads(receipt.read_text(encoding='utf-8'))
    if (not record['executed'] or record['exit_code'] != 0 or record['timed_out'] or not record['memory_limit_enforced']
            or verify_backend_inputs() != record['backend_input_pin']
            or sha(record['boot_result']) != record['boot_result_sha256']
            or audit_axioms(record['stdout'], targets) != proof['audit']):
        raise CandidateError('Actual private native evidence/pin mismatch')
    return [{'candidate_id': parse_candidate(a['candidate']).candidate_id, 'declaration': target,
        'candidate_sha256': canonical_sha(parse_candidate(a['candidate']).to_dict()), 'kernel_checked': True,
        'source_sha256': proof['source_sha256'], 'olean_sha256': proof['olean_sha256'], 'axioms': proof['audit']['targets'][target],
        'trust_level': 'lean_kernel_core_checked_conditional', 'model_applicability': a.get('model_condition_satisfied'),
        'nonempty_domain_witness': parse_candidate(a['candidate']).domain_witness,
        'claim_scope': 'Conditional instantaneous finite affine site-output only; private test registration'}
        for a, target in zip(attempts, targets, strict=True)]
