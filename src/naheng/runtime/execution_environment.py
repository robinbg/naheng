"""Record installed scientific packages against the frozen dependency lock."""
import importlib.metadata,platform,sys,tomllib
from pathlib import Path
from .artifacts import sha256_file

CORE_PACKAGES=("numpy","scipy","pydantic","pyarrow","fastapi","uvicorn","PyYAML")
def capture_environment(source_root:Path):
    lock=Path(source_root)/"uv.lock"
    locked={p["name"].lower():p.get("version") for p in tomllib.loads(lock.read_text(encoding="utf-8"))["package"]}
    versions={name:importlib.metadata.version(name) for name in CORE_PACKAGES}
    mismatches={name:{"installed":version,"locked":locked.get(name.lower())} for name,version in versions.items() if locked.get(name.lower())!=version}
    if mismatches:
        raise RuntimeError("Installed core dependencies differ from frozen uv.lock: "+str(mismatches))
    return {"python_executable":sys.executable,"python_version":platform.python_version(),"platform":platform.platform(),
            "dependency_lock_hash":sha256_file(lock),"installed_packages":versions,"lock_match":True,
            "scope":"Core installed package versions; no claim of binary reproducibility"}
def assert_environment_unchanged(source_root:Path,record:dict):
    current=capture_environment(source_root)
    if current["installed_packages"]!=record["installed_packages"] or current["dependency_lock_hash"]!=record["dependency_lock_hash"]:
        raise RuntimeError("Execution environment changed during numerical run")