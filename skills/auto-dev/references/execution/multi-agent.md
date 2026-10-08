# Multi-Agent Team Core

进入条件：Root Task 已选择 `Team Core`，当前 Milestone 使用 Rolling Graph，并且当前 execution decision 选择 `multi_worker`。只有真正需要并行 Worker 时才要求 Root Capability Receipt 启用 `parallel-work`；`single_worker` 是同一控制面下的单 Worker lane，不需要该 capability。

## Boundary

- `Direct` 不隐式创建 worker。
- `Team Core + Single Agent` 仍是完整、受支持的原有路径。
- `Team Core + Multi-Agent` 只改变 Work packet 的执行拓扑；Requirement Intake、Root capability、Outcome Contract、Proof、Integration 和 Review 仍由 Root 控制面拥有。
- Work packet 不重新选择完整 Direct/Team Core；它携带局部 `execution_profile`、`required_capabilities`、`verification_policy`、`review_policy` 和 `merge_policy`。
- Worker 不能扩大 scope、修改 Root 状态、递归创建 Team 或自行启用 capability。缺少上下文或能力时返回 re-route/recompile 请求。

## Context Capsule

启动 worker 时应提供可校验的 packet 上下文：项目、branch、base HEAD、Task/Outcome/Milestone、继承的 hard constraints 和 forbidden moves、write scope、ownership、提供/消费契约、已授权 capabilities、plan/state/contract revision、proof recipe、模型 profile、预算和停止条件。

## Current Runtime Boundary

当前源码阶段已支持 packet policy 的编译、digest、frontier 和状态回读，并提供确定性的 `milestone worker prepare|bind|inspect|capture|apply|finalize|cleanup` 生命周期：`prepare` 创建隔离 worktree 和 Context Capsule，但只进入 `dispatch_required`；`bind` 必须记录真实 executor ref，或记录 `dispatch_blocked`。默认 `light_worker` 使用内置 Luna profile；DeepSeek 等非内置通道必须在 execution select 时使用 `external_worker` 明确声明 provider/model/reasoning，bind 时完全匹配。控制面不搜索 key、relay 或历史配置。只有 `running` Worker 才能 capture scope-checked patch；主控 finalize 才能运行 Proof 和 Checkpoint。

## Verification Handoff

Packet 完成后必须回传结构化 result：`packet_id`、`base_head`、`context_digest`、changed paths、proof attempts、capability evidence、contract effects、unresolved findings 和 next action。主模型据此执行 Packet Review、Pre-Merge Validation、Integration Proof 和 Milestone Review。
