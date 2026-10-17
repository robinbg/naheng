"""Local source index reconciliation; never download, import, split, or fit data."""
import argparse
import copy
import csv
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/manifests/sources.yaml"
MEMBER_MANIFESTS = [
    "artifacts/data/public_independent/zenodo13836819-complete-members-de471d9e/manifest.json",
    "artifacts/data/public_independent/zenodo13836819-complete-members-8d838012/manifest.json",
]
LATEST_HANDOFF = "artifacts/data/public_independent/cohort-revision2-addd1ce2/delivery.json"
OLD_HANDOFF = "artifacts/data/public_independent/D01_independent_data_delivery.json"
CVUT_HANDOFF = "artifacts/data/public_new/ordered-delivery-v3-fa6715bc.json"
EXACT = {"time": "Test Time (s)", "current": "Current (A)", "voltage": "Voltage (V)",
         "temperature": "Aux_Temperature_1 (C)", "sequence": "Data Point", "step": "Step Index",
         "charge_capacity": "Charge Capacity (Ah)", "discharge_capacity": "Discharge Capacity (Ah)"}


def sha(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def local(path):
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError("Evidence path escapes repository")
    return resolved


def relative(path):
    return local(path).relative_to(ROOT).as_posix()


def file_ref(path):
    original = local(path)
    return {"path": relative(original), "sha256": sha(original)}


def components_for_members(members):
    """Connected components join all author IDs sharing any original SHA."""
    groups = sorted({m["author_group"] for m in members})
    adjacency = {group: set() for group in groups}
    contents = {}
    for member in members:
        contents.setdefault(member["sha256"], []).append(member)
    duplicates = []
    for digest, matching in contents.items():
        if len(matching) > 1:
            touched = {m["author_group"] for m in matching}
            for group in touched:
                adjacency[group].update(touched - {group})
            duplicates.append({"sha256": digest, "members": [{"name": m["name"], "group": m["author_group"]} for m in matching],
                               "cross_author_group": len(touched) > 1})
    result, seen = [], set()
    for group in groups:
        if group in seen:
            continue
        pending, component = [group], set()
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(adjacency[current] - component)
        seen.update(component)
        result.append(sorted(component))
    return sorted(result), sorted(duplicates, key=lambda d: d["sha256"])


def validate_new_source(source):
    if source["verification_status"] != "complete_member_crc_verified" or source["checksum"] is not None:
        raise ValueError("Partial archives cannot receive a whole source checksum or verified state")
    if source["independent_physical_groups"] is not None or source["physical_independence_status"] != "UNKNOWN":
        raise ValueError("Author IDs and split components are not confirmed independent physical cells")
    if source["D01_complete"] or source["D02_complete"]:
        raise ValueError("Raw byte audit cannot complete scientific import or external validation")
    if (source['split_assignment_status'] != 'not_assigned' or source['frozen_split'] is not None
            or source['model_fit_status'] != 'not_performed' or source['external_model_validation'] != 'not_performed'):
        raise ValueError('Unit views cannot establish splitting, model fitting or external validation')
    if source["license_id"] != "CC-BY-4.0":
        raise ValueError("Expected stored official license")
    for archive in source["archives"]:
        if archive["archive_md5_status"] != "UNKNOWN" or archive["whole_archive_official_md5_verified"] is not False:
            raise ValueError("Whole official archive MD5 is unknown")
        if archive["retained_prefix_bytes"] >= archive["official_size_bytes"]:
            raise ValueError("Expected a preserved partial archive")
    components, duplicates = components_for_members(source["raw_members"])
    if components != sorted(source["conservative_split_components"]) or duplicates != source["content_duplicates"]:
        raise ValueError("Source components must follow all original content duplicates")
    if len(components) != source["conservative_split_component_count"]:
        raise ValueError("Component count mismatch")
    if any(m["crc_status"] != "complete_member_crc_verified" for m in source["raw_members"]):
        raise ValueError("Incomplete compressed members cannot be registered as complete")
    status = source['canonical_import_status']
    if status == 'seven_complete_member_unit_views_reopened':
        validate_unit_view_evidence(source)
    elif status != 'not_performed':
        raise ValueError('Unsupported canonical import claim')


def validate_unit_view_evidence(source):
    """A reviewed unit view is a separate layer from scientific completion."""
    def checked_ref(value):
        if not isinstance(value, dict) or not isinstance(value.get('path'), str) or not value.get('sha256'):
            raise ValueError('Unit-view evidence reference required')
        path = local(value['path'])
        if not path.is_file() or sha(path) != value['sha256']:
            raise ValueError('Unit-view evidence reference changed or missing')
        return read(path)

    acceptance = source.get('canonical_view_acceptance', {})
    handoff = checked_ref(acceptance.get('normal_entry_handoff'))
    review = checked_ref(acceptance.get('independent_review'))
    if (review.get('exit_code') != 0 or not review.get('independent_of_writer_and_validator_author')
            or not review.get('checks') or any(c.get('status') != 'passed' for c in review['checks'])):
        raise ValueError('Actual independent unit-view review required')
    if handoff.get('D01_complete') is not False or handoff.get('D02_complete') is not False:
        raise ValueError('Unit-view handoff cannot complete scientific gates')
    if handoff.get('all_original_rows') != source['raw_rows_including_duplicate']:
        raise ValueError('Unit-view cohort row count differs')
    members = handoff.get('members', [])
    registered = source['raw_members']
    if len(members) != len(registered) or {m['raw'] for m in members} != {m['path'] for m in registered}:
        raise ValueError('Unit-view member coverage differs')
    required_files = {'src/naheng/data/zenodo_csv.py', 'tests/unit/test_zenodo_csv.py', 'tools/validate_zenodo_csv.py'}
    if set(handoff.get('public_files_sha256', {})) != required_files:
        raise ValueError('Unit-view implementation baseline requires all three exact files')
    reviewed = review.get('members', [])
    if (len(reviewed) != len(members) or {m['raw'] for m in reviewed} != {m['raw'] for m in members}
            or review.get('public_baseline_sha256') != handoff['public_files_sha256']):
        raise ValueError('Independent unit-view member coverage or implementation differs')
    for member in members:
        seen = next(m for m in reviewed if m['raw'] == member['raw'])
        if (local(seen['view']) != local(member['view']) or seen['manifest_sha256'] != member['member_manifest_sha256']
                or seen['raw_identity']['sha256'] != member['raw_sha256']
                or seen['output_identity']['sha256'] != member['view_sha256']
                or seen['independent_output_line_count'] != member['rows']):
            raise ValueError('Independent unit-view member binding differs')
    for relative, digest in handoff['public_files_sha256'].items():
        if sha(local(relative)) != digest:
            raise ValueError('Verified unit-view implementation changed')
    for raw in registered:
        member = next(m for m in members if m['raw'] == raw['path'])
        view = raw.get('canonical_view')
        if not isinstance(view, dict):
            raise ValueError('Registered unit-view member missing')
        for key in ('member_manifest', 'member_manifest_sha256', 'view', 'view_sha256', 'rows',
                    'conservative_split_component', 'actual_reopened_audit'):
            if view.get(key) != member[key]:
                raise ValueError('Unit-view member differs from checked handoff')
        if member['raw_sha256'] != raw['sha256'] or member['rows'] != raw['rows']:
            raise ValueError('Unit-view original identity or count differs')
        manifest = checked_ref({'path': view['member_manifest'], 'sha256': view['member_manifest_sha256']})
        for key in ('current_sign_evidence', 'canonical_current_sign', 'canonical_units'):
            if view.get(key) != manifest[key]:
                raise ValueError('Unit-view current sign or units summary differs from checked manifest')
        if (manifest['complete'] is not True or manifest['source_id'] != source['source_id']
                or manifest['member_sha256'] != raw['sha256'] or manifest['row_count'] != raw['rows']
                or manifest['rows_dropped'] != 0 or manifest['timestamps_shifted'] != 0
                or manifest['archive_md5_status'] != 'UNKNOWN' or manifest['whole_archive_official_md5_verified'] is not False
                or manifest['physical_independence_status'] != 'UNKNOWN' or manifest['independent_physical_cells'] is not None
                or manifest['D01_complete'] is not False or manifest['D02_complete'] is not False
                or manifest['external_model_validation'] != 'not_performed'):
            raise ValueError('Unit-view scope or identity inflated')
        output = local(view['view']) / manifest['observations']
        if not output.resolve().is_relative_to(ROOT) or not output.is_file():
            raise ValueError('Controlled unit-view output missing')
        if sha(output) != view['view_sha256'] or manifest['observations_sha256'] != view['view_sha256']:
            raise ValueError('Unit-view output bytes changed')
        if member['actual_reopened_audit']['status'] != 'passed' or member['actual_reopened_audit']['rows_reopened_and_compared'] != raw['rows']:
            raise ValueError('Complete unit-view reopening required')


def preservation_paths():
    paths = set()
    for folder in [ROOT / "data/raw/public_independent", ROOT / "data/raw/public_new"]:
        paths.update(p for p in folder.rglob("*") if p.is_file())
    paths.update((ROOT / "data/manifests").glob("*.yaml"))
    for handoff_path in (OLD_HANDOFF, CVUT_HANDOFF):
        handoff = read(local(handoff_path))
        paths.add(local(handoff_path))
        for name in handoff.get("frozen_files_sha256", {}):
            if name.startswith(("data/", "artifacts/")):
                paths.add(local(name))
        for name in handoff.get("preserved_original_inputs_sha256", {}):
            if name.startswith(("data/", "artifacts/")):
                paths.add(local(name))
    paths.update([local(LATEST_HANDOFF)])
    latest = read(local(LATEST_HANDOFF))
    paths.add(local(latest["global_identity_audit"]))
    for name in ("source_identity_preregistration.json", "combined_original_members.json"):
        paths.add(local(LATEST_HANDOFF).parent / name)
    paths.update(local(p) for p in MEMBER_MANIFESTS)
    # Only the explicitly authorized central source index may change.
    return sorted(paths - {INDEX})


def preserved_hashes():
    return {relative(p): sha(p) for p in preservation_paths()}


def audit_csv(member):
    path = local(member["output_path"])
    bounds = {name: None for name in ("time", "current", "voltage", "temperature")}
    missing, rows, previous = {}, 0, None
    anomalies = {"sequence_errors": 0, "duplicate_time": 0, "regressed_time": 0,
                 "negative_voltage": 0, "zero_voltage": 0,
                 "voltage_below_author_protocol_cutoff_1p5V": 0,
                 "voltage_above_author_protocol_cutoff_3p9V": 0}
    sign = {"positive_current_charge_capacity_increases": 0, "negative_current_charge_capacity_increases": 0,
            "negative_current_discharge_capacity_increases": 0, "positive_current_discharge_capacity_increases": 0}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not set(EXACT.values()).issubset(reader.fieldnames):
            raise ValueError("Exact source headers missing")
        missing = {key: 0 for key in reader.fieldnames}
        for row in reader:
            rows += 1
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed original row")
            for key, value in row.items():
                missing[key] += value == ""
            values = {key: float(row[column]) for key, column in EXACT.items()}
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError("Nonfinite required original field")
            anomalies["sequence_errors"] += values["sequence"] != rows
            anomalies["negative_voltage"] += values["voltage"] < 0
            anomalies["zero_voltage"] += values["voltage"] == 0
            anomalies["voltage_below_author_protocol_cutoff_1p5V"] += values["voltage"] < 1.5
            anomalies["voltage_above_author_protocol_cutoff_3p9V"] += values["voltage"] > 3.9
            for name in bounds:
                value = values[name]
                bounds[name] = [value, value] if bounds[name] is None else [min(bounds[name][0], value), max(bounds[name][1], value)]
            if previous is not None:
                delta = values["time"] - previous["time"]
                anomalies["duplicate_time"] += delta == 0
                anomalies["regressed_time"] += delta < 0
                if values["step"] == previous["step"]:
                    dc = values["charge_capacity"] - previous["charge_capacity"]
                    dd = values["discharge_capacity"] - previous["discharge_capacity"]
                    if dc > 1e-8:
                        if values["current"] > .01:
                            sign["positive_current_charge_capacity_increases"] += 1
                        elif values["current"] < -.01:
                            sign["negative_current_charge_capacity_increases"] += 1
                    if dd > 1e-8:
                        if values["current"] < -.01:
                            sign["negative_current_discharge_capacity_increases"] += 1
                        elif values["current"] > .01:
                            sign["positive_current_discharge_capacity_increases"] += 1
            previous = values
    if rows != member["raw_row_count"]:
        raise ValueError("Raw row count changed")
    inferred_sign = "positive_charge" if (sign["positive_current_charge_capacity_increases"] > 0 and
                       sign["negative_current_discharge_capacity_increases"] > 0 and
                       sign["negative_current_charge_capacity_increases"] == sign["positive_current_discharge_capacity_increases"] == 0) else "UNKNOWN"
    return {"exact_columns": EXACT, "source_units": {"time": "s", "current": "A", "voltage": "V", "temperature": "degC"},
            "rows": rows, "bounds_in_original_units": bounds, "missing_by_column": missing,
            "anomalies": anomalies, "current_sign_evidence": sign, "vendor_current_sign_inferred": inferred_sign,
            "internal_current_conversion": "current_A = -vendor_current_A" if inferred_sign == "positive_charge" else None,
            "measured_temperature_channel": "Aux_Temperature_1 (C)",
            "source_filename_temperature_is_chamber_condition": True,
            "canonical_import_status": "not_performed", "no_rows_removed_or_fitted": True}


def member_crc_from_prefix(manifest, member):
    prefix = local(manifest["raw_prefix_path"])
    start, end = member["original_compressed_byte_range"]
    header_format = struct.Struct("<4s5H3I2H")
    with prefix.open("rb") as stream:
        stream.seek(member["local_header_byte_offset"])
        header = header_format.unpack(stream.read(header_format.size))
        sig, version, flags, method, clock, date, crc, compressed_size, size, filename_len, extra_len = header
        name = stream.read(filename_len).decode("utf-8" if flags & 0x800 else "cp437")
        if sig != b"PK\x03\x04" or flags & (1 | 8) or name != member["archive_member_name"]:
            raise ValueError("Unsupported or mismatching complete local ZIP header")
        if member["local_header_byte_offset"] + header_format.size + filename_len + extra_len != start:
            raise ValueError("Original compressed start mismatch")
        if start + compressed_size - 1 != end or end >= prefix.stat().st_size:
            raise ValueError("Incomplete compressed member or original range mismatch")
        stream.seek(start)
        compressed = stream.read(compressed_size)
    if method == 8:
        decompressor = zlib.decompressobj(-15)
        data = decompressor.decompress(compressed, size + 1)
        if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
            raise ValueError("Incomplete exact deflate stream")
    elif method == 0:
        data = compressed
    else:
        raise ValueError("Unsupported compression")
    if len(data) != size or size != member["original_size_bytes"] or crc != int(member["local_header_crc32"], 16):
        raise ValueError("Original complete member size/CRC header mismatch")
    if zlib.crc32(data) & 0xffffffff != crc:
        raise ValueError("Full member CRC failure")
    digest = hashlib.sha256(data).hexdigest()
    if digest != member["member_sha256"] or sha(local(member["output_path"])) != digest:
        raise ValueError("Full original decompression differs from retained raw member")
    return format(crc, "08x")


def audit(out):
    out.mkdir(parents=True, exist_ok=False)
    original_bytes = INDEX.read_bytes()
    (out / "sources.before.yaml").write_bytes(original_bytes)
    before = preserved_hashes()
    old_handoff, latest, cvut = read(local(OLD_HANDOFF)), read(local(LATEST_HANDOFF)), read(local(CVUT_HANDOFF))
    if sha(local(OLD_HANDOFF)) != latest["old_frozen_delivery_sha256_before"] or latest["old_frozen_delivery_sha256_before"] != latest["old_frozen_delivery_sha256_after"]:
        raise ValueError("Older frozen handoff changed")
    previous_fields = read(local(latest["global_identity_audit"]))
    if sha(local(latest["global_identity_audit"])) != latest["global_identity_audit_sha256"]:
        raise ValueError("Latest frozen field audit changed")
    metadata_path = local(old_handoff["license_evidence_path"])
    metadata = read(metadata_path)
    if sha(metadata_path) != old_handoff["license_evidence_sha256"] or metadata["metadata"]["license"]["id"] != "cc-by-4.0":
        raise ValueError("Stored official license mismatch")
    archives, members, actual_audits = [], [], []
    for manifest_path in MEMBER_MANIFESTS:
        manifest = read(local(manifest_path))
        prefix = local(manifest["raw_prefix_path"])
        if sha(prefix) != manifest["raw_prefix_sha256_before"] or manifest["raw_prefix_sha256_before"] != manifest["raw_prefix_sha256_after"]:
            raise ValueError("Original official prefix changed")
        official_file = next(item for item in metadata["files"] if item["checksum"] == "md5:" + manifest["official_archive_md5"])
        if official_file["size"] != manifest["official_archive_size"] or prefix.stat().st_size >= official_file["size"]:
            raise ValueError("Official archive metadata or incomplete size mismatch")
        archives.append({"official_name": official_file["key"], "official_size_bytes": official_file["size"],
                         "official_md5": manifest["official_archive_md5"], "archive_md5_status": "UNKNOWN",
                         "whole_archive_official_md5_verified": False, "retained_prefix": file_ref(prefix),
                         "retained_prefix_bytes": prefix.stat().st_size, "member_manifest": file_ref(manifest_path),
                         "unavailable_next_member": manifest["unavailable_final_member"]})
        for member in manifest["members"]:
            crc = member_crc_from_prefix(manifest, member)
            field = audit_csv(member)
            previous = next(a for a in previous_fields["audits"] if a["member"] == local(member["output_path"]).name)
            for name, value in (("rows", field["rows"]), ("bounds_in_original_units", field["bounds_in_original_units"]),
                                ("current_sign_evidence", field["current_sign_evidence"]),
                                ("negative_voltage_record_count", field["anomalies"]["negative_voltage"]),
                                ("duplicate_global_time_count", field["anomalies"]["duplicate_time"]),
                                ("regressed_global_time_count", field["anomalies"]["regressed_time"])):
                if previous[name] != value:
                    raise ValueError("Latest prior full-field audit does not reproduce: " + name)
            item = {"name": local(member["output_path"]).name, "path": relative(member["output_path"]),
                    "archive_member_name": member["archive_member_name"], "sha256": member["member_sha256"],
                    "bytes": member["original_size_bytes"], "crc32": crc, "crc_status": "complete_member_crc_verified",
                    "rows": field["rows"], "author_group": member["physical_group_id"],
                    "author_battery_number": member["author_battery_number"],
                    "manufacturer_serial_id": None, "physical_independence_status": "UNKNOWN",
                    "source_protocol": "Driving_cycle" if member["archive_member_name"].startswith("2_") else "Pulse",
                    "source_temperature_condition_degC": member["source_temperature_condition_degC"], "field_audit": field}
            members.append(item)
            actual_audits.append({"member": item["name"], "sha256": item["sha256"], **field})
            print(json.dumps({"member": item["name"], "rows": item["rows"], "CRC": crc,
                              "negative_voltage": field["anomalies"]["negative_voltage"]}), flush=True)
    components, duplicates = components_for_members(members)
    if components != sorted(latest["conservative_cross_split_components"]) or duplicates != previous_fields["byte_identical_duplicates"]:
        raise ValueError("Frozen cross-member leakage components do not reproduce")
    source = {"source_id": "zenodo13836819_sodium_soc_original_members", "kind": "public_measurement",
              "url": "https://zenodo.org/records/13836819", "doi": "10.5281/zenodo.13836819",
              "chemistry_id": "public_zenodo13836819_sodium_3p2Ah_10Ah_author_groups_unconfirmed",
              "provenance_type": "public_measurement", "read_status": "stored_official_metadata_and_full_members_locally_reaudited",
              "read_on": dt.datetime.now(dt.timezone.utc).date().isoformat(), "read_origin": "stored_official_metadata_and_preserved_original_zip_prefixes",
              "download_status": "partial_archives_complete_members_recovered", "checksum": None,
              "verification_status": "complete_member_crc_verified", "license": "CC-BY-4.0", "license_id": "CC-BY-4.0",
              "license_evidence_path": relative(metadata_path), "license_evidence_sha256": sha(metadata_path),
              "author_metadata": file_ref(metadata_path), "archives": archives, "raw_members": members,
              "raw_member_count": len(members), "unique_content_count": len({m["sha256"] for m in members}),
              "raw_rows_including_duplicate": sum(m["rows"] for m in members),
              "author_declared_group_count": len({m["author_group"] for m in members}),
              "content_duplicates": duplicates, "conservative_split_components": components,
              "conservative_split_component_count": len(components), "independent_physical_groups": None,
              "physical_independence_status": "UNKNOWN", "canonical_import_status": "not_performed",
              "split_assignment_status": "not_assigned", "frozen_split": None, "model_fit_status": "not_performed",
              "external_model_validation": "not_performed", "D01_complete": False, "D02_complete": False,
              "frozen_handoffs": {"original_six_members": file_ref(OLD_HANDOFF), "latest_seven_member_cohort": file_ref(LATEST_HANDOFF),
                                   "latest_all_row_field_and_identity_audit": file_ref(latest["global_identity_audit"])},
              "local_reaudit": {"path": relative(out / "audit.json"), "status": "full_original_member_crc_sha_and_all_rows_reproduced"},
              "supports": ["Seven complete original licensed raw CSV members with local byte SHA and full member CRC",
                           "Exact field units, measured temperature, and capacity-increment current-sign evidence",
                           "Cross-author-ID byte duplicates joined into conservative split components"],
              "limitations": ["Complete local members do not verify the official whole ZIP archive MD5; both archives remain UNKNOWN.",
                              "Three author battery IDs are labels; physical serials and batch independence remain unknown. Two split components are leakage constraints, not confirmed independent cells.",
                              "Raw negative/outlying voltages and missing optional fields are preserved. Protocol cutoffs identify anomalies, not universal sodium safety limits.",
                              "Canonical importer acceptance, fixed train/validation/test roles, model fitting and external scoring have not been performed.",
                              "No long-term aging, RUL, validated incident population, revenue superiority, or calibrated operating risk claim.",
                              "Frozen CVUT 64-row holdout and prior six-member delivery remain unchanged; no new network request.",
                              "Prior seven-member identity audit retained a stale six-member limitation; actual member count is seven and this separate audit corrects only the central index."]}
    validate_new_source(source)
    proposal = read(INDEX)
    if any(s["source_id"] == source["source_id"] for s in proposal["sources"]):
        raise ValueError("Source already registered; do not duplicate integration")
    proposal["state_definitions"]["complete_member_crc_verified"] = "Complete locally retained original ZIP members have size/CRC/SHA and field audits; whole archive MD5 and physical independence remain unknown; not canonical importer or model validation"
    existing = next(s for s in proposal["sources"] if s["source_id"] == cvut["source_id"])
    existing["active_views"].append({"view": "complete_event_order_v3", "registry_path": cvut["registry_path"],
        "registry_sha256": cvut["registry_sha256"], "spec_path": cvut["spec_path"], "spec_sha256": cvut["spec_sha256"],
        "csv_path": "artifacts/data/public_new/cvut_sodium_0001_complete.csv", "csv_sha256": cvut["csv_bytes_unchanged_sha256"],
        "source_id": cvut["source_id"], "physical_group_id": cvut["physical_group_id"], "batch_id": cvut["batch_id"],
        "field_compatibility": "complete_original_event_order_import_passed_64_rows", "complete_instrument_semantics_accepted": True,
        "actual_import_exit_code": 0, "records_persisted": 64, "records_dropped": 0, "timestamps_shifted": 0,
        "command_record": cvut["actual_commands"]["actual_full_v3_cli_import"]["command_record"],
        "command_record_sha256": sha(local(cvut["actual_commands"]["actual_full_v3_cli_import"]["command_record"]))})
    existing["frozen_split_v3"] = {**copy.deepcopy(cvut["new_frozen_holdout"]), "holdout_only": True,
                                     "same_physical_pack_as_v2": True, "does_not_add_independent_groups": True}
    existing["ordered_v3_frozen_handoff"] = file_ref(CVUT_HANDOFF)
    existing["D01_complete"] = False
    existing["D02_complete"] = False
    existing["limitations"][0] = "Legacy v2 strict chronology failure remains preserved. Explicit instrument_event_order v3 accepted all 64 rows with unchanged timestamps and documented co-timed transitions; this is the same physical pack and not additional independent data."
    existing["supports"].append("Explicit original instrument event order v3 persists all 64 rows and documented co-timed step boundaries")
    proposal["sources"].append(source)
    proposal["model_identities"].append({"model_kind": "public_data_case", "chemistry_id": source["chemistry_id"],
        "parameter_source_id": source["source_id"], "status": "complete_raw_members_not_imported_or_calibrated",
        "external_model_validation": "not_performed"})
    for name, expected in cvut["frozen_files_sha256"].items():
        if name.startswith(("data/", "artifacts/")) and sha(local(name)) != expected:
            raise ValueError("CVUT frozen delivery evidence changed: " + name)
    after = preserved_hashes()
    if before != after or INDEX.read_bytes() != original_bytes:
        raise ValueError("Preserved inputs changed during read-only audit")
    write(out / "sources.proposed.yaml", proposal)
    result = {"schema_version": 1, "status": "local_raw_source_integration_audit_passed_scientific_import_pending",
              "original_index_sha256": hashlib.sha256(original_bytes).hexdigest(), "proposed_index_sha256": sha(out / "sources.proposed.yaml"),
              "script_sha256": sha(Path(__file__)), "all_row_audits": actual_audits,
              "raw_members": len(members), "unique_contents": source["unique_content_count"],
              "rows_including_duplicates": source["raw_rows_including_duplicate"], "components": components,
              "content_duplicates": duplicates, "confirmed_independent_physical_cells": None,
              "archive_md5_status": "UNKNOWN", "D01_complete": False, "D02_complete": False,
              "network_requests": 0, "model_fits": 0, "holdout_used_for_fitting": False,
              "preserved_input_hashes_before": before, "preserved_input_hashes_after": after,
              "old_views_and_frozen_splits_preserved": True, "latest_frozen_handoff": file_ref(LATEST_HANDOFF),
              "CVUT_v3_same_pack_64_records": True}
    write(out / "audit.json", result)
    print(json.dumps({"audit": relative(out / "audit.json"), "proposal": relative(out / "sources.proposed.yaml"),
                      "raw_members": len(members), "unique_contents": source["unique_content_count"],
                      "conservative_components": len(components), "index_original_sha256": result["original_index_sha256"]}))


def assert_preserved_registered_unit_views(current_index, proposed_index):
    """Reject a raw-only proposal that drops accepted views/history.

    Initial registration remains possible. A reviewed view replacement needs
    its own explicit migration, rather than being part of a raw byte re-audit.
    """
    protected = [source for source in current_index['sources']
                 if source.get('canonical_import_status') == 'seven_complete_member_unit_views_reopened']
    for old in protected:
        matching = [source for source in proposed_index['sources'] if source['source_id'] == old['source_id']]
        if len(matching) != 1:
            raise ValueError('Previously reviewed source must remain registered exactly once')
        new = matching[0]
        for key in ('canonical_import_status', 'canonical_view_acceptance'):
            if new.get(key) != old.get(key):
                raise ValueError('Previously reviewed canonical acceptance cannot be removed or replaced by raw apply')
        old_members = {member['path']: member for member in old['raw_members']}
        new_members = {member['path']: member for member in new['raw_members']}
        if len(new_members) != len(new['raw_members']) or not old_members.keys() <= new_members.keys():
            raise ValueError('Previously reviewed member identity cannot disappear or become ambiguous')
        for path, member in old_members.items():
            for key in ('canonical_view', 'field_audit'):
                if new_members[path].get(key) != member.get(key):
                    raise ValueError('Previously reviewed member view or historical sign audit cannot be removed or replaced by raw apply')
    if protected:
        key = 'complete_member_crc_verified'
        if proposed_index.get('state_definitions', {}).get(key) != current_index.get('state_definitions', {}).get(key):
            raise ValueError('Reviewed byte-state and canonical acceptance scope definition must remain explicit')


def apply(out, expected):
    audit_record = read(out / "audit.json")
    if sha(INDEX) != expected or expected != audit_record["original_index_sha256"]:
        raise ValueError("Central index changed after audit; coordinate and re-audit")
    if sha(out / "sources.proposed.yaml") != audit_record["proposed_index_sha256"]:
        raise ValueError("Audited source proposal changed")
    if preserved_hashes() != audit_record["preserved_input_hashes_before"]:
        raise ValueError("Original source/holdout/failed evidence changed")
    proposal = read(out / "sources.proposed.yaml")
    assert_preserved_registered_unit_views(read(INDEX), proposal)
    validate_new_source(next(s for s in proposal["sources"] if s["source_id"] == "zenodo13836819_sodium_soc_original_members"))
    with (out / "sources.backup-before-apply.yaml").open("xb") as backup:
        backup.write(INDEX.read_bytes())
    staged = out / "sources.atomic-stage.yaml"
    with staged.open("xb") as stream:
        stream.write((out / "sources.proposed.yaml").read_bytes())
    os.replace(staged, INDEX)
    write(out / "apply.json", {"old_index_sha256": expected, "new_index_sha256": sha(INDEX),
                               "backup": file_ref(out / "sources.backup-before-apply.yaml"),
                               "preserved_inputs_unchanged": preserved_hashes() == audit_record["preserved_input_hashes_before"]})
    print(json.dumps({"central_index_updated": relative(INDEX), "sha256": sha(INDEX), "backup": relative(out / "sources.backup-before-apply.yaml")}))


def verify(out):
    record = read(out / "audit.json")
    index = read(INDEX)
    source = next(s for s in index["sources"] if s["source_id"] == "zenodo13836819_sodium_soc_original_members")
    validate_new_source(source)
    if sha(INDEX) != record["proposed_index_sha256"] or preserved_hashes() != record["preserved_input_hashes_before"]:
        raise ValueError("Applied index or immutable input no longer matches audited bytes")
    old = read(out / "sources.before.yaml")
    cvut = next(s for s in index["sources"] if s["source_id"] == "zenodo17459188_cvut_sib_0001")
    old_cvut = next(s for s in old["sources"] if s["source_id"] == cvut["source_id"])
    if cvut["active_views"][:len(old_cvut["active_views"])] != old_cvut["active_views"] or cvut["frozen_split"] != old_cvut["frozen_split"]:
        raise ValueError("Prior CVUT views or frozen holdout were altered")
    for original in old["sources"]:
        if original["source_id"] == cvut["source_id"]:
            continue
        if original != next(s for s in index["sources"] if s["source_id"] == original["source_id"]):
            raise ValueError("Unrelated original source changed")
    write(out / "verify.json", {"status": "passed", "index_sha256": sha(INDEX), "audit_sha256": sha(out / "audit.json"),
                                "raw_holdout_prior_failures_and_handoffs_unchanged": True, "source_count": len(index["sources"]),
                                "raw_members": source["raw_member_count"], "unique_contents": source["unique_content_count"],
                                "conservative_components": source["conservative_split_component_count"],
                                "confirmed_independent_physical_cells": None, "whole_archive_md5_status": "UNKNOWN",
                                "D01_complete": False, "D02_complete": False, "network_requests": 0, "model_fits": 0})
    print(json.dumps({"status": "passed", "verify": relative(out / "verify.json"), "sha256": sha(INDEX)}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["audit", "apply", "verify"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--expected-index-sha256")
    args = parser.parse_args()
    out = local(args.out)
    if out.parent != ROOT / "artifacts/review" or not out.name.startswith("data-integration-"):
        raise ValueError("Controlled data-integration review output required")
    if args.action == "audit":
        audit(out)
    elif args.action == "apply":
        apply(out, args.expected_index_sha256)
    else:
        verify(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
