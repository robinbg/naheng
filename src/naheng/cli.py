from __future__ import annotations
import argparse,json,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    p=argparse.ArgumentParser(prog="naheng")
    sub=p.add_subparsers(dest="cmd",required=True)
    doctor=sub.add_parser("doctor"); doctor.add_argument("--out",type=Path,default=Path("artifacts/environment.json"))
    verify=sub.add_parser("verify"); verify.add_argument("--profile",choices=["smoke","application","formal","release"],default="smoke"); verify.add_argument("--out",type=Path)
    demo=sub.add_parser("demo"); demo.add_argument("--scenario",default="acceptance_loop"); demo.add_argument("--out",type=Path,default=Path("artifacts/demo")); demo.add_argument("--ambient-K",type=float); demo.add_argument("--price",type=float)
    formal=sub.add_parser("formal"); fsub=formal.add_subparsers(dest="formal_cmd",required=True); check=fsub.add_parser("check"); check.add_argument("--suite",default="foundation"); check.add_argument("--out",type=Path)
    simulate=sub.add_parser("simulate"); simulate.add_argument("--model",choices=["reference_sodium"],required=True); simulate.add_argument("--profile",choices=["probe"],default="probe"); simulate.add_argument("--out",type=Path,default=Path("artifacts/reference_smoke")); simulate.add_argument("--duration-s",type=float,default=10); simulate.add_argument("--c-rate",type=float,default=.1)
    serve=sub.add_parser("serve"); serve.add_argument("--host",default="127.0.0.1"); serve.add_argument("--port",type=int,default=8000)
    recover=sub.add_parser('recover');recover.add_argument('--run-id',required=True);recover.add_argument('--out',type=Path,default=Path('artifacts/recovery'))
    data=sub.add_parser('data'); dsub=data.add_subparsers(dest='data_cmd',required=True)
    freeze=dsub.add_parser('freeze-members'); freeze.add_argument('--catalog',required=True); freeze.add_argument('--catalog-sha256',required=True); freeze.add_argument('--policy',required=True); freeze.add_argument('--policy-sha256',required=True); freeze.add_argument('--out',required=True)
    reopen=dsub.add_parser('verify-members'); reopen.add_argument('--frozen',required=True); reopen.add_argument('--frozen-sha256',required=True)
    diagnose=sub.add_parser('diagnose'); diagnose.add_argument('--input',type=Path,required=True); diagnose.add_argument('--out',type=Path,required=True)
    calibrate=sub.add_parser('calibrate'); calibrate.add_argument('--input',type=Path,required=True); calibrate.add_argument('--out',type=Path,required=True)
    consume=sub.add_parser('consume-calibration',help='Explicit synthetic simulation using one selected calibration candidate')
    consume.add_argument('--calibration-dir',type=Path,required=True); consume.add_argument('--out',type=Path,required=True)
    consume.add_argument('--horizon-s',type=float,required=True); consume.add_argument('--current-limit-A',type=float,required=True)
    consume.add_argument('--ambient-K',type=float,required=True); consume.add_argument('--sell-price-per-kWh',type=float,required=True)
    consume.add_argument('--seed',type=int,default=20261014)
    scenario=sub.add_parser('scenario-calibration',help='Two bounded synthetic scenario actions with sensor updates and replanning')
    scenario.add_argument('--calibration-dir',type=Path,required=True); scenario.add_argument('--out',type=Path,required=True)
    joint_scenario=sub.add_parser('joint-scenario-calibration',help='Explicit finite-support joint Gaussian observer with correlated biased synthetic sensors')
    joint_scenario.add_argument('--calibration-dir',type=Path,required=True); joint_scenario.add_argument('--out',type=Path,required=True)
    frontier=sub.add_parser('baseline-frontier',help='Register, tune fixed baselines on training executions, freeze and evaluate paired conditional synthetic trajectories')
    frontier.add_argument('--input',type=Path,required=True); frontier.add_argument('--calibration-dir',type=Path,required=True)
    frontier.add_argument('--out',type=Path,required=True)
    experiment=sub.add_parser('experiment',help='Registered, bounded real public-data experiments')
    esub=experiment.add_subparsers(dest='experiment_cmd',required=True)
    experiment_run=esub.add_parser('run')
    experiment_run.add_argument('--suite',choices=['public-data','lifecycle-finance'],required=True)
    experiment_run.add_argument('--profile',choices=['pilot'],required=True)
    experiment_run.add_argument('--manifest',type=Path)
    experiment_run.add_argument('--out',type=Path)
    prereg=esub.add_parser('preregister',help='Freeze a protocol and record any missing scientific prerequisites')
    prereg.add_argument('--config',type=Path,required=True);prereg.add_argument('--out',type=Path)
    optimize=sub.add_parser('optimize',help='Bounded nine-coordinate synthetic strategy training')
    optimize.add_argument('--profile',choices=['pilot'],required=True);optimize.add_argument('--out',type=Path)
    optimize.add_argument('--resume',action='store_true');optimize.add_argument('--calibration-dir',type=Path)
    discover=sub.add_parser('discover',help='Learn candidate selection from actual finite-model feedback with separate baselines')
    discover.add_argument('--profile',choices=['pilot'],required=True)
    discover.add_argument('--out',type=Path,default=Path('artifacts/discovery/pilot'))
    args=p.parse_args(argv)
    try:
        if args.cmd=='optimize':
            from .learning.pilot import run_pilot
            result=run_pilot(ROOT,args.out,profile=args.profile,resume=args.resume,calibration_dir=args.calibration_dir);code=result['exit_code']
        elif args.cmd=='discover':
            from .discovery.pilot import discover as run_discovery
            result=run_discovery(ROOT,args.out);code=result['exit_code']
        elif args.cmd=="doctor":
            from .runtime.environment import doctor
            result=doctor(args.out); code=result["exit_code"]
        elif args.cmd=='diagnose':
            from .estimation.diagnostic_session import run_diagnostics
            result=run_diagnostics(ROOT,args.input,args.out); code=result['exit_code']
        elif args.cmd=='calibrate':
            from .estimation.calibration_session import run_calibration
            result=run_calibration(ROOT,args.input,args.out); code=result['exit_code']
        elif args.cmd=='consume-calibration':
            from .runtime.calibration_consumer import run_consumer
            result=run_consumer(ROOT,args.calibration_dir,args.out,horizon_s=args.horizon_s,
                current_limit_A=args.current_limit_A,ambient_K=args.ambient_K,
                sell_price_per_kWh=args.sell_price_per_kWh,seed=args.seed); code=result['exit_code']
        elif args.cmd=='scenario-calibration':
            from .runtime.scenario_calibration import run_scenario
            result=run_scenario(ROOT,args.calibration_dir,args.out); code=result['exit_code']
        elif args.cmd=='joint-scenario-calibration':
            from .runtime.joint_scenario_calibration import run_joint_scenario
            result=run_joint_scenario(ROOT,args.calibration_dir,args.out); code=result['exit_code']
        elif args.cmd=='baseline-frontier':
            from .runtime.baseline_frontier import run_frontier
            result=run_frontier(ROOT,args.calibration_dir,args.input,args.out); code=result['exit_code']
        elif args.cmd=='experiment':
            if args.experiment_cmd=='preregister':
                from .experiments.preregistration import preregister
                result=preregister(ROOT,args.config,args.out)
            elif args.suite == 'public-data':
                from .runtime.public_capacity_session import run_public_data_phases
                result=run_public_data_phases(ROOT,args.manifest,args.out)
            else:
                if args.manifest is not None: raise ValueError('Lifecycle finance uses its registered source configuration')
                from .runtime.lifecycle_finance_session import run_lifecycle_finance
                result=run_lifecycle_finance(ROOT,args.out)
            code=result['exit_code']
        elif args.cmd=='data':
            from .data.member_partitions import freeze_members,verify_members
            if args.data_cmd=='freeze-members':
                result=freeze_members(ROOT,{'path':args.catalog,'sha256':args.catalog_sha256},
                                      {'path':args.policy,'sha256':args.policy_sha256},args.out)
            else:
                result=verify_members(ROOT,{'path':args.frozen,'sha256':args.frozen_sha256})
            code=result['exit_code']
        elif args.cmd=="verify":
            from .runtime.verification import verify
            result=verify(ROOT,args.profile,args.out); code=result["exit_code"]
        elif args.cmd=="formal":
            from .formal.checker import check
            result=check(suite=args.suite,out=args.out or ROOT/"artifacts/formal"/args.suite)
            code=result["exit_code"]
        elif args.cmd=="demo":
            import yaml
            from .runtime.jobs import JobStore
            from .runtime.artifacts import atomic_json,code_hash
            from .runtime.freezing import freeze_source
            from .runtime.dispatch import spawn,monitor
            config_path=ROOT/"configs/scenarios"/(args.scenario+".yaml")
            if not config_path.is_file(): raise ValueError("Unknown scenario")
            config=yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if args.ambient_K is not None: config["ambient_K"]=args.ambient_K
            if args.price is not None: config["sell_price_per_kWh"]=args.price
            config["code_hash"]=code_hash(ROOT)
            store=JobStore(ROOT/"artifacts/runs"); job=store.create(config,owner_pid=os.getpid())
            frozen,digest=freeze_source(ROOT,store.root/job["run_id"])
            config.update(source_dir=str(frozen),code_hash=digest)
            store.bind_frozen_config(job["run_id"],config)
            proc=spawn(ROOT,store,job["run_id"]); monitor(proc,store,job["run_id"])
            if store.get(job["run_id"])["state"]!="succeeded": raise ValueError(store.get(job["run_id"])["error"] or "Incomplete run")
            result={"run_id":job["run_id"],"state":store.get(job["run_id"])["state"],"artifact_dir":str(store.root/job["run_id"]),"report":str(store.root/job["run_id"]/"report.html"),"scope":"synthetic numerical loop; proof and public data gates separate"}
            args.out.mkdir(parents=True,exist_ok=True); atomic_json(args.out/"latest.json",result); code=0
        elif args.cmd=='recover':
            from .runtime.jobs import JobStore
            from .runtime.resumption import prepare_recovery
            from .runtime.dispatch import spawn,monitor
            from .runtime.artifacts import atomic_json
            store=JobStore(ROOT/'artifacts/runs')
            job=prepare_recovery(ROOT,store,args.run_id)
            proc=spawn(ROOT,store,job['run_id']);monitor(proc,store,job['run_id'])
            final=store.get(job['run_id'])
            if final['state']!='succeeded': raise ValueError(final['error'] or 'Incomplete recovery')
            result={'run_id':job['run_id'],'recovered_from':args.run_id,'independent_sample':False,
                'state':final['state'],'report':str(store.root/job['run_id']/'report.html')}
            args.out.mkdir(parents=True,exist_ok=True);atomic_json(args.out/'latest.json',result);code=0
        elif args.cmd=="simulate":
            from .models.reference_pybamm import main as reference_main
            return reference_main(["--out",str(args.out),"--duration-s",str(args.duration_s),"--c-rate",str(args.c_rate)])
        elif args.cmd=="serve":
            if args.host not in ("127.0.0.1","localhost","::1"): raise ValueError("Public binding requires separate explicit authorization/configuration")
            import uvicorn
            from .api.app import create_app
            uvicorn.run(create_app(ROOT),host=args.host,port=args.port)
            return 0
        print(json.dumps(result,ensure_ascii=False,indent=2,default=str)); return code
    except (ValueError,OSError,ImportError) as e:
        print(json.dumps({"error":type(e).__name__,"reason":str(e),"exit_code":2 if isinstance(e,(ImportError,OSError)) else 1},ensure_ascii=False))
        return 2 if isinstance(e,(ImportError,OSError)) else 1
if __name__=="__main__": raise SystemExit(main())
