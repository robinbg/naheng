import type { Job } from '../api';
export default function RunSelector({jobs,selected,onSelect,onRefresh}:{jobs:Job[];selected:string;onSelect:(id:string)=>void;onRefresh:()=>void}) {
 return <div className="run-selector"><label htmlFor="run-select">运行记录</label><select id="run-select" value={selected} onChange={e=>onSelect(e.target.value)}><option value="">选择运行</option>{jobs.map(job=><option key={job.run_id} value={job.run_id}>{job.run_id.slice(0,15)} · {job.state} · {job.config.mode === 'replay'?'回放':job.config.mode === 'batch'?'批量':'交互'}</option>)}</select><button className="secondary" onClick={onRefresh}>刷新记录</button></div>;
}
