import importlib.util,json
from pathlib import Path
spec=importlib.util.spec_from_file_location("ui_gate",Path(__file__).resolve().parents[2]/"tools/check_ui_acceptance.py")
gate=importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
def test_success_labels_with_missing_evidence_are_blocked(tmp_path):
    record={"status":"passed","passed":sorted(gate.REQUIRED),"build_hash":"claimed","run_ids":["claimed"],"evidence_hashes":{"missing.jpg":"claimed"},"build_manifest":"missing.json","independent_review_paths":[]}
    path=tmp_path/"acceptance.json"; path.write_text(json.dumps(record))
    assert gate.audit_ui_record(tmp_path,path)["exit_code"]==2
    assert gate.audit_ui_record(tmp_path,path)["status"]=="blocked"
def test_real_partial_observations_do_not_imply_report_opened(tmp_path):
    path=tmp_path/"acceptance.json"
    path.write_text(json.dumps({"status":"partial","passed":sorted(gate.REQUIRED-{"report_opened"})}))
    result=gate.audit_ui_record(tmp_path,path)
    assert result["missing"]==["report_opened"]
    assert result["exit_code"]==2