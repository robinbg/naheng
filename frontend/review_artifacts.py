"""Read saved artifacts independently; this does not operate the UI."""
from pathlib import Path
import argparse, hashlib, json
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]

def review(directory):
 manifest_file=directory/'manifest.json'
 if not manifest_file.is_file():return {'run_id':directory.name,'status':'incomplete','reason':'manifest missing'}
 manifest=json.loads(manifest_file.read_text(encoding='utf-8'));forecast=json.loads((directory/'forecast.json').read_text(encoding='utf-8'));snapshots=json.loads((directory/'posterior.json').read_text(encoding='utf-8'));economics=json.loads((directory/'economics.json').read_text(encoding='utf-8'));hashes=json.loads((directory/'artifact_hashes.json').read_text(encoding='utf-8'))
 mismatches=[]
 for key,filename in manifest['artifact_index'].items():
  path=directory/filename
  if not path.is_file():mismatches.append('missing:'+key)
  elif hashlib.sha256(path.read_bytes()).hexdigest()!=hashes.get(key):mismatches.append('hash:'+key)
 sensors=pq.read_table(directory/'sensor_trace.parquet').to_pylist();actions=pq.read_table(directory/'actions.parquet').to_pylist();cashflows=pq.read_table(directory/'cashflows.parquet').to_pylist();decisions=json.loads((directory/'decisions.json').read_text(encoding='utf-8'));report=(directory/'report.html').read_text(encoding='utf-8')
 findings={
 'artifact_hashes_match':not mismatches,
 'run_manifest_complete':manifest['complete'] is True,
 'synthetic_identity_explicit':manifest['provenance_type']=='synthetic' and forecast['provenance_type']=='synthetic',
 'forecast_latest_snapshot':forecast['snapshot_id']==snapshots[-1]['snapshot_id'],
 'forecast_policy_and_environment_present':bool(forecast['query']['future_policy_id'] and forecast['query']['environment_id'] and forecast['query']['endpoint_protocol']),
 'no_independent_risk_certificate':forecast['risk']['risk_certificate'] is False,
 'unknown_fire_and_plating':all(forecast['risk']['events'][name]['status']=='unknown' and forecast['risk']['events'][name]['probability'] is None for name in ['fire','sodium_plating']),
 'posterior_matches_observations':len(sensors)==len(snapshots),
 'executed_action_decision_cashflow_counts':len(actions)==len(cashflows)==len(decisions),
 'distinct_execution_ids':len({item['execution_id'] for item in cashflows})==len(cashflows),
 'cashflow_recomputes':abs(sum(item['net_cashflow'] for item in cashflows)-economics['net_cashflow'])<1e-12,
 'cashflow_energy_recomputes':abs(sum(item['energy_J'] for item in cashflows)-economics['energy_J'])<1e-8,
 'cashflow_actual_prices':all(abs(item['exported_energy_J']/3600000*item['sell_price_per_kWh']-item['sales'])<1e-12 and abs(item['imported_energy_J']/3600000*item['buy_price_per_kWh']-item['purchases'])<1e-12 for item in cashflows),
 'report_current_run_and_scope':directory.name in report and '合成研究运行' in report and '非真实电芯寿命' in report,
 'report_current_cashflow':str(economics['net_cashflow']) in report,
 'no_full_lifecycle_claim':economics['lifecycle_complete'] is False,
 'inventory_checks_saved':all('inventory_residual_mol' in item for item in actions)
 }
 return {'run_id':directory.name,'review_mode':'existing_evidence_review_no_ui_reoperation','status':'passed_artifact_scope' if all(findings.values()) else 'failed','findings':findings,'hash_mismatches':mismatches,'counts':{'observations':len(sensors),'snapshots':len(snapshots),'actions':len(actions),'forecast_paths':len(forecast['paths'])},'manifest_hash':hashlib.sha256(manifest_file.read_bytes()).hexdigest(),'report_hash':hashlib.sha256((directory/'report.html').read_bytes()).hexdigest(),'actual_energy_J':economics['energy_J'],'actual_net_cashflow_CNY':economics['net_cashflow'],'limits':['no independent real UI operation in this review','synthetic channel only','no Lean build or real-data validation','complete lifecycle and research core remain incomplete']}

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
 if '/' in args.run or '\\' in args.run or not args.run.startswith('nh-'):raise ValueError('Controlled RunID required')
 result=review(ROOT/'artifacts/runs'/args.run);args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['status']=='passed_artifact_scope' else 2 if result['status']=='incomplete' else 1)
