from dataclasses import replace,asdict
import json
import hashlib
import io
from pathlib import Path
import pytest
from naheng.data.importers import ImportSpec,import_csv
from naheng.data import download


def fixture(tmp_path,content=None):
    content=content or "time,I,U,T,cell,batch,trajectory\n0,1000,3200,25,c1,b1,a\n1,-500,3100,26,c1,b1,a\n"
    path=tmp_path/"synthetic_unit_fixture.csv"
    path.write_text(content,encoding="utf-8")
    spec=ImportSpec(source_id="synthetic-unit-test",source_url="https://example.invalid/unit-fixture",
        chemistry_id="synthetic_csv_test_only",current_sign="positive_charge",
        units={"time":"min","current":"mA","voltage":"mV","temperature":"degC"},
        columns={"time":"time","current":"I","voltage":"U","temperature":"T",
                 "cell_id":"cell","batch_id":"batch","trajectory_id":"trajectory"},
        license_id="test-fixture",license_evidence_sha256="",
        raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),provenance_type="synthetic",
        identity_evidence="Explicit synthetic test CSV identity columns",
        current_sign_evidence="Synthetic fixture convention, not vendor evidence")
    return path,spec


def test_explicit_vendor_sign_and_units_and_raw_source_trace_are_preserved(tmp_path):
    path,spec=fixture(tmp_path)
    dataset=import_csv(path,spec)
    assert dataset.records[0]["current_A"] == -1
    assert dataset.records[1]["current_A"] == 0.5
    assert dataset.records[1]["timestamp_s"] == 60
    assert dataset.records[0]["voltage_V"] == 3.2
    assert dataset.records[0]["temperature_K"] == 298.15
    assert dataset.records[0]["vendor_current"] == 1000
    assert dataset.records[0]["provenance_type"] == "synthetic"
    assert dataset.manifest()["external_model_validation"] == "not_performed"


def test_missing_temperature_remains_unknown_not_room_temperature(tmp_path):
    path,spec=fixture(tmp_path)
    columns={k:v for k,v in spec.columns.items() if k!="temperature"}
    dataset=import_csv(path,replace(spec,columns=columns))
    assert dataset.records[0]["temperature_K"] is None
    assert dataset.records[0]["quality"] == ["temperature_not_measured"]


@pytest.mark.parametrize("change",[
    {"raw_sha256":"0"*64},{"current_sign":"unspecified"},{"units":{"time":"s"}},
    {"chemistry_id":"unknown"},{"identity_evidence":""},{"current_sign_evidence":""},
    {"provenance_type":"public_measurement","license_id":"pending"},
    {"provenance_type":"public_measurement","license_id":"CC-BY-4.0","license_evidence_sha256":""}
])
def test_identity_license_sign_unit_or_checksum_mismatch_rejected(tmp_path,change):
    path,spec=fixture(tmp_path)
    with pytest.raises(ValueError):
        import_csv(path,replace(spec,**change))


@pytest.mark.parametrize("content",[
 "time,I,U,T,cell,batch,trajectory\n1,1,3200,25,c,b,t\n0,2,3100,25,c,b,t\n",
 "time,I,U,T,cell,batch,trajectory\n0,1,3200,25,c,b,t\n0,2,3100,25,c,b,t\n",
 "time,I,U,T,cell,batch,trajectory\n0,nan,3200,25,c,b,t\n1,2,3100,25,c,b,t\n",
 "time,I,U,T,cell,batch,trajectory\n0,1,3200,-300,c,b,t\n1,2,3100,25,c,b,t\n",
])
def test_bad_numeric_or_nonmonotonic_trajectory_not_silently_repaired(tmp_path,content):
    path,spec=fixture(tmp_path,content)
    with pytest.raises(ValueError):
        import_csv(path,spec)


def test_byte_and_row_limits_are_checked(tmp_path):
    path,spec=fixture(tmp_path)
    with pytest.raises(ValueError,match="byte"):
        import_csv(path,spec,maximum_bytes=5)
    with pytest.raises(ValueError,match="row"):
        import_csv(path,spec,maximum_rows=1)


def test_remote_archive_requires_license_range_206_and_exact_content_range(monkeypatch):
    def fake_fetch(url,maximum_bytes,records,headers=None,method="GET"):
        if method=="HEAD": return b"",{"response_headers":{"Content-Length":"100"}}
        return b"abc",{"status":200,"response_headers":{"Content-Range":"bytes 0-2/100"}}
    monkeypatch.setattr(download,"fetch",fake_fetch)
    with pytest.raises(ValueError,match="license"):
        download.RemoteZip(download.ZIP_URL,"unknown",[])
    remote=download.RemoteZip(download.ZIP_URL,"CC-BY-4.0",[])
    with pytest.raises(ValueError,match="206"):
        remote.read(3)
    def bad_range(url,maximum_bytes,records,headers=None,method="GET"):
        if method=="HEAD": return b"",{"response_headers":{"Content-Length":"100"}}
        return b"abc",{"status":206,"response_headers":{"Content-Range":"bytes 1-3/100"}}
    monkeypatch.setattr(download,"fetch",bad_range)
    remote=download.RemoteZip(download.ZIP_URL,"CC-BY-4.0",[])
    with pytest.raises(ValueError,match="Content-Range"):
        remote.read(3)


def test_remote_archive_budget_and_url_allowlist_are_fail_closed(monkeypatch):
    def head_only(url,maximum_bytes,records,headers=None,method="GET"):
        if method!="HEAD": pytest.fail("Over-budget payload must not be requested")
        return b"",{"response_headers":{"Content-Length":"100"}}
    monkeypatch.setattr(download,"fetch",head_only)
    remote=download.RemoteZip(download.ZIP_URL,"CC-BY-4.0",[],maximum_bytes=2)
    with pytest.raises(ValueError,match="budget"):
        remote.read(3)
    for bad in ["https://evil.invalid/record/987579","http://publications.rwth-aachen.de/record/987579",
                "https://publications.rwth-aachen.de/record/9875790/files/data"]:
        with pytest.raises(ValueError):
            download.allowed_url(bad)


def test_public_label_cannot_be_claimed_from_client_metadata_without_registered_source_bytes(tmp_path):
    path,spec=fixture(tmp_path)
    purported_public=replace(spec,provenance_type="public_measurement",
        license_id="CC-BY-4.0",license_evidence_sha256="a"*64)
    with pytest.raises(ValueError,match="registered source-byte"):
        import_csv(path,purported_public)


def test_verified_registry_prevents_client_from_overriding_vendor_units(tmp_path,monkeypatch):
    path,spec=fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    directory=tmp_path/"data"/"manifests"
    directory.mkdir(parents=True)
    purported=replace(spec,provenance_type="public_measurement",license_id="CC-BY-4.0",
        license_evidence_sha256="a"*64)
    registered={**asdict(purported),"verification_status":"source_bytes_verified"}
    binding=directory/"synthetic_negative_source_binding.json"
    binding.write_text(json.dumps(registered))
    bound=replace(purported,source_registry_path=str(binding),
        source_registry_sha256=hashlib.sha256(binding.read_bytes()).hexdigest(),
        units={**purported.units,"current":"A"})
    with pytest.raises(ValueError,match="units"):
        import_csv(path,bound)


def test_changed_file_after_capture_does_not_change_verified_normalized_rows(tmp_path,monkeypatch):
    path,spec=fixture(tmp_path)
    original_open=Path.open
    changed=[False]
    replacement=path.read_bytes().replace(b"1000",b"999999")
    def racing_open(current,*args,**kwargs):
        mode=args[0] if args else kwargs.get("mode","r")
        if current==path and mode=="rb" and not changed[0]:
            with original_open(current,"rb") as source:
                captured=source.read()
            with original_open(current,"wb") as destination:
                destination.write(replacement)
            changed[0]=True
            return io.BytesIO(captured)
        return original_open(current,*args,**kwargs)
    monkeypatch.setattr(Path,"open",racing_open)
    dataset=import_csv(path,spec)
    assert changed[0]
    assert dataset.records[0]["vendor_current"]==1000
    assert dataset.records[0]["current_A"]==-1
    assert dataset.raw_sha256==spec.raw_sha256
    with original_open(path,"rb") as stream:
        assert hashlib.sha256(stream.read()).hexdigest()!=dataset.raw_sha256


def test_growing_file_cannot_bypass_actual_read_byte_limit(tmp_path,monkeypatch):
    path,spec=fixture(tmp_path)
    original_open=Path.open
    def grew(current,*args,**kwargs):
        mode=args[0] if args else kwargs.get("mode","r")
        if current==path and mode=="rb":
            return io.BytesIO(b"x"*200)
        return original_open(current,*args,**kwargs)
    monkeypatch.setattr(Path,"open",grew)
    with pytest.raises(ValueError,match="byte limit"):
        import_csv(path,spec,maximum_bytes=150)
