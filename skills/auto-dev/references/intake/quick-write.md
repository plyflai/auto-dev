# Quick Write

Quick Write is the low-cost path for a one-shot, low-risk product patch. It is not a task tier and never creates a Task, Plan, proof, review, or finish receipt. In an uninitialized repository it remains stateless; inside an initialized Control Root it records one lightweight Activity under the nearest known Outcome after validation.

## Goal

Make the smallest requested source change directly, then run only the narrow validation that can establish the result.

## Eligible Work

Use this path when all of the following are true:

- There is one coherent user result, such as changing one field, adding one local branch, or adjusting one local condition.
- The expected change is a small update to existing source or documentation files.
- The current branch has no active Auto Dev task. An existing Project in `idle` or `selection_required` may use Quick Write.
- In a managed Project, the current user turn has a `clear` Intake classification. Hook rejects a pending/deep/clarify gate before the patch is applied.
- The current branch is not protected by the project's configured branch policy.
- The change does not alter a public API, schema, protocol, dependency, lockfile, configuration source of truth, permission, security boundary, release behavior, or control-plane state.

The Hook checks the actual `apply_patch`, not only the model's classification. The current bounded policy allows update-only patches for at most two approved text files and 40 changed lines. File creation, deletion, movement, path traversal, blocked control/configuration paths, and unsupported file types fall back to Product Write.

## Execution

1. State the result and the exact files to change in one short sentence.
2. Inspect only the relevant code and nearest validation entry.
3. Apply the smallest patch. Use `apply_patch`; do not use Bash to write product files.
4. Run `git diff --check` and the narrowest relevant test, build, or type check.
5. In a managed Project, record the validated patch with `activity record --intake-id ... --path ... --validation ...`; attach it to the nearest Outcome or the generated `unlinked` inbox. This is an Activity only, not a hidden Task.
6. Report the result, changed files, validation, and any unverified risk with a bilingual node receipt.

## Stop Rules

- If the Hook rejects the patch, stop Quick Write and route to Product Write.
- If the patch grows beyond the bounded shape, exposes a contract or architecture decision, or needs unrelated cleanup, route to Direct or Team Core. An already-large target file does not by itself disqualify a same-responsibility local fix; adding an independent responsibility, module boundary, or public abstraction does.
- Do not create or repair `.auto-dev` state from Quick Write. Control-plane recovery uses `auto_dev.py fix inspect`, then `fix apply` after user confirmation; only the canonical post-validation `activity record` mutation is permitted for managed Quick Write attribution.

## Completion

Quick Write is complete only when the requested small change is present and the targeted validation passes. It does not claim durable task continuity or replace Direct/Team evidence.
