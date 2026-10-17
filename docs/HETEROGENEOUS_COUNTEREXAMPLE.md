# 异质双位点总量闭合反例

定义模块为 `formal/Naheng/Reduction/HeterogeneousCounterexample.lean`，局部检查入口为 `naheng formal check --suite reduction_heterogeneous_counterexample`。它导出原来冻结的八个声明；出版只移除十六行诊断打印并修改一条候选状态注释，保留 `pp.proofs false`。五个定义、八个命题头、条件和证明体与通过当前 Lean 检查的原字节一致。

模型采用两个单位容量位点。总量 `q=x₀+x₁` 与组成差 `d=x₀−x₁` 能还原两个状态，因此 `(q,d)` 是可逆坐标变换，没有减少维度。最初四条定理从实际位点右端项导出总量和组成差的恒等式，并将它们连接到分别满足原 ODE 的已给定可微轨迹。

后四条使用正的不同外部固定系数 `0<k₀<k₁`，分别令每个位点的正反向速率相同、副反应系数为零。对 `0<u<v<1`，交换两位点初值不改变初始总量，却改变总量导数。实际显式解是

`xᵢ(t)=1/2+(xᵢ(0)−1/2) exp(−2 kᵢ t)`。

平衡值为 `1/2`。定理同时证明两条解在所有非负时间保持严格占据域，在每个正时间具有不同总量；因此该固定系数问题不存在对所有域内状态通用的仅依赖总量的闭合右端项。

这没有证明同电流反馈的 `SiteModel` 读出反例、任意位点容量、任意位点数或电压/温度输出等价。实际模型继续保留各个位点状态；此套件不单独授予运行时单状态替代、浮点/求解器误差认证、严格 T3、真实电芯安全或完整 F02/core 权限。化学收支与瞬时残差原有运行连接仍通过各自当前证明指针校验。

候选证据位于 `artifacts/formal/candidates/heterogeneous-next-20261014-a`：当前原字节 kernel 检查退出 0、35.632 秒；`publication-delta.json` 的精确逆变换恢复原文件；`publication-structure.json` 逐段核对定义和证明体。独立出版候选复核为 66/66、退出 0，见 `artifacts/review/heterogeneous-publication-independent-20261014-a/candidate-accepted-report-r2.json`。历史首次编译失败和旧 105 项只读复核均保留，旧报告没有找到单独外层运行收据，不能补造。

安装记录为 `artifacts/formal/publication/heterogeneous-d81fa5f9/manifest.json`；安装记录仅表示源码接入，正式构建和逐声明传递公理审计另行保存。只有当前实际检查通过的 manifest 可作为 checked 声明证据。完整需求的原验收门槛保持。

正式模块构建和八条声明逐项打印/传递公理审计已实际退出 0，仅依赖 `propext`、`Classical.choice`、`Quot.sound`。新增导出后，原八套也重新构建审计；九套共 82 个唯一声明，当前汇总为 `artifacts/formal/current-heterogeneous-partials-7f00a1d9/manifest.json`。整个真实批次收据为 `artifacts/validation/F02-all-nine-current-defining-module-builds-and-strict-axiom-audits-f6544d43/command.json`，退出 0、328.268 秒；每条 Lean 子命令均在原 120 秒界内。此批次没有完成空目标的完整核心套件。
