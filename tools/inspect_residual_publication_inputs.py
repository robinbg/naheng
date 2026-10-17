"""Read-only publication prerequisite audit; grants no proof/runtime authority."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    handoff_path = ROOT / "artifacts/review/residual_delivery-f65e1805.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    source = ROOT / handoff["source"]["frozen"]
    manifest = ROOT / handoff["actual_lean_result"]["manifest"]
    proof = json.loads(manifest.read_text(encoding="utf-8"))
    command = ROOT / handoff["actual_lean_result"]["durable_command"]
    record = json.loads(command.read_text(encoding="utf-8"))
    checks = {
        "frozen_source_exact": digest(source) == handoff["source"]["sha256"] == proof["source_sha256"],
        "actual_compilation_finished_zero": record["exit_code"] == proof["exit_code"] == 0 and not record["timed_out"],
        "transitive_audit_passed": proof["audit"]["status"] == "passed",
        "seven_identical_declared_targets": proof["targets"] == handoff["actual_lean_result"]["targets"] and len(proof["targets"]) == 7,
        "published_exact_dependency_unchanged": digest(ROOT / handoff["formal_dependency"]["source"]) == handoff["formal_dependency"]["source_sha256_before_and_after_actual_check"],
        "candidate_still_unpublished_without_runtime_authority": not handoff["published"] and not handoff["runtime_authority_granted"],
    }
    for name in ("checker", "mapping"):
        checks[name + "_source_unchanged"] = digest(ROOT / handoff["source"][name]) == handoff["source"][name + "_sha256"]
    out = ROOT / "artifacts/review" / ("residual-publication-inputs-" + uuid.uuid4().hex[:8])
    out.mkdir(exist_ok=False)
    result = {"utc": datetime.now(timezone.utc).isoformat(), "checks": checks,
              "exit_code": 0 if all(checks.values()) else 2,
              "scope": "Byte and previous-command evidence prerequisites only; no new theorem proof or independent mathematical review",
              "source": str(source.relative_to(ROOT)), "source_sha256": digest(source),
              "remaining": handoff["remaining_requirements"],
              "next_implementation": "Root reviews mathematical scope, publishes a separate residual slice with actual build/audit, refreshes foundation before any new worker; full reduction/core remain incomplete"}
    (out / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(out / "manifest.json"), **result}, ensure_ascii=False))
    return result["exit_code"]

if __name__ == "__main__":
    raise SystemExit(main())
