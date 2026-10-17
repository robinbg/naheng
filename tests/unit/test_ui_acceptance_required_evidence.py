"""Synthetic saved-evidence calibration; no browser, worker, or proof execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from naheng.runtime.artifacts import code_hash

PROJECT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("required_ui_gate",PROJECT/"tools/check_ui_acceptance.py")
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)


class Packet:
    def __init__(self,root):
        self.root=root
        self.ids=["nh-"+str(i)*32 for i in (1,2)]
        self.files={"frontend/src/App.tsx":"synthetic calibration UI", "frontend/dist/index.html":"synthetic built UI"}
        self.files.update({"frontend/"+n:"{}" for n in ("package.json","package-lock.json","vite.config.ts","tsconfig.json","index.html")})
        self.files["browser.txt"]="Synthetic calibration only; no actual browser was operated."
        self.flush_files()
        sources={n:self.sha(n) for n in self.files if n.startswith("frontend/") and not n.startswith("frontend/dist/")}
        dist={"frontend/dist/index.html":self.sha("frontend/dist/index.html")}
        build_id=hashlib.sha256(json.dumps({"sources":sources,"dist":dist},sort_keys=True).encode()).hexdigest()
        source=code_hash(root)
        native={"argv":["synthetic-calibration-command"],"exit_code":0,"status":"completed","timed_out":False}
        self.files["build-command.json"]=copy.deepcopy(native)
        self.files["review-command.json"]=copy.deepcopy(native)
        self.files["build.json"]={"build_id":build_id,"source_hashes":sources,"dist_hashes":dist,
            "build_exit_code":0,"build_evidence":"build-command.json","build_command":native["argv"]}
        runs={}
        for number,identifier in enumerate(self.ids):
            prefix="runs/"+identifier+"/"
            config={"code_hash":source,"ambient_K":298.15+number,"initial_soc":.6,
                "sell_price_per_kWh":.3,"duration_s":60}
            self.files[prefix+"job.json"]={"run_id":identifier,"state":"succeeded","config":config}
            self.files[prefix+"manifest.json"]={"run_id":identifier,"complete":True,"mode":"interactive",
                "code_hash":source,"artifact_index":{"sensor_csv":"trace.csv","report":"report.html"}}
            self.files[prefix+"source.json"]={"code_hash":source,"files":sources}
            self.files[prefix+"trace.csv"]="timestamp_s,current_A,voltage_V,temperature_K\n0,1,3,298.15\n60,1,"+str(3+number)+",298.15\n"
            self.files[prefix+"report.html"]="<html>"+identifier+" synthetic calibration report</html>"
            self.files[prefix+"hashes.json"]={}
            runs[identifier]={"job_record":prefix+"job.json","manifest":prefix+"manifest.json",
                "source_index":prefix+"source.json","artifact_hashes":prefix+"hashes.json"}
        self.files["download.html"]=self.files["runs/"+self.ids[0]+"/report.html"]
        observations=[]
        for requirement in sorted(gate.REQUIRED):
            observations.append({"requirement":requirement,"status":"passed","run_ids":self.ids[:],
                "evidence_paths":["review.json"] if requirement=="independent_review" else ["browser.txt"],
                "mechanism":"independent_artifact_review" if requirement=="independent_review" else "real_browser","details":{}})
        self.record={"status":"passed","mode":"real_ui_acceptance","passed":sorted(gate.REQUIRED),
            "run_ids":self.ids[:],"code_hash":source,"build_hash":build_id,"build_manifest":"build.json",
            "run_artifacts":runs,"observations":observations,"independent_review_paths":["review.json"]}
        self.observation("seven_routes_same_run")["details"]={"routes":[{"route":route,"run_id":self.ids[0],
            "visible_run_id":self.ids[0],"state":"succeeded"} for route in sorted(gate.ROUTES)]}
        self.observation("report_opened")["details"]={"status":"opened","method":"normal_supported_viewer",
            "path":"download.html","visible_run_id":self.ids[0],"url":"http://localhost/report-preview","prior_denial_bypassed":False}
        self.review={"exit_code":0,"status":"passed","review_role":"independent_reviewer",
            "reviewed_build_hash":build_id,"reviewed_code_hash":source,"reviewed_run_ids":self.ids[:],
            "checks":[{"status":"passed","scope":"Synthetic evidence method calibration only"}],"command_manifest":"review-command.json"}

    def observation(self,name):
        return next(x for x in self.record["observations"] if x["requirement"]==name)

    def sha(self,name):
        return hashlib.sha256((self.root/name).read_bytes()).hexdigest()

    def flush_files(self):
        for name,value in self.files.items():
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(value if isinstance(value,str) else json.dumps(value),encoding="utf-8")

    def save(self):
        self.flush_files()
        for identifier in self.ids:
            prefix="runs/"+identifier+"/"
            self.files[prefix+"hashes.json"]={"sensor_csv":self.sha(prefix+"trace.csv"),"report":self.sha(prefix+"report.html")}
        self.flush_files()
        self.review.setdefault("evidence_hashes",{name:self.sha(name) for name in self.files})
        self.files["review.json"]=self.review
        self.flush_files()
        self.record["evidence_hashes"]={name:self.sha(name) for name in self.files}
        path=self.root/"acceptance.json";path.write_text(json.dumps(self.record),encoding="utf-8")
        return path


@pytest.fixture
def packet(tmp_path):
    return Packet(tmp_path)


def test_complete_synthetic_record_is_consistent_without_claiming_ui_execution(packet):
    result=gate.audit_ui_record(packet.root,packet.save())
    assert result["exit_code"]==0
    assert result["scope"]=="UI evidence record only; not scientific or release validation"


@pytest.mark.parametrize("case",[
    "empty_sources","empty_dist","bad_build_identity","bool_build_success","build_native_failed",
    "empty_reviews","arbitrary_run_id","duplicate_run_ids","empty_run_ids","labels_only","duplicate_observation",
    "observation_without_evidence","backend_replaces_browser","observation_unrelated_run","no_two_runs",
    "unchanged_inputs","unchanged_trace","nonfinite_trace","incomplete_run","replay_as_normal","wrong_run_source",
    "routes_different_runs","missing_route","wrong_download","report_not_opened","file_viewer_bypass",
    "review_wrong_run","review_wrong_build","review_wrong_source","review_checks_empty","review_checks_failed",
    "review_role_self","review_native_blocked","review_critical_evidence_empty","review_critical_evidence_partial",
    "calibration_claimed_real","blocked_observation_remains","wrong_current_source","passed_is_string",
])
def test_required_saved_evidence_failures_remain_blocked(packet,case):
    p=packet;first,second=p.ids;prefix="runs/"+first+"/";other="runs/"+second+"/"
    if case=="empty_sources":p.files["build.json"]["source_hashes"]={}
    elif case=="empty_dist":p.files["build.json"]["dist_hashes"]={}
    elif case=="bad_build_identity":p.record["build_hash"]=p.files["build.json"]["build_id"]="a"*64
    elif case=="bool_build_success":p.files["build.json"]["build_exit_code"]=False
    elif case=="build_native_failed":p.files["build-command.json"]["exit_code"]=1
    elif case=="empty_reviews":p.record["independent_review_paths"]=[]
    elif case=="arbitrary_run_id":p.record["run_ids"][0]="claimed"
    elif case=="duplicate_run_ids":p.record["run_ids"].append(first)
    elif case=="empty_run_ids":p.record["run_ids"]=[]
    elif case=="labels_only":p.record["observations"]=[]
    elif case=="duplicate_observation":p.record["observations"].append(copy.deepcopy(p.record["observations"][0]))
    elif case=="observation_without_evidence":p.observation("create_real_run")["evidence_paths"]=[]
    elif case=="backend_replaces_browser":p.observation("create_real_run")["mechanism"]="backend_function"
    elif case=="observation_unrelated_run":p.observation("create_real_run")["run_ids"]=["nh-"+"3"*32]
    elif case=="no_two_runs":p.record["run_artifacts"].pop(second)
    elif case=="unchanged_inputs":p.files[other+"job.json"]["config"]=copy.deepcopy(p.files[prefix+"job.json"]["config"])
    elif case=="unchanged_trace":p.files[other+"trace.csv"]=p.files[prefix+"trace.csv"]
    elif case=="nonfinite_trace":p.files[prefix+"trace.csv"]=p.files[prefix+"trace.csv"].replace("0,1,3,","0,1,nan,")
    elif case=="incomplete_run":p.files[prefix+"manifest.json"]["complete"]=False
    elif case=="replay_as_normal":p.files[prefix+"manifest.json"]["reused_from"]=second
    elif case=="wrong_run_source":p.files[prefix+"source.json"]["code_hash"]="b"*64
    elif case=="routes_different_runs":p.observation("seven_routes_same_run")["details"]["routes"][0]["run_id"]=second
    elif case=="missing_route":p.observation("seven_routes_same_run")["details"]["routes"].pop()
    elif case=="wrong_download":p.files["download.html"]=p.files[other+"report.html"]
    elif case=="report_not_opened":p.observation("report_opened")["details"]["status"]="downloaded_only"
    elif case=="file_viewer_bypass":p.observation("report_opened")["details"]["prior_denial_bypassed"]=True
    elif case=="review_wrong_run":p.review["reviewed_run_ids"]=[first]
    elif case=="review_wrong_build":p.review["reviewed_build_hash"]="b"*64
    elif case=="review_wrong_source":p.review["reviewed_code_hash"]="b"*64
    elif case=="review_checks_empty":p.review["checks"]=[]
    elif case=="review_checks_failed":p.review["checks"][0]["status"]="failed"
    elif case=="review_role_self":p.review["review_role"]="operator"
    elif case=="review_native_blocked":p.files["review-command.json"]["exit_code"]=2
    elif case=="review_critical_evidence_empty":p.review["evidence_hashes"]={}
    elif case=="review_critical_evidence_partial":
        p.flush_files();p.review["evidence_hashes"]={"browser.txt":p.sha("browser.txt")}
    elif case=="calibration_claimed_real":p.record["calibration_only"]=True
    elif case=="blocked_observation_remains":p.record["blocked"]=["report_opened"]
    elif case=="wrong_current_source":p.record["code_hash"]="a"*64
    elif case=="passed_is_string":p.record["passed"]=" ".join(sorted(gate.REQUIRED))
    result=gate.audit_ui_record(p.root,p.save())
    assert result["exit_code"]==2,(case,result)
    assert result["status"]=="blocked"


@pytest.mark.parametrize("shape",[[],None,True,3,"claimed"])
def test_malformed_record_is_structured_blocked(tmp_path,shape):
    path=tmp_path/"acceptance.json";path.write_text(json.dumps(shape),encoding="utf-8")
    assert gate.audit_ui_record(tmp_path,path)["exit_code"]==2


def test_later_file_added_to_dist_is_not_hidden_by_sparse_index(packet):
    path=packet.save()
    (packet.root/"frontend/dist/unreviewed.js").write_text("new bundle",encoding="utf-8")
    assert gate.audit_ui_record(packet.root,path)["exit_code"]==2


def test_evidence_escape_is_blocked(packet,tmp_path):
    packet.record["build_manifest"]="../outside.json"
    assert gate.audit_ui_record(packet.root,packet.save())["exit_code"]==2
