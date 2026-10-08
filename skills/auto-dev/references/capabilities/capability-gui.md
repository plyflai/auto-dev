# Capability: GUI

## Enable When

页面、窗口、表单、可点击流程、响应式布局或用户可见状态发生变化。

## Hard Gates

- 定义与当前改动直接对应的 GUI case，不能用无关历史 E2E 替代。
- 使用当前环境可用的真实 GUI executor；Web 优先 Playwright。
- 验证关键状态、错误反馈、布局、遮挡、裁切和响应式结果。
- 防止动态内容造成非预期、不可操作或遮挡关键控件的布局跳动；产品明确要求的自适应变化按验收执行。

## Evidence

- 保存关键页面状态、截图，以及相关 console/network 证据。
- 将面向产品的摘要写入 `auto-dev/e2e-evidence/v1` manifest，并通过当前
  `proof --evidence-file` 绑定到对应 GUI case；摘要只写用户流程、环境、
  页面表现、数据交互、系统结果、尚未验证项和产品下一步。
- 失败时采证、修复并重跑同一 case，最多 3 轮。
- GUI 不可达时给出最小手测路径、逐步预期和需要回传的证据。
- 当前 Task 的 case matrix、headed/Manual only 边界和可选 `gui` evidence
  段按 [gui-evidence-contract.md](gui-evidence-contract.md) 执行。

## Completion

- 当前改动对应的 GUI case 已通过或明确记录不可执行原因。
- 桌面和移动端适用状态均无关键重叠、裁切或不可操作元素。
