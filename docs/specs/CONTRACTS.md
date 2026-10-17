# 数据、模型包、运行服务与 API 契约

这是新增实现规格，不是已存在 API。Codex 在 G02 固定类型并生成 OpenAPI/前端类型。工程可调整字段命名，但语义、必要血缘和验收不能消失。

## 1. 对象与身份

- `ChemistryIdentity`：体系/材料标识、model_kind、参数出处、支持温区/电压/倍率、版本和 source_id。unknown 成分不得用最像的电芯补齐。
- `Observation`：run_id、cell_id、timestamp_s、current_A、voltage_V、temperature_K、可选诊断特征及质量掩码。没有隐藏真值字段。
- `PosteriorSnapshot`：snapshot_id、run_id、model_package_id、parameter_revision、obs_until_s、状态定义与单位、samples_uri/权重或显式分布、均值/分位数、有效样本量、可识别性标记。缓存键含快照与模型哈希。
- `Action`：action_id、snapshot_id、start_s、duration_s、cell/module 目标、电流或功率命令、充放电配置、热管理命令与限制。不能同时给矛盾的电流/功率命令；转换器需解可行性。
- `ForecastQuery`：snapshot_id、future_policy_id、environment_id、horizon、endpoint_protocol、event_definitions、sample_budget。寿命/风险/收益都从该对象衍生。
- `ForecastResult`：观测预测、RUL分布/删失、事件级概率估计、事件定义、条件、cost/energy ledger 与 provenance。不得在没有样本/证据时返回任意区间。
- `ReferenceTrace`：真实内部状态、参考参数、无噪声输出与约束事件，只在评估存储中，不传控制服务。

`schema_version` 与业务模型标识不同。读取旧 schema 必须显式迁移，不能静默猜字段。模型转换前校验化学体系、单位、位点语义和驱动方式。

## 2. ModelPackage

模型包包含：`package_id`、`chemistry_id`、`parameter_revision`、`state_definition`、`dynamics_ast`、`readout_ast`、`reduction_map`、`lifting_map`、`domain`、`error_contracts`、`evidence_refs`、`validity_monitor`、`fallback_refs`、`artifact_hashes`。

表达式采用白名单 AST，不执行任意 Python 或 eval。初版支持有限代数、指定初等函数与注册求解器；不支持的表达式返回错误。物理常数与参数都绑定来源/单位。理论与 Python 从相同 AST 产生或进行一致性验证；未经验证的转换不能升级为形式保证。

`domain` 是可执行条件和说明的组合，覆盖参数、状态/可信集合、温度、驱动、电位参考、时间范围和初始映射。每条检查输出 PASS/FAIL/UNKNOWN + reason + evidence_ref。针对状态集合的要求不能只检查后验均值；粒子样本只覆盖其统计表示，不自动代表全域。

`error_contract` 必须包含 target、bound_expression、comparison_reference、horizon、same_input_or_closed_loop_conditions、domain、numerical_error、probabilistic_assumptions。某项缺失时仅能声明局部/统计/经验覆盖，不得用 null 代表0误差。

## 3. 证据至少三个独立维度

### 生成/核验状态

`proposed`、`checking`、`checked`、`counterexample_found`、`timeout_unknown`、`blocked`、`invalid`。只有 verifier 写入 checked，LLM 不能自报。

### 证据类别

`formal_kernel`、`formal_extended_trust`、`validated_numerics`、`statistical`、`empirical`、`none`。一个结论可以关联多个证据；不能把它们排成“万能最高分”。

### 当前适用性

`applicable`、`inapplicable`、`unknown`、`stale`。证明仍然成立但包参数改变，可以是核验 checked、适用性 stale。旧证据不删除，新的策略不能继续借用旧适用性。

证据字段：statement_text/statement_hash、formal_target、assumptions、scope、checker_version、build_log_uri、dependency_manifest、artifact_sha256、created_at、runtime_contract_refs、uncovered_errors。占位证据记录必须 proposed；不能填一个虚构哈希和 proof passed。

`EligibilityDecision` 返回 `accept`、`reject`、`unknown` 及逐项原因。strict 模式只接收证据充分、条件适用且收紧约束满足的动作；empirical 模式另标，不冒充 strict。最终产品必须有有用的可行运行，不接受“永远拒绝”作为完整优化成功。

## 4. Python 接口（实现目标）

    class ObservationSource:
        def next(self) -> Observation: ...

    class CellModel:
        def rhs(self, t_s, state, drive, params): ...
        def observe(self, state, drive, params): ...
        def protocol_capacity(self, initial, protocol): ...

    class Estimator:
        def update(self, observation, action_history) -> PosteriorSnapshot: ...

    class ModelRegistry:
        def validate(self, package) -> ValidationReport: ...
        def applicable(self, package_id, snapshot, query) -> DomainResult: ...
        def transition(self, src, dst, snapshot) -> PosteriorSnapshot: ...

    class Forecaster:
        def predict(self, query: ForecastQuery) -> ForecastResult: ...

    class Controller:
        def propose(self, snapshot, forecast, constraints, economics) -> Action: ...

    class AdmissionChecker:
        def check(self, snapshot, action, model_package) -> EligibilityDecision: ...

    class ExperimentRunner:
        def run(self, frozen_spec, budget) -> RunManifest: ...

`...` 表示本规格声明，不是允许最终函数返回空值。应用与评估必须用相同接口运行不同算法，不能给主方法额外内部信息。观测快照不可就地修改；变更产生新 revision。

## 5. API 目标

| 路径 | 含义与验收 |
|---|---|
| `GET /api/health` | 存活、版本，不表示科学能力全部可用 |
| `GET /api/capabilities` | 已实现/受阻模型、正式证明可用性、数据与运行模式 |
| `GET /api/scenarios` | 场景列表与 source/chemistry/synthetic 标记 |
| `POST /api/runs` | 输入场景、策略、模式、预算，返回202和唯一 RunID |
| `GET /api/runs/{id}` | 状态、进度、时间、错误、取消信息 |
| `GET /api/runs/{id}/events` | SSE/等价增量事件；断线可从事件序号续读 |
| `POST /api/runs/{id}/cancel` | 安全取消，部分轨迹不可冒充完整验收样本 |
| `GET /api/runs/{id}/snapshots` | 可见状态结果，不返回评估真值 |
| `POST /api/forecasts` | 同快照查询寿命/风险，长任务返回 job_id |
| `POST /api/optimizations` | 受预算约束的策略搜索，不后台无限运行 |
| `GET /api/runs/{id}/decisions` | 候选动作、准入、备用及证据卡 |
| `GET /api/runs/{id}/economics` | 现金流、能量明细、残值和不确定性 |
| `GET /api/model-packages/{id}` | 模型定义、适用域、证据和未覆盖部分 |
| `GET /api/evidence/{id}` | 证明/证书元数据与受控工件查看 |
| `POST /api/discovery-jobs` | 受限语法和预算的离线搜索，不执行任意上传代码 |
| `POST /api/datasets/import` | CSV等受限格式，验证单位/时间/来源/体积 |
| `POST /api/replays` | 从已完成 RunID 回放，明确 mode=replay |
| `POST /api/reports` | 以 RunID/experiment_id 生成 HTML/CSV/JSON报告 |

配置/数据错误422，资源不存在404，无效模型切换或证据冲突409；权限错误401/403；科学证据未知是结构化状态，不伪装成500。文件工件由白名单 ID 取回，禁止客户端传服务器任意路径。

## 6. 长作业与血缘

作业状态 created→queued→running→succeeded/failed/cancelled/interrupted。原子 checkpoint，心跳与资源使用，幂等键只复用相同冻结输入；若缓存复用，明确 reused_from，不增加独立样本数。执行与评估有独立随机源，seed 分为场景、观测、滤波、优化、采样五类。

`RunManifest` 至少记录 run_id、experiment_id、role(train/validation/test/stress)、observation_policy、model/parameter/policy/data/code/hash、dependency_lock_hash、seed_bundle、walltime、hardware、mode、provenance_type、failure_reason、artifact_index。哈希记录 dirty diff；无 git 时对源码快照内容计算哈希，不伪造 commit。

核心工件：sensor_trace.parquet、posterior.parquet、actions.parquet、events.jsonl、cashflows.parquet、forecast.json、manifest.json。参考真值位于 evaluator 专用目录并不经过用户观测 API。所有图表由这些数据生成，不在绘图脚本中补赢家数值。

## 7. 安全与公开部署

默认本地绑定127.0.0.1；无物理设备写接口。公开部署需显式授权，有认证、队列配额、上传限制和请求预算。候选证明/代码搜索按不可置信输入处理，子进程禁止访问秘密并限制 CPU/内存/时间。证明字符串不等于 shell 命令。

所有 secrets 在服务器环境，日志脱敏，前端bundle与报告不包含密钥。数据下载器仅获取显式批准的来源，校验压缩包路径与大小，避免目录穿越和解压炸弹。报告中的外部文本转义。公共仓库前执行许可、隐私和凭据审计。
