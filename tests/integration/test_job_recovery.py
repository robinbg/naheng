import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from naheng.runtime.jobs import JobStore,JobQuotaExceeded


def test_interruption_and_cancel_are_not_complete(tmp_path):
    s=JobStore(tmp_path)
    queued=s.create({"seed":0})
    running=s.create({"seed":1})
    assert s.try_start(running["run_id"])
    s.checkpoint(running["run_id"],{"complete":False,"step":3})
    assert s.recover_interrupted()==2
    assert s.get(queued["run_id"])["state"]=="interrupted"
    assert s.get(running["run_id"])["state"]=="interrupted"
    assert not s.try_start(queued["run_id"])
    assert s.recover_interrupted()==0
    cancelled=s.create({"seed":2})
    s.cancel(cancelled["run_id"])
    assert s.get(cancelled["run_id"])["state"]=="cancelled"
    assert not s.try_start(cancelled["run_id"])


def test_only_one_concurrent_worker_can_start_the_same_job(tmp_path):
    store=JobStore(tmp_path)
    run=store.create({"seed":3})["run_id"]
    barrier=threading.Barrier(8)
    def start():
        barrier.wait()
        return store.try_start(run)
    with ThreadPoolExecutor(max_workers=8) as pool:
        result=list(pool.map(lambda _:start(),range(8)))
    assert sum(result)==1
    assert store.get(run)["state"]=="running"
    assert sum(event["type"]=="running" for event in store.events(run))==1


def test_concurrent_queued_cancel_and_start_never_restart_terminal_job(tmp_path):
    store=JobStore(tmp_path)
    for index in range(12):
        run=store.create({"seed":index})["run_id"]
        barrier=threading.Barrier(2)
        def start():
            barrier.wait()
            return store.try_start(run)
        def cancel():
            barrier.wait()
            return store.cancel(run)
        with ThreadPoolExecutor(max_workers=2) as pool:
            started=pool.submit(start)
            cancelled=pool.submit(cancel)
            started.result();cancelled.result()
        final=store.get(run)
        assert final["cancel"]==1
        assert final["state"] in ("running","cancelled")
        with pytest.raises(ValueError):
            store.state(run,"succeeded",1)
        if final["state"]=="running": store.state(run,"cancelled")
        assert not store.try_start(run)
        types=[event["type"] for event in store.events(run)]
        if "cancelled" in types:
            assert "running" not in types[types.index("cancelled")+1:]


def test_start_event_failure_rolls_back_state_and_event_together(tmp_path,monkeypatch):
    store=JobStore(tmp_path)
    run=store.create({"seed":4})["run_id"]
    original=store._event
    def unavailable(connection,run_id,payload):
        if payload["type"]=="running": raise OSError("Injected event persistence failure")
        return original(connection,run_id,payload)
    monkeypatch.setattr(store,"_event",unavailable)
    with pytest.raises(OSError,match="Injected"):
        store.try_start(run)
    assert store.get(run)["state"]=="queued"
    assert [event["type"] for event in store.events(run)]==["queued"]


def test_terminal_idempotence_and_pending_cancel_success_guard(tmp_path):
    store=JobStore(tmp_path)
    run=store.create({"seed":5})["run_id"]
    assert store.try_start(run)
    store.cancel(run)
    with pytest.raises(ValueError,match="publish success"):
        store.state(run,"succeeded",1)
    assert store.get(run)["state"]=="running"
    store.state(run,"cancelled",.25,error="Requested by user")
    before=store.get(run)
    events=store.events(run)
    store.cancel(run)
    store.state(run,"cancelled",1,error="Must not overwrite")
    assert store.get(run)==before and store.events(run)==events
    with pytest.raises(ValueError,match="Terminal"):
        store.state(run,"running")


def test_nonterminal_count_is_not_limited_to_recent_one_hundred(tmp_path):
    store=JobStore(tmp_path)
    live=store.create({"live":True})["run_id"]
    assert store.try_start(live)
    for index in range(101):
        run=store.create({"index":index})["run_id"]
        store.cancel(run)
    assert all(row["run_id"]!=live for row in store.list())
    assert store.count_nonterminal()==1


def test_eight_concurrent_enqueues_respect_atomic_four_job_quota(tmp_path):
    store=JobStore(tmp_path)
    barrier=threading.Barrier(8)
    def enqueue(index):
        barrier.wait()
        try:
            return store.create({"index":index},max_nonterminal=4)["run_id"]
        except JobQuotaExceeded:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted=list(pool.map(enqueue,range(8)))
    assert sum(run is not None for run in accepted)==4
    assert store.count_nonterminal()==4
    assert len(store.list())==4
    assert sum(len(store.events(job["run_id"])) for job in store.list())==4
    # Explicit lightweight replay metadata can opt out; computation admission
    # still counts every active row when subsequently enforcing its quota.
    replay=store.create({"mode":"replay","source":"fixture"})
    store.state(replay["run_id"],"cancelled")
    with pytest.raises(JobQuotaExceeded):
        store.create({"another":True},max_nonterminal=4)
