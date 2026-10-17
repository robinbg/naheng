"""Author tests for the proposed runtime draft; they are not independent review.

One real thermal-stop calculation and one original cutoff comparison are used.
Small returned-result fixtures calibrate exit classification without claiming
model evidence, formal proof, or application acceptance.
"""
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
original_spec = importlib.util.spec_from_file_location('original_capacity_frozen', Path(__file__).resolve().parents[2]/'artifacts/review/capacity-protocol-proposed-change-20261013/original_capacity_protocol.py')
original_module = importlib.util.module_from_spec(original_spec)
sys.modules[original_spec.name] = original_module
original_spec.loader.exec_module(original_module)
original_capacity = original_module.protocol_capacity
from naheng.models.site_model import SiteModel

from naheng.lifecycle import capacity_protocol as draft


class ResultFixtureModel(SiteModel):
    fixture_events = []
    fixture_elapsed_s = 10.0
    fixture_error = None
    calls = 0

    def integrate(self, state, current_A, duration_s, ambient_K):
        type(self).calls += 1
        if self.fixture_error is not None:
            raise self.fixture_error
        return SimpleNamespace(events=self.fixture_events, elapsed_s=self.fixture_elapsed_s,
                               inventory_residual_mol=0.0)


def test_zero_accessibility_does_not_invent_a_cutoff(monkeypatch):
    model = ResultFixtureModel()
    state = model.initial_state()
    state[2] = sum(model.params.site_capacity_mol)
    monkeypatch.setattr(ResultFixtureModel, 'calls', 0)
    result = draft.protocol_capacity(model, state)
    assert result['status'] == 'unknown' and result['capacity_C'] is None
    assert result['reason'] == 'zero_accessibility_without_voltage_cutoff_witness'
    assert result['delivered_charge_C'] == result['elapsed_s'] == 0
    assert ResultFixtureModel.calls == 0


@pytest.mark.parametrize('events,elapsed,status,reason', [
    ([{'name': 'voltage_low'}], 10.0, 'computed', 'observed_numerical_voltage_cutoff'),
    ([], 60.0, 'right_censored', 'maximum_duration_without_voltage_cutoff'),
    ([{'name': 'temperature_high'}], 10.0, 'unknown', 'competing_protocol_exit'),
    ([{'name': 'reservoir_depleted'}], 10.0, 'unknown', 'competing_protocol_exit'),
    ([{'name': 'voltage_high'}], 10.0, 'unknown', 'competing_protocol_exit'),
    ([{'name': 'temperature_low'}], 60.0, 'unknown', 'competing_protocol_exit'),
    ([{'name': 'voltage_low'}, {'name': 'temperature_high'}], 10.0, 'unknown', 'competing_protocol_exit'),
    ([], 10.0, 'unknown', 'incomplete_protocol_horizon'),
])
def test_returned_result_exit_classification(monkeypatch, events, elapsed, status, reason):
    monkeypatch.setattr(ResultFixtureModel, 'fixture_events', events)
    monkeypatch.setattr(ResultFixtureModel, 'fixture_elapsed_s', elapsed)
    model = ResultFixtureModel()
    protocol = draft.CapacityProtocol(maximum_duration_s=60.0)
    result = draft.protocol_capacity(model, model.initial_state(), protocol)
    assert result['status'] == status and result['reason'] == reason
    assert result['delivered_charge_C'] == protocol.discharge_current_A * elapsed
    assert result['capacity_C'] == (elapsed if status == 'computed' else None)
    assert result['capacity_lower_bound_C'] == (elapsed if status != 'unknown' else None)
    assert result['protocol_id'] == 'synthetic_capacity_v1'
    assert result['initialization_assumption'] == 'trapped_accessibility_v1'


def test_solver_failure_is_unknown_without_fabricated_charge(monkeypatch):
    monkeypatch.setattr(ResultFixtureModel, 'fixture_error', RuntimeError('solver did not provide a result'))
    model = ResultFixtureModel()
    result = draft.protocol_capacity(model, model.initial_state())
    assert result['status'] == 'unknown' and result['capacity_C'] is None
    assert result['delivered_charge_C'] is None


def test_actual_thermal_exit_keeps_delivered_charge_and_capacity_unknown():
    base = SiteModel()
    model = SiteModel(replace(base.params, temperature_max_K=298.151,
                             thermal_conductance_W_per_K=0.0))
    result = draft.protocol_capacity(model, model.initial_state(), draft.CapacityProtocol(maximum_duration_s=60.0))
    assert any(event['name'] == 'temperature_high' for event in result['events'])
    assert 0 < result['elapsed_s'] < 60
    assert result['status'] == 'unknown' and result['reason'] == 'competing_protocol_exit'
    assert result['capacity_C'] is result['capacity_Ah'] is result['capacity_lower_bound_C'] is None
    assert result['delivered_charge_C'] == pytest.approx(result['elapsed_s'])


def test_actual_original_voltage_cutoff_capacity_is_preserved():
    model = SiteModel()
    protocol = draft.CapacityProtocol()
    state = model.initial_state()
    original = original_capacity(model, state, protocol)
    result = draft.protocol_capacity(model, state, protocol)
    assert original['status'] == result['status'] == 'computed'
    assert any(event['name'] == 'voltage_low' for event in result['events'])
    assert result['capacity_C'] == pytest.approx(original['capacity_C'], rel=1e-10, abs=1e-8)
    assert result['elapsed_s'] == pytest.approx(original['elapsed_s'], rel=1e-10, abs=1e-8)
    assert result['delivered_charge_C'] == result['capacity_C']
