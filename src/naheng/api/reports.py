"""Reports expose immutable run references and escaped measured-data summaries."""
import html
import json

def run_report_reference(run_id, resolve_artifact):
    resolve_artifact(run_id, 'report')
    return {'run_id': run_id, 'url': f'/api/runs/{run_id}/artifacts/report'}

def dataset_report(packet):
    metadata = {key: packet[key] for key in ('dataset_id', 'code_hash', 'row_count', 'source',
        'filename', 'chemistry_id', 'provenance_type', 'provenance_verification', 'source_current_sign',
        'canonical_current_sign', 'source_csv_sha256', 'mode', 'model_assimilation')}
    escape = lambda value: html.escape(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>钠衡数据核算报告</title>'
        '<style>body{max-width:70rem;margin:2rem auto;font-family:sans-serif}pre{white-space:pre-wrap}</style>'
        '<h1>钠衡 · 导入观测电气核算</h1><p>来源由用户声明，尚未独立核验。'
        '数值由当前上传观测计算；容量、SOH、RUL、运营风险和收益保持未知。</p>'
        '<h2>来源与版本</h2><pre>' + escape(metadata) + '</pre>'
        '<h2>实际核算与未知原因</h2><pre>' + escape(packet['analysis']) + '</pre></html>')
