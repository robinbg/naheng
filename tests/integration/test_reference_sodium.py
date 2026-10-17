import csv
import hashlib
import json
import numpy as np
import pytest

from naheng.models.reference_pybamm import ReferenceSodiumAdapter,UnsupportedCapability,save_reference_trace


def test_reference_rejects_unmodeled_capabilities_and_temperature():
    adapter=ReferenceSodiumAdapter()
    for name in ("thermal_dynamics","side_reactions","aging","full_lifecycle"):
        assert adapter.capabilities()[name]["status"]=="unsupported"
        with pytest.raises(UnsupportedCapability): adapter.simulate(requested_capabilities=(name,))
    with pytest.raises(UnsupportedCapability): adapter.simulate(temperature_K=310)


def test_real_sodium_dfn_readouts_parameters_and_action_change(tmp_path):
    adapter=ReferenceSodiumAdapter()
    low=adapter.simulate(duration_s=10,C_rate=.1)
    high=adapter.simulate(duration_s=10,C_rate=.2)
    assert low["backend_version"]=="25.10.2"
    assert low["parameter_set"]=="Chayambuka2022"
    assert low["provenance_type"]=="reference_simulation" and low["public_measurement"] is False
    assert low["elapsed_s"]==pytest.approx(10)
    assert np.ptp(low["voltage_V"])>1e-8
    assert high["voltage_V"][0]<low["voltage_V"][0]
    assert np.mean(high["current_A"])==pytest.approx(2*np.mean(low["current_A"]))
    assert low["electrical_energy_J"]==pytest.approx(np.trapezoid(np.array(low["current_A"])*low["voltage_V"],low["time_s"]))
    assert all(len(values)==len(low["time_s"]) and np.all(np.isfinite(values)) for values in low["reference_internal"].values())
    assert low["artifact_hashes"]["parameter_tables_sha256"]
    manifest=save_reference_trace(low,tmp_path)
    for artifact in manifest["artifacts"].values():
        from pathlib import Path
        assert hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest()==artifact["sha256"]
    saved=json.loads((tmp_path/"trace.json").read_text(encoding="utf-8"))
    assert saved["voltage_V"]==low["voltage_V"]
    with (tmp_path/"observations.csv").open(encoding="utf-8") as stream:
        assert len(list(csv.DictReader(stream)))==len(low["time_s"])
