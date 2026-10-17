import {useEffect,useRef,useState} from 'react';
import type {FormEvent} from 'react';
import {request} from '../api';
import type {Dictionary,Forecast,Results} from '../api';
import {Facts,RawData} from './DataViews';

interface ForecastJob {run_id:string;state:string;progress:number;error:string|null;cancel:boolean;updated:string;}
const terminal=new Set(['succeeded','failed','cancelled']);

export default function ConditionalForecastPanel({results}:{results:Results}) {
 const snapshot=results.snapshots?.at(-1);
 const [current,setCurrent]=useState(.1),[ambient,setAmbient]=useState(25),[horizon,setHorizon]=useState(60),[paths,setPaths]=useState(2);
 const storageKey=`naheng.forecast.${snapshot?.snapshot_id}`;
 const [jobId,setJobId]=useState(()=>{try{return localStorage.getItem(storageKey)??'';}catch{return '';}}),[job,setJob]=useState<ForecastJob>(),[prediction,setPrediction]=useState<Forecast&Dictionary>(),[error,setError]=useState(''),[creating,setCreating]=useState(false);
 const mounted=useRef(true);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 useEffect(()=>{
  if(!jobId)return;
  let alive=true;let timer:ReturnType<typeof setTimeout>;
  const poll=async()=>{try {
    const state=await request<ForecastJob>(`/api/forecast-jobs/${encodeURIComponent(jobId)}`);
    if(!alive)return;setJob(state);setError('');
    if(state.state==='succeeded'){
      const result=await request<Forecast&Dictionary>(`/api/forecast-jobs/${encodeURIComponent(jobId)}/result`);
      if(alive)setPrediction(result);
    } else if(!terminal.has(state.state)){timer=setTimeout(()=>void poll(),1000);}
   }catch(reason){if(alive){setError(String(reason));timer=setTimeout(()=>void poll(),2000);}}
  };
  void poll();return()=>{alive=false;clearTimeout(timer);};
 },[jobId]);
 if(!snapshot)return <p className="empty">完成研究运行后，可从其保存的后验创建独立条件预测。</p>;
 const busy=creating||Boolean(jobId&&(!job||!terminal.has(job.state)));
 const submit=async(event:FormEvent)=>{
  event.preventDefault();setCreating(true);setError('');setPrediction(undefined);setJob(undefined);setJobId('');
  try {const response=await request<{job_id:string;state:string}>('/api/forecasts',{
    snapshot_id:snapshot.snapshot_id,future_policy_id:'fixed-current-v1',environment_id:'constant-ambient-v1',
    horizon_s:horizon,endpoint_protocol:'synthetic_capacity_v1',sample_budget:paths,current_A:current,ambient_K:ambient+273.15,seed:20261009
   });if(mounted.current){setJobId(response.job_id);try{localStorage.setItem(storageKey,response.job_id);}catch{setError('浏览器未能保存预测作业标识；请保留页面显示的作业编号。');}}
  }catch(reason){if(mounted.current)setError(String(reason));}finally{if(mounted.current)setCreating(false);}
 };
 const cancel=async()=>{try {const value=await request<ForecastJob>(`/api/forecast-jobs/${encodeURIComponent(jobId)}/cancel`,{});if(mounted.current)setJob(value);}catch(reason){if(mounted.current)setError(String(reason));}};
 const refresh=async()=>{try{const value=await request<ForecastJob>(`/api/forecast-jobs/${encodeURIComponent(jobId)}`);if(!mounted.current)return;setJob(value);setError('');if(value.state==='succeeded'){const result=await request<Forecast&Dictionary>(`/api/forecast-jobs/${encodeURIComponent(jobId)}/result`);if(mounted.current)setPrediction(result);}}catch(reason){if(mounted.current)setError(String(reason));}};
 return <section aria-label="创建条件预测"><h2>修改未来条件并计算</h2><p>固定电流、恒定环境的未来计算使用本次保存的后验。新预测单独保存，不增加独立运营样本。</p>
  <Facts data={{来源运行:results.manifest?.run_id,来源快照:snapshot.snapshot_id}}/>
  <form onSubmit={event=>void submit(event)} className="run-form">
   <label>预测电流 (A)<input aria-label="预测电流 (A)" type="number" min={-.3} max={.3} step={.01} value={current} onChange={e=>setCurrent(Number(e.target.value))} required disabled={busy}/></label>
   <label>预测环境温度 (℃)<input aria-label="预测环境温度 (℃)" type="number" min={0} max={60} step={.1} value={ambient} onChange={e=>setAmbient(Number(e.target.value))} required disabled={busy}/></label>
   <label>预测时域 (s)<input aria-label="预测时域 (s)" type="number" min={1} max={86400} step={1} value={horizon} onChange={e=>setHorizon(Number(e.target.value))} required disabled={busy}/></label>
   <label>预测路径数<input aria-label="预测路径数" type="number" min={1} max={256} step={1} value={paths} onChange={e=>setPaths(Number(e.target.value))} required disabled={busy}/></label>
   <button type="submit" disabled={busy}>{busy?'预测计算中…':'计算新的条件预测'}</button>
  </form>{jobId&&<Facts data={{预测作业:jobId,计算状态:job?.state??'queued',进度:job?.progress,错误:job?.error}}/>}
  {busy&&jobId&&<button className="secondary" onClick={()=>void cancel()}>取消本次条件预测</button>}
  {jobId&&<button className="secondary" onClick={()=>void refresh()}>刷新本次预测状态</button>}
  {error&&<p role="alert" className="error">{error}</p>}
  {prediction&&<><h3>新条件预测的保存结果</h3><Facts data={{预测作业:prediction.job_id,来源运行:prediction.source_run_id,快照:prediction.snapshot_id,查询标识:prediction.query_hash,代码标识:prediction.code_hash,实际未来条件:prediction.query,请求轨迹数:prediction.rul.observation_requested_path_denominator,完整网格轨迹:prediction.rul.observation_complete_path_count,网格右删失:prediction.rul.grid_right_censored_count,连续首次退役未知:prediction.rul.unknown_first_passage_count,寿命状态:prediction.rul.status}}/><p>网格观察不证明点间的首次退役时刻。真实电芯寿命和独立运营风险证书仍未知。</p><a href={`/api/forecast-jobs/${encodeURIComponent(jobId)}/result`} download={`${jobId}-forecast.json`}>导出本次条件预测 JSON</a><RawData title="查看新预测每条轨迹、风险和容量观察" data={prediction}/></>}
 </section>;
}
