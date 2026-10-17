from __future__ import annotations
import hashlib, json, os
from pathlib import Path
from collections.abc import Iterator

SOURCE_FOLDERS = ("src", "configs", "formal", "frontend/src", "model_packages", "experiments")
SOURCE_EXCLUDED_DIRS = frozenset(("__pycache__", ".lake"))

def iter_source_files(root: Path) -> Iterator[Path]:
    """Keep the source hash order while pruning dependency/cache trees first."""
    for folder in SOURCE_FOLDERS:
        source = root / folder
        if SOURCE_EXCLUDED_DIRS.intersection(source.parts):
            continue
        files = []
        for current, directories, filenames in os.walk(source, topdown=True):
            directories[:] = [name for name in directories if name not in SOURCE_EXCLUDED_DIRS]
            for name in filenames:
                path = Path(current) / name
                if name not in SOURCE_EXCLUDED_DIRS and path.is_file():
                    files.append(path)
        # Per-directory sorting changes the historical hash when a file and
        # directory name interleave. Sort the complete retained folder instead.
        yield from sorted(files)

def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    os.replace(temp,path)

def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def code_hash(root: Path) -> str:
    digest=hashlib.sha256()
    for path in iter_source_files(root):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()

def safe_artifact(run_dir: Path, artifact_id: str) -> Path:
    index=json.loads((run_dir/"manifest.json").read_text(encoding="utf-8"))["artifact_index"]
    if artifact_id not in index or artifact_id.startswith("evaluator"):
        raise KeyError(artifact_id)
    target=(run_dir/index[artifact_id]).resolve()
    if not target.is_relative_to(run_dir.resolve()):
        raise ValueError("Artifact traversal")
    return target
