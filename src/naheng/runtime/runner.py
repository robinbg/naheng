from __future__ import annotations
import dataclasses, html, json, time, csv, os
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from naheng.domain.contracts import Observation, ForecastQuery, RunManifest
from naheng.models.site_model import SiteModel
from naheng.estimation.particle_filter import ParticleFilter
from naheng.lifecycle.forecast import forecast
from naheng.control.rules import propose
from naheng.economics.ledger import EnergyLedger
from naheng.risk.admission import check
from naheng.packages.registry import ModelRegistry
from .jobs import JobStore
from .artifacts import atomic_json, code_hash, sha256_file
from .snapshots import save_snapshot
from .recovery import config_digest,save_recovery_checkpoint,load_recovery_checkpoint,restore_sensor_rng,restore_ledger

def write_rows(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    if rows: pq.write_table(pa.Table.from_pylist(rows),path,version="2.4",data_page_version="1.0",write_statistics=False)
    else: pq.write_table(pa.table({"empty":pa.array([],type=pa.string())}),path)
    if rows:
        with path.with_suffix('.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows: writer.writerow({key:json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else value for key,value in row.items()})

def execute(project: Path,store: JobStore,run_id: str):
    job=store.get(run_id)
    if job["state"]=="cancelled": return
    config=job["config"]; dest=store.root/run_id; dest.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    if not store.try_start(run_id,owner_pid=os.getpid()): return
    sensor=[]; posterior=[]; actions=[]; decisions=[]; truth=[]; mpc_plans=[]
    execution_pending=False
    validity_gate=None
    try:
        from .validity import validate_profiles,voltage_bias,RuntimeValidityGate,ValidityStop
        validity_enabled=validate_profiles(config)
        if job["reused_from"]:
            raise ValueError("Cache reuse is recorded but must be replayed explicitly; independent simulation is not credited")
        source_root=Path(config.get("source_dir",str(project)))
        from .execution_environment import capture_environment,assert_environment_unchanged
        environment_record=capture_environment(source_root)
        atomic_json(dest/"execution_environment.json",environment_record)
        model=SiteModel()
        state=model.initial_state(soc=config["initial_soc"],temperature_K=config["ambient_K"])
        rng=np.random.default_rng(config["seed"]+1)
        pf=ParticleFilter(run_id,model,seed=config["seed"]+2,particles=config["filter_particles"])
        ledger=EnergyLedger(run_id)
        package=json.loads((Path(config.get("source_dir",str(project)))/"model_packages/research_base/package.json").read_text(encoding="utf-8"))
        package['parameter_revision']=pf.parameter_revision
        package['parameters']=dataclasses.asdict(model.params)
        registry=ModelRegistry(source_root); registered=registry.register(package)
        package=registry.packages[registered['package_id']]
        atomic_json(dest/'model_package.json',package)
        from naheng.formal.active_evidence import select_foundation,select_reduction_residual
        from naheng.formal.runtime_binding import load_runtime_binding,revalidate_runtime_binding
        from naheng.formal.inventory_check import check_sodium_interval
        evidence_path,selection_reason=select_foundation(project)
        chemical_binding=load_runtime_binding(project,source_root,package,model.params,evidence_path)
        chemical_binding.record['manifest_selection']=selection_reason
        from naheng.formal.reduction_binding import ReductionBinding,load_reduction_binding,revalidate_reduction_binding,evaluate_posterior_rate
        rate_manifest,rate_selection=select_reduction_residual(project)
        reduction_binding=load_reduction_binding(project,source_root,package,model,rate_manifest)
        reduction_binding=ReductionBinding({**reduction_binding.record,'manifest_selection':rate_selection})
        if code_hash(source_root)!=config['code_hash']:
            raise ValueError('Execution source differs from persisted Run code identity')
        atomic_json(dest/'chemical_binding.json',chemical_binding.record)
        atomic_json(dest/'reduction_binding.json',reduction_binding.record)
        def observation(t,current):
            measured=model.observe(state,current)
            return Observation(run_id=run_id,timestamp_s=t,current_A=current,
                voltage_V=float(measured["voltage_V"]+rng.normal(0,.01)+(voltage_bias(config,t) if validity_enabled else 0.)),
                temperature_K=float(measured["temperature_K"]+rng.normal(0,.2)))
        resume_step=0
        if config.get('recovery_source'):
            loaded=load_recovery_checkpoint(store,config['recovery_source'],
                expected_code_hash=config['code_hash'],expected_lock_hash=environment_record['dependency_lock_hash'],
                expected_input_hash=config_digest(config),new_run_id=run_id,
                checkpoint=config['recovery_lineage']['source_checkpoint'])
            resume_step=loaded['next_step']
            if abs(loaded['logical_time_s']-min(resume_step*config['step_s'],config['duration_s']))>1e-7:
                raise ValueError('Partial model-domain interval cannot be silently skipped during recovery')
            state=np.asarray(loaded['state'],dtype=float)
            rng=restore_sensor_rng(loaded['sensor_rng_state'])
            # The estimator restores only its own particles and random state.
            pf=ParticleFilter.from_checkpoint(run_id,model,loaded['pf_checkpoint'])
            sensor=loaded['sensor'];posterior=loaded['posterior'];actions=loaded['actions']
            decisions=loaded['decisions'];truth=loaded['truth']
            restore_ledger(ledger,actions,loaded['cashflows'])
            snapshot=pf.snapshot
            for row in posterior:
                from naheng.domain.contracts import PosteriorSnapshot
                save_snapshot(dest,PosteriorSnapshot.model_validate(row))
            from .resumption import public_lineage
            atomic_json(dest/'recovery_lineage.json',public_lineage(loaded['lineage']))
        else:
            obs=observation(0,0); sensor.append(obs.model_dump())
            snapshot=pf.update(obs,duration_s=0)
            save_snapshot(dest,snapshot); posterior.append(snapshot.model_dump(mode="json"))
        if validity_enabled:
            if config.get('recovery_source'):
                raise ValueError('Monitored checkpoint continuation requires restored validity history; start an explicit new run')
            validity_gate=RuntimeValidityGate(project,source_root,store,run_id,config,model,package,pf,snapshot)
            validity_gate.check(snapshot,config['ambient_K'],'initial_sensor',residuals=False)
        def checkpoint(step,logical_time):
            save_recovery_checkpoint(store,run_id,code_hash=config['code_hash'],
                lock_hash=environment_record['dependency_lock_hash'],input_hash=config_digest(config),
                execution_config_hash=job['input_hash'],step=step,logical_time_s=logical_time,
                simulator_state=state,sensor_rng=rng,pf=pf,sensor=sensor,posterior=posterior,
                actions=actions,cashflows=ledger.entries,decisions=decisions,truth=truth,
                lineage=loaded['lineage'] if config.get('recovery_source') else None)
        checkpoint(resume_step,snapshot.obs_until_s)
        # A fully executed parent may resume only final publication; inherited
        # actual flows still need the same persisted public ledger artifact.
        atomic_json(dest/'executed_ledger.json',{'entries':ledger.entries,'summary':ledger.summary(),
            'forecast_energy_booked':False,'terminal_value_booked':False})
        n=int(np.ceil(config["duration_s"]/config["step_s"]))
        for step in range(resume_step,n):
            if store.get(run_id)["cancel"]:
                store.state(run_id,"cancelled",step/n)
                atomic_json(dest/"partial.json",{"complete":False,"steps":step})
                return
            if time.monotonic()-started>120: raise TimeoutError("120 second simulation budget exhausted")
            t=step*config["step_s"]; dt=min(config["step_s"],config["duration_s"]-t)
            chemical_binding=revalidate_runtime_binding(project,source_root,chemical_binding,package,model.params)
            reduction_binding=revalidate_reduction_binding(project,source_root,reduction_binding,package,model)
            if code_hash(source_root)!=config['code_hash']:
                raise ValueError('Execution source changed since binding')
            atomic_json(dest/'chemical_binding.json',chemical_binding.record)
            atomic_json(dest/'reduction_binding.json',reduction_binding.record)
            stage_ambient=config['ambient_K']; stage_buy=config['buy_price_per_kWh']; stage_sell=config['sell_price_per_kWh']
            if validity_gate:validity_gate.check(snapshot,stage_ambient,'before_planning')
            policy=config.get('policy_id','rules-v1')
            if policy=='mpc-v1':
                from naheng.control.mpc import plan,MPCStage,MPCParameters
                if config.get('recovery_source'):
                    prior=store.root/config['recovery_source']/'mpc_plans.json'
                    if not mpc_plans:
                        mpc_plans=json.loads(prior.read_text(encoding='utf-8'))[:resume_step]
                horizon=config.get('mpc_horizon_steps',3)
                schedule=config['mpc_schedule']
                window=schedule[step:step+horizon]
                if len(window)!=horizon:
                    raise ValueError('Declared MPC schedule does not cover the future horizon')
                stages=[MPCStage(**row) for row in window]
                if abs(stages[0].duration_s-dt)>1e-8:
                    raise ValueError('MPC first-stage duration differs from the executable interval')
                settings=dict(config.get('mpc_parameters',{}))
                settings['wall_budget_s']=min(settings.get('wall_budget_s',20),max(.001,120-(time.monotonic()-started)))
                mpc_parameters=MPCParameters(**settings)
                response=plan(snapshot,model,package,stages,start_s=t,parameters=mpc_parameters,runtime_binding=chemical_binding)
                mpc_plans.append(response.to_dict())
                atomic_json(dest/'mpc_plans.json',mpc_plans)
                if response.status!='feasible' or response.action is None:
                    if validity_gate:validity_gate.no_feasible_action(snapshot,'No admitted MPC first move: '+response.status+': '+response.reason)
                    raise ValueError('No admitted MPC first move: '+response.status+': '+response.reason)
                action=response.action
                stage_ambient=stages[0].ambient_K; stage_buy=stages[0].buy_price_per_kWh; stage_sell=stages[0].sell_price_per_kWh
            elif policy=='rules-v1':
                action=propose(snapshot,stage_sell,start_s=t,duration_s=dt)
            else:
                raise ValueError('Unsupported policy identity')
            rate_evaluation=evaluate_posterior_rate(snapshot,action,model,reduction_binding,
                upper=config.get('stored_sodium_rate_upper_mol_per_s'))
            decision=check(snapshot,action,package,stage_ambient,mode="empirical",runtime_binding=chemical_binding,
                rate_evaluation=rate_evaluation)
            decisions.append({"action_id":action.action_id,"snapshot_id":snapshot.snapshot_id,**decision})
            if decision["decision"]!="accept":
                if validity_gate:validity_gate.no_feasible_action(snapshot,'No admitted synthetic action: '+decision['reason'])
                ledger.append(action,execution_id=action.action_id,energy_J=0,executed=False,reason=decision["reason"])
                atomic_json(dest/'decisions.json',decisions)
                atomic_json(dest/'unexecuted_cashflows.json',{'complete':False,'entries':ledger.entries,
                    'summary':ledger.summary(),'reason':'Admission stopped the requested synthetic action'})
                raise ValueError("No admitted synthetic action: "+decision["reason"])
            initial_state=state.copy()
            guarded=None
            if validity_gate:
                validity_gate.check(snapshot,stage_ambient,'before_execution',residuals=False)
                execution_pending=True
            # Persist intent before launching numerical work. A killed worker
            # cannot run its except handler or attest a completed interval.
            store.event(run_id,{'type':'execution_started','step':step,
                'action_id':action.action_id,'snapshot_id':action.snapshot_id})
            if policy=='mpc-v1':
                from naheng.control.execution import integrate_guarded_action,GuardedExecutionRejected
                try:
                    guarded=integrate_guarded_action(model,state,action,package,mpc_parameters,stage_ambient)
                except GuardedExecutionRejected as error:
                    store.event(run_id,{'type':'execution_not_started','step':step,
                        'action_id':action.action_id,'solver_calls':0,'executed':False})
                    atomic_json(store.root/'evaluator'/run_id/f'refusal-{step}.json',error.receipt)
                    raise
                result=guarded.result
            else:
                result=model.integrate(state,action.current_A,dt,ambient_K=stage_ambient,thermal_W=action.thermal_W)
            execution_pending=True
            # Only actual executed intervals enter cashflows.
            executed_dt=float(getattr(result,"elapsed_s",dt))
            state=result.state
            ledger.append(action,execution_id=action.action_id,energy_J=result.energy_J,
                thermal_energy_J=float(getattr(result,"thermal_management_energy_J",0)) if validity_gate else max(0,float(getattr(result,"thermal_management_energy_J",0))),
                buy_price_per_kWh=stage_buy,sell_price_per_kWh=stage_sell,duration_s=executed_dt)
            actions.append({**action.model_dump(),"executed_duration_s":executed_dt,"energy_J":result.energy_J,"inventory_residual_mol":result.inventory_residual_mol})
            truth.append({"timestamp_s":t+executed_dt,"state":state.tolist(),"inventory_residual_mol":result.inventory_residual_mol,"events":result.events})
            atomic_json(dest/'executed_ledger.json',{'entries':ledger.entries,'summary':ledger.summary(),
                'forecast_energy_booked':False,'terminal_value_booked':False})
            if validity_gate:validity_gate.record_execution(action,result,ledger)
            atomic_json(store.root/'evaluator'/run_id/f'execution-{step}.json',{
                'elapsed_s':executed_dt,'energy_J':result.energy_J,
                'thermal_management_energy_J':result.thermal_management_energy_J,
                'times_s':result.times_s.tolist(),'states':result.states.tolist(),
                'voltages_V':result.voltages_V.tolist(),'events':result.events,'solver':result.solver})
            if guarded is not None:
                atomic_json(store.root/'evaluator'/run_id/f'guard-{step}.json',guarded.receipt)
            inventory_check=check_sodium_interval(model,initial_state,result,action.current_A,stage_ambient,action.thermal_W,
                                                  evidence_refs=decision['evidence_refs'])
            decisions[-1]['interval_inventory_check']=inventory_check
            if inventory_check['status']!='PASS':
                atomic_json(dest/'decisions.json',decisions)
                raise ValueError('Executed interval failed sodium inventory consistency check')
            if guarded is not None:
                from .execution_receipts import stop_status
                stopping=stop_status(guarded.receipt,result,dt)
                if stopping:
                    store.event(run_id,{'type':'execution_stop','status':stopping,
                        'events':guarded.receipt['native_events_with_scope']})
                    raise ValueError('Actual MPC execution stopped: '+stopping)
            obs=observation(t+executed_dt,action.current_A); sensor.append(obs.model_dump())
            snapshot=pf.update(obs,duration_s=executed_dt,ambient_K=stage_ambient,thermal_W=action.thermal_W)
            save_snapshot(dest,snapshot); posterior.append(snapshot.model_dump(mode="json"))
            checkpoint(step+1,obs.timestamp_s)
            execution_pending=False
            if validity_gate:validity_gate.check(snapshot,stage_ambient,'after_assimilation')
            store.state(run_id,"running",.8*(step+1)/n)
            if result.events:
                store.event(run_id,{"type":"model_event","events":result.events})
                if executed_dt < dt-1e-6: raise ValueError("Continuous model domain event stopped requested simulation")
        query=ForecastQuery(snapshot_id=snapshot.snapshot_id,future_policy_id="fixed-current-v1",
            environment_id="ambient-"+str(config["ambient_K"]),horizon_s=config["forecast_horizon_s"],
            endpoint_protocol=config["endpoint_protocol"],sample_budget=config["forecast_paths"],
            current_A=config["future_current_A"],ambient_K=config["ambient_K"],seed=config["seed"]+4)
        predictions=forecast(snapshot,query,model,cancel_check=lambda: bool(store.get(run_id)["cancel"]))
        atomic_json(dest/"forecast.json",predictions)
        atomic_json(dest/"decisions.json",decisions)
        atomic_json(dest/"economics.json",ledger.summary())
        atomic_json(dest/"posterior.json",posterior)
        write_rows(dest/"sensor_trace.parquet",sensor)
        write_rows(dest/"actions.parquet",actions)
        write_rows(dest/"cashflows.parquet",ledger.entries)
        # Physically separate reference states; no API serves this directory.
        atomic_json(store.root/"evaluator"/run_id/"reference_trace.json",truth)
        atomic_json(dest/"query.json",query.model_dump(mode="json"))
        assert_environment_unchanged(source_root,environment_record)
        artifacts={"execution_environment":"execution_environment.json","model_package":"model_package.json","sensor_trace":"sensor_trace.parquet","sensor_csv":"sensor_trace.csv","actions_csv":"actions.csv","cashflows_csv":"cashflows.csv","posterior":"posterior.json","actions":"actions.parquet","cashflows":"cashflows.parquet","forecast":"forecast.json","decisions":"decisions.json","economics":"economics.json","query":"query.json","report":"report.html","events":"events.json"}
        artifacts['chemical_binding']='chemical_binding.json'
        artifacts['reduction_binding']='reduction_binding.json'
        artifacts['executed_ledger']='executed_ledger.json'
        if config.get('policy_id')=='mpc-v1': artifacts['mpc_plans']='mpc_plans.json'
        if validity_gate:artifacts['validity']='validity.json'
        if config.get('recovery_source'): artifacts['recovery_lineage']='recovery_lineage.json'
        manifest=RunManifest(run_id=run_id,mode=config["mode"],provenance_type="synthetic",
            model_id="two_site_current_adapter_v1",parameter_revision=pf.parameter_revision,policy_id=config.get('policy_id','rules-v1'),
            data_id="synthetic-two-site-v1",code_hash=config["code_hash"],
            dependency_lock_hash=environment_record["dependency_lock_hash"],seed_bundle={"scenario":config["seed"],"observation":config["seed"]+1,"filter":config["seed"]+2,"optimization":config["seed"]+3,"forecast":config["seed"]+4},
            artifact_index=artifacts,complete=True,recovered_from=config.get('recovery_source'),
            recovery_step=resume_step if config.get('recovery_source') else None,
            independent_sample=not bool(config.get('recovery_source')))
        report="<html><meta charset='utf-8'><title>钠衡运行报告</title><h1>钠衡：合成研究运行</h1><p>RunID: "+html.escape(run_id)+"</p><p>非真实电芯寿命、事故概率或收益验证。正式证明按证据索引单列。</p><h2>状态与条件预测</h2><pre>"+html.escape(json.dumps({"snapshot":snapshot.model_dump(mode="json"),"forecast":predictions,"economics":ledger.summary()},ensure_ascii=False,indent=2))+"</pre></html>"
        chemistry_summary={key:chemical_binding.record[key] for key in ('status','reason','scope','evidence_refs','withdrawn')}
        chemistry_summary['numerical_inventory_checks']=[row.get('interval_inventory_check') for row in decisions
                                                          if row.get('interval_inventory_check') is not None]
        chemistry_summary['instantaneous_rate_binding']={key:reduction_binding.record[key] for key in ('status','reason','scope','evidence_refs','grants_future_reduction','grants_strict_safety')}
        chemistry_summary['instantaneous_rate_diagnostics']=[row.get('rate_diagnostics') for row in decisions]
        report=report.replace('</html>','<h2>化学收支与证据适用性</h2><p>数值库存容差为经验检查，未建立全域误差界或现实电芯安全保证。</p><pre>'+
                              html.escape(json.dumps(chemistry_summary,ensure_ascii=False,indent=2))+'</pre></html>')
        if mpc_plans:
            report=report.replace('</html>','<h2>滚动MPC执行</h2><p>每轮只执行首步；其余为预测，不能作为已执行现金流。名义优化和后验场景复验没有严格风险证书。</p><pre>'+
                html.escape(json.dumps(mpc_plans,ensure_ascii=False,indent=2))+'</pre></html>')
        if validity_gate:
            report=report.replace('</html>','<h2>失配监测与实际服务</h2><p>工程残差阈值，无已校准误报概率；新理论不会在本运行中自动采纳。</p><pre>'+
                html.escape((dest/'validity.json').read_text(encoding='utf-8'))+'</pre></html>')
        if config.get('recovery_source'):
            report=report.replace('<h2>状态与条件预测</h2>',
                '<p>检查点续算自 '+html.escape(config['recovery_source'])+
                '；继承已执行区间 '+str(resume_step)+'，新增已执行区间 '+str(n-resume_step)+
                '。现金流包含继承账目，各区间只记一次；本运行不增加独立实验样本。</p><h2>状态与条件预测</h2>')
        from .publication import publish_complete
        publish_complete(store,run_id,dest,manifest,report,artifacts,step=n,snapshot_id=snapshot.snapshot_id)
    except Exception as exc:
        from .publication import record_incomplete
        if validity_gate:
            if not isinstance(exc,ValidityStop):validity_gate.failure(exc,execution_pending=execution_pending)
            try:record_incomplete(store,run_id,dest,exc,steps=len(actions),sensor=sensor,execution_pending=execution_pending)
            except Exception:pass
        else:
            record_incomplete(store,run_id,dest,exc,steps=len(actions),sensor=sensor,execution_pending=execution_pending)
        current=store.get(run_id)
        if current["state"] in {"cancelled","interrupted","failed"}: return
        if current["cancel"]:
            store.state(run_id,"cancelled",error="Cancelled during a numerical stage; partial result is incomplete")
            return
        if validity_gate and isinstance(exc,ValidityStop):
            store.state(run_id,'interrupted',error=str(exc));return
        store.state(run_id,"failed",error=type(exc).__name__+": "+str(exc))
        raise
