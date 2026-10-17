"""Two independently exposed parser failures, with literal altered bad copies."""
from copy import deepcopy
import pytest
from test_periodic_exposure import saved,adapted


def test_unknown_source_execution_mode_never_becomes_realized_cash():
    bad=deepcopy(saved()['fine'])
    bad['phases'][0]['execution_mode']='unknown_future_integrator'
    with pytest.raises(ValueError,match='execution mode'):
        adapted(bad,'fine')


def test_missing_complete_periodic_metadata_is_explicit_rejection_not_keyerror():
    bad=deepcopy(saved()['macro'])
    for field in ('aggregation','cycle_period_s','phase_offset_s'):
        del bad['phases'][0][field]
    with pytest.raises(ValueError,match='periodic metadata'):
        adapted(bad,'macro')
