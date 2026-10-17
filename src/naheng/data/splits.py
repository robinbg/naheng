"""Frozen identity-level splits, without a time-point shuffle interface."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path


def check_no_leakage(assignments:list[dict]):
    owners={}
    for row in assignments:
        role=row["role"]
        if role not in ("train","validation","test"):
            raise ValueError("Unknown split role")
        # Whole cells and every trajectory must belong to one role.
        for kind,value in (("cell",row["cell_id"]),
                           ("trajectory",row["cell_id"]+"\0"+row["trajectory_id"])):
            identity=(row["source_id"],kind,value)
            if identity in owners and owners[identity]!=role:
                raise ValueError("Physical cell or complete trajectory leaked across splits")
            owners[identity]=role
    return True


def freeze_split(datasets:list,out:Path,seed:int=20261010,
                 fractions=(.6,.2,.2),group_by="cell_id",holdout_only=False):
    if group_by not in ("cell_id","batch_id"):
        raise ValueError("Split by complete cells or batches, never time points")
    if len(fractions)!=3 or any(value<0 for value in fractions) or abs(sum(fractions)-1)>1e-12:
        raise ValueError("Split fractions must be nonnegative and sum to one")
    if not datasets: raise ValueError("Datasets required for a frozen split")
    groups={}
    # A cell observed in multiple batches must still have exactly one split.
    parent={}
    def find(key):
        parent.setdefault(key,key)
        if parent[key]!=key: parent[key]=find(parent[key])
        return parent[key]
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b: parent[max(a,b)]=min(a,b)
    for dataset in datasets:
        for record in dataset.records:
            cell=(record["source_id"],"cell",record["cell_id"])
            find(cell)
            if group_by=="batch_id":
                if not record["batch_id"]: raise ValueError("Missing batch identity prevents batch split")
                union(cell,(record["source_id"],"batch",record["batch_id"]))
    assignments=[]
    for dataset in datasets:
        for record in dataset.records:
            group=find((record["source_id"],"cell",record["cell_id"]))
            identifier=json.dumps(group,separators=(",",":"))
            if identifier not in groups:
                rank=int(hashlib.sha256((str(seed)+identifier).encode()).hexdigest()[:16],16)/2**64
                groups[identifier]="test" if holdout_only else "train" if rank<fractions[0] else "validation" if rank<fractions[0]+fractions[1] else "test"
            assignments.append({"source_id":record["source_id"],"cell_id":record["cell_id"],
                "batch_id":record["batch_id"],"trajectory_id":record["trajectory_id"],
                "timestamp_s":record["timestamp_s"],"raw_sha256":record["raw_sha256"],
                "source_csv_line":record["source_csv_line"],"group_id":identifier,"role":groups[identifier]})
    check_no_leakage(assignments)
    identity={"schema_version":1,"seed":seed,"group_by":group_by,"fractions":list(fractions),
        "holdout_only":holdout_only,"source_hashes":sorted({dataset.raw_sha256 for dataset in datasets}),
        "assignments":assignments}
    revision=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    result={**identity,"revision":revision,"frozen":True,"independent_group_count":len(groups),
        "role_record_counts":{role:sum(row["role"]==role for row in assignments) for role in ("train","validation","test")},
        "limitations":["No model fit, forecast calibration or external validation is performed by data splitting"]}
    out=Path(out)
    if out.exists():
        existing=json.loads(out.read_text(encoding="utf-8"))
        if existing!=result: raise ValueError("Frozen split cannot be overwritten; use a new revision path")
        return existing
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result
