import {useEffect, useState} from 'react';
import {request, valueText} from '../api';
import type {Dictionary, Sensor} from '../api';
import {Metric, RawData, SensorChart} from './DataViews';

interface Packet extends Dictionary {dataset_id:string;row_count:number;observations:Sensor[];analysis:Dictionary;}
export default function DatasetPanel(){
 const [records,setRecords]=useState<Dictionary[]>([]);
 const [selected,setSelected]=useState(()=>localStorage.getItem('naheng-dataset')??'');
 const [packet,setPacket]=useState<Packet>();const [error,setError]=useState('');const [busy,setBusy]=useState(false);
 const [text,setText]=useState('');const [filename,setFilename]=useState('observations.csv');
 const [source,setSource]=useState('');const [chemistry,setChemistry]=useState('unmapped_sodium');
 const [sign,setSign]=useState('positive_discharge');const [provenance,setProvenance]=useState('public_measurement');
 async function refresh(){setRecords(await request<Dictionary[]>('/api/datasets'));}
 useEffect(()=>{void refresh().catch(e=>setError(String(e)));},[]);
 useEffect(()=>{localStorage.setItem('naheng-dataset',selected);setPacket(undefined);if(!selected)return;
  let alive=true;request<Packet>(`/api/datasets/${encodeURIComponent(selected)}`).then(p=>{if(alive){setPacket(p);setError('');}}).catch(e=>{if(alive)setError(String(e));});
  return()=>{alive=false;};},[selected]);
 async function ingest(){setBusy(true);setError('');try{
  const p=await request<Packet>('/api/datasets/import',{filename,source,chemistry_id:chemistry,
   provenance_type:provenance,current_sign:sign,units:{timestamp_s:'s',voltage_V:'V',current_A:'A',temperature_K:'K'},csv_text:text});
  setSelected(p.dataset_id);await refresh();
 }catch(e){setError(`导入失败：${String(e)}`);}finally{setBusy(false);}}
 return <section aria-label="观测数据导入与核算"><h2>观测数据导入与核算</h2>
  <p>CSV 表头：timestamp_s,voltage_V,current_A,temperature_K。单位为 s、V、A、K，单个连续时间段，最多 5000 行 / 2 MiB。来源由你声明；尚无模型映射时，保存与电气核算仍可完成，状态、容量与寿命保持未知。</p>
  <form className="run-form" onSubmit={e=>{e.preventDefault();void ingest();}}>
   <label>观测 CSV 文件<input aria-label="观测 CSV 文件" type="file" accept=".csv,text/csv" onChange={async e=>{const f=e.target.files?.[0];if(!f)return;if(f.size>2*1024*1024){setError('文件超过 2 MiB');return;}setFilename(f.name);try{setText(await f.text());}catch(err){setError(String(err));}}}/></label>
   <label>数据来源<input aria-label="数据来源" value={source} onChange={e=>setSource(e.target.value)} required maxLength={500}/></label>
   <label>数据化学身份<input aria-label="数据化学身份" value={chemistry} onChange={e=>setChemistry(e.target.value)} required pattern="[a-zA-Z0-9_.-]+" maxLength={80}/></label>
   <label>来源类型<select aria-label="来源类型" value={provenance} onChange={e=>setProvenance(e.target.value)}><option value="public_measurement">测量数据 · 用户声明</option><option value="synthetic">合成观测</option><option value="reference_simulation">参考仿真观测</option></select></label>
   <label>原数据电流正号<select aria-label="原数据电流正号" value={sign} onChange={e=>setSign(e.target.value)}><option value="positive_discharge">正值表示放电</option><option value="positive_charge">正值表示充电</option></select></label>
   <label>CSV 观测内容<textarea aria-label="CSV 观测内容" value={text} onChange={e=>setText(e.target.value)} required rows={5}/></label>
   <button disabled={busy} type="submit">{busy?'正在导入…':'导入并核算观测'}</button>
  </form>
  {error&&<p role="alert" className="error">{error}</p>}
  <label>已保存数据<select aria-label="已保存数据" value={selected} onChange={e=>setSelected(e.target.value)}><option value="">请选择数据</option>{records.map(p=><option key={String(p.dataset_id)} value={String(p.dataset_id)}>{String(p.filename)} · {String(p.dataset_id)}</option>)}</select></label>
  <button className="secondary" onClick={()=>void refresh().catch(e=>setError(String(e)))}>刷新数据记录</button>
  {packet&&<div data-testid="dataset-result"><p>数据 ID：<code data-testid="dataset-id">{packet.dataset_id}</code> · 已保存 {packet.row_count} 行 · {valueText(packet.provenance_type)} · {valueText(packet.provenance_verification)}</p>
   <div className="metrics"><Metric label="观测放电通量" value={packet.analysis.discharge_throughput_Ah} unit="Ah"/><Metric label="观测放电端口能量" value={packet.analysis.discharge_port_energy_J} unit="J"/><Metric label="容量 / SOH / RUL" value={undefined}/></div>
   <p>{valueText(packet.analysis.unknown_reason)}</p><SensorChart rows={packet.observations} field="voltage_V" label="导入观测电压 / V"/>
   {(['source','observations','analysis','report'] as const).map(key=><a className="download" key={key} href={`/api/datasets/${packet.dataset_id}/artifacts/${key}`} download>{({source:'导出原始 CSV',observations:'导出规范 CSV',analysis:'导出核算 JSON',report:'下载数据 HTML 报告'})[key]}</a>)}
   <a className="download" href={`/api/datasets/${packet.dataset_id}/report-preview`} target="_blank" rel="noreferrer">打开数据报告预览</a>
   <RawData title="当前上传观测的真实核算" data={packet.analysis}/><RawData title="模型接入状态与原因" data={packet.model_assimilation}/>
  </div>}
 </section>;
}
