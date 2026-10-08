# Performance Verification

这是 `measured_improvement` Outcome 的条件式验证 profile，不是所有任务的固定阶段，
也不是新的 benchmark runner。

## Enable When

- 用户结果明确涉及延迟、吞吐量、CPU、内存、包体积或启动/构建时间；
- Outcome 使用 `kind=measured_improvement`，并有可重复的项目 benchmark；
- 目标指标、方向、工作量和环境已经具体到可以前后复测。

普通功能、修复、UI 或文档任务不启用。功能异常但根因未知时走 Debug，而不是用
Performance profile 代替诊断。

## Proof Contract

同一个具名 Proof 使用 `auto-dev/performance-evidence/v1` 形成 append-only 两段历史：

1. `phase=baseline`：至少两次样本，记录 hypothesis、metric、unit、direction、
   target、workload、environment 与 noise tolerance。成功命令只产生 `recorded`，
   Outcome 仍是 pending。
2. `phase=comparison`：引用该 Proof 的 baseline attempt，并在相同 metric、target、
   workload、environment 和 noise tolerance 下至少复测两次。

Comparison 只有在 benchmark 命令成功、目标达成，并且相对改善幅度大于声明噪声时
才成为 Green。baseline 或 comparison manifest 改动都会使结果 stale。可能影响功能
行为时，Outcome 另声明必要的功能回归 Proof；性能提升不能替代功能正确性。

## Boundaries

- 优先复用项目已有 benchmark、profiler 或 CI 报告；Auto Dev 不生成通用 runner。
- 不用单次更快、不同工作量、不同环境或手工挑选样本宣布成功。
- baseline 只是比较依据，不是完成证据；无可重复基线时缩小结论或记录阻塞。
- 原始 trace、profile 和长日志留在外部报告，通过 `source_ref` 回查。
