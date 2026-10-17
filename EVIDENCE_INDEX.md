# 开源包内容与边界

本仓库是工作树的**可审阅、可运行子集**，共 15.96 MiB。
* 源码/测试/工具/配置/Lean 源/前端源：374 个文件
* 精选证据收据：383 个文件
* `tools/` 策展：保留 34 个，排除 228 个一次性会话脚本
* 路径规范化：173 个文件的本机绝对路径已改写为占位符
* 引用核对：246 条可解析，4 条为有意提及的不存在路径，133 条不可解析

## 路径规范化规则

证据收据记录的是产出它的机器上的绝对路径。发布副本按下列规则改写，**工作树原件从不改写**；
每个被改写文件的原始 SHA256 记录在 `NORMALIZATION_SHA256.json`，因此该变换可审计、可逆向。

| 原前缀（账号名已脱敏） | 占位符 |
|---|---|
| `(?:[\\]{2,4}\?[\\]{1,2})?C:[/\\]{1,2}Users[/\\]{1,2}<HOST_USER>[/\\]{1,2}Documents[/\\]{1,2}Codex[/\\]{1,2}2026-10-09[/\\]{1,2}agents-md-plans-md-tasks-yaml[/\\]{1,2}outputs[/\\]{1,2}naheng` | `<PROJECT_ROOT>` |
| `C:[/\\]{1,2}Users[/\\]{1,2}<HOST_USER>` | `<HOST_HOME>` |
| `D:[/\\]{1,2}Naheng-Research-VM-[0-9A-Za-z\-]+` | `<HOST_BACKEND_ROOT>` |
| `D:[/\\]{1,2}Naheng-Maintenance` | `<HOST_MAINTENANCE_ROOT>` |
| `D:[/\\]{1,2}Naheng-Delivery-Validation-[0-9A-Za-z\-]+` | `<HOST_DELIVERY_ROOT>` |
| `D:[/\\]{1,2}Naheng-[0-9A-Za-z\-]+` | `<HOST_DATA_ROOT>` |
| `D:[/\\]{1,2}nh[0-9A-Za-z\-]*` | `<HOST_TEMP_ROOT>` |
| `<HOST_USER>` | `<HOST_USER>` |

权威正则见 `tools/build_publication_bundle.py` 的 `NORMALIZATIONS`；本表与清单只作说明，因此不重复发布被移除的标识符本身。

## 有意排除

* `artifacts/` 批量工件（2.6 GiB）—— 运行轨迹、恢复测试转储、审查工作树
* `formal/.lake/` —— Lean 构建产物；用锁定工具链 `lake build` 重建
* `data/raw/`（303 MiB）—— 第三方公开测量原始 CSV，按其上游许可保留在原处；`data/manifests/` 提供来源、许可、逐成员 SHA256 与重新获取方式
* `.venv/` `.bootstrap/` `.tools/` —— 解释器、uv 与 Lean 工具链
* `frontend/node_modules/` `frontend/dist/` —— `npm install` 与 `npm run build` 可重建
* `tools/` 中 226 个一次性会话脚本 —— 见上方策展计数
* `docs/STATUS.md`（742 行追加式会话日志）、`START_CODEX.md`、`HANDOFF_CHECK.json` —— 内部工程记录
* `configs/discovery/proof-backend-host.json` —— 本机后端位置；已 gitignore，发布 `.example` 副本

## 文档有意提及、但本包内不存在的路径

* `artifacts/demo` —— output target of the `naheng demo` quick-start command; created when the reader runs it
* `artifacts/reports/learning-9593-20261016-d/generation.json` —— cited in README as a worked example of a broken citation inside docs/CLAIMS.md; the directory is empty in the working tree and the real figure evidence lives in artifacts/handoff/r01-learning-figures-20261016-a/
* `artifacts/test-temp/proof-worker-isolation` —— runtime directory created by the proof-output fixture while tests run
* `docs/STATUS.md` —— the 700-line append-only session log is internal; docs/STATUS_OVERVIEW.md is published instead

## 不可解析的引用

这些路径出现在文档中但不在本包内：多数是 `docs/` 中历史检查点里"下一条执行命令"的输出目标（命令尚未运行，或输出已被后续轮次取代），少数属于被排除的批量工件。全部如实列出。

* `artifacts/a03-determinism-probe-20261016-` —— 被引用于 `docs/PROGRESS_REPORT_20261016.md`, `docs/REPORT_FINDINGS_20261016.md`
* `artifacts/authorization/a02-new-WSL-human-approved-20261015-a/approval.json` —— 被引用于 `docs/ENVIRONMENT.md`
* `artifacts/baseline_frontier/public-eight-20261014-a` —— 被引用于 `docs/BASELINE_FRONTIER.md`
* `artifacts/baseline_frontier/public-twelve-20261014-b` —— 被引用于 `docs/BASELINE_FRONTIER.md`
* `artifacts/baseline_frontier/public-twelve-20261014-d` —— 被引用于 `PLANS.md`
* `artifacts/calibration/frontier-after-heterogeneous-20261014-c` —— 被引用于 `PLANS.md`
* `artifacts/calibration/frontier-current-20261014-d` —— 被引用于 `PLANS.md`
* `artifacts/calibration/joint-current-20261014-a` —— 被引用于 `docs/JOINT_GAUSSIAN_OBSERVER.md`
* `artifacts/data/D01_import_split_bound_command.json` —— 被引用于 `docs/DATA_INGESTION.md`
* `artifacts/data/public_new/check_import_and_split_v2.py` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `artifacts/data/public_new/imported_instrument_step_v2` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `artifacts/data/public_new/independent_source_review.json/.log` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `artifacts/diagnostics/new-analysis` —— 被引用于 `docs/DIAGNOSTICS.md`
* `artifacts/diagnostics/public-train-session-20261014-a` —— 被引用于 `docs/DIAGNOSTICS.md`
* `artifacts/diagnostics/saved-synthetic-session-20261014-a` —— 被引用于 `docs/DIAGNOSTICS.md`
* `artifacts/environment.json` —— 被引用于 `PLANS.md`
* `artifacts/environment_final.json` —— 被引用于 `docs/ENVIRONMENT.md`
* `artifacts/environment_locked.json` —— 被引用于 `docs/ENVIRONMENT.md`
* `artifacts/experiments/preregistrations` —— 被引用于 `experiments/protocols/README.md`
* `artifacts/formal/candidates/heterogeneous-next-20261014-a` —— 被引用于 `docs/HETEROGENEOUS_COUNTEREXAMPLE.md`
* `artifacts/formal/candidates/heterogeneous-next-20261014-a/check_once.py` —— 被引用于 `PLANS.md`
* `artifacts/formal/publication/heterogeneous-d81fa5f9/manifest.json` —— 被引用于 `docs/HETEROGENEOUS_COUNTEREXAMPLE.md`
* `artifacts/formal/readout-publication-ccfe9b55/axioms.log` —— 被引用于 `docs/FIXED_CURRENT_READOUT.md`
* `artifacts/formal/setup/extend_plan-62385f1c/stdout.log` —— 被引用于 `PLANS.md`
* `artifacts/formal/unit_tests.log` —— 被引用于 `docs/CAPABILITY_AUDIT.md`
* `artifacts/frontend-stage` —— 被引用于 `docs/USER_GUIDE.md`
* `artifacts/frontend-stage.json` —— 被引用于 `docs/USER_GUIDE.md`
* `artifacts/full-policy-random-6fc49921be/checkpoint.json` —— 被引用于 `docs/adr/0025-fidelity-effort-in-work-units.md`
* `artifacts/full-policy-uncertainty-6ecf182273/checkpoint.json` —— 被引用于 `docs/adr/0025-fidelity-effort-in-work-units.md`
* `artifacts/handoff/a02-delegated-backend-20261016-a/boot_fixed_proofs_r2.py` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a02-delegated-backend-20261016-a/boot_owned_canary_r4.py` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a02-delegated-backend-20261016-a/fetch_runtime_packages_r2.py` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a02-delegated-backend-20261016-a/prepare_proof_seed_utf8.py` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a02-delegated-backend-20261016-a/qemu_payload.py` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a02-delegated-backend-20261016-a/runtime-dependencies-wave2.json` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a02-integrated-vm-worker-20261016-a/evidence/original-eight-20261016-a` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a02-integrated-vm-worker-20261016-a/invoke.py` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a02-integrated-vm-worker-20261016-b/evidence/actual-loop-20261016-b` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a02-integrated-vm-worker-20261016-b/evidence/original-eight-20261016-b` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a02-integrated-vm-worker-20261016-b/invoke.py` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a02-integrated-vm-worker-20261016-c/evidence/original-eight` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a02-integrated-vm-worker-20261016-c/invoke.py` —— 被引用于 `PLANS.md`
* `artifacts/handoff/a03-constrained-search-20261016-a/run_pilot.py` —— 被引用于 `PLANS.md`
* `artifacts/handoff/d02-primary-mapping-research-20261015-a` —— 被引用于 `docs/DATA_VALIDATION.md`
* `artifacts/handoff/r01-install-current-20261016-b/current-selection-template.json` —— 被引用于 `docs/EVIDENCE_REPORT.md`
* `artifacts/handoff/r01-learning-figures-20261016-a/candidate/tools/render_learning_evidence.py` —— 被引用于 `artifacts/handoff/r01-learning-figures-20261016-a/README.md`
* `artifacts/joint_scenario_calibration/public-current-20261014-a` —— 被引用于 `docs/CALIBRATION.md`, `docs/JOINT_GAUSSIAN_OBSERVER.md`
* `artifacts/lifecycle_finance` —— 被引用于 `docs/LIFECYCLE_FINANCE.md`
* `artifacts/lifecycle_finance/public-current-20261014-c` —— 被引用于 `PLANS.md`, `docs/LIFECYCLE_FINANCE.md`
* `artifacts/lifecycle_validation/compare_cycle_maps.py` —— 被引用于 `docs/LIFECYCLE.md`
* `artifacts/maintenance/owned-lean-relocation-20261015-a/probe.json` —— 被引用于 `docs/ENVIRONMENT.md`
* `artifacts/maintenance/owned-python-import-cache-8431e9e0/cache-index.json` —— 被引用于 `docs/adr/0024-owned-checked-hash-import-cache.md`
* `artifacts/performance/frontier-real-profile-58ae6804/manifest.json` —— 被引用于 `docs/adr/0024-owned-checked-hash-import-cache.md`
* `artifacts/probes/lean_download_head.log` —— 被引用于 `docs/CAPABILITY_AUDIT.md`
* `artifacts/probes/reference-restored/pybamm_results.json` —— 被引用于 `docs/CAPABILITY_AUDIT.md`
* `artifacts/progress/capacity-data-20261013-0f4a4518/NOVELTY.md` —— 被引用于 `docs/NOVELTY.md`
* `artifacts/progress/core-verification-wrapper-20261014-a/prior-default-core` —— 被引用于 `docs/adr/0021-complete-core-verification-wrapper.md`
* `artifacts/progress/input-20261013-0420-gates.json` —— 被引用于 `PLANS.md`
* `artifacts/progress/input-20261013-0450-preclose.json` —— 被引用于 `PLANS.md`
* `artifacts/public_validation` —— 被引用于 `docs/DATA_VALIDATION.md`
* `artifacts/public_validation/current-capacity-combined-20261014-b/manifest.json` —— 被引用于 `docs/DATA_VALIDATION.md`
* `artifacts/public_validation/pilot-current-20261014-a` —— 被引用于 `docs/DATA_VALIDATION.md`
* `artifacts/public_validation/pilot-current-20261014-b` —— 被引用于 `docs/DATA_VALIDATION.md`
* `artifacts/recovery` —— 被引用于 `docs/USER_GUIDE.md`
* `artifacts/recovery-tests` —— 被引用于 `docs/CHECKPOINT_RECOVERY.md`
* `artifacts/reference_smoke` —— 被引用于 `docs/REFERENCE_ADAPTER.md`
* `artifacts/reference_smoke/first` —— 被引用于 `docs/REFERENCE_ADAPTER.md`
* `artifacts/reference_smoke/verified` —— 被引用于 `docs/CAPABILITY_AUDIT.md`, `docs/REFERENCE_ADAPTER.md`
* `artifacts/reference_smoke/verified/trace.json` —— 被引用于 `docs/REFERENCE_ADAPTER.md`
* `artifacts/release-after-C02-20261014-a.json` —— 被引用于 `PLANS.md`, `docs/LIFECYCLE_FINANCE.md`
* `artifacts/release-after-next-source-20261014-b.json` —— 被引用于 `PLANS.md`
* `artifacts/reports/current-progress-review-20261016-b` —— 被引用于 `docs/EVIDENCE_REPORT.md`
* `artifacts/reports/learning-9593-20261016-d` —— 被引用于 `docs/REPORT_FINDINGS_20261016.md`
* `artifacts/reports/learning-current-two-review` —— 被引用于 `artifacts/handoff/r01-learning-figures-20261016-a/README.md`
* `artifacts/review/baseline-frontier-independent-20261014-a/artifact-report-current-v2-r1.json` —— 被引用于 `docs/BASELINE_FRONTIER.md`
* `artifacts/review/d01-final-original-scope-20261014-a/gate.py` —— 被引用于 `PLANS.md`
* `artifacts/review/heterogeneous-publication-independent-20261014-a/candidate-accepted-report-r2.json` —— 被引用于 `docs/HETEROGENEOUS_COUNTEREXAMPLE.md`
* `artifacts/review/p03-installed-ui-independent-20261016-c/handoff.json` —— 被引用于 `docs/CLAIMS.md`
* `artifacts/review/public-sodium-causal-independent-20261014-a/handoff.json` —— 被引用于 `docs/DATA_VALIDATION.md`
* `artifacts/review/public-sodium-current-after-hard-exit-independent-20261014-a/handoff.json` —— 被引用于 `docs/DATA_VALIDATION.md`
* `artifacts/review/public-sodium-public-entry-independent-20261014-a/handoff.json` —— 被引用于 `docs/DATA_VALIDATION.md`
* `artifacts/review/python-checked-hash-cache-independent-20261015-a/handoff.json` —— 被引用于 `docs/adr/0024-owned-checked-hash-import-cache.md`
* `artifacts/runs` —— 被引用于 `docs/USER_GUIDE.md`
* `artifacts/runs/evaluator` —— 被引用于 `docs/CHECKPOINT_RECOVERY.md`
* `artifacts/scenario_calibration` —— 被引用于 `docs/CALIBRATION.md`
* `artifacts/scenario_calibration/public-20261014-b` —— 被引用于 `docs/SCENARIO_MPC.md`
* `artifacts/smoke-current-core-20261015-a.json` —— 被引用于 `PLANS.md`
* `artifacts/smoke-current139f-core-20261015-b.json` —— 被引用于 `PLANS.md`, `docs/adr/0023-full-smoke-aggregate-and-short-windows-test-owner.md`
* `artifacts/smoke-current142e-core-20261015-c.json` —— 被引用于 `PLANS.md`
* `artifacts/smoke-current142e-core-20261015-d.json` —— 被引用于 `PLANS.md`
* `artifacts/smoke-current142e-core-20261016-a.json` —— 被引用于 `PLANS.md`
* `artifacts/test-temp/pwcheck` —— 被引用于 `docs/PROGRESS_REPORT_20261016.md`, `docs/adr/0026-utf8-evidence-readback-and-authorized-proof-output.md`
* `artifacts/ui/clean-delivery-9593-20261016-d/theory.dom.txt` —— 被引用于 `docs/CLAIMS.md`
* `artifacts/ui/proof-current-2cce7055/first-long-run-results.json` —— 被引用于 `PLANS.md`
* `artifacts/ui/proof-current-ffe9bf89/theory-expanded.dom.txt` —— 被引用于 `docs/CLAIMS.md`
* `artifacts/validation/C-relocated-Lean-Lake-original-entry-native-probes-c064236d/command.json` —— 被引用于 `docs/ENVIRONMENT.md`
* `artifacts/validation/C01-twelve-fixed-baseline-family-tuning-freeze-new-paired-evaluation-5e7f94e9/command.json` —— 被引用于 `docs/BASELINE_FRONTIER.md`
* `artifacts/validation/D01-import-tests-current-b5d927f1` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `artifacts/validation/D01-public-full-import-4e991e9c` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `artifacts/validation/D01-public-full-import-v2-4648ab65` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `artifacts/validation/D01-public-row-split-guard-v2-af451f28` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `artifacts/validation/D01-public-step-import-6b4037b1` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `artifacts/validation/D01-public-step-import-v2-60541240` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `artifacts/validation/D01-public-xlsx-audit-a9390ec1` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `artifacts/validation/D02-current-serial-voltage-plus-independent-capacity-rerun-fa6fb55d/command.json` —— 被引用于 `docs/DATA_VALIDATION.md`
* `artifacts/validation/E02-current-final-real-correlated-biased-sensor-replanning-entry-e57e10fb/command.json` —— 被引用于 `docs/JOINT_GAUSSIAN_OBSERVER.md`
* `artifacts/validation/F02-all-nine-current-defining-module-builds-and-strict-axiom-audits-f6544d43/command.json` —— 被引用于 `docs/HETEROGENEOUS_COUNTEREXAMPLE.md`
* `artifacts/validation/G03-reference-recovery-418270b2` —— 被引用于 `docs/REFERENCE_ADAPTER.md`
* `artifacts/validation/G03-reference-restored-probe-5e3fbce3` —— 被引用于 `docs/CAPABILITY_AUDIT.md`
* `artifacts/validation/R00-9593-original-E2E-Edge-e7986304/command.json` —— 被引用于 `docs/CLAIMS.md`
* `artifacts/validation/R02-current-required-release-ledger-fbf5c9b0/command.json` —— 被引用于 `docs/CLAIMS.md`
* `artifacts/validation/S02-reference-cli-1519bc17` —— 被引用于 `docs/CAPABILITY_AUDIT.md`, `docs/REFERENCE_ADAPTER.md`
* `artifacts/validation/S02-reference-tests-corrected-42b1c0c4` —— 被引用于 `docs/REFERENCE_ADAPTER.md`
* `artifacts/validation/X00-current139f-original-lifecycle-failure-trace-355b9893/command.json` —— 被引用于 `docs/adr/0023-full-smoke-aggregate-and-short-windows-test-owner.md`
* `artifacts/validation/X00-lifecycle-original-short-D-owner-control-21d48f16/command.json` —— 被引用于 `docs/adr/0023-full-smoke-aggregate-and-short-windows-test-owner.md`
* `artifacts/validation/X00-original-current-smoke-8a5dc021/command.json` —— 被引用于 `docs/adr/0022-current-complete-smoke-suite-budget.md`
* `artifacts/validation/X00-original-frontier-isolated-120-second-reproduction-26d0be84/command.json` —— 被引用于 `docs/adr/0024-owned-checked-hash-import-cache.md`
* `artifacts/validation/X00-original-frontier-with-owned-checked-import-cache-355c7d93/command.json` —— 被引用于 `docs/adr/0024-owned-checked-hash-import-cache.md`
* `artifacts/verification/release-4eb2a84a4e/audit.json` —— 被引用于 `docs/adr/0023-full-smoke-aggregate-and-short-windows-test-owner.md`
* `artifacts/verification/release-9d1cbd-20261013` —— 被引用于 `PLANS.md`
* `artifacts/verification/smoke-c0aa2b9443/progress.json` —— 被引用于 `docs/adr/0026-utf8-evidence-readback-and-authorized-proof-output.md`
* `configs/discovery/proof-backend-host.json` —— 被引用于 `docs/PROOF_BACKEND.md`, `docs/adr/0027-curated-portable-publication.md`
* `data/raw/public_new` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `data/raw/public_new/zenodo17459188/RMF-VZ1_044_021_CVUT_S.txt` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `data/raw/public_new/zenodo17459188/VZ1_044_021_CVUT_D_0001_v1.xlsx` —— 被引用于 `artifacts/data/public_new/DELIVERY.md`
* `docs/adr/0025` —— 被引用于 `PLANS.md`
* `docs/adr/0026` —— 被引用于 `PLANS.md`
* `formal/release` —— 被引用于 `docs/adr/0021-complete-core-verification-wrapper.md`
* `tools/apply_a02_public_adoption_20261016.py` —— 被引用于 `PLANS.md`
* `tools/apply_final_learning_delivery_bundle_20261016.py` —— 被引用于 `PLANS.md`
* `tools/apply_reviewed_runtime_bundle_20261016.py` —— 被引用于 `PLANS.md`
* `tools/install_f03_aging_candidates.py` —— 被引用于 `PLANS.md`
* `tools/run_public_discovery_loop_20261016.py` —— 被引用于 `PLANS.md`

## 字节精确发布（冻结登记链要求）

下列 0 个文件被 `data/manifests/sources.yaml` 按 SHA256 钉住，因此**原样发布、不做路径规范化**：改写任何一个字节都会让读者无法验证冻结的数据登记链，并让数据登记测试失败。它们内部的历史绝对路径属于来源记录，不是配置项。


完整理由与逐文件清单见 `PORTABILITY_SCAN.json`。
