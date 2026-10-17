"""Bounded real PyBaMM sodium solve and Lean/Lake capability probes.

Import success, model construction, short solving and lifecycle capability are
separate evidence. No lithium parameter substitution is permitted here.
"""

from pathlib import Path
import argparse
import importlib.util
import json
import os
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from naheng.formal.checker import run_command, _lake

PYBAMM_PROBE = r'''
import inspect, json
import pybamm
model = pybamm.sodium_ion.BasicDFN()
parameters = model.default_parameter_values
sim = pybamm.Simulation(model, parameter_values=parameters, C_rate=0.1)
solution = sim.solve([0, 10])
voltage = solution["Voltage [V]"].entries.tolist()
source = inspect.getsource(type(model))
print(json.dumps({
    "version": pybamm.__version__, "model": type(model).__module__ + "." + type(model).__name__,
    "model_source_file": inspect.getfile(type(model)), "model_source": source,
    "default_parameters": str(parameters), "options": str(getattr(model, "options", None)),
    "time_s": solution.t.tolist(), "voltage_v": voltage,
    "available_variables": sorted(model.variables), "parameter_citations": parameters.get("citations", []),
    "capabilities": {"sodium_dfn_short_solve": "passed", "thermal_dynamics": "not_validated",
      "side_reactions": "not_validated", "aging": "not_validated", "full_lifecycle": "not_validated"}
}, default=str))
'''


def probe(out: Path) -> dict:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    result = {"exit_code": 2, "status": "blocked", "python": sys.version,
              "capabilities": {}, "evidence": []}
    py_file = out / "pybamm_probe.py"
    py_file.write_text(PYBAMM_PROBE, encoding="utf-8")
    py_run = run_command([sys.executable, str(py_file)], ROOT, out / "pybamm.log")
    result["evidence"].append({k:v for k,v in py_run.items() if k not in {"stdout", "stderr"}})
    if py_run["exit_code"] == 0:
        try:
            raw = json.loads(py_run["stdout"].splitlines()[-1])
            (out / "pybamm_results.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            result["capabilities"]["pybamm_sodium_short_solve"] = {"status": "passed", "version": raw["version"]}
        except (json.JSONDecodeError, IndexError) as exc:
            result["capabilities"]["pybamm_sodium_short_solve"] = {"status": "failed", "reason": repr(exc)}
    else:
        result["capabilities"]["pybamm_sodium_short_solve"] = {
            "status": "blocked" if importlib.util.find_spec("pybamm") is None or py_run["timed_out"] else "failed",
            "reason": py_run["stderr"][-4000:], "timed_out": py_run["timed_out"]}
    lake = _lake()
    if lake:
        tiny = out / "Probe.lean"
        tiny.write_text("theorem chemical_integer_balance : (1 : Int) + (-1) = 0 := by decide\n"
                        "#print axioms chemical_integer_balance\n", encoding="utf-8")
        lean_exe = str(Path(lake).with_name("lean.exe" if os.name == "nt" else "lean"))
        version = run_command([lean_exe, "--version"], ROOT, out / "lean_version.log")
        lean_run = run_command([lean_exe, str(tiny)], ROOT, out / "lean.log")
        result["evidence"].extend({k:v for k,v in run.items() if k not in {"stdout", "stderr"}}
                                   for run in (version, lean_run))
        result["capabilities"]["lean_kernel_probe"] = {
            "status": "passed" if lean_run["exit_code"] == 0 else "blocked",
            "version": version["stdout"].strip(), "reason": lean_run["stderr"]}
    else:
        result["capabilities"]["lean_kernel_probe"] = {"status": "blocked", "reason": "lean/lake unavailable"}
    if all(item["status"] == "passed" for item in result["capabilities"].values()):
        result.update(exit_code=0, status="passed")
    elif any(item["status"] == "failed" for item in result["capabilities"].values()):
        result.update(exit_code=1, status="failed")
    (out / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("artifacts/probes"))
    args = parser.parse_args()
    outcome = probe(args.out)
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    raise SystemExit(outcome["exit_code"])
