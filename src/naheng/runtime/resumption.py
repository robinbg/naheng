"""Create a distinct, source-bound continuation without changing its parent."""
from pathlib import Path
import json, uuid, os
from .artifacts import code_hash, sha256_file
from .freezing import freeze_source
from .recovery import config_digest, load_recovery_checkpoint

def public_lineage(value):
    """Keep private checkpoint storage metadata out of public job artifacts."""
    if isinstance(value,dict):
        return {key:public_lineage(item) for key,item in value.items() if key not in {'source_checkpoint','private_recovery'}}
    if isinstance(value,list): return [public_lineage(item) for item in value]
    return value


def prepare_recovery(project, store, parent_run_id, *, max_nonterminal=4):
    parent=store.get(parent_run_id)
    if parent['state'] not in {'failed','cancelled','interrupted'}:
        raise ValueError('Recovery requires an incomplete terminal parent')
    config=dict(parent['config'])
    if config.get('validity_profile','off')!='off':
        raise ValueError('Monitored checkpoint continuation requires restored validity history; it cannot silently reset a withdrawal')
    parent_dir=store.root/parent_run_id
    source=(parent_dir/'source_snapshot').resolve()
    if Path(config.get('source_dir','')).resolve()!=source:
        raise ValueError('Parent has no controlled frozen source')
    index=json.loads((parent_dir/'source_index.json').read_text(encoding='utf-8'))
    if index['code_hash']!=config['code_hash'] or code_hash(source)!=config['code_hash']:
        raise ValueError('Parent frozen source hash changed')
    for relative,digest in index['files'].items():
        path=(source/relative).resolve()
        if not path.is_relative_to(source) or not digest or sha256_file(path)!=digest:
            raise ValueError('Parent frozen file identity changed: '+relative)
    if not (source/'src/naheng/runtime/recovery.py').is_file():
        raise ValueError('This older run has no supported continuation code')
    lock=sha256_file(source/'uv.lock')
    checkpoint=json.loads((parent_dir/'checkpoint.json').read_text(encoding='utf-8'))
    loaded=load_recovery_checkpoint(store,parent_run_id,expected_code_hash=config['code_hash'],
        expected_lock_hash=lock,expected_input_hash=config_digest(config),
        new_run_id='preflight-'+uuid.uuid4().hex,checkpoint=checkpoint)
    expected_time=min(loaded['next_step']*config['step_s'],config['duration_s'])
    if abs(loaded['logical_time_s']-expected_time)>1e-7:
        raise ValueError('A partially executed model-domain interval cannot skip the remainder')
    config.update(recovery_source=parent_run_id,recovery_lineage={
        'origin_run_id':loaded['lineage']['origin_run_id'],'parent_run_id':parent_run_id,'recovery_step':loaded['next_step'],
        'source_bundle_sha256':loaded['lineage']['source_bundle_sha256'],
        'source_checkpoint':checkpoint,'independent_sample':False})
    new=store.create(config,max_nonterminal=max_nonterminal,owner_pid=os.getpid())
    try:
        frozen,digest=freeze_source(source,store.root/new['run_id'])
        if digest!=config['code_hash']: raise ValueError('Recovery copied source mismatch')
        config.update(source_dir=str(frozen),code_hash=digest)
        store.bind_frozen_config(new['run_id'],config)
        store.event(new['run_id'],{'type':'checkpoint_recovery',
            'origin_run_id':loaded['lineage']['origin_run_id'],'parent_run_id':parent_run_id,'recovery_step':loaded['next_step'],
            'inherited_executed_intervals':loaded['next_step'],'independent_sample':False})
    except Exception as exc:
        store.state(new['run_id'],'failed',error=type(exc).__name__+': '+str(exc))
        raise
    return store.get(new['run_id'])
