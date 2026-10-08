# Direct Execution

Direct 是单人高级工程师执行终点，不是进入 Team 前的准备阶段。

一次性低风险 patch 优先走 Quick Write；Direct 仍表示需要任务范围、验证和可恢复记录的受治理单人交付。

## 流程

1. 消费最终需求回执和现有调查，不重复访谈。
2. 使用代码导航与仓库模式收紧目标调用链、候选路径和验证入口；任务首次需要工具或外部依赖时，按 [project-memory.md](../control-plane/project-memory.md) resolve 一次并复用 resolution lease；最终需求回执的运行诊断不是 `not_applicable` 时，读取 [runtime-diagnostics.md](../control-plane/runtime-diagnostics.md)。
3. 在第一行产品代码前做一次静默结构判断：确认当前行为的职责归属、可复用模块、依赖方向和稳定验证边界。目标文件已经很大但改动仍属同一职责时，不因体量单独扩张流程；若当前实现会新增独立职责、复制已有能力、形成反向或循环依赖、混合业务逻辑与外部副作用，或现有结构已经阻碍验证，则在当前范围内提取清晰边界；需要新模块边界、共享抽象、多个调用方迁移或广泛重构时升级 Team Core。该判断不创建额外回执或等待。
4. 需要本地记录时用 `auto_dev.py start --tier direct` 建立轻量 receipt，并声明 run-level Outcome Contract；一次性任务也必须先通过 `auto_dev.py proof`，再用 `task review` 进入 `review_ready`。
5. 直接实现最小改动，不创建 Team flow、能力回执、里程碑、全量 Blast Radius 或 Subagent。若任务启用了连续性记录，则为节点声明 Outcome Contract；一次性 Direct 也必须在完成回执中区分主结果和 supporting evidence。验证前只回看本次改动及其直接边界，修正本轮新增的职责混杂、重复实现或错误依赖，不借机治理无关旧债。
6. 按 [verification.md](../verification/verification.md) 运行与改动直接对应的验证；运行诊断适用时，验证成功与相关失败路径的记录，并更新 `.auto-dev/runtime-diagnostics.json`。
7. 进入 `review_ready` 前读取 [product-review.md](../verification/product-review.md)，通过 `task review` 记录产品验收摘要，并原样转发 CLI 返回的 `product_receipt`。同时交付工程结果、改动、验证和剩余风险并等待用户反馈。相关反馈用 `task resume --state-revision ... --reason ... --confirmation-source ...` 继续；用户明确接受后，才用 `finish --status passed --confirmation-source ...` 归档。

## 约束

- 保留用户已有改动，只触碰确认范围。
- 调试先复现，再改动最有证据的根因。
- 已验证 dependency recipe 正常成功时直接复用；失败、环境变化或 candidate 才读取相关 attempt 和 fallback，不能为每个动作重复解析。
- 不以最佳实践完整性为理由增加无关抽象、依赖或测试。
- 新业务决定或产品行为变化回 Requirement Intake。
- 连续两轮未恢复目标验证时升级 Team Core。
- 证据表明当前无法实现或验证时停止生产性动作，说明阻塞、已尝试内容和解除条件；不为维持“正在交付”的外观制造代码或报告。

## 完成回执

```text
🧾 Direct 完成
- 结果: [用户现在能做什么]
- 改动: [最小工程范围]
- 验证: [命令 / GUI / 运行证据]
```

## 完成条件

- 单一用户结果已实现。
- 改动仍在 Direct 边界，或已明确升级。
- 目标验证通过，未验证项与剩余风险如实披露。
