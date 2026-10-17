# 模型包注册与可执行 DSL

`ModelRegistry.register(package, expected_hash=None)` 与 `applicable(package_id, snapshot, ambient_K)` 保持原签名。新增 `evaluate(package_id, state, inputs, parameter_revision=...)` 返回实际导数、读出、归约数值及包/参数身份。注册器的软件执行状态与正式证据状态分开：可执行不意味着已证明，证据默认 unverified。

完整包的状态、单位、参数版本、域、动态与读出均需核验。保留旧最小包兼容为 metadata_only，但不能求值，适用性返回 UNKNOWN，不能许可动作。当前已注册内建 `two_site_current_adapter_v1` / `synthetic_voltage_thermal_v1` 绑定实际 `SiteModel.rhs` / `observe`；声明必须与五状态及 SI 单位一致。参数快照进入参数哈希，源文件与模型/热/退化实现保存依赖哈希。表达式、参数或已绑定文件变化会使依赖失效，必须重新注册与复验。

归约映射 q 使用限定表达式语言 `N1*x1+N2*x2` 实际执行，输入只含登记状态、控制输入与已登记参数；不读取参考真值。这个数值映射不证明总量足够，也不建立反向精确重建。现有 uncertain_set lifting 仍声明信息损失。

通用 `dynamics_ast.kind=expressions_v1` 需要逐状态 typed AST、逐导数单位、显式 input_units，以及参数的 value/unit/source_id；读出需要匹配的 expressions/units。支持现有有界 AST 的算术、有限函数与变量；拒绝任意代码、属性访问、未声明变量、超限节点和非有限结果。加减项单位相同，exp/log 必须无量纲，导数单位是状态单位每秒。SI 内部不静默转换 ℃ 等单位。通用归约输出单位 schema 尚未实现，非空通用归约暂拒绝。

软件注册与数值 DSL 的范围不替代 F02–F05。完整理论误差、全时域域保持、模型到真实电芯误差、统计覆盖与证据再准入尚未完成；引用证据 ID 本身不能晋升 checked。当前运行器的动力学仍由实际 SiteModel 执行，新增通用 DSL 的执行已单独验收，尚未承诺运行器会切换到任意用户模型程序。

验收包含受限 AST 实际求值、Na 收支、输入变化、单位/版本拒绝、任意代码拒绝、隐藏真值拒绝、表达式/参数及依赖文件失效、metadata_only 未知。真实命令与日志在 artifacts/validation/P00-*。
