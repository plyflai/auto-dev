# Action Attribution

## Boundary

`event --phase` records an action, not progress. It is valid only when the action is bound to the current executable continuity node. A task-level event must never stand in for a new plan node, current node, gap, checkpoint, proof, or user approval.

Before a real-device, external, long-running, or irreversible action:

1. Read `auto_dev.py status --compact --strict`.
2. If `current_node` is empty or does not cover the action, revise the plan and activate or checkpoint the intended node before the action begins.
3. Open the action with `event --phase started --node <current-node> --action-id ...`.
4. For a managed dependency, use a matching runtime-bound lease. If no usable lease exists, open a bounded `deps preflight` permit tied to that same `action-id`; do not source an unmanaged environment as a substitute.
5. Perform the action only after the start receipt and lease/permit gate succeed; close the action with `result` or `failed` using the same node, then close the preflight permit with actual evidence.

An executable node may be `active` or `blocked` when the action is the concrete attempt to resolve its known constraint. The Agent still decides whether the plan, scope, acceptance, or Requirement Diff requires user confirmation; the CLI only validates the resulting attribution.

## Legacy Evidence

Old action events without a `node_id` remain immutable task history. Do not restore a superseded task or edit the source event to make it look current. After creating or activating the correct node, use `auto_dev.py evidence link` with current plan/state revisions, the current node, the historical `action_id`, and a `partial`, `failed`, or `rejected` classification.

The command writes one append-only link in the selected task's continuity state. It does not convert supporting evidence into a passed proof, alter the original action event, or create a plan node automatically.

## Detection And Stop Rule

`status` exposes `unattributed_actions` when an action phase has no valid node binding and no evidence link. Strict status reports `unattributed_action_evidence` as `needs_reconcile`; stop affected product and external work, link or replan the evidence, then read status again.

The progress page shows this condition as an operational warning. It intentionally does not render the normal event ledger as a second timeline.

## Hook Boundary

The lifecycle Hook can reject directly recognizable `adb` capture/input/install commands and Frida actions without an opened, node-bound pending action. For Frida CLI, `frida-ps`, and the project Python probe it also checks the dependency gate: the actual argv must start with a binding stored in an active lease, or in an unexpired preflight permit for the current action. It cannot prove the meaning of manual UI actions, unknown scripts, or arbitrary wrappers. The CLI action receipt and dependency lease are the durable hard gates; the Hook is defense in depth.
