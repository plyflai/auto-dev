---
name: auto-dev
description: 需求补盲与风险驱动的软件开发交付。Use this skill when the user asks to build, fix, refactor, optimize, test, clean up, explain, resume, hand off, bootstrap, or adopt software work, including rolling Work packet planning and optional parallel workers. Product writes preserve a shared requirement-intake contract, then route to Direct execution or a Team Core that activates only evidence-backed capability packs. Prefer this skill for end-to-end product engineering; do not use it for unrelated general questions.
---

# auto-dev

> 先确认做对什么，再只启用交付它所需要的治理能力。

## 激活标识

进入入口或执行档位时输出：`🔥 auto-dev - [Requirement Intake / 需求澄清 | Quick Write / 快速写入 | Direct / 直接执行 | Team Core / 团队核心交付 | Read Only / 只读] 已激活 / Activated`

用户可见回执与等待规则统一遵循 [interaction-contract.md](references/control-plane/interaction-contract.md)。
Lifecycle Hook 的确定性回执统一遵循 [lifecycle-hooks.md](references/control-plane/lifecycle-hooks.md)，入口不自行拼接 Hook 文案。
所有节点名称的中英双语对照统一遵循 [receipt-catalog.md](references/control-plane/receipt-catalog.md)。

## 默认目标

- 保留用户输入背后的目标，同时主动发现局限、遗漏和错误假设。
- 用仓库事实补齐技术判断，只把产品结果与业务取舍交给用户。
- 未命中 Team 硬门槛时使用 Direct；命中后进入 Team Core。
- Team 只启用有风险证据支持的能力包，不把全套治理当成质量本身。
- 用最小充分验证证明结果；没有证据时不宣称完成。

## 唯一路由

1. 先读 [mode-index.md](references/mode-index.md)，区分只读、快速写入、恢复/交接与产品写入。
2. 代码导航、外部依赖、运行诊断、workspace policy 或受管动作命中时，进入 [Control Plane Router](references/control-plane/README.md)，只选当前工具/状态所需 leaf。代码理解、定位、影响面或测试面先按其 CodeGraph 分支执行；受管外部动作前满足 dependency lease 或 bounded preflight gate。
3. 先运行 `project inspect` 确认 Git/local workspace 状态，再进入 [Intake Router](references/intake/README.md)：`git_setup_recommended` 选 pre-Git，低风险一次性 patch 选 Quick Write，其他产品写入选 Requirement Intake。任一会写入受管 `.auto-dev` 的路径先从 Control Plane Router 选 control-plane language。先完成本 turn 的 `clear / clarify / deep / project-discovery` 评估：`clear` 可自主继续，其他路径只等待真实用户决策或 Requirement Baseline 确认。
4. Intake 已授权后进入 [Execution Router](references/execution/README.md)，独立选择 `Direct / Team Core`，并按回执中的运行诊断结论选路。
5. `Direct`：从 Execution Router 只选 Direct leaf，再从 [Verification Router](references/verification/README.md) 选普通 verification；运行诊断适用时，按 Direct leaf 从 Control Plane Router 追加 runtime diagnostics。交付单元完成后自动执行适用 proof；Team 才按 AI 判断增加可见 verification/release Milestone。
6. `Team Core`：从 Execution Router 选 Team Core 与 capability router，生成能力回执；再进入 [Team Capabilities Router](references/capabilities/README.md)，只读回执中 `enabled` 的 capability leaf。
7. Team 能力选定后，先建立 Root Policy Envelope（全局最低证据、停止条件、是否允许并行与 Integration barrier），再从 Intake Router 选 Outcome Contract，从 Execution Router 在普通 Execution Loop 与 Rolling Milestones 中选一个，并从 Verification Router 选普通 verification。Rolling Milestones 只有在当前 Milestone 的 Work packet DAG 编译后，才派生 packet 级 verification、review、merge policy 与 execution profile；`parallel-work` 只改变后续执行拓扑，不改变 Team Core 的单 Agent 路径。`status.workspace_policy` 为 configured/unavailable 或命中项目路径红线时，从 Control Plane Router 追加 workspace policy；运行诊断适用时追加 runtime diagnostics。
8. 只读模式从 Execution Router 选 Read Only；恢复或交接进入 [Continuity Router](references/continuity/README.md)。创建新执行焦点或从不相关旧工作切换时，从 Control Plane Router 选 State Transitions，用一次 `transition` 建立完整 ready 控制面并返回已验证 UI；相关反馈继续原 Task。进入 `review_ready` 前从 Verification Router 选 Product Review；用户说“更新新版 Auto Dev”“升级这个项目的 Auto Dev”或等价表达时，Agent 自己先运行零写入的 Legacy Upgrade inspect，再只为 apply 取得确认，不能要求用户记忆或输入 CLI；已有 `.auto-dev` 的 hierarchy upgrade 待处理时，从 Continuity Router 选 Legacy Upgrade；长任务命中连续性条件时，按 Resume/Handoff leaf 的 `plan / checkpoint / status` 契约执行。
9. 开始或记录真机、外部、长时间或不可逆动作前，从 Control Plane Router 选 Action Attribution。

## Team 能力包

能力名、leaf 映射和进入条件只在 [Team Capabilities Router](references/capabilities/README.md) 维护；本入口不复制能力清单。

## 全局不变量

- 用户输入可能片面；受治理产品写入必须有当前用户 turn 的 Intake classification，不能把流畅表达当成需求完整；`git_setup_recommended` 与 explicit pre-Git gate 只允许调查和存储选择，不能写产品文件；`clear` 不增加用户等待，`clarify / deep / project-discovery` 只在真实产品决策未闭合时等待；Quick Write 只按其独立低风险契约执行。
- 最小切口并保留现有改动；删除、替换、公共契约变化和不可逆动作需要明确证据与保护。
- 写产品代码前，先按仓库事实判断职责归属、复用点、依赖方向和可验证边界；保持职责内聚，不把新的独立职责继续堆进已经混杂或明显过大的文件，也不只为缩短文件制造无所有权的转发层、循环依赖或碎片模块。
- Quick Write 只能处理 Hook 判定通过的短 patch，不创建或修改 `.auto-dev` 控制面；不满足 Quick Write 边界时回到 Product Write。
- 调查事实与技术方案由 Agent 完成；业务规则、权限、金额、状态和验收取舍由用户决定。
- 交付审查不能静默增加产品行为；发现变化时输出 Requirement Diff 并重新确认。
- 对 fork、迁移、兼容或明确的绝对边界，先读 [outcome-contract.md](references/intake/outcome-contract.md) 的 Inherited Contract：每层只能追加，不能静默削弱父层主线、禁项、替换关系或 coverage；strict contract 的 stale/plan blocker 必须先处理。
- 有运行态的产品改动必须在最终需求回执中收敛运行诊断结论；具体接入、持久化与读取规则只在 [runtime-diagnostics.md](references/control-plane/runtime-diagnostics.md) 维护。
- 代码结构、调用链、影响面和邻近测试优先由 CodeGraph 提供；CodeGraph 可用且项目已索引时不得先进行大范围 raw `rg` / Read。
- CodeGraph 不覆盖运行时行为、外部依赖或项目专属经验；这些事实只有在真实验证后，才按 [project-memory.md](references/control-plane/project-memory.md) 的 Project Memory 契约记录。环境/路径和跨功能业务语言使用新的 `.auto-dev` profile/domain 真相源；旧 `.autodev/**` 只在显式迁移盘点中作为只读素材，绝不作为正常运行输入。
- 工具依赖只在首次选择、失败、环境变化、新版本复验或明确调查时解析；有效且 runtime-bound 的 resolution lease 内直接复用，不为每个动作重复读取。受管外部动作不得绕过 lease；candidate 只能通过 bounded preflight 生成新事实。
- 项目依赖配方与失败经验必须带有范围、证据、观察时间和版本/环境；不记录凭据，不把临时猜测写成 known-good。
- Team 能力选择必须列出启用、跳过、证据和预算；不能凭感觉加载全套，也不能静默省略已命中的能力。
- 能力包未启用时不读取其正文；一旦启用，包内标记为硬门的规则不可跳过。
- 默认不使用 Subagent；只有 `parallel-work` 被证据启用时才允许并行委派。
- `Direct` 不隐式创建 Subagent；`Team Core` 可以由一个主 Agent 完成，也可以在 Rolling Milestones 的 packet DAG 编译后启用 Multi-Agent。Multi-Agent 时主模型使用 worker lifecycle 准备隔离 worktree、生成 Context Capsule、捕获和应用 patch；模型选择与 Codex Subagent 创建仍由宿主负责，CLI 不伪造已完成的 worker 或 merge 结果。
- 连续两轮实现未恢复目标验证、同类发现重复两次、或预算耗尽时停止局部修补并重规划。

## 确定性运行记录

模型热路径需要当前决策时，优先请求 CLI 的显式 `agent-focus` 视图；它是完整状态判定后的只读摘要，不替代 full/compact 状态，也不改变任何写入门禁。遇到 blocker、迁移、审计、恢复或不确定性时，再按需读取 full 或目标详情。

需要本地可恢复记录时使用：

```text
python3 <skill-root>/scripts/auto_dev.py --help
```

Direct 与 Team 使用 Control Plane Router 中的同一 CLI Contract 和 `.auto-dev/` 本地运行记录：物理 `project` 之下可建立多个 `project-context`，每个上下文维护 Capability Map 和递归 Outcome Graph；Task 只归属一个 Outcome，Plan 只解释一个 Task 如何完成。每个 branch 只保留一个 Execution Focus，`focus` 的 View Focus 不得改变写入权限。`intake turn/assess/resolve/confirm` 是当前用户 turn 的需求状态真相源；`outcome / capability / activity` 记录层级、持续能力和受管 Quick Write。正常新建或切换 Execution Focus 使用 `transition`，一次提交旧焦点退出、新 Context/Outcome/Intake/Task/Plan、ready readback 与控制面 URL；`switch-superseded` 不为离开无关旧工作重验 stale proof。完成验证后先进入 `review_ready`，保留原 task、计划、proof 和选中投影；只有用户明确接受后才 `finish --status passed` 归档。相关新反馈用 `task resume` 继续原 task。`fix inspect/apply` 是异常控制面修复的受治理入口，先用 `fix inspect` 说明候选操作，取得用户确认后调用 `fix apply`，不允许直接编辑状态文件。`legacy-upgrade inspect/apply` 接手版本化项目控制面：显式 inspect 才会将旧 `.autodev` 已知素材以 digest-only candidate 列出，取得用户确认后按 revision、step 与 fingerprint 受保护地升级；旧 Proof 只通过列出的 `proof --revalidate` 目标真实复验，不得用普通 `migrate` 或直接编辑状态文件替代。底层 `start / plan / checkpoint / status / resume / handoff / finish / bootstrap` 保留为兼容、修复和高级入口，环境/领域事实使用 `environment / domain`，项目依赖使用 `deps`，人工进度页使用 `progress`。Plugin 的 Lifecycle Hooks 只通过 canonical CLI 恢复上下文并保护真相源。旧的 `runctl.py / dependency_manager.py / project_memory.py / progress_server.py` 仍是兼容入口，但新调用统一走 `auto_dev.py`。未初始化控制面的 Quick Write 保持无状态；受管 Quick Write 记录轻量 Activity，但不升级为 Task/Plan。CLI 只记录与校验事实，不替代模型的需求、风险和能力判断。

任何档位都不得用过程材料替代用户结果。连续性节点通过 Intake Router 中的 Outcome Contract 声明主结果并保存 append-only proof attempts；无法产出或验证时使用结构化 `blocked`，说明真实约束和下一步，不制造代码或完成叙事。需要当前 Milestone 的强制写前/写后 Git 保护时使用 `auto_dev.py workspace checkpoint protect`，再按受保护的 `inspect|create` 固化两点；创建必须显式 scoped、confirmation-bound，且不会由 Hook 自动完成。
