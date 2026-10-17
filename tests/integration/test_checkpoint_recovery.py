"""Real numerical continuation, with synthetic research inputs and no oracle PF."""
from copy import deepcopy
from dataclasses import replace
import hashlib,json
import os,subprocess,sys,uuid
from pathlib import Path
import numpy as np
import pytest
from naheng.domain.contracts import Observation,Action
from naheng.models.site_model import SiteModel
from naheng.estimation.particle_filter import ParticleFilter
from naheng.economics.ledger import EnergyLedger
from naheng.runtime.jobs import JobStore
from naheng.runtime.recovery import (config_digest,save_recovery_checkpoint,load_recovery_checkpoint,
    restore_sensor_rng,restore_ledger,rekey_history,_io_path)

CODE="a"*64
LOCK="b"*64
CONFIG={"seed":1234,"step_s":10,"duration_s":40,"filter_particles":16,"initial_soc":.6}


def start(run_id):
    model=SiteModel()
    state=model.initial_state()
    rng=np.random.default_rng(CONFIG["seed"])
    pf=ParticleFilter(run_id,model,seed=4321,particles=16,voltage_noise_V=.003)
    sensed=model.observe(state,0)
    obs=Observation(run_id=run_id,timestamp_s=0,current_A=0,
        voltage_V=sensed["voltage_V"]+rng.normal(0,.01),temperature_K=sensed["temperature_K"]+rng.normal(0,.2))
    snapshot=pf.update(obs,duration_s=0)
    return {"run_id":run_id,"model":model,"state":state,"rng":rng,"pf":pf,
        "ledger":EnergyLedger(run_id),"sensor":[obs.model_dump()],"posterior":[snapshot.model_dump(mode="json")],
        "actions":[],"decisions":[],"truth":[],"step":0,"logical_time_s":0}


def advance(runtime,stop=4):
    for step in range(runtime["step"],stop):
        t=step*10;dt=10;current=[.05,-.03,.04,-.02][step]
        snapshot=runtime["pf"].snapshot
        action=Action(action_id=f"{runtime['run_id']}-step-{step}",snapshot_id=snapshot.snapshot_id,
            start_s=t,duration_s=dt,current_A=current,thermal_W=.01)
        integrated=runtime["model"].integrate(runtime["state"],current,dt,thermal_W=.01)
        assert integrated.elapsed_s==dt and not integrated.events
        runtime["state"]=integrated.state
        runtime["ledger"].append(action,execution_id=action.action_id,energy_J=integrated.energy_J,
            thermal_energy_J=integrated.thermal_management_energy_J,duration_s=integrated.elapsed_s)
        runtime["actions"].append({**action.model_dump(),"executed_duration_s":integrated.elapsed_s,
            "energy_J":integrated.energy_J,"inventory_residual_mol":integrated.inventory_residual_mol})
        runtime["decisions"].append({"action_id":action.action_id,"snapshot_id":snapshot.snapshot_id,
            "scope":"fixed-current numerical recovery fixture; no admission guarantee"})
        runtime["truth"].append({"timestamp_s":t+dt,"state":integrated.state.tolist(),
            "inventory_residual_mol":integrated.inventory_residual_mol,"events":integrated.events})
        sensed=runtime["model"].observe(integrated.state,current)
        obs=Observation(run_id=runtime["run_id"],timestamp_s=t+dt,current_A=current,
            voltage_V=sensed["voltage_V"]+runtime["rng"].normal(0,.01),
            temperature_K=sensed["temperature_K"]+runtime["rng"].normal(0,.2))
        runtime["sensor"].append(obs.model_dump())
        snapshot=runtime["pf"].update(obs,duration_s=dt,thermal_W=.01)
        runtime["posterior"].append(snapshot.model_dump(mode="json"))
        runtime["step"],runtime["logical_time_s"]=step+1,t+dt
    return runtime


def saved(tmp_path):
    store=JobStore(tmp_path/"runs")
    run=store.create(CONFIG)["run_id"];store.try_start(run)
    runtime=advance(start(run),2)
    checkpoint=save_recovery_checkpoint(store,run,code_hash=CODE,lock_hash=LOCK,input_hash=config_digest(CONFIG),
        step=2,logical_time_s=20,simulator_state=runtime["state"],sensor_rng=runtime["rng"],pf=runtime["pf"],
        sensor=runtime["sensor"],posterior=runtime["posterior"],actions=runtime["actions"],
        cashflows=runtime["ledger"].entries,decisions=runtime["decisions"],truth=runtime["truth"])
    store.cancel(run);store.state(run,"cancelled")
    return store,run,runtime,checkpoint


def load(store,run,new_run="continued",checkpoint=None,**kwargs):
    return load_recovery_checkpoint(store,run,expected_code_hash=kwargs.get("code",CODE),
        expected_lock_hash=kwargs.get("lock",LOCK),expected_input_hash=kwargs.get("input",config_digest(CONFIG)),
        new_run_id=new_run,checkpoint=checkpoint)


def test_real_integrations_and_posterior_match_uninterrupted_after_new_run_resume(tmp_path):
    store,run,partial,checkpoint=saved(tmp_path)
    uninterrupted=advance(start("uninterrupted"))
    parent_files={p:hashlib.sha256(p.read_bytes()).hexdigest() for base in (store.root/run,store.root/"evaluator"/run) for p in _io_path(base).rglob("*") if p.is_file()}
    restored=load(store,run)
    model=SiteModel()
    runtime={**restored,"model":model,"state":np.array(restored["state"]),
        "rng":restore_sensor_rng(restored["sensor_rng_state"]),
        "pf":ParticleFilter.from_checkpoint("continued",model,restored["pf_checkpoint"]),
        "ledger":EnergyLedger("continued")}
    restore_ledger(runtime["ledger"],runtime["actions"],runtime["cashflows"])
    assert runtime["pf"].snapshot.snapshot_id==runtime["posterior"][-1]["snapshot_id"]
    advance(runtime)
    assert runtime["truth"]==uninterrupted["truth"]
    for actual,expected in zip(runtime["posterior"],uninterrupted["posterior"]):
        for key in ("samples","weights","mean","quantiles","ess","identifiability","parameter_revision","obs_until_s"):
            assert actual[key]==expected[key]
    for actual,expected in zip(runtime["sensor"],uninterrupted["sensor"]):
        assert {k:v for k,v in actual.items() if k!="run_id"}=={k:v for k,v in expected.items() if k!="run_id"}
    for actual,expected in zip(runtime["ledger"].entries,uninterrupted["ledger"].entries):
        assert {k:v for k,v in actual.items() if k not in {"run_id","execution_id","action_id","snapshot_id"}}=={k:v for k,v in expected.items() if k not in {"run_id","execution_id","action_id","snapshot_id"}}
    assert runtime["pf"].export_checkpoint()["rng_state"]==uninterrupted["pf"].export_checkpoint()["rng_state"]
    assert runtime["lineage"]["independent_operational_trajectories"]==0
    assert len(runtime["lineage"]["snapshot_id_mapping"])==3
    assert all(hashlib.sha256(path.read_bytes()).hexdigest()==digest for path,digest in parent_files.items())
    assert store.get(run)["state"]=="cancelled"
    assert "state" not in checkpoint and "truth" not in checkpoint and "samples" not in checkpoint
    assert checkpoint["complete"] is False


@pytest.mark.parametrize("key",["code","lock","input"])
def test_recovery_rejects_changed_source_lock_or_scientific_inputs(tmp_path,key):
    store,run,_,_=saved(tmp_path)
    with pytest.raises(ValueError,match="mismatch"): load(store,run,**{key:"f"*64})


def test_bundle_mutation_and_pointer_escape_rejected(tmp_path):
    store,run,_,checkpoint=saved(tmp_path)
    escaped=deepcopy(checkpoint);escaped["private_recovery"]["relative_path"]="../outside.json"
    with pytest.raises(ValueError,match="outside"):load(store,run,checkpoint=escaped)
    private=_io_path(store.root/checkpoint["private_recovery"]["relative_path"])
    private.write_bytes(private.read_bytes()+b" ")
    with pytest.raises(ValueError,match="byte identity"):load(store,run)


def test_pf_checkpoint_is_detached_post_resampling_and_rejects_simulator_truth(tmp_path):
    runtime=start("original")
    assert runtime["pf"].update_diagnostics[-1]["resampled"]
    checkpoint=runtime["pf"].export_checkpoint()
    assert checkpoint["weights"]!=checkpoint["last_snapshot"]["weights"]
    restored=ParticleFilter.from_checkpoint("new",runtime["model"],checkpoint)
    original=restored.export_checkpoint()["samples"][0][0]
    checkpoint["samples"][0][0]=-999
    assert restored.export_checkpoint()["samples"][0][0]==original
    bad=runtime["pf"].export_checkpoint();bad["simulator_state"]=runtime["state"].tolist()
    with pytest.raises(ValueError,match="schema"):ParticleFilter.from_checkpoint("new",runtime["model"],bad)
    changed=SiteModel(replace(runtime["model"].params,thermal_cop=2))
    with pytest.raises(ValueError,match="parameters changed"):
        ParticleFilter.from_checkpoint("new",changed,runtime["pf"].export_checkpoint())


def test_immutable_bundle_and_history_rekey_are_idempotent(tmp_path):
    store,run,runtime,checkpoint=saved(tmp_path)
    again=save_recovery_checkpoint(store,run,code_hash=CODE,lock_hash=LOCK,input_hash=config_digest(CONFIG),
        step=2,logical_time_s=20,simulator_state=runtime["state"],sensor_rng=runtime["rng"],pf=runtime["pf"],
        sensor=runtime["sensor"],posterior=runtime["posterior"],actions=runtime["actions"],
        cashflows=runtime["ledger"].entries,decisions=runtime["decisions"],truth=runtime["truth"])
    assert again==checkpoint
    restored=load(store,run)
    assert restored==load(store,run)
    assert len(list(_io_path(store.root/"evaluator"/run).glob("*.json")))==1
    assert config_digest(CONFIG)==config_digest({**CONFIG,"source_dir":"newpath","recovery_source":"parent","recovery_lineage":{}})
    assert config_digest(CONFIG)!=config_digest({**CONFIG,"seed":999})


def test_running_source_cannot_be_resumed_concurrently(tmp_path):
    store,run,_,_=saved(tmp_path)
    new=store.create(CONFIG)["run_id"];store.try_start(new)
    with pytest.raises(ValueError,match="incomplete terminal"):load(store,new)


def test_nonresampled_particle_weights_and_next_rng_update_are_preserved():
    model=SiteModel();state=model.initial_state()
    estimator=ParticleFilter("first",model,seed=29,particles=8,voltage_noise_V=10)
    sensed=model.observe(state,0)
    estimator.update(Observation(run_id="first",timestamp_s=0,current_A=0,**{k:sensed[k] for k in ("voltage_V","temperature_K")}))
    assert not estimator.update_diagnostics[-1]["resampled"]
    payload=json.loads(json.dumps(estimator.export_checkpoint()))
    restored=ParticleFilter.from_checkpoint("second",model,payload)
    assert restored.export_checkpoint()["weights"]==payload["weights"]
    assert len(set(payload["weights"]))>1
    integrated=model.integrate(state,.01,2)
    sensed=model.observe(integrated.state,.01)
    values={"timestamp_s":2,"current_A":.01,"voltage_V":sensed["voltage_V"],"temperature_K":sensed["temperature_K"]}
    a=estimator.update(Observation(run_id="first",**values),duration_s=2)
    b=restored.update(Observation(run_id="second",**values),duration_s=2)
    for key in ("samples","weights","mean","quantiles","ess"):
        assert getattr(a,key)==getattr(b,key)
    assert estimator.export_checkpoint()["rng_state"]==restored.export_checkpoint()["rng_state"]


@pytest.mark.parametrize("cancel_step",[0,1,3])
def test_frozen_runner_cancel_at_boundary_then_resume_matches_full_run(cancel_step):
    """Actual runner/admission/forecast; cancellation hook only requests cancellation."""
    import yaml
    import pyarrow.parquet as pq
    from naheng.runtime.freezing import freeze_source
    from naheng.runtime.resumption import prepare_recovery
    project=Path(__file__).resolve().parents[2]
    evidence=project/"artifacts"/"recovery-tests"/uuid.uuid4().hex[:8]
    store=JobStore(evidence/"artifacts"/"runs")
    config=yaml.safe_load((project/"configs/scenarios/acceptance_loop.yaml").read_text(encoding="utf-8"))
    config.update(duration_s=150,step_s=60,filter_particles=8,forecast_paths=2,forecast_horizon_s=120)
    def create(source_project=project):
        job=store.create(config)
        source,digest=freeze_source(source_project,store.root/job["run_id"])
        bound={**config,"source_dir":str(source),"code_hash":digest}
        store.bind_frozen_config(job["run_id"],bound)
        return store.get(job["run_id"])
    def execute_job(job,cancel_step=None):
        code="""import sys,json
from pathlib import Path
from naheng.runtime.jobs import JobStore
from naheng.runtime.runner import execute
project,root,run_id,cancel_step=sys.argv[1:]
store=JobStore(Path(root))
if cancel_step!='None':
    original=JobStore.checkpoint
    def boundary(self,run,value):
        original(self,run,value)
        if run==run_id and value.get('recoverable') and not value['complete'] and value['step']==int(cancel_step):
            self.cancel(run)
    JobStore.checkpoint=boundary
execute(Path(project),store,run_id)
print(json.dumps({'state':store.get(run_id)['state'],'scope':'real numerical runner recovery test'}))
"""
        command=[sys.executable,"-c",code,str(project),str(store.root),job["run_id"],str(cancel_step)]
        completed=subprocess.run(command,cwd=project,env={**os.environ,"PYTHONPATH":str(Path(job["config"]["source_dir"])/"src"),"PYTHONIOENCODING":"utf-8"},capture_output=True,timeout=120)
        (store.root/job["run_id"]/"test_worker_stdout.log").write_bytes(completed.stdout)
        (store.root/job["run_id"]/"test_worker_stderr.log").write_bytes(completed.stderr)
        assert completed.returncode==0,completed.stderr.decode(errors="replace")
        return store.get(job["run_id"])
    complete=create();assert execute_job(complete)["state"]=="succeeded"
    parent=create(Path(complete["config"]["source_dir"]));assert execute_job(parent,cancel_step)["state"]=="cancelled"
    checkpoint=json.loads((store.root/parent["run_id"]/"checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["step"]==cancel_step and checkpoint["logical_time_s"]==min(cancel_step*60,150)
    assert checkpoint["complete"] is False and checkpoint["recoverable"] is True
    files={p:hashlib.sha256(p.read_bytes()).hexdigest() for base in (store.root/parent["run_id"],store.root/"evaluator"/parent["run_id"]) for p in _io_path(base).rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    child=prepare_recovery(project,store,parent["run_id"])
    assert child["run_id"]!=parent["run_id"]
    assert execute_job(child)["state"]=="succeeded"
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in files.items())
    assert store.get(parent["run_id"])["state"]=="cancelled"
    full_dir=store.root/complete["run_id"];child_dir=store.root/child["run_id"]
    read=lambda path:json.loads(path.read_text(encoding="utf-8"))
    ignored={"run_id","action_id","execution_id","snapshot_id"}
    for filename in ("sensor_trace.parquet","actions.parquet","cashflows.parquet"):
        full=pq.read_table(full_dir/filename).to_pylist();resumed=pq.read_table(child_dir/filename).to_pylist()
        assert len(full)==len(resumed)
        for a,b in zip(full,resumed): assert {k:v for k,v in a.items() if k not in ignored}=={k:v for k,v in b.items() if k not in ignored}
    full=read(full_dir/"posterior.json");resumed=read(child_dir/"posterior.json")
    for a,b in zip(full,resumed): assert {k:v for k,v in a.items() if k not in ignored}=={k:v for k,v in b.items() if k not in ignored}
    assert read(store.root/"evaluator"/complete["run_id"]/"reference_trace.json")==read(store.root/"evaluator"/child["run_id"]/"reference_trace.json")
    for filename in ("economics.json","forecast.json"):
        full=read(full_dir/filename);resumed=read(child_dir/filename)
        if filename=="economics.json":
            assert {k:v for k,v in full.items() if k not in ignored}=={k:v for k,v in resumed.items() if k not in ignored}
        else:
            # Conditional numerical paths are identical; the query identity and
            # elapsed computation time are intentionally new execution metadata.
            for key in ("rul","risk","paths"):
                assert full[key]==resumed[key]
            assert {k:v for k,v in full["budget"].items() if k!="walltime_s"}=={k:v for k,v in resumed["budget"].items() if k!="walltime_s"}
    lineage=read(child_dir/"recovery_lineage.json")
    assert lineage["independent_sample"] is False and lineage["independent_operational_trajectories"]==0
    assert len(lineage["action_id_mapping"])==cancel_step and len(lineage["snapshot_id_mapping"])==cancel_step+1
    manifest=read(child_dir/"manifest.json")
    assert manifest["independent_sample"] is False and manifest["recovered_from"]==parent["run_id"]
    from fastapi.testclient import TestClient
    from naheng.api.app import create_app
    def contains_private(value):
        if isinstance(value,dict): return bool({"source_checkpoint","private_recovery"}&set(value)) or any(contains_private(v) for v in value.values())
        if isinstance(value,list): return any(contains_private(v) for v in value)
        return False
    with TestClient(create_app(evidence,dispatch=False)) as client:
        for endpoint in (f"/api/runs/{child['run_id']}","/api/runs",f"/api/runs/{child['run_id']}/manifest",f"/api/runs/{child['run_id']}/artifacts/recovery_lineage"):
            response=client.get(endpoint)
            assert response.status_code==200,response.text
            assert not contains_private(response.json())
        api_lineage=client.get(f"/api/runs/{child['run_id']}/artifacts/recovery_lineage").json()
        assert api_lineage==lineage
        assert client.get(f"/api/runs/{child['run_id']}/manifest").json()["independent_sample"] is False
    record={"scope":"actual frozen runner/admission/PF/forecast and historical cashflow continuation; synthetic research model",
        "full_run_id":complete["run_id"],"parent_run_id":parent["run_id"],"recovered_run_id":child["run_id"],
        "cancel_step":cancel_step,"numerical_equality":"exact","tail_step_s":30,
        "independent_operational_trajectories_added":0,"parent_unchanged":True,
        "code_hash":child["config"]["code_hash"],"dependency_lock_hash":manifest["dependency_lock_hash"]}
    (evidence/"result.json").write_text(json.dumps(record,indent=2),encoding="utf-8")
