# 当前真实钠电完整成员接入与冻结（2026-10-14）

Zenodo13836819 的八个许可完整 CSV 成员已由真实公开入口导入单位视图，共1240278原始行；全部异常、原时间、作者编号和来源字符串保留。最终冻结 C 位于 `data/splits/zenodo13836819-eight-provenance-20261013-c.json`，SHA `c86f34c674f77fe7972f614ad1b88d0cf37531dc51d457479b17b4f837a4b539`。真实 fullfreeze 0/44.401s、恢复磁盘空间后的全行 verify 0/67.234s 见42256f2c及851d2015命令收据；缺收据的旧550ee结果仍不提升。

完整作者组、相同完整 raw SHA 和已有组件关系取传递闭包。C34 的六个10Ah Pulse成员为train776011行，C5的3.2Ah Driving成员为validation332603行，C1的3.2Ah Pulse成员为test131664行；每个member/context/完整[1,n]只属于一个角色。相同 raw 的两条来源路径保留并同组，不把重复行数视作独立样本。首冻 catalog974c及policyde3跨新文件路径锁定，不能另存新角色将旧测试集转训练。CVUT原64行两个持出版本、b41七成员层和补充904/pending152原字节不变。

这是预先声明的跨容量/协议迁移工程划分。作者编号不是确认物理序列号，生产批次、物理独立性、IID和整ZIP官方MD5仍UNKNOWN；相同Pulse协议和25℃在train/test共有，不声称严格协议或温度持出，不混拟合为已知同材料参数。D02校准、RUL/事故标签及收益验收尚未完成。当前许可、来源、实际命令、冻结及已验视图指针见 `data/manifests/public_sodium.yaml` 的 `current_cohort`；旧RWTH顶层字段保留其原历史范围。

68项原及新增对应测试0。非作者88项独立检查覆盖小型好坏方法样例和真实元数据，独立真实数值行读取0且payload SHA显式stub；不能把它说成独立124万行数值复验。完整单位数值重开及原raw/sign/异常/gzip、231及90数值样本的独立范围在此前七成员与补充成员入口链分别记录。

旧Decimal精度28窗口方法有超长数值假匹配反例，首次失败及精度扫描超时保留。修正后用精确整数系数/指数差，61项非作者方法及4项好坏对照0；完整真实8行窗口审计0/62.908s，在选定八个原信号字符串和14个精确时间/序号差的规则下匹配0。它不证明其他窗口、数值等价格式、孤立行或物理/统计独立。首次工具中断UNKNOWN及旧方法报告保留。

以下原文为2026-10-10的RWTH尝试及严格ImportSpec入口历史记录，原失败和未取得该来源字节的结论保留。它不描述当前Zenodo完整成员是否已取得。

---

# 公共钠电数据接入：已实现与受阻证据

D01 的 CSV 导入与防泄漏实现已经运行验收；真实公共数据仍受阻，不能记为 D01 完成，也没有开展 D02 外测。当前登记见 [public_sodium.yaml](../data/manifests/public_sodium.yaml)。

当前读到的一手入口为 [RWTH 记录 987579](https://publications.rwth-aachen.de/record/987579)、[文件列表](https://publications.rwth-aachen.de/record/987579/files/)及 [ReadMe](https://publications.rwth-aachen.de/record/987579/files/ReadMe.pdf)。机构页面标示 CC BY 4.0，许可条款入口为 [Creative Commons](https://creativecommons.org/licenses/by/4.0/)。ReadMe 描述的是商业 1.2 Ah、18650 钠离子电芯资料；未据此补猜厂商、电极材料、供应商电流符号或测量列。该研究包含严重产气的压力条件，不是运营事故概率样本。

文件列表报告 ZIP 为 3.44 GB，超出本轮 100 MiB 上限。实现提供 HTTP Range 读取 ZIP 中央目录和一个完整小成员：只接受 206，逐项验证 Content-Range、字节数、成员 CRC 与 SHA-256；200 整包响应在读取 body 前拒绝。原始整包未下载，整包及测量文件 checksum 均为空。配套 Python 文件只作为文本阅读对象，禁止执行。

本轮实际网络结果已保留：

- 第一次命令退出 2：Python TLS 无法确认 issuer，收到 0 字节；没有关闭证书校验。
- 第二次命令退出 2：使用 Windows 既有证书与主机名校验，四个地址均收到 HTTP 200，但 body 都是同一个 248 字节的 JavaScript challenge HTML，共 992 字节。包括命名为 PDF/XML 的响应，它们都不是相应来源内容。未执行挑战脚本，未请求 ZIP 数据。
- 原始日志、HTTP 头与错误分别保存在 artifacts/data/rwth_download_attempt1*、rwth_download_attempt2* 和对应 attempt 目录。后续下载器已增加 challenge/PDF 类型拒绝，不会把响应扩展名当作已下载数据的证据。本轮不继续网络重试。

## 可用代码接口

    ImportSpec(...).validate()
    import_csv(path: Path, spec: ImportSpec,
               maximum_bytes=50*1024*1024, maximum_rows=1_000_000) -> ImportedDataset
    ImportedDataset.manifest() -> dict
    ImportedDataset.write(out: Path) -> dict
    freeze_split(datasets: list[ImportedDataset], out: Path,
                 seed=20261010, fractions=(0.6,0.2,0.2),
                 group_by="cell_id", holdout_only=False) -> dict
    check_no_leakage(assignments: list[dict]) -> bool

ImportSpec 必须显式提供 source_id、credential-free HTTPS source_url、dataset chemistry_id、current_sign、units、columns、license_id、raw_sha256、身份与电流符号依据；不猜列名和符号。公共测量还必须绑定 data/manifests 内已登记的 source_bytes_verified 清单、清单 SHA-256、许可工件 SHA-256，并核对来源、化学身份、原始文件哈希及符号。客户端仅自行声称 public_measurement 不足以获得该标签。

电流输入 positive_charge 转为内核负充电，positive_discharge 保持放电正号。时间、mA/mV、摄氏度按显式单位转换，原始电流、符号、行号和文件哈希保留。缺测温度保存为 null 和质量标记，不能填入 298.15 K，也不能直接构造要求温度齐全的 Observation。重复/逆序时间、非有限数、未知单位、原文件哈希变化、缺身份等均拒绝，不排序或插值修复。

split 按完整电芯或批次；批次模式将共享电芯与批次的关联组绑定为一个角色。所有相邻时间点和同电芯的其他轨迹都不能跨角色。冻结结果有内容哈希，已有清单不能改写；只有一个可用独立组时可整体 holdout，不能生成虚假训练/验证样本。

## 已运行验收

    .bootstrap/bin/uv.exe run --frozen --offline --extra dev pytest tests/unit/test_data_import.py tests/integration/test_split_leakage.py -q

23 项通过，退出码 0。命令与日志为 artifacts/data/D01_import_split_bound_command.json、D01_import_split_bound.log。测试中的 CSV 均明确标 synthetic 单元测试夹具，不写入公共数据目录或外测清单。

获得真实字节及字段/符号/身份依据后，可使用：

    uv run python -m naheng.data.importers --csv <真实完整成员> --spec <已登记来源配置.json> --out artifacts/data/<导入版本>

CLI 成功返回 0，字段错误返回 1，来源字节证据尚未登记或受阻返回 2。当前不具备这条实际导入命令的必要输入，data/splits 中没有伪造的公共样本划分。
