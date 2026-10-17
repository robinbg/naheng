# 完整核心验证包装预算

原 `verify formal/release` 的 core gate 没有显式 timeout，因此把完整 CLI 批次按单次证明的 120 秒截止。完整178声明已实际分十批内核审计通过，各 native 调用小于120秒，完整 CLI 用688.78秒；外层120秒会错误截断已合法实现的完整批次。

只为两处原 core gate 设置1500秒的完整批次包装预算，保持同一原命令、全部178目标、原命题和严格三公理白名单。`checker.run_command` 的单次native上限仍120秒，内层1800秒本地批次预算及8GiB执行限制不变；不删除任何审计，失败、缺失和超时仍不能授予部分证据。其余 gate、45任务、18需求与原验收命令不改。

旧默认core目录先逐字节保存在 `artifacts/progress/core-verification-wrapper-20261014-a/prior-default-core`，包装配置的原字节也在同目录。随后必须实际执行原 `verify --profile release`；未完成任务和独立科学门仍需退出2，不能由形式化通过替代。
