"""Method fixtures are synthetic; saved S04 evidence is not a new trajectory."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest

from naheng.runtime.lifecycle_finance_endpoints import adopt_endpoints
from naheng.economics.lifecycle import FinancialAssumptions, from_lifecycle_result
from naheng.lifecycle.capacity_protocol import CapacityProtocol
from naheng.models.site_model import SiteModel, SiteParameters
from naheng.simulation.module import ModuleModel

ROOT = Path(__file__).resolve().parents[2]
SAVED = ROOT / 'tests/fixtures/lifecycle_finance/local_replacement_case.json'


def saved():
    return json.loads(SAVED.read_bytes())['result']


def source_model():
    # Exact declared parameters from the saved source script; no new ODE run.
    weak = SiteModel(replace(SiteParameters(), side_rate_s_inv=(.003, .003), accelerated_synthetic=True))
    return ModuleModel((weak, SiteModel(), SiteModel(), SiteModel()))


def adopt(value=None, model=None):
    return adopt_endpoints(saved() if value is None else value,
                           source_ref='artifacts/lifecycle_validation/local_replacement_case.json#result',
                           model=source_model() if model is None else model,
                           protocol=CapacityProtocol(retirement_ratio=.955))


def test_real_saved_module_endpoint_generations_capacity_and_unknown_rul():
    value = saved()
    initial, final, events, audit = adopt(value)
    assert [x.asset_id for x in initial.assets] == [f'cell-{i}:generation-0' for i in range(1, 5)]
    assert [x.asset_id for x in final.assets] == ['cell-1:generation-1', 'cell-2:generation-0',
                                                'cell-3:generation-0', 'cell-4:generation-0']
    assert audit['generation_count_by_cell'] == [1, 0, 0, 0]
    assert len(events) == 1 and events[0].asset_id == 'cell-1:generation-0'
    assert events[0].introduced_asset_id == 'cell-1:generation-1'
    assert all(x.rul_s is None for x in initial.assets + final.assets)
    assert initial.soc == pytest.approx(.6)
    assert final.soc == pytest.approx(sum(.012 * row[0] + .008 * row[1] for row in value['final_state']) / .08)
    assert [a.capacity_C for a in final.assets] == [r['protocol']['capacity_C'] for r in value['final_protocol_diagnostics']]
    assert audit['macro_endpoint_is_projection'] and final.evidence_kind == 'conditional_projection'


def test_actual_saved_module_pure_finance_adapter_without_new_operating_cash():
    value = saved()
    initial, final, events, _ = adopt(value)
    result = from_lifecycle_result(value, run_id='saved-S04-module-review', initial=initial, final=final,
                                  assumptions=FinancialAssumptions('synthetic source', 'same-S04-module', value['elapsed_s']),
                                  source_ref='artifacts/lifecycle_validation/local_replacement_case.json#result',
                                  cash_events=events).to_dict()
    assert result['realized_cash_CNY'] is not None
    assert 'conditional terminal' in result['scope']


def test_four_cell_soc_uses_all_heterogeneous_site_capacities_not_mean_cell_soc():
    capacities = ((.01, .02), (.02, .02), (.04, .01), (.01, .01))
    module = ModuleModel(tuple(SiteModel(replace(SiteParameters(), site_capacity_mol=n)) for n in capacities))
    state = module.initial_state()
    state[:, :2] = [[.1, .3], [.2, .4], [.5, .7], [.8, .9]]
    value = saved(); value['trace'][0]['state'] = state.tolist(); value['final_state'] = state.tolist()
    initial, final, _, _ = adopt(value, module)
    # Independently expanded numerator .001+.006+.004+.008+.020+.007+.008+.009.
    assert initial.soc == pytest.approx(.063 / .14)
    assert final.soc == pytest.approx(.45)
    assert final.soc != pytest.approx((.1 + .3 + .2 + .4 + .5 + .7 + .8 + .9) / 8)


@pytest.mark.parametrize('bad', [None, [1, 2], [[.2] * 5] * 3, [[.2] * 5] * 5,
                               [[float('nan'), .2, 0, .02, 298.15]] * 4,
                               [[1.1, .2, 0, .02, 298.15]] * 4])
def test_unknown_or_invalid_module_moment_returns_none(bad):
    value = saved(); value['final_state'] = bad
    _, final, _, _ = adopt(value)
    assert final.soc is None


def test_invalid_capacity_weights_do_not_fabricate_soc():
    module = source_model()
    # Explicit method-only malformed parameters, not a physical model acceptance.
    object.__setattr__(module.cells[0].params, 'site_capacity_mol', (float('nan'), .01))
    _, final, _, _ = adopt(model=module)
    assert final.soc is None


def test_global_retirement_does_not_give_replacement_active_assets_lifetime():
    value = saved(); value['status'] = 'retired'; value['retirement_interval_s'] = [52., 56.]
    _, final, _, _ = adopt(value)
    assert final.status == 'retired'
    assert final.assets[0].asset_id == 'cell-1:generation-1'
    assert all(a.rul_s is None and a.rul_status == 'unknown' for a in final.assets)


def test_cell_replacement_generations_are_independent():
    value = saved()
    second = deepcopy(value['maintenance'][0]); second.update(cell_id='cell-4', time_s=54.)
    value['maintenance'].append(second)
    _, final, events, audit = adopt(value)
    assert audit['generation_count_by_cell'] == [1, 0, 0, 1]
    assert final.assets[0].asset_id == 'cell-1:generation-1'
    assert final.assets[3].asset_id == 'cell-4:generation-1'
    assert events[1].asset_id == 'cell-4:generation-0'


def test_competing_per_cell_capacity_exit_preserves_unknown_without_other_cell_loss():
    value = saved()
    row = value['final_protocol_diagnostics'][2]
    row['protocol']['events'].append({'name': 'temperature_high', 'time_s': row['protocol']['elapsed_s']})
    _, final, _, _ = adopt(value)
    assert final.assets[2].capacity_C is None and final.assets[2].pristine_capacity_C is None
    assert final.assets[0].capacity_C is not None and final.assets[3].capacity_C is not None


def test_fake_per_cell_charge_and_competing_storage_remain_unknown():
    value = saved()
    value['final_protocol_diagnostics'][1]['protocol']['capacity_C'] += 1.
    value['economics']['final_stored_energy_probe']['events'].append({'name': 'reservoir_depleted', 'time_s': 1.})
    _, final, _, audit = adopt(value)
    assert final.assets[1].capacity_C is None
    assert final.stored_energy_J is None
    assert audit['final_storage']['reason'] == 'competing_storage_probe_exit'


def test_missing_trace_withholds_module_initial_soc_and_capacities():
    value = saved(); value['trace'] = []; value['status'] = 'budget_exhausted'
    initial, final, _, audit = adopt(value)
    assert initial.soc is None and all(x.capacity_C is None for x in initial.assets)
    assert final.status == 'unknown' and audit['initial_capacity_diagnostic_missing']


@pytest.mark.parametrize('model', [object(), SiteModel()])
def test_unsupported_model_or_wrong_topology_is_refused(model):
    with pytest.raises(ValueError):
        adopt(model=model)


def test_endpoint_cell_count_must_match_declared_four_series_model():
    value = saved(); value['final_protocol_diagnostics'] = value['final_protocol_diagnostics'][:3]
    value['trace'][0]['cells'] = value['trace'][0]['cells'][:3]
    with pytest.raises(ValueError, match='declared model topology'):
        adopt(value)
