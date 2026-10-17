# 钠衡化学形式基础

工具链锁为 Lean 4.19.0 / mathlib v4.19.0。当前源码不是已检查证明；只有 `artifacts/formal/*/manifest.json` 的实际 build、所有目标 `#print axioms` 审计与源码哈希同时通过，才获得 `checked`。

`Species` 对应合成 DSL 的 sodium-ion、electron、vacant-site、occupied-site、trapped-product。库存单位 mol；计量是每 mol 反应的物种变化，通量 mol/s，电荷数按每粒子的元电荷单位。有效 trapped-product 保存 Na、为中性类别；未声称它是真实 SEI 成分。电流控制根求解与法拉第换算在 Python 模型执行，形式基础暂未证明其闭环适用性。

目前导出：明确反应计量的元素/电荷收支、开放端口的瞬时库存导数收支、位点两端导数方向、明确常速率指数曲线的域保持。一般时变速率 ODE 轨迹存在性与域不变性尚未证明，边界引理不替代该结论。T1/T2/T3 与热力学仍未完成，`core` 必须退出 2。

执行：`python tools/audit_formal.py --suite foundation --out artifacts/formal/foundation`。本地 Lake 可通过 `NAHENG_LAKE` 指定，或放置于 `.tools/lean/bin/lake.exe`；不使用任意其他版本替代锁定版本。
