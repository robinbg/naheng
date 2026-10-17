# 检查点续算契约与证据

续算从最后一个已完成传感器同化的边界继续实际计算，创建新的 RunID，保留父运行及其冻结源码。`cancelled`、`failed`、`interrupted` 可作为来源；`queued`、`running`、`succeeded` 不可被并发续算。旧运行中断前的部分记录不能变成完整轨迹，恢复也不增加独立实验样本。

`runtime/recovery.py` 将完整 bundle 写入 `artifacts/runs/evaluator/{RunID}/recovery-{step}-{sha256}.json`。文件内容完成并同步后以独占硬链接提交，禁止覆盖同名不同内容。公开 `checkpoint.json` 原子提交哈希、相对指针、源码/锁/科学输入哈希、步数、逻辑时间和快照身份，不含仿真状态、参考轨迹、粒子或随机状态。Windows 读写使用局部长路径前缀，避免更改全局系统设置。bundle 上限为 100 MiB；读取、校验和解析使用同一有界字节缓冲。

bundle 保存仿真运行时状态与传感器 PCG64 状态，以及 PF 自身的重采样后粒子、权重、PCG64 状态、最后同化时间、重采样前公开后验、噪声、模型参数哈希、先验版本及诊断。PF 的恢复函数只接收 PF checkpoint；不能传入模拟器状态或参考轨迹。恢复以 `__new__` 建立实例，不重抽先验、不重复同化边界观测，并按粒子末两列恢复各粒子的实际动力学参数。

核心接口为：

```python
config_digest(config) -> str
save_recovery_checkpoint(store, run_id, *, code_hash, lock_hash, input_hash,
    step, logical_time_s, simulator_state, sensor_rng, pf, sensor, posterior,
    actions, cashflows, decisions, truth, execution_config_hash=None, lineage=None) -> dict
load_recovery_checkpoint(store, parent_run_id, *, expected_code_hash,
    expected_lock_hash, expected_input_hash, new_run_id, checkpoint=None) -> dict
ParticleFilter.export_checkpoint() -> dict
ParticleFilter.from_checkpoint(new_run_id, model, pf_checkpoint) -> ParticleFilter
restore_sensor_rng(sensor_rng_state) -> numpy.random.Generator
restore_ledger(empty_new_run_ledger, rekeyed_actions, rekeyed_cashflows) -> EnergyLedger
prepare_recovery(project, store, parent_run_id, *, max_nonterminal=4) -> queued_job
```

科学输入哈希只排除 `source_dir`、`code_hash`、`recovery_source`、`recovery_lineage` 执行元数据。seed、物理环境、策略价格、粒子数、预测路径和时间参数仍参与比较。恢复核验父源码索引的每个文件、复制后的源码哈希、依赖锁、输入哈希、完整 bundle 哈希和边界身份。恢复模型参数、PF prior revision、状态单位或 RNG 类型改变时拒绝执行；不静默切换模型。逻辑时间必须等于 `min(next_step * step_s, duration_s)`，提前发生模型域事件的半步不允许假跳过剩余时间。

历史后验、动作与执行 ID 按新 RunID 确定性映射，数值保持不变；lineage 保存直接父运行、最初来源及完整映射。账本通过原有 `append` 重放真实历史能量，严格比较原账目、价格和现金流，并重建执行 ID 去重。余下实际积分生成新执行记录。`independent_sample=false`，`independent_operational_trajectories=0`；继承区间只记一次收益。公开 lineage 和 API config 递归去除 `source_checkpoint` 与 `private_recovery`，私有 evaluator 文件不进入报告下载索引。

异常、取消和硬预算终止保留最后成功边界的指针；失败阶段和原因另记。报告、完整产物、哈希和完成检查点均写好后，SQLite 才原子提交成功，且事务内拒绝已有取消请求。公开事件文件是提交前快照，最终事件以 SQLite/API 为准。每个恢复 worker 重新遵守 120 秒预算。服务器启动将遗留队列标为 interrupted，用户可通过 `/api/runs/{RunID}/recover` 或 `naheng recover --run-id {RunID}` 请求续算。

首次组件验收 `G04-checkpoint-component-initial-0b156503` 退出 1：Windows 长路径导致 7 项失败，8 项通过；原日志保留。修复后 `G04-checkpoint-component-bounded-27766e15` 退出 0，16 项通过，覆盖后重采样与非重采样恢复、双 RNG、私有字节/指针篡改、源码/锁/输入/模型不符及 PF 拒收参考状态。

首轮真实 runner 验收 `G04-checkpoint-runner-initial-e9de274d` 退出 0，10 项通过。它执行冻结源码子进程中的真实 SiteModel、PF、动作准入、积分、账本和条件预测：同 seed、150 秒总时长、60 秒步长（尾步 30 秒）、8 粒子、2 条预测路径；一次在步 1 的已保存边界提交取消，再以新冻结 RunID 续算。逐点传感器记录、私有积分状态、全后验分布、实际能量现金流及预测路径与不中断运行精确相等，父文件和父 cancelled 状态保留。该缩小场景用于恢复机制验收，不替代 M1 的 64 粒子/16 路径/30 分钟门槛。

最终切片 `G04-checkpoint-runner-boundaries-b3743afd` 退出 0，32 项通过（82.97 秒），包含 PF/无 oracle、CAS/发布回归以及取消边界 0、1、3 的真实冻结 worker 数值对照。起点取消、执行中取消和末步已完成后 forecast 前取消均保存可恢复边界，恢复结果精确一致。实际 API 读取 job/list/manifest/lineage 下载不含私有指针，lineage 与历史 ID 映射一致，恢复运行不标为独立样本。各轮真实运行记录位于 `artifacts/recovery-tests/{id}/result.json`；首次失败、初次通过及最终日志均保留。

这些证据属于合成模型下的真实数值与 API 集成验收；不代表真实钠电数据外测、事故概率认证、Linux 进程树验证或完整交付版本的浏览器用户任务验收。稳定候选仍需整体 smoke 和真实界面验收。
