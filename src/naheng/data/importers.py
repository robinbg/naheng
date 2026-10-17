"""Strict, explicit CSV ingestion. No downloaded Python is executed."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import csv
import io
import hashlib
import json
from math import isfinite
from pathlib import Path
import re
from urllib.parse import urlsplit


class SourceEvidenceUnavailable(ValueError):
    """Missing or blocked registered source bytes, distinct from malformed CSV."""


@dataclass(frozen=True)
class ImportSpec:
    source_id: str
    source_url: str
    chemistry_id: str
    current_sign: str
    units: dict[str,str]
    columns: dict[str,str]
    license_id: str
    license_evidence_sha256: str
    raw_sha256: str
    provenance_type: str = "public_measurement"
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    decimal_separator: str = "."
    fixed_cell_id: str | None = None
    fixed_batch_id: str | None = None
    fixed_trajectory_id: str | None = None
    identity_evidence: str = ""
    current_sign_evidence: str = ""
    source_registry_path: str | None = None
    source_registry_sha256: str | None = None
    ordering_policy: str = "strict_increasing_time"
    ordering_evidence_path: str | None = None
    ordering_evidence_sha256: str | None = None
    temperature_channels: dict[str,str] | None = None

    def validate(self):
        if not self.source_id or not self.chemistry_id or self.chemistry_id.lower() == "unknown":
            raise ValueError("Explicit source and dataset chemistry identity required")
        url=urlsplit(self.source_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("A credential-free HTTPS source URL is required")
        if self.provenance_type not in ("public_measurement","synthetic"):
            raise ValueError("Unsupported provenance type")
        if self.current_sign not in ("positive_charge","positive_discharge"):
            raise ValueError("Vendor current sign must be explicitly declared")
        if not self.current_sign_evidence or not self.identity_evidence:
            raise ValueError("Current-sign and cell/trajectory identity evidence are required")
        if self.ordering_policy not in ("strict_increasing_time", "instrument_event_order"):
            raise ValueError("Unsupported explicit measurement ordering policy")
        if self.ordering_policy == "strict_increasing_time" and (
                self.ordering_evidence_path is not None or self.ordering_evidence_sha256 is not None):
            raise ValueError("Strict time ordering cannot carry an instrument event-order override")
        registered = None
        if self.provenance_type == "public_measurement":
            if self.license_id not in ("CC-BY-4.0","CC0-1.0"):
                raise ValueError("Public data license is unverified or unsupported")
            if not re.fullmatch("[0-9a-f]{64}",self.license_evidence_sha256):
                raise ValueError("Verified license artifact SHA-256 required")
        if (self.provenance_type == "public_measurement" or self.ordering_policy == "instrument_event_order"
                or self.source_registry_path is not None or self.source_registry_sha256 is not None):
            if not self.source_registry_path or not self.source_registry_sha256:
                raise SourceEvidenceUnavailable("Public input requires a registered source-byte verification manifest")
            registry_path=Path(self.source_registry_path).resolve()
            approved_directory=(Path.cwd()/"data"/"manifests").resolve()
            if not registry_path.is_relative_to(approved_directory) or not registry_path.is_file():
                raise SourceEvidenceUnavailable("Public source registry must exist in project data/manifests")
            registry_bytes=registry_path.read_bytes()
            if hashlib.sha256(registry_bytes).hexdigest()!=self.source_registry_sha256:
                raise ValueError("Registered source manifest checksum mismatch")
            import yaml
            registered=yaml.safe_load(registry_bytes)
            if registered.get("verification_status")!="source_bytes_verified":
                raise SourceEvidenceUnavailable("Registered public source bytes are not verified")
            for name in ("source_id","source_url","chemistry_id","license_id","raw_sha256",
                         "license_evidence_sha256","current_sign","units","columns",
                         "fixed_cell_id","fixed_batch_id","fixed_trajectory_id",
                         "identity_evidence","current_sign_evidence",
                         "delimiter","encoding","decimal_separator"):
                if registered.get(name)!=getattr(self,name):
                    raise ValueError("CSV specification does not match registered source identity: "+name)
            for name, default in (("ordering_policy", "strict_increasing_time"),
                                  ("ordering_evidence_path", None),
                                  ("ordering_evidence_sha256", None),
                                  ("temperature_channels", None)):
                if registered.get(name, default) != getattr(self, name):
                    raise ValueError("CSV specification does not match registered source identity: "+name)
        if not re.fullmatch("[0-9a-f]{64}",self.raw_sha256):
            raise ValueError("Raw file SHA-256 required")
        if self.delimiter not in (",",";","\t") or self.encoding not in ("utf-8-sig","utf-8","utf-16","latin-1"):
            raise ValueError("Unsupported explicit CSV format")
        if self.decimal_separator not in (".",","):
            raise ValueError("Unsupported decimal separator")
        expected={"time":{"s","ms","min","h"},"current":{"A","mA"},"voltage":{"V","mV"}}
        for quantity,allowed in expected.items():
            if self.units.get(quantity) not in allowed or quantity not in self.columns:
                raise ValueError("Explicit time/current/voltage units and columns required")
        if "temperature" in self.columns and self.units.get("temperature") not in ("K","degC"):
            raise ValueError("Explicit temperature unit required")
        if self.temperature_channels is not None:
            if not isinstance(self.temperature_channels, dict) or not self.temperature_channels:
                raise ValueError("Explicit nonempty temperature channel mapping required")
            if self.units.get("temperature") not in ("K", "degC"):
                raise ValueError("Explicit temperature channel unit required")
            for name, column in self.temperature_channels.items():
                _identity(name, "temperature channel")
                _identity(column, "temperature channel column")
            if len(set(self.temperature_channels.values())) != len(self.temperature_channels):
                raise ValueError("Temperature channels require distinct original columns")
        for name in ("cell_id","trajectory_id"):
            if name not in self.columns and not getattr(self,"fixed_"+name):
                raise ValueError("Cell and complete trajectory identity required")
        if self.ordering_policy == "instrument_event_order":
            if not self.fixed_cell_id or not self.fixed_batch_id or not self.fixed_trajectory_id or any(
                    name in self.columns for name in ("cell_id", "batch_id", "trajectory_id")):
                raise ValueError("Instrument event order requires one fixed physical group and complete trajectory")
            for name in ("event_index", "source_row", "instrument_step"):
                if name not in self.columns:
                    raise ValueError("Instrument event order requires original "+name+" column")
            if len({self.columns[name] for name in ("event_index", "source_row", "instrument_step")}) != 3:
                raise ValueError("Instrument order columns must be distinct")
            return _load_ordering_evidence(self, registered)


@dataclass(frozen=True)
class ImportedDataset:
    spec: ImportSpec
    raw_sha256: str
    records: list[dict]
    raw_bytes: int

    def manifest(self):
        return {"schema_version":1,"source":asdict(self.spec),"raw_sha256":self.raw_sha256,
            "raw_bytes":self.raw_bytes,"row_count":len(self.records),
            "cells":sorted({r["cell_id"] for r in self.records}),
            "trajectories":sorted({r["trajectory_id"] for r in self.records}),
            "canonical_units":{"time":"s","current":"A","voltage":"V","temperature":"K"},
            "current_sign":"positive_discharge","field_validation":"passed",
            "ordering_policy":self.spec.ordering_policy,
            "external_model_validation":"not_performed",
            "temperature_available":all(r["temperature_K"] is not None for r in self.records)}

    def write(self,out:Path):
        out=Path(out); out.mkdir(parents=True,exist_ok=True)
        (out/"manifest.json").write_text(json.dumps(self.manifest(),indent=2),encoding="utf-8")
        with (out/"observations.jsonl").open("w",encoding="utf-8") as stream:
            for row in self.records:
                stream.write(json.dumps(row,allow_nan=False)+"\n")
        return self.manifest()


def _identity(value,name):
    if not isinstance(value, str) or not value or len(value)>200 or any(ord(c)<32 for c in value):
        raise ValueError("Invalid "+name)
    return value


def _positive_integer(value, name):
    # No float rounding, decimal coercion, sign ambiguity or bool-as-int ordering.
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise ValueError("Original "+name+" must be an unambiguous positive integer")
    return int(value)


def _load_ordering_evidence(spec, registered):
    if not spec.ordering_evidence_path or not spec.ordering_evidence_sha256 or not re.fullmatch(
            "[0-9a-f]{64}", spec.ordering_evidence_sha256):
        raise SourceEvidenceUnavailable("Registered instrument event-order evidence required")
    root = Path.cwd().resolve()
    evidence_path = Path(spec.ordering_evidence_path).resolve()
    if not any(evidence_path.is_relative_to(root / folder) for folder in ("artifacts/data", "data/manifests")):
        raise SourceEvidenceUnavailable("Event-order evidence must be a project data artifact")
    if not evidence_path.is_file() or evidence_path.stat().st_size > 4*1024*1024:
        raise SourceEvidenceUnavailable("Event-order evidence missing or exceeds its byte limit")
    data = evidence_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != spec.ordering_evidence_sha256:
        raise ValueError("Instrument event-order evidence checksum mismatch")
    evidence = json.loads(data)
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise ValueError("Unsupported instrument event-order evidence schema")
    for name, expected in (("source_id", spec.source_id), ("raw_sha256", spec.raw_sha256),
                           ("fixed_cell_id", spec.fixed_cell_id), ("fixed_trajectory_id", spec.fixed_trajectory_id),
                           ("ordering_policy", spec.ordering_policy),
                           ("event_index_column", spec.columns["event_index"]),
                           ("source_row_column", spec.columns["source_row"]),
                           ("instrument_step_column", spec.columns["instrument_step"])):
        if evidence.get(name) != expected:
            raise ValueError("Instrument event-order evidence identity mismatch: "+name)
    original_path = Path(registered.get("original_measurement_path", "")).resolve()
    original_hash = registered.get("original_measurement_sha256", "")
    if not original_path.is_relative_to(root / "data/raw") or not original_path.is_file():
        raise SourceEvidenceUnavailable("Event ordering must bind a project original measurement")
    if not re.fullmatch("[0-9a-f]{64}", original_hash) or evidence.get("original_measurement_sha256") != original_hash:
        raise ValueError("Original measurement identity missing from event-order evidence")
    if original_path.stat().st_size > 50*1024*1024 or hashlib.sha256(original_path.read_bytes()).hexdigest() != original_hash:
        raise ValueError("Original measurement checksum or byte-limit mismatch")
    steps = evidence.get("instrument_step_order")
    events = evidence.get("event_records")
    transitions = evidence.get("co_timed_step_transitions")
    if not isinstance(steps, list) or not steps or any(not isinstance(step, str) for step in steps) or len(set(steps)) != len(steps):
        raise ValueError("Distinct original instrument step order required")
    for step in steps:
        _identity(step, "instrument step")
    if not isinstance(events, list) or not 2 <= len(events) <= 1_000_000 or not isinstance(transitions, list):
        raise ValueError("Explicit original event records and step transitions required")
    for event in events:
        if not isinstance(event, dict) or set(event) != {"event_index", "source_row", "instrument_step", "timestamp_s"}:
            raise ValueError("Malformed original event-order record")
        _positive_integer(event["event_index"], "event_index")
        _positive_integer(event["source_row"], "source_row")
        if event["instrument_step"] not in steps or isinstance(event["timestamp_s"], bool) or not isinstance(
                event["timestamp_s"], (int, float)) or not isfinite(event["timestamp_s"]) or event["timestamp_s"] < 0:
            raise ValueError("Invalid original event-order record")
    transition_keys = {"before_event_index", "after_event_index", "before_source_row", "after_source_row",
                       "before_instrument_step", "after_instrument_step", "timestamp_s"}
    for transition in transitions:
        if not isinstance(transition, dict) or set(transition) != transition_keys:
            raise ValueError("Malformed documented co-timed step transition")
    if len({json.dumps(item, sort_keys=True) for item in transitions}) != len(transitions):
        raise ValueError("Duplicate documented co-timed step transition")
    return evidence


def import_csv(path:Path,spec:ImportSpec,maximum_bytes=50*1024*1024,maximum_rows=1_000_000):
    ordering = spec.validate()
    path=Path(path)
    if path.stat().st_size > maximum_bytes:
        raise ValueError("CSV exceeds the configured byte limit")
    with path.open("rb") as stream:
        data=stream.read(maximum_bytes+1)
    if len(data)>maximum_bytes:
        raise ValueError("CSV exceeds the configured byte limit")
    digest=hashlib.sha256(data).hexdigest()
    if digest != spec.raw_sha256:
        raise ValueError("Raw checksum mismatch")
    time_scale={"s":1,"ms":.001,"min":60,"h":3600}[spec.units["time"]]
    current_scale={"A":1,"mA":.001}[spec.units["current"]]
    voltage_scale={"V":1,"mV":.001}[spec.units["voltage"]]
    sign=-1 if spec.current_sign=="positive_charge" else 1
    previous={}
    previous_event = None
    used_transitions = []
    output=[]
    def number(value,line,field):
        try:
            numeric=float(value.replace(",",".") if spec.decimal_separator=="," else value)
        except (AttributeError,ValueError):
            raise ValueError(f"Invalid {field} at CSV line {line}") from None
        if not isfinite(numeric): raise ValueError(f"Nonfinite {field} at CSV line {line}")
        return numeric
    # Parse exactly the immutable bytes whose identity was just verified.
    # A later filesystem edit cannot replace the normalized source contents.
    with io.StringIO(data.decode(spec.encoding),newline="") as stream:
        reader=csv.DictReader(stream,delimiter=spec.delimiter)
        if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)):
            raise ValueError("Missing or duplicate CSV headers")
        missing=(set(spec.columns.values()) | set((spec.temperature_channels or {}).values()))-set(reader.fieldnames)
        if missing: raise ValueError("Missing configured CSV columns: "+", ".join(sorted(missing)))
        for line,row in enumerate(reader,2):
            if len(output)>=maximum_rows: raise ValueError("CSV exceeds the configured row limit")
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed CSV record at line {line}")
            cell=_identity(row[spec.columns["cell_id"]] if "cell_id" in spec.columns else spec.fixed_cell_id,"cell_id")
            trajectory=_identity(row[spec.columns["trajectory_id"]] if "trajectory_id" in spec.columns else spec.fixed_trajectory_id,"trajectory_id")
            batch=row[spec.columns["batch_id"]] if "batch_id" in spec.columns else spec.fixed_batch_id
            if batch is not None: batch=_identity(batch,"batch_id")
            timestamp=number(row[spec.columns["time"]],line,"time")*time_scale
            if timestamp<0: raise ValueError("Negative measurement time")
            key=(cell,trajectory)
            event = None
            if ordering is None:
                if key in previous and timestamp<=previous[key]:
                    raise ValueError(f"Nonmonotonic or duplicate time in complete trajectory at CSV line {line}")
            else:
                event = {"event_index": _positive_integer(row[spec.columns["event_index"]], "event_index"),
                         "source_row": _positive_integer(row[spec.columns["source_row"]], "source_row"),
                         "instrument_step": _identity(row[spec.columns["instrument_step"]], "instrument_step"),
                         "timestamp_s": timestamp}
                if len(output) >= len(ordering["event_records"]) or event != ordering["event_records"][len(output)]:
                    raise ValueError(f"CSV order differs from documented original event at line {line}")
                if previous_event is None and event["instrument_step"] != ordering["instrument_step_order"][0]:
                    raise ValueError("Original first instrument step is missing")
                if previous_event is not None:
                    if event["event_index"] <= previous_event["event_index"] or event["source_row"] <= previous_event["source_row"]:
                        raise ValueError(f"Non-increasing original event or source row order at CSV line {line}")
                    if timestamp < previous_event["timestamp_s"]:
                        raise ValueError(f"Regressing global instrument clock at CSV line {line}")
                    steps = ordering["instrument_step_order"]
                    old_step, new_step = steps.index(previous_event["instrument_step"]), steps.index(event["instrument_step"])
                    if new_step not in (old_step, old_step+1):
                        raise ValueError(f"Regressing or skipped documented instrument step at CSV line {line}")
                    if timestamp == previous_event["timestamp_s"]:
                        transition = {"before_event_index": previous_event["event_index"], "after_event_index": event["event_index"],
                                      "before_source_row": previous_event["source_row"], "after_source_row": event["source_row"],
                                      "before_instrument_step": previous_event["instrument_step"],
                                      "after_instrument_step": event["instrument_step"], "timestamp_s": timestamp}
                        if old_step == new_step or transition not in ordering["co_timed_step_transitions"]:
                            raise ValueError(f"Undocumented or within-step duplicate timestamp at CSV line {line}")
                        used_transitions.append(transition)
                previous_event = event
            previous[key]=timestamp
            vendor_current=number(row[spec.columns["current"]],line,"current")
            temperature=None
            if "temperature" in spec.columns and row[spec.columns["temperature"]].strip():
                temperature=number(row[spec.columns["temperature"]],line,"temperature")
                if spec.units["temperature"]=="degC": temperature+=273.15
                if temperature<=0: raise ValueError("Temperature below absolute zero")
            record={"source_id":spec.source_id,"chemistry_id":spec.chemistry_id,
                "provenance_type":spec.provenance_type,"cell_id":cell,"batch_id":batch,
                "trajectory_id":trajectory,"timestamp_s":timestamp,
                "current_A":sign*current_scale*vendor_current,
                "voltage_V":voltage_scale*number(row[spec.columns["voltage"]],line,"voltage"),
                "temperature_K":temperature,"vendor_current":vendor_current,
                "vendor_current_unit":spec.units["current"],"vendor_current_sign":spec.current_sign,
                "source_csv_line":line,"raw_sha256":digest,
                "quality":[] if temperature is not None else ["temperature_not_measured"]}
            if event is not None:
                record.update(event_index=event["event_index"], source_row=event["source_row"], instrument_step=event["instrument_step"])
            if spec.temperature_channels is not None:
                record["raw_temperature_channels"] = {}
                for name, column in spec.temperature_channels.items():
                    raw = row[column]
                    value = number(raw, line, "temperature channel "+name)
                    kelvin = value + 273.15 if spec.units["temperature"] == "degC" else value
                    if kelvin <= 0:
                        raise ValueError("Temperature channel below absolute zero")
                    record["raw_temperature_channels"][name] = {"raw_value": raw, "unit": spec.units["temperature"]}
            output.append(record)
    if len(output)<2:
        raise ValueError("A measurement trajectory requires at least two records")
    if ordering is not None:
        if len(output) != len(ordering["event_records"]):
            raise ValueError("Missing original instrument event records")
        if used_transitions != ordering["co_timed_step_transitions"]:
            raise ValueError("Documented co-timed transitions were not exactly observed in original order")
        if previous_event["instrument_step"] != ordering["instrument_step_order"][-1]:
            raise ValueError("Original final instrument step is missing")
    return ImportedDataset(spec,digest,output,len(data))


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--csv",type=Path,required=True)
    parser.add_argument("--spec",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    try:
        spec=ImportSpec(**json.loads(args.spec.read_text(encoding="utf-8")))
        manifest=import_csv(args.csv,spec).write(args.out)
        print(json.dumps(manifest,indent=2))
        return 0
    except SourceEvidenceUnavailable as error:
        print(json.dumps({"status":"blocked","reason":str(error)}))
        return 2
    except ValueError as error:
        print(json.dumps({"status":"failed","reason":str(error)}))
        return 1


if __name__=="__main__": raise SystemExit(main())
