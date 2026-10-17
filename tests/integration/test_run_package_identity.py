import copy,json
from pathlib import Path
from fastapi.testclient import TestClient
from naheng.api.app import create_app
from naheng.runtime.artifacts import atomic_json

def test_selected_run_package_and_replay_use_saved_revision(tmp_path):
    original=json.loads((Path(__file__).resolve().parents[2]/"model_packages/research_base/package.json").read_text(encoding="utf-8"))
    app=create_app(tmp_path,dispatch=False)
    store=app.state.store
    c=TestClient(app)
    ids=[]
    for revision in ("run-parameter-a","run-parameter-b"):
        job=store.create({"mode":"interactive"})
        ids.append(job["run_id"])
        package=copy.deepcopy(original)
        package.update(parameter_revision=revision,parameters={"calibration":"synthetic"})
        atomic_json(store.root/job["run_id"]/"model_package.json",package)
        assert store.try_start(job['run_id'])
        store.state(job["run_id"],"succeeded",1)
        assert c.get(f"/api/runs/{job['run_id']}/model-package").json()["parameter_revision"]==revision
    replay=store.create({"mode":"replay","replay_source":ids[0]})
    assert store.try_start(replay['run_id'])
    store.state(replay["run_id"],"succeeded",1)
    assert c.get(f"/api/runs/{replay['run_id']}/model-package").json()["parameter_revision"]=="run-parameter-a"
    pending=store.create({"mode":"interactive"})
    assert c.get(f"/api/runs/{pending['run_id']}/model-package").status_code==409
    assert c.get("/api/runs/absent/model-package").status_code==404
