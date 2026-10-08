# Task

进入条件：修改 branch-selected Task、Plan 编号/依赖、交付命令、review-ready 后续或归档。

- Task 持久化、选择与投影：[state.py](state.py)
- Task list/select/pause/resume/scope 命令：[commands.py](commands.py)
- Plan 解析、编号与节点校验：[plan.py](plan.py)
- Rolling Packet 的 Proof recipe 闭合与隔离 preflight：[proof_contracts.py](proof_contracts.py)
- start/plan/checkpoint/event 等交付编排：[delivery.py](delivery.py)
- Rolling Milestone frontier、compile、handoff、Integration 与 Review：[milestones.py](milestones.py)
- Worker worktree、dispatch bind、capture 与 host finalize：[workers.py](workers.py)
- completion、archive 与 abandon：[completion.py](completion.py)

顶层 `runctl.py` 继续拥有 public exports。验证入口是 runctl selftest、plan numbering、P0 migration 与 Hook task-state 测试。
