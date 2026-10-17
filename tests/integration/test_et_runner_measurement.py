"""E-T measurement layer and refusal discipline.

Two things matter here and are tested separately:

* the measurements are computed from real evaluations, and a value that cannot be
  computed is ``None`` rather than a plausible-looking number;
* ``execute`` refuses to compute anything at all unless the frozen preregistration
  authorizes the suite, and a refusal writes no result file.
"""
import json
from pathlib import Path

import pytest

from naheng.experiments import et_runner
from naheng.experiments.preregistration import DependencyBlocked

ROOT = Path(__file__).resolve().parents[2]
REGISTRATION = (ROOT / 'artifacts/experiments/preregistrations/'
                'naheng-joint-experiments-pilot/r5/registration.json')


def test_rate_is_none_rather_than_a_fake_zero():
    assert et_runner._rate(0, 0) is None
    assert et_runner._rate(3, 0) is None
    assert et_runner._rate(0, 4) == 0.0
    assert et_runner._rate(2, 4) == 0.5


def test_unreadable_replay_record_is_excluded_not_counted_as_failure():
    # The real record carries an explicit boolean; the status string is 'replayed'.
    assert et_runner._replay_passed({'matches_exact_instantaneous_difference': True,
                                     'status': 'replayed'}) is True
    assert et_runner._replay_passed({'matches_exact_instantaneous_difference': False}) is False
    # An unrecognised shape must not be silently read as a failure.
    assert et_runner._replay_passed({'something_else': 1}) is None
    assert et_runner._replay_passed(None) is None
    assert et_runner._replay_passed('replayed') is None


def test_formal_evidence_counts_only_allowed_axioms_and_names_skipped_manifests():
    report = et_runner.formal_evidence(ROOT)
    assert report['total_targets'] > 0 and report['manifests_present'] > 0
    assert 0.0 <= report['checked_theorem_rate'] <= 1.0
    # Every checked target must be accounted for by an allowed-axiom audit.
    assert report['checked_targets'] <= report['total_targets']
    # Non-suite manifests are named rather than silently dropped.
    for row in report['manifests_skipped']:
        assert row['manifest'] and row['reason']
    # The published core is fully checked, so its own rate must be 1.0.
    core = report['suites'].get('core')
    assert core is not None and core['targets'] > 0 and core['checked'] == core['targets']


def test_measurement_layer_reports_every_preregistered_metric():
    result = et_runner.measure(ROOT, wall_budget_s=1.0, heldout=True)
    metrics = result['metrics']
    for name in ('applicable_domain_coverage', 'checked_theorem_rate',
                 'heldout_model_family_generalization', 'unknown_rate',
                 'counterexample_replay_rate', 'solver_total_time_s', 'candidate_count',
                 'complexity', 'downstream_value', 'known_vs_new_result_identity'):
        assert name in metrics, name
    # Computable here, so they must be numbers, not placeholders.
    assert metrics['candidate_count'] > 0
    assert 0.0 <= metrics['applicable_domain_coverage'] <= 1.0
    assert metrics['solver_total_time_s'] >= 0.0
    # Not computable in this suite, so they stay None with a stated reason.
    assert metrics['downstream_value'] is None
    assert metrics['known_vs_new_result_identity'] is None
    for name in ('downstream_value', 'known_vs_new_result_identity'):
        assert result['metric_notes'][name]
    assert result['novelty_classified'] is False
    assert result['new_independent_scientific_N'] == 0


def test_replay_rate_uses_a_readable_denominator():
    result = et_runner.measure(ROOT, wall_budget_s=1.0, heldout=True)
    training = result['training']
    assert training['counterexamples'] > 0, 'this fixture set must produce counterexamples'
    assert training['replayed'] == training['counterexamples'], (
        'every produced counterexample must carry a readable replay verdict; a mismatch means the '
        'record shape changed and the rate would silently deflate')
    assert result['metrics']['counterexample_replay_rate'] == 1.0


def test_heldout_generalization_never_uses_test_families_for_selection():
    result = et_runner.measure(ROOT, wall_budget_s=1.0, heldout=True)
    assert result['heldout'] is not None
    assert result['heldout']['models'] > 0
    # The selection is a declared enumeration scope, and it is reported as such
    # rather than as a selected-count that does not exist.
    assert result['metrics']['complexity']['selection_is_subset'] is False
    assert result['metrics']['complexity']['selection_frozen'] is True


def test_execute_refuses_before_computing_when_unauthorized(tmp_path):
    out = ROOT / 'artifacts' / 'test-temp' / 'et-runner-refusal'
    if out.exists():
        import shutil
        shutil.rmtree(out)
    result = et_runner.execute(ROOT, REGISTRATION, out, wall_budget_s=1.0, heldout=False)
    assert result['exit_code'] == 2 and result['status'] == 'blocked'
    assert result['experiment_executed'] is False
    assert result['new_independent_scientific_N'] == 0
    assert result['reason']
    # A refusal must not leave a result behind: nothing was measured.
    assert not (out / 'result.json').exists()
    assert not out.exists()


def test_execute_rejects_an_output_outside_project_artifacts():
    with pytest.raises(ValueError, match='Project-owned'):
        et_runner.execute(ROOT, REGISTRATION, ROOT.parent / 'outside', wall_budget_s=1.0, heldout=False)
