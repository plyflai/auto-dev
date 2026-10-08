---
name: refresh
description: "Refresh Auto Dev's current package/runtime and project continuity state with one deterministic receipt and clickable project/control-plane links. Use when the user explicitly invokes $auto-dev:refresh, asks to refresh/update Auto Dev, returns to an older conversation, or suspects Hook/runtime drift before continuing work."
---

# Auto Dev Refresh

🔄 Auto Dev Refresh 已激活。

Use this sibling Skill as a read-only readiness check. It is an orchestrator around the existing Auto Dev control plane, not a second control plane. It also bridges older Codex sessions by comparing the loaded Hook/CLI contract with the current package before deciding whether the same checkout can continue.

## Run

The user-facing Skill entry is:

```text
$auto-dev:refresh
```

From the current project checkout, invoke the canonical command:

```text
python3 <auto-dev-root>/skills/auto-dev/scripts/auto_dev.py refresh --repo-root <checkout> --view agent-focus
```

For normal agent continuity, use `--view agent-focus` to return the post-evaluation decision summary. Use `--view full` for diagnostics, UI, migration, or external consumers; the default full refresh contract remains available and unchanged.

Read the JSON result and relay its `receipt` verbatim. Every invocation must then render both links from `links` as Markdown, even when the final state is blocked. Use `links.project.label` with `links.project.path` for the `Project:` link, and use `links.control_plane.url` for the `Control plane:` link.

If `links.control_plane.url` is absent, report `Control plane: unavailable` and preserve the non-ready result; never invent a URL. Then report only the single `next` action and the relevant detail from `runtime`, `project`, and `service`.

Every refresh must leave `.auto-dev`, product files, task selection, proof records, and writer ownership unchanged. Do not run `legacy-upgrade apply`, `fix apply`, `handoff import`, `task resume`, `transition`, or any other project mutation as part of refresh.

Read `project.transition` as compatibility diagnosis only. It may identify `start-new` or list routes that are valid from the observed state, but it never proves that a new user intent exists and never executes a route. After any reported repair, adoption, upgrade, or transition decision, resume the user's original intent instead of restarting obsolete work.

When `project.upgrade.status` is `upgrade_available`, `reverification_required`, `manual_decision_required`, `blocked`, or `newer_than_cli`, preserve that result and route into the existing [Legacy Upgrade](../auto-dev/references/continuity/legacy-upgrade.md) contract. Refresh may report the read-only inspection and next action; only the normal Auto Dev continuity flow may ask for confirmation or perform `legacy-upgrade apply`. Resolve a runtime/session mismatch first in a new conversation on the same checkout; it is not a reason to create a new task or import a handoff.

For a Rolling Milestone, `project.rolling_graph` is a read-only projection of the compiled packet contract. It may include packet execution profile, required capabilities, verification/review/merge policy, model profile, execution topology, and worker lifecycle readback. These fields describe what the control plane compiled; they do not create subagents, choose models, apply patches, or run verification.

## Terminal States

The result has exactly one top-level state:

| State | Meaning | Next action |
| --- | --- | --- |
| `ready` | Package and project readback are usable; no current blocker was hidden. | Continue the current task. |
| `work_blocked` | The existing project/task has a real blocker such as stale verification, out-of-scope changes, or a paused task. | Follow the existing blocker or `continuity_summary.next_action`; refresh does not clear it. |
| `fresh_session_required` | The source/package is usable but the current Hook/runtime path is missing, incomplete, or older. | Ask the host to create a new conversation in the same checkout, then run this Skill there. |
| `confirmation_required` | The control plane needs user confirmation, task selection, or review acceptance. | Ask for that explicit decision. |
| `runtime_unavailable` | A required package or status readback cannot be verified. | Restore a complete compatible Auto Dev runtime, then refresh again. |

Do not turn `fresh_session_required` into `ready` merely because a new conversation was created. The new conversation must run refresh and receive its own `ready` result. A fresh conversation may remove stale Hook activation while leaving a project blocker intact.

## Same Checkout Continuity

For the same project, checkout, branch, and Auto Dev task:

- reuse the existing `.auto-dev` state;
- rely on `SessionStart` auto-resume;
- do not export or import a handoff;
- do not create a new Auto Dev task;
- do not claim writer ownership during refresh.

Use handoff only when the workspace, checkout, branch, machine, or control root genuinely changes. The host owns Codex conversation creation and should preserve the same checkout without creating a worktree for this recovery path.

Detailed contracts are in [refresh-contract.md](references/refresh-contract.md) and [handoff-flow.md](references/handoff-flow.md).
