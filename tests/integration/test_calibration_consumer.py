"""Author bounded controls; cloned receipts are synthetic method fixtures only."""
import copy
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch
import uuid

from naheng.runtime import calibration_consumer as C
from naheng.estimation.calibration_session import run_calibration
ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / 'artifacts/calibration' / ('consumer-test-input-' + uuid.uuid4().hex[:8])
BASE = ROOT / 'artifacts/calibration' / ('consumer-controls-' + uuid.uuid4().hex[:8])
BASE.mkdir(parents=True, exist_ok=False)


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


class ConsumerControls(unittest.TestCase):
    count = 0

    @classmethod
    def setUpClass(cls):
        result = run_calibration(ROOT, ROOT / 'tests/fixtures/calibration_builtin/request.json', PACKET)
        assert result['exit_code'] == 0 and result['complete']

    def fixture(self, change=None):
        ConsumerControls.count += 1
        packet = BASE / ('p' + str(ConsumerControls.count))
        packet.mkdir()
        for original in PACKET.iterdir():
            if original.is_file():
                (packet / original.name).write_bytes(original.read_bytes())
        if change:
            payload, result = C._read(packet / 'input.json'), C._read(packet / 'result.json')
            change(payload, result)
            dump(packet / 'input.json', payload)
            dump(packet / 'result.json', result)
        mf, start, worker = (C._read(packet / name) for name in ('manifest.json', 'started.json', 'worker-command.json'))
        worker['command'][5:7] = [str(packet / 'input.json'), str(packet)]
        worker['log'] = str(packet / 'worker.log')
        start['argv'] = worker['command']
        mf['input_sha256'] = start['input_sha256'] = C._sha(packet / 'input.json')
        mf['result_sha256'] = C._sha(packet / 'result.json')
        dump(packet / 'manifest.json', mf)
        dump(packet / 'started.json', start)
        dump(packet / 'worker-command.json', worker)
        old = (packet / 'worker.log').read_text(encoding='utf-8')
        tail = old.split('\n\n--- STDOUT ---\n', 1)[1]
        (packet / 'worker.log').write_text(json.dumps(worker, ensure_ascii=False, indent=2) + '\n\n--- STDOUT ---\n' + tail, encoding='utf-8')
        (packet / 'FIXTURE_ONLY.txt').write_text('Synthetic re-bound receipt structure for negative method tests; not a real calibration worker run.', encoding='utf-8')
        return packet

    def params(self):
        return C._parameters(5, .02, 299.15, .30, 20261014)

    def test_original_current_owned_packet_and_raw_defaults(self):
        before = {p.name: C._sha(p) for p in PACKET.iterdir() if p.is_file()}
        loaded = C._packet(ROOT.resolve(), PACKET)
        self.assertEqual(loaded['candidate'].posterior.obs_until_s, 40)
        self.assertEqual(len(loaded['snapshot'].samples), 8)
        self.assertNotIn('schema_version', loaded['package'])
        self.assertEqual(loaded['request'].model_package.model_dump(mode='json', exclude_unset=True), loaded['package'])
        self.assertEqual(before, {p.name: C._sha(p) for p in PACKET.iterdir() if p.is_file()})

    def test_stale_code_hash_is_unknown(self):
        packet = self.fixture()
        mf = C._read(packet / 'manifest.json'); mf['code_hash'] = '0' * 64; dump(packet / 'manifest.json', mf)
        with self.assertRaisesRegex(C.ConsumerUnknown, 'implementation'):
            C._packet(ROOT.resolve(), packet)

    def test_input_bytes_hash_mismatch(self):
        packet = self.fixture(); (packet / 'input.json').write_bytes((packet / 'input.json').read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'bytes'):
            C._packet(ROOT.resolve(), packet)

    def test_result_bytes_hash_mismatch(self):
        packet = self.fixture(); (packet / 'result.json').write_bytes((packet / 'result.json').read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'bytes'):
            C._packet(ROOT.resolve(), packet)

    def test_worker_timeout_even_if_manifest_claims_zero(self):
        packet = self.fixture(); worker = C._read(packet / 'worker-command.json'); worker['timed_out'] = True; dump(packet / 'worker-command.json', worker)
        with self.assertRaisesRegex(ValueError, 'budget'):
            C._packet(ROOT.resolve(), packet)

    def test_worker_log_receipt_mismatch(self):
        packet = self.fixture(); (packet / 'worker.log').write_text('{}\n\n--- STDOUT ---\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'log/command'):
            C._packet(ROOT.resolve(), packet)

    def test_worker_argv_targets_other_packet(self):
        packet = self.fixture(); worker = C._read(packet / 'worker-command.json'); worker['command'][6] = str(PACKET); dump(packet / 'worker-command.json', worker)
        with self.assertRaisesRegex(ValueError, 'argv/path'):
            C._packet(ROOT.resolve(), packet)

    def test_missing_actual_forward_grant(self):
        packet = self.fixture(lambda p, r: r['integration_verification'].update(actual_parent_forward_predictions_recomputed=False))
        with self.assertRaisesRegex(ValueError, 'adoption-time recomputation'):
            C._packet(ROOT.resolve(), packet)

    def test_candidate_sha_mismatch_after_receipt_rehash(self):
        packet = self.fixture(lambda p, r: r['calibration'].update(candidate_content_sha256='1' * 64))
        with self.assertRaisesRegex(ValueError, 'Candidate content'):
            C._packet(ROOT.resolve(), packet)

    def test_heldout_observations_rejected_after_receipt_rehash(self):
        for role in ('validation', 'test', 'stress'):
            with self.subTest(role=role):
                packet = self.fixture(lambda p, r: p['batch']['observations'][0].update(role=role))
                with self.assertRaisesRegex(ValueError, 'Training eligibility'):
                    C._packet(ROOT.resolve(), packet)

    def test_unknown_source_not_authorized(self):
        packet = self.fixture(lambda p, r: p['prior']['binding'].update(source_identity_status='UNKNOWN'))
        with self.assertRaisesRegex(ValueError, 'Training eligibility'):
            C._packet(ROOT.resolve(), packet)

    def test_other_chemistry_not_mixed(self):
        packet = self.fixture(lambda p, r: p['prior']['binding'].update(chemistry_id='unverified_real_cell'))
        with self.assertRaises(ValueError):
            C._packet(ROOT.resolve(), packet)

    def test_future_missing_propagation_not_current_state(self):
        packet = self.fixture(lambda p, r: p['batch'].update(propagated_joint_samples=None, propagated_until_s=None, propagation_evidence=None))
        with self.assertRaisesRegex(ValueError, 'Training eligibility'):
            C._packet(ROOT.resolve(), packet)

    def test_propagation_cannot_change_parameter_columns(self):
        def change(p, r): p['batch']['propagated_joint_samples'][0][-2] += .1
        with self.assertRaisesRegex(ValueError, 'Training eligibility'):
            C._packet(ROOT.resolve(), self.fixture(change))

    def test_no_noise_not_zero_noise(self):
        with self.assertRaisesRegex(ValueError, 'Missing likelihood'):
            C._packet(ROOT.resolve(), self.fixture(lambda p, r: p.update(noise=None)))

    def test_parameter_defaults_change_raw_registered_hash(self):
        with self.assertRaisesRegex(ValueError, 'content hash'):
            C._packet(ROOT.resolve(), self.fixture(lambda p, r: p['model_package'].update(schema_version=1)))

    def test_casefold_private_or_escape_refs_rejected(self):
        marker = BASE / 'Evaluator'; marker.mkdir(); data = marker / 'probe.json'; data.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'private evaluator'):
            C._public(data, ROOT.resolve())
        # After public installation __file__ is inside ROOT. Preserve the
        # original outside-file control using a real owned external fixture.
        with TemporaryDirectory(prefix='.nh-consumer-out-', dir=ROOT.parent) as directory:
            outside = Path(directory).resolve()
            assert outside.is_relative_to(ROOT.parent.resolve()) and not outside.is_relative_to(ROOT.resolve())
            probe = outside / 'synthetic-probe.json'
            probe.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'escaped ROOT'):
                C._public(probe, ROOT.resolve())

    def test_explicit_numeric_action_limits(self):
        bads = ((float('nan'), .02, 299.15, .3, 1), (11, .02, 299.15, .3, 1),
                (0, .02, 299.15, .3, 1), (5, 0, 299.15, .3, 1), (5, .02, float('inf'), .3, 1),
                (5, .02, 299.15, -.1, 1), (True, .02, 299.15, .3, 1), (5, .02, 299.15, .3, True))
        for args in bads:
            with self.subTest(args=str(args)), self.assertRaises(ValueError): C._parameters(*args)
        self.assertEqual(self.params()['horizon_s'], 5)

    def test_output_cannot_write_source_or_existing_evidence(self):
        with self.assertRaisesRegex(ValueError, 'controlled'):
            C.run_consumer(ROOT, PACKET, ROOT / 'src' / 'bad-output')
        existing = BASE / 'existing'; existing.mkdir(); (existing / 'marker').write_bytes(b'original')
        with self.assertRaisesRegex(ValueError, 'fresh'):
            C.run_consumer(ROOT, PACKET, existing)
        self.assertEqual((existing / 'marker').read_bytes(), b'original')

    def test_physical_action_domain_excess_rejected(self):
        out = BASE / 'domain'; out.mkdir()
        params = self.params(); params['current_limit_A'] = 999
        with self.assertRaisesRegex(ValueError, 'physical package domain'):
            C._execute(ROOT.resolve(), PACKET, out, params)

    def test_rejected_admission_does_not_execute_or_book_energy(self):
        out = BASE / 'rejected'; out.mkdir()
        with patch.object(C, 'admission_check', return_value={'decision': 'reject', 'reason': 'synthetic negative admission fixture'}), patch.object(C, 'particle_model') as evaluator:
            result = C._execute(ROOT.resolve(), PACKET, out, self.params())
        self.assertFalse(result['actual_executed'])
        self.assertEqual(result['actual_execution_energy_J'], 0)
        self.assertEqual(result['net_cashflow_CNY'], 0)
        self.assertFalse((out / 'evaluator').exists())
        evaluator.assert_not_called()
        ledger = C._read(out / 'ledger.json')
        self.assertEqual(ledger['summary']['unexecuted_proposals'], 1)
        self.assertFalse(ledger['forecast_energy_booked'])

    def test_active_thermal_requires_matching_forecast_policy(self):
        loaded = C._packet(ROOT.resolve(), PACKET)
        action = C.propose(loaded['snapshot'], .3, 40, 5, C.RuleParameters(current_limit_A=.02)).model_copy(update={'thermal_W': -.1})
        out = BASE / 'thermal'; out.mkdir()
        with patch.object(C, 'propose', return_value=action), patch.object(C, 'forecast') as forecast:
            with self.assertRaisesRegex(ValueError, 'thermal proposal'):
                C._execute(ROOT.resolve(), PACKET, out, self.params())
        forecast.assert_not_called()

    def math_rebind(self, payload, result):
        """Fixture creates coherent Gaussian math, not true forward evidence."""
        request = C.CalibrationRequest.model_validate_json(json.dumps(payload))
        fitted = C.fit_candidate(request.prior, request.batch, request.noise)
        self.assertEqual(fitted.status, 'PASS')
        result['calibration'] = fitted.model_dump(mode='json')
        result['calibration']['candidate_content_sha256'] = fitted.candidate.content_sha256
        result['calibration']['posterior_content_sha256'] = fitted.candidate.posterior.content_sha256
        result['calibration']['posterior_contract'] = C.posterior_to_contract(fitted.candidate).model_dump(mode='json')

    def test_math_rebound_fake_predictions_rejected_by_actual_dynamics(self):
        def change(payload, result):
            payload['batch']['particle_predictions'][0][0][0] += .004
            self.math_rebind(payload, result)
        packet = self.fixture(change)
        with self.assertRaisesRegex(ValueError, 'actual builtin forward recomputation'):
            C._packet(ROOT.resolve(), packet)

    def test_math_rebound_fake_final_state_rejected_by_actual_dynamics(self):
        def change(payload, result):
            payload['batch']['propagated_joint_samples'][0][0] += .001
            payload['batch']['propagated_derived_observables'][0]['particle_values'][0] += .0006
            self.math_rebind(payload, result)
        packet = self.fixture(change)
        with self.assertRaisesRegex(ValueError, 'actual builtin forward recomputation'):
            C._packet(ROOT.resolve(), packet)

    def test_raw_private_alias_that_resolves_public_is_rejected(self):
        marker = BASE / 'Evaluator'; marker.mkdir(exist_ok=True)
        target = BASE / 'normal-probe'; target.write_bytes(b'{}')
        alias = marker / '..' / target.name
        self.assertEqual(alias.resolve(), target.resolve())
        with self.assertRaisesRegex(ValueError, 'Raw public source'):
            C._public(alias, ROOT.resolve())


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ConsumerControls)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    dump(BASE / 'method-report.json', {'exit_code': 0 if result.wasSuccessful() else 1,
        'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
        'fixture_scope': 'Author negative receipt-structure fixtures and explicit unit controls; cloned metadata is not real worker evidence',
        'source_sha256': C._sha(Path(__file__).with_name('calibration_consumer.py')),
        'actual_current_input_packet': str(PACKET), 'packet_source_unchanged': True})
    print(json.dumps({'fixture_artifacts': str(BASE), 'exit_code': 0 if result.wasSuccessful() else 1}))
    raise SystemExit(0 if result.wasSuccessful() else 1)
