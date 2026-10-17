# 钠衡 · Naheng

**带形式化理论约束的钠离子电池全生命周期运维工作台**
A traceable sodium-ion battery lifecycle operations workbench, constrained by machine-checked chemistry and lifetime theory.

> **English abstract.** Naheng couples a particle-filter state estimator, conditional remaining-useful-life, per-event risk, MPC charge/discharge with thermal management, and energy-based cash accounting into one reproducible closed loop, exposed through a seven-page workbench. Its distinguishing feature is that **178 Lean 4 declarations** about the underlying chemistry and lifetime model are kernel-checked (relying only on `propext`, `Classical.choice`, `Quot.sound` — no `sorry`) and are **bound into the runtime by source-byte hash and re-verified before every execution**, so the theory constrains behaviour instead of decorating it. The system treats `UNKNOWN` as a first-class output: it reports 16 retirement times as unknown rather than interpolating them, and never converts a model-internal violation rate into an operational accident probability. This repository also documents a methodological finding we consider the most transferable result: **wall-clock evaluation budgets silently invalidate algorithm comparisons**, because identical deterministic work produced different training labels on the same machine minutes apart.

---

## 核心结果（全部可在本仓库内核验）

| 结果 | 数值 | 证据 |
|---|---|---|
| Lean 4 内核检查的形式声明 | **178 条，`status: checked`，退出码 0** | [`artifacts/formal/core/manifest.json`](artifacts/formal/core/manifest.json) |
| 每条声明的传递公理依赖 | **恰好** `propext` / `Classical.choice` / `Quot.sound`；无 `sorry`、`admit`、`sorryAx`、自定义结论公理 | 同上 `audit` 字段 |
| 形式模块分布 | 化学 42 · 状态归约 72 · 寿命 30 · 输出合同 34（46 个 `.lean` 源文件） | [`formal/Naheng/`](formal/Naheng/) |
| 工具链锁定 | `leanprover/lean4:v4.19.0` | [`formal/lean-toolchain`](formal/lean-toolchain) |
| 冻结的公开钠电测量 | **1,240,278 行**，训练/验证/测试角色按电芯与批次锁定，首次冻结后不再调参 | [`data/splits/zenodo13836819-eight-provenance-20261013-c.json`](data/splits/zenodo13836819-eight-provenance-20261013-c.json) |
| 独立参考模型 | 固定版本 PyBaMM `25.10.2`，`sodium_ion.BasicDFN` / Chayambuka2022 实际运行 | [`tests/integration/test_reference_sodium.py`](tests/integration/test_reference_sodium.py) |
| 数值回归（最近一次完整跑完的数值门） | **1153 passed / 23 subtests**，同轮 4 项失败已定位并修复（见 §结论三、四） | [`artifacts/verification/smoke-8e6b29d9b0/numerical_tests.stdout.log`](artifacts/verification/smoke-8e6b29d9b0/numerical_tests.stdout.log) |
| 修复后定向套件（本轮实测） | 证明隔离+发现闭环 **8 passed / 523.80 s**；生命周期 **5 passed / 89.74 s**；学习预算 **12 passed** | [`docs/STATUS.md`](docs/STATUS.md) 最新检查点 |
| 任务账本 | **45 项任务 / 18 项需求全部保留，35 项已按原验收条件完成** | [`TASKS.yaml`](TASKS.yaml) |
| 完整发布门 | `verify --profile release` **退出码 2（受阻/未验收）** —— 我们没有把它调成通过 | [`docs/CLAIMS.md`](docs/CLAIMS.md) |

---

## 结论一：把"未知"当一等公民，系统才真正可用

多数电池数字孪生的失效方式不是算错，而是**在该说"不知道"的地方给了一个数**。钠衡在四个层面把 `UNKNOWN` 做成一等状态：

- **寿命**：容量协议只在网格点上被观测，而网格观察**不能证明**网格之间的首次穿越时刻。因此 16 个退役时刻如实显示"未知"并附原因，而不是用单调性假设外推一个日期。运维方拿到的是可据以安排复检的区间，而非一个日后会被追溯为"系统说过 2027 年 3 月"的假精确值。
- **风险**：模型内 5 类原生事件（电压下/上限、温度下/上限、储库耗尽）的越限率，与"起火概率"是不同的东西。系统分别命名，并显式标注 `risk_certificate=false`、`population_calibration: not_performed`。析钠代理、电压越限、退役、火灾从不被合并成一个"失效事件"。
- **准入**：适用性未知**不默认放行**。模型包超出适用域时返回 unknown、动作被 withheld，而不是回退到一个"看起来安全"的默认策略。
- **学习**：UNKNOWN 的执行**消耗预算但绝不获得数值标签**。36 次查询里 34 次 UNKNOWN 就如实记 34 次，不插补、不剔除、不当负样本。

> 这套"未知语义"可直接迁移到任何带安全后果的预测系统：它把"模型不知道"从工程负债变成可审计的输出字段。

## 结论二：形式化证明只有在改变运行时行为时才有意义

我们给自己定了一条**消融判据**：若把证明徽章从界面隐藏而数值行为完全不变，系统性能应当一模一样。这条判据逼出三个真实调用点——

1. **模型包适用域**：定理条件（共同温度因子、参数范围、物理域、正速率）写入模型包，运行时逐条核对；
2. **误差预算**：瞬时速率残差界进入每一步的表示后验计算与动作准入；
3. **状态归约与切换**：精确聚合的充要条件决定"组总量"何时足以替代完整位点状态。

绑定是**字节级**的：T0 证明绑定精确状态/参数/源码哈希，每次执行前复核；证据被撤回或过期，严格权限立即失效，不复用旧指针。

### 理论侧的具体结果（模型内，非新自然规律）

- [`ClassSufficiency.lean`](formal/Naheng/Reduction/ClassSufficiency.lean)：组总量对真实总储钠导数与俘获速率**充分**的充要分类——当且仅当同组内 `r = a+b+c` 与 `c` 分别相同；**允许 `a` 在组内异质**。附四位点到两组的正速率实例，以及"总量不充分"的反例。
- [`GivenAmountResidual.lean`](formal/Naheng/Reduction/GivenAmountResidual.lean)：由三角不等式与容量加权系数均值导出 `|R| ≤ min(δq, δ(C−q))`。一个显式物理有理实例把界从 `δC = 2δ` 收到 `δ/2`（**4 倍收紧**）。更关键的是我们同时证明了：**一般参数下两种预算没有无条件的大小顺序**，必须在同一状态与参数下分别比较——这条"不能一般化"的结论本身就是防误用的护栏。
- **反例是成果的一部分**：[`HeterogeneousCounterexample.lean`](formal/Naheng/Reduction/HeterogeneousCounterexample.lean) 给出异质双位点组成在显式时间轨迹下**不闭合**；平/无穿越情形**不产生**无条件 RUL。这些均实际通过 Lean 检查，而非被绕过。

> **边界**：以上是在**已声明的合成模型**上的形式化，属于既有数学结构（精确/受约束 lumping、CLUE 框架、不变流形）的特例与工程连接。我们**没有**通过穷尽文献确认其数学新颖性，也**不主张**发现新的钠电自然规律。模型内证明**不是**现实电芯的安全认证。文献对照见 [`docs/NOVELTY.md`](docs/NOVELTY.md)。

## 结论三：墙钟预算会让算法对比整体失效，而且不报错

这是本轮最有推广价值的发现，因为它**推翻了我们自己的一组实验结论**。

主动学习要求对比三种查询策略（价值查询 / 随机 / 不确定性），每臂 36 次真实查询。结果为 2 / 2 / **0** 个有效结果，看起来像"不确定性采样在此问题上完全无效"。

真相是：三臂共用同一种子与同一 Latin Hypercube 设计，**前 12 个候选逐字节相同**。序数 6 那个候选的实际执行记录：

| 臂 | 声明工作量 | 实际完成的工作量 | 单步墙钟 | 判定 |
|---|---|---|---|---|
| 价值查询 | 24 次评估 / 120 s 上限 | **24 次评估、128 次积分** | 0.74 s | 完成 |
| 随机 | 同上 | **24 次评估、128 次积分（完全相同）** | 1.33 s | 6.02 s 被杀 → UNKNOWN |
| 不确定性 | 同上 | 未及记录 | — | 6.04 s 被杀 → UNKNOWN |

**同一份确定性工作，墙钟耗时从 0.55 秒摆动到超过 6 秒。** 三臂严格串行执行（时间窗互不重叠），因此不是彼此争抢 CPU，而是宿主背景负载。内层 6 秒墙钟守卫位于工作循环内部，会先于声明的工作预算掐断计算，于是——

> **训练标签变成了机器负载的函数，而不是候选参数的函数。**

而这一个硬币的正反面恰好决定该臂能否找到第一个可行点，进而决定整臂退出码是 0 还是 2。所谓"不确定性采样 0 有效"，测量的是那台机器在那 22 分钟里的负载曲线。

**修复**：保真度改为只由工作量单位定义（`max_iterations` 1/25、`max_candidate_evaluations` 24/120 **一字未改**），墙钟降级为宿主资源后备，并在代码内断言 `4 × 25 ≤ 120 − 8`，使其可证明不会抢先于每查询预算。物理模型、动作准入、预算配置、UNKNOWN 语义全部未动。见 [`docs/adr/0025-fidelity-effort-in-work-units.md`](docs/adr/0025-fidelity-effort-in-work-units.md) 与 [`src/naheng/learning/policy_space.py`](src/naheng/learning/policy_space.py)。

**验证**（重复执行同一封存候选）：低保真序数 6 → **5/5 全部 completed**，效用值完全一致（`3.0302705698157835e-09`），worker 墙钟 0.911–1.444 s 对 25 s 后备有约 17–27 倍余量；高保真序数 12 → **3/3 completed**，效用与约束裕度一致，四个 MPC 步骤的逐步工作序列完全相同。见 [`artifacts/a03-determinism-probe-20261016-c/report.json`](artifacts/a03-determinism-probe-20261016-c/report.json)。

**这条结论适用于任何仿真在环优化、硬件在环测试、AutoML 基准与强化学习评测**：只要被评估的工作量是确定的、而时限是墙钟的，负载就会渗透进标签，而且不报错——它只会安静地让某个算法看起来更差。三条可操作建议：

1. 用**工作量单位**定义保真度（迭代数、评估数、网格分辨率），墙钟只作宿主保护、不参与判定；
2. 算法对比必须做**同输入复现测试**：同一候选跑 N 次，断言标签与工作量计数器逐次相同——这比任何统计检验都更早暴露问题；
3. **警惕"一致的 UNKNOWN"**。我们的第一版探针因 5 次重复都返回 UNKNOWN 而判定"可复现"并退出 0，那是空洞通过。现在只要没真正跑到计算内核，一律判为"未测试"（退出 2）。

同一教训在本仓库的验收门层面再次出现：完整 smoke 门在主机被无关任务占满 8 核时于 1440 s 触顶（数值门 85%），`real_demo` 与 `foundation` 亦双双超时——而它们在同一代码上前一轮分别只用 48 s 与 61 s。我们如实记为**受阻**，未归因为代码回归，也未放宽门限。

## 结论四：负结果同样是结果，而且我们保留了它们

- **学习效用低于穷举**：A01 实测效用为 学习 **5.3994** / 随机 **4.4846** / 穷举 **5.9590**。学习明显优于随机，但**不及穷举**。我们没有把它包装成"学习方法领先"——在 144 个训练点、九维空间、每次评估约 1 秒的预算下穷举仍然可行，这本身就是关于问题规模的有用结论。
- **跨体系迁移没有优势**：公开钠电数据的电压迁移计算后 MAE **未显示优势**，且冻结 cohort 的实物物性映射仍为 UNKNOWN。该项（D02）因此保持未完成，而不是用"迁移可行"含糊过去。
- **相关性 ρ 未被辨识**：多保真的核心是低/高保真差异，但真实配对数只有 1，`ρ` 仍取默认单位值并显式标注 `rho_estimation: default_unit_not_identified`。我们**没有**据此声称"已学会保真度差异"。
- **108 次请求 ≠ 108 个独立样本**：同一后验缓存下的重复查询不构成统计独立。全部工件中 `scientific_N_added` 恒为 **0**。

---

## 仓库结构

```
src/naheng/          后端：模型、估计、风险、控制、经济、学习、运行时、API
  models/            双位点储钠 SiteModel 与积分器
  estimation/        粒子滤波、联合高斯观察器、标定会话
  risk/              事件风险与动作准入（accept / reject / unknown）
  control/           名义 MPC、固定基线、场景 MPC、受护执行
  economics/         能量账本（只记真实执行的能量流）
  learning/          约束 BO、多保真 GP、查询策略、策略空间、训练 oracle
  discovery/         候选语言、反例、受限证明 worker
  runtime/           冻结 worker、检查点续算、进程树、验证门
  api/               FastAPI（与前端唯一的接口）
formal/              Lean 4.19 + Mathlib：46 个源文件、178 条导出声明
frontend/            React 七页工作台（总览/状态/寿命/风险/策略收益/仿真对照/理论证据）
tests/               121 个测试文件（unit / integration / security）
tools/               254 个可执行验收、审计、诊断与交付工具
configs/             预算与验收门定义（execution.yaml / gates.yaml）
docs/                规格、状态、主张边界、ADR、用户指南、原始提案
artifacts/           精选证据收据（见下方"证据边界"）
data/                冻结划分与来源清单（不含原始 CSV）
```

## 快速开始

需要 Python ≥3.11,<3.14、[uv](https://docs.astral.sh/uv/)、Node.js（前端）、以及 Lean 4.19 工具链（形式检查，可用 [elan](https://github.com/leanprover/elan) 安装；`formal/lean-toolchain` 已锁定版本）。

```bash
uv sync --frozen --extra dev --extra reference

# 1. 环境体检（Python / Lean / Lake / uv / npm）
uv run --frozen --extra dev --extra reference naheng doctor

# 2. 真实数值闭环（合成输入、真实求解）
uv run --frozen --extra dev --extra reference naheng demo --scenario acceptance_loop --out artifacts/demo

# 3. 形式核心：178 条声明的内核检查与三公理审计
uv run --frozen --extra dev --extra reference naheng formal check --suite core

# 4. 七页工作台
npm --prefix frontend install && npm --prefix frontend run build
uv run --frozen --extra dev --extra reference naheng serve --host 127.0.0.1 --port 8000
#    → http://127.0.0.1:8000/

# 5. 验收门（退出码：0=全部通过，1=失败，2=必需项受阻/未验收）
uv run --frozen --extra dev --extra reference naheng verify --profile smoke
uv run --frozen --extra dev --extra reference naheng verify --profile release
```

默认 64 个表示样本 / 16 条预测路径 / 1800 秒服务时长，单次 worker 有 120 秒硬预算。全部预算声明在 [`configs/execution.yaml`](configs/execution.yaml)，验收门声明在 [`configs/gates.yaml`](configs/gates.yaml)。更完整的操作说明见 [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)。

> ⚠️ **`verify --profile smoke` 目前不保证通过**，原因见 §结论三末尾：数值门 1440 s 预算在"证明隔离测试真实调用 Lean（约 500 s）"叠加主机高负载时不足。请在空闲主机上运行，并预期它可能如实返回 2。

## 如何核验我们的主张

本仓库的原则是**主张与证据一一绑定**。三个入口：

1. [`docs/CLAIMS.md`](docs/CLAIMS.md) —— 主张与证据边界表：每一行把"可核对的主张 / 当前结果 / 原始证据路径"并列，并明确区分**工程命令退出 0**、**UNKNOWN** 与**科研验收通过**。
2. [`docs/STATUS_OVERVIEW.md`](docs/STATUS_OVERVIEW.md) —— 面向读者的状态概览：任务计数、未完成项与其阻塞原因。（逐轮真实命令与首次失败的完整追加日志属于内部工程记录，不随仓库发布。）
3. [`docs/adr/`](docs/adr/) —— 10 篇架构决策记录（编号至 0026），含理由、不变量与证据路径。

可独立复跑的两个诊断工具（只读，不生成新仿真、不伪造标签）：

```bash
# 从封存工件复现"同输入不同标签"的结论 → 退出 1 表示检出不可复现
python tools/diagnose_a03_label_determinism_20261016.py \
    --out artifacts/review/a03-label-determinism-20261016-a/diagnosis.json

# 重复执行同一封存候选，断言标签与逐步工作量一致（可证伪）
python tools/probe_a03_label_determinism_20261016.py \
    --ordinal 6 --fidelity low --repetitions 5 --out artifacts/a03-determinism-probe-20261016-c
```

### 证据边界（重要）

工作树的 `artifacts/` 有 2.6 GiB，其中绝大多数是运行轨迹、恢复测试转储与 Lean 构建产物，不适合放进仓库。**本仓库只包含被文档实际引用的收据与验收清单**；[`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md) 逐项列出包含内容与有意排除的内容及原因，[`BUNDLE_MANIFEST.json`](BUNDLE_MANIFEST.json) 记录文件数、字节数、被跳过的超大文件，以及**文档引用路径的核对结果**（哪些能在仓库内解析、哪些不能）。

引用核对与可移植性由两个工具机械执行，二者共享同一份豁免清单，因此"CI 检查什么"与"发布什么"不会漂移：

- [`tools/build_publication_bundle.py`](tools/build_publication_bundle.py) —— 构建本仓库：策展 `tools/`（保留 33 个，排除 227 个一次性会话脚本）、把证据收据里的本机绝对路径改写为 `<PROJECT_ROOT>` 等占位符（**工作树原件从不改写**，每个被改写文件的原始 SHA256 记录在 [`NORMALIZATION_SHA256.json`](NORMALIZATION_SHA256.json)）、扫描全部 Markdown 引用并逐条验证、最后再扫一遍 staging 树确认无残留本机路径。构建结果见 [`BUNDLE_MANIFEST.json`](BUNDLE_MANIFEST.json) 与 [`PORTABILITY_SCAN.json`](PORTABILITY_SCAN.json)。
- [`tools/check_portability.py`](tools/check_portability.py) —— 拒绝任何含本机绝对路径的源码进入发布集，CI 的第一个 job 就是它。

我们主动公开它们的输出，包括失效引用：例如 `docs/CLAIMS.md` 引用的 `artifacts/reports/learning-9593-20261016-d/generation.json` 在工作树中**并不存在**（该目录为空），真实的图表证据位于 `artifacts/handoff/r01-learning-figures-20261016-a/`。我们没有为了让引用看起来完整而改写既有主张文档；完整清单见 [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md)。

原始公开测量数据（303 MiB CSV）不在仓库内；[`data/manifests/`](data/manifests/) 保留来源、许可、逐成员 SHA256 与重新获取方式，[`data/splits/`](data/splits/) 保留冻结的角色划分。

---

## 明确的边界：本项目**不**主张

- ❌ 收益领先、成本优势或任何财务回报承诺——`risk_certificate=false` 恒成立，全部现金流标注为合成。
- ❌ 运营事故概率或火灾概率——模型内事件越限率不是人群标定的运营概率。
- ❌ 真实电芯安全认证——模型内 Lean 证明只认证它所证明的形式命题。
- ❌ 新的钠电自然规律或已确认的数学新颖性。
- ❌ 三臂查询策略的任何优势结论——原 2/2/0 结果已被证明是**无效对比**并保留在案，修复后的三臂尚未重跑（A03 仍为进行中）。
- ❌ 真实电芯物性映射、真实 RUL、`k=0, N=299` 的单次零事件检验——D02 与 X01–X04 仍未完成。

**尚未完成**：D02（公开钠电外测，阻塞于冻结 cohort 的实物物性映射 UNKNOWN）、A03（三臂重跑）、P03、X01–X04（预登记与 E-T/E-A/E-L 三组独立验收，缺一不可）、R00–R02（交付回放与安全、图表与研究报告、最终发布）。完整发布门退出码 **2**。

## 项目状态与治理

- 任务账本 [`TASKS.yaml`](TASKS.yaml)：**45 项任务 / 18 项需求全部保留，35 done / 2 in_progress / 8 todo**。`done` 的规则是"必须有实际命令、退出码、工件与日志；blocked 不算 done"。
- 需求覆盖 [`REQUIREMENTS.yaml`](REQUIREMENTS.yaml)，执行计划与决策日志 [`PLANS.md`](PLANS.md)，工作纪律 [`AGENTS.md`](AGENTS.md)，原始提案 [`docs/source/PROPOSAL.md`](docs/source/PROPOSAL.md)。
- 本轮工程记录：[`docs/REPORT_FINDINGS_20261016.md`](docs/REPORT_FINDINGS_20261016.md)（成果与洞见详版）。

## 参与共建

[`CONTRIBUTING.md`](CONTRIBUTING.md) 覆盖环境准备、跑测试、Windows 路径长度与主机负载这两个已知陷阱、验收门与提交规范，以及**欢迎接手的问题清单**。

其中最重要的一条：不得为了让检查变绿而削弱它——不改弱目标命题、不放宽守卫、不把验收脚本改成恒成功、不为 UNKNOWN 编造数值、不覆盖首次失败记录。如果你认为某个守卫本身是错的，请开 issue 论证。

可选的隔离证明后端不随仓库分发，其声明方式与"未声明时的确切行为"见 [`docs/PROOF_BACKEND.md`](docs/PROOF_BACKEND.md)。

## 许可

[MIT](LICENSE)。许可范围补充说明（真实电芯安全、第三方数据、形式证明的认证含义）见 LICENSE 末尾。
