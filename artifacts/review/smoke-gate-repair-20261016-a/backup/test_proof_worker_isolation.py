from pathlib import Path
import json
import pytest
from naheng.discovery.dataset import build_dataset,candidate_templates,instantiate
from naheng.discovery.grammar import CandidateError
from naheng.discovery.proof_worker import prove_batch,register_checked,run_owned
ROOT=Path(__file__).resolve().parents[2]
STAGE=ROOT/'artifacts/discovery'

def candidate():return instantiate(candidate_templates()[3],build_dataset()['roles']['train'][0])

def test_output_escape_and_resource_escape_rejected(tmp_path):
    with pytest.raises(CandidateError):run_owned(ROOT,['ignored'],ROOT,ROOT/'artifacts/escaped',1)
    with pytest.raises(CandidateError):run_owned(ROOT,['ignored'],ROOT,STAGE/'evidence/escape',121)

def test_native_Lean_timeout_and_actual_retry(tmp_path):
    attempts=[{'target':'Attempt_099','candidate':candidate(),'model_condition_satisfied':True}]
    timeout=prove_batch(ROOT,attempts,tmp_path/'timeout',.001)
    assert timeout['status']=='timeout_unknown' and not timeout['kernel_checked']
    assert timeout['command']['executed'] and timeout['command']['memory_limit_enforced']
    with pytest.raises(CandidateError):register_checked(attempts,timeout)
    recovered=prove_batch(ROOT,attempts,tmp_path/'retry',120)
    assert recovered['kernel_checked'] and recovered['audit']['status']=='passed'
    evidence=register_checked(attempts,recovered);assert len(evidence)==1
    assert set(evidence[0]['axioms'])<=set(['propext','Classical.choice','Quot.sound'])
    source=Path(recovered['source']);source.write_text(source.read_text()+'\n--changed\n')
    with pytest.raises(CandidateError):register_checked(attempts,recovered)

def test_native_missing_executable_is_unknown_and_retryable(tmp_path):
    missing=run_owned(ROOT,[str(STAGE/'missing-Lean.exe')],ROOT/'formal',tmp_path/'missing',1)
    assert missing['exit_code']==2 and missing['status']=='permission_or_setup_unknown' and not missing['executed']

def test_duplicate_target_rejected_before_execution(tmp_path):
    a={'target':'Attempt_001','candidate':candidate()}
    with pytest.raises(CandidateError):prove_batch(ROOT,[a,a],tmp_path/'duplicate')
