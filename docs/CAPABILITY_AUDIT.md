# 实际后端能力探测

2026-10-10 当前恢复结果：项目内Lean4.19.0/Lake5.0.0实际可执行，官方ZIP断点续传exit0、5062成员CRC通过；PyBaMM短解+小型Lean证明的G03探测整体exit0。doctor已识别本地工具链（7项相关测试通过），环境记录artifacts/environment_lean_restored.json、详细命令artifacts/probes/lean-recovery.json。Docker仍缺失但为可选。mathlib/foundation项目化学证明尚待编译，不由工具链成功推断通过。以下为此前实测历史，失败保留。

本轮于 2026-10-09 实际运行 `python tools/probe_backends.py --out artifacts/probes`，最终退出 2（受阻）。Python 为现有 Anaconda 3.13.5；PyBaMM 子进程导入报 ModuleNotFoundError，子命令退出 1，不能声称短解完成。Lean/Lake 不在 PATH，也没有可用项目工具链。

官方 Lean 4.19.0 Windows release 在默认网络 HEAD 退出 7；权限允许的有界 HEAD 返回 HTTP 200。唯一一次 180 秒下载仅收到 2,899,949 / 478,683,633 字节，退出 28，`.tools/lean-4.19.0-windows.zip` 是未完成下载，不能运行。日志：`artifacts/probes/lean_download_head.log`、`lean_download_head_escalated.log`、`lean_download.log` 与对应 JSON。没有无限重试、全局修改或伪造证明。

`python tools/audit_formal.py --suite foundation --out artifacts/formal/foundation` 与 core 均实际退出 2。foundation 源码存在但 Lake build 未执行；evidence 为空，checked=false。core 因 T1/T2/T3 未实现也保持 blocked。对应 `artifacts/formal/foundation/manifest.json`、`core/manifest.json` 和 validation 日志是当前边界。

独立来源/审计测试 7 passed、退出 0，日志 `artifacts/formal/unit_tests.log`。这些测试只检查来源状态与 fail-closed 审计逻辑，不证明 Lean 源码通过。

已读 [PyBaMM 25.10.2 钠电说明](https://docs.pybamm.org/en/v25.10.2/source/examples/notebooks/models/sodium-ion.html) 的 BasicDFN 起点和来源说明；未在本项目完成求解。因此钠电短解、热动态、副反应、老化、全生命周期均未取得已通过的参考模型能力证据。官方示例参数对应 Chayambuka 2022 / COMSOL；禁止用默认锂电参数替代钠电。安装成功后必须重新运行 probe，并审阅它实际保存的模型源码、参数引用与变量清单。

## 2026-10-10 正常恢复与当前边界

PyBaMM25.10.2已在锁定.venv安装，G03恢复探测真实短解退出0，整体probe仍退出2，因为Lean/Lake缺失。证据为 artifacts/probes/reference-restored/pybamm_results.json 与 artifacts/validation/G03-reference-restored-probe-5e3fbce3。实际模型/参数源码、可用变量与版本均保存，不把导入成功当完整生命周期。

S02指定命令和真实集成测试退出0：artifacts/validation/S02-reference-cli-1519bc17、S02-reference-tests-corrected-42b1c0c4；产物 artifacts/reference_smoke/verified。10秒0.1C短解176点、实际电压/内部浓度/能量与8张参数表哈希。它是参考仿真，不是公共测量。热管理、副反应、老化、完整生命周期及严格库存证书均明确不支持，详见 REFERENCE_ADAPTER.md。原始失败结果继续保留。
2026-10-10 本轮最终依赖检查点：Lean工具链恢复仍为通过；mathlib源码实际checkout到锁定c44e0c8e/v4.19.0退出0，但Lake依赖初始化Git443连接失败。foundation-after-lean实际验收exit2，checked=false/evidence空。F00仍blocked；F01的ODE轨迹语义及P01具体证据绑定仍需实现。保留完整中断依赖/锁、失败和正常恢复日志，索引artifacts/formal/setup/checkpoint-after-lean.json。
