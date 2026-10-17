# 固定电流读出局部证明

八条定理保存于 `formal/Naheng/Reduction/FixedCurrentReadout.lean`，命名空间为 `Naheng.Reduction`。独立复核确认原命题、条件和证明正文保持，唯一数学修复是原第 68 行两次 `Finset.sum_mul` 的重写方向。正式定义模块实际 `lake build` 为 0，八项 `#print` / `#print axioms` 审计为 0；只依赖 `propext`、`Classical.choice`、`Quot.sound`。完整声明在 `artifacts/formal/readout-publication-ccfe9b55/axioms.log`，源码和日志哈希绑定在同目录 manifest。

两个状态使用同一组固定的 F、温度因子 theta、位点容量 N、速率 k、偏置、驱动尺度、电流 I、开路偏置 V0 和电阻。可逆电流平衡与 `SiteModel.solve_drive` 的标量表达式对应；副反应速率不进入该可逆电流适配器的平衡式。

| 声明 | 已证明内容 |
| --- | --- |
| `fixed_current_balance_matches_factored_solver` | 同一个精确实数电流平衡与求解器采用的提取公共指数形式相等。 |
| `fixed_current_occupation_residual_identity` | 同一驱动处两个占据状态的平衡差可展开为占据差的有限和。 |
| `fixed_current_occupation_residual_abs_bound` | 平衡差的绝对值由系数绝对值加权的占据差预算控制。 |
| `fixed_current_balance_hasDerivAt` | 从真实指数表达式推出驱动导数是负的斜率幅度。 |
| `fixed_current_strict_drive_secant_from_coefficients` | 已有整个闭区间上的正斜率下界时，平衡具有相应的严格割线下界。 |
| `fixed_current_drive_error_with_residuals` | 两个驱动都在该区间，且各自根残差经认证时，驱动差不超过占据预算与两个残差之和除以正斜率下界。 |
| `fixed_current_voltage_error_with_residuals` | 同温、同参数、同电流的仿射电压读出继承该驱动误差界，物理条件在声明中显式列出。 |
| `nonempty_fixed_current_slope_floor_example` | 给出满足正斜率下界的非空具体实数例子。 |

以上是有条件的精确实数证明。区间内所有驱动处的斜率下界、实际根残差和模型适用性必须独立提供。Brent 的停止容差、有限采样斜率、Python `exp` 或浮点仿射读出均不能直接证明这些条件。不同温度、电流、参数、闭环反馈或未知域不由该套件授权。

当前运行中的化学收支与瞬时速率预算仍通过各自重新构建、审计的显式指针调用。新八条读出定理尚未建立数值认证桥，因此不授予动作的严格 T3 权限，也不完成 full F02/core。原源码 492、首次实际编译失败产生的 `sorryAx` 输出、旧 120 秒 UNKNOWN 和独立审查首次失败均保留；失败候选没有发布。

当前八套局部发布的 74 项汇总见 `artifacts/formal/current-readout-partials-1fb9e802/manifest.json`。汇总仅核对已有真实构建、审计和当前文件身份，未再调用编译器。
