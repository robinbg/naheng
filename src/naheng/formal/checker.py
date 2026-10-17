"""Run bounded, reproducible Lean builds and transitive axiom audits."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone

from .audit import audit_axioms
from naheng.runtime.process_tree import ProcessTree

ROOT = Path(__file__).resolve().parents[3]
SUITES = {
    "foundation": "Naheng.Foundation",
    "reduction": "Naheng.Reduction",
    "aging": "Naheng.Aging",
    "contracts": "Naheng.Contracts",
    "core": "Naheng.Exported",
    "reduction_exact": "Naheng.ReductionExact",
    "reduction_residual": "Naheng.ReductionResidual",
    "reduction_trajectory": "Naheng.ReductionTrajectory",
    "reduction_variable_trajectory": "Naheng.Reduction.VariableTrajectory",
    "reduction_fixed_current_readout": "Naheng.Reduction.FixedCurrentReadout",
    "reduction_heterogeneous_counterexample": "Naheng.Reduction.HeterogeneousCounterexample",
    "aging_film": "Naheng.AgingFilm",
    "aging_capacity_endpoint": "Naheng.Aging.CapacityEndpoint",
}


def _audit_target_batches(targets, size=20):
    """Partition every target exactly once; never discard an expensive target."""
    if (not isinstance(targets, list) or not targets or len(set(targets)) != len(targets)
            or any(not isinstance(t, str) or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+',t) for t in targets)):
        raise ValueError('Unique fully qualified Lean target identifiers required')
    return [targets[i:i+size] for i in range(0,len(targets),size)]


def _audit_plan(suite, targets, manifest):
    """Audit the complete core through its exact original exported modules."""
    _audit_target_batches(targets)
    if suite != 'core':
        return [{'module':SUITES[suite],'targets':batch}
                for batch in _audit_target_batches(targets)]
    groups=('foundation','reduction','aging','contracts')
    entries=manifest.get('suites',{})
    union=[]
    plan=[]
    for name in groups:
        entry=entries.get(name,{})
        if entry.get('implementation_status')!='implemented':
            raise ValueError('Core requires all original suites implemented')
        group=entry.get('targets')
        batches=_audit_target_batches(group)
        if any(target in union for target in group):
            raise ValueError('Core original suites must have disjoint exported targets')
        union.extend(group)
        plan.extend({'module':SUITES[name],'targets':batch} for batch in batches)
    if union != targets:
        raise ValueError('Core targets must equal the complete ordered original suite union')
    return plan


def run_command(command: list[str], cwd: Path, log: Path, timeout: int = 120) -> dict:
    """Capture command, exit status, timeout and exact stdout/stderr in one log."""
    log.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    started = datetime.now(timezone.utc).isoformat()
    try:
        proc = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,text=True,encoding="utf-8",
                                errors="replace",start_new_session=os.name != "nt")
        tree = ProcessTree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            code, timed_out = proc.returncode, False
        except subprocess.TimeoutExpired:
            killed = tree.terminate()
            log.with_suffix(".timeout_kill.log").write_text(json.dumps(killed,indent=2),encoding="utf-8")
            stdout, stderr = proc.communicate(timeout=30)
            code, timed_out = 2, True
        finally:
            tree.close()
    except subprocess.TimeoutExpired as exc:
        def decoded(value):
            return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""
        stdout, stderr, code, timed_out = decoded(exc.stdout), decoded(exc.stderr), 2, True
    except OSError as exc:
        stdout, stderr, code, timed_out = "", repr(exc), 2, False
    record = {"command": command, "cwd": str(cwd), "started_at_utc": started,
              "exit_code": code, "timed_out": timed_out,
              "elapsed_s": round(time.monotonic() - start, 3), "log": str(log)}
    log.write_text(json.dumps(record, ensure_ascii=False, indent=2) +
                   "\n\n--- STDOUT ---\n" + stdout + "\n--- STDERR ---\n" + stderr,
                   encoding="utf-8")
    return {**record, "stdout": stdout, "stderr": stderr}


def _lake() -> str | None:
    explicit = os.environ.get("NAHENG_LAKE")
    if explicit:
        return explicit if Path(explicit).is_file() else None
    local = ROOT / ".tools" / "lean" / "bin" / ("lake.exe" if os.name == "nt" else "lake")
    return str(local) if local.is_file() else shutil.which("lake")


def check(suite: str = "foundation", out: Path | str | None = None) -> dict:
    batch_started = time.monotonic()
    out = Path(out) if out is not None else ROOT / "artifacts" / "formal" / suite
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    project = ROOT / "formal"
    evidence: list[dict] = []
    report = {"suite": suite, "status": "blocked", "exit_code": 2,
              "checked": False, "commands": evidence, "evidence": [], "reason": None,
              "generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_hashes": {}, "targets": [], "audit": None}

    def finish(reason: str, status: str = "blocked", code: int = 2) -> dict:
        report.update(reason=reason, status=status, exit_code=code, checked=status == "checked")
        (out / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    if suite not in SUITES:
        return finish(f"Unknown formal suite: {suite}", "failed", 1)
    manifest_file = project / "exports.json"
    if not manifest_file.is_file():
        return finish("Missing formal/exports.json")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    suite_entry = manifest.get("suites", {}).get(suite)
    if not suite_entry or not suite_entry.get("targets"):
        return finish(f"Suite {suite} has no implemented exported targets; requirements remain incomplete")
    if suite_entry.get("implementation_status") != "implemented":
        return finish(f"Suite {suite} is not fully implemented: {suite_entry.get('implementation_status')}")
    targets = suite_entry["targets"]
    try:
        audit_plan = _audit_plan(suite,targets,manifest)
    except (ValueError,TypeError) as error:
        return finish(str(error), 'failed', 1)
    report["targets"] = targets
    report["toolchain_lock"] = (project / "lean-toolchain").read_text(encoding="utf-8").strip()
    # Prune dependency directories before traversal. Filtering rglob afterwards
    # still scans the entire mathlib checkout and consumes the proof budget.
    sources = []
    for directory, subdirectories, files in os.walk(project):
        subdirectories[:] = [name for name in subdirectories if name != ".lake"]
        sources.extend(Path(directory) / name for name in files if name.endswith(".lean"))
    for path in sorted(sources):
        content = path.read_text(encoding="utf-8")
        report["source_hashes"][str(path.relative_to(project))] = hashlib.sha256(content.encode()).hexdigest()
        # Preliminary rejection only; successful source lint is not proof evidence.
        no_comments = re.sub(r"/\-.*?\-/|--[^\n]*", "", content, flags=re.DOTALL)
        if re.search(r"\b(sorry|admit|axiom|native_decide)\b", no_comments):
            return finish(f"Forbidden proof placeholder/custom axiom/native tactic in {path.name}", "failed", 1)
    lake = _lake()
    if lake is None:
        evidence.append({"command": ["lake", "build", SUITES[suite]], "exit_code": 2,
                         "executed": False, "reason": "lake executable unavailable"})
        return finish("Lean/Lake is unavailable; no formal statement is checked")
    version = run_command([lake, "env", "lean", "--version"], project, out / "version.log")
    evidence.append({k: v for k, v in version.items() if k not in {"stdout", "stderr"}})
    if version["exit_code"]:
        return finish("Lean version/toolchain cannot be resolved")
    report["lean_version"] = version["stdout"].strip()
    expected_version = report["toolchain_lock"].split(":v")[-1]
    if f"version {expected_version}" not in report["lean_version"]:
        return finish("Lean executable version differs from lean-toolchain; do not reuse evidence", "failed", 1)
    build = run_command([lake, "build", SUITES[suite]], project, out / "build.log")
    evidence.append({k: v for k, v in build.items() if k not in {"stdout", "stderr"}})
    if build["timed_out"]:
        return finish("Lean build timed out: UNKNOWN")
    if build["exit_code"] == 2:
        return finish("Lean build could not complete: UNKNOWN")
    if build["exit_code"]:
        return finish("Lean build failed or dependency cannot be fetched", "failed", 1)
    probes, audit_logs, audit_outputs = [], [], []
    report['audit_batches'] = []
    for index, planned in enumerate(audit_plan,1):
        batch=planned['targets']
        if time.monotonic()-batch_started > 1650:
            return finish('Original1800s batch budget cannot admit another120s audit: UNKNOWN')
        single = len(audit_plan)==1
        probe = out / ('Audit.lean' if single else f'Audit_{index:03d}.lean')
        audit_log = out / ('axioms.log' if single else f'axioms_{index:03d}.log')
        probe.write_text("import " + planned['module'] + "\nset_option pp.proofs false\n" +
                         "\n".join(f"#print {target}\n#print axioms {target}" for target in batch) + "\n",
                         encoding="utf-8")
        audit_run = run_command([lake,"env","lean",str(probe)],project,audit_log)
        evidence.append({k:v for k,v in audit_run.items() if k not in {'stdout','stderr'}})
        report['audit_batches'].append({'index':index,'module':planned['module'],'targets':batch,
            'exit_code':audit_run['exit_code'],'timed_out':audit_run['timed_out'],'log':str(audit_log)})
        if audit_run['timed_out'] or audit_run['exit_code']==2:
            return finish(f'Lean declaration/axiom audit batch{index} incomplete: UNKNOWN')
        if audit_run['exit_code']:
            return finish(f'Lean declaration/axiom audit batch{index} failed','failed',1)
        parsed=audit_axioms(audit_run['stdout'],batch)
        if parsed['status']!='passed':
            report['audit']=parsed
            return finish(f'Batch{index} missing/forbidden transitive axioms','failed',1)
        probes.append(probe);audit_logs.append(audit_log);audit_outputs.append(audit_run['stdout'])
    full_output='\n'.join(audit_outputs)
    report["audit"] = audit_axioms(full_output, targets)
    if report["audit"]["status"] != "passed":
        return finish("Missing or forbidden transitive axiom dependencies", "failed", 1)
    report["declarations_output_sha256"] = hashlib.sha256(full_output.encode()).hexdigest()
    (out/'declarations.stdout.log').write_text(full_output,encoding='utf-8')
    lake_manifest = project / "lake-manifest.json"
    if lake_manifest.is_file():
        report["dependencies_sha256"] = hashlib.sha256(lake_manifest.read_bytes()).hexdigest()
    artifact_files = [project / name for name in report["source_hashes"]]
    artifact_files.extend([project / "lean-toolchain", project / "lakefile.toml", manifest_file,
                           out / "build.log", out / "version.log", out/'declarations.stdout.log', *probes, *audit_logs])
    if lake_manifest.is_file():
        artifact_files.append(lake_manifest)
    artifacts = {}
    for path in artifact_files:
        if not path.resolve().is_relative_to(ROOT.resolve()):
            return finish("Proof artifacts must be saved inside controlled project root", "failed", 1)
        artifacts[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    object_root=project/'.lake/build/lib/lean/Naheng'
    report['compiled_object_hashes']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(object_root.rglob('*.olean')) if p.is_file()}
    for target in targets:
        # Printed declaration includes the elaborated proposition and hypotheses.
        # Missing declaration text cannot silently inherit a whole-log hash.
        declaration = re.search(r"(?ms)^(?:theorem|def|opaque)\s+" + re.escape(target) +
                                r"\b(.*?)(?=\s*:=)", full_output)
        if declaration is None:
            return finish(f"No elaborated declaration printed for {target}", "failed", 1)
        statement = declaration.group(0).strip()
        statement_hash = hashlib.sha256(statement.encode()).hexdigest()
        report["evidence"].append({"evidence_id": f"lean.{suite}.{target}.{statement_hash[:16]}",
            "status": "checked", "category": "formal_kernel", "declaration": target,
            "statement_hash": statement_hash, "statement": statement,
            "axioms": report["audit"]["targets"][target], "artifacts": artifacts,
            "scope": suite_entry.get("scope"), "toolchain": report["toolchain_lock"]})
    return finish("Build and all exported declaration axiom audits passed", "checked", 0)
