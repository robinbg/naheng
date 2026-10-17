"""Capabilities expose individually validated proof evidence, never a label alone."""
import json
from fastapi.testclient import TestClient
from naheng.api.app import create_app


def test_unverified_legacy_proof_does_not_break_capabilities(tmp_path):
    path = tmp_path / "artifacts/formal/foundation/manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"status": "blocked", "checked": False}))
    with TestClient(create_app(tmp_path, dispatch=False)) as client:
        response = client.get("/api/capabilities")
    assert response.status_code == 200
    proof = response.json()["formal"]
    assert proof["status"] == "unverified" and proof["evidence_ids"] == []
    assert "Unverified evidence" in proof["reason"]


def test_changed_active_manifest_withdraws_capability(tmp_path):
    path = tmp_path / "artifacts/formal/active_foundation.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"manifest": "artifacts/formal/missing.json", "sha256": "0" * 64}))
    with TestClient(create_app(tmp_path, dispatch=False)) as client:
        response = client.get("/api/capabilities")
    assert response.status_code == 200
    assert response.json()["formal"]["status"] == "unverified"
    assert "withdrawn" in response.json()["formal"]["reason"]
