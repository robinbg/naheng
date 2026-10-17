import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';

const csv='timestamp_s,voltage_V,current_A,temperature_K\n0,3,2,298.15\n10,3,2,299.15\n';
async function run(page:any,mode='interactive'){
 await page.getByRole('link',{name:'总览',exact:true}).click();
 await page.getByLabel('运行时长 (s)',{exact:true}).fill('60');
 await page.getByLabel('运行模式',{exact:true}).selectOption(mode);
 const response=page.waitForResponse((r:any)=>r.url().endsWith('/api/runs')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'创建并计算',exact:true}).click();
 const job=await(await response).json();expect(job.run_id).toMatch(/^nh-[0-9a-f]{32}$/);
 await expect(page.getByTestId('run-id')).toHaveText(job.run_id);
 await expect(page.getByTestId('run-state')).toHaveText('已保存');
 return job.run_id;
}

test('full-flow: upload, accounting, persisted export, batch, seven pages, report and replay',async({page,request},info)=>{
 await page.goto('/');
 await page.getByLabel('数据来源',{exact:true}).fill('Browser acceptance synthetic sensor fixture');
 await page.getByLabel('来源类型',{exact:true}).selectOption('synthetic');
 await page.getByLabel('CSV 观测内容',{exact:true}).fill(csv.replace('10,3,2','0,3,2'));
 await page.getByRole('button',{name:'导入并核算观测',exact:true}).click();
 await expect(page.getByRole('alert').filter({hasText:'strictly increasing'})).toBeVisible();
 await page.getByLabel('CSV 观测内容',{exact:true}).fill(csv);
 const imported=page.waitForResponse(r=>r.url().endsWith('/api/datasets/import')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'导入并核算观测',exact:true}).click();
 const packet=await(await imported).json();expect(packet.provenance_type).toBe('synthetic');
 await expect(page.getByTestId('dataset-id')).toHaveText(packet.dataset_id);
 expect(packet.row_count).toBe(2);expect(packet.analysis.discharge_port_energy_J).toBe(60);
 expect(packet.analysis.capacity_Ah).toBeNull();expect(packet.analysis.RUL_s).toBeNull();
 expect(packet.model_assimilation.status).toBe('unknown');
 const sourceDownload=page.waitForEvent('download');
 await page.getByRole('link',{name:'导出原始 CSV',exact:true}).click();
 const savedSource=info.outputPath('downloaded-source.csv');await(await sourceDownload).saveAs(savedSource);
 expect(await fs.readFile(savedSource,'utf8')).toBe(csv);
 const jsonDownload=page.waitForEvent('download');await page.getByRole('link',{name:'导出核算 JSON',exact:true}).click();
 const savedJson=info.outputPath('downloaded-analysis.json');await(await jsonDownload).saveAs(savedJson);
 expect(JSON.parse(await fs.readFile(savedJson,'utf8'))).toEqual(packet);
 await page.reload();await expect(page.getByTestId('dataset-id')).toHaveText(packet.dataset_id);
 expect(await(await request.get(`/api/datasets/${packet.dataset_id}`)).json()).toEqual(packet);

 const identifier=await run(page,'batch');
 const job=await(await request.get(`/api/runs/${identifier}`)).json();expect(job.config.mode).toBe('batch');
 const manifest=await(await request.get(`/api/runs/${identifier}/manifest`)).json();expect(manifest.complete).toBe(true);
 for(const name of ['状态估计','寿命预测','风险预警','策略收益','仿真对照','理论证据']){
  await page.getByRole('link',{name,exact:true}).click();await expect(page.getByRole('heading',{name,exact:true})).toBeVisible();
 }
 const reportPost=page.waitForResponse(r=>r.url().endsWith('/api/reports')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'生成运行报告',exact:true}).click();expect((await reportPost).status()).toBe(201);
 const reportDownload=page.waitForEvent('download');await page.getByRole('link',{name:'下载 HTML 报告',exact:true}).click();
 const htmlPath=info.outputPath('run-report.html');await(await reportDownload).saveAs(htmlPath);
 expect(await fs.readFile(htmlPath,'utf8')).toContain(identifier);
 await page.getByRole('link',{name:'仿真对照',exact:true}).click();
 await page.getByRole('button',{name:'登记当前运行回放',exact:true}).click();
 await expect(page.getByTestId('run-id')).not.toHaveText(identifier);
 await expect(page.getByTestId('run-state')).toHaveText('已保存');
 const replayId=await page.getByTestId('run-id').innerText();
 const replay=await(await request.get(`/api/runs/${replayId}/manifest`)).json();
 expect(replay.mode).toBe('replay');expect(replay.reused_from).toBe(identifier);expect(replay.independent_sample).toBe(false);
 await page.reload();await expect(page.getByTestId('run-id')).toHaveText(replayId);
});

test('full-flow: changed conditional prediction, refresh/reopen and cancellation preserve lineage',async({page,request},info)=>{
 await page.goto('/');const identifier=await run(page);
 await page.getByRole('link',{name:'寿命预测',exact:true}).click();
 await page.getByLabel('预测电流 (A)',{exact:true}).fill('0.12');
 await page.getByLabel('预测环境温度 (℃)',{exact:true}).fill('30');
 await page.getByLabel('预测时域 (s)',{exact:true}).fill('60');
 await page.getByLabel('预测路径数',{exact:true}).fill('2');
 const submitted=page.waitForResponse(r=>r.url().endsWith('/api/forecasts')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'计算新的条件预测',exact:true}).click();
 const first=await(await submitted).json();expect(first.job_id).toMatch(/^nh-[0-9a-f]{32}$/);
 await expect(page.getByRole('heading',{name:'新条件预测的保存结果',exact:true})).toBeVisible();
 const prediction=await(await request.get(`/api/forecast-jobs/${first.job_id}/result`)).json();
 expect(prediction.source_run_id).toBe(identifier);expect(prediction.query.current_A).toBe(.12);
 expect(prediction.query.ambient_K).toBeCloseTo(303.15);expect(prediction.rul.observation_requested_path_denominator).toBe(2);
 const download=page.waitForEvent('download');await page.getByRole('link',{name:'导出本次条件预测 JSON',exact:true}).click();
 const saved=info.outputPath('forecast.json');await(await download).saveAs(saved);
 expect(JSON.parse(await fs.readFile(saved,'utf8'))).toEqual(prediction);
 await page.reload();await expect(page.getByRole('heading',{name:'新条件预测的保存结果',exact:true})).toBeVisible();
 await expect(page.getByRole('link',{name:'导出本次条件预测 JSON',exact:true})).toHaveAttribute('href',`/api/forecast-jobs/${first.job_id}/result`);
 await page.getByRole('button',{name:'刷新本次预测状态',exact:true}).click();
 expect(await(await request.get(`/api/forecast-jobs/${first.job_id}/result`)).json()).toEqual(prediction);
 await page.getByLabel('预测时域 (s)',{exact:true}).fill('86400');await page.getByLabel('预测路径数',{exact:true}).fill('256');
 const nextResponse=page.waitForResponse(r=>r.url().endsWith('/api/forecasts')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'计算新的条件预测',exact:true}).click();const next=await(await nextResponse).json();
 await page.getByRole('button',{name:'取消本次条件预测',exact:true}).click();
 await expect(page.getByText('cancelled',{exact:true})).toBeVisible();
 expect((await request.get(`/api/forecast-jobs/${next.job_id}/result`)).status()).toBe(409);
 await expect(page.getByRole('link',{name:'导出本次条件预测 JSON',exact:true})).toHaveCount(0);
 await page.reload();await expect(page.getByText('cancelled',{exact:true})).toBeVisible();
});

test('full-flow: lifecycle thermal and four-series assets, seven pages and saved report',async({page,request},info)=>{
 await page.goto('/');await page.getByRole('link',{name:'总览',exact:true}).click();
 await page.getByLabel('生命周期售电单价 (CNY/kWh)',{exact:true}).fill('0.44');
 await page.getByLabel('生命周期运行模式',{exact:true}).selectOption('batch');
 const created=page.waitForResponse(r=>r.url().endsWith('/api/lifecycle-jobs')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'创建生命周期并计算',exact:true}).click();const job=await(await created).json();
 await expect(page.getByTestId('run-id')).toHaveText(job.run_id);await expect(page.getByTestId('run-state')).toHaveText('已保存');
 const response=await request.get(`/api/runs/${job.run_id}/lifecycle`);expect(response.ok()).toBe(true);const packet=await response.json();
 expect(packet.parameters.sell_price_per_kWh).toBe(.44);expect(packet.independent_operating_n).toBe(0);
 expect(packet.cases.length).toBe(8);expect(packet.cases.every((c:any)=>c.valid_execution)).toBe(true);
 const moduleIndex=packet.cases.findIndex((c:any)=>c.mode==='module');expect(moduleIndex).toBeGreaterThanOrEqual(0);
 await page.getByLabel('查看生命周期案例',{exact:true}).selectOption(String(moduleIndex));
 for(const name of ['状态估计','寿命预测','风险预警','策略收益','仿真对照','理论证据']){
  await page.getByRole('link',{name,exact:true}).click();await expect(page.getByRole('heading',{name,exact:true})).toBeVisible();
 }
 await page.getByRole('button',{name:'生成运行报告',exact:true}).click();
 const downloaded=page.waitForEvent('download');await page.getByRole('link',{name:'下载 HTML 报告',exact:true}).click();
 const saved=info.outputPath('lifecycle-report.html');await(await downloaded).saveAs(saved);
 expect(await fs.readFile(saved,'utf8')).toContain(job.run_id);
 await page.getByRole('link',{name:'仿真对照',exact:true}).click();await page.getByRole('button',{name:'登记当前运行回放',exact:true}).click();
 await expect(page.getByTestId('run-id')).not.toHaveText(job.run_id);await expect(page.getByTestId('run-state')).toHaveText('已保存');
 const replayId=await page.getByTestId('run-id').innerText();const replay=await(await request.get(`/api/runs/${replayId}/lifecycle`)).json();
 expect(replay.mode).toBe('replay');expect(replay.source_run_id).toBe(job.run_id);expect(replay.independent_sample).toBe(false);
});
