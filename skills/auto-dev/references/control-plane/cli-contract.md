# CLI Contract

## Level And Front Door

`auto-dev` 是 `L3 control-plane CLI`。唯一 canonical front door 是：

```text
python3 <skill-root>/scripts/auto_dev.py <command> [arguments]
```

命令面：

- 项目与任务控制：`project inspect|init|migrate`、`project-context list|show|adopt|set|select`、`task list|select|pause|amend-scope|attribute|review|resume`
- 需求与层级控制：`intake turn|status|assess|resolve|confirm|reopen|show`、`outcome list|show|add|set|link|move`、`capability list|add|set`、`activity list|record`、`focus show|set`
- 控制面修复：`fix inspect|apply`、`legacy-upgrade inspect|apply`

- 运行控制：`start / escalate / capabilities / event / evidence link / plan / milestone frontier|compile|execution|handoff|integration|review|worker / proof / checkpoint / diagnostics / finish / abandon / handoff / recover / migrate / bootstrap / refresh / resume / status`
- 条件式影响保护：`impact inspect|record`。inspect 零控制面副作用；record 重新执行 bounded CodeGraph JSON 检查，要求当前 node、state revision、至少一项 preservation 和 verification action，并将 receipt 追加到当前 Task。
- 条件式项目路径策略：`policy inspect|set|approve`。inspect 零副作用；set 使用独立 policy revision、用户确认、锁、原子写与 readback；approve 使用 current policy/state/node 与 exact paths，把一次性批准追加到当前 Task。详见 [workspace-policy.md](workspace-policy.md)。
- 条件式 Deep Debug：`debug inspect|begin|case-search bind|reproduction record|hypothesis add|observe|resolve|recovery`。除 inspect 外均要求 current Team Task/node/state revision；命令只记录语义投影和 evidence refs，不执行 probe。详见 [capability-debug-observability.md](../capabilities/capability-debug-observability.md)。
- 项目案例：`memory case search|promote`。search 零写入；promote 要求 review-ready source Task、fresh diagnostic/recovery、Task/Memory 双 revision 与用户 confirmation，并写入同一 `project-memory.json`。
- 环境与领域事实：`environment inspect|init|set`、`domain inspect|set`。inspect 零写入；init/set 使用 Project Memory revision、confirmation source、lock、原子替换和 readback，生成 `.auto-dev/path.md` 与 `.auto-dev/project-domain.md` 人读投影。投影不是可编辑真相源，旧 `.autodev/**` 不能作为正常运行输入。
- Workspace safety：`workspace checkpoint inspect|protect|create|list`、`workspace rollback inspect`。inspect/list/rollback inspect 无副作用；`protect --node <current-node> [--scope ...] --confirmation-source ...` 是 opt-in 的单 Milestone 双点事务，持久保存 scope、待创建的 before/after 状态和确认来源。它本身不改 Git；Hook 仅在 before pending 时拒绝产品写入。受保护 `baseline` 可在明确 confirmation 下提交该精确业务 scope 的既有 dirty 改动，受保护 `archive` 只要求该 node 的 fresh proof；完成检查拒绝 pending、missing 或 mismatched protection ref。普通 create 继续拒绝 staged、用户基线、敏感路径和未覆盖 dirty changes。`.auto-dev`、`.autodev`、`.codegraph`、`.conductor` 是保留的 control metadata，不进入 checkpoint dirty/staged/user-owned/scope 判断，也不会被 checkpoint 纳入提交；敏感路径按精确目录、文件名和证书扩展名判断，不因业务文件名包含 `credential`、`token` 或 `secret` 而误拒绝。`baseline` 回传 `💾 Auto Dev 存档点：开工保护`，`milestone/archive` 回传 `💾 Auto Dev 存档点：成果固化`；`list` 用真实 Git ref 与 active/task/run receipt 交叉校验并暴露 `recorded / untracked / missing_ref / mismatched_ref`。P0 只预演 rollback，不修改工作区。
- 依赖配方：`deps <record|list|show|resolve|gate|preflight|attempt|verify|review>`
- 人工进度页：`progress --repo-root ... --port 0`；`0` 是默认值，由系统分配空闲本地端口，只有需要固定地址时才显式覆盖。
- 发现与兼容：`help [command] / version`

`runctl.py`、`dependency_manager.py`、`project_memory.py` 和 `progress_server.py` 保留为兼容入口与内部实现。新文档、Hook 和 Agent 调用不得继续新增这些入口的直接依赖。

## Read And Write Boundary

查询命令必须无副作用：`project inspect`、`task list`、`bootstrap inspect`、`fix inspect`、`legacy-upgrade inspect`、`milestone frontier|compile inspect|execution inspect|integration inspect|review inspect|worker inspect|worker finalize inspect`、`impact inspect`、`policy inspect`、`debug inspect`、`memory case search`、`status`、`resume`、`workspace checkpoint inspect|list` 和 `workspace rollback inspect` 不创建 `.auto-dev/`、不修改 Git `info/exclude`、不更新时间。`workspace checkpoint protect|create`、`milestone execution select`、`worker apply|finalize apply` 是明确 mutation。`status --strict` 与 `resume` 在控制面不存在或状态不是 `ready` 时输出可解析状态并退出 `2`。

依赖命令中的 `list / show / review / verify / gate` 只读；`resolve` 仅在显式传入 `--write-lease` 时写 lease。`preflight open / close` 是显式 mutation：前者写短时 permit，后者记录结果、按请求 promotion 并关闭 permit。`progress` 只投影 compact 状态与已有 dependency registry / lease / attempt 的只读视图，不是真相源。

Mutation 命令必须显式命名。`plan` 要求当前 `--base-revision`；`proof`、`checkpoint` 和 `evidence link` 同时要求当前 `--plan-revision` 与 `--state-revision`。对于 contract coverage 声明的 `artifact_schema`，`proof` 还必须提供 `--evidence-file`，由 CLI 只读校验 manifest 的 schema、coverage、source_ref 和 entries；命令 exit 0 不能单独冒充 parity 证据。普通 `proof` 只接受 active node；`proof --revalidate` 只接受 `legacy-upgrade inspect` 明确列出的 selected Task 已完成节点，追加真实 attempt，不重开或重编号 Plan。`event --phase` 必须携带与当前可执行节点一致的 `--node`，并将该归属写入 pending action 和事件；不能用 event 创建计划进度。`evidence link` 只为当前 task 中已闭合的历史 action 追加到当前节点的 `partial / failed / rejected` supporting-evidence 链接，不改写来源事件。无计划的一次性 Direct 使用 `--node run --plan-revision 0`；其 run-level outcome proof 是 `task review` 的必要条件。`task review` 需要当前 state revision、结果、验证和风险，写入 `review_ready` 但保留 selected projection；相关反馈只能由 `task resume`（state revision、原因、确认来源）恢复。`finish --status passed` 只接受 `review_ready`，以 review evidence 归档，并要求 `--confirmation-source` 证明用户明确接受。

Rolling Worker 的 `prepare` 只创建 worktree 并进入 `dispatch_required`；`worker bind` 记录真实 executor ref 后进入 `running`，或用具体原因进入 `dispatch_blocked`。`capture` 只接受 `running`。`milestone handoff take` 只转移 Integration owner，不允许借此重新选择 lane。Proof recipe 的 `cwd / inputs / observed_paths / preflight_argv` 都是结构化字段；显式 preflight 在隔离 worktree 中运行，失败时 compile 不写状态。

`fix apply` 是特权但受治理的控制面事务：operation registry 支持恢复错误归档任务、重建选中投影，以及按 upgrade manifest/fingerprint 回滚无完成审计的中断升级。任务修复要求 task/project revision，升级恢复要求 manifest digest/current fingerprint；二者都要求原因、确认来源、自动备份、审计记录与状态 readback，且不能直接编辑 goal、acceptance、scope、proof 或产品文件。`legacy-upgrade apply` 只接受刚刚 `inspect` 返回的 project/active revision、upgrade version、完整 step 集合和 fingerprint，以及用户确认来源与原因；它备份所有受影响文件、失败自动回滚、保留历史 `runs/`、写入升级审计并 readback。

`task amend-scope` 只追加路径；`requirement-diff` kind 必须有确认来源。冲突退出非零，不得自动改用最新 revision 或静默覆盖。`plan` 要求每个新节点带 Outcome Contract，且不能把已有 active/planned 节点直接改成 `done`；接管前已完成的历史节点必须带独立的 `historical_completion`、证据和确认来源。根节点顺序被规范为连续主里程碑 `M<n>`，子编号从 `parent_id` 推导；稳定 `id` 不参与编号。`proof` 使用参数数组实际执行节点声明的具名验证，保存退出码、输出哈希、HEAD 与工作区状态；`checkpoint done` 只接受当前 outcome 对应的全部成功 proof。`checkpoint blocked` 不要求成功 proof，但必须登记 blocking gap 与真实尝试证据。已完成或已替代节点的编号发生变化时，必须提供 `--numbering-change-confirmation`。具体外部动作顺序、遗留证据和 Hook 边界见 [action-attribution.md](action-attribution.md)。

普通 E2E 可在 `proof --evidence-file` 传入 `auto-dev/e2e-evidence/v1` manifest，绑定用户流程、环境和页面/数据/系统三层摘要；`task review` 只投影 fresh、passed 的 E2E 证据。

Release 节点可在同一参数传入 `auto-dev/release-evidence/v1` manifest；CLI 仅在 Team Task 已启用 `release` 且当前 active node 为 `node_kind=release` 时接受，保存环境、版本、健康、关键用户流程、回退和未验证边界。`partial / blocked / rolled_back` 不能成为 Green proof，manifest 变化会使 Proof stale；该参数不执行部署，也不扩大 deploy/push/auth 权限。

`measured_improvement` Outcome 可在同一参数传入 `auto-dev/performance-evidence/v1` manifest。baseline attempt 至少包含两次样本并返回 `status=recorded`，不会完成 Outcome；comparison 必须引用同一 Proof 的 recorded baseline，并匹配 hypothesis、metric、unit、direction、target、workload、environment 与 noise tolerance。只有目标达成且改善超过噪声才返回 Green；两个 manifest 任一变化都会使 comparison stale。CLI 不提供 benchmark runner。

`impact record` 只接受当前 active/blocked Plan node 与当前 state revision；preservation/verification 不能为空。它复跑 inspect 后追加 receipt，零依赖信号必须显式记录 uncertainty；status/Handoff 只读投影并按 CodeGraph index、scope、Plan revision 与 current node 重算 freshness。详见 [impact-preservation.md](impact-preservation.md)。

Deep Debug 的 failed proof 可以作为 fresh Red observation，但不能成为 Green outcome proof。`debug observe` 必须引用当前 Task 中 context-fresh 的 proof attempt 或 evidence link；`root_cause_confirmed` 需要 fresh confirmed observation，`recovery=verified` 需要 fresh passing proof 和 probe cleanup。`no_defect_observed` 还要求 Debug 开始后的 HEAD/worktree baseline 未改变。Handoff 携带 diagnostic 并在目标 workspace 重算 freshness；stale observation 不再支撑 confirmed resolution。

## Machine Contract

- 成功结果写 stdout；运行控制与依赖热路径使用 JSON。workspace checkpoint protect 返回 protection id、状态投影与 `💾 Auto Dev 存档保护` receipt；create 同时返回包含完整 Git `object` 的 `checkpoint` metadata，以及带 `commit=<8 位短 hash>` 的 `receipt`。compact status 以 `workspace_checkpoint_nodes` 将同源 before/after 点绑定到 Plan node。每次 create 成功后 Agent 必须把 `💾` receipt 原样输出到聊天，不能只留在工具 JSON 中，也不与 Hook 的 `🪝` receipt 混用。
- 诊断写 stderr；参数错误退出 `2`，状态未 ready 的 strict read 退出 `2`，运行或校验失败退出非零。
- 默认输出保持紧凑；完整状态只在明确调用非 compact `status` 时返回，长日志不写入控制面输出。
- front door 使用参数数组调用内部脚本，不通过 `shell=True` 重拼模型输入。
- `task review` 可通过互斥的 `--product-review-file` 或 `--product-review-json` 写入产品验收摘要；stdout 同时返回结构化 `product_review` 和以 `💡` 开头的 `product_receipt`。旧调用未提供摘要时保持兼容，并明确提示摘要缺失。

## State Safety

- `.auto-dev/project.json` 是物理 Control Root 的 Project/Branch/Task 索引；`projects/<context-id>/frame.json` 保存 Managed Project Frame，子目录保存 Capability、Outcome 与 Intake；`tasks/<task-id>.json` 保存任务 receipt；`.auto-dev/active.json` 是当前 branch 的兼容 active 投影。UI、Hook 和最终回执都通过 branch-aware resolver 读取同一任务。
- Outcome 是唯一允许递归的产品对象，存为同一 Managed Project Context 内的 DAG；Task 不能包含 Task，只引用一个 primary Outcome；Plan 只属于一个 Task。生成的 `unlinked` Outcome 可以收纳尚未建立产品直觉的有界工作，不假装理解整个产品。
- `intake turn` 只接受 opaque session key 与 turn ID。`assess` 记录语义分类，`resolve / confirm` 绑定后续用户 turn 和 Intake revision；Hook 只根据 gate 是否授权允许产品写入。
- View Focus 保存在 session scoped `view-focus/`，只影响 CLI/UI 浏览；Execution Focus 仍是当前 branch 的 selected Task。改变 View Focus 不得改写 Task 选择或产品文件。
- 跨仓库信息只能作为 Managed Project Frame 中的 soft external references 保存，包含版本、契约、owner、证据时间和状态；不得写入、读取为真相源或链接到另一个仓库的 `.auto-dev` 状态。
- `project inspect` 是无 Git 目录也可执行的只读调查；`git_setup_recommended` 默认推荐 `project init --mode git`，但必须有用户确认，且不自动 commit、push 或配置 remote。用户明确拒绝或无法使用 Git 时可执行 `project init --mode local`；它使用同一控制面但输出 `workspace.vcs: none`，Task 必须有 scope，Git/branch/diff 证据均不适用。local control 后来接入 Git 时先返回 `migration_available`，再以 revision 和确认来源执行 `project migrate`。
- 每个 branch 同时最多一个当前 task。`active` 和 `review_ready` 都保持 selected projection；暂停 task 不能与新 active task 并存，必须 select、resume 或明确归档后才可新建。branch、HEAD 或 task revision 不匹配时拒绝 mutation，不猜测其他任务。
- 写入使用原子替换、备份和单写锁；caller revision 与实际状态冲突时拒绝。Proof history、diagnostic observations 和 impact receipts 都是 append-only；latest projection 只消费或展示重算后的 freshness，Plan node 的 `node_kind`、verification metadata、proof/evidence/workspace/impact/diagnostic refs 均 additive round-trip。Project Memory 另用 `memory_revision` 和 registry lock 防止 dependency/gotcha/case 并发覆盖。
- `recover / migrate / handoff / abandon / finish` 明确处理恢复、兼容、交接和终态，不由普通 read 命令隐式执行。
- 旧兼容入口不能维护第二套状态或绕过相同校验。

## Verification

```text
bash <skill-root>/scripts/contracts/cli-contract-test.sh
bash <skill-root>/scripts/contracts/project-control-contract-test.sh
bash <skill-root>/scripts/contracts/runctl-selftest.sh
bash <skill-root>/scripts/contracts/plan-numbering-contract-test.sh
bash <skill-root>/scripts/contracts/outcome-contract-test.sh
bash <skill-root>/scripts/contracts/project-memory-contract-test.sh
bash <skill-root>/scripts/contracts/progress-server-contract-test.sh
```

CLI contract test 至少证明：front door 可发现、跨 cwd 工作、所有 dependency read 命令零文件变化、strict 状态可判定、checkpoint revision 必填、失败的 dependency mutation 不留初始化产物、兼容命名空间可达。
