# 局部形式套件直接检查定义模块

变系数轨迹与容量端点的发布首次检查在 120 秒内未完成纯 import 包装入口。正常增量复验仍保留其 UNKNOWN 结果。日志能确认叶模块已构建或缓存读取，不能据此声称入口或整套声明审计通过，也不足以归因于 native 编译或链接。

将两个局部 suite 的构建和审计 import 指向实际定义定理的 `Naheng.Reduction.VariableTrajectory` 与 `Naheng.Aging.CapacityEndpoint`。纯 import 包装文件保留；全部声明、证明正文、导出目标、适用范围、120 秒单次限制及逐声明传递公理审计不变。新结果仍须实际 `lake build` 和全部 `#print` / `#print axioms` 均为 0 才能 checked。

此选择不改变完整 reduction、aging、contracts 或 core 的未完成目标，也不授予未来轨迹、首次退役、读出误差、浮点或现实安全证书。模块选择的实际修改记录、原 checker 副本与未变文件哈希保存在 `artifacts/formal/publication/definition-modules-*`，早先失败工件保留。
