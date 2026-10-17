# 冻结证据报告工具

独立工具：`tools/evidence_report.py`。此文件与已独审 R01 D 生成器逐字相同，SHA256 为 `77b8604f7934da9b47a1129d42e41ca607965672e94941f243d679f016fcca2c`。仅使用 Python 标准库，不改 `src`、运行策略、配置或 CLI。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
& ./.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/unit/test_evidence_report.py
& ./.venv/Scripts/python.exe tools/evidence_report.py --root . --selection artifacts/handoff/r01-install-current-20261016-b/current-selection-template.json --out artifacts/reports/current-progress-review-20261016-b
```

输出目录必须不存在。生成器先验证每个显式项目工件路径、SHA256、字段位置及类型，之后一次性生成 `report.html`、`tables.json`、`claims.json`、原始 `selection.json` 与生成收据 `generation.json`。不读取外部目录、私有 evaluator 或未列入清单的资料；拒绝路径越界、重解析、重复来源、缺字段及非有限数值。不会覆盖已有报告。

命令 exit 0 不自动表示成功：生成器分别列出实际观察到的退出码、执行确认、原生退出码、清理确认和超时确认。旧收据缺确认时为 UNKNOWN，原 exit 1/2 的失败/阻塞事实保留。所有报告仍是待审草稿；不推断科研样本量、比较优势、文献新颖性或 R01/release 完成。

测试夹具 `tests/fixtures/evidence_report/legacy-command.json` 是原 A02 历史收据的逐字副本，只验证旧 exit 0 缺执行/清理确认时仍为 UNKNOWN。它不是新运行证明。

当前模板保留旧失败、UNKNOWN、未完成条件；0a2 原36确已结束但只有2 completed/34 UNKNOWN、没有正常采集分支与配对。9593 B仅纳入固定启动协议。必须等最终收据与独审后另存新清单，不得静默更新本模板或替换旧运行。D盘交付新观察、旧包样本标签错误及 proof closure 缺口分别列于 `pending-receipts.json`，这些待补项不作为通过证据。
