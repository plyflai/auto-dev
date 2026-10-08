# Requirement Intake

所有产品代码、测试和配置写入共用本入口。目标是发现用户输入中的局限与遗漏，而不是机械复述。每个节点回执遵循 [receipt-catalog.md](../control-plane/receipt-catalog.md) 的中英双语格式。

## 0. 当前 Turn Gate

先运行 `project inspect`。若结果是 `git_setup_recommended`、`inside_parent_repository`、`migration_available` 或 `uninitialized`，先按 [pre-git-control.md](pre-git-control.md) 收敛 workspace 存储；这不是额外的产品确认，但在 Git/local control 建立前只允许调查，不能写产品文件。

在受管 Git 或 local No-Git workspace 中，只有当前 session 已显式引用 `$auto-dev` 时，`UserPromptSubmit` Hook 才记录 opaque `session_key + turn_id`；它不读取或推断用户提示词的产品语义。普通未启用 session 不创建 Intake 状态。Agent 必须在只读调查后使用 canonical CLI 将已启用 turn 评估为：

- `clear`：立即记录为已授权，不等待用户；适合目标、范围、验收和业务规则都已具体的工作。
- `clarify`：只提出 1-3 个会改变产品行为、范围或验收的用户决策；这些答案关闭决策后直接授权，不再追加一次重复确认。
- `deep`：显式展示推断、仓库事实、专家补全、候选盲区和决策包；所有决策收敛后等待一次 Requirement Baseline 确认。
- `project-discovery`：用于新项目、项目方向重塑、Capability/多 Outcome 启动；以多轮有依赖关系的决策包建立 Project Frame 和初始 Outcome Graph，最后等待一次项目级 Baseline 确认。

产品写入前必须先完成当前 turn 的 `intake assess`。Hook 只验证 gate 的结果；它不解释用户语言、不会替模型挑选深度。读代码、CodeGraph、测试、日志和外部事实调查在 gate 未授权时仍可执行。explicit pre-Git Hook marker 也会阻止写入，但它只是存储选择前的临时 gate，不替代 canonical Intake。

## 1. 需求重述

区分并展示：

- `目标`：用户真正需要的可观察结果。
- `当前方案`：用户提出的做法，可能是约束，也可能只是候选实现。
- `范围 / 非目标`：本轮改变与明确不改变的行为。
- `初始验收`：成功、相关失败路径和边界条件。

输出 `🧾 需求重述 / Requirement Restatement`。`clear` 路径将这份重述作为 route receipt 并继续；其他路径只询问会改变产品行为、范围或验收的缺口。

## 2. 仓库事实调查

用户确认当前理解后：

1. 代码理解、入口、调用链、影响面、复用点和邻近测试先按 [code-navigation.md](../control-plane/code-navigation.md) 使用 CodeGraph；若需要新工具或外部依赖，先对相关 capability 做一次紧凑 dependency resolve。
2. CodeGraph 不可用、未索引、结果 stale、为空或异常狭窄时，记录原因并做 1-2 个有意义的定向搜索或直接读取 fallback；dependency registry 无匹配时才进入模型/联网调查。
3. 检查相关配置、项目级日志层、最近提交和工作区状态；独立读取可并行，有依赖时保持串行并在行动前综合。
4. 把 `fact / technical` 留给 Agent 处理。
5. 用户给出具体实现方案时，用仓库事实复核它是否仍是达成目标的合适路径。
6. 若证据推翻需求假设，输出 Requirement Diff，再补增量问题。

调查只覆盖需求补盲与分档所需事实；核心证据足够时停止，不为润色、可选示例或次要背景重复检索，也不初始化 Team 控制面。

### 方案复核

方案复核属于仓库事实调查，不新增回执或确认门。只有用户给出具体方案，或仓库证据显示存在实质更合适的路径时才执行：

- `沿用`：用户方案与仓库事实一致，继续推进，不增加交互。
- `调整`：产品目标、范围和验收不变，但有证据支持更合适的技术路径。只有不引入待决定的持久设计承诺时，Agent 才直接采用，并在最终需求回执中说明调整和依据；用户已把原方案声明为硬约束，或替代路径命中下面的承诺防线时，转为 `挑战`。
- `挑战`：用户假设不成立，替代路径会改变产品行为、范围或验收，或者命中持久设计承诺且仍有真实取舍。把差异并入现有 Requirement Diff 和确认菜单，等待用户取舍。

复核依据必须来自目标调用链、现有模式、兼容边界、验证入口或可观察风险。代码风格偏好和泛泛的最佳实践不足以挑战用户方案。

### 持久设计承诺防线

DeepTalk、其他上游、历史方案和 Auto Dev 自己产生的 expert completion 都是输入来源，不因进入 Intake 就自动成为已批准需求。有上游准入结果时复用其候选状态，不重复完整发现；无论来源是谁，当前 Intake 都执行本节的最小承诺复核，阻止未经证明的持久设计承诺静默进入 baseline。

这里的持久设计承诺不按安全、权限、架构或界面等已知类别枚举，而按结构变化识别：新增长期存在的概念、状态、分支、依赖、配置、责任或重复操作；形成难撤销的数据、接口或流程约束；或显著收窄用户和运营者之后的选择。

这类内容进入当前 baseline 前，必须满足以下一条：

- 仓库事实、既有合同、物理约束或已发生故障证明它是当前目标必需，而且不存在需要用户承担的实质取舍；记录证据后可纳入。
- 它仍涉及收益、持续代价、最小替代或延后时机的真实取舍；状态保持 `pending`，并入现有 `clarify / deep` 菜单，由用户决定。
- 它只服务未来假设，当前不做不会破坏结果；标为 `deferred`，保持可见但不进入当前 Plan。

`clear` 只可把上面第一种有证据、无实质取舍的必要复杂度记为 `accepted`；不得把尚未证明必要或仍有实质取舍的 Agent 新增承诺直接批准。纯实现细节、现有模式内的局部技术选择和当前结果物理必需的最低复杂度仍由 Agent 自主收敛，不为了本防线增加无意义确认轮。执行层只消费已收敛 baseline，不在 Team Core 或 capability 中重复进行本审查。

### 运行诊断评估

只要本轮会新建或改变可运行的产品行为，就在仓库调查中按 [runtime-diagnostics.md](../control-plane/runtime-diagnostics.md) 评估现有项目级日志层和本次范围。结论只能是 `covered / augment / foundation / not_applicable`：前两者分别表示已有覆盖或在既有层补齐，`foundation` 表示需要建立或修复共享的诊断基础，`not_applicable` 只用于确实没有运行态行为的改动。

这是一项技术判断，不增加独立回执或确认门。日志存储、保留期、隐私、成本或外部服务会改变产品约束时，把需要用户取舍的部分并入既有 Requirement Diff 和最终需求回执；其余实现细节由 Agent 收敛。

## 3. Expert Requirement Review

自动选择 0-4 个与目标和仓库事实最相关的产品视角。只提出会改变用户可见行为、业务规则、范围或验收的高信号建议。`deep / project-discovery` 必须把这些建议显化为具体的 expert completion 和盲区候选，不能只在内部思考后静默写代码。

每项状态必须为：

- `accepted`：纳入本轮。
- `deferred`：后续处理。
- `excluded`：明确不做。
- `pending`：待用户决定，存在时不能进入最终回执。

没有高信号建议时记录“无”，不要制造专家问题。架构、测试、回滚、观测等交付保障不在这里扩展产品行为。

## 4. Requirement Diff

初次重述后，目标、范围、规则、验收或建议状态变化时只展示增量：

```text
🧾 Requirement Diff
- Added: ...
- Changed: ...
- Removed: ...
```

### Scope Amendment

文件路径扩展不等于每次都要重开需求。已声明目录内的工作不改 scope；相邻实现或测试路径可在 active task 上用 `task amend-scope --kind adjacent --reason ...` 追加并记录。只有新增 subsystem、公共 API / 配置 / schema / 数据或外部边界、改变验收，或会混入用户无关 dirty work 时，才先输出 Requirement Diff、获得确认，再用 `--kind requirement-diff --confirmation-source ...`。

这条区分很重要：scope 变化可能让原目标、验收和 proof 不再覆盖真实交付。记录轻量路径扩展保留连续性，Requirement Diff 则阻止静默扩大产品承诺。

### Absolute Baseline Contract

当工作是 fork、迁移、兼容、受监管流程，或用户明确给出“绝对不能偏离”的内容时，Intake 必须把这些内容收敛为 versioned `contract`，而不是只放在自然语言历史里。contract 至少包含一句 `mainline`；按风险补充 `hard_constraints`、`forbidden_moves`、`replacement_map` 和 `required_coverage`。每个 required coverage 必须声明它所需的 `evidence_kind`。

确认后的 contract 上升到 Project Frame；Outcome/Task/Plan 只继承并追加，不能静默收窄。改变其中任何业务边界、禁项、替换关系或 coverage，先输出 Requirement Diff 并获得确认，再生成新 hash。不要把“当前 Task 的窄验收”当成父项目的完整合同。

## 5. 最终需求回执

至少包含：目标、范围、非目标、兼容约束、成功与失败验收、专家建议决策、仓库事实、技术判断、运行诊断结论、`remaining_pending: none`。运行诊断适用时，写明 `covered / augment / foundation`、现有或拟采用的项目级日志层、持久化与 Agent 读取路径，以及是否存在需用户取舍的约束；`not_applicable` 说明没有运行态的原因。

方案复核命中 `调整` 或 `挑战` 时，同时记录用户原方案、最终采用路径、决定性仓库证据，以及产品目标、范围或验收是否变化。

`deep / project-discovery` 输出 `🧾 需求基线已确认 / Requirement Baseline Confirmed` 前等待用户确认。`clarify` 的用户答案会关闭同一份 baseline；`clear` 不等待。所有路径记录 Intake ID、baseline hash、来源 turn 和确认 turn；用户修订时重新打开唯一 baseline，不维护并行最终版。

### Canonical State Calls

```text
auto_dev.py intake assess --session-key ... --turn-id ... --depth clear|clarify|deep|project-discovery ...
auto_dev.py intake resolve --session-key ... --turn-id <later-user-turn> --intake-id ... --intake-revision ...
auto_dev.py intake confirm --session-key ... --turn-id <later-user-turn> --intake-id ... --intake-revision ...
```

可使用 `--contract-json '<object>'` 记录合同；`outcome add|set` 与 `start` 也支持同字段为子层追加约束。strict Task 的 Plan 使用 `coverage_ids`，其 outcome proof 使用 `evidence_kind + coverage_ids` 声明可核验的贡献。

CLI 只校验结构、revision 和确认时序；目标推断、专家补全、技术调查、问题优先级和交互文案仍由 Agent 负责。

## 完成条件

- 当前用户 turn 已被 `clear / clarify / deep / project-discovery` 正确分类，并且 gate 已授权。
- `clarify` 的 pending 决策已由用户答案收敛；`deep / project-discovery` 已在后续用户 turn 获得明确 Requirement Baseline 确认。
- 仓库事实已调查，技术选择没有甩给用户。
- 已触发的方案复核有仓库证据；需要用户取舍的变化已并入既有确认门。
- Agent 或上游新增的持久设计承诺已有当前必要性且无实质取舍的证据，或已收敛为 `pending / deferred / excluded`；`clear` 没有静默批准未证明或仍有取舍的承诺。
- 有运行态的范围已收敛运行诊断结论；会影响产品约束的诊断决策已并入最终回执。
- 专家需求建议全部收敛且无 `pending`。
- 成功、相关失败路径、边界与非目标明确。
