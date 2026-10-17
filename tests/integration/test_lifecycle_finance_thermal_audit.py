"""Nonzero thermal bookkeeping must be an explicit separate audit."""
import json
from pathlib import Path
import pytest
from naheng.runtime.lifecycle_finance_session import _validate_registration

ROOT = Path(__file__).resolve().parents[2]


def test_thermal_audit_preserves_the_primary_fixed_policy_registration():
    registration = json.loads((ROOT / 'configs/experiments/lifecycle-finance-pilot-v1.json').read_bytes())
    _validate_registration(registration)
    assert registration['thermal_audit']['thermal_W'] == .02
    assert registration['thermal_audit']['included_in_actual_frontier'] is False
    assert all('thermal_W' not in policy for policy in registration['policies'])


def test_thermal_audit_cannot_enter_the_primary_frontier():
    registration = json.loads((ROOT / 'configs/experiments/lifecycle-finance-pilot-v1.json').read_bytes())
    registration['thermal_audit']['included_in_actual_frontier'] = True
    with pytest.raises(ValueError):
        _validate_registration(registration)
