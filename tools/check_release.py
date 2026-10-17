import argparse,json
from pathlib import Path
import yaml
p=argparse.ArgumentParser(); p.add_argument("--scope",choices=["application","release"],default="release"); a=p.parse_args()
root=Path(__file__).resolve().parents[1]
tasks=yaml.safe_load((root/"TASKS.yaml").read_text(encoding="utf-8"))["tasks"]
required=[t for t in tasks if t["required"] and (a.scope=="release" or t["milestone"] in ("M0","M1","M2"))]
missing=[{"id":t["id"],"status":t["status"],"blocker":t.get("blocker")} for t in required if t["status"]!="done" or not t["evidence"]]
# Completion additionally requires independently replayable audits, not ledger labels.
for suite in ("theory","application","linkage","public_validation"):
    path=root/"artifacts/experiments"/suite/"audit.json"
    if not path.exists(): missing.append({"experiment":suite,"status":"unverified"})
    else:
        record=json.loads(path.read_text(encoding="utf-8"))
        if record.get("exit_code")!=0 or not record.get("independent_evidence"): missing.append({"experiment":suite,"status":"unverified"})
print(json.dumps({"scope":a.scope,"exit_code":2 if missing else 0,"incomplete":missing},ensure_ascii=False,indent=2))
raise SystemExit(2 if missing else 0)
