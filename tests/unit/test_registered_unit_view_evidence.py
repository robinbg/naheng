"""Reject inflated or detached view claims while preserving scientific unknowns."""
import copy
import importlib.util
import json
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Every test here drives validate_new_source against the frozen registry, whose
# pinned chain ends in derived views of a third-party dataset that is not
# redistributed. Without that data the validator raises for the wrong reason, so
# the negative cases would pass vacuously — the same failure mode as a probe that
# scores agreement on "unknown" as success. Skipping keeps "not run here" visibly
# different from "passed"; present-but-different bytes still fail the assertion.
from naheng.data.registry_availability import SKIP_REASON, unit_view_evidence_available  # noqa: E402

pytestmark = pytest.mark.skipif(not unit_view_evidence_available(), reason=SKIP_REASON)


def source_and_tool():
    spec = importlib.util.spec_from_file_location('source_view_gate', ROOT / 'tools/data_source_integration.py')
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    index = json.loads((ROOT / 'data/manifests/sources.yaml').read_text(encoding='utf-8'))
    source = copy.deepcopy(next(s for s in index['sources'] if s['source_id'] == 'zenodo13836819_sodium_soc_original_members'))
    return source, tool


@pytest.mark.parametrize('corruption', ['missing_review', 'changed_handoff_hash', 'changed_member_rows', 'changed_view_hash'])
def test_reopened_claim_requires_actual_bound_evidence(corruption):
    source, tool = source_and_tool()
    if corruption == 'missing_review':
        source['canonical_view_acceptance'].pop('independent_review')
    elif corruption == 'changed_handoff_hash':
        source['canonical_view_acceptance']['normal_entry_handoff']['sha256'] = '0' * 64
    elif corruption == 'changed_member_rows':
        source['raw_members'][0]['canonical_view']['rows'] -= 1
    else:
        source['raw_members'][0]['canonical_view']['view_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='Unit-view|unit-view'):
        tool.validate_new_source(source)


def test_reopened_view_does_not_authorize_dataset_roles_or_fit():
    for field, value in [('split_assignment_status', 'assigned'), ('model_fit_status', 'fitted'),
                         ('external_model_validation', 'verified')]:
        source, tool = source_and_tool()
        source[field] = value
        with pytest.raises(ValueError, match='splitting, model fitting or external validation'):
            tool.validate_new_source(source)


@pytest.mark.parametrize('field', ['canonical_current_sign', 'canonical_units'])
def test_registered_summary_cannot_drift_from_checked_view(field):
    source, tool = source_and_tool()
    view = source['raw_members'][0]['canonical_view']
    view[field] = 'unverified_replacement'
    with pytest.raises(ValueError, match='current sign or units summary'):
        tool.validate_new_source(source)


def test_unrelated_successful_review_cannot_authorize_this_cohort(tmp_path):
    source, tool = source_and_tool()
    acceptance = source['canonical_view_acceptance']
    handoff = json.loads((ROOT / acceptance['normal_entry_handoff']['path']).read_text(encoding='utf-8'))
    review = json.loads((ROOT / acceptance['independent_review']['path']).read_text(encoding='utf-8'))
    # Deliberately corrupt only the fixture's identity; real evidence stays intact.
    review['members'][0]['raw'] = 'another_cohort.csv'
    for name, payload, field in [('handoff.json', handoff, 'normal_entry_handoff'), ('review.json', review, 'independent_review')]:
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding='utf-8')
        acceptance[field] = {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    tool.ROOT = tmp_path
    with pytest.raises(ValueError, match='Independent unit-view member coverage'):
        tool.validate_new_source(source)


@pytest.mark.parametrize('missing', ['all', 'validator'])
def test_matching_but_incomplete_baselines_cannot_pass_vacuously(tmp_path, missing):
    source, tool = source_and_tool()
    acceptance = source['canonical_view_acceptance']
    handoff = json.loads((ROOT / acceptance['normal_entry_handoff']['path']).read_text(encoding='utf-8'))
    review = json.loads((ROOT / acceptance['independent_review']['path']).read_text(encoding='utf-8'))
    if missing == 'all':
        handoff['public_files_sha256'] = {}
    else:
        handoff['public_files_sha256'].pop('tools/validate_zenodo_csv.py')
    review['public_baseline_sha256'] = handoff['public_files_sha256'].copy()
    for name, payload, field in [('handoff.json', handoff, 'normal_entry_handoff'), ('review.json', review, 'independent_review')]:
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding='utf-8')
        acceptance[field] = {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    tool.ROOT = tmp_path
    with pytest.raises(ValueError, match='baseline requires all three exact files'):
        tool.validate_new_source(source)
