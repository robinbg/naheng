from naheng.runtime.jobs import JobStore
from naheng.runtime.artifacts import code_hash
def test_cache_declares_parent_and_input_change_invalidates(tmp_path):
    s=JobStore(tmp_path/"runs"); a=s.create({"code_hash":"a","seed":1})
    s.state(a["run_id"],"running"); s.state(a["run_id"],"succeeded",1)
    b=s.create({"code_hash":"a","seed":1},reuse=True)
    assert b["reused_from"]==a["run_id"]
    c=s.create({"code_hash":"b","seed":1},reuse=True)
    assert c["reused_from"] is None
def test_source_hash_captures_dirty_content(tmp_path):
    (tmp_path/"src").mkdir(); p=tmp_path/"src"/"x.py"; p.write_text("x=1")
    a=code_hash(tmp_path); p.write_text("x=2")
    assert code_hash(tmp_path)!=a
