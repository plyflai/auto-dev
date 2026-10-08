# Auto Dev

**A resumable workflow from requirements to verified software delivery.**

**English** | [简体中文](README.zh-CN.md)

[![Tests](https://github.com/plyflai/auto-dev/actions/workflows/ci.yml/badge.svg)](https://github.com/plyflai/auto-dev/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/plyflai/auto-dev)](https://github.com/plyflai/auto-dev/releases/latest)

Auto Dev is a Codex plugin that keeps requirements, implementation, verification, and project progress connected. It combines reusable skills, lifecycle hooks, a local Python CLI, and a read-only progress page. Optional [CodeGraph](https://github.com/colbymchenry/codegraph) integration adds code navigation and impact analysis.

Workflow instructions and default user-facing records are primarily in Simplified Chinese. The English and Chinese READMEs cover the same features, setup, and limitations.

## Why Auto Dev

| What you get | How Auto Dev supports it |
| --- | --- |
| **A workflow that fits the change** | Eligible small patches use Quick Write. Direct handles focused delivery. Team Core adds capabilities when repository evidence shows they are needed. |
| **A clear point to resume from** | Managed tasks retain their goal, plan, checkpoints, blockers, and next action in `.auto-dev/`. Session hooks restore a compact view when you return to a resumable task. |
| **Completion backed by verification** | Direct and Team tasks record proof attempts against their outcomes. Applicable checks run after implementation, failed attempts remain visible, and review checks whether evidence is still current. |
| **Execution checks in the tool path** | In an activated session, supported Hooks check recognized writes against requirement status, task scope, and configured path policies before execution. |
| **Progress you can inspect** | A local read-only page shows the active goal, plan nodes, verification results, and blockers without requiring you to reconstruct them from chat history. |
| **Code intelligence when you need it** | CodeGraph can supply affected symbols and tests. Core workflows use Python's standard library and Git; the graph engine is an optional, separately installed tool. |

For the detailed behavior, see [workflow routing](skills/auto-dev/references/mode-index.md), [continuity](skills/auto-dev/references/continuity/resume-handoff.md), [verification](skills/auto-dev/references/verification/verification.md), and [Hooks](skills/auto-dev/references/control-plane/lifecycle-hooks.md).

## How the workflow adapts

Auto Dev investigates the repository, resolves requirement gaps that affect the result, and selects an execution path:

| Path | Suitable work | What happens |
| --- | --- | --- |
| **Quick Write** | A bounded, low-risk patch to existing text files | Make the change and run targeted validation. No Task or Plan is created. |
| **Direct** | A focused implementation or fix | Track the requested outcome and the verification needed to establish it. |
| **Team Core** | Work with evidenced architecture, shared-contract, integration, or other delivery risks | Enable the relevant capabilities; use rolling work packets and optional parallel workers when justified. |

These paths are selected from the task and repository evidence, not from a requirement to run multiple agents. Team Core can run with one agent. Parallel work requires host support and explicit workflow selection. See the [Quick Write boundaries](skills/auto-dev/references/intake/quick-write.md) and [Direct/Team routing](skills/auto-dev/references/execution/execution-router.md).

For managed tasks, implementation is followed by verification and a `review_ready` state. You review the result before final acceptance. If work is interrupted, Auto Dev can resume from its saved task state.

## What is included

- **Auto Dev skill**: requirement intake, Quick Write, Direct, Team Core, verification, and handoff.
- **Refresh skill**: checks the installed runtime and current project state before continuing an older conversation.
- **Lifecycle hooks**: `SessionStart`, `UserPromptSubmit`, `SubagentStart`, and `PreToolUse`.
- **Local CLI**: project/task state, plans, proof records, dependency information, recovery, and a local progress view.
- **CodeGraph integration**: external CLI queries, affected symbols and tests, and recorded impact evidence.
- **Optional capabilities**: debugging, architecture, GUI evidence, release evidence, and parallel work. Parallel workers require host support and explicit workflow selection.

## Requirements

- Codex desktop with support for manually installed plugins and lifecycle hooks.
- `python3` (Python 3.9 or newer), Git, and a POSIX environment such as macOS or Linux. The Python runtime uses the standard library only. Native Windows support is not verified.
- [CodeGraph](https://github.com/colbymchenry/codegraph) is optional for core workflows and required for automated `impact inspect` / `impact record`. See [CodeGraph integration](#codegraph-integration).
- Development contract tests also use Bash and ripgrep (`rg`).

Installing a plugin does not automatically trust its hooks. Review the hook definitions in Codex and trust them when prompted. Availability depends on the host and its managed policies. See the [official hook packaging documentation](https://developers.openai.com/plugins/build/plugins#bundled-mcp-servers-and-lifecycle-hooks).

## Install

Add this repository as a marketplace, then install the plugin:

```sh
codex plugin marketplace add plyflai/auto-dev
codex plugin add auto-dev@plyflai-auto-dev
```

Start a new Codex conversation after installation. You can also select the **Auto Dev by plyflai** marketplace in the desktop plugin browser and install **Auto Dev** there.

For a local checkout:

```sh
git clone https://github.com/plyflai/auto-dev.git
cd auto-dev
codex plugin marketplace add .
codex plugin add auto-dev@plyflai-auto-dev
```

Use one source for the `plyflai-auto-dev` marketplace. The local-checkout commands are an alternative to the GitHub-source commands.

## Use

Open the project you want to work on, then explicitly select the skill or use:

```text
$auto-dev:auto-dev Fix the login issue in this project and verify the fix.
```

To inspect runtime and project readiness before resuming:

```text
$auto-dev:refresh
```

Both skills are configured for explicit invocation. Once a project has resumable Auto Dev state, the lifecycle hooks can restore its context in a new session.

The plugin source directory is protected against adopting itself as an Auto Dev project. Use another project or a disposable fixture when trying the workflow.

## CodeGraph integration

Auto Dev implements the development workflow and the adapter; CodeGraph provides the code graph and query engine. CodeGraph is a separately maintained, MIT-licensed project. Its source and binaries are not bundled with this plugin.

| Feature | Without CodeGraph | With CodeGraph |
| --- | --- | --- |
| Requirements, plans, hooks, verification records, recovery | Available | Available |
| Code investigation | Host search, file reads, and Git | Graph queries plus direct source verification |
| Automated impact inspection and receipts | Unavailable | Requires a current project index |

The integration test targets CodeGraph **1.1.0**. Newer versions are not yet included in the compatibility matrix. Follow the [upstream installation documentation](https://github.com/colbymchenry/codegraph#quick-start), or install the tested version with npm:

```sh
npm install --global @colbymchenry/codegraph@1.1.0
```

In the project being developed:

```sh
codegraph init -i
codegraph status --json
```

Auto Dev finds `codegraph` on `PATH`. Set `AUTO_DEV_CODEGRAPH_BIN` to an executable path when using a separate installation. Keep the index current with the upstream sync/index commands. Automated impact analysis reports missing or stale indexes as errors; it does not treat absent graph evidence as a successful check. Core investigation can still use the host's source search and file-reading tools.

Thanks to [Colby Mchenry and the CodeGraph contributors](https://github.com/colbymchenry/codegraph) for the graph engine. See [third-party notices](THIRD_PARTY_NOTICES.md) for upstream links, licenses, and the distinction between external tools and bundled code.

## State and execution boundaries

- Managed project state lives in the target project's `.auto-dev/` directory.
- Session activation and runtime discovery data live in the host-provided `PLUGIN_DATA` directory.
- The progress service binds to a loopback address. Its URL is reported by the workflow.
- Hooks perform deterministic recovery and checks. The agent and host remain responsible for requirements, model selection, delegation, and authorized external actions.
- A task reaches `review_ready` after verification; final acceptance remains a user decision.

Do not copy project state, credentials, or session data into this plugin repository. Feature-specific external tools are resolved when the task needs them; they are not bundled here.

## Development

The repository root is also the plugin root. It retains the supported `.codex-plugin/plugin.json` manifest layout used by the runtime.

```text
.agents/plugins/marketplace.json    Installation catalog
.codex-plugin/plugin.json          Plugin identity and version
hooks/hooks.json                   Lifecycle event registration
scripts/                          Hook runtime
skills/auto-dev/                   Main skill, references, and CLI
skills/refresh/                    Runtime/project readiness skill
tests/                            Python regression tests
```

Inspect the CLI:

```sh
python3 skills/auto-dev/scripts/auto_dev.py --help
python3 skills/auto-dev/scripts/auto_dev.py version
```

Run the regression suite and shell contracts:

```sh
python3 -m unittest discover -s tests -v
for test in skills/auto-dev/scripts/contracts/*test.sh; do
  bash "$test" || exit 1
done
```

Tests use temporary project fixtures. The live CodeGraph test runs when `codegraph` is installed and otherwise reports a skip. CI runs the core suite separately from the live CodeGraph integration test. Static checks and unit tests do not establish compatibility with every Codex host version; report the host version and observed behavior in installation issues.

Contributions are welcome through issues and pull requests. Include a reproducible example and validation for changed behavior. Keep project data and secrets out of reports. Update both README language versions when changing shared documentation.

## License

[MIT](LICENSE) · Copyright 2026 plyflai. This license covers Auto Dev code; third-party tools retain their own licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Auto Dev is an independent project and is not an official OpenAI or CodeGraph product.
