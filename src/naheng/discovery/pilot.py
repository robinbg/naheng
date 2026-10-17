"""Public immutable-data learned pilot, with separately executed baselines."""
import json
from pathlib import Path
from .dataset import build_dataset,freeze_dataset
from .session import run_pilot
from naheng.runtime.artifacts import atomic_json,code_hash,sha256_file

def discover(root,out):
    root=Path(root).resolve();out=Path(out).resolve()
    if not out.is_relative_to(root/'artifacts'):raise ValueError('Discovery output must stay inside project artifacts')
    out.mkdir(parents=True,exist_ok=True)
    config=json.loads((root/'configs/discovery/learning-pilot-v1.json').read_bytes())
    data=build_dataset(config['seed'])
    dataset_dir=out/'dataset'
    if not dataset_dir.exists():freeze_dataset(dataset_dir,data)
    before=code_hash(root)
    results={}
    for strategy in ('learned','random','enumeration'):
        results[strategy]=run_pilot(root,dataset_dir,out/strategy,config,strategy=strategy)
    completed=all(row['complete'] and row['actual_evaluations']==36 for row in results.values())
    unchanged=before==code_hash(root)
    result={'exit_code':0 if completed and unchanged else 2,'code_hash':before,'source_unchanged':unchanged,
        'config_sha256':sha256_file(root/'configs/discovery/learning-pilot-v1.json'),
        'results':results,'actual_request_denominator':sum(r['actual_evaluations'] for r in results.values()),
        'baselines_are_actual_executions':True,'heldout_feedback_used':False,
        'scope':'Finite synthetic model learning; analytic candidate feedback is not Lean proof or real-cell science',
        'scientific_N_added':0,'kernel_checked':False,'full_project_complete':False}
    atomic_json(out/'manifest.json',result);return result
