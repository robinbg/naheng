"""Explicit bounded synthetic consumption of a current calibration packet.

No saved Run, PF or registry adoption is performed. Source/roles, current code
and physical binding must match; forecast energy is never entered as executed
cash flow. The caller explicitly selects this synthetic simulation action.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

from naheng.control.rules import RuleParameters, propose
from naheng.domain.contracts import ForecastQuery
from naheng.economics.ledger import EnergyLedger
from naheng.estimation.calibration import CalibrationCandidate, content_hash, fit_candidate, posterior_to_contract, _eligibility
from naheng.estimation.calibration_session import CalibrationRequest, TrainingSource, FileRef, _file, verify_builtin_forward
from naheng.estimation.particle_filter import particle_model
from naheng.formal.checker import run_command
from naheng.lifecycle.forecast import forecast
from naheng.risk.admission import check as admission_check
from naheng.runtime.artifacts import code_hash
from naheng.runtime.forecast_jobs import _package_model

SCOPE = "Explicit conditional builtin synthetic simulation only; no saved Run adoption, real-cell fit, strict safety, UI acceptance or profit superiority"
SOURCE_REFS = (
    "src/naheng/control/rules.py", "src/naheng/risk/admission.py", "src/naheng/risk/forecast.py",
    "src/naheng/packages/domain_check.py", "src/naheng/lifecycle/forecast.py",
    "src/naheng/lifecycle/capacity_protocol.py", "src/naheng/economics/ledger.py",
    "src/naheng/estimation/calibration.py", "src/naheng/estimation/calibration_session.py",
    "src/naheng/estimation/discrepancy.py", "src/naheng/estimation/particle_filter.py",
    "src/naheng/estimation/diagnostics.py", "src/naheng/domain/contracts.py",
    "src/naheng/runtime/forecast_jobs.py", "src/naheng/runtime/artifacts.py",
)


class ConsumerUnknown(RuntimeError):
    pass


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    return json.loads(Path(path).read_bytes())


def _write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def _public(path, root):
    _need(not any(p.casefold() == 'evaluator' for p in Path(path).parts), 'Raw public source path enters private evaluator')
    path = Path(path).resolve()
    _need(path.is_relative_to(root) and not any(p.casefold() == 'evaluator' for p in path.parts),
          'Public source path escaped ROOT or enters private evaluator')
    _need(path.is_file() and path.stat().st_size <= 4 * 1024 * 1024, 'Missing or oversized public source file')
    return path


def _parameters(horizon_s, current_limit_A, ambient_K, sell_price_per_kWh, seed):
    values = (horizon_s, current_limit_A, ambient_K, sell_price_per_kWh)
    _need(all(type(x) in (int, float) and math.isfinite(x) for x in values), 'Finite numeric action parameters required')
    _need(0 < horizon_s <= 10 and current_limit_A > 0 and ambient_K > 0 and sell_price_per_kWh >= 0,
          'Action horizon/current/ambient/synthetic tariff out of bounds')
    _need(type(seed) is int and 0 <= seed <= 2**32 - 90, 'Bounded integer seed required')
    return {'horizon_s': float(horizon_s), 'current_limit_A': float(current_limit_A),
            'ambient_K': float(ambient_K), 'sell_price_per_kWh': float(sell_price_per_kWh), 'seed': seed}


def _packet(root, calibration_dir):
    """Validate the current owned-worker receipt and exact conditional candidate."""
    _need(not any(p.casefold() == 'evaluator' for p in Path(calibration_dir).parts), 'Raw private evaluator is not a calibration packet')
    packet = Path(calibration_dir).resolve()
    _need(packet.is_relative_to(root / 'artifacts/calibration') and packet != root / 'artifacts/calibration',
          'Current calibration packet must be under controlled artifacts/calibration')
    _need(not any(p.casefold() == 'evaluator' for p in packet.parts), 'Private evaluator is not a calibration packet')
    files = {name: _public(packet / name, root) for name in (
        'manifest.json', 'input.json', 'result.json', 'started.json', 'worker-command.json', 'worker.log')}
    hashes = {path: _sha(path) for path in files.values()}
    mf, start, worker, result = (_read(files[n]) for n in ('manifest.json', 'started.json', 'worker-command.json', 'result.json'))
    _need(mf.get('schema_version') == 1 and mf.get('complete') is True and mf.get('exit_code') == 0,
          'Calibration packet is not successfully complete')
    implementation_sha = code_hash(root)
    if mf.get('code_hash') != implementation_sha or start.get('code_hash') != implementation_sha:
        raise ConsumerUnknown('Calibration packet implementation differs from current ROOT code_hash')
    _need(mf.get('input_sha256') == start.get('input_sha256') == hashes[files['input.json']]
          and mf.get('result_sha256') == hashes[files['result.json']], 'Calibration input/result bytes do not match receipt hashes')
    argv = worker.get('command')
    _need(isinstance(argv, list) and len(argv) == 7 and argv == start.get('argv')
          and argv[1:4] == ['-m', 'naheng.estimation.calibration_session', '--worker']
          and Path(argv[4]).resolve() == root and Path(argv[5]).resolve() == files['input.json']
          and Path(argv[6]).resolve() == packet and Path(worker.get('cwd', '')).resolve() == root
          and Path(worker.get('log', '')).resolve() == files['worker.log'], 'Calibration owned-worker argv/path binding differs')
    _need(start.get('timeout_s') == 120 and worker.get('exit_code') == 0 and worker.get('timed_out') is False,
          'Calibration worker did not finish successfully within its mandatory budget')
    log_head = files['worker.log'].read_text(encoding='utf-8').split('\n\n--- STDOUT ---\n', 1)[0]
    _need(json.loads(log_head) == worker, 'Calibration worker log/command receipt disagree')
    _need(result.get('exit_code') == 0 and result.get('existing_run_or_filter_modified') is False
          and result.get('independent_experiment') is False, 'Unsupported calibration result scope')
    request = CalibrationRequest.model_validate_json(files['input.json'].read_bytes())
    _need(request.noise is not None, 'Missing likelihood assumption is not zero noise')
    eligibility, reasons = _eligibility(request.prior, request.batch, request.noise)
    _need(eligibility == 'PASS', 'Training eligibility failed: ' + ','.join(reasons))
    _need(request.prior.binding.provenance_type == 'synthetic'
          and request.prior.binding.chemistry_id == 'synthetic_two_site'
          and request.prior.binding.model_id == 'two_site_current_adapter_v1'
          and request.batch.input_scope == 'declared_training_data', 'Only declared builtin synthetic training source is authorized')
    cal = result['calibration']
    candidate = CalibrationCandidate.model_validate_json(json.dumps(cal['candidate'], allow_nan=False))
    _need(cal.get('status') == 'PASS' and candidate.content_sha256 == cal.get('candidate_content_sha256')
          and candidate.posterior.content_sha256 == cal.get('posterior_content_sha256'), 'Candidate content SHA mismatch')
    # Plain SHA/flags can be rebound by a local packet author. Recompute the
    # actual initial sensor update, every parent and nominal trajectory and SOC
    # before releasing any candidate to consumers. Original 100s verifier and
    # this worker's 110s total / 120s owned limit all remain in force.
    _public(root / request.training_source.path, root)
    _public(root / request.batch.propagation_evidence.source_ref, root)
    for rel in request.model_package.binding_hashes:
        _public(root / rel, root)
    actual_forward = verify_builtin_forward(root, request)
    _need(actual_forward == result.get('integration_verification'),
          'Saved forward verification differs from actual adoption-time recomputation')
    recomputed = fit_candidate(request.prior, request.batch, request.noise,
        minimum_samples=request.minimum_samples, minimum_span_s=request.minimum_span_s)
    _need(recomputed.status == 'PASS' and recomputed.candidate is not None
          and recomputed.candidate.content_sha256 == candidate.content_sha256,
          'Saved candidate differs from actual current conditional Gaussian arithmetic')
    snapshot = posterior_to_contract(candidate)
    _need(snapshot.model_dump(mode='json') == cal.get('posterior_contract'), 'Saved posterior contract differs from immutable candidate')
    raw = _read(files['input.json'])['model_package']
    _need(raw == request.model_package.model_dump(mode='json', exclude_unset=True), 'Registered descriptor omitted-default identity differs')
    model = _package_model(raw, root, snapshot)
    _public(root / request.training_source.path, root)
    source = _file(root, request.training_source, 'data/synthetic')
    source_typed = TrainingSource.model_validate_json(source.read_bytes())
    binding = request.prior.binding
    _need((source_typed.source_id, source_typed.source_revision, source_typed.model_id, source_typed.model_package_id,
           source_typed.parameter_revision, source_typed.chemistry_id) ==
          (binding.source_id, binding.source_revision, binding.model_id, binding.model_package_id,
           binding.parameter_revision, binding.chemistry_id), 'Training source identity differs')
    _need(binding.source_sha256 == request.training_source.sha256
          and binding.parameter_sha256 == raw['parameter_hash']
          and binding.model_source_sha256 == raw['binding_hashes']['src/naheng/models/site_model.py'], 'Training source/physical binding differs')
    _need(request.noise.source_ref == request.training_source.path and request.noise.source_sha256 == binding.source_sha256,
          'Likelihood assumption source differs from declared synthetic training source')
    _need(content_hash(source_typed.prior_snapshot) == request.prior.source_snapshot_sha256,
          'Prior does not match the hashed source prefix')
    _need(candidate.posterior.binding == binding and candidate.parent_content_sha256 == request.prior.content_sha256,
          'Candidate no longer represents the original physical binding')
    expected_names, expected_units = tuple(model.state_names) + ('rate_scale', 'side_rate_scale'), tuple(model.state_units) + ('1', '1')
    _need(candidate.posterior.state_names == expected_names and candidate.posterior.state_units == expected_units
          and request.prior.state_names == expected_names and request.prior.state_units == expected_units,
          'Builtin joint state/parameter names or units differ')
    _need(candidate.posterior.parameter_state_names == request.prior.parameter_state_names == ('rate_scale', 'side_rate_scale'),
          'Builtin physical parameter columns must remain explicit')
    _need(len(source_typed.records) == len(request.batch.observations) == len(request.execution_history), 'Source observation/history count differs')
    for sensor, observation, history in zip(source_typed.records, request.batch.observations, request.execution_history):
        _need((sensor.observation_id, sensor.timestamp_s, sensor.values) ==
              (observation.observation_id, observation.timestamp_s, observation.values), 'Training observations differ from source bytes')
        _need(history.model_dump() == {key: getattr(sensor, key) for key in ('timestamp_s', 'current_A', 'ambient_K', 'thermal_W')},
              'Execution history differs from the training source')
    evidence = request.batch.propagation_evidence
    _public(root / evidence.source_ref, root)
    forward = _file(root, FileRef(path=evidence.source_ref, sha256=evidence.artifact_sha256), 'artifacts')
    v = actual_forward
    _need(v.get('status') == 'PASS' and v.get('parents') == len(snapshot.samples)
          and v.get('training_observations') == len(request.batch.observations)
          and v.get('model_binding_hashes') == raw['binding_hashes']
          and all(v.get(k) is True for k in ('source_bytes_and_headers_match', 'initial_sensor_assimilation_recomputed',
              'actual_parent_forward_predictions_recomputed', 'same_particle_SOC_recomputed')),
          'Missing associated actual builtin source/parent-forward verification')
    capacities = np.asarray(model.params.site_capacity_mol)
    for frozen in (request.prior, candidate.posterior):
        _need(len(frozen.derived_observables) == 1 and frozen.derived_observables[0].name == 'soc'
              and frozen.derived_observables[0].unit == '1', 'Actual same-particle SOC readout required')
        actual_soc = np.asarray(frozen.samples)[:, :2] @ capacities / capacities.sum()
        _need(np.allclose(actual_soc, frozen.derived_observables[0].particle_values, rtol=1e-10, atol=1e-12),
              'SOC does not come from the actual same-particle capacity readout')
    hashes[source], hashes[forward] = _sha(source), _sha(forward)
    for rel in set(SOURCE_REFS) | set(raw['binding_hashes']):
        path = _public(root / rel, root)
        hashes[path] = _sha(path)
    return {'request': request, 'candidate': candidate, 'snapshot': snapshot, 'package': raw, 'model': model,
            'implementation_sha': implementation_sha, 'hashes': hashes, 'verification': v, 'packet': packet}


def _execute(root, packet, out, params):
    started = time.monotonic()
    loaded = _packet(root, packet)
    candidate, snapshot, package, model = (loaded[k] for k in ('candidate', 'snapshot', 'package', 'model'))
    protected = loaded['hashes']
    script = Path(__file__).resolve()
    protected[script] = _sha(script)
    candidate_sha, snapshot_sha = candidate.content_sha256, content_hash(snapshot)
    prior_sha = loaded['request'].prior.content_sha256
    weights_sha = content_hash(snapshot.weights)
    ident = {'snapshot_id': snapshot.snapshot_id, 'snapshot_content_sha256': snapshot_sha,
             'frozen_posterior_content_sha256': candidate.posterior.content_sha256, 'candidate_content_sha256': candidate_sha,
             'weights_sha256': weights_sha, 'model_package_id': snapshot.model_package_id,
             'parameter_revision': snapshot.parameter_revision, 'obs_until_s': snapshot.obs_until_s}
    low, high = package['domain']['temperature_K']
    _need(low <= params['ambient_K'] <= high and params['current_limit_A'] <= package['domain']['max_current_A'],
          'Explicit action parameters exceed the registered physical package domain')
    boundaries = []

    def stable(boundary):
        if time.monotonic() - started >= 110:
            raise ConsumerUnknown('Shared consumer soft total budget exhausted at calculation boundary')
        if code_hash(root) != loaded['implementation_sha']:
            raise ConsumerUnknown('ROOT implementation changed during shared consumption')
        for path, digest in protected.items():
            _need(_sha(path) == digest, 'Protected source/input changed at ' + boundary + ': ' + str(path))
        _need(content_hash(snapshot) == snapshot_sha and content_hash(snapshot.weights) == weights_sha
              and candidate.content_sha256 == candidate_sha and loaded['request'].prior.content_sha256 == prior_sha,
              'Shared candidate/posterior/prior mutated')
        _package_model(package, root, snapshot)
        boundaries.append({'boundary': boundary, 'status': 'PASS', 'files': len(protected), **ident})

    _write(out / 'candidate.json', candidate.model_dump(mode='json'))
    _write(out / 'snapshot.json', snapshot.model_dump(mode='json'))
    _write(out / 'source_refs.json', {'calibration_dir': str(loaded['packet']), 'code_hash': loaded['implementation_sha'],
        'params': params, 'explicit_simulation_action': True, 'same_snapshot': ident,
        'prior_content_sha256': prior_sha, 'actual_calibration_forward_verification': loaded['verification'],
        'adoption_forward_recomputed_here': True,
        'adoption_solves': {'initial_PF_sensor_updates': 1, 'parent_integrations': len(snapshot.samples) * len(loaded['request'].batch.observations),
                            'nominal_integrations': len(loaded['request'].batch.observations)},
        'protected_files': [{'path': str(p), 'sha256': d} for p, d in protected.items()]})
    stable('before_rule')
    rule_params = RuleParameters(current_limit_A=params['current_limit_A'])
    action = propose(snapshot, price=params['sell_price_per_kWh'], start_s=snapshot.obs_until_s,
                     duration_s=params['horizon_s'], parameters=rule_params)
    # The existing forecast query has no active thermal input. Reject, rather
    # than silently simulate different heat controls under the same action.
    _need(action.thermal_W == 0, 'Active thermal proposal requires a forecast policy with a thermal command; this consumer only supports passive heat')
    stable('after_rule_before_admission')
    admitted = admission_check(snapshot, action, package, ambient_K=params['ambient_K'], mode='empirical')
    stable('after_admission_before_forecast')
    query = ForecastQuery(snapshot_id=snapshot.snapshot_id, future_policy_id='fixed-current-v1',
        environment_id='constant-ambient-v1', horizon_s=params['horizon_s'], sample_budget=4,
        endpoint_protocol='unknown_calibration_endpoint', current_A=action.current_A,
        ambient_K=params['ambient_K'], seed=params['seed'] + 89)
    remaining = 110 - (time.monotonic() - started)
    predicted = forecast(snapshot, query, model, wall_budget_s=remaining)
    stable('after_forecast_before_execution')
    _need(predicted['snapshot_id'] == snapshot.snapshot_id and predicted['model_package_id'] == snapshot.model_package_id
          and predicted['parameter_revision'] == snapshot.parameter_revision, 'Forecast physical identity differs')
    _need(predicted['rul']['status'] == 'unknown' and not predicted['rul']['samples_s']
          and predicted['rul']['distribution_complete'] is False and predicted['risk']['risk_certificate'] is False,
          'Unverified endpoint or empirical risk was promoted to a certificate')
    for event in ('fire', 'sodium_plating'):
        _need(predicted['risk']['events'][event]['status'] == 'unknown'
              and predicted['risk']['events'][event]['probability'] is None, 'Unavailable risk mechanism is not unknown')
    ledger = EnergyLedger('isolated-consumer-' + out.name, tariff_source='explicit_synthetic_simulation_tariffs')
    execution = {'executed': False, 'energy_J': 0.0, 'thermal_electric_energy_J': 0.0,
                 'elapsed_s': 0.0, 'events': [], 'reason': admitted['reason']}
    if admitted['decision'] == 'accept':
        # Draw only after policy, admission, and forecasting; never supplied to them.
        index = int(np.random.default_rng(params['seed'] + 88).choice(len(snapshot.samples), p=snapshot.weights))
        row = np.asarray(snapshot.samples[index])
        sampled = particle_model(model, row[snapshot.state_names.index('rate_scale')], row[snapshot.state_names.index('side_rate_scale')])
        initial = row[[snapshot.state_names.index(n) for n in model.state_names]].copy()
        actual = sampled.integrate(initial, action.current_A, action.duration_s, ambient_K=params['ambient_K'], thermal_W=action.thermal_W)
        thermal = abs(action.thermal_W) * actual.elapsed_s / sampled.params.thermal_cop
        _need(np.isclose(thermal, actual.thermal_management_energy_J, rtol=0, atol=1e-12), 'Actual thermal electrical cost differs from COP accounting')
        execution = {'executed': True, 'energy_J': actual.energy_J, 'thermal_electric_energy_J': thermal,
            'elapsed_s': actual.elapsed_s, 'events': actual.events, 'reason': admitted['reason'],
            'solver': actual.solver, 'inventory_residual_mol': actual.inventory_residual_mol}
        _write(out / 'evaluator/execution.json', {**execution, **ident, 'private_particle_index': index,
            'private_joint_sample': row.tolist(), 'initial_state': initial.tolist(), 'sampled_parameters': asdict(sampled.params),
            'times_s': actual.times_s.tolist(), 'states': actual.states.tolist(), 'voltages_V': actual.voltages_V.tolist(),
            'final_state': actual.state.tolist(), 'thermal_cop': sampled.params.thermal_cop,
            'private_draw_seed': params['seed'] + 88, 'private_draw_supplied_to_proposer': False,
            'private_draw_scope': 'Conditional synthetic posterior draw; no privileged physical truth'})
    entry = ledger.append(action, execution_id='actual-' + out.name, energy_J=execution['energy_J'],
        thermal_energy_J=execution['thermal_electric_energy_J'], buy_price_per_kWh=0.15,
        sell_price_per_kWh=params['sell_price_per_kWh'], executed=execution['executed'],
        duration_s=execution['elapsed_s'], reason=execution['reason'])
    stable('after_execution_and_ledger')
    _need(entry['snapshot_id'] == snapshot.snapshot_id and entry['action_id'] == action.action_id, 'Ledger action/posterior identity differs')
    _write(out / 'proposal.json', {'input': {**ident, 'rule_parameters': asdict(rule_params), 'params': params}, 'action': action.model_dump(mode='json')})
    _write(out / 'admission.json', {'input': {**ident, 'action_id': action.action_id, 'mode': 'empirical', 'package_hash': package['package_hash']}, 'actual_result': admitted})
    _write(out / 'forecast.json', {'input': {**ident, 'query': query.model_dump(mode='json'), 'thermal_W': 0.0}, 'actual_result': predicted, 'risk_same_paths': True})
    _write(out / 'ledger.json', {'input': {**ident, 'action_id': action.action_id}, 'entries': ledger.entries,
        'summary': ledger.summary(), 'execution': execution, 'forecast_energy_booked': False,
        'execution_energy_source': 'Actual conditional synthetic evaluator integration only'})
    complete = predicted['budget']['completed_paths'] == 4
    summary = {'exit_code': 0 if complete else 2, 'status': 'PASS' if complete else 'UNKNOWN', 'same_snapshot': ident,
        'actual_executed': execution['executed'], 'actual_execution_elapsed_s': execution['elapsed_s'],
        'actual_execution_energy_J': execution['energy_J'], 'net_cashflow_CNY': entry['net_cashflow'],
        'proposal_current_A': action.current_A, 'proposal_thermal_W': action.thermal_W, 'admission_decision': admitted['decision'],
        'forecast_budget': predicted['budget'], 'freshness_checks': boundaries, 'code_hash': loaded['implementation_sha'],
        'adoption_forward_recomputed_here': True,
        'adoption_solves': {'initial_PF_sensor_updates': 1, 'parent_integrations': len(snapshot.samples) * len(loaded['request'].batch.observations),
                            'nominal_integrations': len(loaded['request'].batch.observations)},
        'warnings': ['RUL/fire/sodium_plating unknown', 'Finite particles are not a full state-domain or operating-risk certificate',
                     'Likelihood combined-error assumptions do not identify pure sensor noise', 'Synthetic tariffs; lifecycle costs and terminal value incomplete'],
        'rul_status': 'unknown', 'fire_status': 'unknown', 'sodium_plating_status': 'unknown', 'strict_T3_certificate': False,
        'saved_Run_adoption': False, 'PF_registry_or_old_run_modified': False, 'independent_experiment': False,
        'UI_acceptance': False, 'wall_s': time.monotonic() - started, 'scope': SCOPE}
    _write(out / 'report.json', summary)
    return summary


def _worker(root, packet, out, params):
    try:
        params = _parameters(**params)
        result = _execute(root, packet, out, params)
    except Exception as error:
        import traceback
        traceback.print_exc()
        unknown = isinstance(error, (ConsumerUnknown, OSError, TimeoutError))
        result = {'exit_code': 2 if unknown else 1, 'status': 'UNKNOWN' if unknown else 'FAIL', 'reason': str(error),
                  'saved_Run_adoption': False, 'PF_registry_or_old_run_modified': False, 'scope': SCOPE}
    _write(out / 'result.json', result)
    return result['exit_code']


def run_consumer(root, calibration_dir, output_path, *, horizon_s=5, current_limit_A=.02,
                 ambient_K=299.15, sell_price_per_kWh=.30, seed=20261014) -> dict:
    """Run a fresh isolated simulation worker under the original 120s limit."""
    _need(not any(p.casefold() == 'evaluator' for path in (calibration_dir, output_path) for p in Path(path).parts),
          'Raw consumer input/output must not enter private evaluator')
    root, packet, out = Path(root).resolve(), Path(calibration_dir).resolve(), Path(output_path).resolve()
    params = _parameters(horizon_s, current_limit_A, ambient_K, sell_price_per_kWh, seed)
    _need((root / 'src/naheng').is_dir(), 'Actual ROOT source directory required')
    _need(out.is_relative_to(root / 'artifacts') and out != root / 'artifacts'
          and not out.is_relative_to(packet) and not packet.is_relative_to(out)
          and not any(p.casefold() == 'evaluator' for p in out.parts), 'Fresh output must be a controlled nonoverlapping public artifact directory')
    _need(not out.exists(), 'Output must be fresh; existing evidence cannot be overwritten')
    initial_code_hash = code_hash(root)
    out.mkdir(parents=True, exist_ok=False)
    script = Path(__file__).resolve()
    argv = [sys.executable, '-B', str(script), '--worker', str(root), str(packet), str(out), json.dumps(params, allow_nan=False)]
    _write(out / 'started.json', {'argv': argv, 'code_hash': initial_code_hash, 'params': params,
        'script_sha256': _sha(script), 'utc': datetime.now(timezone.utc).isoformat(), 'timeout_s': 120})
    receipt = run_command(argv, root, out / 'worker.log', timeout=120)
    _write(out / 'worker-command.json', {k: v for k, v in receipt.items() if k not in ('stdout', 'stderr')})
    result_path = out / 'result.json'
    complete = not receipt['timed_out'] and result_path.is_file()
    result = _read(result_path) if complete else {'exit_code': 2, 'status': 'UNKNOWN', 'reason': 'Owned consumer worker incomplete', 'scope': SCOPE}
    if code_hash(root) != initial_code_hash:
        result = {'exit_code': 2, 'status': 'UNKNOWN', 'reason': 'ROOT code changed during owned consumer worker', 'scope': SCOPE}
        complete = False
    if result['exit_code'] != receipt['exit_code']:
        result = {'exit_code': 2, 'status': 'UNKNOWN', 'reason': 'Worker exit and result receipt disagree', 'scope': SCOPE}
        complete = False
    files = [{'path': p.relative_to(out).as_posix(), 'sha256': _sha(p), 'bytes': p.stat().st_size}
             for p in sorted(out.rglob('*')) if p.is_file()]
    _write(out / 'manifest.json', {'schema_version': 1, 'complete': complete, 'exit_code': result['exit_code'],
        'code_hash': initial_code_hash, 'script_sha256': _sha(script), 'calibration_dir': str(packet),
        'params': params, 'files': files, 'saved_Run_adoption': False, 'scope': SCOPE})
    return {**result, 'artifact_dir': str(out), 'complete': complete}


if __name__ == '__main__':
    if len(sys.argv) == 6 and sys.argv[1] == '--worker':
        raise SystemExit(_worker(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve(), Path(sys.argv[4]).resolve(), json.loads(sys.argv[5])))
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--calibration-dir', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--horizon-s', type=float, default=5.0)
    parser.add_argument('--current-limit-A', type=float, default=.02)
    parser.add_argument('--ambient-K', type=float, default=299.15)
    parser.add_argument('--sell-price-per-kWh', type=float, default=.30)
    parser.add_argument('--seed', type=int, default=20261014)
    args = parser.parse_args()
    summary = run_consumer(args.root, args.calibration_dir, args.out, horizon_s=args.horizon_s,
        current_limit_A=args.current_limit_A, ambient_K=args.ambient_K,
        sell_price_per_kWh=args.sell_price_per_kWh, seed=args.seed)
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
    raise SystemExit(summary['exit_code'])
