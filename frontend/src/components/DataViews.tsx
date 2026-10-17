import { valueText } from '../api';
import type { Dictionary, Sensor } from '../api';
export function Facts({data}:{data:Dictionary | undefined}) {if(!data) return <p className="empty">尚无已保存的计算结果。</p>; return <dl className="facts">{Object.entries(data).map(([key,value])=><div key={key}><dt>{key}</dt><dd>{valueText(value)}</dd></div>)}</dl>;}
export function RawData({title,data}:{title:string;data:unknown}) {return <details><summary>{title}</summary><pre>{data===undefined?'未知：当前运行尚未提供该工件。':JSON.stringify(data,null,2)}</pre></details>;}
export function Metric({label,value,unit,note}:{label:string;value:unknown;unit?:string;note?:string}) {return <div className="metric"><span>{label}</span><strong>{valueText(value)}<small>{value!==null && value!==undefined && unit?` ${unit}`:''}</small></strong>{note&&<p>{note}</p>}</div>;}
export function SensorChart({rows,field,label}:{rows:Sensor[] | undefined;field:'voltage_V'|'temperature_K';label:string}) {
 if(!rows?.length) return <p className="empty">尚无传感器轨迹。</p>;
 const finite=rows.filter(row=>Number.isFinite(row[field])&&Number.isFinite(row.timestamp_s)); if(!finite.length) return <p>未知：观测值不可用。</p>;
 const values=finite.map(row=>row[field]); const times=finite.map(row=>row.timestamp_s); const low=Math.min(...values), high=Math.max(...values); const minT=Math.min(...times),maxT=Math.max(...times); const span=Math.max(high-low,0.0001);
 const points=finite.map(row=>`${60+(row.timestamp_s-minT)/(maxT-minT||1)*640},${180-(row[field]-low)/span*140}`).join(' ');
 return <figure className="chart"><figcaption>{label} · 实际保存的观测</figcaption><svg viewBox="0 0 740 230" role="img" aria-label={label}><line x1="60" y1="180" x2="705" y2="180" stroke="#a5b5c6"/><line x1="60" y1="40" x2="60" y2="180" stroke="#a5b5c6"/><polyline points={points} fill="none" stroke="#167a87" strokeWidth="2.5"/><text x="4" y="46">{valueText(high,3)}</text><text x="4" y="184">{valueText(low,3)}</text><text x="60" y="211">{valueText(minT)} s</text><text x="650" y="211">{valueText(maxT)} s</text></svg></figure>;
}
