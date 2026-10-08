# Conditional Impact And Preservation

这是一条按风险触发的保护 profile，不是新的 Team capability，也不是所有 Direct 任务的固定仪式。重构、删除、重命名、公共 API/Schema 迁移或共享契约变化需要在压缩/交接后继续保留影响判断时启用；普通局部修改继续使用 CodeGraph 导航与目标验证。

## Workflow

1. 用当前 CodeGraph 索引定位目标 symbol/file，运行 `auto_dev.py impact inspect --symbol ... --file ...`。inspect 用结构化 `codegraph status -j` 拒绝 pending change、worktree mismatch 或 extraction version 漂移，再对 symbol 做上限为 `--max-depth` 的渐进检查，并按 `--test-filter` 或已识别语言的默认 filter 查询 tests；它不 sync、不写控制面。
2. Agent 根据 `coverage_status`、`coverage_reasons`、结构证据补充语义保留项、动态风险、不确定项和验证动作。`impact_signal` 只表示发现了依赖，不表示覆盖完整；零 caller/test 或 `partial / unknown` coverage 必须留下 `--uncertainty`。
3. 用当前 Plan node 与 `state_revision` 执行 `impact record`。CLI 会重新检查 CodeGraph，再把 receipt 追加到当前 Task 的 `continuity.impact_receipts`。
4. 修改前读取 `status --compact` 的 `continuity_summary.impact`。索引、相关文件、Plan revision 或 current node 变化会显示 stale；按当前证据重新 inspect/record，不复用旧结论。

```text
auto_dev.py impact inspect --repo-root . --symbol <name> --file <path> \
  [--max-depth 8] [--test-filter 'tests/test_*.py']
auto_dev.py impact record --repo-root . --node <current-node> --state-revision <revision> \
  --symbol <name> --file <path> \
  [--max-depth 8] [--test-filter 'tests/test_*.py'] \
  --preserve "<observable behavior or relationship>" \
  --verify "<test or observation>" [--uncertainty "<unknown>"]
```

## Boundaries

- CodeGraph 仍是结构事实源；receipt 只保存结果摘要、digest、保留项和验证动作，不复制代码图。
- Hook、Progress UI 和 status 只读既有投影，不在生命周期事件中运行 CodeGraph。
- stale impact 先作为显式风险提示，不自动成为所有产品写入的全局门禁；已有 scope、Inherited Contract、Intake 和 capability gate 保持权威。
- Handoff 保存 receipt，并在目标工作区按索引和 scope fingerprint 重算 freshness。
- path policy writer、自动删除许可和 rollback apply 不属于本 profile。

## Receipts

- `💥 Auto Dev Impact: impact_inspected`：只读预览完成。
- `💥 Auto Dev Impact: impact_recorded`：当前节点的影响、保留项、验证动作和不确定性已持久化。
