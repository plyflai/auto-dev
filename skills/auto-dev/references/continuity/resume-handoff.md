# Resume And Handoff

## Continuity Activation

只在任务预计跨多个交付单元、session、harness 或机器，或用户明确要求持续进度时启用连续性状态。短小、一次完成的 Direct 任务不创建额外计划。

Project/Branch/Task 的索引真相源是 `.auto-dev/project.json` 与 `tasks/<task-id>.json`；选中 task 的结构化 `continuity` 字段是真正的计划真相源，`active.json` 只是当前 branch 的兼容投影，本地进度服务仍然只是投影。若服务不可用，Agent 直接读取 branch-aware `auto_dev.py status`，不能根据聊天记忆或 markdown 自行重建当前节点。

Plugin Hook 在 `startup / resume / clear / compact` 后调用同一个 compact status，并把当前目标、revision、节点、交付契约和阻塞重新注入 developer context。已有当前 branch 的 active、review_ready 或 selection_required 状态时，新 session 会自动获得只读 resume activation，不需要再次说“继承控制面”或输入 `$auto-dev`。`SessionStart` 不修改 `.auto-dev`，也不抢 writer；首次 canonical control mutation 或产品写入才 acquire branch writer lease。新 writer 接管后，旧 session 的 lease 变为 observer，旧 session 的后续写入由 Hook 拒绝，但读取 status、代码和进度仍可继续。每次 `SessionStart` 还会复用或启动当前仓库的回环只读进度服务，并在 Hook 回执中给出实际控制面链接；服务固定请求 `--port 0`，由系统分配空闲端口。Hook 只是自动触发入口；CLI 输出仍是真相源，注入失败时 Agent 回到本节的显式 Resume 流程。

## Bootstrap / Adopt

接手项目时先运行 `auto_dev.py project inspect --repo-root .`。这是只读调查，也适用于尚未初始化 Git 的目录；`git_setup_recommended` 时先按 [pre-git-control.md](../intake/pre-git-control.md) 推荐 Git、允许只读澄清或由用户明确选择 local No-Git control。已有 Git 但没有 Project 时，再由用户确认 `auto_dev.py project init --mode git --confirmation-source ...`；local control 后来发现 Git 时返回 `migration_available`，必须用 `project migrate` 显式迁移。已有 `.auto-dev` 时，在 `bootstrap` 或 `fix` 之前先运行 `auto_dev.py legacy-upgrade inspect --repo-root .`：`current` 继续；`upgrade_available` 预演并等待确认；`reverification_required` 只复验列出的完成节点；`manual_decision_required / blocked / newer_than_cli` 按 [legacy-upgrade.md](legacy-upgrade.md) 停止产品 mutation 并说明下一动作。随后运行 `auto_dev.py bootstrap inspect` 调查旧 receipt。`no_control` 或 `legacy_recoverable` 时，Agent 先 Survey 项目并复用 Requirement Intake 的两个已有确认：确认恢复/新建 Goal 与验收，再确认完整 Plan；没有这两项确认，不调用 apply。

使用 `auto_dev.py bootstrap apply --mode fresh|adopt|replace` 建立新的唯一控制面：`fresh` 只接受没有 active 的项目；`adopt` 只接管有 task ID 但没有可用计划的 legacy active；`replace` 才能显式替换可读的旧计划。`adopt/replace` 必须提供 `--expected-task-id`。脚本会先验证完整 JSON Plan、依赖、父子节点和当前节点，再在锁内归档旧 receipt、原子写入新的 active 与备份，并执行 strict readback；旧 receipt 标记为 `superseded`，不会被删除或静默覆盖。损坏 active 先走 `recover`；没有备份时停止，不能用 bootstrap 覆盖。

Bootstrap 结果写入 active receipt 的 `continuity.bootstrap`，并产生 `control_bootstrapped` 事件。接手 Agent 后续仍以 `status --compact --strict`、`goal_revision`、`plan_revision`、`state_revision` 和 `current_node` 为准，不从 bootstrap 输出另造进度表。

初始化或调整计划时使用 `auto_dev.py plan`，每次计划调整必须携带当前 `plan_revision` 作为 base；目标或验收变化时再提供用户确认来源。每个新节点必须按 [outcome-contract.md](../intake/outcome-contract.md) 声明主结果与 required proofs。根节点在 `nodes` 数组中的顺序定义主里程碑顺序，控制面自动写入连续 `display_code`，子任务从 `parent_id` 推导 `<parent>.<index>`；`id` 必须保持稳定，标题不是编号真相源。插入根节点会自动后推后续展示编号；若改动已完成或已替代节点的编号，必须带 `--numbering-change-confirmation`。执行单元边界使用 `auto_dev.py checkpoint --plan-revision ... --state-revision ...`。不要把普通 checkpoint 写成新的计划版本。

## Resume

优先执行 `auto_dev.py status --compact --strict` 或 `auto_dev.py resume`；resolver 先按当前 branch 找唯一 selected current task（`active` 或 `review_ready`），再汇总任务 receipt、Git 状态、连续性状态、当前节点、目标/计划 revision、pending action、缺口和 durability。若 `hierarchy.control_plane_upgrade.status` 不是 `current`，先走 [legacy-upgrade.md](legacy-upgrade.md)，不要把它误当成 `bootstrap` 或普通 `migrate`。若 branch 有未终态但没有 selected task，返回 `selection_required` 和紧凑候选列表；必须用 `task select` 确认后再写入。返回非零或状态不是 `ready` 时，不继续受影响的产品写入。active receipt schema 需要兼容字段升级时显式执行 `auto_dev.py migrate`，只读 status 不静默改文件；active 投影损坏但存在 last-known-good 时先执行 `auto_dev.py recover`。需要人工查看时，可启动 `auto_dev.py progress --repo-root . --port 0`，但 UI 只读同一 compact 状态，不替代 JSON。服务通过 SSE 对当前 task receipt 的写入即时更新，并每 60 秒轮询一次作为断线或外部修改的兜底。运行诊断清单存在时，先恢复日志层、存储位置、读取命令、字段约定和已知限制；项目依赖 registry 存在时只读取当前任务 scope 相关配方，复用仍有效的 resolution lease，只有版本/环境漂移、失败或显式复验才展开历史，再恢复目标、已完成工作、enabled capabilities、预算上限与消耗、下一最小动作和阻塞。

目标未变时继续原档位，不重复 Requirement Intake。自动恢复的首个用户 turn 仍会通过 bounded intake turn 写入当前 turn identity，并受同一 writer lease 串行化；目标、范围、规则或验收变化时输出 Requirement Diff 并重新确认。

## Review-Ready

完成 proof 和最终审查后，读取 [product-review.md](../verification/product-review.md)，`task review --state-revision ...` 把工程 review 和产品验收摘要写入当前 task，并置为 `review_ready`；不清除 branch 选择、计划、M 编号、proof 或 active 投影。`status --strict` 会把它作为明确的用户等待状态返回非零，Hook 也会拒绝产品写入。

用户的后续请求若自然延续该结果，用 `task resume --state-revision ... --reason ... --confirmation-source ...` 恢复同一 task，再补 plan、scope 或 proof；不要新建 task 丢失上下文。若请求无关，先问用户是否接受并归档当前结果；接受后才 `finish --status passed --confirmation-source ...`，再创建新 task。一个 branch 同时只有一个当前 task，暂停的旧 task 也不能与新 active task 并存。

scope 仅扩展到相邻实现或测试路径时记录 `task amend-scope --kind adjacent`；遇到新的产品语义或风险边界时先走 [Requirement Diff](../intake/requirement-intake.md#4-requirement-diff)，再用 `--kind requirement-diff` 记录确认。

## Control-Plane Fix

当用户说“刚才那串内容哪里去了”、任务被错误归档、selected projection 损坏、或升级事务中断时，先用 `auto_dev.py fix inspect --repo-root .` 只读诊断。不要直接编辑 `.auto-dev/`。根据 inspect 结果向用户说明候选任务和风险；用户确认恢复后，再调用 `fix apply` 的具名 operation。CLI 自动校验 task/project revision 或 upgrade manifest/fingerprint，备份受影响投影，保留原 archive 与 upgrade backup，写入 repair audit 并 readback。当前 registry 提供 `restore-task`、`reconcile-projection` 和只回滚无完成审计且状态未漂移的 `recover-interrupted-upgrade`；新修复能力必须新增具名 operation，不能退化成任意字段 patch。

比较记录中的 branch、HEAD、planned scope、goal revision、plan revision 与当前状态。漂移、未解决的阻塞缺口或 durability 降级使旧假设或保护失效时标记 `needs_reconcile`；从当前证据重规划，并通过 `plan` 产生新 revision。记录已经过期或被新任务替代时，用 `auto_dev.py abandon --reason ...` 归档，不能盲目续跑或直接覆盖 active run。

恢复时遵循权威顺序：最新明确用户决定 > 已确认 goal revision > 当前 plan revision > 已验证证据 > 登记的上下文文档 > 历史 session。目标、范围、规则或验收变化时输出 Requirement Diff 并重新确认；证据冲突且无法判定时打开 gap 并停止受影响节点。

## Checkpoint

- 计划初始化、计划变化、交付单元完成、外部等待、长时间工具调用前后和准备交接时写 checkpoint。
- checkpoint 至少包含节点、状态、摘要、证据、当前分支/HEAD 和下一最小动作；`done` 前运行 required proofs，阻塞时同时打开 gap、保留尝试证据并标明 owner 为 `agent / user / external`。
- 长时间、外部或不可逆动作遵循 [action-attribution.md](../control-plane/action-attribution.md)：先绑定当前节点，再建立和闭合 pending action；普通命令不记录 action phase。
- 进度服务显示的时间线必须与 `continuity.plan.nodes` 一致。Agent 在回执中引用 `goal_revision`、`plan_revision` 和 `current_node`，不另造一套里程碑名称。

## Git Archive Point

Git 存档点与普通 Plan checkpoint 语义独立，只有用户明确需要、跨大阶段、不可逆或发布风险命中时才创建。先运行 `auto_dev.py workspace checkpoint inspect`，取得明确 confirmation source 后再运行 `workspace checkpoint create`；不自动 commit、push、merge、配置 remote 或扩大 scope。

- `baseline` 产生 `💾 Auto Dev 存档点：开工保护`，用于开始改动前固定干净基线。
- `milestone` 与 proof-fresh 的 `archive` 产生 `💾 Auto Dev 存档点：成果固化`，用于固定已完成阶段或受控 archive commit。
- `workspace checkpoint list` 以真实 Git ref 为权威，并与 active、task、run receipt 的 `workspace_points` 交叉校验；`untracked`、`missing_ref` 或 `mismatched_ref` 必须保留为异常状态。
- `workspace rollback inspect --target ...` 只展示 task-owned scope、当前工作区改动、风险和预计策略；P0 不修改工作区，更不使用 `git reset --hard`。

Agent 原样转发 CLI `receipt`，不把 `💾` 存档点伪装为 Hook 回执。

## Impact Continuity

命中过 [impact-preservation.md](../control-plane/impact-preservation.md) 的任务在 Resume 时读取 `continuity_summary.impact`：`fresh` 才能沿用原影响判断；索引、scope、Plan revision 或 current node 漂移时标为 stale，并在继续风险改造前重新 inspect/record。空 CodeGraph 结果保留原 uncertainty，不得在恢复时改写成安全结论。

## Deep Debug Continuity

存在 `continuity.diagnostic` 时，Resume 恢复 reproduction gate、case-search IDs、active hypothesis、last verdict、resolution/recovery 和 next probe；不回放完整日志或所有 attempts。Handoff additive 携带同一 diagnostic，并在目标 workspace 按 Plan、scope、worktree/runtime 和 evidence refs 重算 freshness：stale observation 不再支撑 confirmed root cause，stale recovery 不再算 verified，`awaiting_confirmation` 继续等待原责任方。

历史 incident case 只保留为 candidate warning。Hook/UI 不搜索、生成、执行或 promotion；Agent 从 compact summary 继续下一条最小 probe。

## Workspace Policy Continuity

`status.workspace_policy` 为 configured/unavailable 时读取 [workspace-policy.md](../control-plane/workspace-policy.md)。Policy 是目标项目本地真相，不由 Handoff 覆盖；`continuity.policy_approvals` 可随 Task 保存，但 policy digest/revision、workspace、Plan revision 或 current node 变化都会使批准 stale。继续 approval path 前重新取得 exact-path 用户批准；forbidden path 永不转成 approval，sensitive evidence 不携带 secret value。

## Handoff

使用 `auto_dev.py handoff export` 导出按需 JSON，包含任务 ID、goal/plan revision、当前节点、连续性状态、需求回执、档位、能力回执、仓库基线、改动状态、验证引用、impact/preservation receipt、workspace policy approval history、未决缺口、下一动作和 durability；敏感文本由导出器脱敏。新环境使用 `handoff import` 后仍必须执行 strict reconcile。

Handoff 只写运行记录时不触发产品写入保护；同时修改产品文件时回到原执行档位。适用的运行诊断必须带上 `.auto-dev/runtime-diagnostics.json` 的位置与最后一次读取验证，不能只留“有日志”这类不可执行描述。若存在 dependency registry，`handoff export/import` 携带同一份脱敏 JSON 和当前 resolution lease；导入后仍需按当前环境执行 `auto_dev.py deps verify`。

## 完成条件

- Resume 没有重复已完成工作。
- Handoff 能让新 Agent 从证据继续，而非重新猜测。
- 进度 UI、`auto_dev.py status` 和最终回执引用同一个结构化节点状态。
- `task review` 已通过节点、gap、pending action、proof 和 strict 状态硬门；`finish passed` 还需要明确用户接受。
- 私密路径、凭据和原始敏感数据未写入交接记录。
- dependency registry 与当前 resolution lease 已随交接携带，且版本、环境或显式复验漂移已标记为待复验。
# Evidence continuity

Handoff carries proof attempts, latest projections, evidence links, typed
Milestone metadata, impact/preservation receipts and workspace Git point references additively. Import keeps
the same Plan/Task identity and recomputes freshness against the target
workspace. A `done` node without a valid proof is imported as
`needs_reconcile`/`legacy_unverified`; it is never silently treated as Green.
