# 钠衡 · 进展报告

**日期**：2026-10-16　**源码基线**：本轮修改前为冻结版 `9593`（`code_hash` 前缀 `95932c3d3d0ea0edec…`）
**范围**：本轮接手后的诊断、修复与验证。所有数字均来自实际命令与其退出码；未跑通的一律标注为未完成。

---

## 1. 摘要

项目当前 **35/45 任务完成、2 项进行中、8 项待办**，18 项需求全部保留，完整发布验收（`verify --profile release`）仍为退出码 **2**。

本轮没有新增功能，而是定位并修复了两个**阻碍验收推进的真实缺陷**：

1. **A03 三臂对比不可复现**——训练标签由宿主负载决定，而非由候选参数决定。已用封存工件证明，并修复、验证。
2. **smoke 门为红**（4 failed / 1153 passed）——上一次会话跑完但未记录结果。已定性全部 4 个失败并修复，验证进行中。

两者都在通往 `release` 的关键路径上：A03 阻塞 `P03 → X01 → X02/X03/X04 → R01 → R02`，smoke 门阻塞 `X00` 签收与 `R02`。

---

## 2. 发现一：A03 三臂对比的标签不可复现

### 2.1 现象

A03 要求比较三种查询策略（价值查询 / 随机 / 不确定性），每臂 36 次真实查询。封存结果为：

| 臂 | 有效结果 | UNKNOWN | 退出码 |
|---|---|---|---|
| learned（主） | 2 | 34 | 0 |
| random | 2 | 34 | 2 |
| uncertainty | **0** | **36** | 2 |

`TASKS.yaml` 中 A03 的 `blocker` 记录为「不确定性臂证据不足，怀疑启动/截止开销」。

### 2.2 根因（已证明，非推测）

三臂共用同一种子、同一 Latin Hypercube 初始设计，因此**前 12 个候选逐字节相同**（`candidate_id`、九维参数、`timeout_s=120` 全部一致）。

序数 6 的候选 `fba7c09c65…` 在三臂中的实际记录：

| 臂 | plan-0 | 每步工作量 | 结果 |
|---|---|---|---|
| learned | feasible，worker **0.741 s** | 24 次候选评估 / 128 次积分 | 4 步全部 feasible → **completed** |
| random | feasible，worker **1.325 s** | **24 / 128（完全相同）** | plan-1 在 `wall_s=6.024` 被杀 → unknown |
| uncertainty | 在 `wall_s=6.037` 被杀，无计数器 | — | unknown |

三臂是**严格串行**执行的（UTC 06:08:51→06:16:33、06:17:15→06:24:40、06:25:05→06:31:26），因此不是彼此争抢 CPU。

结论：**同一份确定性工作量（24/128），墙钟耗时从 0.55 s 摆到 >6 s**。`map_policy` 为低保真声明的 `wall_budget_s=6.0` 位于工作循环内部，在宿主有负载时会先于声明的工作预算掐断计算，从而把同一个候选判成不同标签。该单次成败又决定 `search.best()` 是否为空，进而决定整臂退出 0 还是 2。

因此不确定性臂的 0 有效结果**不是**「不确定性采样更差」的证据，而是这次抛硬币的结果。三臂对比在此状态下不构成有效科学比较。

> 这与上一轮自己的记录一致（导出转录第 29503 行）：「已定位到至少一个相同输入因进程启动、调度和结果返回占用了 6 秒额度而失败；下一轮修复会针对这段开销」。

### 2.3 修复

原则：**保真度只由工作量单位定义；墙钟降级为宿主资源后备，不参与标签判定。**

| 文件 | 改动 | 不变量 |
|---|---|---|
| `src/naheng/learning/policy_space.py` | `wall_budget_s` 6/15 → 统一 25 s 后备；新增代码内断言 `4 × 25 ≤ 120 − 8`，使其不可能抢先于每查询预算；映射中新增自描述的 `effort_semantics` | `max_iterations` 1/25、`max_candidate_evaluations` 24/120 **完全未改** |
| `src/naheng/learning/strategy_mpc.py` | incumbent 准入守卫的两处判定改为纯工作量表述，去掉随负载翻转的 `wall_budget_s <= 6.` 子句 | 守卫意图（仅低保真可接受 incumbent）完整保留 |

`configs/execution.yaml` 声明的预算**一项未动**：单次仿真 120 s、单次证明 120 s、8 GiB、整批 1800 s、12+24 查询数、24 次高保真上限。物理模型、动作准入、UNKNOWN 语义、`tell()` 的全部校验均未触碰。

### 2.4 验证

新增只读诊断与可证伪探针（两者都不生成新仿真、不伪造标签）：

- `tools/diagnose_a03_label_determinism_20261016.py` —— 只比对封存工件，退出 **1**，`divergent_ordinals=[6]`。
  证据：`artifacts/review/a03-label-determinism-20261016-a/diagnosis.json`
- `tools/probe_a03_label_determinism_20261016.py` —— 真实重复执行同一封存候选。

修复后探针实测：

| 探针 | 重复次数 | 状态 | utility | 每步工作序列 | worker 墙钟 |
|---|---|---|---|---|---|
| 低保真 ordinal 6（原分歧点） | 5 | **5/5 completed** | 全部 `3.0302705698157835e-09` | 一致（24/128 ×4 步） | 0.911–1.444 s |
| 高保真 ordinal 12 | 3 | **3/3 completed** | 全部 `1.2052483836389859e-08`，margin `-1e-12` | 全同 `[(25,132),(27,140),(27,140),(40,192)]` | 1.346–2.042 s |

对 25 s 后备的余量约 **12–27 倍**。

证据：`artifacts/a03-determinism-probe-20261016-{a,b,c,d}/report.json`

`pytest tests/integration/test_learning_budget.py -q --basetemp <HOST_TEMP_ROOT>` → **12 passed，退出 0**。

### 2.5 探针自身的两个缺陷（已修，保留首次失败）

诚实记录：探针第一版有两处问题，都会导致错误结论，已修正并保留失败产物。

1. **空洞通过**：标定包绑定 `code_hash`，改源码后旧包被守卫正确拒收，5 次重复全为 `unknown`，却因「彼此一致」而退出 0。已改为**未真正跑到 planner 一律退出 2**。
2. **误判高保真**：把 4 个 MPC 步骤的计数器扁平化成集合，导致同一次运行内部的正常差异被当成跨重复的不一致。已改为比较**逐步序列**。

首次失败保留在 `artifacts/a03-determinism-probe-20261016-a`（陈旧标定包）与 `-b`（路径守卫拒收）、`-d`（旧判据下的 exit 1）。

---

## 3. 发现二：smoke 门为红，且结果未被记录

### 3.1 实际结果

上一轮 `docs/STATUS.md` 记为「full E2E and smoke checks pending」，但该命令**实际已跑完并失败**：

`artifacts/current-smoke-9593-20261016-d.json` → 整体 **exit 1 / failed**

| 门 | 退出码 | 墙钟 | 状态 |
|---|---|---|---|
| numerical_tests | **1** | 932.33 s（未超时，上限 1440 s） | failed |
| real_demo | 0 | 48.28 s | passed |
| foundation | 0 | 61.12 s | passed |
| ui_acceptance | 0 | 1.63 s | passed |

日志 `artifacts/verification/smoke-8e6b29d9b0/numerical_tests.stdout.log`：
**4 failed, 1153 passed, 5 warnings, 23 subtests passed in 928.18 s**

失败项：

```
tests/integration/test_lifecycle_workbench.py::test_actual_lifecycle_worker_export_replay_and_checksum
tests/integration/test_lifecycle_workbench.py::test_lifecycle_cancel_retains_failed_cases_not_success
tests/integration/test_proof_worker_isolation.py::test_native_Lean_timeout_and_actual_retry
tests/integration/test_proof_worker_isolation.py::test_native_missing_executable_is_unknown_and_retryable
```

### 3.2 定性：两个根因，都不是产品逻辑回归

**(a) 临时目录不在授权根下（proof_worker ×2）**

`proof_worker.authorized_output()` 只允许 `ROOT/artifacts/{discovery,test-temp}`，并且**显式禁止 reparse point**、要求 resolve 后仍在授权根内。而 smoke 门的 pytest `--basetemp` 来自 `{temp}`，由 `NAHENG_VALIDATION_TEMP_ROOT` 决定（本次为 `<HOST_DATA_ROOT>\…`）。

关键在于：`verification.py` 的**默认**临时根是 `artifacts/verification/<run>/pytest`，同样不在授权根下。也就是说——

> 新增的 `test_proof_worker_isolation.py`（创建于 2026-10-16 12:38）把 pytest 的 `tmp_path` 当作证明输出目录传入，因此它在**任何** smoke 配置下都不可能通过。

时间线佐证：唯一收集到该文件的 smoke 就是 14:56 那次红门；此前最后一次绿跑 `smoke-c0aa2b9443`（00:38，1061 passed）日志中 `proof_worker` 出现 **0 次**——文件当时还不存在。**这个门从未带着该文件绿过。**

**(b) 临时目录路径过长（lifecycle ×2）**

判别实验：同一组测试换用**短** basetemp 即全绿。

```
pytest tests/integration/test_lifecycle_workbench.py -q --basetemp <HOST_TEMP_ROOT>
→ 5 passed, 89.74 s，退出 0
```

长 basetemp 下则 2 项失败（worker `state='failed'`、快照 manifest 缺失）。这与转录中已记录的 Windows 260 字符路径边界问题同源。

**(c) 被 (a) 掩盖的第三个真实缺陷：GBK 解码**

把 basetemp 换到授权根后，`test_native_missing_executable…` 转绿，但 `test_native_Lean_timeout_and_actual_retry` 换了一个新错误：

```
UnicodeDecodeError: 'gbk' codec can't decode byte 0x92 in position 201
```

`proof_worker.py` 有 4 处文本 I/O 未指定编码（`read_text()` ×3、`write_text()` ×1），在中文 Windows 上按 GBK 解码 UTF-8 的 JSON 证据。JSON 规范默认 UTF-8，因此这是无歧义的产品缺陷，且**与区域设置相关**——在 UTF-8 环境的机器上不会暴露。测试文件第 26 行（故意篡改源码以验证拒收）也有同一问题。

> 注：`UnicodeDecodeError` 是 `ValueError` 子类，会被 `prove_batch` 内部的 `except (… ValueError …)` 吞掉并降级为 `setup_unknown`；它能逃逸到测试层，说明触发点在 `register_checked` 或测试自身。两处同类缺陷均已修，以复跑结果为准。

### 3.3 修复

| 文件 | 改动 | 是否触及断言 |
|---|---|---|
| `src/naheng/discovery/proof_worker.py` | 4 处文本 I/O 显式 `encoding='utf-8'` | 否 |
| `tests/integration/test_proof_worker_isolation.py` | 新增 `proof_out` fixture，把证明输出放到授权根 `artifacts/test-temp/proof-worker-isolation/<uuid12>`；篡改源码那行补 UTF-8 | **否——全部断言逐字保留** |

这样测试**自带合法输出根**，不再依赖 `--basetemp` 落在哪里；smoke 门可继续使用短 D: 路径以满足 lifecycle 的长度约束。两个约束不再冲突。

未修改 `authorized_output` 守卫，未放宽任何断言，未跳过任何测试。

`src/naheng/discovery/dataset.py` 存在同类潜在编码缺陷（2 处 `read_text()`），但**不在本次失败路径上**（`candidate()` 在 704 s 前已成功执行），为保持改动面最小、可审计，本轮**未修改**，仅在此登记。

### 3.4 验证状态

进行中（后台任务 `b8z35ffip`）：

```
pytest tests/integration/test_proof_worker_isolation.py -q --basetemp <HOST_TEMP_ROOT>
```

选用 **D: 短 basetemp**，即 smoke 门的真实配置——若修复正确，4 项应全部通过。该测试真实调用 Lean，预计约 700 s。结果待回填。

---

## 4. 本轮真实命令与退出码

| 命令 | 退出码 | 结果 |
|---|---|---|
| `.venv/Scripts/python.exe -m naheng.cli doctor` | **0** | Python/npm/Lean 4.19.0/Lake 5.0.0/uv 0.9.9 可用；docker 缺失（计划允许） |
| `tools/diagnose_a03_label_determinism_20261016.py --out …/diagnosis.json` | **1** | 检出 ordinal 6 同输入不同标签 |
| `tools/probe_a03_label_determinism_20261016.py --ordinal 6 --fidelity low --repetitions 5`（`-a`） | 0 | **空洞通过**，已废弃并保留 |
| 同上（`-b`，修正标定包路径前） | 0 | 仍空洞通过，保留 |
| 同上（`-c`，标定包修正后） | **0** | 5/5 completed，utility 一致 |
| 同上 `--fidelity high --ordinal 12 --repetitions 3`（`-d`） | 1 | 旧判据误判；数据显示三步序列全同 |
| `pytest tests/integration/test_learning_budget.py -q` | **0** | 12 passed |
| `pytest tests/integration/test_proof_worker_isolation.py -q --basetemp <HOST_TEMP_ROOT>` | 1 | 2 failed（授权守卫拒收 D: 路径）——**修复前基线** |
| 同上 `--basetemp artifacts/test-temp/pwcheck` | 1 | 1 failed / 3 passed，704.17 s，暴露 GBK 缺陷 |
| `pytest tests/integration/test_lifecycle_workbench.py -q --basetemp <HOST_TEMP_ROOT>` | **0** | 5 passed，89.74 s |
| `pytest tests/integration/test_proof_worker_isolation.py -q --basetemp <HOST_TEMP_ROOT>` | 运行中 | 修复后验证 |

---

## 5. 环境与磁盘（影响后续所有验收）

| 项 | 实测 |
|---|---|
| C: | 146 G 总量，**仅剩约 1.3 G**（100% 已用） |
| D: | 330 G 总量，剩约 224 G |
| 项目占用 | `artifacts` 2.3 G、`formal` 1.2 G、`data` 303 M、`.tools` 97 M、`frontend` 66 M |
| git | 仓库已初始化，**尚无任何提交**，全部文件为 untracked |

C 盘余量是持续性风险：转录中已有多次 ENOSPC 与 260 字符路径导致失败的记录。本轮所有 pytest 临时目录与字节码缓存均指向 D:。

> 建议（未执行，需授权）：项目零提交状态下进行一次**仅源码**的本地初始提交（排除 `artifacts/`、`formal/` 大工件），可为后续修改提供可回滚基线。AGENTS.md 允许本地小粒度提交、禁止重写用户历史与强推。

---

## 6. 未完成与阻塞（未缩减任何需求）

| 任务 | 状态 | 阻塞 |
|---|---|---|
| D02 公开钠电外测 | in_progress | 冻结 cohort 的实物身份与物性映射仍 UNKNOWN；新论文与仿真不能替代对应测量 |
| A03 约束 BO / 多保真 | in_progress | 标签确定性已修复并验证；**三臂尚未在新源码上重跑**，故不升级 |
| P03 失配与证据撤回 | todo | 依赖 A03 |
| X01 预登记与强基线协议 | todo | 依赖 A03、P03、D02 |
| X02/X03/X04 E-T/E-A/E-L | todo | 依赖 X01；三组独立验收缺一不可 |
| R00 交付回放与安全 | todo | 依赖 P03 |
| R01 图表与研究报告 | todo | 依赖 X02–X04、R00 |
| R02 最终发布与交付 | todo | 依赖 R01、R00、F05、D02 |

`verify --profile release` 仍为退出码 **2**。smoke 门在修复验证通过前**不声称绿**。

---

## 7. 下一步

1. 收 `b8z35ffip` 结果，确认 4 项 proof_worker 测试在 D: basetemp 下转绿。
2. 以短 `NAHENG_VALIDATION_TEMP_ROOT`（如 `<HOST_TEMP_ROOT>`）重跑完整 `verify --profile smoke`，目标四门全 0。
3. 在修复后的冻结源码上**串行**重跑 A03 三臂（各 36 次真实查询，约 25 分钟计算），如实记录结果——包括不确定性臂若仍为 0 有效结果。
4. 写 ADR `0025`，记录 `wall_budget_s` 语义调整（保真度改由工作量单位定义）的理由、前后 SHA 与不变量，供独立审查推翻。
5. 更新 `TASKS.yaml`、`PLANS.md`、`docs/STATUS.md`，保留全部首次失败与旧证据。

---

## 8. 边界声明

- 本轮全部数值来自**合成研究模型**在固定条件下的真实计算；`scientific_N_added = 0`，未增加任何独立实验样本。
- 不声称收益优势、不声称风险证书（`risk_certificate = false`）、不声称真实电芯标定或运营概率。
- 确定性探针证明的是「同一候选在声明工作预算内给出同一标签」，**不是**全域证明，也不是现实电芯安全认证。
- 模型内 Lean 证明与运行时准入的关系仍由 E-L 连接消融单独验收，本轮未触及。
- 所有首次失败、超时与废弃判据的产物均按项目惯例原样保留，未由重跑覆盖。

---

## 附：本轮改动文件清单

**生产源码**
- `src/naheng/learning/policy_space.py`（前 SHA `c4cec28b…208abd`）
- `src/naheng/learning/strategy_mpc.py`（前 SHA `66c5b104…89efd5`）
- `src/naheng/discovery/proof_worker.py`（前 SHA `6fba32ec…4e75a`）

**测试**
- `tests/integration/test_proof_worker_isolation.py`（前 SHA `ddf53855…59e8`）

**新增工具**
- `tools/diagnose_a03_label_determinism_20261016.py`（只读诊断）
- `tools/probe_a03_label_determinism_20261016.py`（可证伪确定性探针）

**备份与证据**
- `artifacts/review/a03-label-determinism-20261016-a/backup/sha256-before.json`
- `artifacts/review/smoke-gate-repair-20261016-a/backup/sha256-before.json`
- `artifacts/review/a03-label-determinism-20261016-a/diagnosis.json`
- `artifacts/a03-determinism-probe-20261016-{a,b,c,d}/report.json`
