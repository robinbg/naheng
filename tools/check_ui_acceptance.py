"""Validate saved UI evidence; this reader does not perform browser acceptance."""
import csv
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse
from naheng.runtime.artifacts import code_hash

REQUIRED={"create_real_run","changed_input_new_trajectory","seven_routes_same_run","report_opened","independent_review"}
RUN_ID=re.compile(r"nh-[0-9a-f]{32}")
SHA=re.compile(r"[0-9a-f]{64}")
ROUTES={"overview","state","life","risk","strategy","simulation","theory"}

def audit_ui_record(root,path):
    result={"status":"blocked","exit_code":2,"scope":"UI evidence record only; not scientific or release validation"}
    try:
        root,path=Path(root).resolve(),Path(path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return {**result,"reason":"No real UI acceptance record"}
        def require(condition,reason):
            if not condition: raise ValueError(reason)
        def names(value,reason):
            require(isinstance(value,list) and bool(value) and all(isinstance(x,str) and x for x in value),reason)
            require(len(value)==len(set(value)),reason)
            return value
        def controlled(relative):
            require(isinstance(relative,str) and bool(relative) and not Path(relative).is_absolute(),"Invalid evidence path")
            target=(root/relative).resolve()
            require(target.is_relative_to(root) and target.is_file(),"Missing or uncontrolled evidence file")
            return target
        def read(relative):
            value=json.loads(controlled(relative).read_text(encoding="utf-8"))
            require(isinstance(value,dict),"Evidence must be a JSON object")
            return value
        def hashed(mapping,reason):
            require(isinstance(mapping,dict) and bool(mapping),reason)
            for relative,digest in mapping.items():
                require(isinstance(digest,str) and SHA.fullmatch(digest) is not None,reason)
                require(hashlib.sha256(controlled(relative).read_bytes()).hexdigest()==digest,"Evidence bytes changed: "+relative)
        def native_receipt(relative):
            covered(relative); receipt=read(relative)
            require(type(receipt.get("exit_code")) is int and receipt["exit_code"]==0 and
                receipt.get("status")=="completed" and receipt.get("timed_out") is False and
                isinstance(receipt.get("argv"),list) and bool(receipt["argv"]),"Required native receipt did not complete")
            return receipt
        r=json.loads(path.read_text(encoding="utf-8"))
        require(isinstance(r,dict),"Acceptance record must be a JSON object")
        names(r.get("passed",[]),"Passed requirements must be distinct names")
        missing=sorted(REQUIRED-set(r.get("passed",[])))
        if missing: return {**result,"reason":"Required UI observations remain incomplete","missing":missing,"record":str(path)}
        require(r.get("status")=="passed" and r.get("mode")=="real_ui_acceptance" and
            not r.get("calibration_only") and not r.get("blocked"),"Acceptance observations are not complete real UI evidence")
        ids=names(r.get("run_ids"),"Run identities unavailable or duplicate")
        require(all(RUN_ID.fullmatch(i) for i in ids),"Run identities malformed")
        require(isinstance(r.get("code_hash"),str) and SHA.fullmatch(r["code_hash"]) and
            r["code_hash"]==code_hash(root),"UI record does not bind the current source")
        hashed(r.get("evidence_hashes"),"Nonempty evidence hashes required")
        def covered(relative):
            require(relative in r["evidence_hashes"],"Required evidence is not indexed: "+str(relative))
            return controlled(relative)
        covered(r["build_manifest"]); build=read(r["build_manifest"])
        require(isinstance(r.get("build_hash"),str) and SHA.fullmatch(r["build_hash"]) and
            build.get("build_id")==r["build_hash"] and type(build.get("build_exit_code")) is int and
            build["build_exit_code"]==0,"Build identity does not match UI record")
        for field in ("source_hashes","dist_hashes"):
            hashed(build.get(field),"Nonempty built UI "+field+" required")
        sources={p.relative_to(root).as_posix() for p in (root/"frontend/src").rglob("*") if p.is_file()}
        sources.update("frontend/"+n for n in ("package.json","package-lock.json","vite.config.ts","tsconfig.json","index.html"))
        dist={p.relative_to(root).as_posix() for p in (root/"frontend/dist").rglob("*") if p.is_file()}
        require(sources.issubset(build["source_hashes"]) and "frontend/dist/index.html" in dist and
            set(build["dist_hashes"])==dist,"Built UI source/output inventory is incomplete")
        identity=hashlib.sha256(json.dumps({"sources":build["source_hashes"],"dist":build["dist_hashes"]},sort_keys=True).encode()).hexdigest()
        require(identity==r["build_hash"],"Build identity does not bind its inventories")
        receipt=native_receipt(build["build_evidence"])
        require(build.get("build_command")==receipt["argv"],"Build receipt command differs")
        observations={}
        require(isinstance(r.get("observations"),list),"Actual observation records required")
        critical={r["build_manifest"],build["build_evidence"]}
        for item in r["observations"]:
            require(isinstance(item,dict) and isinstance(item.get("requirement"),str),"Invalid observation")
            key=item["requirement"]
            require(key not in observations,"Duplicate requirement observation")
            observations[key]=item
            if key not in REQUIRED: continue
            require(item.get("status")=="passed" and isinstance(item.get("details"),dict),"Required observation did not pass")
            refs=names(item.get("evidence_paths"),"Observation evidence missing")
            observed_ids=names(item.get("run_ids"),"Observation Run identity missing")
            require(set(observed_ids).issubset(ids),"Observation names another Run")
            mechanism="independent_artifact_review" if key=="independent_review" else "real_browser"
            require(item.get("mechanism")==mechanism,"Actual browser/independent mechanism missing")
            for name in refs: covered(name)
            if key!="independent_review": critical.update(refs)
        require(REQUIRED.issubset(observations),"Passed labels have no actual observations")
        runs=r.get("run_artifacts")
        require(isinstance(runs,dict) and len(runs)==2 and set(runs).issubset(ids),"Two normal changed-input Runs required")
        traces=[]; inputs=[]; reports={}
        for identifier,entry in runs.items():
            require(isinstance(entry,dict),"Invalid Run artifact entry")
            for field in ("job_record","manifest","source_index","artifact_hashes"):
                covered(entry[field]);critical.add(entry[field])
            job,manifest,index,hashes=[read(entry[f]) for f in ("job_record","manifest","source_index","artifact_hashes")]
            require(job.get("run_id")==identifier and job.get("state")=="succeeded" and
                manifest.get("run_id")==identifier and manifest.get("complete") is True and
                manifest.get("mode") in {"interactive","batch"} and not manifest.get("reused_from") and
                not manifest.get("recovered_from"),"Run is incomplete or reused")
            config=job["config"]
            require(manifest.get("code_hash")==r["code_hash"]==index.get("code_hash")==config.get("code_hash"),"Run source identity differs")
            require(all(index["files"].get(n)==v for n,v in build["source_hashes"].items() if n.startswith("frontend/src/")),"Run frontend differs from built UI")
            inputs.append(tuple(config[n] for n in ("ambient_K","initial_soc","sell_price_per_kWh","duration_s")))
            directory=controlled(entry["manifest"]).parent
            def artifact(key):
                target=(directory/manifest["artifact_index"][key]).resolve()
                require(target.is_relative_to(directory),"Run artifact escaped directory")
                name=target.relative_to(root).as_posix();covered(name);critical.add(name)
                require(r["evidence_hashes"][name]==hashes[key],"Run artifact hash differs")
                return target
            with artifact("sensor_csv").open(encoding="utf-8",newline="") as stream:
                trace=[tuple(float(row[n]) for n in ("timestamp_s","current_A","voltage_V","temperature_K")) for row in csv.DictReader(stream)]
            require(trace and all(math.isfinite(x) for row in trace for x in row),"Actual trajectory missing or nonfinite")
            traces.append(trace);reports[identifier]=artifact("report")
        require(inputs[0]!=inputs[1] and traces[0]!=traces[1],"Changed inputs did not produce distinct actual trajectories")
        for key in ("create_real_run","changed_input_new_trajectory"):
            require(set(observations[key]["run_ids"])==set(runs),"Normal Run observation pair differs")
        routes=observations["seven_routes_same_run"]["details"]["routes"]
        require(isinstance(routes,list) and len(routes)==7 and {x["route"] for x in routes}==ROUTES and
            len({x["run_id"] for x in routes})==1 and all(x["run_id"] in runs and
            x.get("visible_run_id")==x["run_id"] and x.get("state")=="succeeded" for x in routes),"Seven routes do not bind the same actual Run")
        opened=observations["report_opened"]["details"]
        report_id=opened.get("visible_run_id");viewer=urlparse(opened.get("url",""))
        report=covered(opened["path"]);critical.add(opened["path"])
        require(report_id in reports and opened.get("status")=="opened" and
            opened.get("method")=="normal_supported_viewer" and viewer.scheme in {"http","https"} and viewer.hostname and
            opened.get("prior_denial_bypassed") is False and report.read_bytes()==reports[report_id].read_bytes() and
            report_id in report.read_text(encoding="utf-8"),"Opened report does not bind the actual downloaded Run report")
        reviews=names(r.get("independent_review_paths"),"Nonempty independent reviews required")
        require(set(reviews).issubset(observations["independent_review"]["evidence_paths"]),"Independent observation does not name its reviews")
        for relative in reviews:
            covered(relative);review=read(relative)
            require(type(review.get("exit_code")) is int and review["exit_code"]==0 and review.get("status")=="passed" and
                review.get("review_role")=="independent_reviewer" and not review.get("calibration_only") and
                review.get("reviewed_build_hash")==r["build_hash"] and review.get("reviewed_code_hash")==r["code_hash"] and
                set(names(review.get("reviewed_run_ids"),"Reviewed Run identities missing"))==set(ids),"Independent review is for another baseline")
            checks=review.get("checks")
            require(isinstance(checks,list) and bool(checks) and all(isinstance(c,dict) and c.get("status")=="passed" for c in checks),"Independent review checks missing or failed")
            native_receipt(review["command_manifest"])
            hashed(review.get("evidence_hashes"),"Independent reviewed evidence missing")
            require(critical.issubset(review["evidence_hashes"]),"Independent review did not cover the current build/Run/report evidence")
        return {**result,"status":"passed","exit_code":0,"record":str(path)}
    except (ValueError,KeyError,TypeError,OSError,AttributeError,IndexError,OverflowError) as error:
        return {**result,"reason":str(error)}
def main():
    root=Path(__file__).resolve().parents[1]
    result=audit_ui_record(root,root/"artifacts/ui/acceptance.json")
    print(json.dumps(result,ensure_ascii=False)); return result["exit_code"]
if __name__=="__main__": raise SystemExit(main())
