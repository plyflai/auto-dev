# Verification

## P0 Evidence Contract

Verification is the shared Direct/Team evidence contract. Keep one Plan and one
Outcome/Proof/Checkpoint chain; do not create a second verification ledger.

- Run the smallest proof that can falsify the current outcome. For a web app,
  this can include a headed browser journey when the GUI capability is enabled;
  backend scripts and service checks remain ordinary proof commands.
- `proof` appends an attempt. Each receipt carries the task ID, redacted
  command, command/output digests, scope fingerprint and an optional failure
  classification. A failed attempt remains visible when a retry passes.
  Checkpoint and review consume the latest attempt only when its outcome, plan
  revision, scoped worktree fingerprint and applicable runtime are still
  fresh.
- Team Plans may use `node_kind=delivery|verification|release`. A verification
  node carries `verification.scope`, `verification.gate`,
  `verification.placement_reason`, and optional scenario/expected/actual
  observations; the Agent chooses placement and records why.
- A dedicated verification Milestone is visible in status and Progress UI. It
  is not required for Quick Write or small Direct work, which still records a
  minimum proof.
- Users do not need to issue a separate “start testing” command. After an
  implementation unit, the Agent runs the applicable proof and records the
  result. A blocking verification node prevents dependent delivery and review;
  advisory results remain visible and must be closed or reported before review.
- A control-plane upgrade never turns legacy evidence Green. When
  `legacy-upgrade inspect` returns `reverification_required`, rerun only its
  listed selected-Task targets with `proof --revalidate`; this appends a real
  attempt while leaving the completed node and Plan numbering unchanged.
- After migration revalidation is complete, later in-scope delivery may make a
  historical Green proof stale. Keep that state as a completion blocker while
  the current Plan node remains writable; require affected proof to become
  fresh again before checkpoint, review, or finish. Missing, failed, or
  never-revalidated migration proof remains a strict write blocker.

## CLI Surface

Use the canonical `auto_dev.py` front door:

```text
auto_dev.py plan ...
auto_dev.py proof ...
auto_dev.py checkpoint ...
auto_dev.py status --compact
auto_dev.py handoff export|import ...
```

Proof artifacts remain bounded receipts with redacted command, exit code,
digests, attempt identity, freshness, optional evidence-artifact refs and a
failure classification when the command fails. Use
`--failure-classification product|test_asset|environment|dependency|flaky|timeout|permission|unknown`
when the failure is already diagnosable. Full logs, screenshots, HAR files and
traces stay outside the task receipt.

### E2E Product Evidence

When an E2E run produces a product-facing report, pass it to the same proof with
`--evidence-file`. The manifest uses `schema: auto-dev/e2e-evidence/v1` and
records only the bounded summary: `user_flow`, `environment`, `checks.page`,
`checks.data_interaction`, `checks.system_result`, `result`, `unverified` and
`next_step`, plus a `source_ref` for the full report. The proof stores the
manifest path and digest; changing the report makes the proof stale. A
`partial` or `blocked` E2E result cannot become a Green proof.

### Release Product Evidence

An authorized project release may attach `schema: auto-dev/release-evidence/v1`
to the same proof. This path is available only when the Team Task enabled the
`release` capability and the active Plan node has `node_kind=release`. The
bounded manifest records environment, version, health, key user-flow smoke,
rollback trigger/target, final result, unverified boundaries and the product
next step. It records evidence after the release action; it does not deploy or
grant release permission. Only a fresh `succeeded` result with passing checks
and a ready or not-applicable rollback can become Green.

### Conditional Performance Evidence

When the Outcome is `kind=measured_improvement`, read
[performance-verification.md](performance-verification.md). The same Proof first
records a multi-sample baseline and later records a comparison that references
that baseline attempt. Baseline remains pending; comparison becomes Green only
when the target is met and the improvement exceeds declared noise under the
same metric, workload and environment. Ordinary outcomes do not load this
profile.

验证目标是用最小充分证据证明用户结果，而不是执行固定测试套餐。

## 选择顺序

1. 直接覆盖改动行为的目标测试。
2. 受影响模块的类型检查、构建、lint 或契约检查。
3. 用户可见运行路径的 CLI、API smoke 或 GUI 验证。
4. 只有影响面证据支持时才扩大到更宽回归。

## 证据规则

- 连续性节点先按 [outcome-contract.md](../intake/outcome-contract.md) 运行具名 proof；`done` 只消费当前 outcome 对应的成功 receipt。
- 展示实际执行的命令或 GUI 路径及关键结果。
- 区分 `passed / failed / not_triggered / unavailable / needs_business_confirmation`。
- 自动测试通过但运行观测与预期不符，仍未完成。
- 无法运行时说明原因、替代证据和剩余风险，不把责任泛化给用户。
- 运行诊断适用时，触发成功和相关失败路径，并按 `.auto-dev/runtime-diagnostics.json` 的读取方法定位记录；无法留下或读取记录时，不把诊断交付标为完成。
- dependency candidate、版本变化或失败路径必须基于实际 runtime evidence 裁决 `passed / failed / inconclusive`，再按 dependency registry 记录 attempt；known-good 配方的常规成功无需重复记录。
- 测试数量、文件存在、报告生成或旧证据重跑，只能证明其直接覆盖的事实；不能自动证明本节点产生了新行为、新修复或新知识。

## 风险映射

- 规则或函数：目标单测。
- API/Schema：契约与关键请求验证。
- 异步、缓存、竞态、性能：测试加观测对比。
- 新建或改变的运行态功能：关键状态、外部边界和错误路径的结构化日志，加上 `.auto-dev/runtime-diagnostics.json` 的读取验证。
- GUI：目标测试加真实界面验证。
- 数据迁移：演练、校验和回滚验证。
- 结构重构：每个迁移批次对比 before/after 行为、公共入口和外部副作用；文件变短或文件数量变化本身不能成为 Green proof。
- 项目已配置模块边界、循环依赖、复杂度、重复或文件体量 lint 时，复用项目阈值作为结构证据；Auto Dev 不另设全局数值门槛。

## 完成条件

- 用户验收与验证证据一一对应。
- 失败和未执行项没有被隐藏。
- E2E 产品回执说明用户流程、测试环境、页面表现、数据交互、系统结果、未覆盖范围和产品下一步；原始截图、HAR 和日志仍留在外部证据。
- Release 产品回执说明目标环境、部署版本、健康检查、关键用户流程、回退准备、未覆盖范围和产品下一步；CI/CD 原始报告仍留在外部证据。
- Performance 结果必须有同条件、多样本的 baseline/comparison；单次更快或噪声内变化不能成为 Green。
- 验证范围由影响证据决定，而非固定全量命令。
- 运行诊断适用时，项目级日志层、持久化记录和后续 Agent 的读取入口均已验证。
