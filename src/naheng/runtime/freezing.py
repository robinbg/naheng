from pathlib import Path
from .artifacts import code_hash,atomic_json,sha256_file,iter_source_files

def freeze_source(project:Path,run_dir:Path)->tuple[Path,str]:
    dest=run_dir/"source_snapshot"
    if dest.exists(): raise ValueError("Source snapshot already exists")
    dest.mkdir(parents=True)
    for p in iter_source_files(project):
        rel=p.relative_to(project); target=dest/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(p.read_bytes())
    for rel in ("pyproject.toml","uv.lock","frontend/package.json","frontend/package-lock.json"):
        p=project/rel
        if p.is_file():
            target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
    digest=code_hash(dest)
    atomic_json(run_dir/"source_index.json",{"code_hash":digest,"files":{p.relative_to(dest).as_posix():sha256_file(p) for p in sorted(dest.rglob("*")) if p.is_file()}})
    return dest,digest
