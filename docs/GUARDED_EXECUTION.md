# 合成执行截止与恢复边界

`src/naheng/control/execution.py` 调用原 SiteModel 原生事件积分器。仅把四个 V/T 停止字段收紧为原模型、已登记模型包、显式共同控制界及包适用域的交集；其他物理参数和原动作不变，固定策略与共同预测裕度不作为操作截止。私有抽样模型与登记基础参数的身份分别记录。传感器和控制器不读取私有 guard/state/parameter 产物。

固定前沿、对角观察器场景、联合观察器场景和实际 MPC Run 已接入。预启动拒绝记录零 solver 调用及未执行，不替换成零电流动作；实际返回后先保存真实 elapsed、能量和热管理电耗账本及私有轨迹，再做库存、约束和观察器检查。原 native physical event、operational stop、trace violation 与 unknown early stop 分开记录。预测中未来动作不记现金，停止区间不喂成完整正常传感器更新。

SOC/倍率段、温度、电压、热命令、区间 DoD 与累计 case DoD 接受实际 trace 检查；这不提供连续 SOC/DoD、全域浮点误差、T3 或现实安全证书。

失败后，未并入观察器边界的实际执行在 SQLite 留失效事件，即使文件 checkpoint 写失败也拒绝旧指针。执行前另持久化启动意图；硬退出和服务启动恢复后，所选认证 bundle 必须真实包含对应 step/action。保存的实际账目必须精确等于该边界账目。预启动确定未执行可撤销意图；正常 checkpoint 后取消，以及已全部执行但仅待发布的恢复保持原行为。缺少完成依据不会默认为完成。

原模型 SHA256 保持 `a3ba2d3c061fee7f77acc15eae69cc638edff2cf9f68ccdd500803186ca728e4`。冻结 guard 的 20 项真实测试、独立 145 项检查及 13 次原生对照积分通过；完整失败记录保留。5837 版本完整 735/23 测试通过，08705 最新硬退出修复的 16 项定向检查通过，完整新版本回归另行保存。两加热动作真正执行；冷却第二轮预算 UNKNOWN 未改变预算求通过。

复验：`.venv/Scripts/python.exe -m pytest -q tests/integration/test_guarded_execution.py tests/integration/test_execution_reserve_scope.py tests/integration/test_hard_exit_execution_recovery.py tests/integration/test_executed_failure_accounting.py tests/integration/test_checkpoint_recovery.py`。原 C01 验收命令及完整项目门保持。

08705aadc91c 的完整新版本回归已实际完成：736 项、23 子测试，退出 0，源码和测试字节前后相同。原 C01 工程验收已按原任务范围完成，收据为 `artifacts/progress/C01-engineering-accepted-bd951a89/manifest.json`；生命周期收益、完整理论、真实数据科学比较及 UI 仍按各自任务验收，未授完整项目完成。
