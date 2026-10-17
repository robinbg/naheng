# 当前主张与证据边界

本页对应源码 `95932c3d3d0ea0edec56106bf3150f39929cdc1795b824c195e8f023324c2455`。它是工程进度记录，不是完整科研验收或真实电芯认证；原提案、45 个任务和 18 项需求继续有效。

| 可核对的主张 | 当前结果 | 原始证据 |
| --- | --- | --- |
| 当前工作台能从新输入计算、保存、查看七页、导出报告和回放 | 根工作区真实界面独审 501 项通过 | `artifacts/review/ui-9593-independent-20261016-c/handoff.json` |
| 新独立安装环境能完成同一用户流程 | 626 文件交付包、51 个锁定包；真实界面独审 542 项通过；首次旧 RunID 404 及正常新建恢复保留 | `artifacts/review/r00-clean-9593-independent-20261016-d/ui-handoff.json` |
| 自动流程覆盖上传、预测取消、生命周期、四串联模组、报告与回放 | 原 4 条 Edge 端到端测试通过；缺少默认 Chromium 的首次失败仍保留 | `artifacts/validation/R00-9593-original-E2E-Edge-e7986304/command.json` |
| 真实观测进入后验和条件预测 | 合成观测下的实际计算与持久化通过；不是经过真实电芯覆盖率标定的区间 | 上述界面记录及相应 Run 的 `posterior.json`、`forecast.json` |
| 约束 BO 使用实际观测更新并执行正常采集 | 主臂完成 36 次请求，2 个有效结果、34 个 UNKNOWN，21 次正常采集；真实配对数为 1，rho 未辨识 | `artifacts/review/a03-new-9593-independent-20261016-c/main-4166aae4/handoff.json` |
| 三种查询策略已得到完整、可用于优势结论的比较 | **未通过**：随机臂 2/36 有效，不确定性臂 0/36 有效且原生命令退出 2。108 次请求不是 108 个独立科研样本 | `artifacts/review/a03-new-9593-independent-20261016-c/uncertainty-64937204/handoff.json` |
| 学习实验图表来自真实结果且保留缺失 | 三臂 SVG/JSON 已从冻结账本生成；没有插补效用或收益优势 | `artifacts/reports/learning-9593-20261016-d/generation.json` |
| 失配后自动动作不会继续静默执行 | 合成电压偏置运行实际停止，未服务能量保留；当前原学习/撤回/安全相关 94 测试通过 | `artifacts/review/p03-installed-ui-independent-20261016-c/handoff.json`；`artifacts/validation/A03-P03-R00-current-original-targeted-tests-fe8fd72b/command.json` |
| 形式证明进入实际运行的化学与速率计算 | 根工作区新 Run 的引用、源码及瞬时预算经实际界面与工件复核；模型层证明不自动给出连续闭环或真实电芯安全保证 | `artifacts/ui/proof-current-ffe9bf89/theory-expanded.dom.txt` 及相应 `chemical_binding.json`、`reduction_binding.json` |
| 独立安装包拥有完整证明发布闭包 | **尚未完成**；缺失工件在页面保持 UNKNOWN/unverified，没有继承根工作区的 checked | `artifacts/ui/clean-delivery-9593-20261016-d/theory.dom.txt` |
| 真实电芯物性映射、真实 RUL、事故概率或收益领先已获验证 | **没有此主张**；D02、独立 E-T/E-A/E-L 与真实运营样本门仍未完成，科学新增 N=0 | `TASKS.yaml`；`artifacts/validation/R02-current-required-release-ledger-fbf5c9b0/command.json` |

工程命令退出 0、证据审计通过与科研主张通过分别记录。证据审计器能确认不确定性臂的失败记录一致，但不能把原实验退出 2 改成成功。
