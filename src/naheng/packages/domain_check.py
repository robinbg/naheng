from __future__ import annotations
import math

def reduction_condition(rates: list[float] | None) -> dict:
    if rates is None or not rates:
        return {"status":"UNKNOWN","reason":"Channel rates unavailable from permitted model/parameter information"}
    if any(not math.isfinite(r) or r < 0 for r in rates):
        return {"status":"FAIL","reason":"Rates must be finite and nonnegative"}
    if any(r != rates[0] for r in rates):
        return {"status":"FAIL","reason":"Unequal total channel rates; aggregate sodium inventory does not close"}
    return {"status":"PASS","reason":"Common total rates under declared common external drive"}

def check_domain(package: dict, snapshot, ambient_K: float) -> list[dict]:
    domain=package["domain"]
    checks=[]
    low,high=domain["temperature_K"]
    checks.append({"name":"ambient","status":"PASS" if low <= ambient_K <= high else "FAIL","reason":"Synthetic fixture model temperature domain"})
    names=snapshot.state_names
    ranges={"x1":(0,1),"x2":(0,1),"trapped_mol":(0,float("inf")),"reservoir_mol":(0,float("inf")),"temperature_K":(low,high)}
    for name,(minimum,maximum) in ranges.items():
        if name not in names:
            checks.append({"name":name,"status":"UNKNOWN","reason":"State semantics missing"})
        else:
            i=names.index(name)
            valid=all(math.isfinite(row[i]) and minimum<=row[i]<=maximum for row in snapshot.samples)
            checks.append({"name":name,"status":"PASS" if valid else "FAIL","reason":"All represented posterior samples checked; not a full-support certificate"})
    checks.append({"name":"chemical_reduction",**reduction_condition(domain.get("channel_rates"))})
    return checks
