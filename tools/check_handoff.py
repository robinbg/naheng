#!/usr/bin/env python3
"""Validate the handoff plan only; this is NOT an application or proof verifier.

Requires PyYAML. Run before implementation, from the handoff folder:
    python tools/check_handoff.py --write HANDOFF_CHECK.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "Plan checker requires PyYAML; install it in the project environment, "
        "or run: uv run --with pyyaml tools/check_handoff.py. "
        "No application validation has been performed."
    ) from exc

REQUIRED_FILES = [
    "README.md", "START_CODEX.md", "AGENTS.md", "PLANS.md", "TASKS.yaml",
    "REQUIREMENTS.yaml", "configs/execution.yaml", "docs/STATUS.md",
    "docs/SOURCES.md", "docs/source/PROPOSAL.md",
    "docs/specs/MODELS_FORMAL.md", "docs/specs/CONTRACTS.md",
    "docs/specs/EXPERIMENTS.md", "tools/check_handoff.py",
]

def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a mapping in {path.name}")
    return value

def check(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        if not (root / rel).is_file():
            errors.append(f"Missing file: {rel}")
    if errors:
        return {"scope": "handoff_plan_only", "passed": False, "errors": errors}
    tasks = read_yaml(root / "TASKS.yaml").get("tasks", [])
    reqs = read_yaml(root / "REQUIREMENTS.yaml").get("requirements", [])
    cfg = read_yaml(root / "configs/execution.yaml")
    ids = [t.get("id") for t in tasks]
    if any(not isinstance(x, str) or not x for x in ids):
        errors.append("Task IDs must be nonempty strings")
    if len(set(ids)) != len(ids):
        errors.append("Duplicate task IDs")
    by_id = {t["id"]: t for t in tasks}
    allowed = {"todo", "in_progress", "blocked", "failed", "done"}
    for t in tasks:
        tid = t["id"]
        for field in ("title", "milestone", "workstream", "implementation",
                      "deliverables", "acceptance", "validation_commands"):
            if not t.get(field):
                errors.append(f"{tid}: empty {field}")
        if t.get("status") not in allowed:
            errors.append(f"{tid}: bad status")
        if t.get("status") == "done" and not t.get("evidence"):
            errors.append(f"{tid}: done without recorded evidence")
        for dep in t.get("depends_on", []):
            if dep not in by_id:
                errors.append(f"{tid}: unknown dependency {dep}")
            if dep == tid:
                errors.append(f"{tid}: self-dependency")
            if dep in by_id and by_id[dep]["milestone"] > t["milestone"]:
                errors.append(f"{tid}: dependency from later milestone {dep}")
    marks: dict[str, int] = {}
    order: list[str] = []
    def visit(tid: str, trail: list[str]) -> None:
        if marks.get(tid) == 1:
            errors.append("Dependency cycle: " + " -> ".join(trail + [tid]))
            return
        if marks.get(tid) == 2:
            return
        marks[tid] = 1
        for dep in by_id[tid].get("depends_on", []):
            if dep in by_id:
                visit(dep, trail + [tid])
        marks[tid] = 2
        order.append(tid)
    for tid in by_id:
        visit(tid, [])
    req_ids = [r["id"] for r in reqs]
    if len(set(req_ids)) != len(req_ids):
        errors.append("Duplicate requirement IDs")
    for req in reqs:
        if not req.get("task_ids") or not req.get("done_definition"):
            errors.append(f"{req['id']}: missing traceability")
        for tid in req.get("task_ids", []):
            if tid not in by_id:
                errors.append(f"{req['id']}: unknown task {tid}")
        if not (root / req.get("source", "")).is_file():
            errors.append(f"{req['id']}: missing source")
    for rid in [*(f"F{i:02}" for i in range(1, 11)), "T0", "T1", "T2", "T3", "AI", "LINK", "DATA", "DELIVERY"]:
        if rid not in req_ids:
            errors.append(f"Missing non-optional requirement: {rid}")
    for key in ("remote_llm_enabled", "paid_compute_enabled", "external_publish_enabled", "real_hardware_control_enabled"):
        if cfg.get("permissions", {}).get(key) is not False:
            errors.append(f"Initial permission should be disabled: {key}")
    if (root / "AGENTS.md").stat().st_size >= 24 * 1024:
        errors.append("Root agent instructions unexpectedly large")
    return {
        "scope": "handoff_plan_only",
        "checked_on": "2026-10-09",
        "passed": not errors,
        "task_count": len(tasks),
        "requirement_count": len(reqs),
        "milestones": sorted({t["milestone"] for t in tasks}),
        "task_status_counts": {s: sum(t["status"] == s for t in tasks) for s in sorted(allowed)},
        "topological_order": order,
        "file_hashes": {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in REQUIRED_FILES},
        "errors": errors,
        "not_checked": ["target repository", "application code", "dependency installation",
                        "Lean proof compilation", "battery simulations", "raw dataset validation",
                        "scientific performance", "research novelty"],
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write", type=Path, help="Write this plan-check report to the given path")
    args = parser.parse_args()
    try:
        result = check(args.root.resolve())
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        result = {"scope": "handoff_plan_only", "passed": False, "errors": [str(exc)]}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
