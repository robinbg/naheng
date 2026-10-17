# D02 公共入口完成校验首审

判定：**private public-entry候选完成reader存在缺口，需公共安装版本局部修复后复验；不认可39结构控制为实际CLI通过。** 不改author packet、原scanner、raw或旧电压函数。本审查只做saved-report/AST纯校准，0raw重扫、0业务worker、0Lean/GUI。

`command.json`记录实际Python校准退出1、0.70s、120s/8GiB；32个报告样本中24个应拒绝样本被接受，另一个native1投影错误。初版27样本/不完整binding正例的结果另存first-27-*，后续只补足实际worker形状并增加多协议/attempt反例，没有抹首结果。

应认可的正例和字段：`positive-full-report.json`从当前已验收scanner真八saved member形状复制，补phase/version/manifest、冻结source/role/author/rows/原raw/view refs、完整registered binding形状和scope。它是**合成完成报告校准**，不是新业务运行。`positive-multiple-report.json`展示原scanner允许的多complete protocol结果结构：逐attempt finite估计保留、complete_protocol_count=2、member scalar=null且multiple原因明确，不平均、不增科学N。本多协议正例不声称真实八raw当前存在两个完整protocol；当前真实五computed均为单协议。

必须局部核对：

1. 每个computed attempt的actual_capacity_Ah与diagnostic estimate须是finite非负int/float且非bool；protocol ID与已审固定policy一致。member complete_protocol_count与computed attempt数一致；一个完整协议时member scalar与该值一致；多个时保留合法null/per-protocol结果与明确原因。unknown仍null、有原因且不能伪造computed attempt。不得“一见member null就失败”改变原多协议范围。
2. 参与计算的单位、canonical positive-discharge和view声明的vendor sign、固定diagnostic policy、原source_protocol/nominal/source provenance必须绑定，不能将mA/degC、反向sign、.1C/.003Ah数据当成已审原协议。
3. reader独立核manifest SHA、registered binding中原raw/view/observations/split/catalog/policy/protected refs/源登记及scanner hash；unique content count由冻结成员哈希去重。现guard已有source/role/rows/rawSHA/unknown→0等检查，本轮这些负例正常拒绝；保持它们。
4. capacity native1必须公开phase exit1并execution_completed=false，原receipt保留1；现`actual_code = code if complete else 2`将1投影成2，aggregate只接收2而丢失failure分类。Popen/Job/setup异常未知2合理；无report/partial不能伪造完成；所有实际错误回执保留。

aggregate helper在本轮六种控制下没有mutate原voltage/capacity dict，深拷贝原voltage2与material_mapping UNKNOWN；显式输入phase1时结果1，预算1801/nonfinite时incomplete，0+0也保持D02 exit2。这些逻辑可保留；修runtime native1投影后，再校验聚合路径不会把native1藏成2。

本轮不增加post-stop温度或不参与边界计算字段的hard gate。报告未知仍未知；不缩放参考、不加SOH/RUL/EIS/科学N、不改变旧suite JSON、ridge/settings或旧电压函数。trusted deterministic diagnostic的Job时间/内存限值不能被称代码执行沙箱，候选已明确标false。

源码只读范围与hash在guard-results中，只绑定author候选、原已审scanner/saved member、split/views；root可合法并行改公共src，旧candidate校准不能授予新公共版本。修复后用新review目录重放这些正/坏报告和aggregate控制，再由root运行真正原CLI及独立review，保留原39和本次首fail。
