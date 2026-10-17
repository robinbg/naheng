# 已提供观测的诊断计算

本地入口：

```powershell
.venv/Scripts/python.exe -m naheng.cli diagnose --input input.json --out artifacts/diagnostics/new-analysis
```

输出目录必须是项目 artifacts 下的新目录，已有结果不覆盖。保存输入原字节、计算结果、源码及输入/结果 SHA256。命令退出 0 表示诊断检查执行完毕；每项诊断分别返回 PASS、FAIL 或 UNKNOWN。缺少观测的 UNKNOWN 不等于测量通过。

输入是严格 JSON，包含 analysis_id，以及可选的 ica_trace、ica_policy、impedance、snapshot、linearization、diagnostic_options、diagnostic_budget_s、rank_policy。不接受参考内部真值或执行代码。三个分量各自保留来源；公开测量不能因为与合成后验放在同一文件中，就成为合成化学体系的校准数据。source_ref 和采集条件是输入声明，来源真实性必须另核对。

ICA 使用 s、A、V、K 和库仑名义容量；外部 Ah 乘 3600。电流正号仍表示放电。满足声明的准静态、恒流、温度、采样、噪声和严格单调条件时，只计算实际相邻区间的电流梯形积分及 dQ/dV，不生成峰、重排或插值。累计转移电荷在该充放电模式下为正，因此充电 dQ/dV 为正、放电累计交付电荷的 dQ/dV 为负；它不是统一符号的储钠库存变化。显示 Ah/V 由 C/V 除 3600。工程质量策略未经过真实钠电通用阈值标定。

阻抗接口只读取已提供的频率、复数阻抗及采集条件。标量 AC 电阻不能作为 EIS 谱；缺少频率、小信号或稳态条件时保留 UNKNOWN。零复数阻抗保留零幅值，相位为 None/UNKNOWN；不把 atan2(0,0) 的程序值当作已知数学相位。

局部可辨识性使用已提供、与快照身份、状态单位和均值点绑定的 Jacobian，按状态尺度和观测噪声标准差进行缩放与 SVD。输出局部秩、零空间、重要模糊状态，并返回原后验的独立副本和哈希。PASS 表示局部计算完成，不表示隐藏状态已全部可识别；全局可辨识性始终保持 UNKNOWN。只有声明可用、条件齐全、提供真实敏感度且单项成本在预算内的诊断才会进入建议。信息值只是声明线性/Gaussian 假设下的局部代理量；没有同化观测或收紧后验。

当前证据包括原公共诊断测试 63 项、会话/CLI/共同契约针对性回归 18 项，以及两个真实本地入口结果：

- `artifacts/diagnostics/public-train-session-20261014-a`：已冻结公开训练成员的原行 1–256。Pulse 协议、重复电压、温度变化和未知噪声等原因使 ICA 不可用，曲线与阻抗谱为空；没有读取验证/测试数据做拟合。
- `artifacts/diagnostics/saved-synthetic-session-20261014-a`：独立读取既有合成 Run 的公开后验、模型包和传感器记录，物理源码绑定与包一致；实际有限差分两观测/七联合状态，局部秩 2、六项局部模糊状态。原粒子、权重和分位数不变。这是旧后验的只读分析，不是新的独立轨迹或真实电芯测量。

此入口属于 S05 工程诊断切片。当前没有真实 EIS 谱、真实合格 ICA 性能验收、参数校准或全局识别结论；Web 诊断页的进一步接入与完整交付验收按原 W02/X00 任务推进。
