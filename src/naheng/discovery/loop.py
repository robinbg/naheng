"""A01 learned choices -> actual counterexample -> conditional revision -> Lean."""
from pathlib import Path
import json,time
from .grammar import CandidateError,canonical_sha
from .learner import trusted_registry
from .session import make_pool,bound_feedback,write_json
from .dataset import build_dataset
from .counterexamples import evaluate_candidate
from .providers import refine_conditions,external_provider
from .proof_worker import prove_batch,register_checked,sha,prepare_batch,authorized_output

def execution_accounting(batches):
    """Keep known execution, known nonexecution and unobserved execution distinct."""
    known=absent=unknown=confirmed_declarations=unconfirmed_declarations=0
    for batch in batches:
        execution=batch.get('command',{}).get('executed')
        declared=batch.get('requested_declarations',len(batch.get('targets',[])))
        if type(declared) is not int or declared<0:raise CandidateError('Invalid requested declaration count')
        if execution is True:
            known+=1
            count=batch.get('attempt_count')
            if type(count) is int and 0<=count<=declared:confirmed_declarations+=count
            else:unconfirmed_declarations+=declared
        elif execution is False:absent+=1
        else:
            unknown+=1;unconfirmed_declarations+=declared
    return {'confirmed_native_Lean_invocations':known,'confirmed_not_executed_batches':absent,
            'unknown_native_invocation_batches':unknown,
            'native_Lean_invocations':None if unknown else known,
            'confirmed_declaration_attempts':confirmed_declarations,
            'unknown_declaration_attempts_upper_bound':unconfirmed_declarations,
            'actual_declaration_attempts':None if unknown or unconfirmed_declarations else confirmed_declarations}

def run_loop(root,checkpoint,out,config=None,*,prepare_only=False,local_deadline=None):
    root=Path(root).resolve();out=authorized_output(root,out);out.mkdir(parents=True,exist_ok=True)
    local_deadline=time.monotonic()+1800 if local_deadline is None else local_deadline
    def remaining(limit):
        value=min(limit,local_deadline-time.monotonic())
        if value<=0:raise CandidateError('Local 30min batch deadline exhausted; no further native action')
        return value
    config={'max_proof_attempts':40,'hard_native_timeout_s':120,'external_llm':{'enabled':False}} if config is None else config
    if config.get('max_proof_attempts')!=40 or not 0<config.get('hard_native_timeout_s',0)<=120:raise CandidateError('Fixed 40-attempt protocol required')
    saved=json.loads(Path(checkpoint).read_text(encoding='utf-8'));state=saved['state']
    if canonical_sha(state)!=saved['state_sha256']:raise CandidateError('A01 checkpoint hash mismatch')
    data=build_dataset();registry=trusted_registry(data);pool=make_pool(data,registry);byid={i['item_id']:i for i in pool}
    if saved['identities']['dataset_sha256']!=canonical_sha(data) or saved['identities']['pool_sha256']!=canonical_sha(pool):raise CandidateError('A01 frozen pool/data differs')
    if saved['identities']['strategy']!='learned':raise CandidateError('Proof loop requires actual learned selection source')
    original=[];revised=[];transitions=[]
    for event in state['events']:
        item=byid.get(event['item_id'])
        if item is None:raise CandidateError('Selected item outside frozen pool')
        bound_feedback(item,event['feedback'],registry)
        if not refine_conditions(item['candidate'],event['feedback'])['added_parameter_relations']:continue
        feedback=(event['feedback'] if prepare_only else
            evaluate_candidate(item['candidate'],registry[item['model_id']]['model'],wall_budget_s=remaining(1.),numeric_replay=True))
        feedback=bound_feedback(item,feedback,registry);refinement=refine_conditions(item['candidate'],feedback)
        # This second actual check distinguishes a true conditional theorem from applicability on selected model.
        refined_feedback=({'status':'not_replayed_prepare_only','condition_satisfied':None,'kernel_checked':False}
            if prepare_only else evaluate_candidate(refinement['candidate'],registry[item['model_id']]['model'],wall_budget_s=remaining(1.),numeric_replay=True))
        n=len(original);first={'target':f'Attempt_{n:03d}','candidate':item['candidate'],'model_condition_satisfied':feedback['condition_satisfied']}
        second={'target':f'Attempt_{20+n:03d}','candidate':refinement['candidate'],'model_condition_satisfied':refined_feedback['condition_satisfied']}
        original.append(first);revised.append(second)
        transitions.append({'learned_event_step':event['step'],'item_id':item['item_id'],'model_id':item['model_id'],
            'before':first,'actual_feedback':feedback,'refinement':refinement,'after':second,'after_actual_feedback':refined_feedback,
            'analytic_result_kernel_checked':False})
        if len(original)==20:break
    if len(original)<20:raise CandidateError('Frozen learned sequence has insufficient locally refinable candidates; budget not fabricated')
    write_json(out/'pre-proof-attempts.json',{'checkpoint_sha256':sha(checkpoint),'config':config,'transitions':transitions,'attempt_count':40,
        'prepared_only':prepare_only,'requested_native_invocations':2,'actual_native_invocations':0,
        'scope':'40 requested declarations in two bounded compiler batches; not40independent native commands; per-target elaboration completion unknown until Lean receipts'})
    if prepare_only:
        leaves=[prepare_batch(root,original,out/'original-prepared')[0],prepare_batch(root,revised,out/'revised-prepared')[0]]
        report={'prepared_only':True,'generated_declarations':40,'requested_Lean_batches':2,
            'actual_declaration_attempts':0,'native_Lean_invocations':0,'registered_attempts':0,
            'scientific_N_added':0,'external_LLM_calls':0,'source_checkpoint_sha256':sha(checkpoint),
            'sources':[{ 'path':str(p),'sha256':sha(p)} for p in leaves],
            'exit_code':2,'status':'prepared_unverified'}
        write_json(out/'report.json',report);return report
    failed=prove_batch(root,original,out/'original-attempts',remaining(config['hard_native_timeout_s']))
    accepted=prove_batch(root,revised,out/'revised-attempts',remaining(config['hard_native_timeout_s']))
    rows=register_checked(revised,accepted) if accepted['kernel_checked'] else []
    write_json(out/'registry.json',{'evidence':rows,'distinct_logical_candidate_count':len({r['candidate_id'] for r in rows}),
        'conditional_model_applicability_kept':True,'new_natural_law_claim':False,'scientific_N_added':0})
    accounting=execution_accounting((failed,accepted))
    report={'max_attempts':40,'requested_declarations':40,**accounting,
        'per_target_elaboration_complete':'unknown for unsuccessful batches','execution_status':'unknown' if accounting['unknown_native_invocation_batches'] else 'confirmed',
        'original_status':failed['status'],'revised_status':accepted['status'],'registered_attempts':len(rows),
        'distinct_registered_candidates':len({r['candidate_id'] for r in rows}),
        'actual_counterexample_transitions':sum(t['actual_feedback']['status']=='counterexample_found' for t in transitions),
        'original_feedback_statuses':[t['actual_feedback']['status'] for t in transitions],
        'all_requested_denominator':40,'original_kernel_checked':failed['kernel_checked'],
        'revised_kernel_checked':accepted['kernel_checked'],'strict3_audit':accepted['audit'],
        'external_provider':external_provider(config['external_llm']),'source_checkpoint_sha256':sha(checkpoint),
        'scientific_N_added':0,'full_A02_public_gate_pending':True,
        'batch_reports':[str(out/'original-attempts/proof-report.json'),str(out/'revised-attempts/proof-report.json')],
        'exit_code':0 if not accounting['unknown_native_invocation_batches'] and failed['status']=='proof_failed' and accepted['kernel_checked'] else 2}
    write_json(out/'report.json',report);return report
