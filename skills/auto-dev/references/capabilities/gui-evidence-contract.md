# GUI Evidence Contract

进入条件：GUI capability 已启用，且本次改动触及页面、窗口、表单、交互状态、响应式布局或用户可见流程。此叶只定义当前 Task 的验收资产，不创建通用 GUI runner、Hook 或旧 `.autodev` 文件。

## Case Matrix

- 先给当前改动建立直接对应的 case；历史大回归只能作为补充。
- 至少覆盖 `happy` 与 `negative` 或 `boundary`；会话、权限或状态流转再增加 `recovery`。
- 每个 case 写明前置、操作、页面预期、适用的网络/后端副作用预期，以及失败时先看的观测面。
- 选择真实 executor：Web 默认 Playwright；桌面/移动使用当前可用 driver；没有自动化入口标记 `manual_only`。

## Visual And Retry

- Web GUI 的 `visual_mode` 默认 `required`，使用 headed 执行；不能把不可见 headless 结果说成用户可见验收。
- 每个 case 同时验证适用的页面、网络与后端副作用。只验证按钮可点不构成闭环。
- 失败先记录 `locator / timing / frontend_state / network / backend / environment / test_asset`，修复后重跑同一 case；默认最多 3 轮。
- GUI 不可执行时，记录 `unavailable` 或 `manual_only`，给出最小手测步骤、预期和所需回传证据；不得把它写成通过。

## Evidence Manifest

将当前 GUI 结果作为可选 `gui` 段写入已有的 `auto-dev/e2e-evidence/v1` manifest，再用 `proof --evidence-file` 绑定当前 Proof。非 GUI E2E 不需要这个字段。

```json
{
  "gui": {
    "executor": "playwright",
    "visual_mode": "required",
    "cases": [
      {"id": "checkout-happy", "type": "happy", "status": "passed", "scope": "checkout submit"},
      {"id": "checkout-invalid", "type": "negative", "status": "passed", "scope": "invalid payment"}
    ],
    "evidence": {
      "action_timeline": ["artifacts/gui/timeline.json"],
      "screenshots": ["artifacts/gui/checkout.png"],
      "browser_console": [],
      "network_trace": ["artifacts/gui/checkout.har"],
      "page_state": ["artifacts/gui/page-state.json"],
      "backend_trace": ["request-id=abc123"]
    }
  }
}
```

`action_timeline`、`screenshots` 和 `page_state` 必须非空；其余观测面可按适用性为空，但字段必须存在。E2E 结果为 `passed` 时，GUI 必须是 `required`、非 `manual_only` 且每个 case 已通过。不可见或手测路径必须添加 `manual_fallback`，包含原因、步骤、预期和证据请求。

## Completion

当前改动的 GUI case 已通过，或明确以 `blocked` / `manual_only` 留下可执行的手测交接与剩余风险。产品回执会投影 executor、可视化状态、case 结果和证据类别。
