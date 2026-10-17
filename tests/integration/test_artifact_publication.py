from types import SimpleNamespace
import pytest
from naheng.runtime.jobs import JobStore
from naheng.runtime.artifacts import atomic_json
import naheng.runtime.publication as publication

@pytest.mark.parametrize("failed_name",["events.json","manifest.json","artifact_hashes.json"])
def test_publication_io_failure_never_marks_success(tmp_path,monkeypatch,failed_name):
    store=JobStore(tmp_path/"runs")
    job=store.create({"mode":"interactive"})
    store.state(job["run_id"],"running",.9)
    dest=store.root/job["run_id"]
    dest.mkdir()
    (dest/"trace.csv").write_text("synthetic unit-test file")
    original=publication.atomic_json
    def fail(path,value):
        if path.name==failed_name: raise OSError("injected publication IO error")
        original(path,value)
    monkeypatch.setattr(publication,"atomic_json",fail)
    manifest=SimpleNamespace(model_dump=lambda mode:{"complete":True,"scope":"technical failure-injection fixture"})
    with pytest.raises(OSError,match="injected"):
        publication.publish_complete(store,job["run_id"],dest,manifest,"<html>fixture</html>",{"report":"report.html","trace":"trace.csv","events":"events.json"},step=1,snapshot_id="fixture")
    assert store.get(job["run_id"])["state"]=="running"
    store.state(job["run_id"],"failed",error="injected publication IO error")
    assert not any(e["type"]=="succeeded" for e in store.events(job["run_id"]))

def test_terminal_success_follows_all_required_files(tmp_path):
    store=JobStore(tmp_path/"runs"); job=store.create({"mode":"interactive"})
    store.state(job["run_id"],"running",.9)
    dest=store.root/job["run_id"]; dest.mkdir()
    (dest/"trace.csv").write_text("synthetic unit-test file")
    manifest=SimpleNamespace(model_dump=lambda mode:{"complete":True})
    publication.publish_complete(store,job["run_id"],dest,manifest,"<html>fixture</html>",{"report":"report.html","trace":"trace.csv","events":"events.json"},step=1,snapshot_id="fixture")
    assert (dest/"artifact_hashes.json").is_file()
    assert store.get(job["run_id"])["state"]=="succeeded"
    assert store.events(job["run_id"])[-1]["type"]=="succeeded"
def test_late_cancel_invalidates_ready_manifest(tmp_path):
    import json
    store=JobStore(tmp_path/"runs"); job=store.create({"mode":"interactive"})
    store.state(job["run_id"],"running",.9)
    dest=store.root/job["run_id"]; dest.mkdir()
    (dest/"trace.csv").write_text("synthetic unit-test file")
    store.cancel(job["run_id"])
    manifest=SimpleNamespace(model_dump=lambda mode:{"complete":True})
    with pytest.raises(ValueError) as exc:
        publication.publish_complete(store,job["run_id"],dest,manifest,"<html>fixture</html>",{"report":"report.html","trace":"trace.csv","events":"events.json"},step=1,snapshot_id="fixture")
    publication.record_incomplete(store,job["run_id"],dest,exc.value,steps=1,sensor=[])
    store.state(job["run_id"],"cancelled")
    assert json.loads((dest/"manifest.json").read_text())["complete"] is False
    assert json.loads((dest/"checkpoint.json").read_text())["complete"] is False
    assert not any(e["type"]=="succeeded" for e in store.events(job["run_id"]))
def test_missing_required_file_prevents_success(tmp_path):
    store=JobStore(tmp_path/"runs"); job=store.create({"mode":"interactive"})
    store.state(job["run_id"],"running",.9)
    dest=store.root/job["run_id"]; dest.mkdir()
    manifest=SimpleNamespace(model_dump=lambda mode:{"complete":True})
    with pytest.raises(OSError,match="Missing"):
        publication.publish_complete(store,job["run_id"],dest,manifest,"<html>fixture</html>",{"trace":"missing.csv"},step=1,snapshot_id="fixture")
    assert store.get(job["run_id"])["state"]=="running"
    assert not any(e["type"]=="succeeded" for e in store.events(job["run_id"]))