import { useEffect, useState } from 'react';
import { request } from '../api';
import type { Dictionary, Job } from '../api';
import { Facts, Metric, RawData } from './DataViews';

const object = (value: unknown): Dictionary | undefined => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Dictionary : undefined;
const rows = (value: unknown): Dictionary[] => Array.isArray(value) ? value.map(object).filter((item): item is Dictionary => item !== undefined) : [];
const finite = (value: unknown): number | undefined => typeof value === 'number' && Number.isFinite(value) ? value : undefined;
function total(records: Dictionary[], key: string): number | undefined {
 const values = records.map(row => finite(row[key]));
 return values.some(value => value === undefined) ? undefined : (values as number[]).reduce((a, b) => a + b, 0);
}

export default function ValidityPanel({job}: {job: Job}) {
 const [value, setValue] = useState<Dictionary>();
 const [error, setError] = useState('');
 const [loading, setLoading] = useState(false);
 const [refresh, setRefresh] = useState(0);
 const enabled = job.config.validity_profile === 'engineering-residual-v1';
 useEffect(() => {
  let alive = true; let pending = false;
  setValue(undefined); setError(''); setLoading(false);
  if (!enabled) return () => { alive = false; };
  const load = async () => {
   if (pending) return;
   pending = true; if (alive) setLoading(true);
   try {
    const record = await request<Dictionary>(`/api/runs/${encodeURIComponent(job.run_id)}/validity`);
    if (record.run_id !== job.run_id) throw new Error('监测记录与当前 RunID 不一致');
    if (typeof record.stopped !== 'boolean' || !Array.isArray(record.checks) || !Array.isArray(record.actual_service) || !Array.isArray(record.failures)) throw new Error('监测记录缺少完整状态，暂不能判定');
    if (alive) {setValue(record); setError('');}
   } catch (reason) {if (alive) {setValue(undefined); setError(String(reason));}}
   finally {pending = false; if (alive) setLoading(false);}
  };
  void load();
  const timer = ['queued','running'].includes(job.state) ? window.setInterval(() => void load(), 2000) : undefined;
  return () => {alive = false; if (timer !== undefined) window.clearInterval(timer);};
 }, [job.run_id, job.state, enabled, refresh]);
 const checks = rows(value?.checks);
 const last = object(checks.at(-1)?.decision);
 const stop = object(value?.stop);
 const response = object(stop?.response);
 const failures = rows(value?.failures);
 const reasons = Array.isArray(stop?.reason) ? stop.reason : Array.isArray(last?.reasons) ? last.reasons : failures.map(item => item.reason);
 const service = rows(value?.actual_service);
 const stopped = value?.stopped === true;
 const state = !enabled ? '未启用' : !value ? '未知：尚无可读取的监测记录' : stopped ? last?.status === 'WITHDRAWN' ? '已撤回，自动动作已停止' : '已停止，需重新核验' : '监测中（工程阈值）';
 return <section aria-label="运行有效性监测">
  <h2>运行有效性监测</h2>
  <p>工程残差阈值用于当前合成研究运行，不是标定后的误报概率或安全证书。证据撤回后停止自动动作；没有已核验的备用方案时，不假定零电流动作安全。</p>
  <Facts data={{运行:job.run_id,监测状态:state,监测配置:job.config.validity_profile ?? 'off',合成传感器配置:job.config.synthetic_sensor_profile ?? 'baseline',撤回或停止原因:reasons.length ? reasons : undefined,异常次数:value ? failures.length : undefined}}/>
  {enabled && <button className="secondary" onClick={() => setRefresh(n => n + 1)} disabled={loading}>{loading ? '读取监测记录…' : '刷新监测记录'}</button>}
  {error && <p role="status">监测结果暂不可用：{error}。这不表示运行安全，也不表示没有发生撤回。</p>}
  {value && <><div className="metrics">
   <Metric label="已记录执行电能" value={total(service,'actual_electrical_energy_J')} unit="J"/>
   <Metric label="已执行段未服务量" value={total(service,'unserved_energy_J')} unit="J"/>
   <Metric label="停止后请求未服务量" value={finite(response?.unserved_energy_J)} unit="J"/>
  </div><p>上述执行量仅统计已保存的回执。缺失回执和未提供的未服务量保持未知；停止后请求量与已执行段分开记录。</p>
  <Facts data={{最后有效性状态:last?.status,自动动作许可:response?.action_permitted,备用方案:response?.selected_candidate,自动采用新理论:value.new_theory_auto_adopted,新增独立科学样本:value.new_independent_scientific_N}}/>
  <RawData title="查看当前运行监测、撤回与实际服务记录" data={value}/></>}
 </section>;
}
