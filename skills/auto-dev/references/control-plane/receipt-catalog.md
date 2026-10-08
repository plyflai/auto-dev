# Bilingual Receipt Catalog

所有打印到对话框的 Auto Dev 节点回执都使用稳定的 `事件代码 | 中文 / English` 形式。运行时唯一标签真相源是 `scripts/receipt_catalog.py`；不要在 Skill、Hook 或 UI 中手写另一套翻译。

示例：

```text
🪝 Auto Dev Hook: intake_turn_pending | 需求澄清待分类 / Requirement intake awaiting classification | turn=...
🧾 Auto Dev: intake_confirmed | 需求基线已确认 / Requirement baseline confirmed | intake=...
```

规则：

- 事件代码保持机器可检索；中文和英文标签始终同时出现。
- 用户目标、文件名、业务规则、证据和其他自由文本不强行翻译；只翻译控制节点本身。
- Hook 回执由 dispatcher 原样生成和转发；模型不得改写、删减或另造同一节点回执。
- 非 Hook 的 Agent 回执使用同一事件代码和双语标签，再补充当前任务所需的简短业务内容。

## Git Archive Point Receipts

`auto_dev.py workspace checkpoint create` 的 JSON `receipt` 是 Git 存档点的唯一用户可见回执。每次成功创建后，Agent 必须在同一轮聊天中原样输出该 `receipt`；只把它留在工具输出或 JSON 字段里不算回传，也不得改写成 `🪝 Auto Dev Hook:`。回执包含 `commit=<8 位短 hash>`，与控制面中保存的完整 Git object 和 UI 标签来自同一存档点。

- `--kind baseline`：`💾 Auto Dev 存档点：开工保护`，对应开始改动前的可回退基线。
- `--kind milestone|archive`：`💾 Auto Dev 存档点：成果固化`，对应阶段成果或已验证 archive 的固定点。
- `workspace_checkpoint_before / workspace_checkpoint_after` 与 `archive_phase=before_change / after_change` 是稳定机器字段；完整 `object` hash、`ref`、scope、proof refs 和确认来源仍由同一 task receipt 保存。
- `workspace checkpoint protect`：`💾 Auto Dev 存档保护：存档保护已建立`，返回稳定 protection id；同一 id 关联受保护的 before/after point，并由 compact status 投影其 pending、recorded 或 invalid readback。

## Impact Receipts

`impact inspect|record` 的 JSON `receipt` 使用 `💥 Auto Dev Impact:` 前缀；Agent 原样转发，不改写成 Hook 或 Git 存档点回执。

- `impact_inspected`：只读 CodeGraph 预览完成。
- `impact_recorded`：当前 Plan node 的 impact、preservation、verification 和 uncertainty 已追加到 Task。

## Workspace Policy Receipts

`policy inspect|set|approve` 的 JSON `receipt` 使用 `🚧 Auto Dev Policy:` 前缀；Agent 原样转发，不改写成 Hook、Impact 或 Git 存档点回执。

- `policy_inspected`：只读路径分类完成。
- `policy_set`：用户确认的项目规则已按新 policy revision 固化。
- `policy_approved`：当前 Task、Plan node 与 exact paths 的一次性越线批准已记录。

## Deep Debug

Deep Debug 不新增 `🩺` 确定性回执家族。能力启用沿用 Team Capability Receipt，probe 沿用 proof/evidence，恢复沿用 status/Handoff，用户确认沿用 product review；Hook 只在既有 `🪝 Auto Dev Hook:` 回执中附加紧凑 `debug=<state>`。
