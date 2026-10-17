"""Four-series audit preserves the original paired single-cell denominator."""
import json
from pathlib import Path
import pytest
from naheng.runtime.lifecycle_finance_session import _validate_registration

ROOT = Path(__file__).resolve().parents[2]


def test_module_audit_is_a_separate_explicit_four_cell_configuration():
    config = json.loads((ROOT / 'configs/experiments/lifecycle-finance-pilot-v1.json').read_bytes())
    _validate_registration(config)
    assert config['module_audit']['included_in_actual_frontier'] is False
    assert config['module_audit']['topology'] == '4s'
    assert len(config['module_audit']['cell_overrides']) == 4
    assert len(config['cases']) == len(config['policies']) == 2


@pytest.mark.parametrize('key,value', [('topology', '4p'), ('coupling_W_per_K', -1.),
                                    ('included_in_actual_frontier', True), ('cell_overrides', [{}, {}])])
def test_unregistered_module_topology_or_mixed_primary_case_is_refused(key, value):
    config = json.loads((ROOT / 'configs/experiments/lifecycle-finance-pilot-v1.json').read_bytes())
    config['module_audit'][key] = value
    with pytest.raises(ValueError):
        _validate_registration(config)
