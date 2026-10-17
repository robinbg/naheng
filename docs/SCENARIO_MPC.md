# 联合后验场景规划切片

`src/naheng/control/scenario_mpc.py` 保持原 `MPCStage`、`MPCParameters`、`MPCPlan` 接口。所有表示出的联合状态/参数行与原权重进入真实多阶段积分目标，各行分别建立物理模型、阶段约束和末端 SOC 条件。均值仅用于初值，不用均值掩盖坏行；零权重行也先校验并保留约束。

目标是原权重加权的预测电能现金流，扣除热管理 COP 电耗及显式独立的退化规划影子价。预测不是账本收入。优化采用有候选数、迭代数和墙钟预算的 SLSQP 自有进程；所有返回值保存实际求解次数、源哈希、不可行与超时。只允许返回方案的首动作执行，其他阶段必须在新观测后重规划。备用规则只提供同快照提案，不自动执行。

公共入口 `naheng scenario-calibration --calibration-dir 成功当前校准目录 --out artifacts/新目录` 实际完成 40→45→50 秒的两次首动作、传感器更新与重规划。参考内部状态和抽样只在 evaluator 目录；控制器接收当前后验和声明的未来价序列，观察器只接收 V/I/T/time。40 秒批量校准的采用、45/50 秒真正的新传感器更新分别登记。

正式运行保存于 `artifacts/scenario_calibration/public-20261014-b`；原首版 A 保持其历史代码标识。实际电能分别为 -0.3199324290314948 J 与 0.29934052614548484 J；这是合成工况的充电及放电，不是独立真实电芯或收益优势实验。完整 C01 的固定强基线搜索、前沿、长期终端、完整动作/协议及科学验收仍未完成。有限样本、SLSQP 数值容差和这些仿真不授予严格 T3 权限。

复验：`.venv/Scripts/python.exe -m pytest tests/integration/test_scenario_mpc.py tests/integration/test_mpc_feasibility.py tests/integration/test_scenario_calibration.py -q --basetemp <HOST_HOME>/Documents/Codex/.nh-scenario-新标识`。
