import json
from naheng.runtime.freezing import freeze_source
from naheng.runtime.artifacts import code_hash
def test_frozen_code_survives_workspace_edits(tmp_path):
    project=tmp_path/"project"; (project/"src").mkdir(parents=True)
    (project/"model_packages").mkdir()
    p=project/"src/x.py"; p.write_text("x=1")
    (project/"model_packages/model.json").write_text('{"parameter":1}')
    dest,digest=freeze_source(project,tmp_path/"run")
    p.write_text("x=2")
    assert (dest/"src/x.py").read_text()=="x=1"
    assert code_hash(dest)==digest
    assert code_hash(project)!=digest
    assert json.loads((tmp_path/"run/source_index.json").read_text())["code_hash"]==digest
