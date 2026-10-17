# 本地运行与当前可用范围

工程尚未完成全部规划和发布验收。当前可运行合成双位点数值闭环、七页研究工作台、条件预测和失配撤回；核心 Lean 证明与受限候选证明已实际运行。证明范围限于声明中的模型与条件，不能当作真实电芯安全保证。九维策略优化的公开验收正在推进；真实钠电外测、三组独立实验和完整发布仍以 TASKS.yaml 与实际证据为准。

在工程根目录 PowerShell 执行：

    $env:PATH = "$PWD\.bootstrap\bin;$env:PATH"
    $env:UV_CACHE_DIR = "$PWD\.bootstrap\uv-cache"
    uv run --frozen --offline --no-sync --extra dev --extra reference naheng doctor
    uv run --frozen --offline --no-sync --extra dev --extra reference naheng demo --scenario acceptance_loop --out artifacts/demo
    npm --prefix frontend run build
    uv run --frozen --offline --no-sync --extra dev --extra reference naheng serve --host 127.0.0.1 --port 8000

打开 http://127.0.0.1:8000/ 。总览设温度、电价、初始占据和时长后创建计算；等待“已保存”再读取其他页。修改输入产生新RunID。数据来自真实数值计算，输入为合成假设。状态区间不是现实覆盖率保证；寿命未穿退役阈值会右删失；析钠/火灾保持未知。

“生成运行报告”返回当前RunID的HTML报告；仿真对照可以选择另一已完成运行、登记固定回放。回放模式与源RunID明确展示，复用结果不增加独立实验数。

默认64粒子/16预测抽样/1800秒，worker有120秒硬预算。取消在积分检查点停止，部分结果不列为完整轨迹。每次计算使用独立冻结源码；artifacts/runs/{RunID}/source_snapshot 供追溯。

验收：

    uv run --frozen --offline --no-sync --extra dev --extra reference naheng verify --profile smoke
    uv run --frozen --offline --no-sync --extra dev --extra reference naheng formal check --suite core
    uv run --frozen --offline --no-sync --extra dev --extra reference naheng verify --profile release

缺必需证明、UI或发布证据返回2。smoke/数值闭环通过不代表release。未部署公网、未启用收费模型和硬件控制。

依赖首次安装需单独执行锁定 sync，并包含 dev/reference extras。计算服务运行时不修改 .venv；每条新作业核对核心已安装版本与冻结 uv.lock，并保存 execution_environment.json。事件工件是发布成功提交前的快照，最终状态与终态事件以 SQLite/API 为准。启动时残留 queued/running 转 interrupted，不把部分结果计为完整样本。

“从检查点继续计算”校验父运行的源代码、依赖锁、输入及检查点字节，创建新 RunID，恢复模拟器与观察器各自的随机状态，继续剩余区间。继承的观测、动作和现金流保留来源与身份映射，每个已执行区间只记账一次；续算不增加独立实验样本。私有模拟状态不通过 API 提供给观察器或前端。旧运行没有受支持检查点、哈希不一致或停在不完整的模型域区间时拒绝续算，显示原因。“按原输入重新计算”是另一个从起点开始的新作业。

CLI 对应：

    uv run --frozen --offline --no-sync --extra dev --extra reference naheng recover --run-id <已取消或中断的RunID> --out artifacts/recovery


# 本地工作台与交付目录

任务完成状态以同包 `TASKS.yaml`、`docs/STATUS.md` 和实际验收工件为准。可启动工作台不等于化学、真实数据、收益或完整发布验收已经通过。

交付目录包含锁定源码、配置、模型包、实际构建的前端和逐文件 SHA256 清单。它不包含旧 Run、用户上传、密钥、Python 环境、npm 依赖或 Lean 编译对象。首次在交付目录安装：

    uv sync --frozen --extra dev --extra reference
    .venv/Scripts/python.exe tools/start_local.py --check-only
    .venv/Scripts/python.exe tools/start_local.py

Linux/macOS 将解释器替换为 `.venv/bin/python`。启动器仅接受回环地址，默认 `http://127.0.0.1:8000/`；数据写入当前交付目录下 `artifacts/`。启动前核对交付文件、Python 核心依赖及模型包身份。环境与历史数据不要从另一版本直接覆盖复制。

源码工作区首次还需运行 `npm --prefix frontend ci`。当前 Windows 构建工具会保留 120 秒/8GiB 边界和真实退出码：

    .venv/Scripts/python.exe tools/build_frontend.py --output artifacts/frontend-stage --receipt artifacts/frontend-stage.json
    .venv/Scripts/python.exe tools/build_delivery.py --destination <新的空目录> --built-frontend artifacts/frontend-stage --frontend-receipt artifacts/frontend-stage.json

已存在的目标目录会拒绝覆盖。前端必须与成功构建收据的源码和字节一致；清单内文件修改或增加未知源码后会拒绝以原交付身份启动。

七页使用同一 API 和保存工件。创建真实新运行后等待终态；报告和固定回放均引用 RunID，不把重放当新实验。CSV 导入只接受明确单位、电流方向和有序时钟；数据来源由用户声明，容量、寿命与风险缺少必要协议时保持未知。上传内容不会执行任意表达式。失败、取消、未知与证据撤回保持可见。

长任务有预算、取消和独立冻结源码。检查点恢复须通过源、依赖和状态校验；启用失配监测的恢复以当前实现能力为准，不得清空撤回历史后继续。默认未配置硬件写入或收费模型。启动器默认不转发 API 密钥、代理凭证等任意环境变量，也不向日志输出其值。

可选 Docker 配置尚需在目标机器验证：先提供经审核且包含 `@sha256:` 的 `NAHENG_PYTHON_IMAGE`（Python 3.11–3.13）和 `NAHENG_UV_IMAGE`，再在交付目录执行 `docker compose build`、`docker compose up`。宿主发布仅 `127.0.0.1:8000`，数据在 `naheng-data` 卷。不要将本地无鉴权工作台直接暴露公网；公网部署需要另行授权及鉴权、限额、上传隔离和网络控制。当前 Docker 配置不代表完成容器验收。

必需验收仍包括干净环境从锁文件安装、真实新计算到七页/报告/回放、核心证明重建、全部数据与实验门槛。缺失项不得以健康检查或前端构建替代。

## 策略训练与实验登记

在工程工作区可执行有界策略训练：

    uv run --frozen --offline --no-sync --extra dev --extra reference naheng optimize --profile pilot

默认保留 12 个初始查询和 24 个后续查询，最多 24 次高计算量查询。超时、拒绝或后验检查未通过的结果保留为未知，不产生虚构收益标签；输出是指定合成模型中的训练结果，不是现场收益或独立风险验收。

实验协议登记命令为：

    uv run --frozen --offline --no-sync --extra dev --extra reference naheng experiment preregister --config configs/experiments/pilot.yaml

登记不会执行实验。必要数据、模型族划分、独立风险队列或执行适配器未齐备时返回 2，并保存具体阻塞。每个项目的协议编号与 revision 只有一份规范登记；改变输入或源码后需新 revision，换输出目录只能导出同一登记。
