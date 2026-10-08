# Capability: Parallel Work

## Enable When

至少两个工作流真正独立，输入输出边界清楚，并行收益大于上下文重建与合并成本。

## Do Not Enable

- 小型、紧耦合、共享大部分上下文的任务。
- 机械重复可由同一 warm context 批量完成。
- 子任务会修改同一核心文件或依赖前一步语义判断。

## Hard Gates

- 每个子任务有明确范围、输入、产物、验证和禁止触碰区域。
- 指定合并顺序与冲突所有者。
- Reviewer 只在风险与独立性证明其成本时派发。
- 子代理不能自行扩展产品范围或外部权限。

## Budgets

- 默认每个独立工作流一个实现 Agent。
- 并行总量以 Capability Receipt 的 `parallel_agents` 为上限，并为主协调上下文保留运行容量。
- 机械任务合并审查；高风险基础模块独立审查。
- 发现共享上下文或串行依赖后停止 fan-out，回到主上下文。

## Completion

- 所有子任务结果已消费并验证。
- 合并后的整体行为通过最终综合审查。
- 没有重复完成或遗留活动 Agent。

## Routing Boundary

`parallel-work` is a Root Team capability. It authorizes the planner to compile
parallel-eligible Work packets and use the worker lifecycle to prepare isolated
worktrees and capture/apply results. Model selection and Codex subagent creation
remain host responsibilities.
It does not change `Direct`, does not force Multi-Agent execution, and does not
let a worker create another Team or enable capabilities. Packet-local
`required_capabilities`, `review_policy`, `verification_policy`, and
`merge_policy` are derived after packet compilation. Until the worker runtime
is verified, the CLI records the requested topology and exposes whether a worker
has been prepared, captured, applied, or cleaned; it never invents a completed
worker or merge result.
