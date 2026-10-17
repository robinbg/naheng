from __future__ import annotations
from math import isfinite
from naheng.packages.domain_check import check_domain


def _output_contract_checks(package,formal_evidence):
    """Inspect references without self-certifying runtime authorization.

    No typed T3 verifier is implemented yet. A manifest's checked status or
    free-text scope establishes neither a bound nor model/parameter binding.
    """
    evidence=formal_evidence if isinstance(formal_evidence,dict) else {}
    raw=evidence.get("records",[])
    raw=raw if isinstance(raw,list) else []
    records={row.get("evidence_id"):row for row in raw
             if isinstance(row,dict) and isinstance(row.get("evidence_id"),str)}
    registered=set(package.get("evidence_refs",[]))
    contracts=package.get("error_contracts",[])
    if not contracts:
        return [{"name":"output_error_contract","status":"UNKNOWN",
                 "reason":"No output error contract; typed T3 certificate verification is not implemented"}]
    result=[]
    for index,contract in enumerate(contracts):
        ref=contract.get("evidence_ref") if isinstance(contract,dict) else None
        if not isinstance(contract,dict) or contract.get("bound") is None:
            reason="Output error bound is missing; null is not zero"
        elif contract.get("status")!="checked":
            reason="Output error contract is not checked"
        elif not isinstance(ref,str) or ref not in registered:
            reason="Output evidence reference is not registered in this model package"
        elif ref not in records:
            reason="Registered output evidence reference has no imported declaration record"
        else:
            reason=("Typed T3 output certificate verification is not implemented; an imported declaration "
                    "does not establish output-error scope or model/parameter applicability")
        result.append({"name":"output_error_contract","contract_index":index,
                       "status":"UNKNOWN","reason":reason,"evidence_ref":ref})
    return result


def check(snapshot,action,package:dict,ambient_K=298.15,mode="empirical",formal_evidence=None,runtime_binding=None,rate_evaluation=None)->dict:
    if mode not in {"empirical","strict"}: raise ValueError("Unsupported admission mode")
    if action.snapshot_id!=snapshot.snapshot_id: raise ValueError("Action snapshot mismatch")
    checks=check_domain(package,snapshot,ambient_K)
    # Equal rates are a numerical condition, not a verified aggregate model.
    physical=[row for row in checks if row["name"]!="chemical_reduction"]
    current=action.current_A
    if current is None or not isfinite(current) or abs(current)>package["domain"]["max_current_A"]:
        failed={"name":"current","status":"FAIL","reason":"Current exceeds model action domain"}
        checks.append(failed);physical.append(failed)
    used_refs=[]
    if runtime_binding is not None:
        from naheng.formal.runtime_binding import RuntimeBindingResult
        if not isinstance(runtime_binding,RuntimeBindingResult):
            raise ValueError("Typed, revalidated runtime chemistry binding required")
        binding=runtime_binding.record
        chemical={"name":"runtime_chemical_inventory_applicability","status":binding["status"],
                  "reason":binding["reason"],"scope":binding["scope"]}
        checks.append(chemical)
        if binding["status"]=="PASS":
            used_refs=list(binding["evidence_refs"])
        elif not binding["empirical_detailed_fallback_allowed"]:
            # Invalid coefficients or an untrusted execution source cannot be
            # repaired by calling the same detailed model an empirical fallback.
            physical.append(chemical)
    rate_record = None
    if rate_evaluation is not None:
        from naheng.formal.reduction_binding import verify_rate_evaluation
        rate_record = verify_rate_evaluation(rate_evaluation, snapshot, action)
        if rate_record.get('upper_mol_per_s') is not None:
            status = rate_record['status']
            if rate_evaluation.binding.record['status'] != 'PASS': status = 'UNKNOWN'
            rate_check = {"name": "represented_posterior_instantaneous_rate_limit", "status": status,
                          "reason": rate_record['reason'], "scope": rate_record['scope'],
                          "numerical_status": rate_record['numerical_status']}
            checks.append(rate_check); physical.append(rate_check)
    accepted=all(row["status"]=="PASS" for row in physical)
    checks.append({"name":"chemical_reduction_certificate","status":"UNKNOWN",
        "reason":"Typed T1 aggregate-closure certificate verification is not implemented; foundation declarations cannot authorize reduction"})
    checks.extend(_output_contract_checks(package,formal_evidence))
    result={"mode":mode,"checks":checks,"model_selected":"detailed","evidence_refs":used_refs,
        "uncovered":["Model-to-real-cell discrepancy","Full continuous state support","Fire and sodium plating"]}
    if rate_record is not None:
        result['rate_diagnostics'] = rate_record
        result['reduction_evidence_refs'] = list(rate_record.get('evidence_refs', []))
    if not accepted:
        failed=any(row["status"]=="FAIL" for row in physical)
        result.update(decision="reject" if failed else "unknown",
                      reason="Action or represented posterior is outside the declared physical domain" if failed else "Physical applicability is unknown")
    elif mode=="strict":
        result.update(decision="unknown",reason="Typed T3 output-error certificate verification is not implemented; checked balance/boundary records cannot certify strict safety")
    else:
        result.update(decision="accept",reason="Synthetic empirical execution only")
    return result
