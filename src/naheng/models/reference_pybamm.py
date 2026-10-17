"""Pinned sodium DFN reference; never substitutes a lithium parameter set."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import inspect
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

PINNED_VERSION = "25.10.2"
PARAMETER_SET = "Chayambuka2022"
SOURCES = {
    "manual": "https://docs.pybamm.org/en/v25.10.2/source/examples/notebooks/models/sodium-ion.html",
    "parameters": "https://github.com/pybamm-team/PyBaMM/blob/v25.10.2/src/pybamm/input/parameters/sodium_ion/Chayambuka2022.py",
    "model": "https://github.com/pybamm-team/PyBaMM/blob/v25.10.2/src/pybamm/models/full_battery_models/sodium_ion/basic_dfn.py",
    "paper": "https://doi.org/10.1016/j.electacta.2021.139764",
}


class MissingBackend(RuntimeError):
    pass


class UnsupportedCapability(ValueError):
    pass


class ReferenceSolveError(RuntimeError):
    pass


def _load_backend():
    # Avoid telemetry/config prompts in automated local scientific runs.
    os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
    try:
        module = importlib.import_module("pybamm")
    except (ImportError, OSError) as exc:
        raise MissingBackend(f"PyBaMM {PINNED_VERSION} reference extra is unavailable: {exc}") from exc
    if module.__version__ != PINNED_VERSION:
        raise MissingBackend(f"reference requires PyBaMM {PINNED_VERSION}; found {module.__version__}")
    if not hasattr(module.sodium_ion, "BasicDFN"):
        raise MissingBackend("installed PyBaMM has no sodium_ion.BasicDFN")
    return module


class ReferenceSodiumAdapter:
    model_id = "reference_sodium"
    chemistry_id = "hard-carbon-NVPF-NaPF6-EC-PC"
    model_kind = "reference_sodium"
    parameter_revision = "pybamm-25.10.2-Chayambuka2022"

    @staticmethod
    def capabilities() -> dict:
        return {
            "sodium_dfn_voltage": {"status": "implemented", "requires": "real_backend_solve"},
            "particle_and_electrolyte_concentrations": {"status": "implemented", "requires": "real_backend_solve"},
            "thermal_dynamics": {"status": "unsupported", "reason": "BasicDFN uses prescribed temperature; parameter functions lack calibrated temperature dependence"},
            "thermal_management": {"status": "unsupported", "reason": "no thermal energy balance or management actuator"},
            "side_reactions": {"status": "unsupported", "reason": "no audited sodium SEI or plating mechanism in this adapter"},
            "aging": {"status": "unsupported", "reason": "no evolving degradation states or calibrated life mechanisms"},
            "full_lifecycle": {"status": "unsupported", "reason": "short electrochemical trace does not validate capacity fade, maintenance, or RUL"},
            "inventory_certificate": {"status": "unsupported", "reason": "spatial concentration means are not a full volume-weighted sodium inventory audit"},
        }

    def simulate(self, *, duration_s: float = 10, C_rate: float = .1, temperature_K: float = 298.15,
                 points: int = 21, requested_capabilities: tuple[str, ...] = ()) -> dict:
        for capability in requested_capabilities:
            item = self.capabilities().get(capability)
            if item is None or item["status"] == "unsupported":
                raise UnsupportedCapability(f"unsupported reference capability: {capability}")
        if not math.isfinite(duration_s) or not 0 < duration_s <= 3600 or not math.isfinite(C_rate) or not 0 < C_rate <= 1:
            raise ValueError("reference execution budget requires 0<duration_s<=3600 and 0<C_rate<=1")
        if temperature_K != 298.15:
            raise UnsupportedCapability("reference adapter currently audited only at prescribed 298.15 K")
        if type(points) is not int or not 2 <= points <= 1001:
            raise ValueError("points must be an integer in 2..1001")
        pybamm = _load_backend()
        model = pybamm.sodium_ion.BasicDFN()
        parameters = pybamm.ParameterValues(PARAMETER_SET)
        parameters.update({"Ambient temperature [K]":temperature_K,"Initial temperature [K]":temperature_K})
        solver = pybamm.IDAKLUSolver(atol=1e-8,rtol=1e-6)
        simulation = pybamm.Simulation(model,parameter_values=parameters,solver=solver,C_rate=C_rate)
        try:
            solution = simulation.solve(np.linspace(0,duration_s,points))
            times = np.asarray(solution.t,dtype=float)
            voltage = np.asarray(solution["Voltage [V]"].entries,dtype=float).reshape(-1)
            current = np.asarray(solution["Current [A]"].entries,dtype=float).reshape(-1)
        except Exception as exc:
            raise ReferenceSolveError(f"real sodium DFN solve failed: {type(exc).__name__}: {exc}") from exc
        if times.size<2 or times.size!=voltage.size or times.size!=current.size or not all(np.all(np.isfinite(x)) for x in (times,voltage,current)) or np.any(np.diff(times)<=0):
            raise ReferenceSolveError("solver returned invalid time/readout arrays")
        internal = {}
        for name,key in (("Negative particle concentration [mol.m-3]","negative_particle_spatial_mean_mol_per_m3"),
                         ("Positive particle concentration [mol.m-3]","positive_particle_spatial_mean_mol_per_m3"),
                         ("Electrolyte concentration [mol.m-3]","electrolyte_spatial_mean_mol_per_m3")):
            if name not in model.variables:
                raise ReferenceSolveError(f"required reference variable missing: {name}")
            entries = np.asarray(solution[name].entries,dtype=float)
            values = entries.reshape(-1,times.size).mean(axis=0)
            if not np.all(np.isfinite(values)):
                raise ReferenceSolveError(f"nonfinite reference concentration: {name}")
            internal[key] = values.tolist()
        model_file = Path(inspect.getfile(type(model)))
        parameter_module = importlib.import_module("pybamm.input.parameters.sodium_ion.Chayambuka2022")
        parameter_file = Path(inspect.getfile(parameter_module))
        # In this pinned installed wheel, process_1D_data resolves these eight
        # declared tables in the parameter module's data/ directory.
        table_names = ("U_n.csv","U_p.csv","D_n.csv","D_p.csv","k_n.csv","k_p.csv","D_e.csv","sigma_e.csv")
        parameter_assets = {}
        for name in table_names:
            path = parameter_file.parent/"data"/name
            if not path.is_file():
                raise ReferenceSolveError(f"declared parameter table missing: {path}")
            parameter_assets[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        artifact_hashes = {"model_source_sha256":hashlib.sha256(model_file.read_bytes()).hexdigest(),
                           "parameter_source_sha256":hashlib.sha256(parameter_file.read_bytes()).hexdigest(),
                           "parameter_tables_sha256":parameter_assets}
        result = {
            "status":"completed","model_id":self.model_id,"model_kind":self.model_kind,
            "chemistry_id":self.chemistry_id,"parameter_set":PARAMETER_SET,"parameter_revision":self.parameter_revision,
            "source_id":"pybamm-Chayambuka2022-COMSOL","sources":SOURCES,
            "provenance_type":"reference_simulation","public_measurement":False,
            "backend_version":pybamm.__version__,"solver":"IDAKLUSolver","solver_atol":1e-8,"solver_rtol":1e-6,
            "requested_duration_s":duration_s,"elapsed_s":float(times[-1]),"C_rate":C_rate,
            "current_sign":"positive_discharge","temperature_model":"prescribed_isothermal",
            "time_s":times.tolist(),"voltage_V":voltage.tolist(),"current_A":current.tolist(),
            "temperature_K":[temperature_K]*times.size,"reference_internal":internal,
            "electrical_energy_J":float(np.trapezoid(voltage*current,times)),
            "discharge_charge_C":float(np.trapezoid(current,times)),
            "termination":str(solution.termination),"capabilities":self.capabilities(),
            "model_source_file":str(model_file),"parameter_source_file":str(parameter_file),"artifact_hashes":artifact_hashes,
            "available_variables":sorted(model.variables),
            "supported_execution_domain":{"temperature_K":[298.15,298.15],"C_rate":[0,1],"duration_s":[0,3600],
                                          "meaning":"software budget bounds, not an empirical validation domain"},
            "limitations":["Shared DFN/Butler-Volmer assumptions with electrochemical models must be counted in independent evaluation",
                           "No mapping from two-site fixture parameters or hidden state to this DFN has been established",
                           "Internal arithmetic spatial means are diagnostic traces, not sodium conservation certificates",
                           "No thermal, side-reaction, aging, fire, or lifecycle validation is implied"],
        }
        for key in ("sodium_dfn_voltage","particle_and_electrolyte_concentrations"):
            result["capabilities"][key] = {"status":"passed","evidence":"this_real_solver_trace"}
        return result


def save_reference_trace(result: dict,out: str | Path) -> dict:
    out = Path(out)
    out.mkdir(parents=True,exist_ok=True)
    trace = out/"trace.json"
    trace.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    csv_path = out/"observations.csv"
    with csv_path.open("w",newline="",encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp_s","current_A","voltage_V","temperature_K"])
        writer.writerows(zip(result["time_s"],result["current_A"],result["voltage_V"],result["temperature_K"]))
    manifest = {"status":"completed","provenance_type":"reference_simulation","model_id":result["model_id"],
                "parameter_revision":result["parameter_revision"],"capabilities":result["capabilities"],
                "artifacts":{name:{"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
                             for name,path in (("trace",trace),("observations",csv_path))}}
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,default=Path("artifacts/reference_smoke"))
    parser.add_argument("--duration-s",type=float,default=10)
    parser.add_argument("--c-rate",type=float,default=.1)
    args=parser.parse_args(argv)
    try:
        result = ReferenceSodiumAdapter().simulate(duration_s=args.duration_s,C_rate=args.c_rate)
        manifest = save_reference_trace(result,args.out)
        print(json.dumps({"status":"completed","points":len(result["time_s"]),"first_voltage_V":result["voltage_V"][0],
                          "last_voltage_V":result["voltage_V"][-1],"energy_J":result["electrical_energy_J"],"manifest":manifest},ensure_ascii=False))
        return 0
    except (MissingBackend,UnsupportedCapability) as exc:
        status,code="blocked",2
        reason=f"{type(exc).__name__}: {exc}"
    except (ValueError,ReferenceSolveError) as exc:
        status,code="failed",1
        reason=f"{type(exc).__name__}: {exc}"
    args.out.mkdir(parents=True,exist_ok=True)
    manifest={"status":status,"exit_code":code,"reason":reason,"artifacts":{},"capabilities":ReferenceSodiumAdapter.capabilities()}
    (args.out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(manifest,ensure_ascii=False))
    return code


if __name__=="__main__":
    sys.exit(main())
