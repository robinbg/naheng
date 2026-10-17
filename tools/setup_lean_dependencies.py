"""Bounded project-local dependency acquisition; this is not a proof check."""
from pathlib import Path
from datetime import datetime, timezone
import json, os, subprocess, sys, time, uuid

ROOT = Path(__file__).resolve().parents[1]
MODE = sys.argv[1]
assert MODE in {"update", "update_verbose", "cache", "selective_plan", "selective_unpack", "extend_plan", "unpack_plan", "force_unpack_plan", "proofwidgets", "restore_proofwidgets", "checkout", "local_clone"}
lake = ROOT / ".tools/lean/bin/lake.exe"
dest = ROOT / "artifacts/formal/setup" / (MODE + "-" + uuid.uuid4().hex[:8])
dest.mkdir(parents=True, exist_ok=False)
modules = ["Mathlib.Data.Real.Basic", "Mathlib.Tactic.DeriveFintype",
           "Mathlib.Algebra.BigOperators.Group.Finset.Basic",
           "Mathlib.Algebra.BigOperators.Ring.Finset", "Mathlib.Tactic.NormNum",
           "Mathlib.Data.Complex.Exponential", "Mathlib.Tactic.Linarith"]
if MODE in {"cache", "selective_plan", "selective_unpack"} and len(sys.argv) > 2:
    modules = sys.argv[2:]
    for name in modules:
        if not name.startswith("Mathlib.") or not all(part.isidentifier() for part in name.split(".")):
            raise ValueError("Expected a Mathlib module name")
        source = ROOT / "formal/.lake/packages/mathlib" / (name.replace(".", "/") + ".lean")
        if not source.is_file():
            raise ValueError("Pinned module source is missing: " + name)
if MODE in {"update", "update_verbose"}:
    argv = [str(lake), "--verbose", "update"] if MODE == "update_verbose" else [str(lake), "update"]
elif MODE == "cache":
    argv = [str(lake), "exe", "cache", "get", *modules]
elif MODE == "proofwidgets":
    # This is the pinned upstream release target used by Cache.getProofWidgets.
    # Selective olean extraction does not supply its JS/release freshness marker.
    argv = [str(lake), "--verbose", "build", "proofwidgets:release"]
elif MODE == "restore_proofwidgets":
    archive=Path(sys.argv[2]).resolve()
    assert archive.is_relative_to(ROOT / ".tools/downloads") and archive.is_file()
    package=(ROOT / "formal/.lake/packages/proofwidgets").resolve()
    assert package.is_relative_to(ROOT / "formal/.lake/packages")
    argv=[str(lake), "-d", str(package), "unpack", str(archive)]
elif MODE.startswith("selective_"):
    argv = [str(lake), "env", "lean", "--run", "../tools/SelectiveCache.lean",
            MODE.removeprefix("selective_"), *modules]
elif MODE in {"unpack_plan", "force_unpack_plan", "extend_plan"}:
    plan = Path(sys.argv[2]).resolve()
    assert plan.is_relative_to(ROOT / "artifacts/formal/setup") and plan.is_file()
    if MODE == "extend_plan":
        dependency_identity = []
        for package in (ROOT / "formal/.lake/packages").iterdir():
            if (package / ".git").exists():
                rev = subprocess.run(["git","-C",str(package),"rev-parse","HEAD"],capture_output=True,text=True,timeout=30)
                clean = subprocess.run(["git","-C",str(package),"diff","--quiet","HEAD","--"],capture_output=True,timeout=60)
                if rev.returncode or clean.returncode:
                    raise ValueError("Pinned dependency source has changed: " + package.name)
                dependency_identity.append({"package":package.name,"revision":rev.stdout.strip(),"tracked_diff_exit_code":clean.returncode})
        (dest / "dependency_identity.json").write_text(json.dumps(dependency_identity,indent=2),encoding="utf-8")
    argv = [str(lake), "env", "lean", "--run", "../tools/SelectiveCache.lean", MODE, str(plan), *sys.argv[3:]]
elif MODE == "checkout":
    argv = ["git", "-C", str(ROOT / "formal/.lake/packages/mathlib"), "checkout", "--detach", "v4.19.0"]
else:
    source = Path(sys.argv[2]).resolve()
    assert source.is_relative_to(ROOT / "artifacts/formal/setup") and (source / ".git").is_dir()
    target = ROOT / "formal/.lake/packages/mathlib"
    assert not target.exists()
    argv = ["git", "-c", "core.longpaths=true", "clone", "--local", "--no-checkout", str(source), str(target)]
env = {**os.environ, "PATH": str(lake.parent) + os.pathsep + os.environ.get("PATH", ""),
       "MATHLIB_NO_CACHE_ON_UPDATE": "1", "GIT_TERMINAL_PROMPT": "0",
       "XDG_CACHE_HOME": str(ROOT / ".tools/cache")}
env["RAYON_NUM_THREADS"] = "4"
config_index = int(env.get("GIT_CONFIG_COUNT", "0"))
env.update({"GIT_CONFIG_COUNT": str(config_index + 1),
            f"GIT_CONFIG_KEY_{config_index}": "core.longpaths",
            f"GIT_CONFIG_VALUE_{config_index}": "true"})
started = time.monotonic()
record = {"argv": argv, "cwd": str(ROOT / "formal"),
          "utc": datetime.now(timezone.utc).isoformat(), "timeout_s": 300,
          "scope": "dependency_installation_only; no project theorem approval",
          "environment_overrides": {k: env[k] for k in ["MATHLIB_NO_CACHE_ON_UPDATE", "GIT_TERMINAL_PROMPT", "XDG_CACHE_HOME"]},
          "stdout": str(dest / "stdout.log"), "stderr": str(dest / "stderr.log")}
with (dest / "stdout.log").open("wb") as out, (dest / "stderr.log").open("wb") as err:
    proc = subprocess.Popen(argv, cwd=ROOT / "formal", env=env, stdout=out, stderr=err)
    record["owned_pid"] = proc.pid
    (dest / "started.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    try:
        record["exit_code"] = proc.wait(timeout=300)
        record["timed_out"] = False
    except subprocess.TimeoutExpired:
        killed = subprocess.run(["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        (dest / "timeout_kill.log").write_bytes(killed.stdout + killed.stderr)
        proc.wait(timeout=30)
        record.update(exit_code=2, timed_out=True, kill_exit_code=killed.returncode)
record["wall_s"] = time.monotonic() - started
record["lake_manifest_exists"] = (ROOT / "formal/lake-manifest.json").is_file()
(dest / "command.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
print(json.dumps(record, indent=2))
print((dest / "stdout.log").read_text(encoding="utf-8", errors="replace")[-3000:])
print((dest / "stderr.log").read_text(encoding="utf-8", errors="replace")[-3000:])
raise SystemExit(record["exit_code"])
