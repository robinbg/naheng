from pathlib import Path
import json
from naheng.domain.contracts import PosteriorSnapshot
from .artifacts import atomic_json

def save_snapshot(directory: Path, snapshot: PosteriorSnapshot):
    path=directory/"snapshots"/(snapshot.snapshot_id+".json")
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != snapshot.model_dump(mode="json"):
            raise ValueError("Immutable snapshot revision conflict")
        return path
    atomic_json(path,snapshot.model_dump(mode="json"))
    return path
