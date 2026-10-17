# 联合状态参数校准

`naheng calibrate --input 请求.json --out artifacts/calibration/新目录` 对显式训练观测生成独立候选快照。已有 Run、滤波器、注册表和冻结持出集保持不变；候选的使用需要明确选择。

当前计算入口支持 `synthetic_two_site` 的内置模型。请求保存原后验、传感器来源文件及 SHA、原始注册描述、实际执行历史、逐粒子预测、噪声假设和传播证据。入口重算时间零传感器更新、每个父粒子的动力学与观测、末状态及同粒子 SOC，核对状态名称、单位、参数与源码绑定；只有来源、时间前缀和实际计算一致时才允许更新联合权重。参数样本不凭空收窄；状态样本由实际传播更新，均值、分位数与 ESS 均重新计算。

电压和温度的联合高斯似然须显式声明偏置、正定协方差、单位和时间独立性。合成参考具有模型差异，因此残差散布不能冒充纯测量噪声。失配记录包含边缘标准化残差、白化残差、滑动偏置与联合 Mahalanobis 指标；阈值是声明的经验政策，不是事故概率或覆盖率证明。

每次运行使用最多 120 秒的自有子进程，实际传播另有 100 秒软预算。新输出目录保存原请求、结果、真实子进程命令与退出码、日志、源码和输入哈希。FAIL=1、UNKNOWN=2，均不发布可采用的候选。目录已经存在时拒绝覆盖。训练输入不接受参考真值或 Python 代码，拒绝持出角色、前缀重叠、来源越界、失效哈希及 evaluator 文件路径。

已保存的实际合成样例包含 8 个父粒子、4 条后续观测。正常路径实际计算后将同一份新快照用于规则、经验动作准入、条件预测与真实积分的能量账本。预测的 RUL、火灾、析钠在未满足条件时保持 UNKNOWN；账本仅属于所执行的合成仿真，没有真实盈利或相对收益领先结论。

原注册描述省略的默认字段必须保留省略状态。添加 `schema_version` 后得到的描述与原 package hash 不再一致，应拒绝。首次该错误、错误单位被接受的独立反例和之后的局部修复均另存证据，没有覆盖首次结果。

复验命令：`.venv/Scripts/python.exe -m pytest tests/integration/test_calibration_runtime.py tests/integration/test_shared_posterior.py -q --basetemp <HOST_HOME>/Documents/Codex/.nh-cal-review-新标识`。

当前已实现两个显式本地采用入口：`consume-calibration` 从成功候选运行规则、准入、条件预测和真实积分账本；`scenario-calibration` 从同一候选新建观察器，实际执行首动作、读取带声明噪声的合成 V/I/T/time、更新 PF 后用新快照再规划。后者固定为两轮 5 秒的有界研究切片，未来计划不记为执行，传感器更新失败时已执行的账本仍保存。

原 builtin 观察器采用记录保存源/新快照内容与 RNG 哈希，明确时间零 PF 与之后的批量校准，并不冒充训练各时间点的逐次 PF 更新。该原入口继续只接受原来的对角、零偏置似然。新增显式 `joint-scenario-calibration` 使用完整协方差与偏置的有限支持观察器；两种观察器的采用语义分别记录，不静默转换。新对象不修改旧 PF 或 Run。

示例：`.venv/Scripts/python.exe -m naheng.cli scenario-calibration --calibration-dir artifacts/calibration/builtin-calibration-current-20261014-f --out artifacts/scenario_calibration/新目录`。候选必须与当前源码一致；修改实现后需要重新运行校准，不迁移旧 receipt。

当前 Web、真实电芯校准、外测、长期预测和最终 E-T/E-A/E-L 验收仍须分别完成；上述合成计算和工程测试不替代它们。原 C01 的滚动控制和共同约束固定基线工程验收已完成，当前 08705aadc91c 完整回归为 736 项、23 子测试，退出 0；长期终端与生命周期结算继续按原 C02 执行。

联合观察器的当前真实公共入口产物为 `artifacts/joint_scenario_calibration/public-current-20261014-a`。两轮实际首动作积分后，分别在45/50秒读取按声明完整协方差及偏置生成的合成V/T，用同一联合状态参数样本更新，再以新快照规划。公共CLI实际退出0、6.634秒；84项观察器/入口/原共享后验验收及2项实际注册描述绑定回归实际通过。旧参数哈希格式接入错误造成首轮83通过/1失败，原退出和日志保留，未改原断言或重新绑定旧包。完整当前版本回归另行记录，详见 `docs/JOINT_GAUSSIAN_OBSERVER.md`。
