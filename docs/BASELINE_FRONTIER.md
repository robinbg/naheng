# 固定基线调参、冻结与配对执行

公共入口 `naheng baseline-frontier --input 协议 --calibration-dir 当前校准目录 --out 新工件目录` 已接入。先登记代码、参数、来源、候选、训练/评价种子、时域、终端和失败处理；实际训练运行结束后，在每个规则/名义 MPC 方法族内分别求前沿并冻结。评价阶段只执行冻结策略及预登记的场景 MPC 对照，不利用评价结果再次选参数。

固定规则分别使用购价决定充电、售价决定放电，并逐个实际传播所有表示出的联合样本，包含零权重行。名义基线复用原 MPC；固定电流、电压/SOC/温度裕度及名义终端缓冲只能收紧共同条件，不能放松。规则不支持的非零名义终端缓冲明确拒绝。第一动作执行后，用真实计算产生的噪声 V/I/T/time 更新新 PF，再重规划。预测阶段没有记入执行或现金历史。

每个 case 的 RunID 由预登记 SHA、阶段、策略和种子确定，传感器、后验和账本一致。身份 fork 保留原联合样本、权重、时间和 RNG，并保留校准/父观察器来源。内部状态只在 evaluator 目录；控制器只接收当前后验、声明的价序列及模型包。配对传感器噪声按时间索引，拒绝动作不会改变其他策略的噪声序列。

实际积分后立即保存电能和热管理电耗账本，再尝试传感器更新。拒绝、未知、求解失败、提前停机及未启动 case 保留在预登记分母内，单列未服务时间；未启动项没有伪造 worker 收据。训练前沿仅接受完成规定时域且通过共同实际终端 SOC 条件的策略，所有不合格候选仍在表中。模型事件频数与未知项的保守频数分别记录，不称现实概率。

## 实际协议与结果

首版 `configs/experiments/fixed-baseline-frontier-v1.json` 的 8 候选批次实际完成，产物在 `artifacts/baseline_frontier/public-eight-20261014-a`。4 个零终端缓冲的名义候选各两条训练运行均被原后验场景核验拒绝，未执行。首独立复核 1375/1376、退出 1，发现不同策略共享种子造成 RunID 歧义；数值核对通过。原批次、源码、退出码和失败报告保留。

由训练阶段的名义拒绝及明确同输入物理对照，新增协议 v2：4 个规则候选及 8 个名义候选扫描 10/20 mA、0/50 mV 固定裕度和 5e-6/1e-5 名义终端缓冲。新训练种子 2026101403/1404，新评价种子 2026101413/1414；每条执行两次 5 秒动作，预测两阶段。共同终端约束为各条实际初始 SOC 减 1e-5，量纲为无量纲 SOC。协议预登记后才读取这些新运行的结果。

当前协议在 `configs/experiments/fixed-baseline-frontier-v2.json`，当前代码 `556f9472aac248ea2fed7c5b8eaa668d1299c76757096633be45d7d6ba471ec4`。正式产物在 `artifacts/baseline_frontier/public-twelve-20261014-b`，公共 CLI 收据 `artifacts/validation/C01-twelve-fixed-baseline-family-tuning-freeze-new-paired-evaluation-5e7f94e9/command.json` 实际退出 0、186.706 秒。

24 条训练及 10 条评价运行全部完成两次实际动作和未来传感器更新。各族冻结两个并列前沿策略：规则 20 mA 两种电压裕度，以及名义 20 mA、5e-6 终端缓冲两种电压裕度。该短工况的 50 mV 裕度没有改变这些实际动作；保留并列结果，不伪造风险差异。

| 冻结后方法 | 每策略评价种子数 | 平均实际电能现金流 CNY |
| --- | ---: | ---: |
| 规则 20 mA，两种裕度各自登记 | 2 | 3.102157782981565e-8 |
| 名义 20 mA，5e-6 缓冲，两种裕度各自登记 | 2 | 2.6083839072781407e-8 |
| 固定场景 MPC 对照 | 2 | 2.877540756828692e-8 |

这些是合成价格下的实际电能现金流，不包含终端存储价值、维护、更换、残值或全生命周期结算。各臂期末 SOC 差异另存，`scientific_profit_comparability=false`；不能由该表宣称完整净收益优势。每臂只有两个新条件合成轨迹，配对策略不增加独立样本数，旧种子重跑也不增加。现实运营独立轨迹数为 0，风险证书为 false。

原始 `registration.json`、`freeze.json`、每 case 的 worker 日志/收据、计划、传感器、后验、evaluator 轨迹及 `ledger.json` 可重新核对。`points.csv` 和 `report.html` 由实际结果生成。非作者独立只读复核 2931/2931、实际退出 0：`artifacts/review/baseline-frontier-independent-20261014-a/artifact-report-current-v2-r1.json`；它没有新增 ODE、优化、PF、CLI、Lean 或 UI 运行。

成本派生表同目录 `cost-current-v2-r1.json/.csv` 分开列预测积分、未来 PF 独立计算/复用、实际 plant 积分、时延及来源再验证。每 case 的两次实际 `_packet` 再验证各有 36 次 parent/nominal 积分，总计 72 次；另有 3 次 t0 PF 更新。这个数来自源代码与实际调用边界核对，不冒充逐次新日志或独立样本。

## 复验和剩余范围

先生成当前源码的 fresh calibration，再使用新的输出目录运行上述 CLI；不覆盖历史包或日志。现有 `uv` 可执行权限受阻时，使用锁定 `.venv/Scripts/python.exe -m naheng.cli`。相关测试为 `test_fixed_baseline.py`、`test_baseline_frontier.py` 及原 `test_mpc_feasibility.py`、`test_scenario_mpc.py`、`test_shared_posterior.py`；完整回归另外留实际当前版本收据。

原 C01 工程验收已完成：当前源码 08705aadc91c 的完整回归 736 项、23 子测试退出 0，实际三动作 MPC 和 34 个共同执行约束的固定基线任务退出 0。独立复核覆盖源码 44 项、运行包 637 项、前沿 3067 项、执行约束 1147 项和重复场景 595 项。首次失败、预算 UNKNOWN 和历史版本记录保留。长期终端与全生命周期结算属于后续 C02；真实外测、运营统计、T3、七页工作台、报告回放和交付验收仍保持各自原门槛，完整项目未完成。
