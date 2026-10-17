## 2026-10-15 当前 WSL 实测状态（新增明确授权后）

用户在本对话明确批准唯一发行版 `Naheng-Research-20261015-b-a02`、`<HOST_DATA_ROOT>/distro`、新 HKCU 登记及可能的首默认状态，并批准一次可信只读诊断和定向终止。旧“无发行版”记录是导入前事实，保留作历史证据。

已独审计划 `d3fc2a4f24d4811773e4fd73e1a79d7f1795cecc358bf1ef506ff5aa66be5b5e` 的实际导入退出0/98.868秒（300秒上限）；只读诊断退出2/51.083秒（120秒上限）。实际GUID `{f52fa247-08ef-4d78-91f6-2d8c5040019a}` 与唯一D路径绑定。两次均仅定向终止该自有发行版，运行列表为空；未卸载、未全局shutdown。宿主Job active=0及句柄关闭不代表Linux guest进程数已核0，后者保持未知。

实际guest有 `/mnt/wsl`、`/mnt/wslg`、`/init` 共享/互通桥，cgroup v2根的subtree_control为空，memory.max/swap.max/pids.max不可用。自身RLIMIT_AS=8GiB不是聚合内存限制。因此候选执行、Linux Lean、8GiB/64 PID/私有namespace/断网与原40次证明、8项隔离门均未完成，不把安装成功称为A02通过。不改全局挂载、网络、ACL或根cgroup控制器。

真实收据位于 `<HOST_MAINTENANCE_ROOT>/a02-linux-import-supervisor-20261015-a/runs/import-140202-48ee0800/command.json` 和同owner的 `readonly-probe-140532-20deebb7/command.json`；审批记录为 `artifacts/authorization/a02-new-WSL-human-approved-20261015-a/approval.json`。项目源码/测试/模型与解释器版本不因导入改变。

# 实测环境与仓库接入

2026-10-15：为恢复已满的 C 盘，将项目自有 Lean 安装完整移存到 `<HOST_DATA_ROOT>/lean-4.19.0-windows-owned-20261015-a`，原 `.tools/lean` 保留精确目录 junction。4614 文件、1,681,110,243 字节逐项 SHA256 和修改时间核验一致；源码、当前化学证明及活动证据指针不变。迁移实际退出 0；原 C 入口的 `lean --version`、`lake --version`、`lean --print-prefix` 三项实际退出 0，分别为 Lean 4.19.0、Lake 5.0.0 及可解析到 D 的原入口。证据为 `artifacts/maintenance/owned-lean-relocation-20261015-a/probe.json` 与 `artifacts/validation/C-relocated-Lean-Lake-original-entry-native-probes-c064236d/command.json`。首次清单因 C 盘满退出 1 已保留；迁移清单、完整 D 副本和恢复阶段记录均未删除。后续运行需要此 D 盘路径可读。

完整178条核心声明已实际分批编译并审计，严格三公理白名单保持；本轮完整 smoke 内再次实际 core 退出 0（457.18 秒）。这与 A02 候选代码的操作系统权限隔离是不同验收：Windows 实验沙箱实际返回“不支持”，已有 WSL 组件但无发行版，尚未安装或启动新的 Linux 环境。

2026-10-10 当前恢复结果：项目内Lean4.19.0/Lake5.0.0实际可执行，官方ZIP断点续传exit0、5062成员CRC通过；PyBaMM短解+小型Lean证明的G03探测整体exit0。doctor已识别本地工具链（7项相关测试通过），环境记录artifacts/environment_lean_restored.json、详细命令artifacts/probes/lean-recovery.json。Docker仍缺失但为可选。mathlib/foundation项目化学证明尚待编译，不由工具链成功推断通过。以下为此前实测历史，失败保留。

2026-10-10 首轮实施。工程位于本工作区 outputs/naheng。用户指定 cwd 原本仅空 outputs/work，git status / rev-parse 返回非仓库；开工包仅规格及包级检查工具。安全解压保留全部原始文档，新建 Git 仓库，没有重置或删除已有代码；当前没有已提交代码，不伪造 commit。

已读取本会话 AGENTS 约定和包内 AGENTS、PLANS、TASKS、REQUIREMENTS、PROPOSAL 及计算/接口规格。原包共45任务、18必需需求。

Windows 11，8逻辑核；Python 3.13.5、Node24.11.0、npm11.6.1、Git2.51.2。项目 .bootstrap 内 uv0.9.9，uv.lock 已真实解算，.venv 核心依赖实际安装。精确版本以 artifacts/environment_locked.json 与 uv.lock 为准，不能把系统环境测试等同锁环境。

首次联网 pip 受沙箱网络限制；经授权的项目级依赖安装成功。首次全部 Python extras 安装240秒超时，核心安装通过缓存正常恢复并退出0。Lean456MiB工具链下载180秒仅2.9MiB后超时，保留日志和不完整包，未再无限重试。PyBaMM参考依赖后来正常安装、版本/真实短解已复验；Docker、Lean/Lake仍未发现。首轮环境与失败日志保留，当前工具能力见 artifacts/environment_final.json（退出2，原因是Lean缺失）。

依赖安装日志归档 artifacts/validation，参考/形式探测 artifacts/probes。没有读取其他目录凭据，外部 LLM、收费算力、公开部署和硬件控制保持禁用。

缺少官方电芯、截止时间、服务规则及外部API预算不阻塞合成研究计算；相应真实数据、商业收益与研究验收不被替代。

一次界面计算与参考依赖安装重叠，导出阶段pandas处于中间状态而失败；旧RunID保持failed。之后冻结依赖安装、重启服务、由界面创建新Run正常恢复。已加入作业执行前后核心安装版本与冻结lock检查，记录execution_environment.json；它不声称二进制级可复现。

2026-10-10 本轮最终依赖检查点：Lean工具链恢复仍为通过；mathlib源码实际checkout到锁定c44e0c8e/v4.19.0退出0，但Lake依赖初始化Git443连接失败。foundation-after-lean实际验收exit2，checked=false/evidence空。F00仍blocked；F01的ODE轨迹语义及P01具体证据绑定仍需实现。保留完整中断依赖/锁、失败和正常恢复日志，索引artifacts/formal/setup/checkpoint-after-lean.json。
