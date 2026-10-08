# Auto Dev

**Your cyber development team.**

**Auto Dev isn't built for demos. It's built to develop, iterate on, and deliver real, large-scale projects.**

**English** | [简体中文](README.zh-CN.md)

[![Tests](https://github.com/plyflai/auto-dev/actions/workflows/ci.yml/badge.svg)](https://github.com/plyflai/auto-dev/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/plyflai/auto-dev)](https://github.com/plyflai/auto-dev/releases/latest)

[Who it is for](#who-it-is-for) · [Capability catalog](#capability-catalog) · [Install](#install)

**Auto Dev helps you develop real projects as if you had a professional development team.** It organizes the work a large project needs: refining requirements, planning architecture and iterations, implementing features, testing, debugging, and delivering.

**Whether you do not write code, know some development, or are an experienced developer, Auto Dev helps you keep your project moving.** You describe the goal; Auto Dev helps clarify, break down, and refine the requirements, then guides each iteration. Requirement decisions, task progress, and verification records can be preserved to inform future work. You set the product direction; Auto Dev brings professional development-team practices to your coding agent.

Auto Dev is a Codex plugin combining skills, lifecycle hooks, a local Python CLI, and a read-only progress page. Optional [CodeGraph](https://github.com/colbymchenry/codegraph) integration adds code navigation and impact analysis. Workflow instructions and default user-facing records are primarily in Simplified Chinese; both READMEs document the same capabilities and limitations.

## Who it is for

| Your background | How Auto Dev helps |
| --- | --- |
| **You do not write code** | Describe the product in your own words. Auto Dev helps uncover missing requirements, explain decisions, break down the work, and present results you can review. |
| **You understand some development** | Connect the parts you know into a complete workflow, with support for architecture, debugging, testing, and release preparation as the project grows. |
| **You are an experienced developer** | Use a coordinated workflow for complex engineering: staged refactoring, contract changes, deep debugging, performance verification, parallel work, and long-running project continuity. |

**Product thinking, architecture, implementation, testing, debugging, collaboration, and delivery—organized around the same project goal.** Small changes can stay lightweight; larger work can draw on the broader capability set below.

## How the workflow adapts

Auto Dev investigates the repository, resolves requirement gaps that affect the result, and selects an execution path:

| Path | Suitable work | What happens |
| --- | --- | --- |
| **Quick Write** | A bounded, low-risk patch to existing text files | Make the change and run targeted validation. No Task or Plan is created. |
| **Direct** | A focused implementation or fix | Track the requested outcome and the verification needed to establish it. |
| **Team Core** | Work with evidenced architecture, shared-contract, integration, or other delivery risks | Enable the relevant capabilities; use rolling work packets and optional parallel workers when justified. |

These paths are selected from the task and repository evidence, not from a requirement to run multiple agents. Team Core can run with one agent. Parallel work requires host support and explicit workflow selection. See the [Quick Write boundaries](skills/auto-dev/references/intake/quick-write.md) and [Direct/Team routing](skills/auto-dev/references/execution/execution-router.md).

For managed tasks, implementation is followed by verification and a `review_ready` state. You review the result before final acceptance. If work is interrupted, Auto Dev can resume from its saved task state.

## Capability catalog

This catalog covers the current version’s main product and engineering capabilities. Skills guide the agent, the CLI stores project state and evidence, and hooks perform supported lifecycle checks. Capabilities are selected according to the task and its risks.

**Seven conditional Team capability packs:** `architecture`, `data-contract`, `debug-observability`, `gui`, `release`, `parallel-work`, and `compliance`. See the [selection rules](skills/auto-dev/references/execution/capability-router.md).

GUI verification uses available browser or desktop executors; performance verification reuses project benchmarks; deployment uses existing release procedures; multi-agent execution requires host support. Automated CodeGraph impact analysis requires a separate installation and a current index.

### 1. Requirements and product definition

| Capability | What it covers |
| --- | --- |
| [Project discovery](skills/auto-dev/references/intake/requirement-intake.md) | Turn an initial idea into goals, user scenarios, project scope, capability boundaries, and staged outcomes. |
| [Adaptive requirement clarification](skills/auto-dev/references/intake/requirement-intake.md) | Choose direct execution, focused questions, deeper refinement, or project discovery according to the gaps that affect the result. |
| [Expert-perspective requirement review](skills/auto-dev/references/intake/requirement-intake.md) | Use repository evidence to surface useful suggestions and distinguish accepted, deferred, excluded, and pending decisions. |
| [Acceptance and change management](skills/auto-dev/references/intake/outcome-contract.md) | Define success, failure, and boundary scenarios; show requirement changes and preserve scope, non-goals, and inherited constraints. |

### 2. Project organization and iteration planning

| Capability | What it covers |
| --- | --- |
| [Project hierarchy](skills/auto-dev/references/intake/requirement-intake.md) | Organize project contexts, durable capabilities, recursive outcomes, tasks, and plans so a project remains decomposable. |
| [Risk-based workflow selection](skills/auto-dev/references/mode-index.md) | Support read-only investigation, Quick Write, Direct, and Team Core, selecting a workflow from task evidence. |
| [Rolling milestones](skills/auto-dev/references/execution/rolling-milestones.md) | Keep future milestones focused on goals and acceptance, then detail work packets using current repository facts when execution approaches. |
| [Dependencies and execution order](skills/auto-dev/references/execution/rolling-milestones.md) | Organize milestones and work packets as a directed acyclic graph with inputs, outputs, write scopes, acceptance, and integration nodes. |
| [Task and focus management](skills/auto-dev/references/control-plane/state-transitions.md) | Select, pause, resume, switch, or close tasks; separate viewing focus from execution focus and record small-change activities. |
| [Blockers and replanning](skills/auto-dev/references/execution/capability-router.md) | Record gaps, owners, and next actions; revise the strategy after repeated failures or exhausted budgets while preserving completed work. |

### 3. Code understanding, architecture, and implementation

| Capability | What it covers |
| --- | --- |
| [Repository and call-chain investigation](skills/auto-dev/references/control-plane/code-navigation.md) | Locate entry points, symbols, callers, dependencies, and nearby tests with CodeGraph when available, or targeted search and source reads. |
| [Feature development and maintenance](skills/auto-dev/references/execution/direct.md) | Guide the agent through feature implementation, bug fixes, refactoring, optimization, test additions, and cleanup. |
| [Architecture boundaries and staged refactoring](skills/auto-dev/references/capabilities/capability-architecture.md) | Define responsibilities, modules, shared abstractions, interfaces, and cross-platform boundaries; migrate callers in verifiable stages with compatibility paths. |
| [Impact analysis and behavior preservation](skills/auto-dev/references/control-plane/impact-preservation.md) | Use CodeGraph to inspect affected symbols and tests, recording behavior to preserve, validation actions, and unresolved impact. |

### 4. Data, interfaces, and security

| Capability | What it covers |
| --- | --- |
| [Data and interface contracts](skills/auto-dev/references/capabilities/capability-data-contract.md) | Manage schema, public API, protocol, and configuration changes with explicit producers, consumers, versions, and error semantics. |
| [Data migration and compatibility](skills/auto-dev/references/capabilities/capability-data-contract.md) | Plan expand/migrate/contract stages and verify representative data, backups, idempotency, retries, partial failures, and rollback paths. |
| [Permission, security, and privacy checks](skills/auto-dev/references/capabilities/capability-compliance.md) | Inspect trust boundaries around authentication, permissions, payments, and sensitive data; verify allowed, denied, unauthorized, replay, and audit paths. |
| [Workspace path policies](skills/auto-dev/references/control-plane/workspace-policy.md) | Configure forbidden, approval-required, and sensitive paths; supported hooks check writes against the current task and policy. |

### 5. Testing, verification, and acceptance

| Capability | What it covers |
| --- | --- |
| [Targeted engineering verification](skills/auto-dev/references/verification/verification.md) | Select existing project tests, builds, type checks, or runtime checks to match the change and execute applicable validation after implementation. |
| [Traceable proof records](skills/auto-dev/references/verification/verification.md) | Record commands, results, and failed attempts; link evidence to outcomes and plans and require revalidation after relevant code or environment changes. |
| [End-to-end and GUI verification](skills/auto-dev/references/capabilities/capability-gui.md) | Check real user journeys, page states, error feedback, layout, responsive behavior, and data interactions, with screenshots and relevant console/network evidence. |
| [Performance improvement verification](skills/auto-dev/references/verification/performance-verification.md) | Reuse project benchmarks to compare latency, throughput, resource use, build time, or other metrics repeatedly under the same environment and workload, accounting for noise. |
| [Integration and milestone review](skills/auto-dev/references/execution/rolling-milestones.md) | Review combined behavior, changed scope, contract coverage, and validation after work packets are integrated before accepting a milestone. |
| [User-facing product acceptance](skills/auto-dev/references/verification/product-review.md) | Explain completed work, user-visible changes, test entry points, steps, and expected results in product terms; retain unverified items and wait for final acceptance. |

### 6. Debugging and observability

| Capability | What it covers |
| --- | --- |
| [Logging and runtime diagnostics](skills/auto-dev/references/control-plane/runtime-diagnostics.md) | Assess, reuse, or extend project logging with key events, correlation IDs, errors, retention locations, and agent-readable access paths. |
| [Systematic reproduction](skills/auto-dev/references/capabilities/capability-debug-observability.md) | Choose standard or deep debugging based on complexity and retain minimal reproduction, the original failing path, and run/failure data for flaky issues. |
| [Hypothesis testing and root-cause investigation](skills/auto-dev/references/capabilities/capability-debug-observability.md) | Form falsifiable hypotheses, compare predictions with probe observations, and record confirmed, rejected, or inconclusive conclusions. |
| [Recovery verification](skills/auto-dev/references/capabilities/capability-debug-observability.md) | Rerun the minimal reproduction, original failing path, and applicable regressions; clean up temporary probes and record verified, failed, or awaiting-confirmation recovery. |

### 7. Tool dependencies and project memory

| Capability | What it covers |
| --- | --- |
| [Dependency recipes and version records](skills/auto-dev/references/control-plane/project-memory.md) | Store tool purpose, version combinations, runtime conditions, invocation details, and evidence, distinguishing working, incompatible, preferred, and fallback recipes. |
| [Dependency reuse and revalidation](skills/auto-dev/references/control-plane/project-memory.md) | Reuse verified recipes and gather new evidence through bounded trials when selecting a tool, encountering failures, detecting environment drift, or upgrading. |
| [Environment and runtime entry points](skills/auto-dev/references/control-plane/project-memory.md) | Record confirmed working roots, hosts, service endpoints, execution and observation entry points, and GUI executors. |
| [Domain vocabulary and project knowledge](skills/auto-dev/references/control-plane/project-memory.md) | Preserve stable business terms, invariants, unresolved concepts, durable decisions, and project-specific gotchas. |
| [Searchable incident cases](skills/auto-dev/references/capabilities/capability-debug-observability.md) | Promote verified, user-confirmed diagnoses and recoveries into searchable cases, then retest relevant lessons against current evidence in later investigations. |

### 8. Multi-agent collaboration and integration

| Capability | What it covers |
| --- | --- |
| [Bounded work delegation](skills/auto-dev/references/capabilities/capability-parallel-work.md) | Give independent work packets explicit scopes, inputs, outputs, acceptance checks, protected areas, and conflict ownership. |
| [Worker context and isolation](skills/auto-dev/references/execution/multi-agent.md) | Prepare isolated Git worktrees and task context capsules, then have the host create or bind real executors. |
| [Result capture, review, and integration](skills/auto-dev/references/execution/multi-agent.md) | Capture patches within scope, apply results according to dependencies and merge policy, validate before and after integration, and clean up completed workspaces. |
| [Multi-session write coordination](skills/auto-dev/references/control-plane/lifecycle-hooks.md) | Coordinate branch-scoped writer and observer roles, handle session takeover, and check writes from superseded sessions. |

### 9. Continuity, recovery, and handoff

| Capability | What it covers |
| --- | --- |
| [Lifecycle hooks](skills/auto-dev/references/control-plane/lifecycle-hooks.md) | Use SessionStart, UserPromptSubmit, SubagentStart, and PreToolUse to restore context, track requirement turns, pass worker context, and check supported writes. |
| [Task checkpoints and resumption](skills/auto-dev/references/continuity/resume-handoff.md) | Save goals, plans, current nodes, evidence, blockers, and next actions, then recheck state and continue after a new session or context compaction. |
| [Handoff export and import](skills/auto-dev/references/continuity/resume-handoff.md) | Transfer task, dependency, and evidence context to the next agent and recheck its validity in the destination environment. |
| [Existing-project adoption](skills/auto-dev/references/intake/pre-git-control.md) | Inspect and adopt repositories without managed task state; support Git or local no-Git control and migration when prerequisites are met. |
| [Runtime refresh and state upgrades](skills/auto-dev/references/continuity/legacy-upgrade.md) | Check the package, hooks, and project readiness; support versioned state upgrades, backups, post-upgrade revalidation, and interrupted-upgrade recovery. |
| [State repair and snapshot management](skills/auto-dev/references/control-plane/cli-contract.md) | Diagnose before applying named repairs, restore tasks or reconcile views, and prune eligible historical snapshots under retention rules. |

### 10. Delivery, release, and visible progress

| Capability | What it covers |
| --- | --- |
| [Git archive points and rollback inspection](skills/auto-dev/references/continuity/resume-handoff.md) | Create scoped Git archive points when authorized; rollback inspection reports the target, affected scope, and risks without automatically rewriting the workspace. |
| [Release coordination and deployment verification](skills/auto-dev/references/capabilities/capability-release.md) | Work with existing CI/CD, scripts, or manual procedures to define environments, versions, authorization, pre-release checks, post-release health checks, and rollback conditions. |
| [Release evidence and delivery summaries](skills/auto-dev/references/verification/product-review.md) | Record target versions, environments, critical user journeys, rollback status, remaining risks, and next steps against the current deliverable. |
| [External and long-running action tracking](skills/auto-dev/references/control-plane/action-attribution.md) | Bind device operations, external calls, and long-running actions to plan nodes, recording starts, results, failures, and unresolved actions. |
| [Local progress page and structured receipts](skills/auto-dev/references/control-plane/receipt-catalog.md) | Show current goals, task hierarchy, timelines, verification, blockers, and next actions, with stable bilingual stage receipts. |

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
