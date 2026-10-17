import gzip
import json
from pathlib import Path

import pytest

from naheng.data import member_partitions as mp
from naheng.data.zenodo_csv import SourceEvidenceError


def member(mid, author, digest, source="source"):
    return {"member_id": mid, "author_group": author, "source_id": source,
            "raw": {"sha256": digest}, "row_count": 2}


def policy(components):
    return {"explicit_candidate_roles": dict(zip(mp.ROLES, [c["component_id"] for c in components])),
            "three_nonempty_roles_required": True, "random_time_point_shuffle": False,
            "legacy_holdout_roles_locked": True}


def test_author_content_and_saved_component_take_transitive_closure():
    ms = [member("a1", "a", "X"), member("a2", "a", "Y"), member("b1", "b", "X"),
          member("b2", "b", "Z"), member("c1", "c", "Q"), member("d1", "d", "R")]
    cs = mp.provenance_components(ms, {m["member_id"]: "old-" + m["author_group"] for m in ms})
    assert sorted(c["member_ids"] for c in cs) == [["a1", "a2", "b1", "b2"], ["c1"], ["d1"]]
    assert set(mp.assign_roles(cs, policy(cs)).values()) == set(mp.ROLES)


def test_saved_component_cannot_be_broken_when_content_differs():
    ms = [member("a", "a", "X"), member("b", "b", "Y"), member("c", "c", "Z")]
    cs = mp.provenance_components(ms, {"a": "shared", "b": "shared", "c": "other"})
    assert len(cs) == 2
    with pytest.raises(SourceEvidenceError):
        mp.assign_roles(cs, policy(cs))


def test_author_numbers_are_qualified_by_source_but_content_is_global():
    ms = [member("a", "bat1", "X", "one"), member("b", "bat1", "Y", "two"), member("c", "bat2", "X", "three")]
    cs = mp.provenance_components(ms, {"a": "1", "b": "1", "c": "2"})
    assert sorted(c["member_ids"] for c in cs) == [["a", "c"], ["b"]]


@pytest.mark.parametrize("change", ["same", "missing", "extra", "shuffle", "unlock", "empty_claim"])
def test_role_and_lock_failures(change):
    ms = [member(str(i), str(i), str(i)) for i in range(3)]
    cs = mp.provenance_components(ms, {str(i): str(i) for i in range(3)})
    p = policy(cs)
    if change == "same": p["explicit_candidate_roles"]["test"] = p["explicit_candidate_roles"]["train"]
    elif change == "missing": del p["explicit_candidate_roles"]["validation"]
    elif change == "extra": p["explicit_candidate_roles"]["extra"] = "extra"
    elif change == "shuffle": p["random_time_point_shuffle"] = True
    elif change == "unlock": p["legacy_holdout_roles_locked"] = False
    else: p["three_nonempty_roles_required"] = False
    with pytest.raises(SourceEvidenceError): mp.assign_roles(cs, p)


def test_duplicate_member_identity_rejected():
    m = member("a", "a", "X")
    with pytest.raises(SourceEvidenceError): mp.provenance_components([m, m], {"a": "a"})


def fixture_stream(root):
    rows = [{"source_id": "s", "member_sha256": "raw", "author_group": "a", "source_row": i,
             "csv_line_number": i + 1, "conservative_split_component": "c", "duplicate_content": False,
             "context_id": "epoch", "quality_flags": ["negative_original_voltage"] if i == 2 else [],
             "normalization_status": "PASS", "source_values": {"Voltage (V)": "-0.1" if i == 2 else "3.1"}}
            for i in (1, 2)]
    m = {**member("m", "a", "raw", "s"), "observations": {"path": "rows.gz"}}
    v = {"conservative_split_component": "c", "duplicate_content": False, "contexts": {"epoch": 2},
         "quality_flag_counts": {"negative_original_voltage": 1}, "unknown_row_count": 0}
    return rows, m, v


def write_rows(root, rows):
    with gzip.open(root / "rows.gz", "wt", encoding="utf-8") as f:
        for row in rows: f.write(json.dumps(row) + "\n")


def test_full_scan_retains_negative_voltage_flags(tmp_path):
    rows, m, v = fixture_stream(tmp_path)
    write_rows(tmp_path, rows)
    audit = mp._scan_member(tmp_path, m, v)
    assert audit["rows"] == 2 and audit["quality_flag_counts"]["negative_original_voltage"] == 1


@pytest.mark.parametrize("mutation", ["drop", "reorder", "duplicate", "context", "author", "remove_flag", "shift_csv_line"])
def test_complete_stream_failures(tmp_path, mutation):
    rows, m, v = fixture_stream(tmp_path)
    if mutation == "drop": rows.pop()
    elif mutation == "reorder": rows.reverse()
    elif mutation == "duplicate": rows[1] = rows[0]
    elif mutation == "context": rows[1]["context_id"] = "unregistered"
    elif mutation == "author": rows[1]["author_group"] = "other"
    elif mutation == "remove_flag": rows[1]["quality_flags"] = []
    else: rows[1]["csv_line_number"] += 1
    write_rows(tmp_path, rows)
    with pytest.raises(SourceEvidenceError): mp._scan_member(tmp_path, m, v)


def test_references_reject_path_escape_and_conflicting_hash(tmp_path):
    (tmp_path / "input.json").write_text("{}")
    ref = {"path": "input.json", "sha256": mp.sha256(tmp_path / "input.json")}
    seen = {}
    mp._ref(tmp_path, ref, seen)
    with pytest.raises(SourceEvidenceError): mp._ref(tmp_path, {**ref, "sha256": "0" * 64}, seen)
    with pytest.raises(SourceEvidenceError): mp._path(tmp_path, "../outside")
    with pytest.raises(SourceEvidenceError): mp._path(tmp_path, str(tmp_path / "input.json"))


@pytest.mark.parametrize("mutation", ["missing", "extra", "changed", "substitute"])
def test_registered_acceptance_cannot_be_supplied_by_caller(tmp_path, monkeypatch, mutation):
    (tmp_path / "accepted.json").write_bytes(b"accepted registered version")
    digest = mp.sha256(tmp_path / "accepted.json")
    monkeypatch.setattr(mp, "REGISTERED_COHORT_ANCHORS", {"accepted.json": digest})
    refs = [{"path": "accepted.json", "sha256": digest}]
    mp._require_registered_anchors(tmp_path, refs, {})
    if mutation == "missing": refs.clear()
    elif mutation == "extra": refs.append({"path": "invented.json", "sha256": "0" * 64})
    elif mutation == "changed": refs[0]["sha256"] = "0" * 64
    else: refs[0]["path"] = "invented.json"
    with pytest.raises(SourceEvidenceError): mp._require_registered_anchors(tmp_path, refs, {})


@pytest.mark.parametrize("mutation", ["catalog", "policy", "cohort"])
def test_first_test_role_policy_cannot_be_changed_using_new_output_path(mutation):
    c = {"path": "any-identical-copy.json", "sha256": mp.FIRST_FROZEN_POLICY["catalog_sha256"]}
    p = {"path": "same-first-policy.json", "sha256": mp.FIRST_FROZEN_POLICY["policy_sha256"]}
    catalog = {"cohort_id": mp.FIRST_FROZEN_POLICY["cohort_id"]}
    mp._require_first_frozen_policy(c, p, catalog)
    if mutation == "catalog": c["sha256"] = "0" * 64
    elif mutation == "policy": p["sha256"] = "0" * 64
    else: catalog["cohort_id"] = "invented alias bypass"
    with pytest.raises(SourceEvidenceError): mp._require_first_frozen_policy(c, p, catalog)


def test_existing_frozen_output_fails_before_scanning(tmp_path, monkeypatch):
    path = tmp_path / "data/splits/existing.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"original frozen bytes")
    monkeypatch.setattr(mp, "_content", lambda *args: pytest.fail("Existing output must not be scanned or overwritten"))
    with pytest.raises(SourceEvidenceError): mp.freeze_members(tmp_path, {}, {}, "data/splits/existing.json")
    assert path.read_bytes() == b"original frozen bytes"


def test_frozen_content_or_new_role_policy_cannot_be_silently_accepted(tmp_path, monkeypatch):
    path = tmp_path / "data/splits/f.json"
    path.parent.mkdir(parents=True)
    saved = {"catalog_ref": {}, "policy_ref": {}, "total_rows": 6, "role_row_counts": {"train": 2}, "members": [{"role": "test"}]}
    path.write_text(json.dumps(saved))
    monkeypatch.setattr(mp, "_content", lambda *args: {**saved, "members": [{"role": "train"}]})
    with pytest.raises(SourceEvidenceError): mp.verify_members(tmp_path, {"path": "data/splits/f.json", "sha256": mp.sha256(path)})
