"""Independent saved-artifact review. This does not perform browser actions."""
import argparse,csv,hashlib,json,math
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[1]

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def controlled(base,name):
 path=(base/name).resolve()
 if not path.is_relative_to(base.resolve()) or not path.is_file():raise ValueError('Missing controlled review artifact: '+name)
 return path

def equivalent_csv(directory,name,rows,numeric):
 with controlled(directory,name).open(encoding='utf-8',newline='') as stream:export=list(csv.DictReader(stream))
 if len(export)!=len(rows):return False
 for original,row in zip(rows,export):
  for key in numeric:
   value=original.get(key)
   if value is None:
    if row.get(key)!='':return False
   elif not math.isclose(float(row[key]),float(value),rel_tol=1e-12,abs_tol=1e-12):return False
 return True

def review(run_id):
 directory=ROOT/'artifacts/runs'/run_id
 load=lambda name:json.loads(controlled(directory,name).read_text(encoding='utf-8'))
 manifest=load('manifest.json');index=load('source_index.json');hashes=load('artifact_hashes.json');forecast=load('forecast.json');posterior=load('posterior.json');economics=load('economics.json');package=load('model_package.json');decisions=load('decisions.json')
 mismatches=[]
 for name,expected in index['files'].items():
  if digest(controlled(directory/'source_snapshot',name))!=expected:mismatches.append('source:'+name)
 for key,name in manifest['artifact_index'].items():
  if digest(controlled(directory,name))!=hashes.get(key):mismatches.append('artifact:'+key)
 calculated=hashlib.sha256()
 for folder in ('src','configs','formal','frontend/src','model_packages'):
  for path in sorted((directory/'source_snapshot'/folder).rglob('*')):
   if path.is_file() and '__pycache__' not in path.parts and '.lake' not in path.parts:
    calculated.update(path.relative_to(directory/'source_snapshot').as_posix().encode());calculated.update(path.read_bytes())
 sensors=pq.read_table(controlled(directory,'sensor_trace.parquet')).to_pylist();actions=pq.read_table(controlled(directory,'actions.parquet')).to_pylist();cash=pq.read_table(controlled(directory,'cashflows.parquet')).to_pylist();report=controlled(directory,'report.html').read_text(encoding='utf-8')
 checks={
 'all_frozen_source_and_output_hashes_match':not mismatches,
 'frozen_source_code_hash_matches_manifest':calculated.hexdigest()==manifest['code_hash']==index['code_hash'],
 'frozen_dependency_lock_matches_manifest':digest(controlled(directory/'source_snapshot','uv.lock'))==manifest['dependency_lock_hash'],
 'manifest_is_complete_and_synthetic':manifest['complete'] is True and manifest['provenance_type']=='synthetic',
 'model_package_posterior_forecast_manifest_revision_match':package['parameter_revision']==posterior[-1]['parameter_revision']==forecast['parameter_revision']==manifest['parameter_revision'],
 'forecast_uses_latest_posterior':forecast['snapshot_id']==posterior[-1]['snapshot_id'],
 'forecast_explicit_policy_environment_endpoint':all(forecast['query'].get(name) for name in ['future_policy_id','environment_id','endpoint_protocol']),
 'sensor_csv_matches_parquet':equivalent_csv(directory,'sensor_trace.csv',sensors,['timestamp_s','voltage_V','current_A','temperature_K']),
 'action_csv_matches_parquet':equivalent_csv(directory,'actions.csv',actions,['start_s','duration_s','current_A','power_W','thermal_W','executed_duration_s','energy_J','inventory_residual_mol']),
 'cashflow_csv_matches_parquet':equivalent_csv(directory,'cashflows.csv',cash,['start_s','duration_s','energy_J','exported_energy_J','imported_energy_J','thermal_electric_energy_J','sales','purchases','thermal_cost','net_cashflow','buy_price_per_kWh','sell_price_per_kWh']),
 'observations_and_posterior_lengths_match':len(sensors)==len(posterior),
 'decision_action_cashflow_lengths_match':len(decisions)==len(actions)==len(cash),
 'unique_execution_ids':len({row['execution_id'] for row in cash})==len(cash),
 'actual_cashflow_recomputes':abs(sum(row['net_cashflow'] for row in cash)-economics['net_cashflow'])<1e-12,
 'actual_energy_recomputes':abs(sum(row['energy_J'] for row in cash)-economics['energy_J'])<1e-8,
 'purchase_sales_thermal_cost_formula_matches_execution':all(abs(row['sales']-row['exported_energy_J']/3600000*row['sell_price_per_kWh'])<1e-12 and abs(row['purchases']-row['imported_energy_J']/3600000*row['buy_price_per_kWh'])<1e-12 and abs(row['thermal_cost']-row['thermal_electric_energy_J']/3600000*row['buy_price_per_kWh'])<1e-12 for row in cash),
 'unsupported_events_unknown':all(forecast['risk']['events'][name]['status']=='unknown' and forecast['risk']['events'][name]['probability'] is None for name in ['fire','sodium_plating']),
 'no_operational_risk_certificate':forecast['risk']['risk_certificate'] is False,
 'no_full_lifecycle_claim':economics['lifecycle_complete'] is False,
 'report_current_identity_value_and_scope':run_id in report and str(economics['net_cashflow']) in report and '非真实电芯寿命' in report
 }
 return {'run_id':run_id,'status':'passed_artifact_scope' if all(checks.values()) else 'failed','review_mode':'independent_existing_evidence_review_no_ui_reoperation','pyarrow_version':pa.__version__,'checks':checks,'mismatches':mismatches,'counts':{'observations':len(sensors),'posterior':len(posterior),'actions':len(actions),'forecast_paths':len(forecast['paths'])},'actual_energy_J':economics['energy_J'],'actual_net_cashflow_CNY':economics['net_cashflow'],'source_index_hash':digest(directory/'source_index.json'),'report_hash':digest(directory/'report.html'),'limits':['synthetic channel only','UI operations require root operator evidence','formal core, real data and independent lifetime/risk/benefit validation not complete']}

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
 if not args.run.startswith('nh-') or '/' in args.run or '\\' in args.run:raise ValueError('Controlled RunID required')
 result=review(args.run);args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['status']=='passed_artifact_scope' else 1)
