# Execution Router

进入条件：Requirement Intake 已完成，需要选择或执行 Read Only、Direct 或 Team Core。

- 只读调查：[read-only.md](read-only.md)
- Direct/Team 选择：[execution-router.md](execution-router.md)
- Direct 交付：[direct.md](direct.md)
- Team Core 骨架：[team-core.md](team-core.md)
- Team capability 选择：[capability-router.md](capability-router.md)
- Plan/Proof/Checkpoint 执行循环：[execution-loop.md](execution-loop.md)
- 薄 Milestone Roadmap、执行前 Work Packet DAG 编译与滚动验收：[rolling-milestones.md](rolling-milestones.md)
- Multi-Agent Team Core 的 worker 契约与调度边界：[multi-agent.md](multi-agent.md)

短而稳定的执行继续使用普通 execution loop；长任务、依赖图或显著事实漂移风险选择 Rolling Milestones。每次只进入当前档位与 enabled capability 所需的 leaf，不同时加载 Direct 和 Team 全路径。
