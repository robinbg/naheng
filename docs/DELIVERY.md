# 9593 本地源码交付候选

当前包位于 `<HOST_DELIVERY_ROOT>/naheng-9593-source.zip`，SHA256：`3c90b91e878731e443b84e915ee761ccfa47c7e2962adf0b7936a3ec9c77485b`。源码与实际构建的前端共 626 个清单文件，压缩前后逐个哈希一致。

实际解包内容目录为 `<HOST_DELIVERY_ROOT>/app`，本次独立环境使用该目录下新建的 `.venv`，Python 3.13.5，锁定依赖与项目合计 51 包。交付 ZIP 不包含虚拟环境、既有运行数据或用户凭据。包的清单及源码版本保持冻结；本页是之后产生的外部验收说明。

在本次已安装的环境中执行：

```powershell
& '<HOST_DELIVERY_ROOT>/app/.venv/Scripts/python.exe' `
  '<HOST_DELIVERY_ROOT>/app/tools/start_local.py' `
  --project-root '<HOST_DELIVERY_ROOT>/app' --check-only
```

启动时把 `--check-only` 改为 `--host 127.0.0.1 --port 8002`，打开 `http://127.0.0.1:8002`。验收用临时服务已经由自有进程管理器停止；不会常驻或开放公网。默认不向硬件写入，也不转发外部模型凭据。换机器需先按 `uv.lock` 安装依赖，不能将本机验证推断为跨平台二进制可复现。

实际干净安装复验覆盖两组新输入、七页、结果重开、报告下载与打开、回放以及非回放标签。首次浏览器旧 RunID 返回 404，正常创建新运行后恢复；两次结果与新报告没有复用旧数据。对应独审为 `artifacts/review/r00-clean-9593-independent-20261016-d/ui-handoff.json`。

这仍不是完整发布：A03 不确定性比较退出 2，P03/R00 的原任务依赖尚未全部满足；真实数据映射、三组独立科研实验及证明发布闭包继续保持未完成。安装包缺少的证明工件显示 UNKNOWN，不能以模型层证明、合成曲线或功能测试声称真实电芯安全、寿命或收益保证。详见 `docs/CLAIMS.md` 与 `TASKS.yaml`。
