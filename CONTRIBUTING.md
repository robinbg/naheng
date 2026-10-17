# 参与共建

感谢你的兴趣。这个项目有一条不寻常但很重要的纪律，请先读完 §1 再提交 PR——它决定了你的改动会不会被接受。

## 1. 最重要的一条：不得为了让检查变绿而削弱它

`AGENTS.md` 是本项目的工作约定，其中几条对贡献者同样适用：

- **不得**改弱目标命题、放宽物理/准入守卫、或把验收脚本改成恒成功。
- **不得**为 UNKNOWN 的结果编造数值标签。证明器超时就是 UNKNOWN。
- 数值采样没有反例 **不等于** 全域证明；模型内证明 **不等于** 现实电芯安全认证。
- 首次失败、超时与被废弃的判据**原样保留**，不由重跑覆盖。
- 未实测的任务不得标记为完成（`done` 必须有真实命令、退出码、工件与日志）。

如果你认为某个守卫本身是错的，请在 issue 里论证，不要直接在 PR 里绕过它。

## 2. 环境准备

需要 Python ≥3.11,<3.14、[uv](https://docs.astral.sh/uv/)、Node.js ≥20（前端）。形式化部分需要 Lean 4.19（建议用 [elan](https://github.com/leanprover/elan) 安装；`formal/lean-toolchain` 已锁定版本）。

```bash
uv sync --frozen --extra dev --extra reference
uv run --frozen --extra dev --extra reference naheng doctor   # 期望 exit 0
```

`doctor` 会报告每个工具链是否可用。Docker 是可选的；缺失不影响其余部分。

### 可选：隔离证明后端

`src/naheng/discovery/` 下的候选证明可以在一个资源受限、断网的 guest 中真实执行。该后端是数 GiB 的机器特定镜像，**不随仓库分发**。未声明时，相关代码返回 `BackendUnavailable`（归类为 setup-unknown，绝不算 checked），依赖它的那一个测试会带明确原因跳过。声明方式见 [`docs/PROOF_BACKEND.md`](docs/PROOF_BACKEND.md)。

### CI

`.github/workflows/ci.yml` 已在工作树中就绪（可移植性扫描、Python 3.11–3.13 矩阵、前端构建、发布包引用核对，Lean 形式核心按需触发），但**尚未随仓库发布**：GitHub 拒绝没有 `workflow` 权限的令牌创建工作流文件。维护者运行 `gh auth refresh -h github.com -s workflow` 后把它放回 `.github/workflows/` 即可启用；在那之前请按 §3 本地跑测试。

## 3. 跑测试

```bash
# 快速子集（不需要 Lean，也不需要后端）
uv run --frozen --extra dev --extra reference pytest tests/unit -q

# 完整数值套件（约 15–25 分钟，视机器而定）
uv run --frozen --extra dev --extra reference pytest tests/unit tests/integration tests/test_registry_dsl.py -q

# 安全相关
uv run --frozen --extra dev --extra reference pytest tests/security -q
```

### Windows 用户请注意临时目录路径长度

部分测试会创建很深的临时目录。Windows 的 260 字符路径边界会让它们以 `FileNotFoundError` 失败，而这**不是**代码缺陷。请给 pytest 一个短的 `--basetemp`：

```bash
pytest tests/integration/test_lifecycle_workbench.py -q --basetemp <HOST_TEMP_ROOT>
```

同一组测试在短路径下通过、在长路径下失败，是这个问题的判别方法。

### 墙钟预算与主机负载（重要）

本项目的评估预算按**工作量单位**声明（迭代数、候选评估数），墙钟只作为宿主资源后备——这是有原因的，见 [`docs/adr/0025-fidelity-effort-in-work-units.md`](docs/adr/0025-fidelity-effort-in-work-units.md)。

如果你在主机高负载时运行，**墙钟敏感的门可能超时**，而这不代表代码回归。请：

1. 先确认主机空闲（本项目曾遇到数值门在 8 核被其他任务占满时于 1440 s 触顶，而同一代码在空闲时只需 932 s）；
2. 若某项在负载下超时、空闲下通过，请在 issue 中同时给出两组数据；
3. **不要**通过延长单次证明/仿真的 120 s 限制或跳过慢项来"修复"超时。

## 4. 验收门

```bash
uv run --frozen --extra dev --extra reference naheng verify --profile smoke
uv run --frozen --extra dev --extra reference naheng formal check --suite core
uv run --frozen --extra dev --extra reference naheng verify --profile release
```

退出码约定：**0** = 该档要求全部通过；**1** = 失败；**2** = 必需项受阻/未验收。`smoke` 通过不代表 `release` 通过。当前 `release` 如实返回 **2**。

`formal check --suite core` 需要 Lean 工具链与 Mathlib 依赖（首次需联网获取，见 `formal/lake-manifest.json`）。它会编译并逐条审计 178 条导出声明的传递公理依赖，只接受 `propext`、`Classical.choice`、`Quot.sound`。

## 5. 提交规范

- **小步提交**，每个提交对应一个可验收的切片。
- 提交信息说明**做了什么**和**如何验证**（命令 + 退出码）。
- 改动了行为就要更新对应文档：主张变化更新 [`docs/CLAIMS.md`](docs/CLAIMS.md)，设计决策新增一篇 [`docs/adr/`](docs/adr/) 记录（编号递增），任务状态更新 [`TASKS.yaml`](TASKS.yaml)。
- 新增实验或指标必须带 RunID、模型/参数/策略/数据/代码标识，并区分 `synthetic` / `reference_simulation` / `public_measurement` / `replay` 四类来源。
- 不要在源码中写入本机绝对路径。CI 会扫描并拒绝。需要主机特定位置时，走 `src/naheng/discovery/backend_host.py` 那套"由操作者声明、缺失时明确报错"的模式。

## 6. 目录导航

| 路径 | 内容 |
|---|---|
| `src/naheng/models/` | 双位点储钠 `SiteModel` 与积分器 |
| `src/naheng/estimation/` | 粒子滤波、联合高斯观察器、标定会话 |
| `src/naheng/risk/` | 事件风险与动作准入（accept / reject / unknown） |
| `src/naheng/control/` | 名义 MPC、固定基线、场景 MPC、受护执行 |
| `src/naheng/economics/` | 能量账本（只记真实执行的能量流） |
| `src/naheng/learning/` | 约束 BO、多保真 GP、查询策略、训练 oracle |
| `src/naheng/discovery/` | 候选语言、反例、受限证明 worker |
| `src/naheng/runtime/` | 冻结 worker、检查点续算、进程树、验证门 |
| `formal/Naheng/` | Lean 4.19 证明：Chemistry / Reduction / Aging / Contracts |
| `docs/specs/` | 模型与形式化规格、数据契约、实验设计 |
| `configs/` | 预算（`execution.yaml`）与验收门（`gates.yaml`） |

## 7. 已知的、欢迎接手的问题

- **D02**：冻结 cohort 的实物身份与物性映射仍为 UNKNOWN。需要可接纳的一手钠电物性来源；新论文与仿真不能替代对应测量。
- **A03**：标签确定性问题已修复（ADR 0025），但三臂对比尚未在修复后的源码上重跑，因此**没有**任何查询策略的优势结论。
- **X01–X04**：预登记与 E-T/E-A/E-L 三组独立验收实验尚未完成。
- **smoke 门预算**：证明隔离测试开始真实调用 Lean 后，数值门 1440 s 预算偏紧；在不放宽单次 120 s 限制的前提下重新分配预算是一个明确的待办。

issue 模板见 [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/)。
