# Lifecycle Hooks

Plugin 使用一个动态 dispatcher 响应 Codex 生命周期事件。已有 managed Git/local workspace 且当前 branch 存在 `active / review_ready / selection_required` 任务状态时，新的 session 在 `SessionStart` 自动建立只读 resume activation，不需要用户再次输入 `$auto-dev`；没有可恢复任务的项目继续保持静默。用户显式引用 `$auto-dev` 的 managed workspace 仍会在 `PLUGIN_DATA` 建立短期 session activation marker；non-Git 新目录仍会进入 [pre-git-control.md](../intake/pre-git-control.md) 的短期 Project Discovery gate。Auto Dev 自身的 Plugin 源码目录是永久 self-target 排除项：Hook 和 CLI 都不得在其中创建或更新 `.auto-dev`，应从中立 workspace 或显式测试 fixture 驱动 Auto Dev。Project 存在但当前 branch（或 local execution context）没有 task 时，不恢复其他 branch 的任务。

## Event Routes

- `SessionStart(startup|resume|clear|compact)`：先用 branch-aware identity 检查是否存在可恢复任务；命中时自动建立当前 session 的 activation，再调用 compact strict status，恢复目标、revision、当前节点、下一动作、交付契约、漂移与阻塞。自动恢复只读运行态，不写 `.auto-dev`，也不抢 writer。回执中的 `session-role=writer-available|writer-held|observer` 表示当前 branch writer lease；首个 canonical `auto_dev.py` mutation 或产品写入才会 acquire/renew lease。新 session 接管后，旧 owner 的后续写入会被 Hook 拒绝为 observer。Deep Debug 存在时只附 profile/status、reproduction gate、case count、active hypothesis、last verdict、resolution/recovery freshness 与 next probe，不注入完整 observation history；若 Task 绑定 inherited contract，还注入短 `contract_capsule`（主线、少量硬约束/禁项/替换关系和当前 coverage），不回放整份 Intake 正文；复用或启动当前仓库专属的回环只读进度服务，启动参数固定为 `progress --repo-root <root> --port 0`，并把实际 URL 放入回执；多个候选时只注入 `task_selection_required` 和紧凑菜单数据。
- `UserPromptSubmit`：当前 session 已通过显式引用或 SessionStart 自动恢复时，带 turn identity 的 prompt 通过 canonical `intake turn` 记录 bounded pending turn（只保存 opaque session key 与 turn ID，不保存提示词正文），并受 branch writer lease 串行化；旧 owner 已被接管时只注入 observer/只读说明，不再写 intake turn。首次显式引用或自动恢复分别写入 `PLUGIN_DATA/session-activations`；没有 managed project/task 的普通 prompt 仍不创建 activation、不开 Intake、也不读取控制状态。strict inherited contract 额外只注入短 `mainline pulse`（合同、主线、锚点、当前节点和未完成 gate），不重复整份 delivery contract。它不做自然语言产品判断；模型必须先完成 `intake assess`，再写产品文件。若目录没有 Git/local control 但 prompt 明确引用 `$auto-dev`，Hook 在 `PLUGIN_DATA` 记录 pre-Git pending marker，注入 Git/local/只读选择，不保存 prompt 正文。没有可用 turn identity 时退回旧的 model / project revision / context key / task ID / state revision 去重恢复。
- `SessionStart` 在 Auto Dev Plugin 自身目录中只注入 `plugin_self_target` 保护回执，不读取项目状态、不启动进度服务，也不恢复 stale pre-Git marker；`UserPromptSubmit` 和 `SubagentStart` 在该目录保持静默。
- `SubagentStart`：仅在当前 session activation marker 存在且 Team 已启用 `parallel-work` 时，把目标、范围、验证、能力与当前节点注入子 Agent。
- `PreToolUse(Bash|apply_patch)`：未启用当前 session 时只保留直接修改 `.auto-dev/` 状态或使用兼容脚本执行 mutation 的防腐保护，普通产品工具调用静默放行；启用后再执行完整 gate。启用路径先阻止直接修改 `.auto-dev/` 状态；对 canonical `auto_dev.py` mutation 或产品写入，在常规 intake/policy/product gate 通过后 acquire/renew branch writer lease。另一个 session 在旧 mutation 的短暂 in-flight fence 内会收到 conflict；fence 结束后可接管，旧 owner 记录为 observer，后续写入 fail-closed。token-aware 分类不会把 `sed -n`、stderr 重定向或自然语言片段当写入。explicit pre-Git marker 存在时先拒绝产品写入；对当前 session 已观察到的 Git/local turn，所有产品写入再检查 Intake gate：`pending / awaiting_user / awaiting_confirmation` 都确定性拒绝，`authorized` 才进入 [workspace-policy.md](workspace-policy.md)、Quick Write 或 Task scope 规则。路径策略在 Quick Write 前执行；forbidden hard deny，approval 需要 fresh exact-path Task 批准，sensitive 需要加强 proof 与脱敏，启用项目规则后未知 Bash 写路径 fail-close。已 armed 的 `workspace checkpoint protect` 在 before point pending 或 invalid 时，会确定性拒绝业务产品写入；它不阻止 `.autodev`、`.codegraph`、`.conductor` 这类非状态 control metadata 的 `apply_patch`，但 `.auto-dev` 仍只能由 canonical CLI 写入。没有当前 active task 时，符合 [quick-write.md](../intake/quick-write.md) 的短 `apply_patch` 只在 Intake 已授权时放行，不能放行 Bash 写入或控制面写入。canonical `auto_dev.py` state mutation（包括 `project init|migrate`、`intake`、`project-context`、`outcome`、`capability`、`activity`、`focus`、`debug`、`memory case promote`、`fix apply`、`policy set|approve`、`workspace checkpoint protect|create` 和 `evidence link`）可用于恢复或更新控制面。
- 实际产品写入仍必须有当前 active task、没有 product-write blocker，并且 `apply_patch` 路径落在 planned scope。Rolling Graph 另要求当前执行焦点是 `work_packet` 或 `integration`，且显式产品路径落在该节点的 path-level `write_scope`；无法可靠解析路径的 Bash 不因此新增 blanket deny，最终 Integration diff reconciliation 继续兜底。采用 `historical-stale-completion-v1` 后，后续节点开发造成的历史 Green Proof stale 仍保留为 completion blocker，但不阻止当前 active 节点的范围内修复；升级后尚未真实复验、缺失/失败 Proof 和其他 strict blocker 继续阻止写入。
- Deep Debug 不新增“根因未知则禁止所有写入”的粗门：planned-scope 内的失败测试、最小脚本和 instrumentation 仍可写；真正的语义 gate 在 debug resolve/recovery 与 task review。strict inherited contract 的 `stale / plan_stale / plan_incomplete / unavailable` 会加入 blocker；coverage 声明 `write_gate=before_product_write` 且尚未 proof passed 时同样确定性拒绝产品写入。需要 `artifact_schema` 的 coverage 必须通过 `proof --evidence-file` 读取匹配 manifest，不能用任意成功命令替代。缺 coverage 的完成检查仍由 Plan/Proof/Review gate 处理。对直接可识别的 `adb`/Frida 外部动作，Hook 还要求已有当前节点的 node-bound pending action；Frida CLI、`frida-ps` 与项目 Python probe 还必须匹配有效 runtime-bound dependency lease，或匹配同一 pending action 的短时 preflight permit。其完整边界见 [action-attribution.md](action-attribution.md)。`review_ready` 明确拒绝产品写入并给出 `task resume` 恢复提示。

`plan_stale` is also a strict inherited-contract blocker: it means a Plan was authored against a different Task snapshot and must be revised before product writes resume.

## User-visible Receipts

每个非静默 Hook 结果都由 dispatcher 确定性生成一条中英双语 `🪝 Auto Dev Hook:` 回执；格式来自 [receipt-catalog.md](receipt-catalog.md)，Agent 不创作或改写回执内容。

- `SessionStart`：对自动恢复或显式启用的 session 产生回执 `session_startup / session_resume / session_clear / session_compact`，并附 active task、state revision、current node、当前项目控制面链接与 `session-role`；没有可恢复 task 的新 session 仍无输出。
- `SessionStart` 同时注入当前 Milestone 的 `node_kind`、验证摘要、latest proof freshness/attempt、条件式 Deep Debug 摘要、impact freshness/保留项/不确定性、workspace policy revision/rule/approval freshness、Git archive point 与 control-plane upgrade 状态；这些内容都来自同一 compact 状态投影。它只恢复和展示，不 apply migration、运行 revalidation、搜索 case、生成 hypothesis、决定 root cause、执行 probe/CodeGraph/长测试、写 memory/policy 或创建 Git ref。
- `UserPromptSubmit`：对显式启用或自动恢复的 session，带 turn identity 的新用户 turn 回执 `hook_activated | 需求澄清待分类 / Requirement intake awaiting classification`；接管后的旧 session 回执仍带 `session-role=observer` 且不写 intake。无 turn identity 时才沿用 `hook_activated / model_changed / active_task_changed / control_state_changed` 的去重路径。没有可恢复任务且未显式启用的 session 仍静默。
- `UserPromptSubmit` 的 explicit pre-Git 路径回执 `pre_git_intake_pending`；`PLUGIN_DATA` 不可写时回执 `pre_git_guard_unavailable` 并明确降级为只读，不能把它写成已受保护。
- managed session activation 无法写入 `PLUGIN_DATA` 时回执 `session_activation_unavailable`，不得把当前 session 写成已受保护。
- `SubagentStart`：仅在 `parallel-work` 已启用并实际注入契约时，回执 `subagent_[agent_type]`。
- status 读取失败：回执 `status_unavailable` 与事件名，同时注入确定性的恢复指令。
- `PreToolUse` 拒绝：回执 `pre_tool_use_denied` 与拒绝原因。

同一条回执同时通过顶层 `systemMessage` 交给宿主，并写入 `additionalContext`，要求 Agent 在其他用户可见文本之前原样转发一次后继续任务。没有 active control plane、当前 session 未显式启用、状态未变化、未启用 `parallel-work` 或未命中保护规则时保持静默。

## Boundaries

- Hook 只做确定性读取、bounded turn 记录、机械 gate、路由、保护以及本地只读进度服务的复用/启动；不判断用户提示词的产品语义，不自动 checkpoint、review、finish 或批准外部动作。
- Hook 不执行 `codegraph status/impact/affected`；只消费 `impact record` 已保存并由 status 重算的投影。stale impact 在 P1 是可见风险，不自动扩成全局写门禁。
- Hook 不执行 `memory case search`、不生成 hypothesis、不写 observation、不判 root cause/recovery、不自动 promotion；这些都由 Agent 通过 canonical CLI 与实际 evidence 完成。
- Workspace archive point 只能由 Agent 通过 `auto_dev.py workspace checkpoint create` 显式调用；Hook 不创建 checkpoint、tag 或 commit，也不执行 pytest/Playwright/后端长测试。
- `auto_dev.py status --compact --strict` 是恢复上下文的唯一机器入口；Hook 不维护第二套项目状态。
- Session marker、session activation marker 与 branch-scoped session writer lease 只保存在 `PLUGIN_DATA`：前者包含 session、model、project revision、context key、task ID 和 state revision，activation 只记录 schema、来源和时间，writer lease 只记录脱敏 session fingerprint、branch key、task/revision、短期 expiry、in-flight fence 与最近 superseded fingerprints；都不复制任务正文或工具输出。它们是可丢弃的运行时缓存，不是任务选择或 Plan 真相源。explicit pre-Git marker 也只保存 workspace fingerprint、pending turn 与短期状态；它在用户选择 `project init --mode git|local` 后被 Git/local control 面替代，不能成为第二份 Task/Plan 真相源。进度服务的 URL/PID 注册也只存于 `PLUGIN_DATA/progress-servers`（或没有该目录时的系统临时目录），并通过 `/api/health` 校验当前仓库身份；它是可丢弃的运行时发现缓存，不是控制面状态。
- Hook 输出保持紧凑且不包含凭据；控制面不可读时注入恢复指令，不用聊天记忆猜测状态。
- 同一事件的有序动作放在 dispatcher 内执行，避免依赖 Codex 对多个 matching Hook 的并发顺序。
