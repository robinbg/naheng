# 可选的隔离证明后端

`src/naheng/discovery/` 实现了"AI 候选 → 反例 → 证明尝试"的发现链。其中的候选代码与证明搜索**必须**在受限环境中执行——`AGENTS.md` 要求限制网络、文件与资源。本项目使用的实现是一个宿主特定的 QEMU + 离线 Linux guest + 锁定 Lean 工具链的后端，在 cgroup 内存/进程数限额、私有 namespace、断网条件下运行候选证明，并只接受来自该 live executor 签发的报告。

**这个后端不随仓库分发**：它是数 GiB 的机器特定镜像与预置依赖。因此它的位置由操作者声明，源码中不存在任何硬编码主机路径。

## 未声明后端时的行为

这是默认情况，也是 fresh clone 的情况：

| 调用 | 行为 |
|---|---|
| `verify_backend_inputs()` | 抛 `BackendUnavailable`，消息指出第一个缺失的钉住文件与声明方式 |
| `prove_batch(...)` | 返回 `status='permission_or_setup_unknown'`、`executed` 不为真、`kernel_checked=False` |
| `register_checked(...)` | 拒绝——没有 live executor 签发的报告就不能登记为已检查 |
| `offline_seed.prepare(...)` | 抛 `BackendUnavailable`（导入该模块不触发） |
| `tests/integration/test_proof_worker_isolation.py` | 3 个守卫测试照常运行；唯一驱动真实证明的测试**带明确原因跳过** |

关键性质：**后端缺失永远不会被解释为"证明通过"**。跳过与通过在输出中是不同状态，`kernel_checked` 保持 `False`。

## 声明后端

两种方式，环境变量优先：

```bash
# 方式一：环境变量
export NAHENG_PROOF_BACKEND_ROOT=/absolute/path/to/isolated-proof-backend
export NAHENG_PROOF_MAINTENANCE_ROOT=/absolute/path/to/prepared-dependencies

# 方式二：配置文件（已 gitignore）
cp configs/discovery/proof-backend-host.example.json configs/discovery/proof-backend-host.json
# 然后编辑其中的 backend_root / maintenance_root
```

两个值都必须是**存在的绝对路径**。相对路径会被拒绝并给出原因。

```python
from naheng.discovery.backend_host import availability_report
availability_report()   # {'available': bool, 'backend_root': ..., 'maintenance_root': ..., 'reason': ...}
```

## 后端需要提供什么

`configs/discovery/proof-backend.json` 钉住了 2012 个文件的 SHA256：guest 侧脚本、序列帧传输、诊断探针、以及被导入的形式源。`verify_backend_inputs()` 会逐个核对；任何一个缺失或改动都会使证明被拒绝，而不是被降级接受。这意味着：

- 你不能只放一部分文件就期望它工作；
- 你**可以**通过阅读那份清单，确切知道这个后端由什么构成；
- 任何对钉住文件的改动都必须由 `tools/repin_proof_backend_portability_20261017.py` 这类工具在机器校验后显式重钉，并留下 diff 工件。

## 没有后端也能验证的部分

形式化成果的主干**不依赖**这个后端：

```bash
uv run --frozen --extra dev --extra reference naheng formal check --suite core
```

它用本地 Lean/Lake 编译并逐条审计 178 条导出声明的传递公理依赖（只接受 `propext`、`Classical.choice`、`Quot.sound`）。需要 Lean 4.19 工具链与 Mathlib 依赖（首次联网获取，见 `formal/lake-manifest.json`）。

隔离后端影响的是**发现链中"在受限环境里真实执行候选证明"这一环**，不影响已发布的形式核心。
