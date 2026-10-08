# Rolling Milestones

Use `strategy=rolling_graph` for long or uncertainty-bearing work that benefits from a thin Milestone roadmap and fresh compilation before each execution slice. Direct one-shot work and short stable plans remain `legacy`.

## Plan Shape

- Root nodes are Milestones in a DAG. Future Milestones stay thin: goal, acceptance, coverage, dependencies, and status only.
- Only `compilation_focus` may be compiled. A Milestone becomes eligible after all dependency Milestones are accepted.
- `milestone compile inspect` captures current repository, worktree, dependency Exit Snapshots, and CodeGraph evidence. CodeGraph is static evidence, not a semantic oracle.
- The planning model submits one local DAG through `milestone compile apply`: one or more `work_packet` nodes plus exactly one `integration` node that depends on every Packet.
- Root capabilities establish the policy floor; packet-level verification, review, and merge policy are derived only after the current packet DAG is compiled.

## Work Packet Contract

Every Packet and Integration node must declare a concrete target, path-level `write_scope`, owned concepts, provided/consumed contracts, exclusive claims, observable assertions, proof recipes, and escalation routes. Proof recipes use argument arrays and may declare `cwd`, existing or packet-produced `inputs`, exact `observed_paths`, an evidence file/schema, and an optional `preflight_argv`. Compile validates executable closure; only an explicit preflight runs, inside a temporary worktree, and never replaces the authoritative Proof.

Packet-local policy fields are optional for compatibility and normalized at compile time:

- `execution_profile`: `bounded` or `governed`.
- `required_capabilities`: capabilities already enabled by the Root Team receipt.
- `verification_policy`: required and post-merge evidence, plus blocking behavior.
- `review_policy`: `proof_only`, `quick`, `strong`, or `full`.
- `merge_policy`: accumulated workspace or worktree merge queue, conflict owner, and pre-merge validation.
- `model_profile`: a packet role hint. The execution decision separately resolves a worker profile; the default `light_worker` records `gpt-5.6-luna/high`. A non-built-in provider uses `external_worker` and must declare provider/model/reasoning during lane selection. In both cases the host must bind the real executor before work begins.

The compilation payload may also include a `policy` envelope with `execution_topology`, `merge_mode`, `verification_floor`, `integration_required`, `review_budget`, and `conflict_owner`. This envelope is a plan contract, not a claim that a worker runtime or merge queue is already active.

Compilation ends at an explicit execution decision gate. The Milestone stores `execution_decision.status=pending` and does not activate a Packet. The Root conversation must select one lane with `milestone execution select`: `main_session`, `single_worker`, or `multi_worker`. Worker lanes resolve a visible profile and enter `dispatch_required`; `milestone worker bind` records either the matching real executor ref and moves to `running`, or a concrete `dispatch_blocked` reason. It never searches credentials, relays, or historical configuration. `single_worker` is allowed without `parallel-work`; `multi_worker` requires both the compiled multi-agent topology and the Root `parallel-work` capability.

Compilation rejects unordered overlapping write scopes, ownership or exclusive-claim collisions, missing or ambiguous contract providers, and contract consumers that lack an ordering dependency. It records static impact relations such as `write_conflict`, `contract_dependency`, `shared_blast_radius`, `revalidation`, `resource_conflict`, and `uncertain`. Phase 1 executes one node at a time, but status and UI retain parallel-eligible groups and the compiled execution policy for later delegation.

## Execution And Acceptance

1. Execute only `execution_focus`. Explicit product-write paths must stay inside that node's `write_scope`.
2. Run each declared recipe through `proof`; actual argv and evidence must match the compiled recipe.
3. `checkpoint done` stores a scoped result ref and advances the Ready Frontier. Ordinary checkpoint cannot complete a Milestone.
4. Worker execution is bounded by `prepare(dispatch_required) → bind(running|dispatch_blocked) → capture(awaiting_main) → host finalize`. The Worker returns a Result Contract but never runs authoritative Proof, Checkpoint, Integration, Review, or frontier advancement. The host finalize path runs the declared Packet Proof recipes and reuses Checkpoint.
5. When a worker lane uses `before_integration`, the final Packet Checkpoint enters `awaiting_main`. The Main session uses `milestone handoff take`; this changes ownership without changing the selected lane, then activates Integration under the compiled merge policy. Model availability and actual subagent creation remain host responsibilities; the control plane records the promised profile and the bound executor instead of guessing.
6. Record Integration, then run Milestone review. Acceptance requires all nodes done, fresh required proofs, closed coverage, no blocking gaps, and integrated status. New proofs prefer recipe `observed_paths` for freshness; older proofs keep their prior scope semantics. Once a Milestone is accepted with an Exit Snapshot, its child proofs do not re-enter upgrade revalidation merely because later Milestones add sibling files.
7. `accepted` generates an Exit Snapshot and only then opens the next Milestone for fresh compilation.

Failure routes are first-class: `packet_rework_required` invalidates that Packet and Integration execution base; `milestone_recompile_required` recompiles the local graph from current facts; `roadmap_revision_required` returns to the thin Milestone DAG. Recompile may retain completed Packet evidence only when its contract and execution base remain valid.

## Commands

```text
auto_dev.py milestone frontier
auto_dev.py milestone compile inspect|apply
auto_dev.py milestone execution inspect|select
auto_dev.py milestone execution revalidate
auto_dev.py milestone handoff take
auto_dev.py milestone integration inspect|record
auto_dev.py milestone review inspect|record
auto_dev.py milestone worker prepare|bind|inspect|capture|apply|finalize|cleanup
```

All inspect/frontier commands are read-only. `compile apply` also requires the `repository_facts_sha256` returned by the latest inspect; fact drift forces a new inspect. Mutations require current plan and state revisions. The CLI resolves a declared worker profile and records the real executor binding, but it does not create a Codex subagent. `refresh` never selects a lane, dispatches a Worker, runs Proof, or mutates the project. A one-packet handoff/document task without a Team hard condition should remain Direct instead of creating a Rolling Milestone solely for ceremony.
