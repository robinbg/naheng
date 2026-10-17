"""Synthetic, structurally registered fixtures test event order, never public truth."""
from dataclasses import asdict, replace
from pathlib import Path
import csv
import hashlib
import json
import pytest
from naheng.data.importers import ImportSpec, import_csv


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path, monkeypatch, *, rows=None, steps=None, edit_evidence=None):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/raw").mkdir(parents=True)
    (tmp_path / "data/manifests").mkdir(parents=True)
    (tmp_path / "artifacts/data").mkdir(parents=True)
    if rows is None:
        rows = [(1, 2, "1", 0), (2, 3, "1", 1), (3, 4, "2", 1),
                (4, 5, "2", 1.1), (5, 6, "5", 1.1), (6, 7, "5", 2)]
    path = tmp_path / "data/raw/synthetic_order_fixture.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["idx", "source_row", "step", "time", "I", "V", "T1", "T2"])
        for idx, source_row, step, time in rows:
            writer.writerow([idx, source_row, step, time, -1, 12, -12.3, -11.7])
    events = [{"event_index": idx, "source_row": source_row, "instrument_step": step, "timestamp_s": time}
              for idx, source_row, step, time in rows]
    transitions = [{"before_event_index": before[0], "after_event_index": after[0],
                    "before_source_row": before[1], "after_source_row": after[1],
                    "before_instrument_step": before[2], "after_instrument_step": after[2], "timestamp_s": after[3]}
                   for before, after in zip(rows, rows[1:]) if before[3] == after[3] and before[2] != after[2]]
    evidence = {"schema_version": 1, "source_id": "synthetic-order-test", "raw_sha256": sha(path),
                "fixed_cell_id": "synthetic-pack-group", "fixed_trajectory_id": "synthetic-complete",
                "ordering_policy": "instrument_event_order", "original_measurement_sha256": sha(path),
                "event_index_column": "idx", "source_row_column": "source_row", "instrument_step_column": "step",
                "instrument_step_order": steps or list(dict.fromkeys(row[2] for row in rows)),
                "event_records": events, "co_timed_step_transitions": transitions,
                "scope": "Synthetic unit fixture input projection; not a real instrument or public evidence"}
    if edit_evidence:
        edit_evidence(evidence)
    evidence_path = tmp_path / "artifacts/data/synthetic_order_evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    spec = ImportSpec(source_id="synthetic-order-test", source_url="https://example.invalid/synthetic-only",
        chemistry_id="synthetic_pack_test_only", current_sign="positive_charge",
        units={"time": "s", "current": "A", "voltage": "V", "temperature": "degC"},
        columns={"time": "time", "current": "I", "voltage": "V", "temperature": "T1",
                 "event_index": "idx", "source_row": "source_row", "instrument_step": "step"},
        license_id="test-fixture", license_evidence_sha256="", raw_sha256=sha(path), provenance_type="synthetic",
        delimiter=",", encoding="utf-8", fixed_cell_id="synthetic-pack-group", fixed_batch_id="synthetic-batch",
        fixed_trajectory_id="synthetic-complete", identity_evidence="Synthetic complete pack fixture",
        current_sign_evidence="Synthetic discharge-negative fixture convention",
        ordering_policy="instrument_event_order", ordering_evidence_path=str(evidence_path),
        ordering_evidence_sha256=sha(evidence_path), temperature_channels={"T1": "T1", "T2": "T2"})
    registry = tmp_path / "data/manifests/synthetic-order.json"
    registry.write_text(json.dumps({**asdict(spec), "verification_status": "source_bytes_verified",
        "original_measurement_path": str(path), "original_measurement_sha256": sha(path)}), encoding="utf-8")
    return path, replace(spec, source_registry_path=str(registry), source_registry_sha256=sha(registry))


def test_complete_event_order_keeps_clock_units_source_rows_steps_and_raw_channels(tmp_path, monkeypatch):
    path, spec = fixture(tmp_path, monkeypatch)
    dataset = import_csv(path, spec)
    assert [row["timestamp_s"] for row in dataset.records] == [0, 1, 1, 1.1, 1.1, 2]
    assert [row["event_index"] for row in dataset.records] == list(range(1, 7))
    assert [row["source_row"] for row in dataset.records] == list(range(2, 8))
    assert [row["instrument_step"] for row in dataset.records] == ["1", "1", "2", "2", "5", "5"]
    assert {row["trajectory_id"] for row in dataset.records} == {"synthetic-complete"}
    assert {row["cell_id"] for row in dataset.records} == {"synthetic-pack-group"}
    assert all(row["current_A"] == 1 and row["voltage_V"] == 12 for row in dataset.records)
    assert dataset.records[0]["temperature_K"] == -12.3 + 273.15
    assert dataset.records[0]["raw_temperature_channels"] == {
        "T1": {"raw_value": "-12.3", "unit": "degC"}, "T2": {"raw_value": "-11.7", "unit": "degC"}}
    assert dataset.manifest()["ordering_policy"] == "instrument_event_order"
    assert dataset.manifest()["external_model_validation"] == "not_performed"


def test_strict_default_still_rejects_co_timed_transition(tmp_path, monkeypatch):
    path, spec = fixture(tmp_path, monkeypatch)
    strict = replace(spec, ordering_policy="strict_increasing_time", ordering_evidence_path=None,
                     ordering_evidence_sha256=None, source_registry_path=None, source_registry_sha256=None)
    with pytest.raises(ValueError, match="duplicate time"):
        import_csv(path, strict)


@pytest.mark.parametrize("rows,pattern", [
    ([(1, 2, "1", 0), (2, 3, "1", 0)], "within-step duplicate"),
    ([(1, 2, "1", 1), (2, 3, "2", 0)], "Regressing global"),
    ([(1, 2, "1", 0), (1, 3, "2", 0)], "Non-increasing original event"),
    ([(2, 2, "1", 0), (1, 3, "2", 0)], "Non-increasing original event"),
    ([(1, 2, "1", 0), (2, 2, "2", 0)], "Non-increasing original event"),
    ([(1, 3, "1", 0), (2, 2, "2", 0)], "Non-increasing original event"),
    ([(1, 2, "1", 0), (2, 3, "2", 1), (3, 4, "1", 2)], "Regressing or skipped"),
    ([("1.0", 2, "1", 0), (2, 3, "2", 1)], "unambiguous positive integer"),
    ([(True, 2, "1", 0), (2, 3, "2", 1)], "unambiguous positive integer"),
])
def test_ambiguous_or_regressing_order_rejected_even_when_input_projection_records_it(tmp_path, monkeypatch, rows, pattern):
    path, spec = fixture(tmp_path, monkeypatch, rows=rows)
    with pytest.raises(ValueError, match=pattern):
        import_csv(path, spec)


@pytest.mark.parametrize("edit,pattern", [
    (lambda value: value.update(co_timed_step_transitions=[]), "Undocumented"),
    (lambda value: value["co_timed_step_transitions"][0].update(before_source_row=999), "Undocumented"),
    (lambda value: value.update(instrument_step_order=["1", "unused", "2", "5"]), "Regressing or skipped"),
    (lambda value: value["event_records"][0].update(event_index=99), "differs from documented"),
    (lambda value: value["event_records"].pop(), "differs from documented"),
    (lambda value: value["event_records"].append({"event_index": 7, "source_row": 8, "instrument_step": "5", "timestamp_s": 3}), "Missing original"),
    (lambda value: value.update(source_id="another-pack"), "identity mismatch"),
    (lambda value: value.update(original_measurement_sha256="0" * 64), "Original measurement identity"),
])
def test_documented_transition_and_exact_original_projection_required(tmp_path, monkeypatch, edit, pattern):
    path, spec = fixture(tmp_path, monkeypatch, edit_evidence=edit)
    with pytest.raises(ValueError, match=pattern):
        import_csv(path, spec)


@pytest.mark.parametrize("change,pattern", [
    ({"ordering_policy": "allow_duplicates"}, "Unsupported"),
    ({"source_registry_path": None, "source_registry_sha256": None}, "registered source-byte"),
    ({"ordering_evidence_sha256": "0" * 64}, "ordering_evidence_sha256"),
    ({"ordering_policy": "strict_increasing_time", "ordering_evidence_path": None, "ordering_evidence_sha256": None}, "ordering_policy"),
    ({"temperature_channels": {"T1": "T2"}}, "temperature_channels"),
    ({"units": {"time": "ms", "current": "A", "voltage": "V", "temperature": "degC"}}, "units"),
])
def test_policy_evidence_units_and_channels_cannot_override_registered_identity(tmp_path, monkeypatch, change, pattern):
    path, spec = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match=pattern):
        import_csv(path, replace(spec, **change))


def test_changed_order_evidence_and_original_measurement_bytes_rejected(tmp_path, monkeypatch):
    path, spec = fixture(tmp_path, monkeypatch)
    evidence = Path(spec.ordering_evidence_path)
    original = evidence.read_bytes()
    evidence.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="evidence checksum"):
        import_csv(path, spec)
    evidence.write_bytes(original)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Original measurement checksum"):
        import_csv(path, spec)


@pytest.mark.parametrize("change,pattern", [
    ({"ordering_evidence_path": None, "ordering_evidence_sha256": None}, "event-order evidence required"),
    ({"fixed_trajectory_id": None}, "complete trajectory identity required"),
    ({"fixed_batch_id": None}, "one fixed physical"),
    ({"columns": {"time": "time", "current": "I", "voltage": "V", "temperature": "T1",
                  "event_index": "idx", "source_row": "source_row"}}, "instrument_step column"),
    ({"columns": {"time": "time", "current": "I", "voltage": "V", "temperature": "T1",
                  "event_index": "idx", "source_row": "idx", "instrument_step": "step"}}, "must be distinct"),
])
def test_missing_evidence_or_ambiguous_contract_rejected_even_if_registered(tmp_path, monkeypatch, change, pattern):
    path, spec = fixture(tmp_path, monkeypatch)
    changed = replace(spec, **change)
    registry = Path(spec.source_registry_path)
    metadata = json.loads(registry.read_text(encoding="utf-8"))
    metadata.update(change)
    registry.write_text(json.dumps(metadata), encoding="utf-8")
    changed = replace(changed, source_registry_sha256=sha(registry))
    with pytest.raises(ValueError, match=pattern):
        import_csv(path, changed)
