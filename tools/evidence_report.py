"""Read-only frozen evidence tables. No execution, inference of scientific N, or release approval."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import html
import json
import math
import os
from pathlib import Path,PurePosixPath
import re
import stat
import tempfile

MAX_BYTES=8*1024*1024
CATEGORIES={'synthetic','public_measurement','reference_simulation','replay','formal','software_validation','unknown'}
ROLES={'value','attempt_count','elapsed','cashflow','source_reported_sample_count'}
FORBIDDEN={'evaluator','.git','.ssh','.aws','.azure','.env','.venv','node_modules'}

class EvidenceError(ValueError):pass

def sha(data):return hashlib.sha256(data).hexdigest()

def no_reparse(path):
    for item in (path.absolute(),*path.absolute().parents):
        try:s=item.lstat()
        except FileNotFoundError:continue
        if item.is_symlink() or getattr(s,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):
            raise EvidenceError('Reparse input/output is not accepted')

def owned(root,name):
    if not isinstance(name,str) or '\\' in name or ':' in name or '\x00' in name:
        raise EvidenceError('Canonical project-relative artifact path required')
    parts=name.split('/')
    if len(parts)<2 or parts[0]!='artifacts' or any(not p or p in {'.','..'} or p!=p.rstrip(' .') for p in parts):
        raise EvidenceError('Only explicit project artifacts may be read')
    if any(p.casefold() in FORBIDDEN or p.casefold().startswith('.env') or PurePosixPath(p).suffix.lower() in {'.pem','.key','.p12','.pfx'} for p in parts):
        raise EvidenceError('Private evaluator or sensitive input is not report evidence')
    path=root.joinpath(*parts);no_reparse(path)
    if not path.resolve().is_relative_to(root):raise EvidenceError('Artifact path escaped project')
    return path

def read_json(path):
    no_reparse(path)
    if not path.is_file() or path.stat().st_size>MAX_BYTES:raise EvidenceError('Missing or oversized JSON evidence')
    data=path.read_bytes()
    if len(data)>MAX_BYTES:raise EvidenceError('JSON evidence grew past limit')
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise EvidenceError('Duplicate JSON key')
            out[k]=v
        return out
    def nonfinite(value):raise EvidenceError('Nonfinite JSON numeric value')
    def number(value):
        parsed=float(value)
        if not math.isfinite(parsed):raise EvidenceError('Nonfinite JSON numeric value')
        return parsed
    try:value=json.loads(data,object_pairs_hook=pairs,parse_constant=nonfinite,parse_float=number)
    except (UnicodeError,json.JSONDecodeError) as error:raise EvidenceError('Invalid JSON evidence') from error
    return data,value

def pointer(value,path):
    if not isinstance(path,list) or len(path)>20:raise EvidenceError('Explicit bounded JSON pointer required')
    try:
        for key in path:
            if type(key) is int and isinstance(value,list):value=value[key]
            elif isinstance(key,str) and isinstance(value,dict):value=value[key]
            else:raise EvidenceError('JSON pointer type mismatch')
    except (KeyError,IndexError) as error:raise EvidenceError('JSON pointer missing: '+repr(path)) from error
    return value

def scalar(value):
    if value is None or type(value) in (bool,int):return value
    if type(value) is float and math.isfinite(value):return value
    if isinstance(value,str) and len(value)<=4096:return value
    raise EvidenceError('Only bounded finite scalar table values are allowed')

def outcome(document,spec):
    mode=spec.get('kind');value=pointer(document,spec.get('pointer',[]))
    if mode=='record':return {'state':'recorded','source_value':None,'scope':'Evidence record only, not task completion'}
    if mode=='invocation':return {'state':'in_progress','source_value':None,'scope':'Started invocation snapshot; no terminal result supplied'}
    if mode=='command':
        if not isinstance(value,dict):raise EvidenceError('Command receipt object required')
        code=value.get('exit_code');native=value.get('native_exit_code')
        if any(v is not None and type(v) is not int for v in (code,native)):
            raise EvidenceError('Integer or unknown command/native exit code required')
        executed=value.get('executed');cleanup=value.get('resource_cleanup_confirmed');timed_out=value.get('timed_out')
        if any(v is not None and type(v) is not bool for v in (executed,cleanup,timed_out)):
            raise EvidenceError('Boolean or unknown execution/cleanup/timeout confirmation required')
        confirmed=False if executed is False else True if executed is True and native is not None else None
        consistent=(code==native) if code is not None and native is not None else None
        if executed is False:state='not_run'
        elif timed_out is True:state='unknown'
        elif consistent is False:state='unknown'
        elif code is None:state='unknown'
        elif code!=0:state='blocked' if code==2 else 'failed'
        elif confirmed is True and cleanup is True and timed_out is False:state='passed'
        else:state='unknown'
        return {'state':state,'source_value':code,'command_exit_observed':code,
            'execution_reported':executed,'execution_confirmed':confirmed,'native_exit_observed':native,
            'native_matches_command':consistent,'resource_cleanup_confirmed':cleanup,'timed_out':timed_out,
            'log_references':{key:value[key] for key in ('stdout','stderr','log') if isinstance(value.get(key),str) and len(value[key])<=4096 and '\n' not in value[key]},
            'scope':'Command exit observation and execution/cleanup confirmation are separate; no scientific or product certification'}
    if mode=='status':
        raw=scalar(value)
        states={'pass':'passed','passed':'passed','succeeded':'passed','completed':'passed','checked':'passed',
            'fail':'failed','failed':'failed','error':'failed','blocked':'blocked','todo':'not_started',
            'not_started':'not_started','unknown':'unknown','isolation_setup_unknown':'unknown',
            'in_progress':'in_progress','running':'in_progress','queued':'in_progress',
            'cancelled':'cancelled','withdrawn':'withdrawn','incomplete':'incomplete','partial':'incomplete'}
        state=states.get(raw.casefold(),'unknown') if isinstance(raw,str) else 'unknown'
        return {'state':state,'source_value':raw,'scope':'Source-reported status in its declared scope'}
    raise EvidenceError('Unknown outcome adapter')

def compile_data(root,selection):
    if selection.get('schema_version')!=1 or selection.get('draft') is not True:raise EvidenceError('Explicit draft schema required')
    entries=selection.get('entries');claims=selection.get('claims',[])
    if not isinstance(entries,list) or not 1<=len(entries)<=128 or not isinstance(claims,list) or len(claims)>128:raise EvidenceError('Bounded evidence/claim lists required')
    rows=[];seen=set();inputs=[];source_paths=set()
    for entry in entries:
        eid=entry.get('id')
        if not isinstance(eid,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',eid) or eid in seen:raise EvidenceError('Unique evidence ID required')
        seen.add(eid)
        category=entry.get('category')
        if category not in CATEGORIES:raise EvidenceError('Explicit evidence category required')
        path=owned(root,entry['path']);data,document=read_json(path)
        if path in source_paths:raise EvidenceError('One source file must use one evidence row')
        source_paths.add(path)
        expected=entry.get('sha256')
        if not isinstance(expected,str) or not re.fullmatch('[a-f0-9]{64}',expected) or sha(data)!=expected:raise EvidenceError('Frozen evidence hash mismatch: '+eid)
        basis=entry.get('category_basis')
        if not isinstance(basis,dict) or scalar(pointer(document,basis['pointer']))!=basis['equals']:raise EvidenceError('Category basis differs from frozen source')
        if len(entry.get('metrics',[]))>64 or len(entry.get('lineage',{}))>16:raise EvidenceError('Too many selected metrics or lineage fields')
        metrics=[]
        for metric in entry.get('metrics',[]):
            if metric.get('role') not in ROLES:raise EvidenceError('Metric role required; independent N is not inferred')
            value=scalar(pointer(document,metric['pointer']))
            metrics.append({'name':metric['name'],'value':value,'unit':metric['unit'],'role':metric['role'],'pointer':metric['pointer'],
                'independence_verified':False if metric['role']=='source_reported_sample_count' else None})
        lineage={name:{'value':scalar(pointer(document,location)),'pointer':location} for name,location in entry.get('lineage',{}).items()}
        rows.append({'id':eid,'task':entry['task'],'title':entry['title'],'category':category,
            'category_basis':basis,'source_path':entry['path'],'source_sha256':expected,'source_bytes':len(data),
            'outcome':outcome(document,entry['outcome']),'lineage':lineage,'metrics':metrics,'notes':entry.get('notes','')})
        inputs.append((path,expected))
    matrix=[];claim_ids=set()
    for claim in claims:
        cid=claim.get('id');refs=claim.get('evidence_ids')
        if not isinstance(cid,str) or cid in claim_ids or not isinstance(refs,list) or any(r not in seen for r in refs):raise EvidenceError('Claim evidence reference missing or duplicate')
        claim_ids.add(cid)
        matrix.append({'id':cid,'text':claim['text'],'evidence_ids':refs,'assessment':'not_adjudicated',
            'evidence_states':{r:next(row['outcome']['state'] for row in rows if row['id']==r) for r in refs},'limitations':claim['limitations']})
    for path,digest in inputs:
        if sha(read_json(path)[0])!=digest:raise EvidenceError('Evidence changed during report compilation')
    return {'schema_version':1,'title':selection['title'],'captured_utc':selection.get('captured_utc'),'draft':True,'R01_complete':False,'release_pass':False,
        'rows':rows,'claims':matrix,'required_incomplete':selection.get('required_incomplete',[]),
        'artifact_counts_by_state':dict(Counter(r['outcome']['state'] for r in rows)),
        'artifact_counts_by_category':dict(Counter(r['category'] for r in rows)),
        'count_scope':'Counts are evidence files, not independent trajectories, cells, or scientific N',
        'independent_scientific_N':None,'comparative_advantage':None,'novelty_assessment':'not_performed_no_literature_claim',
        'limitations':['Draft evidence inventory; claim truth requires independent review.',
            'No risk confidence bound, causal effect, comparative profit, or literature novelty is computed.',
            'Categories remain separate; replay never creates a new independent sample.',
            'Unfinished X02, X03, X04 and R00 prevent R01/release completion.']}

def render(data):
    esc=lambda x:html.escape(str(x),quote=True)
    show=lambda x:esc(json.dumps(x,ensure_ascii=False,allow_nan=False))
    body=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>'+esc(data['title'])+'</title><style>body{font:16px system-ui,sans-serif;line-height:1.55;max-width:1450px;margin:2rem auto;padding:0 1rem;color:#17242b;background:#f6f8fa}h1{font-size:1.8rem}table{width:100%;border-collapse:collapse;background:white;margin:1rem 0}th,td{border:1px solid #d6dfe4;padding:.65rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}code{font-size:.8rem}.notice{border-left:5px solid #b16b00;background:#fff1d3;padding:1rem}.scroll{overflow:auto}.muted{color:#53616a}dt{font-weight:bold}dd{margin-bottom:.5rem}</style>',
        '<h1>'+esc(data['title'])+'</h1><p class="notice">研究草稿 · R01 未完成 · release_pass=false。工件状态不能替代科学、产品或交付验收。</p>',
        '<p>输入冻结于 '+esc(data['captured_utc'])+'；运行中的条目只表示该快照。</p><p>'+esc(data['count_scope'])+'</p><p>按来源：'+show(data['artifact_counts_by_category'])+'；按状态：'+show(data['artifact_counts_by_state'])+'</p>',
        '<h2>已冻结证据及数值血缘</h2><div class="scroll"><table><thead><tr><th>工件 / 任务</th><th>类别 / 原状态</th><th>数值与单位</th><th>Run / 版本血缘</th><th>路径 / SHA256 / 限制</th></tr></thead><tbody>']
    for row in data['rows']:
        metrics='<br>'.join(esc(m['name'])+' = '+show(m['value'])+' '+esc(m['unit'])+' <span class="muted">['+esc(m['role'])+'; '+show(m['pointer'])+']</span>' for m in row['metrics']) or '未提取数值'
        lineage='<br>'.join(esc(k)+' = <code>'+show(v['value'])+'</code>' for k,v in row['lineage'].items()) or '该文件未提供；不推断'
        confirmations=''
        if 'command_exit_observed' in row['outcome']:
            confirmations='<br>'+ '<br>'.join(esc(key)+' = '+('UNKNOWN' if row['outcome'][key] is None else show(row['outcome'][key])) for key in ('command_exit_observed','execution_confirmed','native_exit_observed','resource_cleanup_confirmed','timed_out'))
            if row['outcome']['log_references']:confirmations+='<br>原日志引用：<code>'+show(row['outcome']['log_references'])+'</code>'
        body.append('<tr><td>'+esc(row['id'])+' / '+esc(row['task'])+'<br>'+esc(row['title'])+'</td><td>'+esc(row['category'])+'<br>'+esc(row['outcome']['state'])+' / '+show(row['outcome']['source_value'])+'<br>'+esc(row['outcome']['scope'])+confirmations+'</td><td>'+metrics+'</td><td>'+lineage+'</td><td><code>'+esc(row['source_path'])+'<br>'+esc(row['source_sha256'])+'</code><br>'+esc(row['notes'])+'</td></tr>')
    body.extend(['</tbody></table></div><h2>主张—证据矩阵</h2><p>主张文字是待审内容，不因存在工件或命令退出 0 自动成为结论。</p><table><tr><th>待审主张</th><th>证据及状态</th><th>限制</th></tr>'])
    for claim in data['claims']:body.append('<tr><td>'+esc(claim['id'])+'：'+esc(claim['text'])+'<br>not_adjudicated</td><td>'+show(claim['evidence_states'])+'</td><td>'+esc(claim['limitations'])+'</td></tr>')
    body.append('</table><h2>未完成的必需工作</h2><ul>')
    for item in data['required_incomplete']:body.append('<li>'+esc(item)+'</li>')
    body.append('</ul><h2>解释限制</h2><ul>')
    for item in data['limitations']:body.append('<li>'+esc(item)+'</li>')
    body.append('</ul><p>HTML、JSON 表与主张矩阵由同一冻结输入生成；详见 generation.json。</p></html>')
    return ''.join(body)

def build_report(project_root,frozen_path,output):
    no_reparse(Path(project_root));root=Path(project_root).resolve()
    no_reparse(Path(frozen_path))
    frozen=owned(root,Path(frozen_path).resolve().relative_to(root).as_posix())
    frozen_bytes,selection=read_json(frozen)
    output=Path(output);no_reparse(output)
    if output.exists() or not output.resolve().is_relative_to(root/'artifacts') or output.resolve()==root/'artifacts':raise EvidenceError('New project artifact output required')
    data=compile_data(root,selection)
    payloads={'tables.json':json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),
        'claims.json':json.dumps(data['claims'],ensure_ascii=False,indent=2,allow_nan=False),
        'report.html':render(data),'selection.json':frozen_bytes}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.r01-',dir=output.parent) as temporary:
        stage=Path(temporary)/'report';stage.mkdir()
        for name,text in payloads.items():
            if isinstance(text,bytes):(stage/name).write_bytes(text)
            else:(stage/name).write_text(text,encoding='utf-8')
        receipt={'schema_version':1,'selection_path':frozen.relative_to(root).as_posix(),'selection_sha256':sha(frozen_bytes),
            'generator_sha256':sha(Path(__file__).read_bytes()),'R01_complete':False,'release_pass':False,
            'outputs':{name:sha((stage/name).read_bytes()) for name in payloads},
            'sources':{r['source_path']:r['source_sha256'] for r in data['rows']}}
        (stage/'generation.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        if output.exists():raise EvidenceError('Output was created by another operation')
        os.rename(stage,output)
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--selection',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();result=build_report(args.root,args.selection,args.out)
    print(json.dumps({'outputs':result['outputs'],'R01_complete':False,'release_pass':False}))
