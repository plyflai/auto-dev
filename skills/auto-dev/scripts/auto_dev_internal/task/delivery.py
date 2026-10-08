"""Direct and Team delivery command orchestration.

The stable CLI remains in runctl.py; these handlers receive that facade as
control so state, schema, and compatibility helpers keep one owner.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime

def command_start(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    storage_mode = control.workspace_storage_mode(repo)
    current, resolution = control.resolve_branch_task(repo, state)
    if current is not None:
        if current.get("status") == "review_ready":
            raise ValueError(
                "current branch task is review_ready; resume it for related work or archive it after user acceptance before starting another"
            )
        raise ValueError(f"run already active on current branch: {current.get('id')}")
    if resolution.get("candidates"):
        raise ValueError("current branch has an unarchived task; select or abandon it before starting another")
    scopes = control.normalize_scopes(repo, args.scope)
    if storage_mode == "local" and not scopes:
        raise ValueError("local No-Git workspaces require an explicit --scope before a task can start")
    requested_snapshot_scope = list(getattr(args, "snapshot_scope", []) or [])
    snapshot_scopes = (
        control.normalize_scopes(repo, requested_snapshot_scope)
        if requested_snapshot_scope
        else list(scopes)
    )
    branch = control.current_branch(repo)
    initial_status = control.current_status(repo)
    control.ensure_write_ready(state, branch, scopes, initial_status)
    project_context_id, primary_outcome_id, intake_id = control.prepare_task_attribution(
        repo,
        state,
        requested_context_id=args.project_context,
        requested_outcome_id=args.outcome_id,
        requested_intake_id=args.intake_id,
    )
    local_contract = control.contract_from_args(
        args,
        {},
        default_id=f"TASK-{datetime.now().astimezone().strftime('%Y%m%d%H%M%S')}-CONTRACT",
        default_mainline=str(args.task),
    )
    effective_contract, parent_contract = control.effective_contract_for_task(
        state,
        repo,
        project_context_id,
        primary_outcome_id,
        intake_id,
        local_contract,
    )
    task_coverage_ids = list(dict.fromkeys(str(value) for value in args.coverage_id))
    if effective_contract and task_coverage_ids:
        unknown_coverage = sorted(set(task_coverage_ids) - set(control.contract_coverage_ids(effective_contract)))
        if unknown_coverage:
            raise ValueError("task coverage is not declared by the inherited contract: " + ", ".join(unknown_coverage))
    if control.contract_is_strict(effective_contract) and control.contract_coverage_ids(effective_contract) and not task_coverage_ids:
        raise ValueError("strict contract task requires at least one --coverage-id contribution")
    classification = control.classify_capabilities(
        args.capability,
        args.skip,
        args.capability_evidence,
        require_complete=args.tier == "team",
    )
    if args.tier == "direct" and (classification["enabled"] or classification["skipped"]):
        raise ValueError("Direct cannot enable Team capability packs")
    budgets = {
        **(control.DEFAULT_TEAM_BUDGETS if args.tier == "team" else {}),
        **control.parse_budgets(args.budget),
    }
    outcome_values = [args.outcome_kind, args.primary_outcome, args.proof_id, args.proof_description]
    if any(value is not None for value in outcome_values) and not all(value is not None for value in outcome_values):
        raise ValueError(
            "start outcome contract requires --outcome-kind, --primary-outcome, "
            "--proof-id, and --proof-description together"
        )
    if args.document_authorization is not None and not all(value is not None for value in outcome_values):
        raise ValueError("--document-authorization requires a complete start outcome contract")
    outcome = None
    if all(value is not None for value in outcome_values):
        outcome_input = {
            "kind": args.outcome_kind,
            "primary": args.primary_outcome,
            "proofs": [{"id": args.proof_id, "description": args.proof_description}],
        }
        if args.document_authorization is not None:
            outcome_input["document_authorization"] = args.document_authorization
        outcome = control.normalize_outcome(outcome_input, {}, node_id="run")
    run_id = "AUTO-DEV-" + control.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    receipt = {
        "schema_version": control.SCHEMA_VERSION,
        "id": run_id,
        "status": "active",
        "tier": args.tier,
        "task": control.require_concrete("task", args.task),
        "requirement_receipt": control.require_concrete("requirement receipt", args.requirement_receipt),
        "confirmation_source": control.require_concrete("confirmation source", args.confirmation_source),
        "project_context_id": project_context_id,
        "primary_outcome_id": primary_outcome_id,
        "intake_id": intake_id,
        "acceptance": [control.require_concrete("acceptance", value) for value in args.acceptance],
        "route_evidence": [control.require_concrete("route evidence", value) for value in args.evidence],
        "planned_scope": scopes,
        "preservation_scope": snapshot_scopes,
        "workspace_mode": storage_mode,
        "validation_plan": [control.require_concrete("validation plan", value) for value in args.validation],
        "capabilities": classification,
        "budgets": budgets,
        "budget_usage": {key: 0 for key in budgets},
        "exhausted_budgets": [],
        "stop_conditions": control.merge_unique(
            args.stop_condition,
            control.DEFAULT_TEAM_STOP_CONDITIONS if args.tier == "team" else [],
        ),
        "repo_root": str(repo),
        "base_head": control.git_head(repo),
        "base_branch": branch,
        "initial_status": initial_status,
        "worktree_baseline": control.capture_worktree_baseline(repo, initial_status),
        "local_scope_baseline": control.local_scope_manifest(repo, scopes) if storage_mode == "local" else None,
        "snapshot": control.capture_snapshot(
            repo,
            state["snapshots"] / run_id,
            scopes,
            mode=getattr(args, "snapshot_mode", "auto"),
            preservation_scopes=snapshot_scopes,
        ),
        "started_at": control.now(),
        "state_revision": 0,
        "events": [],
        "outcome": outcome,
        "proofs": [],
        "contract_snapshot": effective_contract,
        "contract_parent_hash": parent_contract.get("hash") if parent_contract else None,
        "contract_status": control.contract_status(effective_contract),
        "contract_coverage_ids": task_coverage_ids,
    }
    control.write_active(state, receipt)
    control.bind_intake_to_task(state, project_context_id, intake_id, run_id)
    print(json.dumps({
        "status": "active",
        "id": run_id,
        "tier": args.tier,
        "project_context_id": project_context_id,
        "primary_outcome_id": primary_outcome_id,
        "intake_id": intake_id,
        "receipt": control.bilingual_receipt("🧾 Auto Dev", "task_attributed", f"task={run_id}"),
    }, ensure_ascii=False))
    return 0


def command_escalate(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_working_task(state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    if receipt["tier"] != "direct":
        raise ValueError("only an active Direct run can escalate to Team Core")
    classification = control.classify_capabilities(
        args.capability,
        args.skip,
        args.capability_evidence,
        require_complete=True,
    )
    receipt["tier"] = "team"
    receipt["capabilities"] = classification
    receipt["budgets"] = {
        **control.DEFAULT_TEAM_BUDGETS,
        **receipt.get("budgets", {}),
        **control.parse_budgets(args.budget),
    }
    receipt["stop_conditions"] = control.merge_unique(
        receipt.get("stop_conditions", []), control.DEFAULT_TEAM_STOP_CONDITIONS
    )
    control.sync_budget_state(receipt)
    receipt["schema_version"] = control.SCHEMA_VERSION
    receipt["events"].append({
        "type": "direct_to_team",
        "at": control.now(),
        "reasons": [control.require_concrete("escalation reason", value) for value in args.reason],
    })
    control.write_active(state, receipt, expected_revision=loaded_state_revision)
    print(json.dumps({"status": "active", "tier": "team", "capabilities": classification}, ensure_ascii=False))
    return 0


def command_capabilities(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_working_task(state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    if receipt["tier"] != "team":
        raise ValueError("capability packs can only be changed for Team Core")
    receipt["capabilities"] = control.classify_capabilities(
        args.enable,
        args.skip,
        args.capability_evidence,
        require_complete=True,
    )
    receipt["budgets"].update(control.parse_budgets(args.budget))
    control.sync_budget_state(receipt)
    receipt["schema_version"] = control.SCHEMA_VERSION
    receipt["events"].append({
        "type": "capability_reroute",
        "at": control.now(),
        "evidence": receipt["capabilities"]["evidence"],
    })
    control.write_active(state, receipt, expected_revision=loaded_state_revision)
    print(json.dumps(receipt["capabilities"], ensure_ascii=False))
    return 0


def command_event(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_working_task(state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    event_type = control.require_concrete("event type", args.event_type)
    if not re.fullmatch(r"[a-z][a-z0-9_]*", event_type):
        raise ValueError("event type must use lowercase snake_case")
    consumption = control.parse_budgets(args.consume)
    unknown = sorted(set(consumption) - set(receipt["budgets"]))
    if unknown:
        raise ValueError(f"cannot consume undefined budgets: {', '.join(unknown)}")
    already_exhausted = sorted(set(consumption) & set(receipt["exhausted_budgets"]))
    if already_exhausted:
        raise ValueError(
            "cannot consume exhausted budgets before reroute or replanning: "
            + ", ".join(already_exhausted)
        )
    for key, amount in consumption.items():
        receipt["budget_usage"][key] = receipt["budget_usage"].get(key, 0) + amount
    control.sync_budget_state(receipt)
    receipt["schema_version"] = control.SCHEMA_VERSION
    event = {
        "type": event_type,
        "at": control.now(),
        "summary": control.require_concrete("event summary", args.summary),
        "budget_consumption": consumption,
        "evidence": [control.require_concrete("event evidence", value) for value in args.evidence],
    }
    if args.node and not args.phase:
        raise ValueError("--node is only valid with --phase")
    if args.phase:
        action_id = control.require_continuity_id("action id", args.action_id or "")
        continuity = control.continuity_from_receipt(receipt)
        if continuity is None:
            raise ValueError("action phases require an initialized continuity plan")
        node_id, _ = control.require_action_node(continuity, args.node)
        pending = continuity.get("pending_action")
        if args.phase == "started":
            if pending:
                raise ValueError(f"pending action already exists: {pending.get('action_id')}")
            continuity["pending_action"] = {
                "action_id": action_id,
                "node_id": node_id,
                "kind": event_type,
                "summary": event["summary"],
                "started_at": event["at"],
                "expected": control.require_concrete("expected action result", args.expected) if args.expected else None,
                "owner": args.owner,
            }
        else:
            if not pending or pending.get("action_id") != action_id:
                raise ValueError(f"no matching pending action: {action_id}")
            pending_node_id = pending.get("node_id")
            if pending_node_id and pending_node_id != node_id:
                raise ValueError(
                    f"pending action belongs to node {pending_node_id}, not {node_id}"
                )
            continuity["pending_action"] = None
        event.update({"action_id": action_id, "node_id": node_id, "phase": args.phase})
    receipt["events"].append(event)
    control.write_active(state, receipt, expected_revision=loaded_state_revision)
    print(json.dumps({
        "status": receipt["status"],
        "node_id": event.get("node_id"),
        "budget_usage": receipt["budget_usage"],
        "exhausted_budgets": receipt["exhausted_budgets"],
    }, ensure_ascii=False))
    return 0


def command_evidence_link(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_working_task(state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    if args.state_revision != loaded_state_revision:
        raise ValueError(
            f"state revision conflict: expected {loaded_state_revision}, received {args.state_revision}"
        )
    continuity = control.continuity_from_receipt(receipt)
    if continuity is None or not continuity.get("plan", {}).get("nodes"):
        raise ValueError("evidence link requires an initialized continuity plan")
    plan_revision = int(continuity["plan"].get("revision", 0))
    if args.plan_revision != plan_revision:
        raise ValueError(
            f"evidence link plan revision conflict: expected {plan_revision}, received {args.plan_revision}"
        )
    node_id, _ = control.require_action_node(continuity, args.node)
    action_id = control.require_continuity_id("action id", args.action_id)
    action_events = [
        event for event in receipt.get("events", [])
        if isinstance(event, dict)
        and event.get("action_id") == action_id
        and event.get("phase") in {"started", "result", "failed"}
    ]
    if not action_events:
        raise ValueError(f"action evidence does not exist in the current task: {action_id}")
    if not any(event.get("phase") in {"result", "failed"} for event in action_events):
        raise ValueError("action evidence must have a result or failed phase before it can be linked")
    if all(event.get("node_id") for event in action_events):
        raise ValueError("action evidence is already node-bound; use the node event history directly")

    classification = args.classification
    summary = control.require_concrete("evidence link summary", args.summary)
    extra_evidence = [
        control.require_concrete("evidence link evidence", value) for value in args.evidence
    ]
    links = continuity.setdefault("evidence_links", [])
    existing = next(
        (
            link for link in links
            if isinstance(link, dict)
            and link.get("source_task_id") == receipt.get("id")
            and link.get("action_id") == action_id
        ),
        None,
    )
    if existing is not None:
        if (
            existing.get("node_id") == node_id
            and existing.get("classification") == classification
            and existing.get("summary") == summary
            and existing.get("evidence", []) == extra_evidence
        ):
            print(json.dumps({
                "status": "already_linked",
                "node_id": node_id,
                "action_id": action_id,
                "state_revision": loaded_state_revision,
            }, ensure_ascii=False))
            return 0
        raise ValueError(
            f"action evidence is already linked to node {existing.get('node_id')}; links are append-only"
        )

    link = {
        "id": f"action-{action_id}",
        "node_id": node_id,
        "source_task_id": receipt.get("id"),
        "action_id": action_id,
        "classification": classification,
        "summary": summary,
        "evidence": extra_evidence,
        "event_count": len(action_events),
        "first_at": action_events[0].get("at"),
        "last_at": action_events[-1].get("at"),
        "linked_at": control.now(),
    }
    links.append(link)
    continuity["updated_at"] = control.now()
    control.continuity_event(receipt, "action_evidence_linked", link=link)
    next_revision = control.write_active(state, receipt, expected_revision=loaded_state_revision)
    print(json.dumps({
        "status": "linked",
        "node_id": node_id,
        "action_id": action_id,
        "classification": classification,
        "state_revision": next_revision,
    }, ensure_ascii=False))
    return 0


def command_plan(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_working_task(state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    continuity = control.continuity_from_receipt(receipt)
    if continuity is None:
        continuity = {
            "schema_version": control.CONTINUITY_SCHEMA_VERSION,
            "goal": {"revision": 0, "statement": "", "acceptance": [], "source": ""},
            "plan": {"revision": 0, "reason": "", "nodes": [], "updated_at": None},
            "current_node": None,
            "next_action": None,
            "gaps": [],
            "last_checkpoint": None,
            "evidence_links": [],
            "durability": {"level": args.durability or "local", "updated_at": control.now()},
        }
        receipt["continuity"] = continuity

    current_revision = control.current_plan_revision(receipt)
    if args.base_revision != current_revision:
        raise ValueError(
            f"plan revision conflict: expected base {current_revision}, received {args.base_revision}"
        )
    payload = control.load_plan_input(args)
    raw_goal = payload.get("goal", {})
    if isinstance(raw_goal, str):
        raw_goal = {"statement": raw_goal}
    if not isinstance(raw_goal, dict):
        raise ValueError("continuity plan goal must be a string or object")
    previous_goal = continuity["goal"]
    goal_statement = control.require_concrete(
        "goal statement", str(raw_goal.get("statement", previous_goal.get("statement", receipt["task"])))
    )
    goal_acceptance = control.require_concrete_list(
        "goal acceptance", raw_goal.get("acceptance", previous_goal.get("acceptance", receipt["acceptance"]))
    )
    goal_source = control.require_concrete(
        "goal source", str(raw_goal.get("source", previous_goal.get("source", receipt["confirmation_source"])))
    )
    existing_nodes = {node["id"]: node for node in continuity["plan"].get("nodes", [])}
    nodes = control.validate_plan_nodes(payload.get("nodes"), existing_nodes)
    existing_plan = continuity.get("plan", {})
    strategy = str(payload.get("strategy", existing_plan.get("strategy", "legacy")))
    raw_relations = payload.get("relations", existing_plan.get("relations", []))
    relations = control.validate_rolling_plan(
        nodes, strategy=strategy, relations=raw_relations
    )
    control.validate_contract_plan(receipt, nodes)
    activation_time = control.now()
    for node in nodes:
        previous = existing_nodes.get(node["id"], {})
        if node["status"] == "active" and previous.get("status") != "active":
            node["activated_at"] = activation_time
    nodes, numbering_changes = control.normalize_plan_numbering(nodes)
    terminal_numbering_changes = [
        change for change in numbering_changes
        if change["id"] in existing_nodes
        and existing_nodes[change["id"]].get("status") in {"done", "superseded"}
    ]
    if terminal_numbering_changes and not args.numbering_change_confirmation:
        raise ValueError(
            "numbering changed for completed or superseded nodes; "
            "provide --numbering-change-confirmation after explicit approval"
        )
    node_ids = {node["id"] for node in nodes}
    current_node = payload.get("current_node", continuity.get("current_node"))
    if current_node is not None:
        current_node = control.require_continuity_id("current node", str(current_node))
        if current_node not in node_ids:
            raise ValueError(f"current node does not exist: {current_node}")
        if next(node for node in nodes if node["id"] == current_node)["status"] in {"done", "superseded"}:
            raise ValueError("current node cannot be done or superseded")
        current = next(node for node in nodes if node["id"] == current_node)
        if strategy == "rolling_graph" and current.get("node_role") not in {
            "work_packet", "integration",
        }:
            raise ValueError(
                "rolling graph current_node must be an executable work_packet or integration node"
            )
    goal_changed = (
        goal_statement != previous_goal.get("statement")
        or goal_acceptance != previous_goal.get("acceptance", [])
    )
    if goal_changed:
        if int(previous_goal.get("revision", 0)) > 0 and not args.goal_change_confirmation:
            raise ValueError(
                "goal or acceptance changed; provide --goal-change-confirmation after Requirement Diff approval"
            )
        continuity["goal"] = {
            "revision": int(previous_goal.get("revision", 0)) + 1,
            "statement": goal_statement,
            "acceptance": goal_acceptance,
            "source": args.goal_change_confirmation or goal_source,
            "updated_at": control.now(),
        }
        control.continuity_event(
            receipt,
            "goal_revised",
            goal_revision=continuity["goal"]["revision"],
            statement=goal_statement,
            acceptance=goal_acceptance,
            confirmation_source=continuity["goal"]["source"],
        )
    old_node_ids = set(existing_nodes)
    new_nodes = {node["id"]: node for node in nodes}
    new_node_ids = set(new_nodes)
    added_ids = sorted(new_node_ids - old_node_ids)
    removed_ids = sorted(old_node_ids - new_node_ids)
    changed_ids = sorted(
        node_id for node_id in old_node_ids & new_node_ids
        if existing_nodes[node_id] != new_nodes[node_id]
    )
    continuity["schema_version"] = control.CONTINUITY_SCHEMA_VERSION
    if strategy == "rolling_graph":
        children_by_parent: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            if node.get("parent_id"):
                children_by_parent.setdefault(str(node["parent_id"]), []).append(node)
        for node in nodes:
            if node.get("node_role") != "milestone":
                continue
            previous_state = node.get("milestone_state")
            milestone_state = dict(previous_state) if isinstance(previous_state, dict) else {}
            milestone_state.setdefault(
                "compilation_status",
                "compiled" if children_by_parent.get(node["id"]) else "thin",
            )
            milestone_state.setdefault("compilation_revision", 0)
            milestone_state.setdefault("integration_mode", "accumulated_workspace")
            milestone_state.setdefault("integration_status", "not_ready")
            milestone_state.setdefault("review_result", None)
            milestone_state.setdefault("exit_snapshot_id", None)
            node["milestone_state"] = milestone_state
    graph_sha256 = control.plan_graph_digest(nodes, relations)
    continuity["plan"] = {
        "revision": current_revision + 1,
        "reason": control.require_concrete("plan reason", args.reason),
        "strategy": strategy,
        "nodes": nodes,
        "relations": relations,
        "graph_sha256": graph_sha256,
        "contract_hash": control.strict_receipt_contract_hash(receipt),
        "updated_at": control.now(),
    }
    continuity["current_node"] = current_node
    if strategy == "rolling_graph":
        rolling_roots = [
            node for node in nodes if node.get("node_role") == "milestone"
        ]
        compilation_focus = payload.get("compilation_focus")
        if compilation_focus is None:
            compilation_focus = next(
                (
                    node["id"] for node in rolling_roots
                    if node.get("milestone_state", {}).get("compilation_status")
                    in {"thin", "recompile_required"}
                    and all(
                        next(candidate for candidate in rolling_roots if candidate["id"] == dependency)
                        .get("milestone_state", {}).get("review_result") == "accepted"
                        for dependency in node.get("depends_on", [])
                    )
                ),
                None,
            )
        elif compilation_focus not in {node["id"] for node in rolling_roots}:
            raise ValueError("rolling graph compilation_focus must reference a milestone")
        continuity["compilation_focus"] = compilation_focus
        continuity["execution_focus"] = current_node
        continuity.setdefault("exit_snapshots", [])
        control.refresh_rolling_frontier(continuity)
    else:
        continuity.pop("compilation_focus", None)
        continuity.pop("execution_focus", None)
    next_action = args.next_action or payload.get("next_action")
    continuity["next_action"] = control.require_concrete("next action", str(next_action)) if next_action else continuity.get("next_action")
    continuity["durability"] = {
        "level": args.durability or continuity.get("durability", {}).get("level", "local"),
        "updated_at": control.now(),
    }
    continuity["updated_at"] = control.now()
    control.continuity_event(
        receipt,
        "plan_revised",
        plan_revision=continuity["plan"]["revision"],
        reason=continuity["plan"]["reason"],
        current_node=current_node,
        node_ids=[node["id"] for node in nodes],
        added_ids=added_ids,
        removed_ids=removed_ids,
        changed_ids=changed_ids,
        numbering_changes=numbering_changes,
        numbering_change_confirmation=args.numbering_change_confirmation if terminal_numbering_changes else None,
    )
    control.write_active(state, receipt, expected_revision=loaded_state_revision)
    milestone_summary = [
        {
            "id": node["id"],
            "display_code": node.get("display_code"),
            "node_kind": node.get("node_kind", "delivery"),
            "gate": (node.get("verification") or {}).get("gate") if isinstance(node.get("verification"), dict) else None,
            "placement_reason": (node.get("verification") or {}).get("placement_reason") if isinstance(node.get("verification"), dict) else None,
        }
        for node in nodes
        if node.get("node_kind", "delivery") in {"verification", "release"}
    ]
    print(json.dumps({
        "status": "updated",
        "goal_revision": continuity["goal"]["revision"],
        "plan_revision": continuity["plan"]["revision"],
        "strategy": strategy,
        "graph_sha256": graph_sha256,
        "current_node": current_node,
        "numbering_changes": numbering_changes,
        "numbering_change_confirmation": args.numbering_change_confirmation if terminal_numbering_changes else None,
        "milestones": milestone_summary,
    }, ensure_ascii=False))
    return 0


def command_checkpoint(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_working_task(state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    continuity = control.continuity_from_receipt(receipt)
    if continuity is None or not continuity["plan"].get("nodes"):
        raise ValueError("checkpoint requires an initialized continuity plan")
    nodes = {node["id"]: node for node in continuity["plan"]["nodes"]}
    plan_revision = int(continuity["plan"].get("revision", 0))
    if args.plan_revision is not None and args.plan_revision != plan_revision:
        raise ValueError(
            f"checkpoint plan revision conflict: expected {plan_revision}, received {args.plan_revision}"
        )
    if args.state_revision is not None and args.state_revision != loaded_state_revision:
        raise ValueError(
            f"checkpoint state revision conflict: expected {loaded_state_revision}, received {args.state_revision}"
        )
    node_id = args.node or continuity.get("current_node")
    if not node_id:
        raise ValueError("checkpoint requires --node when no current node exists")
    node_id = control.require_continuity_id("node id", node_id)
    if node_id not in nodes:
        raise ValueError(f"checkpoint node does not exist: {node_id}")
    node = nodes[node_id]
    rolling = continuity.get("plan", {}).get("strategy") == "rolling_graph"
    if rolling and node.get("node_role") == "milestone":
        raise ValueError("rolling milestones can only complete through milestone review")
    status = args.status or node.get("status", "active")
    if status not in control.CONTINUITY_NODE_STATUSES:
        raise ValueError(f"invalid checkpoint status: {status}")
    if status in {"active", "done"}:
        unfinished_dependencies = [
            dependency for dependency in node.get("depends_on", [])
            if not control.node_dependency_satisfied(nodes[dependency], continuity)
        ]
        if unfinished_dependencies:
            raise ValueError(
                f"node {node_id} has unfinished dependencies: {', '.join(unfinished_dependencies)}"
            )
    if status == "done":
        unfinished_children = [
            child["id"] for child in nodes.values()
            if child.get("parent_id") == node_id and child.get("status") not in {"done", "superseded"}
        ]
        if unfinished_children:
            raise ValueError(
                f"node {node_id} has unfinished children: {', '.join(unfinished_children)}"
            )
        outcome = node.get("outcome")
        if outcome:
            expected_outcome_digest = control.outcome_digest(outcome)
            required_proofs = {proof["id"] for proof in outcome.get("proofs", [])}
            passed_proofs = {
                proof_id
                for proof_spec in outcome.get("proofs", [])
                for proof_id in [str(proof_spec.get("id"))]
                for proof in [control.latest_proof(continuity.get("proofs", []), node_id=node_id, proof_id=proof_id)]
                if proof
                and proof.get("status") == "passed"
                and control.proof_is_fresh(
                    proof,
                    outcome=outcome,
                    repo=repo,
                    plan_revision=plan_revision,
                    node=node,
                )
                and proof.get("outcome_sha256") == expected_outcome_digest
            }
            missing_proofs = sorted(required_proofs - passed_proofs)
            if missing_proofs:
                raise ValueError(
                    f"node {node_id} primary outcome is unproven; missing passed proofs: "
                    + ", ".join(missing_proofs)
                )
            control.validate_node_contract_proofs(repo, receipt, continuity, node)
        else:
            control.continuity_event(
                receipt,
                "legacy_outcome_unenforced",
                node_id=node_id,
                reason="node predates outcome contracts",
            )
    if status == "blocked":
        if not args.gap_id or not args.gap_summary:
            raise ValueError("blocked checkpoint requires --gap-id and --gap-summary")
        if not args.evidence:
            raise ValueError("blocked checkpoint requires evidence of attempts, constraints, or failure")
    node["status"] = status
    if status == "active" and not node.get("activated_at"):
        node["activated_at"] = control.now()
    if rolling and status == "done" and node.get("node_role") in {"work_packet", "integration"}:
        proof_attempts = []
        for proof_spec in (node.get("outcome") or {}).get("proofs", []):
            latest = control.latest_proof(
                continuity.get("proofs", []),
                node_id=node_id,
                proof_id=str(proof_spec.get("id")),
            )
            if latest is not None:
                proof_attempts.append(latest.get("attempt_id"))
        result_ref = {
            "node_id": node_id,
            "node_role": node.get("node_role"),
            "contract_sha256": node.get("contract_sha256"),
            "compilation_revision": node.get("execution_base", {}).get("compilation_revision"),
            "scope": list(node.get("write_scope", [])),
            "scope_sha256": control.workspace_scope_digest(repo, node.get("write_scope", [])),
            "head": control.git_head(repo),
            "product_status": control.workspace_product_status(control.current_status(repo)),
            "proof_attempt_ids": sorted({str(value) for value in proof_attempts if value}),
            "completed_at": control.now(),
        }
        if node.get("result_ref"):
            node.setdefault("result_history", []).append(node["result_ref"])
        node["result_ref"] = result_ref
        milestone = nodes.get(str(node.get("parent_id")))
        if isinstance(milestone, dict):
            milestone_state = milestone.setdefault("milestone_state", {})
            if node.get("node_role") == "integration":
                milestone_state["compilation_status"] = "integration_ready"
                milestone_state["integration_status"] = "ready"
            elif all(
                child.get("status") in {"done", "superseded"}
                for child in nodes.values()
                if child.get("parent_id") == milestone.get("id")
                and child.get("node_role") == "work_packet"
            ):
                milestone_state["compilation_status"] = "integration_ready"
                milestone_state["integration_status"] = "ready"
    next_node = args.next_node
    if rolling and status in {"done", "superseded"}:
        continuity["current_node"] = None
        continuity["execution_focus"] = None
        frontier = control.refresh_rolling_frontier(continuity)
        if next_node and next_node not in frontier.get("work_packets", []):
            raise ValueError(f"next rolling node is not in the ready frontier: {next_node}")
        next_node = next_node or frontier.get("next_execution")
        candidate = nodes.get(str(next_node)) if next_node else None
        milestone = nodes.get(str(node.get("parent_id")))
        milestone_state = (
            milestone.get("milestone_state", {}) if isinstance(milestone, dict) else {}
        )
        decision = milestone_state.get("execution_decision")
        work_packets_complete = bool(
            isinstance(milestone, dict)
            and node.get("node_role") == "work_packet"
            and all(
                child.get("status") in {"done", "superseded"}
                for child in nodes.values()
                if child.get("parent_id") == milestone.get("id")
                and child.get("node_role") == "work_packet"
            )
        )
        if (
            isinstance(decision, dict)
            and decision.get("selected_mode") in {"single_worker", "multi_worker"}
            and decision.get("boundary") == "before_integration"
            and (
                work_packets_complete
                or (candidate is not None and candidate.get("node_role") == "integration")
            )
        ):
            decision.update({
                "status": "awaiting_main",
                "owner": "main_session",
                "handoff_status": "required",
                "handoff_reason": "packets_complete_before_integration",
            })
            continuity["next_action"] = "Main session owns Integration and Milestone Review"
            control.continuity_event(
                receipt,
                "packet_handoff_required",
                milestone_id=milestone.get("id") if isinstance(milestone, dict) else None,
                packet_id=node_id,
                stop_before="integration",
            )
            next_node = None
    if next_node:
        next_node = control.require_continuity_id("next node", next_node)
        if next_node not in nodes:
            raise ValueError(f"next node does not exist: {next_node}")
        unfinished_dependencies = [
            dependency for dependency in nodes[next_node].get("depends_on", [])
            if not control.node_dependency_satisfied(nodes[dependency], continuity)
        ]
        if unfinished_dependencies:
            raise ValueError(
                f"next node {next_node} has unfinished dependencies: {', '.join(unfinished_dependencies)}"
            )
        if nodes[next_node]["status"] == "planned":
            nodes[next_node]["status"] = "active"
            nodes[next_node]["activated_at"] = control.now()
    if next_node:
        continuity["current_node"] = next_node
        if rolling:
            continuity["execution_focus"] = next_node
    elif status in {"blocked", "active"}:
        continuity["current_node"] = node_id
    elif status in {"done", "superseded"}:
        continuity["current_node"] = None
        if rolling:
            continuity["execution_focus"] = None
    if rolling:
        control.refresh_rolling_frontier(continuity)
    if args.next_action:
        continuity["next_action"] = control.require_concrete("next action", args.next_action)
    checkpoint = {
        "node_id": node_id,
        "status": status,
        "summary": control.require_concrete("checkpoint summary", args.summary),
        "evidence": [control.require_concrete("checkpoint evidence", value) for value in args.evidence],
        "branch": control.current_branch(repo),
        "head": control.git_head(repo),
        "at": control.now(),
    }
    if status == "done" and node.get("outcome"):
        checkpoint["outcome_sha256"] = control.outcome_digest(node["outcome"])
        latest_required_proofs = [
            control.latest_proof(
                continuity.get("proofs", []),
                node_id=node_id,
                proof_id=str(proof_spec.get("id")),
            )
            for proof_spec in node["outcome"].get("proofs", [])
        ]
        checkpoint["proof_attempts"] = [
            {
                "node_id": proof.get("node_id"),
                "proof_id": proof.get("proof_id"),
                "attempt_id": proof.get("attempt_id"),
                "attempt_index": proof.get("attempt_index", 1),
                "status": proof.get("status"),
                "outcome_sha256": proof.get("outcome_sha256"),
            }
            for proof in latest_required_proofs
            if proof is not None
        ]
        for proof in latest_required_proofs:
            if proof is not None:
                proof["validated_checkpoint"] = {
                    "status": "passed",
                    "at": checkpoint["at"],
                    "node_id": node_id,
                    "outcome_sha256": checkpoint["outcome_sha256"],
                    "plan_revision": plan_revision,
                }
    continuity["last_checkpoint"] = checkpoint
    if args.gap_id or args.gap_summary:
        if not args.gap_id or not args.gap_summary:
            raise ValueError("--gap-id and --gap-summary must be supplied together")
        gap_id = control.require_continuity_id("gap id", args.gap_id)
        gaps = continuity.setdefault("gaps", [])
        existing_gap = next((gap for gap in gaps if gap.get("id") == gap_id), None)
        gap = existing_gap or {"id": gap_id, "opened_at": control.now()}
        gap.update({
            "status": "open",
            "summary": control.require_concrete("gap summary", args.gap_summary),
            "owner": args.gap_owner,
            "node_id": node_id,
            "blocking": not args.non_blocking,
            "updated_at": control.now(),
        })
        if existing_gap is None:
            gaps.append(gap)
        control.continuity_event(receipt, "gap_opened", gap=gap)
    for gap_id in args.resolve_gap:
        normalized_gap_id = control.require_continuity_id("gap id", gap_id)
        gap = next((gap for gap in continuity.get("gaps", []) if gap.get("id") == normalized_gap_id), None)
        if gap is None:
            raise ValueError(f"gap does not exist: {normalized_gap_id}")
        gap.update({"status": "resolved", "resolved_at": control.now(), "updated_at": control.now()})
        control.continuity_event(receipt, "gap_resolved", gap_id=normalized_gap_id)
    continuity["updated_at"] = control.now()
    control.continuity_event(receipt, "node_checkpointed", checkpoint=checkpoint, current_node=continuity.get("current_node"))
    control.write_active(state, receipt, expected_revision=loaded_state_revision)
    print(json.dumps({
        "status": "updated",
        "node": node_id,
        "node_status": status,
        "current_node": continuity.get("current_node"),
        "open_gaps": sum(1 for gap in continuity.get("gaps", []) if gap.get("status") == "open"),
    }, ensure_ascii=False))
    return 0
