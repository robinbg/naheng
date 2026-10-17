# 数据政策与当前边界

数据状态按已读来源、已下载字节、已验收字段分别登记于 `data/manifests/sources.yaml`。本轮已读官方 Lean、PyBaMM 钠电说明和 RWTH 数据元数据；RWTH 原数据尚未下载，checksum 为空。TUM 在初次取页后再次读取返回 HTTP 429，保留受阻状态。原开工包声称已读的其他网页仅登记为包中记录，不冒充本轮核验。

公开数据下载需来源允许、许可核实、单轮总量不超过 configs/execution.yaml 的 1 GiB。下载后保存原文件及 SHA-256，校验化学体系、电芯/轨迹/批次标识、时间与电流符号、单位、协议、缺失字段。未知不可自动补成其他电芯参数。API 导入不得执行下载的数据配套脚本。

训练、验证与冻结外测按完整电芯/批次/轨迹拆分，禁止相邻时间点随机泄漏。未提供老化/事故标签不声称相应外测；gassing 压力测试不能直接当运营总体失效概率。

内部电流 I>0 为放电、时间 s、温度 K、电压 V、电流 A、库存 mol；外部单位与符号必须登记转换。理论 fixture、快模型、钠电参考、真实公共数据使用独立身份；synthetic、reference_simulation、public_measurement、replay 均不可相互冒充。

已读取的一级入口：[PyBaMM 钠电 DFN](https://docs.pybamm.org/en/v25.10.2/source/examples/notebooks/models/sodium-ion.html)、[RWTH 数据](https://publications.rwth-aachen.de/record/987579)、[TUM 待复核入口](https://mediatum.ub.tum.de/node?id=1762675)。原始数据字段与独立真实外测仍未完成。
