# Recovery Conversation Flow

When refresh returns `fresh_session_required`, the Skill/Agent reports the receipt and asks the host layer to create a recovery conversation. The CLI and Hook cannot create Codex conversations themselves. This only loads the current package/Hook contract in the old session; it does not itself upgrade `.auto-dev`.

The host recovery conversation must:

1. open in the same local checkout and preserve the current branch;
2. avoid creating a worktree for this same-checkout recovery;
3. start with a bounded prompt to run `$auto-dev:refresh` and continue the existing Auto Dev task;
4. let `SessionStart` reuse the existing `.auto-dev` task without creating a new Intake or task;
5. return a clickable conversation/task link to the user;
6. stop if the new refresh result is not `ready`; if it reports a project control-plane upgrade, continue through the existing Legacy Upgrade inspect/confirm route without creating another task.

If host conversation creation fails, report `fresh_session_required` and the manual next step. Never fabricate `ready`, and never use `handoff import` for the same checkout/branch/task. Existing handoff import is reserved for a genuinely different control root and may reject a branch that already has an active task.
