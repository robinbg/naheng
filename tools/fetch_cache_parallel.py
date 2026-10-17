"""Audited upstream cache transfer with connection reuse and a strict byte cap."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from naheng.runtime.process_tree import ProcessTree

CACHE = ROOT / ".tools/cache/mathlib"
SETUP = ROOT / "artifacts/formal/setup"
DEST = SETUP / ("parallel_fetch-" + uuid.uuid4().hex[:8])
DEST.mkdir(exist_ok=False)
LIMIT = 1024 ** 3


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


plan_path = Path(sys.argv[1]).resolve()
if not plan_path.is_relative_to(SETUP) or not plan_path.is_file():
    raise ValueError("Expected a project cache evidence plan")
plan = json.loads(plan_path.read_text(encoding="utf-8"))
expected = {}
for row in plan:
    name = row["file"]
    if (not re.fullmatch(r"[0-9a-f]{16}\.ltar", name) or
            row["url"] != "https://lakecache.blob.core.windows.net/mathlib4/f/" + name or
            Path(row["destination"]).resolve() != (CACHE / name).resolve() or name in expected):
        raise ValueError("Invalid or duplicate upstream cache object")
    expected[name] = row
prior = {}
for folder in SETUP.glob("selective_fetch-*"):
    for path in folder.glob("*.ltar.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("exit_code") == 0 and row.get("transfer", {}).get("http_code") == 200:
            prior[path.name.removesuffix(".json")] = row.get("sha256")
for folder in SETUP.glob("parallel_fetch-*"):
    for path in folder.glob("*.ltar.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("status") == "downloaded":
            prior[row["file"]] = row["sha256"]
    manifest = folder / "manifest.json"
    if manifest.is_file():
        for row in json.loads(manifest.read_text(encoding="utf-8")).get("records", []):
            if row.get("status") == "downloaded":
                prior[row["file"]] = row["sha256"]
records = []
missing = []
for name, row in expected.items():
    path = CACHE / name
    if path.is_file():
        actual = digest(path)
        if prior.get(name) != actual:
            raise ValueError("Existing cache object lacks matching HTTP200/hash evidence: " + name)
        records.append({**row, "status":"reused_verified_bytes", "sha256":actual,
                        "bytes":path.stat().st_size})
    else:
        missing.append(row)
initial_bytes = sum(path.stat().st_size for path in CACHE.iterdir() if path.is_file())
# Each new output has its own equal reservation, so all concurrent outputs and
# retries together fit the remaining cap. Oversized objects fail explicitly and
# may be retried in a later, smaller missing-object batch.
per_object_limit = min(32 * 1024 ** 2, (LIMIT - initial_bytes) // max(1, len(missing)))
if per_object_limit <= 0:
    raise ValueError("Dependency cache byte budget exhausted")
run_id = uuid.uuid4().hex[:8]
parts = {row["file"]: CACHE / (row["file"] + ".parallel-part-" + run_id) for row in missing}
config = DEST / "curl.cfg"
config.write_text("".join("url = " + row["url"] + "\n-o " +
                         json.dumps(str(parts[row["file"]])) + "\n" for row in missing), encoding="utf-8")
manifest = {"scope":"dependency cache transfer only; requires subsequent actual Lean build/audit",
            "plan":str(plan_path),"plan_sha256":digest(plan_path),"script_sha256":digest(Path(__file__)),
            "utc":datetime.now(timezone.utc).isoformat(),"max_parallel":4,"network_retries":2,
            "batch_timeout_s":900,"cache_byte_limit":LIMIT,"initial_cache_bytes":initial_bytes,
            "per_object_byte_reservation":per_object_limit,"records":records,"exit_code":None}
(DEST / "started.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
start = time.monotonic()
timed_out = threading.Event()
if missing:
    argv = ["curl.exe","--parallel","--parallel-max","4","--location","--fail","--silent",
            "--show-error","--retry","2","--retry-all-errors","--connect-timeout","15",
            "--max-time","90","--max-filesize",str(per_object_limit),"--write-out","%{json}\n",
            "--config",str(config)]
    manifest["argv"] = argv
    with (DEST / "stderr.log").open("wb") as stderr, (DEST / "transfers.jsonl").open("w",encoding="utf-8") as stdout:
        proc = subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=stderr,text=True,
                                encoding="utf-8",errors="replace",start_new_session=os.name != "nt")
        tree = ProcessTree(proc)
        manifest["owned_pid"] = proc.pid
        (DEST / "started.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")

        def stop():
            timed_out.set()
            manifest["termination"] = tree.terminate()

        timer = threading.Timer(900,stop)
        timer.start()
        try:
            for line in proc.stdout:
                stdout.write(line)
                stdout.flush()
                if not line.strip():
                    continue
                transfer = json.loads(line)
                part = Path(transfer.get("filename_effective", "")).resolve()
                candidates = [name for name, path in parts.items() if path.resolve() == part]
                if len(candidates) != 1:
                    raise ValueError("Unexpected transfer output path")
                name = candidates[0]
                row = {**expected[name],"transfer":transfer,"status":"failed"}
                if part.is_file():
                    row.update(bytes=part.stat().st_size,sha256=digest(part))
                if transfer.get("http_code") == 200 and transfer.get("exitcode") == 0 and part.is_file():
                    part.rename(CACHE / name)
                    row["status"] = "downloaded"
                (DEST / (name + ".json")).write_text(json.dumps(row,indent=2),encoding="utf-8")
                records.append(row)
                if len(records) % 100 == 0:
                    print(f"cache objects accounted {len(records)}/{len(plan)}",flush=True)
            manifest["curl_exit_code"] = proc.wait(timeout=30)
        finally:
            timer.cancel()
            if proc.poll() is None:
                manifest["termination"] = tree.terminate()
                proc.wait(timeout=30)
            tree.close()
leantar = CACHE / "leantar-0.1.15.exe"
if leantar.is_file():
    version = subprocess.run([str(leantar),"--version"],capture_output=True,timeout=15)
    manifest["leantar"] = {"exit_code":version.returncode,"stdout":version.stdout.decode(errors="replace"),
                           "sha256":digest(leantar)}
else:
    manifest["leantar"] = {"exit_code":2,"reason":"Missing pinned decompressor"}
manifest["final_cache_bytes"] = sum(path.stat().st_size for path in CACHE.iterdir() if path.is_file())
manifest["timed_out"] = timed_out.is_set()
manifest["wall_s"] = time.monotonic() - start
manifest["exit_code"] = (0 if not timed_out.is_set() and len(records) == len(plan) and
    all(row["status"] in {"downloaded","reused_verified_bytes"} for row in records) and
    manifest["final_cache_bytes"] <= LIMIT and manifest["leantar"]["exit_code"] == 0 and
    manifest["leantar"].get("stdout","").strip() == "leantar 0.1.15" else 2)
(DEST / "manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
print(json.dumps({"manifest":str(DEST / "manifest.json"),"exit_code":manifest["exit_code"],
                  "records":len(records),"wall_s":manifest["wall_s"]}))
raise SystemExit(manifest["exit_code"])
