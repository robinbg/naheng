# 实施状态概览

本文件是面向读者的状态概览。逐轮真实命令、退出码与首次失败的完整追加日志属于内部工程记录，不随仓库发布。

任务总数 **45**，需求 **18** 项，全部保留。

| 状态 | 数量 |
|---|---|
| done | 38 |
| in_progress | 1 |
| todo | 6 |

## 未完成项

* **D02** (in_progress, M2) — 公开钠电外测与参考差异报告
  * 阻塞：冻结cohort实物身份与物性映射仍UNKNOWN；新论文和仿真不能替代对应测量。
* **X01** (todo, M4) — 冻结强基线与三组协议
  * 阻塞：Public integration/actual registration and D02/independent trajectory/theory-family/adapter dependencies remain.
* **X02** (todo, M4) — E-T理论与AI方法实验
  * 阻塞：Runner implemented and unit-verified but NOT registered, and the suite is blocked. src/naheng/experiments/et_runner.py implements the ten preregistered E-T metrics from real evaluations (applicable_domain_coverage 1.0, checked_theorem_rate 723/1167 across 59 manifests, heldout_model_family_generalization 16/16, counterexample_replay_rate 48/48, candidate_count 144) and reports downstream_value and known_vs_new_result_identity as null with reasons because they are not computable in this suite. experiments/theory.py is the bounded worker. execute() calls require_authorization first and refuses with exit 2 without writing a result while the registration denies E-T; registering the adapter is a separate reviewable step (REGISTERED_ADAPTERS) and was not self-certified. Suite authorization additionally stays blocked by D02 through ORIGINAL_DEPENDENCY_INCOMPLETE, and by THEORY_FAMILY_SPLIT_MISSING and the B0-B6 baseline runners.
* **X03** (todo, M4) — E-A完整应用及独立风险收益验收
  * 阻塞：等待必需前置任务：X01, D02, S04, A03, P03
* **X04** (todo, M4) — E-L理论到应用连接消融
  * 阻塞：等待必需前置任务：X01, P02, P03, W02
* **R01** (todo, M5) — 图表、研究报告与论文素材
  * 阻塞：Original X02/X03/X04/R00 dependencies and complete research report acceptance remain incomplete; progress artifacts are not release reports.
* **R02** (todo, M5) — 完整发布审计与交付
  * 阻塞：13 required tasks and independent theory/application/linkage/public scientific audits remain incomplete.

完整发布门 `verify --profile release` 目前返回退出码 **2**（必需项受阻/未验收）。
主张与证据边界见 [CLAIMS.md](CLAIMS.md)。
