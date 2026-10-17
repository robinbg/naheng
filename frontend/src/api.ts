export type Dictionary = Record<string, unknown>;
export interface Job {run_id: string; state: string; progress: number; error: string | null; updated: string; config: Dictionary; reused_from: string | null;}
export interface Snapshot {snapshot_id: string; parameter_revision: string; obs_until_s: number; mean: Record<string, number>; quantiles: Record<string, number[]>; ess: number; samples: number[][]; state_names: string[]; state_units: string[]; identifiability: string[];}
export interface Sensor {timestamp_s: number; voltage_V: number; temperature_K: number; current_A: number;}
export interface RiskEvent {status: string; probability?: number | null; reason?: string | null; event_count?: number; posterior_predictive_samples?: number; definition?: Dictionary;}
export interface Forecast {run_id: string; snapshot_id: string; query: Dictionary; query_hash: string; rul: Dictionary; risk: {events: Record<string, RiskEvent>; completed_paths: number; failed_paths: number; risk_certificate: boolean;}; budget: Dictionary; coverage: string; paths: Dictionary[];}
export interface Decision {action_id: string; snapshot_id: string; decision: string; reason: string; mode: string; model_selected: string; evidence_refs: string[]; checks: Dictionary[]; uncovered?: string[]; rate_diagnostics?: Dictionary; reduction_evidence_refs?: string[];}
export interface LifecycleCase {case_id:string;policy_id:string;mode:string;valid_execution:boolean;adoption_error:string|null;finance:Dictionary|null;endpoints:Dictionary|null;execution:Dictionary|null;}
export interface LifecyclePacket {display_run_id:string;source_run_id:string;mode:string;code_hash:string;registration_sha256:string;provenance_type:string;parameters:Dictionary;registration:Dictionary;experiment_manifest:Dictionary;frontier:Dictionary;cases:LifecycleCase[];independent_sample:boolean;independent_operating_n:number;reused_from:string|null;scope:string;}
export interface Results {lifecycle?:LifecyclePacket;snapshots?: Snapshot[]; forecast?: Forecast; economics?: Dictionary; decisions?: Decision[]; manifest?: Dictionary; trace?: Sensor[]; modelPackage?: Dictionary; chemicalBinding?: Dictionary; reductionBinding?: Dictionary; errors: string[];}
export async function request<T>(url: string, body?: unknown): Promise<T> {
 const response = await fetch(url, body === undefined ? undefined : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if (!response.ok) {const content=await response.text(); let reason=content; try {reason=JSON.stringify(JSON.parse(content).detail ?? JSON.parse(content));} catch {} throw new Error(`${response.status}: ${reason}`);}
 return response.json() as Promise<T>;
}
export async function readResults(id: string,lifecycle=false): Promise<Results> {
 if(lifecycle){const entries=await Promise.allSettled(['lifecycle','manifest'].map(name=>request(`/api/runs/${encodeURIComponent(id)}/${name}`)));const result:Results={errors:[]};entries.forEach((entry,index)=>{if(entry.status==='fulfilled')Object.assign(result,{[index===0?'lifecycle':'manifest']:entry.value});else result.errors.push(`${index===0?'lifecycle':'manifest'}: ${entry.reason}`);});return result;}
 const names=['snapshots','forecast','economics','decisions','manifest','trace','model-package','chemical-binding','reduction-binding'] as const;
 const values=await Promise.allSettled(names.map(name=>request(`/api/runs/${encodeURIComponent(id)}/${name}`)));
 const result: Results={errors:[]};
 values.forEach((value,index)=>{if(value.status==='fulfilled') Object.assign(result,{[names[index]==='model-package'?'modelPackage':names[index]==='chemical-binding'?'chemicalBinding':names[index]==='reduction-binding'?'reductionBinding':names[index]]:value.value}); else result.errors.push(`${names[index]}: ${value.reason}`);});
 return result;
}
export function valueText(value: unknown, digits=4): string {if(value===null || value===undefined) return '未知'; if(typeof value==='number') {if(!Number.isFinite(value))return '未知';if(value!==0&&Math.abs(value)<0.001)return value.toExponential(3);return value.toLocaleString('zh-CN',{maximumFractionDigits:digits});} if(typeof value==='object') return JSON.stringify(value); return String(value);}
