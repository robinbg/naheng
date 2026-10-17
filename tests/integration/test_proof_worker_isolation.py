from pathlib import Path
import json
import shutil
import uuid
import pytest
from naheng.discovery.dataset import build_dataset,candidate_templates,instantiate
from naheng.discovery.grammar import CandidateError
from naheng.discovery.backend_host import backend_available,install_hint
from naheng.discovery.proof_worker import prove_batch,register_checked,run_owned
ROOT=Path(__file__).resolve().parents[2]
STAGE=ROOT/'artifacts/discovery'
# Only this test drives a real proof through the isolated backend. The other
# three exercise guards that run before any backend is touched, so they stay
# active everywhere. Skipping is explicit and reasoned: an absent backend means
# "not run here", never "passed".
requires_backend=pytest.mark.skipif(not backend_available(),
    reason='optional isolated proof backend is not declared; '+install_hint())
# Proof output must live under an authorized project-owned root. The worker
# guard rejects every other location and also rejects reparse points, so
# pytest's own temporary directory is not a legal proof output path: it sits
# wherever --basetemp points, which the smoke gate places outside the project.
TEST_STAGE=ROOT/'artifacts/test-temp'/'proof-worker-isolation'

@pytest.fixture
def proof_out():
    """One unique authorized proof-output root per test, removed afterwards."""
    TEST_STAGE.mkdir(parents=True,exist_ok=True)
    out=TEST_STAGE/uuid.uuid4().hex[:12]
    out.mkdir(parents=True,exist_ok=False)
    yield out
    shutil.rmtree(out,ignore_errors=True)

def candidate():return instantiate(candidate_templates()[3],build_dataset()['roles']['train'][0])

def test_output_escape_and_resource_escape_rejected(tmp_path):
    with pytest.raises(CandidateError):run_owned(ROOT,['ignored'],ROOT,ROOT/'artifacts/escaped',1)
    with pytest.raises(CandidateError):run_owned(ROOT,['ignored'],ROOT,STAGE/'evidence/escape',121)

@requires_backend
def test_native_Lean_timeout_and_actual_retry(proof_out):
    attempts=[{'target':'Attempt_099','candidate':candidate(),'model_condition_satisfied':True}]
    timeout=prove_batch(ROOT,attempts,proof_out/'timeout',.001)
    assert timeout['status']=='timeout_unknown' and not timeout['kernel_checked']
    assert timeout['command']['executed'] and timeout['command']['memory_limit_enforced']
    with pytest.raises(CandidateError):register_checked(attempts,timeout)
    recovered=prove_batch(ROOT,attempts,proof_out/'retry',120)
    assert recovered['kernel_checked'] and recovered['audit']['status']=='passed'
    evidence=register_checked(attempts,recovered);assert len(evidence)==1
    assert set(evidence[0]['axioms'])<=set(['propext','Classical.choice','Quot.sound'])
    source=Path(recovered['source'])
    source.write_text(source.read_text(encoding='utf-8')+'\n--changed\n',encoding='utf-8')
    with pytest.raises(CandidateError):register_checked(attempts,recovered)

def test_native_missing_executable_is_unknown_and_retryable(proof_out):
    missing=run_owned(ROOT,[str(STAGE/'missing-Lean.exe')],ROOT/'formal',proof_out/'missing',1)
    assert missing['exit_code']==2 and missing['status']=='permission_or_setup_unknown' and not missing['executed']

def test_duplicate_target_rejected_before_execution(tmp_path):
    a={'target':'Attempt_001','candidate':candidate()}
    with pytest.raises(CandidateError):prove_batch(ROOT,[a,a],tmp_path/'duplicate')
