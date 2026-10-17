## C02 actual engineering acceptance 2026-10-14T00:54:31.354436+00:00

Original C02 engineering acceptance: actual eight source-C executions cover four primary fixed cases, macro projection, early retirement, external thermal electricity and heterogeneous coupled 4s module replacement. Common SOC/capacity/storage/RUL terminal rules, generation ownership, sourced disabled services, no shadow double count and finite evaluated Pareto event/alpha are implemented. 840 tests and23 subtests native0; independent1415/831 pass. Synthetic cash only; independent operatingN0, probability boundNone and unknown/censored RUL remain explicit.

23done/6in_progress/16todo. Original360s timeout2 is retained; fresh D temporary output all840 run native0 in530.44s. Current GUI new120s Run saved3 observations, report generated and replay registered; full W01/W02 not granted. Complete core/T3, public-cell model mapping and independent operating return acceptance remain unfinished.

Record: artifacts/progress/C02-engineering-accepted-51e5ed11/manifest.json

Next command: `.venv/Scripts/python.exe -m naheng.cli verify --profile release --out artifacts/release-after-C02-20261014-a.json`

# 生命周期金融实际接入

入口为 `.venv/Scripts/python.exe -m naheng.cli experiment run --suite lifecycle-finance --profile pilot --out artifacts/lifecycle_finance/新的目录`。每次创建新的输出、冻结完整源码与登记协议，先存实际生命周期结果，再采用端点、结算现金并生成 JSON、CSV 和 HTML。它使用原 S04 `run_lifecycle`、原 SiteModel 和四串 ModuleModel，原物理模型、现金账本、跳步预算和既有测试保持原字节。

当前实际包是 `artifacts/lifecycle_finance/public-current-20261014-c`，源码 `2b4b5c424375323d0b12ddcad03964c7c52d5e9defebfc98ebea0a2abf23a372`。公共 CLI 真实退出 0、32.857 秒。八个子任务逐个执行，单个 Windows Job 硬限制 120 秒和 8 GiB；所有命令、退出、日志、输入、完整源码、原始状态和相位账目均保留。完整新源码回归另行封存，单次 CLI 通过不等于完整项目验收。

## 现金与端点

`economics/lifecycle.py` 校验执行身份、SI 单位、完整时间、相位和重复义务。购售电与热管理电耗来自原积分器能量，不从目标函数、预测值或提案金额记实际收入。热费已经在能量账中，规划影子成本单列且不重复扣；维护、更换和退役信用按来源与每个资产世代记一次。没有服务规则、资格与来源时需求响应/辅助服务关闭，不能凭空增加收入。

容量与初始基准来自声明的数值 CapacityProtocol：必须有单独电压截止、匹配时间和电流积分，竞争退出、完整时域未截止或缺证据保留 UNKNOWN。储能是从当前状态出发的反事实放电探测，检查所有事件及截止时间；它不计入运行售电。期末比较统一扣除初始价值并保留存储、健康残值和未服务时间。启用非零 RUL 价值时，未知寿命导致比较值 UNKNOWN；没有把运行窗口或旧资产退役区间当成活资产的剩余寿命。

SOC 字段是所有单体站点容量加权的占位矩，属于未校准的理论代理。真实电芯 SOC、SOH、寿命或市场收入没有由此取得验证。协议容量也属于实际执行的合成数值诊断，不是物理电芯实测。

## 已执行的覆盖

| 路径 | 实际结果 | 采用范围 |
| --- | --- | --- |
| 两固定政策 × 普通/加速案例 | 四条轨迹均 12 周期、48 秒、各 24 实际相位；两个加速案例各更换一次 | 共同协议退休比 .995、同信息/事件/alpha .05、每政策完整分母 2 |
| 宏步审计 | 两次接受跳步、四条原聚合能量记录 | 单独预登记退休比 .8；全部投影现金/端点，不加入实际主前沿，不虚构逐周期能量 |
| 提前退出审计 | 不允许更换，8 周期、32 秒退休，16 秒未服务 | 实际端点保留；按合成 .001 CNY/s 记录 .016 CNY 条件惩罚 |
| 热管理审计 | .02 W 执行 48 秒，COP 1，电耗约 .96 J | 原账本热费合计 4e-8 CNY，只扣一次 |
| 四串模组审计 | 四电芯、热耦合 .04 W/K、48 秒、弱电芯更换一次 | 世代 `[1,0,0,0]`，四个活资产 RUL 都为 None；单独审计，不扩大主前沿分母 |

主政策平均条件比较值分别为 -45.041749130025366 与 -45.04174542957063 CNY。价格、残值与更换费用都是合成假设。有限登记案例的保守事件比例均为 .5；独立运营 N=0，运营概率上界为 None。不能把集合内排序称为现实收益领先、事故率保证或长期寿命结论。重跑相同普通/加速案例没有新增独立样本。

## 失败与复验

首版将跨周期聚合相位误作连续区间，真实保存的 macro 接入退出 1；修复为按原周期 metadata 派生不相交暴露区间并保持原聚合能量。第二版对未知执行模式和缺字段处理不完整，原失败保留，修订 C 明确拒绝。独立最终财务方法复核 176 项退出 0，原指定两测试文件 37 项实际退出 0。

首公开包 A 的宏步请求实际走 24 相位精细回退，不能称宏步成功。包 B/C 才执行单独预登记的宏步、提前退出和非零热审计。各包源码快照、数值和历史日志不改写。默认 pytest 临时目录首次拒读造成 25 通过、10 错误，随后使用新建且已授权的短路径输出，原 35 项断言全部通过；没有改 ACL、跳过测试或删除首次错误。

完整 C02 状态需按原 F05/F08 贡献、当前全回归及独立模组产物复核决定。D02 同电芯映射、完整核心理论/T3、科学 E-T/E-A/E-L、七页界面与报告回放、完整发布仍分别保留原门槛。
