from __future__ import annotations
import csv, json, os, re, subprocess, sys, threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from naheng.domain.contracts import Observation, PosteriorSnapshot, Action, ForecastQuery, Evidence, ModelPackage, RegisteredModelPackage, RunManifest
from naheng.runtime.jobs import JobStore,TERMINAL,JobQuotaExceeded
from naheng.runtime.artifacts import code_hash, safe_artifact,atomic_json,sha256_file
from naheng.runtime.freezing import freeze_source
from naheng.runtime.dispatch import spawn,monitor

from naheng.api.datasets import DatasetImport, save as save_dataset, read as read_dataset, artifact as dataset_file
from naheng.api.reports import run_report_reference

class RunRequest(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    scenario_id: str="acceptance_loop"
    ambient_K: float=Field(default=298.15,ge=273.15,le=333.15)
    initial_soc: float=Field(default=.6,ge=.15,le=.85)
    sell_price_per_kWh: float=Field(default=.30,ge=0,le=10)
    buy_price_per_kWh: float=Field(default=.15,ge=0,le=10)
    duration_s: float=Field(default=1800,ge=60,le=3600)
    stored_sodium_rate_upper_mol_per_s: float | None = None
    mode: str="interactive"
    validity_profile: Literal['off','engineering-residual-v1']='off'
    synthetic_sensor_profile: Literal['baseline','voltage-bias-after-first-v1']='baseline'
    requested_service_power_W: float=Field(default=.04,ge=0,le=10)

    @field_validator('requested_service_power_W',mode='before')
    @classmethod
    def service_numeric(cls,value):
        if type(value) not in (int,float):raise ValueError('Numeric service request required')
        return value

    @model_validator(mode='after')
    def coherent_monitoring_profile(self):
        if self.synthetic_sensor_profile!='baseline' and self.validity_profile=='off':
            raise ValueError('Synthetic sensor stress requires explicit validity monitoring')
        return self
class RunRef(BaseModel):
    model_config=ConfigDict(extra="forbid")
    run_id: str

class LifecycleRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    profile: Literal['pilot']='pilot'
    mode: Literal['interactive','batch']='interactive'
    sell_price_per_kWh: float=Field(default=.3,ge=0,le=10)
    buy_price_per_kWh: float=Field(default=.15,ge=0,le=10)
    replacement_cost_CNY: float=Field(default=100,ge=0,le=100000)

    @field_validator('sell_price_per_kWh','buy_price_per_kWh','replacement_cost_CNY',mode='before')
    @classmethod
    def numeric_input(cls,value):
        if type(value) not in (int,float): raise ValueError('Numeric lifecycle input required')
        return value
def create_app(root:Path,dispatch=True):
    root=Path(root); store=JobStore(root/"artifacts/runs")
    from naheng.runtime.forecast_jobs import forecast_store,create_forecast_job,dispatch_forecast_job,get_forecast_result
    prediction_store=forecast_store(root)
    @asynccontextmanager
    async def lifespan(app):
        if dispatch:
            store.recover_interrupted()
            prediction_store.recover_interrupted()
        yield
    app=FastAPI(title="钠衡研究计算API",version="0.1.0",lifespan=lifespan)
    app.add_middleware(CORSMiddleware,allow_origins=["http://127.0.0.1:5173","http://localhost:5173"],allow_methods=["GET","POST"],allow_headers=["Content-Type"])
    app.state.store=store
    children={}
    admission_lock=threading.RLock()
    def public_job(value):
        from naheng.runtime.resumption import public_lineage
        config=dict(value['config'])
        if 'recovery_lineage' in config: config['recovery_lineage']=public_lineage(config['recovery_lineage'])
        return {**value,'config':config}
    def job(run_id):
        try: return store.get(run_id)
        except KeyError: raise HTTPException(404,"Unknown RunID")
    def completed_dir(run_id,allow_lifecycle_partial=False):
        j=job(run_id)
        partial=allow_lifecycle_partial and j['config'].get('task_kind')=='lifecycle-finance' and j['state'] in TERMINAL
        if j["state"]!="succeeded" and not partial: raise HTTPException(409,{"state":j["state"],"reason":"Result is not complete"})
        source=j["config"].get("replay_source",run_id)
        return store.root/source
    def result(run_id,name):
        directory=completed_dir(run_id,allow_lifecycle_partial=name=='manifest.json'); path=directory/name
        if not path.is_file(): raise HTTPException(409,"Result field unavailable")
        return json.loads(path.read_text(encoding="utf-8"))
    @app.post('/api/datasets/import', status_code=201, openapi_extra={
        'requestBody': {'required': True, 'content': {'application/json': {'schema': DatasetImport.model_json_schema()}}}})
    async def dataset_import(request: Request):
        from pydantic import ValidationError
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            raise HTTPException(415, 'JSON CSV import required')
        body = bytearray()
        async for chunk in request.stream():
            if len(body)+len(chunk) > 3*1024*1024:
                raise HTTPException(413, 'Dataset request exceeds 3 MiB')
            body.extend(chunk)
        try:
            value = DatasetImport.model_validate_json(bytes(body))
            return save_dataset(root, value)
        except ValidationError as error:
            raise HTTPException(422, error.errors(include_input=False, include_context=False))
        except (ValueError, csv.Error) as error:
            raise HTTPException(422, str(error))
        except OSError:
            raise HTTPException(503, 'Dataset could not be persisted; no completed import recorded')

    @app.get('/api/datasets')
    def datasets():
        directory = root/'artifacts/datasets'
        records = []
        if not directory.is_dir(): return records
        for item in sorted(directory.iterdir(), key=lambda p:p.stat().st_mtime, reverse=True)[:100]:
            if not item.is_dir() or not (item/'manifest.json').is_file(): continue
            try:
                packet = read_dataset(root, item.name)
                records.append({key:packet[key] for key in ('dataset_id','filename','row_count','provenance_type','code_hash')})
            except (ValueError,OSError,KeyError):
                records.append({'dataset_id':item.name, 'filename':'不可核验的保存记录', 'status':'unknown'})
        return records

    @app.get('/api/datasets/{identifier}')
    def dataset(identifier: str):
        try: return read_dataset(root, identifier)
        except KeyError: raise HTTPException(404, 'Unknown dataset')
        except (ValueError,OSError) as error: raise HTTPException(409, str(error))

    @app.get('/api/datasets/{identifier}/artifacts/{key}')
    def dataset_artifact(identifier: str, key: str):
        try: path = dataset_file(root, identifier, key)
        except KeyError: raise HTTPException(404, 'Unknown dataset artifact')
        except (ValueError,OSError) as error: raise HTTPException(409, str(error))
        return FileResponse(path, filename=path.name)

    @app.get('/api/datasets/{identifier}/report-preview')
    def dataset_preview(identifier: str):
        try: path = dataset_file(root, identifier, 'report')
        except KeyError: raise HTTPException(404, 'Unknown dataset report')
        except (ValueError,OSError) as error: raise HTTPException(409, str(error))
        return FileResponse(path, media_type='text/html', headers={
            'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'",
            'X-Content-Type-Options':'nosniff'})

    @app.get("/api/health")
    def health(): return {"status":"alive","version":"0.1.0","scope":"Not a scientific validation"}
    @app.get("/api/capabilities")
    def capabilities():
        from naheng.formal.active_evidence import select_foundation, select_core
        from naheng.packages.evidence_import import load_evidence
        f, reason = select_foundation(root)
        records = []
        if f is not None:
            try:
                imported = load_evidence(root, f)
                records = imported["records"]
            except (ValueError, OSError) as error:
                reason = "Proof authority unavailable: " + str(error)
        formal = {"status": "checked" if records else "unverified",
                  "scope": "Only individually imported foundation declarations; no T1/T2/T3 or physical-cell safety grant",
                  "evidence_ids": [row["evidence_id"] for row in records], "reason": reason}
        core_path, core_reason = select_core(root)
        core_records = []
        if core_path is not None:
            try: core_records = load_evidence(root, core_path)['records']
            except (ValueError,OSError) as error: core_reason = 'Core source/statement import rejected: '+str(error)
        core = {'status':'checked' if core_records else 'unverified', 'target_count':len(core_records),
            'reason':core_reason, 'scope':'Kernel-audited model-level declarations only; continuous numerical/closed-loop/cell applicability requires independent certificates'}
        return {"numerical_loop":{"status":"implemented","provenance_type":"synthetic"},"formal": formal,"formal_core":core,"public_sodium_data":{"status":"external_model_validation_incomplete"},"hardware":{"status":"disabled"},"modes":["interactive","batch","replay"],"unsupported_events":["fire","sodium_plating"],"release":{"status":"incomplete"}}
    @app.get("/api/scenarios")
    def scenarios(): return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((root/"configs/scenarios").glob("*.yaml"))]
    @app.get("/api/runs")
    def runs(): return [public_job(value) for value in store.list()]
    @app.post("/api/runs",status_code=202)
    def create(request:RunRequest):
        if request.scenario_id!="acceptance_loop": raise HTTPException(422,"Unknown scenario")
        if request.mode not in ("interactive","batch"): raise HTTPException(422,"Use replay endpoint for registered replay")
        config=yaml.safe_load((root/"configs/scenarios/acceptance_loop.yaml").read_text(encoding="utf-8"))
        config.update(request.model_dump()); config["code_hash"]=code_hash(root)
        with admission_lock:
            if store.count_nonterminal()+prediction_store.count_nonterminal()>=4: raise HTTPException(429,"Local worker quota reached")
            try: new=store.create(config,max_nonterminal=4,owner_pid=os.getpid() if dispatch else None)
            except JobQuotaExceeded: raise HTTPException(429,"Local worker quota reached")
        if dispatch:
            frozen,digest=freeze_source(root,store.root/new["run_id"])
            config.update(source_dir=str(frozen),code_hash=digest)
            store.bind_frozen_config(new["run_id"],config)
            try:
                proc=spawn(root,store,new["run_id"])
                children[new["run_id"]]=proc
                threading.Thread(target=monitor,args=(proc,store,new["run_id"]),daemon=True).start()
            except OSError as e:
                store.state(new["run_id"],"failed",error=str(e))
                raise HTTPException(503,"Worker could not start")
        return public_job(store.get(new["run_id"]))
    @app.get("/api/runs/{run_id}")
    def run(run_id:str): return public_job(job(run_id))
    @app.get("/api/runs/{run_id}/events")
    def events(run_id:str,after:int=0):
        job(run_id); return store.events(run_id,after)
    @app.get('/api/runs/{run_id}/validity')
    def validity(run_id:str):
        job(run_id)
        path=store.root/run_id/'validity.json'
        if not path.is_file():raise HTTPException(409,'This run has no persisted validity monitor result')
        try:return json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):raise HTTPException(409,'Validity result is unavailable or incomplete')
    @app.post("/api/runs/{run_id}/cancel")
    def cancel(run_id:str): job(run_id); return public_job(store.cancel(run_id))
    @app.post('/api/runs/{run_id}/recover',status_code=202)
    def recover(run_id:str):
        job(run_id)
        from naheng.runtime.resumption import prepare_recovery
        try: new=prepare_recovery(root,store,run_id,max_nonterminal=4)
        except JobQuotaExceeded: raise HTTPException(429,'Local worker quota reached')
        except (ValueError,OSError,KeyError) as exc: raise HTTPException(409,'Checkpoint continuation unavailable: '+str(exc))
        if dispatch:
            try:
                proc=spawn(root,store,new['run_id']);children[new['run_id']]=proc
                threading.Thread(target=monitor,args=(proc,store,new['run_id']),daemon=True).start()
            except OSError as exc:
                store.state(new['run_id'],'failed',error=str(exc))
                raise HTTPException(503,'Recovery worker could not start')
        return public_job(store.get(new['run_id']))
    @app.get("/api/runs/{run_id}/snapshots")
    def snapshots(run_id:str): return result(run_id,"posterior.json")
    @app.get("/api/runs/{run_id}/forecast")
    def forecasts(run_id:str): return result(run_id,"forecast.json")
    @app.get("/api/runs/{run_id}/decisions")
    def decisions(run_id:str): return result(run_id,"decisions.json")
    @app.get("/api/runs/{run_id}/chemical-binding")
    def chemical_binding(run_id:str):
        path = completed_dir(run_id) / "chemical_binding.json"
        if not path.is_file():
            return {"status": "UNKNOWN", "reason": "This historical run has no recorded chemistry binding", "evidence_refs": []}
        return json.loads(path.read_text(encoding="utf-8"))
    @app.get("/api/runs/{run_id}/reduction-binding")
    def reduction_binding(run_id:str):
        path = completed_dir(run_id) / "reduction_binding.json"
        if not path.is_file():
            return {"status": "UNKNOWN", "reason": "This historical run has no recorded instantaneous rate binding", "evidence_refs": [],
                    "grants_future_reduction": False, "grants_strict_safety": False}
        return json.loads(path.read_text(encoding="utf-8"))
    @app.get("/api/runs/{run_id}/economics")
    def economics(run_id:str): return result(run_id,"economics.json")
    @app.get("/api/runs/{run_id}/manifest")
    def manifest(run_id:str):
        j=job(run_id); original=result(run_id,"manifest.json")
        return {**original,"display_run_id":run_id,"mode":j["config"]["mode"],"reused_from":j["config"].get("replay_source"),"independent_sample":not bool(j["config"].get("replay_source") or j['config'].get('recovery_source') or j['config'].get('task_kind')=='lifecycle-finance')}
    @app.get("/api/runs/{run_id}/trace")
    def trace(run_id:str):
        import pyarrow.parquet as pq
        return pq.read_table(completed_dir(run_id)/"sensor_trace.parquet").to_pylist()
    @app.get("/api/runs/{run_id}/model-package",response_model=RegisteredModelPackage | ModelPackage)
    def run_package(run_id:str): return result(run_id,"model_package.json")
    @app.get("/api/model-packages/{package_id}")
    def package(package_id:str):
        if package_id!="research_base-v1": raise HTTPException(404,"Unknown package")
        return json.loads((root/"model_packages/research_base/package.json").read_text(encoding="utf-8"))
    @app.get("/api/evidence/{evidence_id}")
    def evidence(evidence_id:str):
        if evidence_id not in ('foundation','core'): raise HTTPException(404,"Unknown evidence")
        from naheng.formal.active_evidence import select_foundation, select_core
        from naheng.packages.evidence_import import load_evidence
        f, reason = (select_foundation if evidence_id=='foundation' else select_core)(root)
        if f is None: return {"status":"unverified", "checked":False, "reason":reason}
        try:
            load_evidence(root, f)
        except (ValueError, OSError) as error:
            return {"status":"unverified", "checked":False, "reason":str(error)}
        return json.loads(f.read_text(encoding="utf-8"))
    @app.get("/api/runs/{run_id}/artifacts/{artifact_id}")
    def artifact(run_id:str,artifact_id:str):
        try: path=controlled_artifact(run_id,artifact_id)
        except (KeyError,ValueError): raise HTTPException(404,"Unknown controlled artifact")
        return FileResponse(path,filename=path.name)
    @app.post("/api/reports",status_code=201)
    def report(ref:RunRef):
        return run_report_reference(ref.run_id, controlled_artifact)
    @app.post("/api/replays",status_code=201)
    def replay(ref:RunRef):
        source=job(ref.run_id)
        completed_dir(ref.run_id)
        config={**source["config"],"mode":"replay","replay_source":source["config"].get("replay_source",ref.run_id)}
        new=store.create(config); store.state(new["run_id"],"running",0)
        store.state(new["run_id"],"succeeded",1)
        store.event(new["run_id"],{"type":"replay","source_run_id":ref.run_id,"independent_sample":False})
        return public_job(store.get(new["run_id"]))
    @app.post("/api/forecasts",status_code=202)
    def new_forecast(query:ForecastQuery):
        if '/' in query.snapshot_id or '\\' in query.snapshot_id or '..' in query.snapshot_id: raise HTTPException(422,'Invalid snapshot identifier')
        # Forecast must reference an existing immutable posterior, never a client-supplied truth vector.
        found=None
        for j in store.list():
            f=store.root/j["run_id"]/"snapshots"/(query.snapshot_id+".json")
            if f.is_file(): found=j['run_id']; break
        if found is None: raise HTTPException(404,"Unknown snapshot")
        with admission_lock:
            if store.count_nonterminal()+prediction_store.count_nonterminal()>=4:
                raise HTTPException(429,'Combined local run/forecast quota reached')
            try:
                identifier=create_forecast_job(root,found,query.snapshot_id,query)
                if dispatch: dispatch_forecast_job(root,identifier)
            except JobQuotaExceeded:
                raise HTTPException(429,'Local forecast quota reached')
            except (ValueError,OSError,KeyError) as error:
                raise HTTPException(409,'Forecast source/applicability rejected: '+str(error))
        return {'job_id':identifier,'state':prediction_store.get(identifier)['state'],
                'status_url':f'/api/forecast-jobs/{identifier}','result_url':f'/api/forecast-jobs/{identifier}/result'}
    def prediction_job(identifier):
        if not re.fullmatch(r'nh-[0-9a-f]{32}',identifier): raise HTTPException(404,'Unknown forecast job')
        try: return prediction_store.get(identifier)
        except KeyError: raise HTTPException(404,'Unknown forecast job')
    @app.get('/api/forecast-jobs/{identifier}')
    def forecast_job(identifier:str):
        value=prediction_job(identifier)
        return {key:value[key] for key in ('run_id','state','progress','error','cancel','updated')}
    @app.get('/api/forecast-jobs/{identifier}/events')
    def forecast_events(identifier:str,after:int=0):
        prediction_job(identifier)
        return prediction_store.events(identifier,after)
    @app.post('/api/forecast-jobs/{identifier}/cancel')
    def cancel_forecast(identifier:str):
        prediction_job(identifier)
        prediction_store.cancel(identifier)
        return forecast_job(identifier)
    @app.get('/api/forecast-jobs/{identifier}/result')
    def forecast_result(identifier:str):
        value=prediction_job(identifier)
        if value['state']!='succeeded': raise HTTPException(409,'Forecast result is incomplete: '+value['state'])
        try: return get_forecast_result(root,identifier)
        except (ValueError,OSError,KeyError) as error: raise HTTPException(409,str(error))
    @app.get("/api/contracts")
    def contracts():
        return {c.__name__:c.model_json_schema() for c in (Observation,PosteriorSnapshot,Action,ForecastQuery,Evidence,ModelPackage,RunManifest)}
    @app.post('/api/lifecycle-jobs',status_code=202)
    def lifecycle_create(request:LifecycleRequest):
        from naheng.runtime.lifecycle_jobs import spawn_lifecycle_job,monitor_lifecycle_job
        config={'task_kind':'lifecycle-finance','profile':request.profile,'mode':request.mode,
                'provenance_type':'synthetic','parameters':request.model_dump(exclude={'profile','mode'}),
                'code_hash':code_hash(root),'independent_operating_n':0}
        with admission_lock:
            if store.count_nonterminal()+prediction_store.count_nonterminal()>=4:
                raise HTTPException(429,'Combined local run/forecast quota reached')
            try: new=store.create(config,max_nonterminal=4,owner_pid=os.getpid() if dispatch else None)
            except JobQuotaExceeded: raise HTTPException(429,'Local worker quota reached')
        if dispatch:
            try:
                frozen,digest=freeze_source(root,store.root/new['run_id'])
                config.update(source_dir=str(frozen),code_hash=digest)
                store.bind_frozen_config(new['run_id'],config)
                proc=spawn_lifecycle_job(root,store,new['run_id'])
                children[new['run_id']]=proc
                threading.Thread(target=monitor_lifecycle_job,args=(proc,store,new['run_id']),daemon=True).start()
            except (OSError,ValueError) as error:
                store.state(new['run_id'],'failed',error=str(error))
                raise HTTPException(503,'Lifecycle source freezing or worker dispatch failed')
        return public_job(store.get(new['run_id']))

    @app.get('/api/runs/{run_id}/lifecycle')
    def lifecycle_result(run_id:str):
        job(run_id)
        from naheng.runtime.lifecycle_jobs import read_lifecycle_result
        try: return read_lifecycle_result(store,run_id)
        except (ValueError,OSError,KeyError) as error: raise HTTPException(409,str(error))

    @app.get('/api/runs/{run_id}/report-preview')
    def report_preview(run_id:str):
        try:
            path=controlled_artifact(run_id,'report')
        except (ValueError,OSError,KeyError) as error: raise HTTPException(409,str(error))
        return FileResponse(path,media_type='text/html',headers={'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; img-src data:",
            'X-Content-Type-Options':'nosniff'})
    def controlled_artifact(run_id,artifact_id):
        directory=completed_dir(run_id,allow_lifecycle_partial=True)
        try:
            path=safe_artifact(directory,artifact_id)
            if not path.is_file(): raise ValueError('Controlled artifact unavailable')
            if job(run_id)['config'].get('task_kind')=='lifecycle-finance':
                from naheng.runtime.lifecycle_jobs import read_lifecycle_result
                read_lifecycle_result(store,run_id)
                if sha256_file(path)!=result(run_id,'manifest.json')['artifact_sha256'][artifact_id]:
                    raise ValueError('Lifecycle artifact checksum changed')
        except (OSError,ValueError) as error: raise HTTPException(409,str(error))
        return path
    frontend=root/"frontend/dist"
    if frontend.is_dir(): app.mount("/",StaticFiles(directory=frontend,html=True),name="workbench")
    return app
