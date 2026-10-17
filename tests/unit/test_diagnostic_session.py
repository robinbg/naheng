import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from naheng.estimation.diagnostic_session import DiagnosticRequest, run_diagnostics


def request_file(root, payload):
    source = root / "supplied.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    return source


def test_missing_measurements_are_saved_as_unknown_not_invented(tmp_path):
    source = request_file(tmp_path, {"analysis_id": "unavailable-protocol"})
    dest = tmp_path / "artifacts/diagnostic-a"
    result = run_diagnostics(tmp_path, source, dest)
    manifest = json.loads((dest / "manifest.json").read_text())
    saved = json.loads((dest / "result.json").read_text())
    assert result["exit_code"] == 0
    assert set(result["availability"].values()) == {"UNKNOWN"}
    assert saved["components"]["ica"]["intervals"] == []
    assert saved["components"]["impedance"]["spectrum"] == []
    assert saved["components"]["identifiability"]["rank"] is None
    assert saved["posterior_updated"] is False and saved["independent_experiment"] is False
    assert (dest / "input.json").read_bytes() == source.read_bytes()
    assert manifest["input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert manifest["result_sha256"] == hashlib.sha256((dest / "result.json").read_bytes()).hexdigest()


def test_existing_result_and_nonartifact_paths_are_rejected(tmp_path):
    source = request_file(tmp_path, {"analysis_id": "immutable-analysis"})
    dest = tmp_path / "artifacts/diagnostic-b"
    run_diagnostics(tmp_path, source, dest)
    original = (dest / "result.json").read_bytes()
    source.write_text('{"analysis_id":"replacement"}', encoding="utf-8")
    with pytest.raises(FileExistsError):
        run_diagnostics(tmp_path, source, dest)
    assert (dest / "result.json").read_bytes() == original
    with pytest.raises(ValueError, match="under project artifacts"):
        run_diagnostics(tmp_path, source, tmp_path / "data/raw")
    assert not (tmp_path / "data/raw").exists()


@pytest.mark.parametrize("extra", [{"reference_truth": [1, 2]}, {"execute_python": "pass"}])
def test_diagnostics_do_not_accept_reference_truth_or_code(extra):
    with pytest.raises(ValidationError):
        DiagnosticRequest.model_validate({"analysis_id": "sensor-only", **extra})


def test_linearization_cannot_be_applied_without_its_snapshot():
    with pytest.raises(ValidationError):
        DiagnosticRequest.model_validate({"analysis_id": "unbound", "diagnostic_options": [{
            "option_id": "candidate", "kind": "ica", "availability": "available",
            "cost_s": 2, "state_names": ["q"]}]})


def test_invalid_measurement_order_does_not_publish_a_curve(tmp_path):
    source = request_file(tmp_path, {"analysis_id": "out-of-order", "ica_trace": {
        "trace_id": "supplied-invalid", "provenance_type": "synthetic",
        "source_ref": "synthetic-method-negative-control", "time_s": [0, 1, 1],
        "voltage_V": [3, 3.1, 3.2], "current_A": [-1, -1, -1]}})
    dest = tmp_path / "artifacts/invalid-order"
    result = run_diagnostics(tmp_path, source, dest)
    saved = json.loads((dest / "result.json").read_text())
    assert result["exit_code"] == 1
    assert saved["components"]["ica"]["status"] == "FAIL"
    assert saved["components"]["ica"]["intervals"] == []
    assert json.loads((dest / "manifest.json").read_text())["exit_code"] == 1


def test_public_cli_uses_real_input_and_preserves_existing_output(tmp_path, monkeypatch, capsys):
    from naheng import cli
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    source = request_file(tmp_path, {"analysis_id": "cli-supplied"})
    dest = tmp_path / "artifacts/cli-run"
    argv = ["diagnose", "--input", str(source), "--out", str(dest)]
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["availability"]["impedance"] == "UNKNOWN"
    before = (dest / "manifest.json").read_bytes()
    assert cli.main(argv) != 0
    assert (dest / "manifest.json").read_bytes() == before
