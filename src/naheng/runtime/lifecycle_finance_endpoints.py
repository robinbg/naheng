"""Adopt S04 numerical endpoints without inventing capacity, storage or RUL.

The source caller authenticates the complete saved S04 result. Protocol and
storage probes are counterfactual numerical diagnostics, never operating sales.
"""
import math

import numpy as np
from naheng.economics.lifecycle import AssetEndpoint, CashEvent, TerminalState
from naheng.models.site_model import SiteModel
from naheng.simulation.module import ModuleModel


def storage_probe(probe, maximum_duration_s):
    """Recheck exit evidence; the original S04 status alone is insufficient."""
    result = {'energy_J': None, 'status': 'unknown', 'source_status': probe.get('status')}
    elapsed = probe.get('elapsed_s')
    events = probe.get('events')
    if (type(elapsed) not in (int, float) or not math.isfinite(elapsed)
            or not 0 <= elapsed <= maximum_duration_s + 1e-6 or not isinstance(events, list)
            or any(not isinstance(e, dict) or not isinstance(e.get('name'), str) for e in events)):
        return {**result, 'reason': 'missing_or_invalid_exit_evidence'}
    voltage = any(e['name'] == 'voltage_low' for e in events)
    competing = any(e['name'] != 'voltage_low' for e in events)
    energy = probe.get('energy_J')
    if competing:
        return {**result, 'reason': 'competing_storage_probe_exit'}
    if voltage:
        if any(type(e.get('time_s')) not in (int, float) or not math.isfinite(e['time_s'])
               or not math.isclose(e['time_s'], elapsed, abs_tol=1e-6, rel_tol=0) for e in events):
            return {**result, 'reason': 'invalid_cutoff_time_witness'}
        if type(energy) not in (int, float) or not math.isfinite(energy) or energy < 0:
            return {**result, 'reason': 'invalid_storage_energy'}
        return {**result, 'energy_J': energy, 'status': 'computed', 'reason': 'voltage_cutoff_only'}
    if elapsed >= maximum_duration_s - 1e-6:
        return {**result, 'status': 'right_censored', 'reason': 'complete_horizon_without_cutoff'}
    return {**result, 'reason': 'early_exit_without_cutoff'}


def capacity_diagnostic(row, protocol):
    """Validate the saved numerical cutoff/charge witness before taking capacity."""
    evidence = row['protocol']
    if evidence.get('protocol_id') != protocol.protocol_id:
        raise ValueError('Same preregistered capacity protocol required')
    if evidence.get('status') != 'computed':
        return None, None
    elapsed, capacity, pristine, soh = (evidence.get('elapsed_s'), evidence.get('capacity_C'),
                                        row.get('pristine_capacity_C'), row.get('soh'))
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (elapsed, capacity, pristine, soh)):
        return None, None
    events = evidence.get('events')
    if (elapsed > protocol.maximum_duration_s + 1e-6 or not isinstance(events, list) or not events
            or any(not isinstance(e, dict) or e.get('name') != 'voltage_low'
                   or type(e.get('time_s')) not in (int, float) or not math.isfinite(e['time_s'])
                   or not math.isclose(e['time_s'], elapsed, abs_tol=1e-6, rel_tol=0)
                   or type(e.get('limit')) not in (int, float)
                   or not math.isclose(e['limit'], protocol.cutoff_voltage_V, abs_tol=1e-8, rel_tol=0) for e in events)
            or not math.isclose(capacity, elapsed * protocol.discharge_current_A, abs_tol=1e-6, rel_tol=1e-10)
            or not math.isclose(soh, capacity / pristine, abs_tol=1e-10, rel_tol=1e-10)):
        return None, None
    return capacity, pristine


def adopt_endpoints(result, *, source_ref, model, protocol):
    """Use each cell's protocol capacity and maintenance generation in order."""
    if result.get('provenance_type') != 'synthetic':
        raise ValueError('Explicit numerical S04 result required')
    if isinstance(model, SiteModel):
        expected_cells = 1
    elif (isinstance(model, ModuleModel) and model.topology == '4s'
          and model.cell_count == 4 and len(model.cells) == 4
          and all(isinstance(cell, SiteModel) for cell in model.cells)):
        expected_cells = 4
    else:
        raise ValueError('Only SiteModel or the declared four-series ModuleModel is supported')
    trace = result['trace']
    if trace and trace[0]['time_s'] != 0:
        raise ValueError('Initial protocol diagnostic at time zero required')
    final_rows = result['final_protocol_diagnostics']
    initial_rows = trace[0]['cells'] if trace else [
        {'protocol': {'status': 'unknown', 'protocol_id': protocol.protocol_id}, 'soh': None,
         'pristine_capacity_C': None} for _ in final_rows]
    if len(initial_rows) != len(final_rows) or not initial_rows:
        raise ValueError('The same ordered cells are required at both endpoints')
    if len(final_rows) != expected_cells:
        raise ValueError('Endpoint cells must match the declared model topology')
    generations = [0] * len(initial_rows)
    events = []
    for index, row in enumerate(result['maintenance']):
        cell = int(row['cell_id'].removeprefix('cell-')) - 1
        if not 0 <= cell < len(generations) or row['cell_id'] != f'cell-{cell+1}' or row['kind'] != 'replacement':
            raise ValueError('Explicit original replacement cell identity required')
        old = f'cell-{cell+1}:generation-{generations[cell]}'
        generations[cell] += 1
        new = f'cell-{cell+1}:generation-{generations[cell]}'
        reference = source_ref + f'#maintenance[{index}]'
        projected_before = any(p['execution_mode'] == 'cycle_map_jump' and p['start_s'] < row['time_s']
                               for p in result['phases'])
        events.append(CashEvent(reference, reference, old, row['cell_id'], 'replacement',
                                row['time_s'], row['time_s'], row['replacement_cost'],
                                row['salvage_value'], reference,
                                classification='projected' if projected_before else 'actual', introduced_asset_id=new))
    projected = bool(result['macro_projected_ledger'])

    def assets(rows, *, initial):
        value = []
        for i, row in enumerate(rows):
            capacity, pristine = capacity_diagnostic(row, protocol)
            rul_status = 'right_censored' if not initial and result['status'] == 'right_censored' else 'unknown'
            ref = source_ref + (f'#trace[0].cells[{i}]' if initial and trace else '#initial_diagnostic_missing' if initial else f'#final_protocol_diagnostics[{i}]')
            value.append(AssetEndpoint(f'cell-{i+1}:generation-{0 if initial else generations[i]}',
                                       capacity, pristine, None, ref, rul_status))
        return tuple(value)

    def soc(state):
        # A theoretical occupied-site moment, never measured usable module SOC.
        try:
            state = np.asarray(state, dtype=float)
            if isinstance(model, SiteModel):
                if state.shape != (5,):
                    return None
                capacities = np.asarray(model.params.site_capacity_mol, dtype=float)
                occupations = state[:2]
            else:
                if state.shape != (4, 5):
                    return None
                capacities = np.asarray([cell.params.site_capacity_mol for cell in model.cells], dtype=float)
                occupations = state[:, :2]
            if (capacities.shape != occupations.shape or not np.all(np.isfinite(state))
                    or not np.all(np.isfinite(capacities)) or np.any(capacities <= 0)
                    or np.any(occupations < 0) or np.any(occupations > 1)):
                return None
            total = float(capacities.sum())
            if not math.isfinite(total) or total <= 0:
                return None
            value = float(np.sum(capacities * occupations) / total)
            return value if math.isfinite(value) and 0 <= value <= 1 else None
        except (TypeError, ValueError, OverflowError):
            return None

    initial_probe = storage_probe(result['economics']['initial_stored_energy_probe'], protocol.maximum_duration_s)
    final_probe = storage_probe(result['economics']['final_stored_energy_probe'], protocol.maximum_duration_s)
    status = result['status']
    if status not in ('right_censored', 'retired'):
        status = 'unknown' if status in ('unknown_capacity', 'budget_exhausted') else 'early_exit'
    initial = TerminalState(0., 'initial', soc(trace[0]['state']) if trace else None, initial_probe['energy_J'],
                            assets(initial_rows, initial=True), source_ref + '#initial')
    final = TerminalState(result['elapsed_s'], status, soc(result['final_state']), final_probe['energy_J'],
                          assets(final_rows, initial=False), source_ref + '#final',
                          evidence_kind='conditional_projection' if projected else 'actual')
    return initial, final, tuple(events), {
        'initial_storage': initial_probe, 'final_storage': final_probe,
        'soc_definition': 'capacity-weighted occupied-site moment; uncalibrated synthetic assumption',
        'rul': 'None; no future lifetime inferred from simulation horizon or retirement detection interval',
        'capacity_source': 'declared numerical CapacityProtocol; not measured physical cells',
        'generation_count_by_cell': generations, 'macro_endpoint_is_projection': projected,
        'initial_capacity_diagnostic_missing': not bool(trace),
    }
