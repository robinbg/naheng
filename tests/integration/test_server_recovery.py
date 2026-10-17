from fastapi.testclient import TestClient
from naheng.api.app import create_app

def test_server_start_marks_abandoned_job_interrupted(tmp_path):
    app=create_app(tmp_path,dispatch=True)
    store=app.state.store
    queued=store.create({"mode":"interactive"})
    running=store.create({"mode":"interactive"})
    store.state(running["run_id"],"running",.1)
    with TestClient(app):
        assert store.get(queued["run_id"])["state"]=="interrupted"
        assert store.get(running["run_id"])["state"]=="interrupted"
        assert all(e["type"]!="succeeded" for e in store.events(running["run_id"]))