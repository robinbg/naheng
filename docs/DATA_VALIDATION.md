# 公开钠电电压迁移试验

2026-10-15 当前补充：电压与容量两阶段已按原串行入口实际运行，完整任务退出 2，161.58 秒；其中电压阶段退出 2、计算完成但科学映射未知，容量阶段退出 0。工件为 `artifacts/public_validation/current-capacity-combined-20261014-b/manifest.json`，命令收据为 `artifacts/validation/D02-current-serial-voltage-plus-independent-capacity-rerun-fa6fb55d/command.json`。共有五项条件截止容量估计、三项 UNKNOWN；它们不构成 SOH、老化或寿命外测。原始失败与以前版本的数值保留在下文及对应工件中。

新增可运行的一手元数据映射在 `artifacts/handoff/d02-primary-mapping-research-20261015-a/`，17 项控制实际退出 0，用时 0.431 秒，未重新打开持出测量、拟合参数或增加科学样本。作者的 [Zenodo v1](https://zenodo.org/records/13836819) 及已冻结元数据给出：bat1/2/5 名义容量 3.2 Ah，bat3/4/6 为 10 Ah，额定电压 3.0 V、实验截止 1.5–3.9 V。Driving 预处理为 0.5C CC-CV 至 3.9 V、0.02C 截止和 1800 秒休息。因此名义电流可精确换算为 1.6/0.064 A 或 5/0.2 A；这些值没有被当成测量容量、隐状态初值或安全界，也没有套用到未说明相同预处理的 Pulse 文件。

作者 battery 编号尚未核实为独立实物电芯身份。当前能访问的一手资料仍不足以核定确切电极/电解液、几何、OCV/动力学、热参数、初始浓度和长期老化标签；出版社全文访问失败不表示论文没有这些信息。`metadata_mapping=PASS` 与 `physical_reference_mapping=UNKNOWN` 分开保存。原 cohort、角色、独立性和完整 D02 科学验收保持不变；不能把 0.003 Ah 参考模型按名义容量缩放后称为同电芯验证。

已实现命令：`.venv/Scripts/python.exe -m naheng.cli experiment run --suite public-data --profile pilot --out artifacts/public_validation/新目录`。原 TASKS 中的 `uv run` 命令保留；当前项目虚拟环境是实际执行的替代入口。

固定 cohort 为 `data/splits/zenodo13836819-eight-provenance-20261013-c.json`，绑定 SHA256 `c86f34c674f77fe7972f614ad1b88d0cf37531dc51d457479b17b4f837a4b539`。8 个完整原文件共 1,240,278 行，7 份唯一原内容；一份完全重复训练文件的 127,274 行没有重复拟合。划分以原作者协议组为单位，材料、电芯独立性和 IID 未知；文件数不算独立电芯数。

预测器仅使用前缀 V、I、实测温度和上一采样间隔，固定 ridge alpha=1。训练拟合 648,138 个窗口后先保存模型，才打开 validation/test；不利用下一条 I/T/dt，不用持出结果调参数。时间不递增、源边界和预声明的 60 秒以上间隔重置上下文；负电压及质量标记保留在主分析，同时另报未标记敏感性。正充电供应商电流按已核单位视图转换为正放电；辅助温度来自真实列而非文件名的环境温度。

5837 版本真实公共产物位于 `artifacts/public_validation/pilot-current-20261014-a`。命令退出 2、78.245 秒，owned Windows Job 硬限制 120 秒和 8 GiB；`execution_completed=true` 与 `D02_complete=false` 分别表示计算完成和完整任务未完成。对应完整原测试及新增测试 735 项、23 子测试通过，源文件前后字节相同。之后恢复模块改动的源码不能直接沿用这份全版本验收；旧产物仍按原版本回放。

| 留出组 | 实际预测窗口 | ridge MAE / V | 上一电压 MAE / V |
| --- | ---: | ---: | ---: |
| validation | 332,601 | 0.002610273840571852 | 0.002540456056957134 |
| test | 131,540 | 0.001187354138486673 | 0.0010717633179261057 |

两组 MAE 均没有优势。保存的 CSV、模型、来源哈希、预登记协议和报告允许重算。独立评审分别执行 67 项合成方法控制、108 项保存数据算术、23 项公共接入控制和 47 项公共产物/版本检查；它们不作为科学样本 N。重复运行新增独立样本数为 0。

同电芯物理参考比较保持受阻。公开文件的电极/电解液/初始物理参数未知；已有 reference_sodium 是 0.003 Ah hard-carbon/NVPF、NaPF6 EC-PC、规定 298.15 K 及常量正倍率范围，不能假装匹配 3.2/10 Ah 的变电流和实测变温数据。没有制造同材料 DFN 残差、容量/老化标签、SOC/SOH/RUL、事故率或真实收益结果。容量和老化等完整 D02 指标及所有原科学门仍需完成。

首次来源角色采用漏洞已修正为校验完整 catalog/policy/cohort、全部成员与预先固定角色，CLI 额外核不可变 cohort 哈希；原失败、模型、测试与评审记录全部保留。独立交接分别在 `artifacts/review/public-sodium-causal-independent-20261014-a/handoff.json` 和 `artifacts/review/public-sodium-public-entry-independent-20261014-a/handoff.json`。

恢复修复后的 08705aadc91c 版本已实际重跑：`artifacts/public_validation/pilot-current-20261014-b`，命令退出 2、82.335 秒，计算完成而完整 D02 未完成。该版本完整回归 736 项、23 子测试退出 0；当前产物独立 47/47 检查退出 0，封存在 `artifacts/review/public-sodium-current-after-hard-exit-independent-20261014-a/handoff.json`。原数据、模型和数值没有变化，重复新增独立样本数为 0。后续新增生命周期代码属于新的全版本，不能改写这些旧版本收据。
