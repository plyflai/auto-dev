# Product Review Handoff

`review_ready` 是工程结果交给产品验收的阶段，不是自动 `passed`。除工程 review 证据外，给产品同学一份短的、可行动的用户视角回执。

## Goal

让产品同学在一条回执里知道：本阶段完成了什么、为什么做、用户有什么变化，以及应该去哪里按什么步骤验证。

## Product Review Contract

在调用 `task review` 时，尽量通过 `--product-review-file` 或 `--product-review-json` 写入下面的结构。它会保存在同一个 task receipt 的 `review.product_review` 中，`status --compact` 和最终 CLI 结果都从这里读取。

```json
{
  "completed": "已完成什么结果",
  "purpose": "为什么做这件事",
  "next_step": "这如何帮助产品验收、灰度或下一阶段开发",
  "user_impact": "普通用户能感知到什么变化",
  "test": {
    "status": "ready",
    "entry": "链接、应用或明确入口",
    "role": "测试角色",
    "steps": ["操作步骤"],
    "expected": "应该看到什么",
    "prerequisites": ["账号、数据或环境前置条件"]
  }
}
```

`test.status` 有三种值：

- `ready`：有明确入口、角色、步骤和预期结果。
- `blocked`：当前不能测，必须说明阻塞原因。
- `not_applicable`：本阶段没有直接用户入口，必须说明产品可以核对的替代证据。

## Writing Rules

- 用产品结果写 `completed` 和 `user_impact`，不要把文件名、函数名或测试数量当成用户变化。
- 如果只是内部能力、稳定性或控制面优化，明确写“用户侧暂无直接变化”，不要制造用户收益。
- 只能使用任务证据中确认过的链接、应用、页面和测试条件；没有入口就写 `blocked` 或 `not_applicable`，不要猜 URL。
- `steps` 保持 1-3 步，`expected` 只写产品能观察到的结果。必要的工程命令留在原 `review` 的验证证据里。
- 不写账号密码、Token、私密路径或原始敏感数据。
- 最终向用户输出 CLI 返回的 `product_receipt` 原文。它必须以 `💡 Auto Dev 产品验收回执` 开头；不要把 `review_ready` 说成已经通过或已发布。

## Output Shape

产品回执固定为：

```text
💡 Auto Dev 产品验收回执
本阶段完成：...
目的与下一步：...；...
用户变化：...
请测试：...
步骤：...
预期：...
```

`blocked` 或 `not_applicable` 时，最后一行改为测试状态和原因。工程字段 `summary`、`changed_files`、`validation_results`、`remaining_risks` 继续保留，不塞进产品回执第一层。

如果当前 Task 有 fresh、passed 的 E2E proof，`task review` 会在同一份 `💡`
回执后追加一段 E2E 自动验证：总体结果、用户流程、测试环境、页面表现、
数据交互、系统结果、尚未验证项和产品下一步。它来自 E2E evidence manifest，
不要求产品经理阅读命令、状态码、截图路径或日志哈希；原始证据仍通过
Proof 的 source ref 回查。

如果当前 Task 有 fresh、passed 的 Release proof，同一份 `💡` 回执会追加发布
验证：最终状态、目标环境、部署版本、健康检查、关键用户流程、回退触发与目标、
尚未验证项和产品下一步。这里只消费已授权发布动作产生的 manifest，不把
`review_ready` 写成已经上线，也不授予发布权限。

## Completion

- `review.product_review` 已持久化，或明确记录摘要缺失。
- `product_receipt` 以 `💡` 开头并可直接交给产品同学。
- `review_ready` 仍等待用户审阅；相关反馈用 `task resume`，用户明确接受后才 `finish --status passed`。
