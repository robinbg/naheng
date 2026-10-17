"""Import individual audited declarations without granting runtime authority."""
from copy import deepcopy
import hashlib,json,re
from pathlib import Path

_ALLOWED_AXIOMS={"propext","Classical.choice","Quot.sound"}
_SHA256=re.compile(r"[0-9a-f]{64}")


def load_evidence(root:Path,manifest_path:Path)->dict:
    root=Path(root).resolve();manifest_path=Path(manifest_path).resolve()
    if not manifest_path.is_relative_to(root): raise ValueError("Uncontrolled evidence manifest")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status")!="checked": raise ValueError("Unverified evidence")
    evidence=manifest.get("evidence")
    if not evidence: raise ValueError("No exported proof evidence")
    records=evidence if isinstance(evidence,list) else [evidence]
    identifiers=set()
    # One read per distinct artifact in this import. This map never survives
    # the call: every action's revalidation reads the current bytes again.
    artifact_hashes={}
    objects=manifest.get('compiled_object_hashes',{})
    if not isinstance(objects,dict):raise ValueError('Malformed compiled object identity index')
    for name,expected in objects.items():
        if (not isinstance(name,str) or not name.startswith('formal/.lake/build/lib/lean/Naheng/')
            or not name.endswith('.olean') or not isinstance(expected,str) or not _SHA256.fullmatch(expected)):
            raise ValueError('Uncontrolled compiled proof object')
        path=(root/name).resolve()
        if not path.is_relative_to(root/'formal/.lake/build/lib/lean/Naheng') or not path.is_file():
            raise ValueError('Missing compiled proof object')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('Stale compiled proof object')
    for record in records:
        if not isinstance(record,dict) or record.get("status")!="checked" or record.get("category")!="formal_kernel":
            raise ValueError("Declaration record is not checked kernel evidence")
        identifier=record.get("evidence_id")
        if not isinstance(identifier,str) or not identifier or identifier in identifiers:
            raise ValueError("Missing or duplicate declaration evidence identity")
        identifiers.add(identifier)
        target=record.get("declaration");statement=record.get("statement")
        if not isinstance(target,str) or not target or not isinstance(statement,str) or not statement:
            raise ValueError("Elaborated declaration identity and statement missing")
        # Lean prints generic declarations with an explicit universe suffix
        # such as .{u_1, u_2}. This suffix is syntax, not another target name.
        universe = r"(?:\.\{[A-Za-z_]\w*(?:,\s*[A-Za-z_]\w*)*\})?"
        if not re.match(r"^(?:theorem|def|opaque)\s+"+re.escape(target)+universe+r"(?=\s|:|\(|\{)",statement):
            raise ValueError("Statement belongs to another declaration")
        statement_hash=record.get("statement_hash")
        if not isinstance(statement_hash,str) or not _SHA256.fullmatch(statement_hash) or hashlib.sha256(statement.encode()).hexdigest()!=statement_hash:
            raise ValueError("Stale declaration statement hash")
        artifacts=record.get("artifacts")
        if not isinstance(artifacts,dict) or not artifacts:
            raise ValueError("Proof source/build artifact hashes missing")
        for name,expected in artifacts.items():
            if not isinstance(name,str) or not isinstance(expected,str) or not _SHA256.fullmatch(expected):
                raise ValueError("Invalid proof artifact identity")
            if name not in artifact_hashes:
                path=(root/name).resolve()
                if not path.is_relative_to(root) or not path.is_file(): raise ValueError("Missing controlled artifact")
                artifact_hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
            if artifact_hashes[name]!=expected: raise ValueError("Stale proof artifact")
        axioms=record.get("axioms")
        if not isinstance(axioms,list) or any(not isinstance(item,str) for item in axioms):
            raise ValueError("Transitive axiom audit missing")
        if not set(axioms).issubset(_ALLOWED_AXIOMS): raise ValueError("Untrusted transitive axiom")
    # Preserve scope for inspection; never infer T1/T3 permission from its text.
    return {"evidence_id":records[0]["evidence_id"],"status":"checked",
            "category":"formal_kernel","records":deepcopy(records)}
