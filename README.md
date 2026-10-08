# Auto Dev

A Codex plugin for software delivery with requirement intake, risk-based execution, lifecycle hooks, and resumable project state.

Auto Dev keeps the user's goal, plan, verification evidence, and next action together. It supports small patches, direct implementation, and larger tasks with optional team capabilities. The plugin includes a local Python CLI, a read-only progress page, and an optional integration with [CodeGraph](https://github.com/colbymchenry/codegraph) for code navigation and impact analysis.

主要工作流使用中文。Auto Dev 会先补齐影响交付的需求缺口，再按真实风险选择执行方式，并通过 Hook 恢复上下文、检查写入边界。

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
$auto-dev:auto-dev 帮我修复这个项目的登录问题，并验证修复结果。
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

Contributions are welcome through issues and pull requests. Include a reproducible example and validation for changed behavior. Keep project data and secrets out of reports.

## License

[MIT](LICENSE) · Copyright 2026 plyflai. This license covers Auto Dev code; third-party tools retain their own licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Auto Dev is an independent project and is not an official OpenAI or CodeGraph product.
