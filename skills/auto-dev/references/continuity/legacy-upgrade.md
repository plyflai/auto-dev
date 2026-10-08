# Versioned Control Plane Upgrade

## Natural-Language Update Route

用户说“更新新版 Auto Dev”“升级这个项目的 Auto Dev”或等价表达时，Agent 自己运行本节的 inspect，不要求用户提供 CLI、revision、step 或 fingerprint。

- `current`：直接说明当前项目已兼容新版控制面。
- `upgrade_available`：展示变更、备份范围和风险，再让用户只选择“确认升级 / 暂不升级”；Agent 在确认后从刚刚的 inspect 自动带入完整 apply contract。
- `reverification_required / manual_decision_required / blocked / newer_than_cli`：Agent 说明当前阻塞和下一步，不猜测或强行 apply。

同一已运行的 Codex task 不能热切换已加载的 Plugin 包；这个限制不改变项目迁移的交互。新版 Plugin 在新 task 中加载后，Agent 仍按本节自动 inspect。

已有 `.auto-dev/` 时先运行只读检测：

```text
python3 <skill-root>/scripts/auto_dev.py legacy-upgrade inspect --repo-root .
```

脚本按代码级 State Surface Registry 检查 Project、全部 Task、Continuity、Proof attempts、Project Memory、环境/领域 Markdown 投影、Dependency Lease、Runtime Diagnostics、Workspace Policy、Handoff contract 和版本化验证门策略。插件版本变化本身不触发项目迁移；只有持久 schema 或语义契约差异才触发。

本命令是唯一会检查旧 `.autodev/**` 的路径：它只对已知素材计算有界 digest，输出 path/kind/suggested route，不解析、不导入、不创建新状态，也不把旧验证文字当作当前 Green。普通 status、Hook、repair 和新 `.auto-dev` 环境/领域运行路径不会读取旧目录。

## 状态选路

- `current`：不写文件，继续原流程。
- `upgrade_available`：展示 `changes`、全部 state surface、备份范围与 `apply_contract`，等待一次用户确认。
- `reverification_required`：结构已升级；只对 `revalidation_targets` 中 selected Task 的完成节点运行真实 `proof --revalidate`。
- `manual_decision_required`：旧完成记录没有可执行 Proof/Outcome，交给用户决定保留风险、补合同或另建工作；不猜业务结论。
- `blocked`：记录损坏或无法安全迁移，停止并报告 blocker。
- `newer_than_cli`：项目由更高版本写入，停止 mutation 并先升级插件。

Hook 和 Progress UI 只投影这个状态与 `action=legacy-upgrade inspect`；它们不 apply、不运行测试、不修改 Proof。

## Apply

`upgrade_available` 时使用编号菜单取得明确确认，再逐字复用 inspect 返回的 revision、完整 step 集合和 fingerprint：

```text
📍 当前: 控制面升级预演已完成 / Control plane upgrade preview is ready
📌 下一步:
[1] 确认升级 - 备份后采用当前状态契约
[2] 暂不升级 - 保持现有控制面不变
[0] 停止
```

```text
python3 <skill-root>/scripts/auto_dev.py legacy-upgrade apply \
  --repo-root . \
  --project-revision <apply_contract.project_revision> \
  --active-task-revision <apply_contract.active_task_revision> \
  --expected-upgrade-version <apply_contract.upgrade_version> \
  --expected-step <each apply_contract.expected_steps item> \
  --expected-fingerprint <apply_contract.fingerprint> \
  --reason "用户确认采用当前控制面状态契约" \
  --confirmation-source "用户在当前对话确认升级"
```

`apply` 在锁内重新 inspect，先备份所有写入目标，逐文件原子替换，失败自动回滚，最后逐文件 readback 并写审计。它升级 active 与 inactive Task，但保留历史 `runs/`、用户文字、Plan 编号和 Proof 历史；不清理产品 dirty worktree，也不伪造 Green Proof。不要用普通 `migrate` 代替，它只处理 selected active receipt。

## Revalidate

升级后若返回 `reverification_required`，先读取 target 的当前 `plan_revision/state_revision`，再执行原节点声明的真实命令：

```text
python3 <skill-root>/scripts/auto_dev.py proof \
  --repo-root . --revalidate \
  --node <target.node_id> --proof-id <target.proof_id> \
  --plan-revision <current plan revision> \
  --state-revision <current state revision> \
  --command <real verification command>
```

失败 attempt 继续保留，仍是 `reverification_required`。全部 target 获得 fresh Green 后，inspect 才回到 `current`。inactive Task 的旧问题只作为 warning 保留，等该 Task 被明确选择后再治理，避免一次升级被历史任务拖成全量重测。

升级进程若在备份后被外部终止，普通异常回滚可能来不及执行。此时显式调用 `auto_dev.py fix inspect` 读取 upgrade backup、完成 audit 和当前文件 fingerprint；用户确认后，使用 `fix apply --operation recover-interrupted-upgrade` 执行恢复：已完成或已回滚事务不处理；部分写入且没有目录冲突时，只允许回滚到备份前状态，再重新运行当前 CLI 的 `legacy-upgrade inspect`，不跨版本猜测 roll-forward。

## Feature Migration Contract

每个新增持久能力必须将状态影响归类为 `none / additive / structural / semantic / manual`，同步更新 `CONTROL_PLANE_STATE_SURFACES`，并在需要时追加严格递增的 `LegacyUpgradeStep`。目标 schema、contract revision、adopted version 与 step surface IDs 不一致时，注册表契约测试必须失败。UI-only、文案和普通插件版本变化标为 `none`，不得制造空迁移。
