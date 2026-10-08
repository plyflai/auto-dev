# Outcome Contract

Outcome Contract 防止把计划、过程记录或报告当作产品性交付。它不要求每个任务都写代码；它要求 Agent 只在用户目标已经产生可验证变化时声明完成。

## 层级边界

本文件中的 Plan Node Outcome Contract 说明“当前 Task 如何证明完成”；它不是项目层 Outcome Graph。项目层 `outcome` 可以递归，并描述有限、可观察的产品结果；Task 永远不能包含 Task，只引用一个 primary Outcome；Plan Node 只属于当前 Task，不能承载独立产品意图。跨仓库关系仅保存为 Project Frame 的 soft evidence，不把外部控制面接进本地 DAG。

## Inherited Contract

对于 fork、迁移、兼容或用户明确声明“绝对不能偏离”的工作，Requirement Baseline 可带一个版本化 `contract`。它是 Outcome DAG 上随层级下传的不可削弱约束，不是另一棵 OKR 状态树：Project Frame 的主线向 Outcome、Task 和 Plan 逐层投影；每个子层只能追加约束和 coverage，不能删除、改写或降级父层内容。

```text
EffectiveContract(child) = ParentContract + child additions
```

合同的经济型字段是：

- `mainline`：一句不可替换的主线。
- `hard_constraints`：必须保留的事实或行为。
- `forbidden_moves`：不能靠“发明新产品”绕过的路径。
- `replacement_map`：唯一允许的领域替换关系。
- `required_coverage`：每项带 ID、描述和 `evidence_kind` 的必证结果。

Coverage may additionally declare `write_gate: before_product_write` when the
reference, workflow, visual, or compatibility evidence must be proven before
any product file is changed. `artifact_schema` makes a proof read a matching
JSON evidence manifest through `proof --evidence-file`; a successful command
alone is not parity evidence.

`mode=legacy-parity|migration|fork|compatibility|strict` 启用 strict contract。Task 在 `start` 时冻结 effective snapshot 与父 hash；父合同之后变化时 Task 变为 `stale`，不能继续产品写入，必须通过 Requirement Diff 建立新 baseline。普通未绑定 Task 保持 legacy 行为。

strict 父 Outcome 自己的 `statement + acceptance` 也会被折叠成 snapshot 中的 `parent_outcome` hard constraint；因此改写父 Outcome 不是只改展示文字，会使已经开始的子 Task 进入 `stale`。对 strict Outcome 的 statement、acceptance、Intake 或 contract 修改，CLI 要求 `--requirement-diff-confirmation` 记录确认来源。

Plan Node 用 `coverage_ids` 声明自己贡献哪几项 coverage。Task 在 `start`
时声明自己的 coverage contribution；strict Plan 必须覆盖这些 ID，每一项还
必须由该 Node 的 outcome proof 声明。proof 的 `evidence_kind` 必须匹配
coverage 的类型，除 `supporting` 外不能降级。因此 `build` 不能替代
`route-matrix`、`visual-parity` 或 `compatibility`。Node/Task 变绿只证明
自己的 coverage；父 Outcome 只有在其自身及子 Outcome 下的 Task coverage
全部汇总通过后才允许进入 `completed`。

后台迁移可以把以下内容写进 baseline：旧系统 fork 边界、旧模块到新模块的 replacement、既有队列/存储/重试行为的 compatibility coverage，以及“无旧路由或流程依据时不得新增管理页面”的 forbidden move。

## 主结果

每个新的连续性节点必须声明：

- `kind`：`behavior_change / defect_resolution / measured_improvement / decision / knowledge_gain / document`。
- `primary`：完成后相对开始时真正变化的结果。
- `proofs`：至少一个具名 proof，说明如何证伪或读回主结果。
- `document_authorization`：只在 `kind=document` 时填写，引用用户明确要求的文档交付或任务本身的文档目标。

没有连续性计划的一次性 Direct 任务，在 `start` 时声明同样的 run-level outcome（主结果和一个 proof）。`task review` 必须消费该 proof，之后 `finish --status passed` 还需要用户明确接受；因此短任务不会因为没有里程碑而退回自由文本验收。

`kind=measured_improvement` 使用 [performance-verification.md](../verification/performance-verification.md)
的条件式 baseline/comparison Proof。baseline 只记录比较起点，不完成 Outcome；
comparison 必须引用同一 Proof 的 baseline attempt，并在相同工作量和环境下证明目标
达成且变化超过噪声。

报告、计划、清单、ledger、截图和日志默认是 supporting evidence。除非 `kind=document` 且存在授权，它们不能替代主结果。测试数量、文件存在或旧证据重跑也不能单独证明新行为、新修复、新结论或新决策。

## 计划示例

```json
{
  "id": "fix-timeout",
  "title": "Fix checkout timeout",
  "status": "active",
  "acceptance": ["The reproduced timeout no longer occurs"],
  "outcome": {
    "kind": "defect_resolution",
    "primary": "The minimal timeout reproduction passes without changing retry semantics",
    "proofs": [
      {"id": "timeout-repro", "description": "Run the minimal regression reproduction"}
    ]
  }
}
```

运行 proof 时使用 canonical CLI；它实际执行命令并保存退出码、输出摘要哈希、HEAD 和工作区状态。Checkpoint 只消费与当前 outcome 内容匹配的成功 receipt：

```text
auto_dev.py proof --repo-root . --node fix-timeout --proof-id timeout-repro \
  --plan-revision 2 --state-revision 8 --command "python3 -m pytest tests/test_timeout.py"
```

`plan` 不能把 active/planned 节点直接改成 `done` 来绕过 proof。接管项目时若计划确实要登记控制面建立前已经完成的节点，节点需携带 `historical_completion.summary / evidence / confirmation_source`；后续执行仍必须走 `proof -> checkpoint`。

## 诚实停止

无法实现、无法验证或外部条件缺失时，不为满足 Outcome Contract 制造代码、测试或报告：

- 使用 `checkpoint --status blocked`。
- 同时登记 blocking gap、owner、已尝试动作或失败证据，以及解除阻塞所需的最小下一步。
- 能得出有限结论但无法完成主结果时，缩小结论并保留 `partial / inconclusive`；不能把 supporting evidence 升格为成功 proof。
- 时间、预算或人员数量不能突破物理依赖、串行依赖、权限边界和不可获得的证据。先停止生产性动作，再如实向用户说明。

## 完成条件

- `done` 节点的每个 required proof 都有当前 outcome 对应的成功 receipt。
- 用户验收与 proof 一一对应；验证的是主结果，不是 Agent 做了多少步骤。
- 文档型主结果有明确授权；其余文档只作为 supporting evidence。
- `blocked` 节点保留真实尝试、阻塞原因、责任方和可执行下一步，不被完成压力误标为成功。
