import {useState} from 'react';
import type {FormEvent} from 'react';
import type {Dictionary, Job, LifecyclePacket} from '../api';
import {valueText} from '../api';
import {Facts,Metric,RawData} from '../components/DataViews';
import type {Page} from './WorkbenchPages';

const labels:Record<string,string>={exact:'完整周期执行',macro:'宏步预测审计','early-exit':'提前退役审计',thermal:'热管理执行审计',module:'四串联模组执行审计'};
function object(value:unknown):Dictionary{return value&&typeof value==='object'&&!Array.isArray(value)?value as Dictionary:{};}
function rows(value:unknown):Dictionary[]{return Array.isArray(value)?value.map(object):[];}

export function LifecycleLauncher({busy,onStart}:{busy:boolean;onStart:(input:Dictionary)=>void}){
 const [sell,setSell]=useState(.3),[buy,setBuy]=useState(.15),[replacement,setReplacement]=useState(100),[mode,setMode]=useState('interactive');
 function submit(event:FormEvent){event.preventDefault();onStart({profile:'pilot',mode,sell_price_per_kWh:sell,buy_price_per_kWh:buy,replacement_cost_CNY:replacement});}
 return <section><h2>创建生命周期实验</h2><p>比较两种固定充放电策略，执行十二个充放电周期，并单列宏步、提前退役、热管理和四串联模组更换。48 秒合成研究窗口用于核算和功能验证，不能外推真实电芯寿命。</p>
 <form className="run-form" onSubmit={submit}><label>生命周期售电单价 (CNY/kWh)<input aria-label="生命周期售电单价 (CNY/kWh)" type="number" min={0} max={10} step={.01} value={sell} onChange={e=>setSell(Number(e.target.value))} required/></label>
 <label>生命周期购电单价 (CNY/kWh)<input aria-label="生命周期购电单价 (CNY/kWh)" type="number" min={0} max={10} step={.01} value={buy} onChange={e=>setBuy(Number(e.target.value))} required/></label>
 <label>每电芯更换费用 (CNY)<input aria-label="每电芯更换费用 (CNY)" type="number" min={0} max={100000} step={1} value={replacement} onChange={e=>setReplacement(Number(e.target.value))} required/></label>
 <label>生命周期运行模式<select aria-label="生命周期运行模式" value={mode} onChange={e=>setMode(e.target.value)}><option value="interactive">交互计算</option><option value="batch">批量作业</option></select></label>
 <button type="submit" disabled={busy}>{busy?'正在创建…':'创建生命周期并计算'}</button></form><p>电价与费用为本次合成假设。输入变更会创建新 RunID，并在执行前冻结。</p></section>;
}

export function LifecyclePages({page,packet,job,onReplay}:{page:Page;packet:LifecyclePacket|undefined;job:Job;onReplay:()=>void}){
 const [index,setIndex]=useState(0);
 if(!packet)return <p className="empty">生命周期作业{job.state==='queued'||job.state==='running'?'正在计算，完成后显示已保存结果。':'尚未提供可核验结果；请查看作业错误。'}</p>;
 const selected=packet.cases[index]??packet.cases[0], f=selected?.finance??{}, endpoints=selected?.endpoints??{}, final=object(endpoints.final), initial=object(endpoints.initial), execution=selected?.execution??{};
 const assets=rows(final.assets), cash=rows(f.cash_events), points=rows(packet.frontier.points);
 const complete=job.state==='succeeded'&&packet.experiment_manifest.exit_code===0;
 return <><p className="notice">合成输入 · 真实数值执行。实际现金、条件终值和宏步投影分别记录；当前没有真实市场收入、真实电芯寿命或运营事故率证书。</p>
 <Facts data={{显示运行:packet.display_run_id,原始结果来源:packet.source_run_id,模式:packet.mode,回放来源:packet.reused_from,完整执行:complete,运营独立样本:packet.independent_operating_n}}/>
 {!complete&&<p role="alert" className="error">作业未完成全部要求；部分结果保留，不计入完整执行验收。</p>}
 <label htmlFor="lifecycle-case">查看生命周期案例</label><select id="lifecycle-case" value={index} onChange={e=>setIndex(Number(e.target.value))}>{packet.cases.map((item,i)=><option key={`${item.mode}:${item.policy_id}:${item.case_id}`} value={i}>{labels[item.mode]??item.mode} · {item.policy_id} · {item.case_id}</option>)}</select>
 {!selected?.valid_execution&&<p role="alert">案例未完成：{selected?.adoption_error??'尚无经过核验的执行产物'}</p>}
 {page==='overview'&&<><h2>生命周期执行概览</h2><div className="metrics"><Metric label="记录的案例" value={packet.cases.length}/><Metric label="已核验的案例" value={packet.cases.filter(item=>item.valid_execution).length}/><Metric label="所选案例周期" value={execution.completed_cycles}/><Metric label="所选案例已执行时间" value={execution.elapsed_s} unit="s"/></div><Facts data={packet.parameters}/></>}
 {page==='state'&&<><h2>协议容量与终端状态</h2><p>这些是指定合成模型的协议诊断与占位 SOC 代理，属于模型读数；本实验没有传感器后验分布，不能将诊断值冒充测量真值或可信区间。</p><div className="metrics"><Metric label="初始占位 SOC 代理" value={initial.soc}/><Metric label="最终占位 SOC 代理" value={final.soc}/><Metric label="最终可用储能" value={final.stored_energy_J} unit="J"/></div><table><thead><tr><th>资产 / 更换代次</th><th>协议容量 C</th><th>同协议初始容量 C</th><th>条件 RUL s</th><th>删失状态</th></tr></thead><tbody>{assets.map(asset=><tr key={String(asset.asset_id)}><td>{valueText(asset.asset_id)}</td><td>{valueText(asset.capacity_C)}</td><td>{valueText(asset.pristine_capacity_C)}</td><td>{valueText(asset.rul_s)}</td><td>{valueText(asset.rul_status)}</td></tr>)}</tbody></table></>}
 {page==='life'&&<><h2>条件寿命与退役</h2><p>容量协议、未来固定策略和环境以本次冻结条件为准。运行窗口没有观测到完整退役时刻时，RUL 保持未知；窗口长度不能代替剩余寿命。</p><Facts data={{终端状态:final.status,已执行时间_s:execution.elapsed_s,更换次数:execution.replacement_count,拓扑:execution.topology,未服务时间_s:f.unserved_time_s,终端证据类型:final.evidence_kind}}/><RawData title="每电芯条件寿命与容量协议来源" data={{assets,protocol:packet.registration.protocol,audit:endpoints.audit}}/></>}
 {page==='risk'&&<><h2>注册案例事件与风险范围</h2><p>案例比例只描述本次有限合成案例，不能作为运营事件概率或安全保证。宏步、提前退役、热管理和模组审计不加入主比较分母。</p><Facts data={{事件定义:packet.registration.event_definition,alpha:packet.registration.alpha,风险范围:packet.registration.risk_scope,所选案例事件:execution.event_occurred,运营独立N:packet.independent_operating_n,运营概率上界:null,析钠:null,火灾:null}}/><RawData title="完整风险比较前沿" data={packet.frontier}/></>}
 {page==='strategy'&&<><h2>生命周期现金流与共同终端核算</h2><div className="metrics"><Metric label="实际执行现金流" value={f.realized_cash_CNY} unit="CNY"/><Metric label="条件终端价值调整" value={f.terminal_value_adjustment_CNY} unit="CNY"/><Metric label="条件比较值" value={f.conditional_comparison_value_CNY} unit="CNY"/><Metric label="宏步投影现金流" value={f.projected_cash_CNY} unit="CNY"/></div><Facts data={{未服务时间_s:f.unserved_time_s,条件未服务费用_CNY:f.conditional_unserved_value_CNY,退化影子重复扣减_CNY:f.planning_shadow_deducted_CNY,终端探测计入售电:f.terminal_probe_energy_is_operating_sales,终端价值属于实际收入:f.terminal_value_is_realized_income,未知原因:f.unknown_reasons}}/><h3>维护与更换现金事件</h3>{cash.length?<table><thead><tr><th>事件</th><th>已保存的核算与资产代次</th></tr></thead><tbody>{cash.map((event,i)=><tr key={i}><td>{valueText(event.kind??event.event_id)}</td><td>{valueText(event)}</td></tr>)}</tbody></table>:<p>本案例没有维护或更换现金事件。</p>}<h3>实际评价前沿</h3><RawData title="所有候选、失败和未知前沿点" data={points.length?points:packet.frontier}/><RawData title="实际电能和热管理核算明细" data={f.actual_energy_entries}/><RawData title="宏步投影与完整金融核算" data={f}/></>}
 {page==='simulation'&&<><h2>生命周期执行与回放</h2><p>回放使用同一已保存结果，不重新积分或增加独立样本。</p>{job.state==='succeeded'&&<button onClick={onReplay}>登记当前运行回放</button>}<Facts data={{案例模式:labels[selected.mode],拓扑:execution.topology,电芯数:execution.cell_count,更换次数:execution.replacement_count,宏步次数:execution.accepted_jumps,实际热管理耗电_J:execution.thermal_management_energy_J}}/><RawData title="执行收据、失败原因与原始结果来源" data={packet.experiment_manifest}/></>}
 {page==='theory'&&<><h2>本次生命周期计算的适用范围</h2><p>冻结模型、容量协议和金融端点规则实际用于本次计算。宏步仅有局部数值误差估计，完整输出误差与寿命合同保持未知；本运行没有授予新的形式证明。</p><Facts data={{代码标识:packet.code_hash,注册条件标识:packet.registration_sha256,终端规则:object(packet.registration.financial_assumptions).terminal_rule_id,宏步严格全时域合同:null,真实电芯模型误差:null}}/><RawData title="冻结的模型、策略、来源与全部运行条件" data={packet.registration}/><RawData title="终端存储与协议诊断证据" data={endpoints.audit}/></>}
 <RawData title="生命周期结果完整来源" data={{source_run_id:packet.source_run_id,code_hash:packet.code_hash,registration_sha256:packet.registration_sha256,scope:packet.scope}}/></>;
}
