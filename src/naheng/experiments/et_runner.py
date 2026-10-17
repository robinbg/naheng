"""E-T runner: measure formal-theory evidence over the frozen finite model families.

Preregistered hypothesis (configs/experiments/pilot.yaml, suite E-T, revision 5):

    Measure valid nontrivial general-family definitions, conditions, replayable
    counterexamples and checked evidence cost; novelty is classified separately.

This module implements the *measurement* layer of that suite plus the execution
entry point. Two rules shape it:

1. ``execute`` calls :func:`require_authorization` **before** doing anything, so a
   blocked, stale or tampered registration denies execution rather than producing
   a number. At revision 5 every suite is blocked, so this entry point currently
   refuses — by design, not by accident.
2. A metric that cannot be computed from the artifacts actually present is
   reported as ``null`` with a reason. Nothing is filled in with a plausible
   value, and a partial run never reports a complete result.

Registering the runner as an installed adapter is a separate, reviewable step
(``REGISTERED_ADAPTERS`` in ``naheng.experiments.preregistration``): this module
is the author side and does not register itself.
"""
from __future__ import annotations

import json
from pathlib import Path

from naheng.discovery.dataset import (build_dataset, candidate_templates, evaluate_holdout,
                                      freeze_selection, instantiate, search_feedback,
                                      training_feedback_rows)
from naheng.experiments.preregistration import DependencyBlocked, require_authorization

SCOPE = ('Finite affine site families on the declared synthetic model; measurements are '
         'computational evidence about candidate validity, not a claim of new natural law')
ALLOWED_AXIOMS = {'propext', 'Classical.choice', 'Quot.sound'}
EVALUABLE = ('counterexample_found', 'verified_condition', 'condition_not_satisfied')
DECIDED = ('counterexample_found', 'verified_condition')


def _rate(numerator: int, denominator: int):
    """A rate, or None when there is nothing to divide by — never a fake zero."""
    if denominator <= 0:
        return None
    return numerator / denominator


def _replay_passed(replay) -> bool | None:
    """Whether a numeric replay reproduced the analytic witness, or None if unrecognised.

    The discovery layer's record carries an explicit boolean,
    ``matches_exact_instantaneous_difference``, alongside ``status='replayed'``.
    An unrecognised shape yields None so the row is excluded from the denominator
    rather than silently counted as a failure — an unreadable record is not
    evidence that the replay failed.
    """
    if not isinstance(replay, dict):
        return None
    for key in ('matches_exact_instantaneous_difference', 'reproduced', 'passed', 'matches'):
        if key in replay and isinstance(replay[key], bool):
            return replay[key]
    status = replay.get('status')
    if isinstance(status, str):
        if status in ('replayed', 'reproduced', 'passed', 'match'):
            return True
        if status in ('failed', 'mismatch', 'not_reproduced'):
            return False
    return None


def formal_evidence(root: Path):
    """Checked-theorem accounting over every published formal suite manifest.

    The glob also reaches manifests that are not suite manifests (setup and
    candidate directories). Those are counted as skipped and named, never
    silently dropped from the denominator's provenance.
    """
    manifests = sorted((Path(root) / 'artifacts' / 'formal').glob('*/manifest.json'))
    total = checked = 0
    suites = {}
    skipped = []
    for manifest_path in manifests:
        try:
            payload = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            skipped.append({'manifest': manifest_path.parent.name, 'reason': 'unreadable'})
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get('targets'), list):
            skipped.append({'manifest': manifest_path.parent.name,
                            'reason': 'not a suite manifest (no target list)'})
            continue
        targets = payload['targets']
        audit = payload.get('audit') or {}
        audit_targets = audit.get('targets') or {}
        suite_checked = 0
        for name in targets:
            total += 1
            axioms = audit_targets.get(name)
            if isinstance(axioms, list) and set(axioms) <= ALLOWED_AXIOMS:
                checked += 1
                suite_checked += 1
        suites[payload.get('suite') or manifest_path.parent.name] = {
            'targets': len(targets), 'checked': suite_checked,
            'status': payload.get('status')}
    return {'total_targets': total, 'checked_targets': checked, 'suites': suites,
            'checked_theorem_rate': _rate(checked, total),
            'manifests_present': len(manifests), 'manifests_skipped': skipped}


def _evaluate_pairs(models, templates, wall_budget_s):
    from naheng.discovery.counterexamples import evaluate_candidate
    rows = []
    for model in models:
        for template in templates:
            row = evaluate_candidate(instantiate(template, model), model, wall_budget_s)
            row['template_id'] = template['template_id']
            rows.append(row)
    return rows


def measure(root, *, seed: int = 20261014, wall_budget_s: float = 1.0,
            heldout: bool = True):
    """Compute the preregistered E-T metrics from real computations.

    Training families drive the coverage/unknown/replay/cost metrics. The
    heldout metric uses the discovery layer's frozen selection flow so that the
    test families are never used for selection.
    """
    root = Path(root)
    dataset = build_dataset(seed)
    templates = candidate_templates()
    training = dataset['roles']['train']
    rows = _evaluate_pairs(training, templates, wall_budget_s)

    evaluable = [r for r in rows if r['status'] in EVALUABLE]
    decided = [r for r in rows if r['status'] in DECIDED]
    unknown = [r for r in rows if r['status'] == 'timeout_unknown']
    counterexamples = [r for r in rows if r['status'] == 'counterexample_found']
    replay_verdicts = [_replay_passed(r.get('numeric_replay')) for r in counterexamples]
    replayed = [v for v in replay_verdicts if v is True]
    replay_unknown = [v for v in replay_verdicts if v is None]
    replay_measured = [v for v in replay_verdicts if v is not None]

    metrics = {
        'applicable_domain_coverage': _rate(len(evaluable), len(rows)),
        'checked_theorem_rate': formal_evidence(root)['checked_theorem_rate'],
        'heldout_model_family_generalization': None,
        'unknown_rate': _rate(len(unknown), len(rows)),
        # Denominator is the counterexamples whose replay record was readable. If
        # none were readable the rate is None, not 0: an unreadable record is not
        # evidence that the replay failed.
        'counterexample_replay_rate': _rate(len(replayed), len(replay_measured)),
        'solver_total_time_s': sum(float(r.get('wall_s') or 0.) for r in rows),
        'candidate_count': len(rows),
        'complexity': None,
        'downstream_value': None,
        'known_vs_new_result_identity': None,
    }
    notes = {
        'applicable_domain_coverage': 'fraction of training (template, model) pairs whose declared '
                                      'premises were evaluable on the model',
        'checked_theorem_rate': 'published formal targets whose transitive axioms stay inside '
                                'propext/Classical.choice/Quot.sound, over all suite manifests present',
        'counterexample_replay_rate': f'{len(replay_measured)} of {len(counterexamples)} '
                                      f'counterexample(s) had a readable replay record; '
                                      f'{len(replay_unknown)} were unreadable and excluded from the '
                                      'denominator rather than counted as failures',
        'complexity': 'reported from the frozen selection scope when the heldout step runs',
        'downstream_value': 'requires the runtime-linkage measurement (suite E-L); out of scope here',
        'known_vs_new_result_identity': 'requires the literature classification in docs/NOVELTY.md, '
                                        'which is a manual author judgement and is not inferred here',
    }

    heldout_detail = None
    if heldout:
        try:
            feedback = search_feedback(templates, training, wall_budget_s)
            selection = freeze_selection(templates, feedback)
            test_models = dataset['roles']['test']
            heldout_rows = evaluate_holdout(selection, templates, test_models, 'test', wall_budget_s)
            per_model = {}
            for row in heldout_rows:
                per_model.setdefault(row['model_id'], []).append(row)
            generalized = sum(1 for group in per_model.values()
                              if any(r['status'] in DECIDED for r in group))
            metrics['heldout_model_family_generalization'] = _rate(generalized, len(per_model))
            metrics['complexity'] = {
                'templates_total': len(templates),
                'selection_scope': selection.get('candidate_selection_scope'),
                'selection_frozen': bool(selection.get('frozen')),
                'selection_is_subset': False,
                'note': 'the frozen selection is a declared enumeration scope over all templates, '
                        'not a reduced subset, so there is no selected-count to report'}
            notes['heldout_model_family_generalization'] = (
                'fraction of heldout test families where at least one frozen-selected candidate was '
                'decided (verified or refuted) without using test families for selection')
            heldout_detail = {'models': len(per_model), 'rows': len(heldout_rows),
                              'generalized_models': generalized}
        except Exception as error:  # noqa: BLE001 - an unusable holdout is reported, not invented
            notes['heldout_model_family_generalization'] = f'heldout measurement unavailable: {error!r}'

    return {'suite': 'E-T', 'metrics': metrics, 'metric_notes': notes,
            'training': {'models': len(training), 'templates': len(templates), 'rows': len(rows),
                         'evaluable': len(evaluable), 'decided': len(decided),
                         'unknown': len(unknown), 'counterexamples': len(counterexamples),
                         'replayed': len(replayed)},
            'heldout': heldout_detail,
            'formal': formal_evidence(root),
            'scope': SCOPE, 'experiment_executed': True,
            'new_independent_scientific_N': 0, 'novelty_classified': False}


def execute(root, registration_path, out, *, wall_budget_s: float = 1.0, heldout: bool = True):
    """Authorized entry point. Refuses before computing anything when unauthorized."""
    root = Path(root).resolve()
    out = Path(out).resolve()
    if not out.is_relative_to(root / 'artifacts'):
        raise ValueError('Project-owned experiment output required')
    try:
        authorization = require_authorization(root, registration_path, 'E-T')
    except DependencyBlocked as error:
        return {'suite': 'E-T', 'exit_code': 2, 'status': 'blocked',
                'reason': str(error), 'experiment_executed': False,
                'new_independent_scientific_N': 0,
                'scope': 'Authorization refused before any computation; no metric was produced'}
    result = measure(root, wall_budget_s=wall_budget_s, heldout=heldout)
    result.update(exit_code=0, status='completed', authorization=authorization,
                  registration_path=str(Path(registration_path).resolve()))
    out.mkdir(parents=True, exist_ok=False)
    (out / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    return result
