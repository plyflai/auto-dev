# Refresh Contract

`refresh` is a read-only aggregation of existing facts. It checks the local bundle, Hook configuration, current version/CLI contract metadata, `status --compact`, conditional legacy-upgrade inspection, progress health when a record exists, and writer-lease readback when a session id is available.

The JSON result separates these layers:

- `runtime`: source/package completeness, packet/worker runtime completeness, and whether the configured Hook path or observed session contract can be trusted;
- `project.readback`: the existing compact Auto Dev status, including task, continuity, blockers, and next action;
- `project.upgrade`: the existing control-plane upgrade projection and conditional inspection;
- `project.transition`: read-only compatibility diagnosis, valid route candidates, and an explicit instruction to resume the original user intent after resolution;
- `project.rolling_graph`: capability availability, Plan strategy, Milestone roadmap, Ready Frontier, compilation/execution focus, compiled packet policies, execution topology/dispatch status, execution decision, policy revalidation, Main-session handoff, Integration/Exit Snapshot state, worker lifecycle readback, and CodeGraph compiler-input freshness;
- `service`: the ensured progress UI and existing lease observations;
- `links`: the current project path and verified control-plane URL that the Skill renders in chat;
- `handoff`: an explicit same-checkout rule showing that import and task creation are false.

No field in this result grants permission, changes a revision, selects a task, executes a transition, applies an upgrade, clears a blocker, or claims a lease. The only runtime side effect is ensuring the existing disposable progress server and its record outside `.auto-dev`; this is required so every successful refresh can return the control-plane link. The ready record and health response must match the current bundle version, so reinstalling Auto Dev replaces an older UI process. A healthy progress service is useful evidence but is not allowed to mask a project blocker.

The source/package/runtime/fresh-session distinction is intentional:

1. `source.status=complete` means the authoritative bundle contains the required files.
2. `runtime.status=package_ready` means this command can use a complete bundle and found no evidence of a stale configured path.
3. `runtime.session_observation=not_observable` means a direct CLI invocation cannot prove what a host-loaded Hook has already activated.
4. `fresh_session_required` is emitted only when a configured runtime is missing/incomplete, its version or CLI schema differs from the usable bundle, or the host exposes an older CLI schema for the current session. This is a session activation diagnosis, not a project migration and not a signal to create a new task.

Packet and worker fields are additive readback. A missing `.auto-dev/workers/` directory means dispatch has not started; it is not a blocker. Worker records are filtered to the active compiled milestone and are never created or changed by refresh. Readback distinguishes `dispatch_required`, `running`, `dispatch_blocked`, `awaiting_main`, and terminal states, and exposes the selected worker profile plus real executor ref when bound. A compiled Milestone without a current execution decision or with incomplete unfinished Packet contracts is reported as policy revalidation required. A pending execution decision is confirmation required; an `awaiting_main` decision points to `milestone handoff take`. Actual Codex Subagent creation remains host-owned.

`status=ready` is never inferred from package files alone: project status readback must also be valid and free of current blockers. An old control plane remains a project blocker until the existing, explicitly confirmed `legacy-upgrade` flow completes; refresh only surfaces the inspection result and preserves the original task.

Lifecycle Hooks enter through the existing `runtime_bootstrap.py`. After a local reinstall, it resolves the most recently installed usable Auto Dev sibling bundle before falling back to the session's configured bundle. This updates Hook-side control readback without mutating project state; the Skill/runtime context of an already open conversation still uses the `fresh_session_required` boundary when it cannot prove the current package is loaded.
