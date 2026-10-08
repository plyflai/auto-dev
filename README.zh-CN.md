# Auto Dev

**你的赛博开发团队。**

**从一句话的 Demo，走向持续迭代、可验证交付的大项目。**

[English](README.md) | **简体中文**

[![测试](https://github.com/plyflai/auto-dev/actions/workflows/ci.yml/badge.svg)](https://github.com/plyflai/auto-dev/actions/workflows/ci.yml)
[![许可证：MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![版本](https://img.shields.io/github/v/release/plyflai/auto-dev)](https://github.com/plyflai/auto-dev/releases/latest)

[适合谁使用](#适合谁使用) · [完整能力清单](#完整能力清单) · [安装](#安装)

一个跑通的 Demo，能让想法变得具体。要把它做成稳定、能够持续发展的项目，还需要打磨需求、协调改动、排查问题、验证每次迭代，并让已有决策在后续开发中持续生效。

**Auto Dev 把专业开发团队的工作方式带给你的编程 Agent。** 从你的想法出发，帮你澄清、细分和打磨需求，把需求转化为可执行的迭代，再组织实现、验证与交付。你把握方向，Auto Dev 把开发组织起来。

Auto Dev 是一个 Codex 插件，包含 Skill、生命周期 Hooks、本地 Python 命令行工具（CLI）和只读进度页面。可选的 [CodeGraph](https://github.com/colbymchenry/codegraph) 集成提供代码导航与影响分析。工作流指令和面向用户的运行记录默认以简体中文为主；中英文 README 包含相同的能力说明与使用限制。

## 适合谁使用

| 你的开发经验 | Auto Dev 如何帮助你 |
| --- | --- |
| **完全不懂代码** | 用自己的语言描述产品。Auto Dev 帮你发现需求遗漏、说明需要决定的事项、拆解工作，并给出你能检查的交付结果。 |
| **懂一部分开发** | 将已有知识串成完整开发流程，在项目变大时获得架构、排障、测试和发布准备方面的支持。 |
| **专业开发者** | 用统一工作流组织复杂工程任务，覆盖渐进重构、契约变化、深度排障、性能验证、并行协作和长周期项目的持续开发。 |

**产品梳理、架构规划、代码实现、测试验证、问题排查、团队协作与交付，都围绕同一个项目目标展开。** 小改动可以保持轻量，大项目可以按需使用下面的完整能力体系。

## 工作流如何适应任务

Auto Dev 先调查仓库，补齐影响结果的需求缺口，再选择执行路径：

| 路径 | 适用任务 | 执行方式 |
| --- | --- | --- |
| **Quick Write：快速写入** | 对已有文本文件做范围明确、风险低的小补丁 | 完成修改并执行针对性验证，不创建 Task 或 Plan。 |
| **Direct：直接执行** | 目标集中的功能实现或修复 | 跟踪用户要求的交付结果，以及证明结果所需的验证。 |
| **Team Core：团队核心交付** | 有证据表明存在架构、共享契约、集成或其他交付风险的任务 | 启用对应能力；有依据时采用滚动工作包和可选的并行执行者。 |

执行路径由任务和仓库证据决定，不要求必须使用多个 Agent。Team Core 可以由单个 Agent 完成。并行工作需要宿主支持，并在工作流中明确选用。具体条件见 [Quick Write 边界](skills/auto-dev/references/intake/quick-write.md)和 [Direct/Team 路由](skills/auto-dev/references/execution/execution-router.md)。

受管任务完成实现后会执行验证，再进入 `review_ready`（待审查）状态。最终验收前，由你检查交付结果。工作中断后，Auto Dev 可以从已保存的任务状态继续。

## 完整能力清单

以下清单覆盖当前版本的主要产品与工程能力。Skill 指导 Agent 执行工作，CLI 保存项目状态与证据，Hooks 执行受支持的生命周期检查。具体能力按任务与风险启用。

**按需启用的 7 个 Team 能力包：** `architecture`、`data-contract`、`debug-observability`、`gui`、`release`、`parallel-work`、`compliance`。详见[能力选择规则](skills/auto-dev/references/execution/capability-router.md)。

GUI 验证使用可用的浏览器或桌面执行工具；性能验证复用项目 benchmark；部署调用已有发布流程；多 Agent 执行需要宿主支持。CodeGraph 自动影响分析需要单独安装工具并建立有效索引。

### 1. 需求与产品定义

| 能力 | 具体工作 |
| --- | --- |
| [项目发现](skills/auto-dev/references/intake/requirement-intake.md) | 从初步想法梳理目标、使用场景、项目范围、能力边界与分阶段成果。 |
| [分层需求澄清](skills/auto-dev/references/intake/requirement-intake.md) | 按需求清晰度选择直接推进、关键追问、深度打磨或项目级发现，解决会影响结果的缺口。 |
| [专家视角补盲](skills/auto-dev/references/intake/requirement-intake.md) | 结合仓库事实提出高价值建议，明确采纳、延期、排除和待决定项。 |
| [验收与变更管理](skills/auto-dev/references/intake/outcome-contract.md) | 定义成功、失败和边界场景；展示需求增量，维护范围、非目标和不可偏离的约束。 |

### 2. 项目组织与迭代规划

| 能力 | 具体工作 |
| --- | --- |
| [项目层级建模](skills/auto-dev/references/intake/requirement-intake.md) | 组织项目上下文、长期能力、递归成果目标、任务和计划，避免把整个项目塞进一个无限任务。 |
| [按风险选择流程](skills/auto-dev/references/mode-index.md) | 支持只读调查、Quick Write、Direct 和 Team Core，按任务证据选择所需流程。 |
| [滚动里程碑](skills/auto-dev/references/execution/rolling-milestones.md) | 远期保留目标与验收，临近执行时再根据最新仓库事实细化工作包。 |
| [依赖与执行顺序](skills/auto-dev/references/execution/rolling-milestones.md) | 用有向无环图组织里程碑和工作包，明确输入、输出、写入范围、验收与集成节点。 |
| [任务与焦点管理](skills/auto-dev/references/control-plane/state-transitions.md) | 选择、暂停、恢复、切换或结束任务；区分查看对象与实际执行目标，并记录小改动活动。 |
| [阻塞与重规划](skills/auto-dev/references/execution/capability-router.md) | 记录缺口、责任方和下一步；重复失败或预算耗尽时调整策略，保留已有结果。 |

### 3. 代码理解、架构与实现

| 能力 | 具体工作 |
| --- | --- |
| [仓库与调用链调查](skills/auto-dev/references/control-plane/code-navigation.md) | 定位入口、符号、调用方、依赖和邻近测试；可用时优先 CodeGraph，否则使用定向搜索和源码阅读。 |
| [功能开发与维护](skills/auto-dev/references/execution/direct.md) | 引导 Agent 完成功能实现、缺陷修复、重构、优化、测试补充和代码清理。 |
| [架构边界与渐进重构](skills/auto-dev/references/capabilities/capability-architecture.md) | 梳理职责、模块、共享抽象、接口和跨平台边界，按可验证阶段迁移调用方并保留兼容路径。 |
| [影响分析与行为保留](skills/auto-dev/references/control-plane/impact-preservation.md) | 通过 CodeGraph 分析受影响符号和测试，记录必须保留的行为、验证动作及未知影响。 |

### 4. 数据、接口与安全

| 能力 | 具体工作 |
| --- | --- |
| [数据与接口契约](skills/auto-dev/references/capabilities/capability-data-contract.md) | 管理 Schema、公共 API、协议和配置变化，明确生产者、消费者、版本与错误语义。 |
| [数据迁移与兼容](skills/auto-dev/references/capabilities/capability-data-contract.md) | 规划扩展、迁移和收缩顺序，验证代表性数据、备份、幂等、重试、部分失败与回滚路径。 |
| [权限、安全与隐私检查](skills/auto-dev/references/capabilities/capability-compliance.md) | 围绕认证、权限、支付和敏感数据检查信任边界，验证允许、拒绝、越权、重放和审计路径。 |
| [工作区路径策略](skills/auto-dev/references/control-plane/workspace-policy.md) | 配置禁止修改、逐次批准和敏感路径；受支持的 Hooks 根据当前任务与策略检查写入。 |

### 5. 测试、验证与验收

| 能力 | 具体工作 |
| --- | --- |
| [针对性工程验证](skills/auto-dev/references/verification/verification.md) | 依据改动选择项目已有的测试、构建、类型检查或运行检查，在实现后执行适用验证。 |
| [可追溯的验证记录](skills/auto-dev/references/verification/verification.md) | 记录验证命令、结果和失败尝试，将证据关联到目标与计划，并在相关代码或环境变化后要求复验。 |
| [端到端与界面验证](skills/auto-dev/references/capabilities/capability-gui.md) | 检查真实用户流程、页面状态、错误反馈、布局、响应式表现和数据交互；保存截图及相关控制台、网络证据。 |
| [性能改进验证](skills/auto-dev/references/verification/performance-verification.md) | 复用项目 benchmark，在相同环境和工作量下多次比较延迟、吞吐、资源占用或构建等指标，区分改善与噪声。 |
| [集成与里程碑审查](skills/auto-dev/references/execution/rolling-milestones.md) | 检查工作包合并后的整体行为、变更范围、契约覆盖和验证结果，再决定里程碑是否可接受。 |
| [面向用户的产品验收](skills/auto-dev/references/verification/product-review.md) | 用产品语言说明完成内容、用户变化、测试入口、操作步骤与预期结果，保留未验证项并等待最终验收。 |

### 6. 排障与可观测性

| 能力 | 具体工作 |
| --- | --- |
| [日志与运行诊断](skills/auto-dev/references/control-plane/runtime-diagnostics.md) | 检查并复用或补齐项目日志层，记录关键事件、关联 ID、错误、保存位置和 Agent 可读取的入口。 |
| [系统性问题复现](skills/auto-dev/references/capabilities/capability-debug-observability.md) | 按问题复杂度选择标准或深度排障，保存最小复现、原始路径及不稳定问题的运行次数和失败率。 |
| [假设与根因调查](skills/auto-dev/references/capabilities/capability-debug-observability.md) | 提出可证伪假设，用探针和观测比较预期与实际，记录确认、排除或证据不足的结论。 |
| [修复后的恢复验证](skills/auto-dev/references/capabilities/capability-debug-observability.md) | 复测最小复现、原始问题路径和适用回归，清理临时探针，记录恢复成功、失败或等待确认。 |

### 7. 工具依赖与项目记忆

| 能力 | 具体工作 |
| --- | --- |
| [依赖配方与版本记录](skills/auto-dev/references/control-plane/project-memory.md) | 保存工具用途、版本组合、运行条件、调用方式和验证证据，区分可用、不可用、首选与备选方案。 |
| [依赖复用与重新验证](skills/auto-dev/references/control-plane/project-memory.md) | 复用已验证配方；工具首次选择、失败、环境漂移或升级时，通过有限试运行形成新证据。 |
| [环境与运行入口](skills/auto-dev/references/control-plane/project-memory.md) | 记录已确认的工作目录、主机、服务端点、运行与观测入口、GUI 执行器等环境事实。 |
| [业务语言与项目经验](skills/auto-dev/references/control-plane/project-memory.md) | 保存稳定的业务术语、不变量、待消歧概念、耐久决策和项目特有的使用陷阱。 |
| [可搜索的故障案例](skills/auto-dev/references/capabilities/capability-debug-observability.md) | 在根因与恢复经过验证、用户确认后沉淀故障案例；后续排障可以检索并用当前证据重新验证。 |

### 8. 多 Agent 协作与集成

| 能力 | 具体工作 |
| --- | --- |
| [有边界的工作分工](skills/auto-dev/references/capabilities/capability-parallel-work.md) | 为独立工作包明确范围、输入、产物、验收、禁止触碰区域及冲突负责人。 |
| [执行者上下文与隔离](skills/auto-dev/references/execution/multi-agent.md) | 准备隔离的 Git worktree 和任务上下文包，再由宿主创建或绑定真实执行者。 |
| [结果收集、审查与合并](skills/auto-dev/references/execution/multi-agent.md) | 收集范围内补丁，按依赖和合并策略应用结果，执行合并前后验证并清理已完成的工作区。 |
| [多会话写入协调](skills/auto-dev/references/control-plane/lifecycle-hooks.md) | 按分支协调写入者与观察者角色，处理会话接管，检查过期会话继续写入的情况。 |

### 9. 持续开发、恢复与交接

| 能力 | 具体工作 |
| --- | --- |
| [生命周期 Hooks](skills/auto-dev/references/control-plane/lifecycle-hooks.md) | 在 SessionStart、UserPromptSubmit、SubagentStart、PreToolUse 阶段恢复上下文、记录需求轮次、传递协作上下文并检查受支持的写入。 |
| [任务检查点与中断续作](skills/auto-dev/references/continuity/resume-handoff.md) | 保存目标、计划、当前节点、证据、阻塞和下一步，在新会话或上下文压缩后重新核对状态并继续。 |
| [交接导出与导入](skills/auto-dev/references/continuity/resume-handoff.md) | 传递下一位 Agent 所需的任务、依赖与证据上下文，并在目标环境重新检查有效性。 |
| [已有项目接管](skills/auto-dev/references/intake/pre-git-control.md) | 检查并接管缺少任务状态的仓库；支持 Git 或本地无 Git 控制模式，并在条件满足时迁移。 |
| [运行时刷新与状态升级](skills/auto-dev/references/continuity/legacy-upgrade.md) | 检查安装包、Hooks 与项目就绪状态；支持版本化状态升级、备份、升级后复验及中断恢复。 |
| [状态修复与快照管理](skills/auto-dev/references/control-plane/cli-contract.md) | 先诊断再执行具名修复，恢复任务或校正视图；按保留策略清理可删除的历史快照。 |

### 10. 交付、发布与进度可见性

| 能力 | 具体工作 |
| --- | --- |
| [Git 存档与回退评估](skills/auto-dev/references/continuity/resume-handoff.md) | 在获得授权后保存范围明确的 Git 存档点；回退检查会展示目标、影响范围与风险，不自动改写工作区。 |
| [发布协调与部署验证](skills/auto-dev/references/capabilities/capability-release.md) | 结合现有 CI/CD、脚本或人工流程，明确环境、版本、授权、发布前检查、发布后健康检查和回退条件。 |
| [发布证据与交付说明](skills/auto-dev/references/verification/product-review.md) | 记录目标版本、环境、关键用户路径、回退状态、残余风险与下一步，关联到当前交付结果。 |
| [外部与长时间动作跟踪](skills/auto-dev/references/control-plane/action-attribution.md) | 把设备操作、外部调用和长时间动作绑定到计划节点，记录开始、结果、失败和未闭合动作。 |
| [本地进度页与结构化回执](skills/auto-dev/references/control-plane/receipt-catalog.md) | 展示当前目标、任务层级、时间线、验证、阻塞和下一步，并提供稳定的中英双语阶段回执。 |

## 包含哪些组件

- **Auto Dev Skill**：需求梳理、Quick Write、Direct、Team Core、验证与交接。
- **Refresh Skill**：继续旧会话前，检查已安装的运行时与当前项目状态。
- **生命周期 Hooks**：`SessionStart`、`UserPromptSubmit`、`SubagentStart` 和 `PreToolUse`。
- **本地 CLI**：项目与任务状态、计划、验证记录、依赖信息、恢复和本地进度视图。
- **CodeGraph 集成**：调用外部 CLI 查询受影响的符号和测试，并记录影响分析证据。
- **可选能力**：调试、架构、界面验证证据、发布证据和并行工作。并行执行者需要宿主支持，并在工作流中明确选用。

## 使用要求

- 支持手动安装插件与生命周期 Hooks 的 Codex 桌面端。
- `python3`（Python 3.9 或更高版本）、Git，以及 macOS 或 Linux 等 POSIX 环境。Python 运行时仅使用标准库。原生 Windows 支持尚未验证。
- 核心工作流不要求安装 [CodeGraph](https://github.com/colbymchenry/codegraph)。自动化的 `impact inspect` / `impact record` 需要 CodeGraph，详见 [CodeGraph 集成](#codegraph-集成)。
- 开发用的契约测试还需要 Bash 和 ripgrep（`rg`）。

安装插件不会自动信任插件的 Hooks。请在 Codex 中查看 Hook 定义，并在出现提示时决定是否信任。功能可用性取决于宿主及其管理策略。详见[官方 Hook 打包文档](https://developers.openai.com/plugins/build/plugins#bundled-mcp-servers-and-lifecycle-hooks)。

## 安装

先将本仓库添加为插件市场，再安装插件：

```sh
codex plugin marketplace add plyflai/auto-dev
codex plugin add auto-dev@plyflai-auto-dev
```

安装后新建一个 Codex 会话。也可以在桌面端的插件浏览器中选择 **Auto Dev by plyflai** 市场，再安装 **Auto Dev**。

如果使用本地克隆：

```sh
git clone https://github.com/plyflai/auto-dev.git
cd auto-dev
codex plugin marketplace add .
codex plugin add auto-dev@plyflai-auto-dev
```

`plyflai-auto-dev` 市场只选择一个来源。本地克隆方式与 GitHub 来源方式二选一。

## 使用

打开需要开发的项目，显式选择 Skill，或输入：

```text
$auto-dev:auto-dev 帮我修复这个项目的登录问题，并验证修复结果。
```

继续任务前，如需检查运行时与项目是否就绪：

```text
$auto-dev:refresh
```

两个 Skill 均配置为显式调用。项目已有可恢复的 Auto Dev 状态后，生命周期 Hooks 可以在新会话中恢复任务上下文。

插件对自身源码目录设有保护，防止将插件本身收编为 Auto Dev 项目。体验工作流时，请使用其他项目或临时测试目录。

## CodeGraph 集成

Auto Dev 实现开发工作流和适配代码；CodeGraph 提供代码图谱与查询引擎。CodeGraph 是独立维护、采用 MIT 许可证的项目。本插件不附带 CodeGraph 的源码或二进制文件。

| 功能 | 未安装 CodeGraph | 已安装 CodeGraph |
| --- | --- | --- |
| 需求、计划、Hooks、验证记录与恢复 | 可用 | 可用 |
| 代码调查 | 使用宿主搜索、文件读取与 Git | 使用图谱查询，并直接检查源码 |
| 自动影响分析与分析记录 | 不可用 | 需要当前项目的有效索引 |

集成测试针对 CodeGraph **1.1.0**。更新版本尚未纳入兼容性测试范围。请参考[上游安装文档](https://github.com/colbymchenry/codegraph#quick-start)，或通过 npm 安装已测试的版本：

```sh
npm install --global @colbymchenry/codegraph@1.1.0
```

在需要开发的项目中执行：

```sh
codegraph init -i
codegraph status --json
```

Auto Dev 从 `PATH` 查找 `codegraph`。如果使用其他安装位置，可将 `AUTO_DEV_CODEGRAPH_BIN` 设置为可执行文件路径。使用上游的同步或索引命令保持索引有效。自动影响分析会将缺失或过期的索引报告为错误，不会把缺少图谱证据视为检查通过。基础代码调查仍可使用宿主的源码搜索与文件读取工具。

感谢 [Colby Mchenry 和 CodeGraph 贡献者](https://github.com/colbymchenry/codegraph) 提供图谱引擎。[第三方声明](THIRD_PARTY_NOTICES.md)列出了上游链接、许可证，以及外部工具与随插件分发代码的边界。

## 状态与执行边界

- 受管项目状态保存在目标项目的 `.auto-dev/` 目录。
- 会话激活与运行时发现数据保存在宿主提供的 `PLUGIN_DATA` 目录。
- 进度服务监听本机回环地址，工作流会提供访问链接。
- Hooks 执行确定性的恢复与检查。需求判断、模型选择、任务委派和已获授权的外部操作仍由 Agent 与宿主负责。
- 任务通过验证后进入 `review_ready`，最终验收仍由用户决定。

请勿将项目状态、凭据或会话数据复制到本插件仓库。特定功能所需的外部工具会在任务需要时解析，本仓库不附带这些工具。

## 开发

仓库根目录也是插件根目录。插件保留运行时使用且受支持的 `.codex-plugin/plugin.json` 清单布局。

```text
.agents/plugins/marketplace.json    安装目录
.codex-plugin/plugin.json          插件标识与版本
hooks/hooks.json                   生命周期事件注册
scripts/                          Hook 运行时
skills/auto-dev/                   主 Skill、参考资料与 CLI
skills/refresh/                    运行时与项目就绪检查 Skill
tests/                            Python 回归测试
```

查看 CLI：

```sh
python3 skills/auto-dev/scripts/auto_dev.py --help
python3 skills/auto-dev/scripts/auto_dev.py version
```

运行回归测试与 Shell 契约测试：

```sh
python3 -m unittest discover -s tests -v
for test in skills/auto-dev/scripts/contracts/*test.sh; do
  bash "$test" || exit 1
done
```

测试使用临时项目样例。已安装 `codegraph` 时，真实 CodeGraph 测试会运行；未安装时会报告跳过。持续集成（CI）分别运行核心测试和真实 CodeGraph 集成测试。静态检查与单元测试不能证明插件兼容所有 Codex 宿主版本；反馈安装问题时，请附上宿主版本和实际行为。

欢迎通过 Issue 和 Pull Request 参与贡献。行为修改请提供可复现的示例和验证结果。反馈中请勿包含项目数据或凭据。修改公共说明时，请同步更新中英文 README。

## 许可证

[MIT](LICENSE) · Copyright 2026 plyflai。该许可证适用于 Auto Dev 代码；第三方工具保留各自的许可证。详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

Auto Dev 是独立项目，不是 OpenAI 或 CodeGraph 的官方产品。
