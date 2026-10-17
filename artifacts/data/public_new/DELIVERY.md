# D01 公开测量获取 v2 交接（冻结）

新增真实钠电原始测量 **17,143 bytes**，不是完整可拟合单芯数据。来源为作者在 Zenodo 发布的 [记录17459188](https://zenodo.org/records/17459188)，作者 Tomáš Finsterle、Jan Kasper、Šárka Paušová、Karel Bouzek；README与官方API均确认 CC BY 4.0。

## 原始文件与身份

- `data/raw/public_new/zenodo17459188/VZ1_044_021_CVUT_D_0001_v1.xlsx`：SHA256 `3e45348dc92bd1a4131e92dfdc46b96d7e062857979ecd1eb011fd1a007f283f`；官方MD5 `0d04ab461817bef013766db23b8089be`、大小均实际匹配。
- `data/raw/public_new/zenodo17459188/RMF-VZ1_044_021_CVUT_S.txt`：6045B；SHA256 `4fc6ee4edfd1a0d70319d99ed9fa10a0bcf52be44faa981144329ead19c7e3bf`。这是许可、器件、工况与文件角色依据。
- D_0001 为 Hakadi18650组成的 **4s11p包**，每芯约1.3Ah、包约14Ah，16V预充，环境设定-15°C。64行原始record，时间0–60.1s；实际CC DChg仅0.1s，原始电流-199.9752A、终端最低8.3891V。不能把计划3s脉冲描述为实测3s。
- 温度T1–T6为包内热电偶，不是44个独立单芯温度。导入明确使用T1，保留其余五路原值；未用环境设定代替测量。V1–V6近零，不解释为独立芯电压。
- D_00011（225638B、SHA256 `9f6f4d79ffab3cac7f72c78fa5ab4c0e9f45ae573fa0f82b814f25cafaf3b7b9`）被README明确识别为**铅酸对照**，排除于钠电数据。
- 5次实际HTTPS请求（两个API元数据、README、两个XLSX）重试0；Windows Schannel默认校验证书/主机名。body合计266430B（其中原始文件+README248826B），小于授权50MiB。每次curl精准argv、退出码、HTTP头、SHA及秒数在对应文件的`.command.json`/`.headers`；没有关闭TLS或执行下载代码。

## 当前有效视图与登记

两视图统一真实来源 `source_id=zenodo17459188_cvut_sib_0001`，同一保守物理包组/批次。

- 当前完整视图登记：`data/manifests/retrieval-zenodo17459188-0001-complete-v2.yaml`；spec：`artifacts/data/public_new/cvut_sodium_0001_complete.v2.spec.json`。
- 当前分步骤兼容视图登记：`data/manifests/retrieval-zenodo17459188-0001-instrument_step-v2.yaml`；spec：`artifacts/data/public_new/cvut_sodium_0001_instrument_step.v2.spec.json`。
- 两个CSV均保留64行、原始步号/行号/原时钟、V/A、六路温度。仅将hh:mm:ss.ms用Decimal精确换成s；不删行、不平移时间、不重采样、不平均温度。
- 全部原始工作簿XML记录保存在`artifacts/data/public_new/xlsx_field_audit.json`，canonical兼容结果在`artifacts/data/public_new/imported_instrument_step_v2/{manifest.json,observations.jsonl}`。
- 共时边界：30.000s工作簿行32/33，30.100s行34/35，前后电压/电流不同，均保留。分步骤视图为完整仪器步骤1/2/5，**不是三个独立实验对象，也不是完整仪器时序语义验收**。
- 初版两个view使用不同来源后缀，具有跨view物理对象泄漏风险；原spec/命令/日志与原registry精确字节快照`first_*_registry_snapshot.json`均保留。旧两个registry已标`superseded_view_identity`且不再准入，当前仅合并v2登记。不要重新执行`prepare_import.py`或`prepare_shared_source.py`覆盖历史证据。

## 真实验收与首次失败

| 检查 | 实际结果 | 命令/日志目录 |
|---|---|---|
| 原始XLSX大小/官方MD5/字段只读审查 | exit0 | `artifacts/validation/D01-public-xlsx-audit-a9390ec1` |
| 首次完整文件导入 | exit1，CSV33共时记录 | `artifacts/validation/D01-public-full-import-4e991e9c` |
| 首次步骤兼容导入 | exit0，64行 | `artifacts/validation/D01-public-step-import-6b4037b1` |
| 当前v2完整文件导入 | exit1，CSV33共时记录 | `artifacts/validation/D01-public-full-import-v2-4648ab65` |
| 当前v2步骤兼容导入 | exit0，64行 | `artifacts/validation/D01-public-step-import-v2-60541240` |
| 当前v2逐值/逐行/共时边界/同包跨步骤与跨view防泄漏/旧spec拒绝 | exit0 | `artifacts/validation/D01-public-row-split-guard-v2-af451f28` |
| D01指定导入与split测试 | 25 passed，exit0，4.53s | `artifacts/validation/D01-import-tests-current-b5d927f1` |

每个目录含`command.json`、stdout与stderr。实际逐值/单位/符号及防泄漏结论见`artifacts/data/public_new/import_and_split_audit_v2.json`。唯一物理group的64行全部冻结为holdout：`holdout_only_snapshot_v2.json`；train/validation均0，不能声称三类独立划分或外测完成。

## 仍未完成与来源可行支路

D01/D02保持未完成：完整文件共时步骤边界尚不被当前严格递增CSV importer接受；这里只有一个保守物理pack group，个别电芯身份、电极体系未提供；没有单芯拟合、概率校准、寿命/事故人口外测或真实经济收益结果。

只读复核官方README的10个钠包文件：仅按16.0/14.4V预充与五种温度列出，设备描述为4s11p钠包；未列独立pack序列号、重复样本号或足以确认≥3独立物理对象的说明。因此不再启动下载，不把工况文件或view作为独立group。铅酸文件亦不能补钠电样本数。

另一个作者来源 [Wang等2024，Zenodo13836819](https://zenodo.org/records/13836819) 的官方API元数据已取得并确认CC BY4.0；它描述3.2Ah Transimage与10Ah HiNa单芯。两ZIP为129024711B/126629603B，超过本支路50MiB，未下载整包、未尝试范围提取，不能声称有其测量字节。元数据在`artifacts/data/public_new/zenodo-13836819.metadata.json`。TUM1837893仅官方网页读取，未新增测量字节。

## 冻结写集与下一命令

本分支仅写`data/raw/public_new/`、本分支`data/manifests/retrieval-*.yaml`、`artifacts/data/public_new/`及对应`artifacts/validation/D01-*`证据。不改仿真/PF/契约、依赖、中央sources.yaml、TASKS/PLANS/STATUS或数据库。独立源审查为`artifacts/data/public_new/independent_source_review.json/.log`（审查者单独交付）。

只读复验当前登记与全部真实记录、防泄漏：

```powershell
.venv/Scripts/python.exe tools/run_evidence.py --label D01-public-v2-recheck --timeout 60 -- .venv/Scripts/python.exe artifacts/data/public_new/check_import_and_split_v2.py
```

源码路径哈希在当前audit中；重跑可读取既有一致holdout快照，不覆盖原始测量。整组数据三角色覆盖和完整仪器时序仍需要后续实现与独立来源，不能用本复验exit0免除。
