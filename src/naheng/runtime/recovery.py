"""Content-addressed private checkpoints and explicit new-run recovery lineage.

Simulator state lives only in evaluator storage. ParticleFilter receives only
its own particle/RNG checkpoint, never simulator state or reference history.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib,json,os,uuid
from pathlib import Path
import numpy as np
from naheng.estimation.particle_filter import rekey_snapshot
from naheng.domain.contracts import Action

MAXIMUM_BUNDLE_BYTES=100*1024*1024
_EXECUTION_METADATA={"source_dir","code_hash","recovery_source","recovery_lineage"}


def _bytes(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")


def config_digest(config:dict)->str:
    """Hash scientific inputs; separately bind source and lineage metadata."""
    return hashlib.sha256(_bytes({k:v for k,v in config.items() if k not in _EXECUTION_METADATA})).hexdigest()


def _digest(value,name):
    if not isinstance(value,str) or len(value)!=64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid "+name+" hash")
    return value


def _io_path(path:Path):
    """Keep long Windows content-addressed paths usable without global settings."""
    path=Path(path).absolute()
    if os.name=="nt" and not str(path).startswith("\\\\?\\"):
        text=str(path)
        return Path("\\\\?\\UNC\\"+text[2:] if text.startswith("\\\\") else "\\\\?\\"+text)
    return path


def _immutable_json(path:Path,data:bytes):
    _io_path(path.parent).mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(".tmp-"+uuid.uuid4().hex[:16])
    try:
        with _io_path(temporary).open("xb") as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        try: os.link(_io_path(temporary),_io_path(path))
        except FileExistsError:
            with _io_path(path).open("rb") as stream: existing=stream.read(len(data)+1)
            if existing!=data: raise ValueError("Immutable checkpoint content conflict")
    finally:
        if _io_path(temporary).exists(): _io_path(temporary).unlink()


def save_recovery_checkpoint(store,run_id:str,*,code_hash:str,lock_hash:str,input_hash:str,
        step:int,logical_time_s:float,simulator_state,sensor_rng,pf,sensor:list,
        posterior:list,actions:list,cashflows:list,decisions:list,truth:list,
        execution_config_hash:str|None=None,lineage:dict|None=None)->dict:
    """Commit a complete private boundary bundle, then its public pointer."""
    if not isinstance(step,int) or isinstance(step,bool) or step<0 or not np.isfinite(logical_time_s) or logical_time_s<0:
        raise ValueError("Invalid recovery boundary")
    if pf.run_id!=run_id or pf.snapshot is None or pf.snapshot.obs_until_s!=logical_time_s:
        raise ValueError("Recovery boundary must follow a completed assimilation")
    state=np.asarray(simulator_state,dtype=float)
    if state.shape!=(len(pf.model.state_names),) or not np.isfinite(state).all():
        raise ValueError("Invalid private simulator checkpoint state")
    if len(actions)!=step or len(cashflows)!=step or len(decisions)!=step or len(truth)!=step:
        raise ValueError("Checkpoint must include every completed executed interval")
    if len(sensor)!=step+1 or len(posterior)!=step+1:
        raise ValueError("Checkpoint sensor and posterior histories are incomplete")
    if posterior[-1]["snapshot_id"]!=pf.snapshot.snapshot_id or sensor[-1]["timestamp_s"]!=logical_time_s:
        raise ValueError("Checkpoint history and estimator boundary disagree")
    payload={"schema_version":1,"run_id":run_id,"code_hash":_digest(code_hash,"source"),
        "dependency_lock_hash":_digest(lock_hash,"dependency lock"),"input_hash":_digest(input_hash,"input"),
        "execution_config_hash":execution_config_hash,"step":step,"next_step":step,
        "logical_time_s":float(logical_time_s),"state":state.tolist(),
        "sensor_rng_state":deepcopy(sensor_rng.bit_generator.state),"pf_checkpoint":pf.export_checkpoint(),
        "sensor":deepcopy(sensor),"posterior":deepcopy(posterior),"actions":deepcopy(actions),
        "cashflows":deepcopy(cashflows),"decisions":deepcopy(decisions),"truth":deepcopy(truth),
        "lineage":deepcopy(lineage)}
    data=_bytes(payload)
    if len(data)>MAXIMUM_BUNDLE_BYTES: raise ValueError("Recovery bundle exceeds byte limit")
    digest=hashlib.sha256(data).hexdigest()
    relative=Path("evaluator")/run_id/f"recovery-{step}-{digest}.json"
    _immutable_json(store.root/relative,data)
    checkpoint={"schema_version":1,"complete":False,"recoverable":True,"step":step,"next_step":step,
        "logical_time_s":float(logical_time_s),"snapshot_id":pf.snapshot.snapshot_id,
        "code_hash":code_hash,"dependency_lock_hash":lock_hash,"input_hash":input_hash,
        "execution_config_hash":execution_config_hash,
        "private_recovery":{"relative_path":relative.as_posix(),"sha256":digest}}
    store.checkpoint(run_id,checkpoint)
    return deepcopy(checkpoint)


def _mapped(prefix,new_run_id,original):
    return prefix+hashlib.sha256(_bytes([new_run_id,original])).hexdigest()[:24]


def rekey_history(bundle:dict,new_run_id:str)->dict:
    """Copy numerical history, mapping identities without counting new trials."""
    old=bundle["run_id"]
    if not new_run_id or new_run_id==old: raise ValueError("Recovery requires a distinct new RunID")
    result=deepcopy(bundle)
    snapshots={row["snapshot_id"]:rekey_snapshot(row,new_run_id)["snapshot_id"] for row in bundle["posterior"]}
    actions={row["action_id"]:_mapped("action-",new_run_id,row["action_id"]) for row in bundle["actions"]}
    executions={row["execution_id"]:actions.get(row["execution_id"],_mapped("execution-",new_run_id,row["execution_id"])) for row in bundle["cashflows"]}
    result["sensor"]=[{**row,"run_id":new_run_id} for row in result["sensor"]]
    result["posterior"]=[rekey_snapshot(row,new_run_id) for row in result["posterior"]]
    for name in ("actions","cashflows","decisions"):
        for row in result[name]:
            if row.get("action_id") not in actions or row.get("snapshot_id") not in snapshots:
                raise ValueError("Checkpoint history contains an unbound identity")
            old_action, old_snapshot = row["action_id"], row["snapshot_id"]
            row["action_id"]=actions[old_action]
            row["snapshot_id"]=snapshots[old_snapshot]
            if name == "decisions" and "rate_diagnostics" in row:
                # The nested record was actually computed for the parent. Its
                # bytes/hash and identity remain historical; only the outer
                # inherited decision is reidentified for this recovery.
                row['rate_diagnostics_lineage'] = {
                    'source_action_id': row['rate_diagnostics']['action_id'],
                    'source_snapshot_id': row['rate_diagnostics']['snapshot_id'],
                    'current_action_id': row['action_id'], 'current_snapshot_id': row['snapshot_id'],
                    'reused': True, 'independent_sample': False}
            if "run_id" in row: row["run_id"]=new_run_id
            if "execution_id" in row: row["execution_id"]=executions[row["execution_id"]]
    result["run_id"]=new_run_id
    previous=bundle.get("lineage") or {}
    result["lineage"]={"origin_run_id":previous.get("origin_run_id",old),"parent_run_id":old,
        "ancestry":deepcopy(previous),"recovery_step":bundle["step"],
        "inherited_executed_intervals":bundle["step"],"independent_sample":False,
        "independent_operational_trajectories":0,
        "snapshot_id_mapping":snapshots,"action_id_mapping":actions,"execution_id_mapping":executions}
    # The PF restores its own original checkpoint and rekeys only its posterior.
    # Numerical arrays and RNG state remain byte-for-byte the inherited values.
    return result


def load_recovery_checkpoint(store,parent_run_id:str,*,expected_code_hash:str,
        expected_lock_hash:str,expected_input_hash:str,new_run_id:str,checkpoint:dict|None=None)->dict:
    """Validate the private bytes and all identities before any resumed computation."""
    if store.get(parent_run_id)["state"] not in {"cancelled","failed","interrupted"}:
        raise ValueError("Recovery source must be an incomplete terminal job")
    events = store.events(parent_run_id)
    if any(event.get('type') == 'unassimilated_execution' for event in events):
        raise ValueError('Unassimilated actual execution prevents recovery from any older pointer')
    if checkpoint is None:
        with (store.root/parent_run_id/"checkpoint.json").open("rb") as stream: raw=stream.read(1_000_001)
        if len(raw)>1_000_000: raise ValueError("Checkpoint pointer exceeds byte limit")
        checkpoint=json.loads(raw)
    if not checkpoint.get("recoverable") or checkpoint.get("complete"):
        raise ValueError("Source checkpoint is not an incomplete recoverable boundary")
    for key,expected in (("code_hash",expected_code_hash),("dependency_lock_hash",expected_lock_hash),("input_hash",expected_input_hash)):
        _digest(expected,key)
        if checkpoint.get(key)!=expected: raise ValueError("Recovery "+key+" mismatch")
    pointer=checkpoint["private_recovery"]
    digest=_digest(pointer["sha256"],"bundle")
    relative=Path(pointer["relative_path"])
    approved=(store.root/"evaluator"/parent_run_id).resolve()
    path=(store.root/relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(approved) or path.name!=f"recovery-{checkpoint['step']}-{digest}.json":
        raise ValueError("Recovery pointer is outside the parent private storage")
    with _io_path(path).open("rb") as stream: data=stream.read(MAXIMUM_BUNDLE_BYTES+1)
    if len(data)>MAXIMUM_BUNDLE_BYTES or hashlib.sha256(data).hexdigest()!=digest:
        raise ValueError("Recovery bundle byte identity mismatch")
    bundle=json.loads(data)
    if bundle.get("schema_version")!=1 or bundle.get("run_id")!=parent_run_id:
        raise ValueError("Recovery bundle parent identity mismatch")
    for key in ("step","next_step","logical_time_s","code_hash","dependency_lock_hash","input_hash","execution_config_hash"):
        if bundle.get(key)!=checkpoint.get(key): raise ValueError("Recovery pointer and bundle disagree: "+key)
    # A durable pre-launch intent survives hard exits and startup recovery.
    # Authenticated observer/action history, rather than a monitor's default
    # flag or an older pointer, establishes that execution reached a boundary.
    intents = {}
    for event in events:
        if event.get('type') == 'execution_started':
            intents[event['action_id']] = event
        elif event.get('type') == 'execution_not_started':
            if event.get('executed') is not False or event.get('solver_calls') != 0:
                raise ValueError('Invalid nonexecution receipt cannot clear an execution intent')
            intents.pop(event['action_id'], None)
    for intent in intents.values():
        step = intent['step']
        if (type(step) is not int or step < 0 or bundle['next_step'] <= step
                or len(bundle['actions']) <= step or bundle['actions'][step]['action_id'] != intent['action_id']):
            raise ValueError('Uncheckpointed execution intent prevents recovery from an older pointer')
    ledger_path = store.root / parent_run_id / 'executed_ledger.json'
    if ledger_path.is_file():
        saved_ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
        if saved_ledger.get('entries') != bundle['cashflows']:
            raise ValueError('Saved actual flows differ from the selected recoverable boundary')
    if bundle["posterior"][-1]["snapshot_id"]!=checkpoint["snapshot_id"] or bundle["pf_checkpoint"]["last_snapshot"]["snapshot_id"]!=checkpoint["snapshot_id"]:
        raise ValueError("Recovery posterior identity mismatch")
    result=rekey_history(bundle,new_run_id)
    result["lineage"].update(source_bundle_sha256=digest,source_checkpoint=deepcopy(checkpoint))
    return result


def restore_sensor_rng(payload:dict):
    if payload.get("bit_generator")!="PCG64": raise ValueError("Unsupported sensor RNG checkpoint")
    rng=np.random.Generator(np.random.PCG64());rng.bit_generator.state=deepcopy(payload)
    return rng


def restore_ledger(ledger,actions:list,cashflows:list):
    """Use actual historical energy through the ordinary ledger, exactly once."""
    if ledger.entries: raise ValueError("Restore requires an empty new-run ledger")
    indexed={row["action_id"]:Action.model_validate({key:row[key] for key in Action.model_fields}) for row in actions}
    if len(indexed)!=len(actions): raise ValueError("Duplicate inherited action identity")
    for row in cashflows:
        if row["run_id"]!=ledger.run_id or row["action_id"] not in indexed:
            raise ValueError("Inherited cashflow belongs to another run or action")
        restored=ledger.append(indexed[row["action_id"]],execution_id=row["execution_id"],energy_J=row["energy_J"],
            thermal_energy_J=row["thermal_electric_energy_J"],buy_price_per_kWh=row["buy_price_per_kWh"],
            sell_price_per_kWh=row["sell_price_per_kWh"],executed=row["executed"],reason=row["reason"],duration_s=row["duration_s"])
        if restored!=row: raise ValueError("Inherited ledger metadata or arithmetic changed")
    return ledger
