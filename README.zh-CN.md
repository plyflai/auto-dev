# Auto Dev

**把需求、开发和验证串成可恢复的工作流。**

[English](README.md) | **简体中文**

[![测试](https://github.com/plyflai/auto-dev/actions/workflows/ci.yml/badge.svg)](https://github.com/plyflai/auto-dev/actions/workflows/ci.yml)
[![许可证：MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![版本](https://img.shields.io/github/v/release/plyflai/auto-dev)](https://github.com/plyflai/auto-dev/releases/latest)

Auto Dev 是一个 Codex 插件，用于衔接需求、实现、验证和项目进度。插件包含可复用的 Skill、生命周期 Hooks、本地 Python 命令行工具（CLI）和只读进度页面。可选的 [CodeGraph](https://github.com/colbymchenry/codegraph) 集成提供代码导航与影响分析。

工作流指令和面向用户的运行记录默认以简体中文为主。中英文 README 包含相同的功能、安装方法和使用限制。

## 为什么使用 Auto Dev

| 你能获得什么 | Auto Dev 如何实现 |
| --- | --- |
| **让流程适应改动规模** | 符合条件的小补丁使用 Quick Write；目标集中的开发任务使用 Direct；仓库证据表明确有需要时，Team Core 才启用相应能力。 |
| **中断后有明确的继续位置** | 受管任务将目标、计划、检查点、阻塞和下一步保存在 `.auto-dev/`。回到可恢复任务时，会话 Hooks 会恢复精简的任务状态。 |
| **用验证记录支撑完成结论** | Direct 和 Team 任务按交付目标记录验证尝试。实现后执行适用检查，保留失败记录，并在审查时检查证据是否仍然有效。 |
| **在工具执行前检查约束** | 会话启用后，受支持的 Hooks 会针对能够识别的写入，检查需求状态、任务范围和已配置的路径策略。 |
| **直接查看开发进度** | 本地只读页面展示当前目标、计划节点、验证结果和阻塞，无需从聊天历史重新整理进度。 |
| **按需接入代码分析能力** | CodeGraph 可以提供受影响的符号和测试。核心工作流使用 Python 标准库与 Git；代码图谱引擎作为可选工具单独安装。 |

详细行为见[工作流路由](skills/auto-dev/references/mode-index.md)、[任务连续性](skills/auto-dev/references/continuity/resume-handoff.md)、[验证机制](skills/auto-dev/references/verification/verification.md)和 [Hooks](skills/auto-dev/references/control-plane/lifecycle-hooks.md)。

## 工作流如何适应任务

Auto Dev 先调查仓库，补齐影响结果的需求缺口，再选择执行路径：

| 路径 | 适用任务 | 执行方式 |
| --- | --- | --- |
| **Quick Write：快速写入** | 对已有文本文件做范围明确、风险低的小补丁 | 完成修改并执行针对性验证，不创建 Task 或 Plan。 |
| **Direct：直接执行** | 目标集中的功能实现或修复 | 跟踪用户要求的交付结果，以及证明结果所需的验证。 |
| **Team Core：团队核心交付** | 有证据表明存在架构、共享契约、集成或其他交付风险的任务 | 启用对应能力；有依据时采用滚动工作包和可选的并行执行者。 |

执行路径由任务和仓库证据决定，不要求必须使用多个 Agent。Team Core 可以由单个 Agent 完成。并行工作需要宿主支持，并在工作流中明确选用。具体条件见 [Quick Write 边界](skills/auto-dev/references/intake/quick-write.md)和 [Direct/Team 路由](skills/auto-dev/references/execution/execution-router.md)。

受管任务完成实现后会执行验证，再进入 `review_ready`（待审查）状态。最终验收前，由你检查交付结果。工作中断后，Auto Dev 可以从已保存的任务状态继续。

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
