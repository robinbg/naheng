"""Audit variants are explicit and excluded from the common actual-case frontier."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from naheng.runtime.lifecycle_finance_session import _validate_registration

ROOT = Path(__file__).resolve().parents[2]


def test_separate_audits_do_not_change_common_case_and_terminal_conditions():
    registration = json.loads((ROOT / 'configs/experiments/lifecycle-finance-pilot-v1.json').read_bytes())
    assumptions = _validate_registration(registration)
    assert registration['protocol']['retirement_ratio'] == .995
    assert registration['macro_audit']['protocol']['retirement_ratio'] == .8
    assert registration['macro_audit']['included_in_actual_frontier'] is False
    assert registration['early_exit_audit']['included_in_actual_frontier'] is False
    assert registration['early_exit_audit']['maximum_replacements'] == 0
    assert registration['maximum_replacements'] == 1
    assert len(registration['cases']) == len(registration['policies']) == 2
    assert assumptions.scheduled_horizon_s == 48.


@pytest.mark.parametrize('path,value', [
    (('macro_audit', 'included_in_actual_frontier'), True),
    (('macro_audit', 'protocol'), {'protocol_id': 'synthetic_capacity_v1', 'retirement_ratio': .995}),
    (('macro_audit', 'case_id'), 'unknown'),
    (('early_exit_audit', 'included_in_actual_frontier'), True),
    (('early_exit_audit', 'maximum_replacements'), False),
    (('early_exit_audit', 'policy_id'), 'unknown'),
])
def test_unregistered_or_mixed_audit_is_refused(path, value):
    registration = json.loads((ROOT / 'configs/experiments/lifecycle-finance-pilot-v1.json').read_bytes())
    registration[path[0]][path[1]] = value
    with pytest.raises(ValueError):
        _validate_registration(registration)
