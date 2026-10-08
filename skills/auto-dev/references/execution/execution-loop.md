# Team Execution Loop

按交付单元连续执行，默认不在每个机械步骤后等待用户确认。

## 每个交付单元

1. 写明用户结果、工程范围、enabled capabilities，并按 [outcome-contract.md](../intake/outcome-contract.md) 声明主结果和最小 proof。
2. 在第一行产品代码前完成 Team Core 与能力包要求的保护。
3. 实现最小完整结果，及时运行能证伪当前方向的验证；有效 dependency lease 内直接复用配方，工具链失败时才进入 dependency failure 分类和 fallback。
4. 用 `auto_dev.py proof` 执行并记录与主结果绑定的验证。报告、计划、清单和旧证据重跑只作 supporting evidence，不能单独让单元 Green。candidate、新版本、失败或显式复验时才记录 dependency attempt，已验证配方的普通成功不写完整历史。运行诊断适用时，按 [runtime-diagnostics.md](../control-plane/runtime-diagnostics.md) 更新 `.auto-dev/runtime-diagnostics.json`。`debug-observability profile=deep` 时，按其 reference 在同一 Task 中完成 case search、reproduction、hypothesis/observation、resolution 与 recovery；proof 仍是执行证据真相源。
   `measured_improvement` Outcome 按 [performance-verification.md](../verification/performance-verification.md)
   先记录 baseline attempt，再在同一 Proof 中绑定 comparison；baseline 不提前完成节点。
5. 当前单元 Green 后继续下一个单元。

验证 Milestone 不是隐藏的收尾动作：当多个 delivery node 首次形成完整用户切片，或跨节点回归能显著降低后续定位成本时，Agent 在同一 Plan 中插入可见 `verification` node；最终发布边界可再插入 `verification`/`release` node。每个 delivery node 仍需自己的最小 proof，不能把所有验证推迟到最后一个 Milestone。

## 必须停止的条件

- 新业务决定或产品行为变化。
- 不可逆、外部写入或权限扩大尚未获授权。
- 连续两轮实现未恢复目标验证。
- 同类缺陷重复两次，需要系统性重规划。
- Capability Receipt 的时间、审查或重试预算耗尽。
- 计划边界错误，继续会扩大范围或破坏回退能力。
- 主结果受物理依赖、权限、串行条件或不可获得证据阻塞。

停止时区分：Requirement Diff、Capability Re-route、Blocked、Budget Exhausted。Blocked 记录已尝试证据、责任方和解除条件；不要为满足完成压力制造代码，也不要用含糊进度总结代替明确问题。

## Review

- 默认一次风险边界审查和一次最终综合审查。
- 安全、数据迁移或发布可要求独立审查。
- 已验证的机械模式重复应用时，合并为批次并在批次边界审查。
- Reviewer 只报告有证据的正确性、兼容性、安全或可维护性问题。
- Reviewer 只针对当前改动和直接受影响边界检查新增的职责混杂、重复实现、反向或循环依赖、混合副作用、过宽接口和无所有权碎片模块；能在当前范围内保持行为等价地修正就修正，否则记录为有证据的剩余风险，不扩大为全仓清理。
- 所有节点与 proof 满足后，读取 [product-review.md](../verification/product-review.md)，用 `task review --state-revision ...` 同时记录工程结果、验证、剩余风险和产品验收摘要，进入 `review_ready`；这不是自动 `passed`。
- `review_ready` 保留同一个 task 和连续性上下文。用户提出相关后续工作时显式 `task resume`；用户接受时才 `finish --status passed --confirmation-source ...`。

## 完成条件

- 所有交付单元达到各自验证标准。
- enabled capability 的完成条件全部满足。
- 最终综合审查没有未处理的高风险发现。
- 结果、验证、回退与剩余风险已形成 review 回执，并等待用户接受或相关反馈。
