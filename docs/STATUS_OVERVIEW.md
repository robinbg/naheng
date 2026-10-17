# 实施状态概览

本文件是面向读者的状态概览。逐轮真实命令、退出码与首次失败的完整追加日志属于内部工程记录，不随仓库发布。

任务总数 **45**，需求 **18** 项，全部保留。

| 状态 | 数量 |
|---|---|
| done | 35 |
| in_progress | 2 |
| todo | 8 |

## 未完成项

* **D02** (in_progress, M2) — 公开钠电外测与参考差异报告
  * 阻塞：冻结cohort实物身份与物性映射仍UNKNOWN；新论文和仿真不能替代对应测量。
* **A03** (in_progress, M4) — 约束BO、多保真及价值边界学习
  * 阻塞：Root cause found and repaired, task NOT upgraded. The prior 2/2/0 three-arm result is an INVALID comparison, kept on record and not overwritten: all arms share one seeded LHS design, ordinal6 is byte-identical across arms, yet it completed in the learned arm and was killed at wall_s 6.024/6.037 in the other two after doing the SAME 24 evaluations/128 integrations. Arms ran strictly sequentially, so host load, not contention, swung identical deterministic work from 0.55s past the 6s inner wall guard. Labels were therefore a function of machine load, and one flip decided search.best() and each arm exit code. Per ADR0025 fidelity is now declared by work units only (max_iterations 1/25 and max_candidate_evaluations 24/120 unchanged); wall_budget_s became a 25s host backstop asserted not to pre-empt the 120s per-query budget. Remaining: three arms must be re-run serially on one frozen source before any comparison is recorded; no rho/advantage gate added; no advantage claim.
* **P03** (todo, M4) — 失配、证据撤回与重新准入
  * 阻塞：Original A03 dependency remains incomplete. No extra success requirement for unsupported monitored checkpoint recovery has been added.
* **X01** (todo, M4) — 冻结强基线与三组协议
  * 阻塞：Public integration/actual registration and D02/independent trajectory/theory-family/adapter dependencies remain.
* **X02** (todo, M4) — E-T理论与AI方法实验
  * 阻塞：等待必需前置任务：X01, A02, F05
* **X03** (todo, M4) — E-A完整应用及独立风险收益验收
  * 阻塞：等待必需前置任务：X01, D02, S04, A03, P03
* **X04** (todo, M4) — E-L理论到应用连接消融
  * 阻塞：等待必需前置任务：X01, P02, P03, W02
* **R00** (todo, M5) — 本地启动、回放与安全交付
  * 阻塞：Original P03 dependency remains incomplete; current original Edge E2E and new clean-package final independent review pending. Docker is optional. Missing trusted proof closure separately blocks full M5/R02 and stays UNKNOWN in this package.
* **R01** (todo, M5) — 图表、研究报告与论文素材
  * 阻塞：Original X02/X03/X04/R00 dependencies and complete research report acceptance remain incomplete; progress artifacts are not release reports.
* **R02** (todo, M5) — 完整发布审计与交付
  * 阻塞：13 required tasks and independent theory/application/linkage/public scientific audits remain incomplete.

完整发布门 `verify --profile release` 目前返回退出码 **2**（必需项受阻/未验收）。
主张与证据边界见 [CLAIMS.md](CLAIMS.md)。
