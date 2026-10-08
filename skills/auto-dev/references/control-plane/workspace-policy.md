# Governed Workspace Policy

只在项目确实存在超出 planned scope、Inherited Contract 与 protected branch 所能表达的稳定路径规则时启用。AI 可以根据仓库证据提出候选；只有用户确认后，`policy set` 才能持久化项目规则。Hook 机械执行已确认策略，不替代产品语义判断，也不自动写 policy。

## Rule Model

- `forbidden_paths`：永久拒绝；项目规则不能覆盖或削弱 `.git`、`.auto-dev` 等系统禁区。
- `approval_paths`：允许修改，但当前 Task 必须有绑定 policy/workspace/plan/current node 的 exact-path 用户批准。
- `sensitive_paths`：允许修改，但当前节点必须有 validation plan 与 proof contract，所有证据保持脱敏。
- 普通路径：继续执行 Intake、Quick Write、planned scope、Inherited Contract 与现有 strict blockers。

系统规则先于项目规则。项目 policy 只能加严，不存在 `allowed_paths` 或绕过系统保护的覆盖语义。规则 pattern 必须是规范化的 repository-relative POSIX glob；绝对路径、`..`、重复 ID 或重复 pattern 均拒绝。

## CLI Contract

`auto_dev.py policy inspect --path ...` 是零副作用读取，未初始化项目时也不创建 `.auto-dev`。它返回每个 exact path 的 `allowed / forbidden / approval_required / sensitive` 结果以及匹配规则。

`auto_dev.py policy set --policy-revision ... --policy-file|--policy-json ... --confirmation-source ... --reason ...` 只接受已初始化 Project，使用独立 `policy_revision`、文件锁、原子替换、备份和 readback。stale revision 或校验失败不得部分写入。

`auto_dev.py policy approve --policy-revision ... --state-revision ... --node ... --path ... --confirmation-source ... --reason ...` 只批准当前 Task 的 exact paths。批准保存到 `continuity.policy_approvals`，绑定 policy digest/revision、workspace fingerprint、Plan revision 与 current node；任一变化都会使旧批准 stale。重复的同一批准返回同一 id，不重复写状态。

Agent 原样转发 CLI JSON 中的稳定回执：

```text
🚧 Auto Dev Policy: policy_inspected
🚧 Auto Dev Policy: policy_set
🚧 Auto Dev Policy: policy_approved
```

## Hook And Continuity

PreToolUse 在 Quick Write 放行前检查路径策略。forbidden hard deny；approval 缺 fresh exact-path 批准时提示 canonical approve；sensitive 缺加强证据时拒绝。项目路径规则启用后，目标路径不可见的 Bash 写入 fail-close，改用 `apply_patch` 或其他 path-visible 操作。

`status --compact` 与 SessionStart 提供 revision、规则数量、批准 freshness 和 sensitive evidence 摘要；Progress UI 只读显示同一投影。Hook/UI 不修改 policy，也不执行验证。Handoff 携带批准历史但不覆盖目标项目 policy；导入后按目标 workspace 与当前 policy/Plan/node 重新计算 freshness。

## Completion

- policy 只来自明确用户确认，且 project/system 边界没有被削弱。
- Hook 在 Quick Write 与 Task write 两条路径给出一致结论。
- sensitive evidence 不含 secret value、credential 或原始敏感 payload。
- policy、Plan、node 或 workspace 漂移后，不沿用旧批准。
