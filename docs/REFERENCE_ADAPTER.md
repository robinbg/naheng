# 独立钠电参考适配

适配固定 PyBaMM 25.10.2 的 `sodium_ion.BasicDFN` 与 `Chayambuka2022` 参数。
参数源码登记硬碳负极、NVPF 正极和 NaPF6/EC:PC 电解液；数值及插值表来自论文所关联的 COMSOL 示例。
这条通道属于 `reference_simulation`，不是本项目下载或采集的真实电芯测量。
依据为 [固定版本参数源码](https://github.com/pybamm-team/PyBaMM/blob/v25.10.2/src/pybamm/input/parameters/sodium_ion/Chayambuka2022.py) 与 [固定版本官方示例](https://docs.pybamm.org/en/v25.10.2/source/examples/notebooks/models/sodium-ion.html)。

执行 `python -m naheng.models.reference_pybamm --duration-s 10 --c-rate 0.1 --out artifacts/reference_smoke`。
输出实际求解得到的电压、电流、三类浓度诊断、能量积分和求解终止原因。
模型源码、参数源码和随包插值表的 SHA256 一并保存，JSON 原始轨迹与 CSV 观测可复算。
浓度均值是算术空间均值，不能用作体积加权库存守恒证书。

模型使用指定的 298.15 K 等温条件；参数函数没有提供可据此标定的温度依赖。
当前适配不支持热动力学、热管理、副反应、老化或全生命周期，明确拒绝这些请求。
2.0/4.2 V 截止仅属于该参数集，不作为通用钠电安全阈值。
适配器允许的时长/倍率上限是软件执行预算，完整温区、倍率域和真实电芯误差仍未验收。

参考模型与快速位点模型实现和参数独立，但仍可能共享电化学守恒、DFN 与动力学假设。
尚未建立两位点状态或参数到 DFN 的映射，不向此 DFN 硬塞抽象位点参数。
本次短轨迹不能证明寿命、安全事故概率或收益优化效果。

依赖缺失或版本不匹配时返回 `MissingBackend`，命令退出 2，保存 blocked 清单且没有电压产物。
数值失败保存 failed 清单，退出 1；只有真实求解和产物保存成功才退出 0。
依赖恢复、运行及测试日志分别由 `tools/run_evidence.py` 留存；最终状态以实际日志和产物为准。

## 2026-10-10 实际验收

第二次有界依赖恢复按原锁成功，退出 0，耗时 143.99 秒；此前 240 秒超时记录仍保留。
新进程实际核验 PyBaMM 25.10.2、CasADi 3.6.7、pybammsolvers 0.3.3、NumPy 2.5.3、SciPy 1.18.1、pandas 3.0.6、pyarrow 22.0.0。
依赖恢复证据为 `artifacts/validation/G03-reference-recovery-418270b2`，版本核验为 `G03-environment-consistency-298263ad`。
安装结束后不再同步或更换依赖。

实际目标命令为：

```text
uv run --frozen --offline --no-sync --extra dev --extra reference naheng simulate --model reference_sodium --profile probe --out artifacts/reference_smoke/verified
```

该命令退出 0，保存 0.1C/10 秒的 176 个真实求解点；电压从 4.040750132208162 V 变到 4.038972338070957 V，执行电能数值积分为 0.01211901173239818 J。
`artifacts/reference_smoke/verified/trace.json`、`observations.csv` 与 `manifest.json` 保存完整结果；参数源码与八个实际 `data/*.csv` 表的哈希都已登记。
运行证据为 `artifacts/validation/S02-reference-cli-1519bc17`。

真实集成验收检查两种电流实际改变解、内部浓度、能量重算、导出重新打开、工件哈希和不支持能力拒绝；2 项通过，退出 0。
证据为 `artifacts/validation/S02-reference-tests-corrected-42b1c0c4`。
首次验收有 1 项失败：CSV 哈希查找没有进入固定版本的 `data/` 目录；修复实际文件路径后重跑，未放宽测试。
首次失败保留在 `S02-reference-tests-68801f99`；首次实际轨迹保留在 `artifacts/reference_smoke/first`。
上游 SciPy/PyBaMM 类型转换 FutureWarning 和 pytest 缓存写入警告均保留在日志；没有因此跳过真实求解或降低门槛。
