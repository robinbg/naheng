"""Publish required artifacts before the atomic terminal success transition."""
from .artifacts import atomic_json,sha256_file
import json

def publish_complete(store,run_id,dest,manifest,report,artifacts,*,step,snapshot_id):
    (dest/"report.html").write_text(report,encoding="utf-8")
    # This is the pre-commit event snapshot. Terminal events remain in SQLite/API.
    atomic_json(dest/"events.json",store.events(run_id))
    atomic_json(dest/"manifest.json",manifest.model_dump(mode="json"))
    hashes={}
    for key,value in artifacts.items():
        path=(dest/value).resolve()
        if not path.is_relative_to(dest.resolve()) or not path.is_file(): raise OSError("Missing or uncontrolled required artifact: "+key)
        hashes[key]=sha256_file(path)
        if hashes[key] is None: raise OSError("Missing required artifact hash: "+key)
    atomic_json(dest/"artifact_hashes.json",hashes)
    pointer=dest/'checkpoint.json'
    checkpoint=json.loads(pointer.read_text(encoding='utf-8')) if pointer.is_file() else {}
    checkpoint.update(step=step,complete=True,snapshot_id=snapshot_id,recoverable=False)
    store.checkpoint(run_id,checkpoint)
    # No required file write follows this transition; cancel is checked atomically.
    store.state(run_id,"succeeded",1)
def record_incomplete(store,run_id,dest,error,*,steps,sensor,execution_pending=False):
    """Best effort file invalidation; SQLite remains authoritative if disk writes fail."""
    import json
    if execution_pending:
        # SQLite is authoritative even when the checkpoint-file write fails.
        # A caller cannot revive an older explicit pointer across real work.
        store.event(run_id,{'type':'unassimilated_execution','executed_steps':steps,
            'reason':'Actual execution was not incorporated into a recoverable observer boundary'})
    failure_name="additional_failure.json" if (dest/"failure.json").exists() else "failure.json"
    checkpoint={"complete":False,"step":steps}
    try:
        existing=dest/"checkpoint.json"
        if existing.is_file(): checkpoint=json.loads(existing.read_text(encoding="utf-8"))
    except (OSError,ValueError) as invalidation_error:
        store.event(run_id,{"type":"artifact_invalidation_error","artifact":"checkpoint.json","error":str(invalidation_error)})
    checkpoint.update(complete=False,incomplete_reason="execution_or_publication_failed")
    if checkpoint.get('private_recovery'): checkpoint['recoverable']=not execution_pending
    if execution_pending:
        checkpoint.update(recoverable=False,unassimilated_execution=True,
                          incomplete_reason='Actual execution not incorporated into a recoverable observer boundary')
    operations=[(failure_name,{"complete":False,"error_type":type(error).__name__,"error":str(error),"steps":steps,"sensor":sensor}),
                ("checkpoint.json",checkpoint)]
    manifest_path=dest/"manifest.json"
    try:
        if manifest_path.is_file():
            value=json.loads(manifest_path.read_text(encoding="utf-8")); value["complete"]=False
            operations.append(("manifest.json",value))
    except (OSError,ValueError) as invalidation_error:
        store.event(run_id,{"type":"artifact_invalidation_error","artifact":"manifest.json","error":str(invalidation_error)})
    for name,value in operations:
        try: atomic_json(dest/name,value)
        except OSError as invalidation_error:
            store.event(run_id,{"type":"artifact_invalidation_error","artifact":name,"error":str(invalidation_error)})
