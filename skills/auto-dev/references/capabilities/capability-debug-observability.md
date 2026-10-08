# Capability: Debug And Observability

Debug/Observability 是 Team Core 的条件式能力，不是独立 mode。普通已知根因修复保持 Direct；Team 中一轮观测可收敛时使用 `standard`，只有多轮不确定性需要恢复时使用 `profile: deep`。

## Enable And Profile

启用 `debug-observability`：根因未收敛，涉及异步、缓存、竞态、性能、跨边界状态、多轮诊断，或运行诊断结论为 `foundation`。

升为 `deep`，满足任一决定性证据即可：

- 初次导航/观测后仍有多个需要 probe 区分的根因候选。
- 复现不稳定，必须保存 runs/failures/rate 和 observation history。
- 一次修复没有恢复原始反馈循环，且失败不是测试资产/环境问题。
- 诊断预计跨 session、compact、harness、GUI/backend/device 或机器继续。
- 用户明确要求系统性、多轮排障。

根因已唯一确定时不为凑流程生成假设；当前环境始终 Green 时允许 `no_defect_observed`；无法取得区分性证据时记录 `inconclusive/blocked`。

## Deep Debug Loop

### 1. Begin

在当前 Team Task/current node 上执行 `debug begin`，保存症状、范围、环境引用、下一 probe 和开始时 HEAD/worktree baseline。它创建 `continuity.diagnostic`，不创建 Debug Task、Markdown ledger 或独立 revision。

### 2. Search Project Cases

先按 [project-memory.md](../control-plane/project-memory.md) 执行只读 `memory case search`，再用 `debug case-search bind` 绑定同一 memory revision/digest。历史 `incident_case` 只是带来源的 hypothesis seed；没有当前 probe 不能确认根因。没有 Project Memory 时 `miss` 不阻塞。

### 3. Reproduction Gate

优先失败测试、CLI/API、最小脚本、GUI 自动化、trace replay、差分/bisect 或结构化人工步骤。用现有 `proof`/evidence 执行，再用 `debug reproduction record` 保存：

- `not_ready / ready_red / ready_flaky / ready_green_no_defect / unavailable`
- original/minimal proof refs、runs/failures、Agent 是否可独立执行

failed proof 可以是有效 Red 证据；它不因此变成 Green proof。

### 4. Falsifiable Hypotheses

使用最小可区分假设集，不固定 3-5 个。`debug hypothesis add` 必须写 statement、prediction 和 minimal probe；历史 case 来源用 `source_case_id` 标明。假设实质变化时新增 ID，不改写旧假设。

### 5. Observe One Primary Hypothesis

每轮先执行现有 proof/GUI/runtime/external evidence，再调用 `debug observe` 保存 expected、actual、`rejected|confirmed|inconclusive` 与 refs。Observation 只引用证据，不复制日志、HAR、trace 或截图正文。

### 6. Resolve

`debug resolve` 只允许：

- `root_cause_confirmed`：fresh confirmed observation 能解释原始症状。
- `no_defect_observed`：fresh `ready_green_no_defect`，且 Debug 开始后没有遗留产品/worktree 修改。
- `inconclusive`：现有证据不能区分候选。
- `blocked`：权限、设备、环境或外部依赖阻止关键 probe，并记录 owner/下一证据。

根因改变产品目标、规则、范围或验收时仍走 Requirement Diff。

### 7. Fix And Recovery

修复只针对 confirmed mechanism。Git point、Impact/Preservation、Workspace Policy 仍按自身风险触发，不因 Deep Debug 自动全开。诊断测试、最小脚本和 temporary instrumentation 属于合法 planned-scope 工作，不能仅因根因未知被 Hook 一刀切阻止。

修复后重跑最小复现、原始路径、适用负例/回归和 runtime/GUI/device readback。`debug recovery` 使用：

- `verified`：fresh passing proof + `probe_cleanup=complete`。
- `awaiting_confirmation`：自动证据完成但仍待真机/用户确认。
- `failed`：恢复验证仍失败。
- `not_applicable`：仅用于 fresh no-defect 结论。

### 8. Review And Promotion

继续使用 `task review -> review_ready -> 用户接受 -> finish passed`。`awaiting_confirmation`、`inconclusive`、`blocked` 不能完成或晋升案例。

用户明确接受后，可用 `memory case promote` 把紧凑根因、修复、保护性测试、教训和 evidence refs 写为 confirmed `incident_case`。不自动写 Post-mortem；用户说仍有问题时恢复同一 Task 和 diagnostic state。

## Observability Boundary

产品日志/trace 的存储、读取和 redaction 继续由 [runtime-diagnostics.md](../control-plane/runtime-diagnostics.md) 管理。`runtime-diagnostics.json` 是日志基础设施契约，不保存当前 hypothesis。临时探针使用 Task/Hypothesis 指纹，完成前清理或转为有 owner 的长期观测。

## Hook And UI Boundary

- SessionStart/status/UI 只投影 reproduction、case match、active hypothesis、last verdict、resolution/recovery 和 next probe。
- UserPromptSubmit 不生成 hypothesis 或写 Project Memory。
- PreToolUse 不搜索 case、不运行 probe/test/GUI、不决定根因、不自动 promotion。
- Deep Debug 不自动启用 Subagent；只有 `parallel-work` 独立命中时才能委派有界 probe。
- 不新增 `🩺` 回执；沿用 Team Capability Receipt、proof、review 和 `🪝 Auto Dev Hook:`。

## Completion

- confirmed root cause 必须有 fresh observation，恢复必须有 fresh Green proof，临时探针已清理。
- no-defect 必须有代表性 Green evidence 且未留下产品修改。
- awaiting/inconclusive/blocked 保留责任方与下一最小证据，不包装成完成。
- Resume/Handoff 重算 proof freshness；stale observation 不再支撑 confirmed resolution。
