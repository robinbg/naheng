"""Technical failure controls only: every process/API below is a fake, with no OS payload."""
from types import SimpleNamespace
import subprocess
import pytest
from naheng.runtime import validation_process as validation


def run_case(monkeypatch,tmp_path,case):
    state={"returncode":None,"waits":0,"events":[]}
    class FakeProcess:
        pid=12345  # Never passed to an actual process API.
        def wait(self,timeout):
            state["waits"]+=1;state["events"].append(("wait",timeout))
            if case in {"timeout_terminate_failure","cleanup_wait15_failure","ordinary_timeout"} and state["waits"]==1:
                raise subprocess.TimeoutExpired("synthetic-never-executed",timeout)
            if case=="cleanup_wait15_failure" and state["waits"]==2:
                raise subprocess.TimeoutExpired("synthetic-cleanup-only",timeout)
            if state["returncode"] is None:
                state["returncode"]=1 if case=="native_failure" else 2 if case=="native_unknown" else 0
            return state["returncode"]
        def poll(self):
            if case=="poll_query_failure":raise OSError("SYNTHETIC owned process handle query failure")
            return state["returncode"]
    proc=FakeProcess()
    class FakeQuery:
        def __call__(self,job,kind,pointer,size,returned):
            state["events"].append(("QueryInformationJobObject",kind))
            pointer._obj.active=0
            return True
    class FakeAPI:
        def __init__(self):self.QueryInformationJobObject=FakeQuery()
        def CloseHandle(self,handle):
            state["events"].append(("CloseHandle",handle));return case!="close_handle_false"
    class FakeTree:
        def __init__(self,process):
            assert process is proc
            if case=="constructor_failure":raise RuntimeError("SYNTHETIC ProcessTree setup failure")
            self.job=123;self.api=FakeAPI()
        def terminate(self):
            state["events"].append(("terminate",))
            if case in {"timeout_terminate_failure","memory_and_terminate_failure"}:
                raise OSError("SYNTHETIC owned tree termination failure")
            if state["returncode"] is None:state["returncode"]=9
            return {"method":"synthetic-owned-job","exit_code":0}
        def close(self):
            if case=="close_handle_false":raise OSError("SYNTHETIC owned Job close failure")
            self.job=None
    def fake_popen(argv,**kwargs):
        if case=="popen_setup_failure":raise OSError("SYNTHETIC Popen setup failure")
        kwargs["stdout"].write(b"synthetic native stdout\n")
        kwargs["stderr"].write(b"synthetic native stderr\n")
        return proc
    def fake_taskkill(*args,**kwargs):
        state["events"].append(("fake_taskkill",));state["returncode"]=9
        return SimpleNamespace(returncode=0)
    def fake_killpg(*args):state["returncode"]=9
    def fake_memory(tree,amount):
        assert amount==8*1024**3
        if case=="memory_and_terminate_failure":raise RuntimeError("SYNTHETIC memory readback failure")
    monkeypatch.setattr(validation.subprocess,"Popen",fake_popen)
    monkeypatch.setattr(validation.subprocess,"run",fake_taskkill)
    monkeypatch.setattr(validation.os,"killpg",fake_killpg,raising=False)
    monkeypatch.setattr(validation,"ProcessTree",FakeTree)
    monkeypatch.setattr(validation,"_memory_limit",fake_memory)
    result=validation.run_validation_command(["synthetic-never-executed"],tmp_path,tmp_path/"stdout",tmp_path/"stderr",timeout_s=1,env={})
    return result,state


@pytest.mark.parametrize("case",["constructor_failure","timeout_terminate_failure","cleanup_wait15_failure",
    "memory_and_terminate_failure","close_handle_false","popen_setup_failure"])
def test_setup_or_cleanup_uncertainty_always_returns_blocked_record(monkeypatch,tmp_path,case):
    result,state=run_case(monkeypatch,tmp_path,case)
    assert result["exit_code"]==2 and result["status"]=="blocked"
    assert result["is_code_execution_sandbox"] is False
    assert result.get("setup_error") or result["cleanup_errors"]
    assert result["wall_s"]>=0
    if case!="popen_setup_failure":
        assert "synthetic native stdout" in (tmp_path/"stdout").read_text()
        assert "synthetic native stderr" in (tmp_path/"stderr").read_text()
        assert "native_exit_code" in result
    if case=="close_handle_false":
        assert result["native_exit_code"]==0
        assert any("Owned Job close" in error for error in result["cleanup_errors"])


@pytest.mark.parametrize(("case","native","status"),[("native_failure",1,"failed"),("native_unknown",2,"blocked")])
def test_native_failure_or_unknown_is_retained(monkeypatch,tmp_path,case,native,status):
    result,_=run_case(monkeypatch,tmp_path,case)
    assert result["exit_code"]==result["native_exit_code"]==native
    assert result["status"]==status and result["cleanup_errors"]==[]


def test_ordinary_timeout_retains_unknown_and_owned_cleanup(monkeypatch,tmp_path):
    result,_=run_case(monkeypatch,tmp_path,"ordinary_timeout")
    assert result["exit_code"]==2 and result["timed_out"]
    assert result["native_exit_code"]==9 and result["cleanup_errors"]==[]


def test_owned_handle_query_failure_does_not_escape_without_record(monkeypatch,tmp_path):
    result,_=run_case(monkeypatch,tmp_path,"poll_query_failure")
    assert result["exit_code"]==2 and result["status"]=="blocked"
    assert result["cleanup_errors"]


def test_same_batch_withholds_remaining_commands_after_unknown_cleanup(monkeypatch,tmp_path):
    import json
    from naheng.runtime import verification
    config=tmp_path/"configs/gates.yaml";config.parent.mkdir()
    config.write_text(json.dumps({"profiles":{"smoke":[
        {"id":"first","command":["synthetic-first"],"timeout_s":1},
        {"id":"later","command":["synthetic-later"],"timeout_s":1}]}}),encoding="utf-8")
    calls=[]
    def unknown_cleanup(argv,*args,**kwargs):
        calls.append(argv)
        return {"command":argv,"exit_code":2,"status":"blocked","executed":True,
            "resource_cleanup_confirmed":False,"cleanup_errors":["SYNTHETIC cleanup unknown"]}
    monkeypatch.delenv("NAHENG_VALIDATION_TEMP_ROOT",raising=False)
    monkeypatch.setattr(verification,"run_validation_command",unknown_cleanup)
    result=verification.verify(tmp_path,"smoke")
    assert calls==[["synthetic-first"]]
    assert result["exit_code"]==2 and result["status"]=="blocked"
    assert [row["id"] for row in result["checks"]]==["first","later"]
    assert result["checks"][1]["executed"] is False
    assert result["checks"][1]["exit_code"]==2
    assert result["source_and_gates_unchanged"] is True
