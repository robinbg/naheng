# 来源与新增工程决定

## 来源提案

本包的任务范围以 `docs/source/PROPOSAL.md` 为依据：第1节全功能，第2节共享概率模型与双闭环，第3节化学形式化，第4节模型包，第5节联合决策，第6节三组实验，第7节产品，第8节交付，第9节边界。该副本来自用户当前对话的公开参赛提案；本包不依赖此前聊天或内部版本名称。

## 本包新增的内容

Python/FastAPI/React/Vite/Lean的具体组合、单机作业架构、文件名、任务依赖、API结构、预算与测试档位，是为开工给出的设计选择，不是提案已经实现的技术事实。候选定理规格是待证明任务；没有运行结果。由实际环境决定兼容锁版本，有理由的调整记ADR。

## 核验过的官方技术资料（2026-10-09）

[S1] OpenAI. Custom instructions with AGENTS.md. 原入口 https://developers.openai.com/codex/guides/agents-md ，现转到 https://learn.chatgpt.com/docs/agent-configuration/agents-md 。支持仓库级说明与逐层加载；本包采用短AGENTS＋分文件规格，不修改用户全局配置。

[S2] OpenAI. Using PLANS.md for multi-hour problem solving. https://developers.openai.com/cookbook/articles/codex_exec_plans 。参考其有可观察结果、里程碑、实际验证、恢复记录和持续更新的规划方式。文档不保证任意会话可以无限后台运行。

[S3] Lean. Axioms. https://lean-lang.org/doc/reference/latest/Axioms/ 。说明 `sorryAx`、`#print axioms` 与 native evaluation 的额外信任依赖。实施时锁定对应版本，审计传递依赖而非仅搜索文本。

[S4] PyBaMM v25.10.2. DFN model for sodium-ion batteries. https://docs.pybamm.org/en/v25.10.2/source/examples/notebooks/models/sodium-ion.html 。示例支持钠电DFN的起点；不据此断言所有热与退化子模型已经具备。网页已读，未在本次计划制作中安装或跑仿真。

[S5] BoTorch. Scalable Constrained Bayesian Optimization. https://botorch.org/docs/v0.17.1/tutorials/scalable_constrained_bo 。可作为约束BO实现与对照的官方起点；实际安装版本重新锁定。不从GP可行性直接推出现实电池的安全概率。

[S6] RWTH Publications. Data: Failure Mode and Degradation Analysis of a Commercial Sodium-Ion Battery With Severe Gassing Issue. https://publications.rwth-aachen.de/record/987579 。本次读取了资源页，不曾下载或校验原始数据；需要后续检查具体许可、文件和标签。

[S7] TUM mediaTUM 数据线索。https://mediatum.ub.tum.de/node?id=1762675 。本次网页读取失败，作为原计划中的待复核入口。不可记成“本次已下载/验证”；必要时查阅机构提供的同数据标识，或选择其他独立真实钠电来源并保留原失败记录。

[S8] Astral. Locking and syncing. https://docs.astral.sh/uv/concepts/projects/sync/ 。依赖解算后提交uv.lock，验收使用锁定环境。版本升级需解释理由并重新验证。

[S9] OpenAI. Run long horizon tasks with Codex. https://developers.openai.com/blog/run-long-horizon-tasks-with-codex 。参考其将执行指令、验证与进度放进仓库的做法，不依赖跨会话隐式记忆。

## 化学与控制研究入口

公开提案末尾已提供6项研究：化学物理Lean形式化；开放反应网络热力学；化学反应网络双模拟；热力学一致粗粒化；安全BO与电池MPC；老化控制与形式验证。Codex进行新增定理/方法的创新性核查时须读原始论文、检索相关定理与对照，不能仅依赖标题断言空白。

所有新增材料在 `data/manifests/sources.yaml` 或文献清单记来源、读取日期、许可及支持的具体主张。不得把来源页面的存在当作本项目实验成功的证据。
