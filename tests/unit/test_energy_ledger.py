import pytest
from naheng.domain.contracts import Action
from naheng.economics.ledger import EnergyLedger


def action(current=0.2):
    return Action(action_id="action-energy",snapshot_id="snapshot-energy",
                  start_s=0,duration_s=30,current_A=current)


def test_only_executed_signed_energy_and_heat_electricity_are_invoiced():
    ledger = EnergyLedger("run-energy")
    ledger.append(action(),execution_id="discharge",energy_J=3_600_000,
                  thermal_energy_J=360_000,buy_price_per_kWh=0.2,sell_price_per_kWh=0.4)
    ledger.append(action(-0.2),execution_id="charge",energy_J=-1_800_000,
                  buy_price_per_kWh=0.2,sell_price_per_kWh=0.4)
    ledger.append(action(),execution_id="not-executed",energy_J=0,executed=False,reason="admission_unknown")
    totals=ledger.summary()
    assert totals["exported_energy_J"] == 3_600_000
    assert totals["imported_energy_J"] == 1_800_000
    assert totals["net_cashflow"] == pytest.approx(0.4-0.1-0.02)
    assert totals["executions"] == 2 and totals["unexecuted_proposals"] == 1
    assert totals["terminal_value"] is None and not totals["lifecycle_complete"]


def test_duplicate_execution_and_candidate_energy_rejected_and_copy_isolated():
    ledger=EnergyLedger("run-energy")
    entry=ledger.append(action(),execution_id="once",energy_J=10)
    entry["energy_J"] = 999
    assert ledger.entries[0]["energy_J"] == 10
    with pytest.raises(ValueError,match="duplicate"):
        ledger.append(action(),execution_id="once",energy_J=10)
    with pytest.raises(ValueError,match="Unexecuted"):
        ledger.append(action(),execution_id="proposal",energy_J=10,executed=False)
