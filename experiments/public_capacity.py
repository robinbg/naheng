"""Trusted deterministic observed-capacity diagnostic, never model fitting."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import sys
import time

REVIEWED_SCANNER_SHA256='0f5f3e7f60497604c485a1fc430e5386170374b79cdee2933379ed900651e381'
FROZEN_MANIFEST_SHA256='c86f34c674f77fe7972f614ad1b88d0cf37531dc51d457479b17b4f837a4b539'


def existing_voltage_module(root):
    path=root/'experiments/public_sodium.py'
    spec=importlib.util.spec_from_file_location('naheng_existing_public_sodium_phase',path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module


def run_capacity_phase(root,manifest,output):
    root=Path(root).resolve()
    manifest=(root/Path(manifest)).resolve()
    output=(root/Path(output)).resolve()
    if not manifest.is_relative_to(root) or not output.is_relative_to(root/'artifacts') or manifest.is_relative_to(output):
        raise ValueError('Registered input and fresh controlled artifacts output required')
    if any(p.casefold()=='evaluator' for p in output.parts+manifest.parts):
        raise ValueError('Evaluator storage cannot be used as the public diagnostic source/output')
    output.mkdir(parents=True,exist_ok=False)
    voltage=existing_voltage_module(root)
    from naheng.runtime.artifacts import code_hash
    before=code_hash(root)
    own=Path(__file__).resolve()
    own_hash=voltage.sha256(own)
    started=time.monotonic()
    report={'schema_version':1,'phase':'capacity','status':'blocked','exit_code':2,
        'utc':datetime.now(timezone.utc).isoformat(),'execution_completed':False,
        'D02_complete':False,'scientific_external_acceptance_passed':False,'UI_tested':False,
        'new_model_fits':0,'heldout_tuning':False,'new_independent_scientific_N':0,
        'code_hash':before,'module_source_sha256':own_hash,'source_current':False,
        'members':[],'missing_dependencies':[],
        'scope':'Observed fixed-protocol conditional capacity estimates; distinct from voltage prediction and physical material mapping'}
    bindings={}
    try:
        if voltage.sha256(manifest)!=FROZEN_MANIFEST_SHA256:
            raise voltage.InputDependencyError('The exact original frozen cohort is required')
        split,sources,bindings=voltage.validate_inputs(root,manifest)
        scanner_path=root/'src/naheng/data/protocol_capacity_measurement.py'
        if not scanner_path.is_file() or voltage.sha256(scanner_path)!=REVIEWED_SCANNER_SHA256:
            raise voltage.InputDependencyError('Reviewed observed-capacity scanner bytes are required')
        bindings[scanner_path.relative_to(root).as_posix()]=REVIEWED_SCANNER_SHA256
        from naheng.data.protocol_capacity_measurement import scan_csv
        reports=[]
        for member in split['members']:
            view=voltage.read_json(voltage.within(root,member['view_manifest']['path']))
            result=scan_csv(voltage.within(root,member['raw']['path']),member['nominal_capacity_Ah'],
                view['current_sign_evidence']['vendor_current_sign'])
            if (result['rows']!=member['row_count'] or result['raw_sha256']!=member['raw']['sha256']
                or not result['raw_unchanged'] or result['status'] not in ('computed','unknown')):
                raise voltage.InputDependencyError('Complete original capacity member binding changed: '+member['member_id'])
            result.update(source_id=member['source_id'],member_id=member['member_id'],role=member['role'],
                author_group=member['author_group'],raw=member['raw'],view_manifest=member['view_manifest'],
                source_protocol=member['protocol'],source_provenance='public_measurement',role_unchanged=True,
                nominal_metadata_scope='Author nominal rating; never substituted for measured capacity',
                duplicate_content=any(m['raw']['sha256']==member['raw']['sha256'] and m['member_id']!=member['member_id'] for m in split['members']))
            reports.append(result)
        if any(voltage.sha256(voltage.within(root,path))!=digest for path,digest in bindings.items()):
            raise voltage.InputDependencyError('Registered source bytes changed during capacity diagnostic')
        if code_hash(root)!=before or voltage.sha256(own)!=own_hash:
            raise voltage.InputDependencyError('Source version changed during capacity diagnostic')
        report.update(status='completed_partial_scientific_scope',exit_code=0,execution_completed=True,
            source_current=True,source_provenance='public_measurement',members=reports,
            original_row_count=split['total_rows'],complete_member_count=len(reports),
            unique_raw_content_count=len({m['raw']['sha256'] for m in split['members']}),
            frozen_role_row_counts=split['role_row_counts'],frozen_cohort_id=split['cohort_id'],
            scanner_sha256=REVIEWED_SCANNER_SHA256,manifest_sha256=FROZEN_MANIFEST_SHA256,
            computed_file_count=sum(m['status']=='computed' for m in reports),
            unknown_file_count=sum(m['status']=='unknown' for m in reports),
            physical_independence_status=split['physical_independence_status'],IID=split['IID'],
            independent_physical_cell_count=split['confirmed_independent_physical_cells'],
            registered_bindings=bindings,protected_inputs_unchanged=True,
            scientific_limits=['Conditional measured-current boundary reconstruction, not precise physical capacity/certificate',
                'Actual onset and true first cutoff unknown between samples; interpolation assumptions and conditional spans retained',
                'Instrument cumulative capacity can share current sensor; not independent truth',
                'Unknown preparations remain unknown; no failed member is converted to zero or dropped',
                'No SOC/SOH/RUL/EIS/accident/risk/profit target inferred; no reference rescaling',
                'This phase exit0 means diagnostic calculation completed; existing voltage exit2 and material mapping UNKNOWN remain original aggregate gates'])
    except (voltage.InputDependencyError,KeyError,ValueError,OSError,ImportError) as error:
        report['missing_dependencies'].append(str(error))
        report['failure_type']=type(error).__name__
        report['registered_bindings']=bindings
    report.update(elapsed_s=time.monotonic()-started,code_hash_after=code_hash(root))
    voltage.write_json(output/'report.json',report)
    (output/'worker-source.py.txt').write_bytes(own.read_bytes())
    voltage.write_json(output/'manifest.json',{'phase':'capacity','exit_code':report['exit_code'],
        'execution_completed':report['execution_completed'],'D02_complete':False,
        'scientific_external_acceptance_passed':False,'code_hash':before,
        'report':{'path':(output/'report.json').relative_to(root).as_posix(),'sha256':voltage.sha256(output/'report.json')},
        'module_source_sha256':own_hash,'scope':report['scope']})
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.root.resolve()/'src'))
    result=run_capacity_phase(args.root,args.manifest,args.output)
    print(json.dumps({'phase':'capacity','exit_code':result['exit_code'],
        'execution_completed':result['execution_completed'],'D02_complete':False}))
    return result['exit_code']

if __name__=='__main__':raise SystemExit(main())
