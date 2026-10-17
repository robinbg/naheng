from dataclasses import replace
import hashlib
import json
import pytest
from naheng.data.importers import ImportSpec,import_csv
from naheng.data.splits import check_no_leakage,freeze_split


def dataset(tmp_path):
    text="time,I,U,cell,batch,trajectory\n"
    for cell in ["c1","c2","c3","c4","c5","c6"]:
        for trajectory in ["a","b"]:
            text+=f"0,1,3.2,{cell},batch-{cell},{trajectory}\n"
            text+=f"1,-1,3.1,{cell},batch-{cell},{trajectory}\n"
    path=tmp_path/"synthetic_split_fixture.csv"
    path.write_text(text)
    spec=ImportSpec(source_id="synthetic-split-test",source_url="https://example.invalid/fixture",
        chemistry_id="synthetic_test_only",current_sign="positive_discharge",
        units={"time":"s","current":"A","voltage":"V"},
        columns={"time":"time","current":"I","voltage":"U","cell_id":"cell",
                 "batch_id":"batch","trajectory_id":"trajectory"},
        license_id="test-fixture",license_evidence_sha256="",
        raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),provenance_type="synthetic",
        identity_evidence="Synthetic fixture IDs",current_sign_evidence="Synthetic fixture convention")
    return import_csv(path,spec)


def test_all_sessions_and_time_points_of_each_cell_share_frozen_role(tmp_path):
    imported=dataset(tmp_path)
    frozen=freeze_split([imported],tmp_path/"split.json",seed=6)
    assert check_no_leakage(frozen["assignments"])
    for cell in frozen["assignments"]:
        roles={r["role"] for r in frozen["assignments"] if r["cell_id"]==cell["cell_id"]}
        assert len(roles)==1
    assert freeze_split([imported],tmp_path/"split.json",seed=6)==frozen
    with pytest.raises(ValueError,match="Frozen"):
        freeze_split([imported],tmp_path/"split.json",seed=7)


def test_time_point_split_and_adjacent_point_role_leakage_rejected(tmp_path):
    imported=dataset(tmp_path)
    with pytest.raises(ValueError,match="never time points"):
        freeze_split([imported],tmp_path/"bad.json",group_by="timestamp_s")
    rows=[{**imported.records[0],"role":"train"},{**imported.records[1],"role":"test"}]
    with pytest.raises(ValueError,match="leaked"):
        check_no_leakage(rows)


def test_connected_batch_and_cell_identities_stay_in_one_role(tmp_path):
    imported=dataset(tmp_path)
    for row in imported.records:
        row["batch_id"]="shared-batch"
    result=freeze_split([imported],tmp_path/"batch.json",group_by="batch_id")
    assert result["independent_group_count"]==1
    assert len({row["role"] for row in result["assignments"]})==1
    imported.records[0]["batch_id"]=None
    with pytest.raises(ValueError,match="Missing batch"):
        freeze_split([imported],tmp_path/"missing.json",group_by="batch_id")


def test_single_group_can_be_frozen_as_external_holdout_without_invented_training(tmp_path):
    imported=dataset(tmp_path)
    result=freeze_split([imported],tmp_path/"holdout.json",holdout_only=True)
    assert result["role_record_counts"]["train"]==0
    assert result["role_record_counts"]["validation"]==0
    assert result["role_record_counts"]["test"]==len(imported.records)
    assert result["frozen"] and result["revision"]
