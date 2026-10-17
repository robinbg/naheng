from pathlib import Path
import hashlib,importlib.util,json,xml.etree.ElementTree as ET
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
PACK=ROOT/'artifacts/handoff/r01-learning-figures-20261016-a'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
assert sha(PACK/'handoff.json')=='07a4d8e30207371f51c17a33ede9753e88ca15c9bf595ee7998a4ec596bfbc8d'
h=read(PACK/'handoff.json')
for name,m in h['files'].items():assert sha(PACK/name)==m['sha256'] and (PACK/name).stat().st_size==m['bytes']
tool=PACK/'candidate/tools/render_learning_evidence.py'
assert sha(tool)=='0ab7e482a70d22b53c0e431d77627074eea2a63d9687a807d52f58cf17920cb7'
spec=importlib.util.spec_from_file_location('reviewed_figures',tool);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
cases=[]
for selection,name in (('real-two-versions.json','historical'),('current-two-arms.json','current')):
    target=HERE/name;module.build(ROOT,PACK/selection,target)
    original=PACK/('real-two-version-figures' if name=='historical' else 'current-two-arm-figures')
    for f in ('learning.svg','ledger-summary.json','selection.json'):assert (target/f).read_bytes()==(original/f).read_bytes()
    data=read(target/'ledger-summary.json')
    assert data['comparative_advantage'] is None and data['scientific_N_added']==0 and data['A03_complete'] is False
    assert all(a['total_requests']==36 for a in data['arms'])
    if name=='historical':assert data['same_frozen_code'] is False
    else:assert data['same_frozen_code'] is True and data['same_world'] is True
    elem=ET.fromstring((target/'learning.svg').read_text(encoding='utf-8'))
    assert len(elem.findall('{http://www.w3.org/2000/svg}circle'))==72
    for arm in data['arms']:
        cp=read(ROOT/arm['source_files']['checkpoint']['path'])['state']['events']
        for row,event in zip(arm['queries'],cp):
            assert row['status']==event['result']['status'] and row['cost_s']==event['result']['cost_s']
            assert 'utility' not in row and row['source_run_id']==event['result']['run_id']
        assert arm['known_cost_subtotal_s']==sum(r['cost_s'] for r in arm['queries'] if r['cost_s'] is not None)
    cases.append({'name':name,'same_code':data['same_frozen_code'],'total_requests':sum(a['total_requests'] for a in data['arms']),
                  'outer_states':[a['outer_command']['state'] for a in data['arms']]})
# Exercise both XML text positions: visible label and escaped JSON metadata.
data['arms'][0]['label']='<image href="x" onload="alert(1)"/>'
data['arms'][0]['queries'][0]['source_run_id']='</title><script>alert(2)</script>'
xml=module.render_svg(data);tree=ET.fromstring(xml)
assert not tree.findall('.//{http://www.w3.org/2000/svg}script') and not tree.findall('.//{http://www.w3.org/2000/svg}image')
assert '&lt;image' in xml and '&lt;/title&gt;&lt;script&gt;' in xml
# A nonzero confirmed outcome is not a success assertion; missing fields remain UNKNOWN.
assert module.receipt_confirmation({'exit_code':2})['state']=='UNKNOWN'
assert module.receipt_confirmation({'executed':True,'native_exit_code':2,'exit_code':2,'resource_cleanup_confirmed':True,'timed_out':False})['observed_exit_code']==2
result={'status':'PASS_FROZEN_FIGURE_SCOPE','file_hash_checks':len(h['files']),'datasets':cases,'byte_reproduced_artifacts':6,
        'svg_injection_controls_passed':True,'original_cost_and_status_unchanged':True,
        'per_case_physics_revalidated':False,'scientific_N_added':0,'comparative_advantage':None,'R01_complete':False}
(HERE/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
