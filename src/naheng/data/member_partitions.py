"""Immutable complete-member partitions, with provenance rather than IID claims.

The selected policy is a metadata transfer benchmark. It does not calibrate a
model, certify physical cell identity, or split adjacent rows into roles.
"""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re

from .zenodo_csv import SourceEvidenceError, load_zenodo_member_specs

ROLES = ("train", "validation", "test")
UNITS = {"time": "s", "current": "A", "voltage": "V", "temperature": "K"}
# This entry point accepts the reviewed eight-member revision. A different
# source revision needs its own acceptance, rather than caller-authored receipts.
REGISTERED_COHORT_ANCHORS = {
    "data/manifests/sources.yaml": "b41c746c7514aabb28e443cf78a63c7137fc5a5025856fc7b949aab62a37740f",
    "data/manifests/additional-unit-view-bat1-20261013-a.json": "904d14e82e2e71f80a661ac82616e7f2db164a71243613709eb69979f624ac21",
    "data/manifests/pending-zenodo13836819-bat1-20261013-a.json": "152bd5748eef8838e5198ba3446bf050d813a13f37b7b104ab2dfaecfbc11b44",
    "artifacts/data/public_independent/zenodo13836819-670b8554/metadata.json.attempt1": "d735c17824b8f547d5cf608aeed678d937ec1dfec7a91c38e132d6778e3e8706",
    "artifacts/data/public_new/holdout_only_snapshot_v2.json": "93f7f123d64e7714d6997bd154caba1307c144d8b6498e4335f44aa3d918ae03",
    "artifacts/data/public_new/ordered-holdout-v3-fa6715bc.json": "a764a9b6711940e846fd6e29ce5d67328775fc9d95899cfe45f06550608a7716",
}
FIRST_FROZEN_POLICY = {
    "catalog_sha256": "974c6879675465e97085635fdb77f2acedb0dbe714632a4433af4f4a5c86628a",
    "policy_sha256": "de3c1fcc4633097f4013378e5ed6f8566201b4581993f1b00f625d87d5f1a566",
    "cohort_id": "zenodo13836819_eight_complete_member_provenance_candidate",
}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _path(root, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise SourceEvidenceError("A relative project path is required")
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise SourceEvidenceError("Path leaves the project")
    return path


def _json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _ref(root, ref, seen):
    if not isinstance(ref, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256", ""))):
        raise SourceEvidenceError("Missing exact SHA256 reference")
    path = _path(root, ref.get("path"))
    previous = seen.setdefault(path, ref["sha256"])
    if previous != ref["sha256"] or sha256(path) != ref["sha256"]:
        raise SourceEvidenceError("Referenced input changed or has conflicting hashes")
    return path


def _require_registered_anchors(root, protected_refs, seen):
    provided = {_path(root, ref["path"]): ref["sha256"] for ref in protected_refs}
    if provided != {_path(root, name): digest for name, digest in REGISTERED_COHORT_ANCHORS.items()}:
        raise SourceEvidenceError("This cohort requires the registered accepted source revision and legacy locks")
    for ref in protected_refs:
        _ref(root, ref, seen)


def _require_first_frozen_policy(catalog_ref, policy_ref, catalog):
    if (catalog_ref["sha256"] != FIRST_FROZEN_POLICY["catalog_sha256"] or
            policy_ref["sha256"] != FIRST_FROZEN_POLICY["policy_sha256"] or
            catalog.get("cohort_id") != FIRST_FROZEN_POLICY["cohort_id"]):
        raise SourceEvidenceError("This cohort's first frozen policy is locked across output paths; no test-to-train reassignment")


def provenance_components(members, view_components):
    """Take the transitive closure of author, content and existing component edges."""
    if not members or len({m["member_id"] for m in members}) != len(members):
        raise SourceEvidenceError("Nonempty unique member IDs required")
    parents = list(range(len(members)))

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    edges = {}
    for i, member in enumerate(members):
        if not member.get("source_id") or not member.get("author_group"):
            raise SourceEvidenceError("Source-qualified author identity required")
        keys = (("author", member["source_id"], member["author_group"]),
                ("raw", member["raw"]["sha256"]),
                ("existing_component", member["source_id"], view_components[member["member_id"]]))
        for key in keys:
            if key in edges:
                parents[find(i)] = find(edges[key])
            else:
                edges[key] = i
    groups = {}
    for i, member in enumerate(members):
        groups.setdefault(find(i), []).append(member)
    result = []
    for group in groups.values():
        authors = sorted({m["author_group"] for m in group})
        sources = sorted({m["source_id"] for m in group})
        # Retain the existing single-source component identity; namespace mixed sources.
        identity = authors if len(sources) == 1 else sorted({(m["source_id"], m["author_group"]) for m in group})
        prefix = "zenodo13836819_component_" if sources == ["zenodo13836819_sodium_soc_original_members"] else "provenance_component_"
        component_id = prefix + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16]
        result.append({"component_id": component_id, "author_groups": authors,
                       "source_ids": sources, "member_ids": sorted(m["member_id"] for m in group)})
    if len({c["component_id"] for c in result}) != len(result):
        raise SourceEvidenceError("Component identity collision")
    return sorted(result, key=lambda c: c["component_id"])


def assign_roles(components, policy):
    mapping = policy.get("explicit_candidate_roles")
    if not isinstance(mapping, dict) or set(mapping) != set(ROLES):
        raise SourceEvidenceError("Explicit train, validation and test components required")
    if (policy.get("random_time_point_shuffle") is not False or
            policy.get("three_nonempty_roles_required") is not True or
            policy.get("legacy_holdout_roles_locked") is not True):
        raise SourceEvidenceError("Complete groups and locked legacy holdouts required")
    if len(set(mapping.values())) != 3 or set(mapping.values()) != {c["component_id"] for c in components}:
        raise SourceEvidenceError("Three distinct nonempty complete components required; no splitting or omission")
    return {component: role for role, component in mapping.items()}


def _accepted_views(root, catalog, seen):
    """Bind data bytes to the registered, actually executed acceptance chain."""
    evidence = {_path(root, ref["path"]): ref["sha256"] for ref in catalog.get("evidence_refs", [])}

    def accepted(ref):
        path = _path(root, ref["path"])
        if evidence.get(path) != ref["sha256"]:
            raise SourceEvidenceError("Required registered acceptance is missing from catalog")
        return _json(_ref(root, ref, seen))

    def command(ref, actual_argv):
        value = accepted(ref)
        if (value.get("exit_code") != 0 or value.get("timed_out", False) or
                value.get("status", "completed") != "completed" or
                Path(value.get("cwd", "")).resolve() != root or value.get("argv", [])[1:] != actual_argv[1:]):
            raise SourceEvidenceError("Actual public command is not bound to the accepted invocation")
        return value

    central = _json(root / "data/manifests/sources.yaml")
    legacy = next(s for s in central["sources"] if s["source_id"] == "zenodo17459188_cvut_sib_0001")
    protected = {_path(root, ref["path"]): ref["sha256"] for ref in catalog["protected_refs"]}
    for lock_name in ("frozen_split", "frozen_split_v3"):
        lock = legacy[lock_name]
        if protected.get(_path(root, lock["path"])) != lock["sha256"]:
            raise SourceEvidenceError("Legacy holdout must retain its originally registered hash")
        _ref(root, lock, seen)
    source = next(s for s in central["sources"] if s["source_id"] == "zenodo13836819_sodium_soc_original_members")
    anchors = source["canonical_view_acceptance"]
    handoff, review = accepted(anchors["normal_entry_handoff"]), accepted(anchors["independent_review"])
    if (review.get("exit_code") != 0 or review.get("failed_count") != 0 or
            review.get("independent_of_writer_and_validator_author") is not True or
            handoff["public_files_sha256"] != review["public_baseline_sha256"]):
        raise SourceEvidenceError("Original member independent acceptance failed or differs")
    for name, digest in handoff["public_files_sha256"].items():
        if catalog["public_source_hashes"].get(name) != digest:
            raise SourceEvidenceError("Accepted importer source differs from catalog")
        _ref(root, {"path": name, "sha256": digest}, seen)
    # Historical registry was frozen before canonical-view registration. Compare
    # original member identities, rather than pretending its hash equals today's index.
    historical = review["frozen_review_input_copies"]["data/manifests/sources.yaml"]
    old_registry = _json(_ref(root, {"path": historical["saved_copy"], "sha256": historical["sha256"]}, seen))
    old_source = next(s for s in old_registry["sources"] if s["source_id"] == source["source_id"])
    identity = lambda s: sorted((m["path"], m["sha256"], m["crc32"], m["rows"], m["author_group"]) for m in s["raw_members"])
    if historical["sha256"] != handoff["source_registry_sha256"] or identity(old_source) != identity(source):
        raise SourceEvidenceError("Historical accepted source is not the current original cohort")
    author_members = {_path(root, m["raw"]): m for m in handoff["members"]}
    reviewed_members = {_path(root, m["raw"]): m for m in review["members"]}
    batches = {}
    covered = []
    for b in handoff["batch_records"]:
        path = _ref(root, {"path": b["manifest"], "sha256": b["sha256"]}, seen)
        batch = _json(path)
        matching = [c for c in handoff["command_records"] if "--out" in c["argv"] and
                    _path(root, c["argv"][c["argv"].index("--out") + 1]) == path.parent]
        if len(matching) != 1:
            raise SourceEvidenceError("Accepted batch requires exactly one actual command")
        command(matching[0], batch["actual_argv"])
        if not any(_path(root, c["path"] + "/command.json") == _path(root, matching[0]["path"]) and
                   c["sha256"] == matching[0]["sha256"] and c["exit_code"] == 0 for c in review["actual_command_records"]):
            raise SourceEvidenceError("Actual public command was not independently reviewed")
        if (batch["exit_code"] != 0 or batch["module_sha256"] != catalog["public_source_hashes"]["src/naheng/data/zenodo_csv.py"] or
                batch["tool_sha256"] != catalog["public_source_hashes"]["tools/validate_zenodo_csv.py"] or
                batch["actual_argv"][1] != "tools/validate_zenodo_csv.py"):
            raise SourceEvidenceError("Batch acceptance belongs to another importer")
        covered.extend(batch["selected_cohort_member_indices"])
        for m in batch["member_results"]:
            key = Path(m["manifest"]["raw_path"]).resolve()
            if key in batches:
                raise SourceEvidenceError("Accepted batches overlap")
            batches[key] = m
        if not any(_path(root, b2["path"]) == path.parent and b2["sha256"] == b["sha256"] for b2 in review["batches"]):
            raise SourceEvidenceError("Batch is absent from independent review")
    if sorted(covered) != list(range(1, len(source["raw_members"]) + 1)):
        raise SourceEvidenceError("Actual batches must cover original member indices once")
    accepted_map = {}
    for raw_member in source["raw_members"]:
        raw_path = _path(root, raw_member["path"])
        a, r, b = author_members[raw_path], reviewed_members[raw_path], batches[raw_path]
        canonical = raw_member["canonical_view"]
        manifest_ref = {"path": canonical["member_manifest"], "sha256": canonical["member_manifest_sha256"]}
        view_path = _ref(root, manifest_ref, seen)
        observations_ref = {"path": (view_path.parent / "observations.jsonl.gz").relative_to(root).as_posix(),
                            "sha256": canonical["view_sha256"]}
        _ref(root, observations_ref, seen)
        if (a["raw_sha256"] != raw_member["sha256"] or r["raw_identity"]["sha256"] != raw_member["sha256"] or
                a["member_manifest_sha256"] != manifest_ref["sha256"] or r["manifest_sha256"] != manifest_ref["sha256"] or
                _path(root, a["member_manifest"]) != view_path or
                a["view_sha256"] != observations_ref["sha256"] or r["output_identity"]["sha256"] != observations_ref["sha256"] or
                a["rows"] != raw_member["rows"] or r["independent_output_line_count"] != raw_member["rows"] or
                a["actual_reopened_audit"]["rows_reopened_and_compared"] != raw_member["rows"] or
                a["actual_reopened_audit"]["status"] != "passed" or b["manifest"] != _json(view_path)):
            raise SourceEvidenceError("Raw, canonical view, actual output and independent member review disagree")
        accepted_map[raw_path] = (view_path, manifest_ref["sha256"], _path(root, observations_ref["path"]), observations_ref["sha256"])
    supplements = [ref for ref in catalog["protected_refs"] if ref["path"].replace("\\", "/").startswith("data/manifests/additional-unit-view-")]
    if len(supplements) != 1:
        raise SourceEvidenceError("Supplementary registered acceptance required")
    supplemental = _json(_ref(root, supplements[0], seen))
    public = accepted(supplemental["public_entry_acceptance"])
    independent = accepted(supplemental["independent_unitview_review"])
    public_review = accepted(supplemental["independent_public_identity_review"])
    command(supplemental["public_entry_command"], public["actual_argv"])
    reviewer_command = accepted(supplemental["independent_public_review_command"])
    if (reviewer_command["exit_code"] != 0 or public_review["exit_code"] != 0 or independent["exit_code"] != 0 or
            not public_review["checks"] or any(c["status"] != "passed" for c in public_review["checks"]) or
            not independent["checks"] or any(c["status"] != "passed" for c in independent["checks"]) or
            independent["failed"] or public["exit_code"] != 0 or public["inputs_unchanged"] is not True or
            reviewer_command.get("status", "completed") != "completed" or reviewer_command.get("timed_out", False) or
            reviewer_command["argv"][1:] != public_review["actual_argv"][1:] or
            Path(reviewer_command["cwd"]).resolve() != root):
        raise SourceEvidenceError("Supplementary actual and independent acceptances did not pass")
    if public["actual_argv"][1] != "tools/validate_additional_zenodo_csv.py":
        raise SourceEvidenceError("Supplementary public command belongs to another entry")
    if (public["candidate_cli_sha256"] != catalog["public_source_hashes"]["tools/validate_additional_zenodo_csv.py"] or
            independent["candidate_cli_sha256"] != public["candidate_cli_sha256"] or
            public["public_baseline_hashes"] != handoff["public_files_sha256"] or
            Path(public_review["public_receipt"]).resolve() != _path(root, supplemental["public_entry_command"]["path"])):
        raise SourceEvidenceError("Supplementary source/public identity linkage differs")
    raw = supplemental["raw_member"]
    mv, obs = supplemental["member_view"], supplemental["observations"]
    view_path, obs_path = _ref(root, mv, seen), _ref(root, obs, seen)
    if (Path(public["new_raw"]["path"]).resolve() != _path(root, raw["path"]) or
            public["new_raw"]["sha256"] != raw["sha256"] or independent["member_raw_sha256"] != raw["sha256"] or
            public["view"]["manifest_sha256"] != mv["sha256"] or public["member_manifest"] != _json(view_path) or
            public["view"]["observations_sha256"] != obs["sha256"] or independent["norm_gzip_sha256"] != obs["sha256"] or
            public["reopened_audit"]["rows_reopened_and_compared"] != raw["actual_full_source_rows"] or
            independent["norm_gzip_full_rows_read"] != raw["actual_full_source_rows"]):
        raise SourceEvidenceError("Supplementary full view is not the independently accepted output")
    for key in ("public_entry_acceptance", "public_entry_command", "independent_unitview_review"):
        ref = supplemental[key]
        bound = [digest for name, digest in public_review["evidence_hashes"].items()
                 if Path(name).resolve() == _path(root, ref["path"])]
        if bound != [ref["sha256"]]:
            raise SourceEvidenceError("Independent public identity review is not bound to the actual chain")
    expected_pairs = {"canonical": obs, "all26_original_strings": supplemental["all26_original_strings"]}
    if {p["name"] for p in public_review["output_pairs"]} != set(expected_pairs) or len(public_review["output_pairs"]) != 2:
        raise SourceEvidenceError("Both actual compressed-output identity pairs required")
    for pair in public_review["output_pairs"]:
        expected = expected_pairs[pair["name"]]
        if Path(pair["public"]).resolve() != _path(root, expected["path"]) or pair["sha256"] != expected["sha256"]:
            raise SourceEvidenceError("Public output identity pair differs from the registered view")
        _ref(root, expected, seen)
        stage = Path(pair["stage"]).resolve()
        if not stage.is_relative_to(root):
            raise SourceEvidenceError("Stage identity source leaves project")
        _ref(root, {"path": stage.relative_to(root).as_posix(), "sha256": expected["sha256"]}, seen)
    accepted_map[_path(root, raw["path"])] = (view_path, mv["sha256"], obs_path, obs["sha256"])
    return accepted_map


def _load_inputs(root, catalog_ref, policy_ref):
    seen = {}
    catalog = _json(_ref(root, catalog_ref, seen))
    policy = _json(_ref(root, policy_ref, seen))
    _require_first_frozen_policy(catalog_ref, policy_ref, catalog)
    if catalog.get("schema_version") != 1 or policy.get("schema_version") != 1:
        raise SourceEvidenceError("Unsupported input schema")
    if policy.get("catalog_sha256") != catalog_ref["sha256"]:
        raise SourceEvidenceError("Policy is not bound to this catalog")
    protected = catalog.get("protected_refs", [])
    _require_registered_anchors(root, protected, seen)
    for ref in protected + catalog.get("evidence_refs", []):
        path = _ref(root, ref, seen)
        if path.name == "command.json" and _json(path).get("exit_code") != 0:
            raise SourceEvidenceError("A referenced completed command did not pass")
    protected_paths = {ref["path"].replace("\\", "/") for ref in protected}
    required_locks = {"data/manifests/sources.yaml", "artifacts/data/public_new/holdout_only_snapshot_v2.json",
                      "artifacts/data/public_new/ordered-holdout-v3-fa6715bc.json"}
    if not required_locks <= protected_paths:
        raise SourceEvidenceError("Original source and both legacy holdout locks required")
    registries = [ref["path"] for ref in protected if ref["path"] == "data/manifests/sources.yaml" or
                  ref["path"].replace("\\", "/").startswith("data/manifests/pending-zenodo")]
    if len(registries) != 2:
        raise SourceEvidenceError("Original and supplementary complete-member sources required")
    specs = [spec for registry in registries for spec in load_zenodo_member_specs(root, registry)]
    spec_map = {(spec.source_id, spec.archive_member_name): spec for spec in specs}
    if len(spec_map) != len(specs):
        raise SourceEvidenceError("Duplicate registry member identity")
    source_hashes = catalog.get("public_source_hashes", {})
    if not source_hashes or not {"src/naheng/data/zenodo_csv.py", "tools/validate_zenodo_csv.py",
                                "tools/validate_additional_zenodo_csv.py"} <= set(source_hashes):
        raise SourceEvidenceError("Reviewed public importer identities required")
    for path, digest in source_hashes.items():
        _ref(root, {"path": path, "sha256": digest}, seen)
    accepted_map = _accepted_views(root, catalog, seen)
    members, views, found = catalog.get("members", []), {}, set()
    for member in members:
        raw = _ref(root, member["raw"], seen)
        manifest_path = _ref(root, member["view_manifest"], seen)
        observations = _ref(root, member["observations"], seen)
        if accepted_map.get(raw) != (manifest_path, member["view_manifest"]["sha256"], observations, member["observations"]["sha256"]):
            raise SourceEvidenceError("Catalog view lacks registered actual/independent acceptance")
        view = _json(manifest_path)
        key = (member["source_id"], view.get("archive_member_name"))
        spec = spec_map.get(key)
        if spec is None or key in found:
            raise SourceEvidenceError("Member omitted from, or duplicated against, licensed source registry")
        found.add(key)
        if (raw != spec.member_path.resolve() or member["raw"]["sha256"] != spec.member_sha256 or
                member["member_id"] != spec.source_id + ":" + spec.archive_member_name or
                member["author_group"] != spec.author_group or member["row_count"] != spec.expected_rows):
            raise SourceEvidenceError("Catalog differs from original licensed member")
        expected_protocol = "Driving_cycle" if spec.member_path.name.startswith("Driving_cycle_") else "Pulse"
        expected_capacity = 3.2 if spec.author_battery_number in (1, 2, 5) else 10.0
        if member.get("protocol") != expected_protocol or member.get("nominal_capacity_Ah") != expected_capacity:
            raise SourceEvidenceError("Authored capacity family or protocol differs")
        if (type(member["row_count"]) is not int or member["row_count"] <= 0 or
                view.get("complete") is not True or view.get("source_id") != spec.source_id or
                view.get("member_sha256") != spec.member_sha256 or view.get("member_crc32") != spec.member_crc32 or
                Path(view.get("raw_path", "")).resolve() != raw or view.get("author_group") != spec.author_group or
                view.get("row_count") != spec.expected_rows or view.get("rows_dropped") != 0 or
                view.get("timestamps_shifted") != 0 or view.get("canonical_units") != UNITS or
                view.get("canonical_current_sign") != "positive_discharge" or view.get("normalization_status") != "PASS" or
                view.get("observations_sha256") != member["observations"]["sha256"] or
                (manifest_path.parent / view.get("observations", "")).resolve() != observations or
                view.get("metadata_sha256") != spec.metadata_sha256 or
                view.get("conservative_split_component") != spec.conservative_split_component):
            raise SourceEvidenceError("Complete canonical view differs from licensed member")
        if not isinstance(view.get("contexts"), dict) or sum(view["contexts"].values()) != spec.expected_rows:
            raise SourceEvidenceError("Whole member context coverage required")
        views[member["member_id"]] = view
    if found != set(spec_map):
        raise SourceEvidenceError("Catalog must cover every registered complete member exactly once")
    components = provenance_components(members, {mid: view["conservative_split_component"] for mid, view in views.items()})
    roles = assign_roles(components, policy)
    return catalog, policy, views, components, roles, seen


def _scan_member(root, member, view):
    """Read every saved normalized row; hashes bind prior full numeric validators."""
    contexts, flags = Counter(), Counter()
    rows, unknown = 0, 0
    with gzip.open(_path(root, member["observations"]["path"]), "rt", encoding="utf-8") as stream:
        for rows, line in enumerate(stream, 1):
            row = json.loads(line)
            if (row.get("source_id") != member["source_id"] or row.get("member_sha256") != member["raw"]["sha256"] or
                    row.get("author_group") != member["author_group"] or row.get("source_row") != rows or
                    row.get("conservative_split_component") != view["conservative_split_component"] or
                    row.get("duplicate_content") != view["duplicate_content"] or row.get("context_id") not in view["contexts"]):
                raise SourceEvidenceError("Member/source-row/context coverage changed")
            if type(row.get("source_row")) is not int or row.get("csv_line_number") != rows + 1:
                raise SourceEvidenceError("Original CSV line sequence changed")
            if not isinstance(row.get("quality_flags"), list) or not isinstance(row.get("source_values"), dict):
                raise SourceEvidenceError("Original signal strings and anomaly flags required")
            if row.get("normalization_status") != "PASS":
                unknown += 1
            contexts[row["context_id"]] += 1
            flags.update(row["quality_flags"])
    if (rows != member["row_count"] or dict(contexts) != view["contexts"] or
            dict(flags) != view["quality_flag_counts"] or unknown != view["unknown_row_count"]):
        raise SourceEvidenceError("Whole row, context or quality coverage differs")
    return {"rows": rows, "contexts": dict(contexts), "quality_flag_counts": dict(flags), "unknown_rows": unknown}


def _content(root, catalog_ref, policy_ref):
    catalog, policy, views, components, roles, seen = _load_inputs(root, catalog_ref, policy_ref)
    component_by_member = {mid: component["component_id"] for component in components for mid in component["member_ids"]}
    frozen_members, counts = [], Counter()
    for member in catalog["members"]:
        view = views[member["member_id"]]
        audit = _scan_member(root, member, view)
        component = component_by_member[member["member_id"]]
        role = roles[component]
        counts[role] += audit["rows"]
        frozen_members.append({**member, "leakage_component_id": component, "role": role,
                               "original_row_range": [1, audit["rows"]], "audit": audit})
    for path, digest in seen.items():
        if sha256(path) != digest:
            raise SourceEvidenceError("Input changed while verifying; no partition written")
    return {"schema_version": 1, "kind": "frozen_complete_member_provenance_partition", "cohort_id": catalog["cohort_id"],
            "catalog_ref": catalog_ref, "policy_ref": policy_ref, "members": frozen_members,
            "components": components, "role_row_counts": dict(counts), "leakage_component_count": len(components),
            "partition_algorithm_sha256": sha256(Path(__file__)),
            "total_rows": sum(counts.values()), "protected_refs": catalog["protected_refs"],
            "evidence_refs": catalog["evidence_refs"], "public_source_hashes": catalog["public_source_hashes"],
            "scope": "Complete licensed member import and predeclared cross-capacity/protocol metadata transfer partition",
            "physical_independence_status": "UNKNOWN", "production_batch_identity": "UNKNOWN", "IID": "UNKNOWN",
            "confirmed_independent_physical_cells": None, "archive_md5_status": "UNKNOWN", "model_fits": 0,
            "same_chemistry_parameter_validation": False, "strict_protocol_heldout": False, "D02_complete": False}


def freeze_members(root, catalog_ref, policy_ref, out):
    root = Path(root).resolve()
    path = _path(root, out)
    if not path.is_relative_to(root / "data/splits") or path.suffix != ".json":
        raise SourceEvidenceError("New split JSON must be inside data/splits")
    if path.exists():
        raise SourceEvidenceError("Frozen output already exists; overwrite prohibited")
    content = _content(root, catalog_ref, policy_ref)
    data = (json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects a writer arriving during verification.
    with path.open("xb") as stream:
        stream.write(data)
    return {"exit_code": 0, "frozen_ref": {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(data).hexdigest()},
            "role_row_counts": content["role_row_counts"], "total_rows": content["total_rows"],
            "scope": content["scope"], "physical_independence_status": "UNKNOWN", "D02_complete": False}


def verify_members(root, frozen_ref):
    root = Path(root).resolve()
    path = _ref(root, frozen_ref, {})
    if not path.is_relative_to(root / "data/splits"):
        raise SourceEvidenceError("Frozen split must be inside data/splits")
    saved = _json(path)
    recomputed = _content(root, saved["catalog_ref"], saved["policy_ref"])
    if saved != recomputed or sha256(path) != frozen_ref["sha256"]:
        raise SourceEvidenceError("Frozen partition differs from current bound complete inputs")
    return {"exit_code": 0, "frozen_ref": frozen_ref, "total_rows": saved["total_rows"],
            "role_row_counts": saved["role_row_counts"], "physical_independence_status": "UNKNOWN", "D02_complete": False}
