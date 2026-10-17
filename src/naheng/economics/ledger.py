"""Cash flow from executed electrical energy, with explicit synthetic tariffs."""
from __future__ import annotations

from copy import deepcopy
from math import isfinite

from naheng.domain.contracts import Action


class EnergyLedger:
    def __init__(self, run_id: str, currency: str = "CNY", tariff_source: str = "synthetic"):
        self.run_id, self.currency, self.tariff_source = run_id, currency, tariff_source
        self._entries = []
        self._execution_ids = set()

    def append(self, action: Action, *, execution_id: str, energy_J: float,
               thermal_energy_J: float = 0.0, buy_price_per_kWh: float = 0.15,
               sell_price_per_kWh: float = 0.30, executed: bool = True,
               reason: str | None = None, duration_s: float | None = None) -> dict:
        """thermal_energy_J is measured electrical consumption, not removed heat."""
        values = [energy_J, thermal_energy_J, buy_price_per_kWh, sell_price_per_kWh]
        if any(not isfinite(value) for value in values) or thermal_energy_J < 0:
            raise ValueError("Finite energy and tariff values required; thermal consumption must be nonnegative")
        if not execution_id or execution_id in self._execution_ids:
            raise ValueError("Execution ID must be unique; duplicate energy cannot be invoiced")
        if not executed and (energy_J != 0 or thermal_energy_J != 0):
            raise ValueError("Unexecuted proposals have no realized energy or revenue")
        if duration_s is not None and not 0 <= duration_s <= action.duration_s:
            raise ValueError("Realized duration must lie within the proposed interval")
        exported_J, imported_J = max(energy_J, 0.0), max(-energy_J, 0.0)
        sales = exported_J / 3_600_000 * sell_price_per_kWh
        purchases = imported_J / 3_600_000 * buy_price_per_kWh
        heat_cost = thermal_energy_J / 3_600_000 * buy_price_per_kWh
        entry = {"run_id": self.run_id, "execution_id": execution_id,
            "action_id": action.action_id, "snapshot_id": action.snapshot_id,
            "start_s": action.start_s, "duration_s": action.duration_s if duration_s is None else duration_s,
            "executed": executed, "reason": reason, "energy_J": energy_J,
            "exported_energy_J": exported_J, "imported_energy_J": imported_J,
            "thermal_electric_energy_J": thermal_energy_J,
            "sales": sales, "purchases": purchases, "thermal_cost": heat_cost,
            "net_cashflow": sales - purchases - heat_cost, "currency": self.currency,
            "buy_price_per_kWh": buy_price_per_kWh, "sell_price_per_kWh": sell_price_per_kWh,
            "tariff_source": self.tariff_source, "provenance_type": "synthetic"}
        self._entries.append(entry)
        self._execution_ids.add(execution_id)
        return deepcopy(entry)

    @property
    def entries(self) -> list[dict]:
        return deepcopy(self._entries)

    def summary(self) -> dict:
        total_keys = ["energy_J", "exported_energy_J", "imported_energy_J",
                      "thermal_electric_energy_J", "sales", "purchases", "thermal_cost", "net_cashflow"]
        totals = {key: sum(row[key] for row in self._entries) for key in total_keys}
        return {"run_id": self.run_id, "currency": self.currency,
            "tariff_source": self.tariff_source, "provenance_type": "synthetic",
            "executions": sum(row["executed"] for row in self._entries),
            "unexecuted_proposals": sum(not row["executed"] for row in self._entries),
            "terminal_value": None, "maintenance_cost": None, "lifecycle_complete": False,
            **totals}
