# Team Core

Team Core 是高治理任务的最小安全内核，不等于全套能力包。

## Core 流程

1. 校验最终需求回执、确认来源和 `remaining_pending: none`。
2. 复用 Requirement Intake 的代码导航、复现和仓库事实；存在工具或外部依赖选择时复用当前 resolution lease，只补分档后仍缺的 dependency evidence。
3. 检查分支、工作区、用户改动和局部回退能力，选择最小充分保护。
4. 读取 [capability-router.md](capability-router.md)，生成 Team Capability Receipt。
5. 设定交付单元、验证计划、预算与停止条件。
6. 只读取 enabled capability 文件，再进入 [execution-loop.md](execution-loop.md)。
7. 多 Milestone 计划由 Agent 自主决定是否插入 `verification`/`release` node，并在同一 Plan 中记录 scope、gate 和 placement reason；Progress UI、status 与 Handoff 都展示这类节点。

## Core 硬门

- 不覆盖或丢弃用户修改。
- 不在受保护分支直接写产品代码。
- 不把交付保障静默变成新产品行为。
- 不加载无证据支持的能力包。
- 不跳过已启用能力包的硬门。
- 不在预算耗尽后继续生产性假象循环。

## 最小保护

- 干净且可回退：记录 HEAD、分支、范围和验证计划即可。
- 范围内有用户改动：保存 scoped patch 与未跟踪文件。
- 不可逆或发布任务：由对应能力包提升 checkpoint 与回退强度。
- 重构、删除、重命名、公共契约或迁移风险需要跨压缩/交接保留影响判断时，读取 [impact-preservation.md](../control-plane/impact-preservation.md)，先 inspect，再把语义保留项与验证动作记录到当前 Plan node；普通 Direct 不增加这层仪式。
- 用户明确要求当前 Milestone 必须同时有写前和写后 Git 固定点时，先执行 `workspace checkpoint protect --node <current-node> --scope <product-path> --confirmation-source ...`。Hook 随即拒绝产品写入，直到用同一 `--protection-id` 显式创建 `baseline`；当前 node 的 proof 通过后，再用同一 id 创建 `archive`。`task review` 和 `finish --status passed` 会拒绝 pending、missing 或 mismatched 的两点。
- 其他跨大阶段、不可逆或发布风险需要真实 Git 固定点时，先执行 `workspace checkpoint inspect`，展示精确预演并取得 confirmation source，再显式创建 `baseline`、`milestone` 或已验证的 `archive`。`baseline` 是开工保护；后两者是成果固化。
- 创建后原样转发 CLI 的 `💾 Auto Dev 存档点` receipt；只读 `list` 必须同时检查 Git ref 与 task receipt，异常 ref 不得被聊天说明掩盖。

## 完成条件

- Capability Receipt 已生成且无未解释的能力选择。
- 保护措施与实际风险相称。
- enabled 能力、预算、验证和停止条件已进入执行计划。
