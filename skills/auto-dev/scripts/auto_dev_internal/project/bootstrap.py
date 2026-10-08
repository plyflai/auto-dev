"""Bootstrap inspection, plan adoption, and control-plane initialization."""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
from datetime import datetime
from typing import Any

def bootstrap_candidate(control, repo: pathlib.Path, state: dict[str, pathlib.Path]) -> dict[str, Any] | None:
    for source, path in (("active.json", state["active"]), ("active.bak", state["active"].with_suffix(".bak"))):
        receipt, _ = control.readable_receipt(path)
        if receipt is not None:
            return {
                "source": source,
                "id": receipt.get("id"),
                "task": receipt.get("task"),
                "status": receipt.get("status"),
                "schema_version": receipt.get("schema_version", 1),
                "goal_available": bool(
                    receipt.get("task")
                    or (
                        receipt.get("continuity", {}).get("goal", {}).get("statement")
                        if isinstance(receipt.get("continuity"), dict)
                        else None
                    )
                ),
                "plan_available": control.continuity_has_plan(receipt),
            }
    if state["runs"].exists():
        candidates = sorted(state["runs"].glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
        for path in candidates:
            receipt, _ = control.readable_receipt(path)
            if receipt is not None:
                return {
                    "source": str(path.relative_to(repo)),
                    "id": receipt.get("id"),
                    "task": receipt.get("task"),
                    "status": receipt.get("status"),
                    "schema_version": receipt.get("schema_version", 1),
                    "goal_available": bool(receipt.get("task")),
                    "plan_available": control.continuity_has_plan(receipt),
                }
    return None


def bootstrap_inspection(control, repo: pathlib.Path) -> dict[str, Any]:
    state = control.paths(repo)
    active, active_error = control.readable_receipt(state["active"])
    backup, backup_error = control.readable_receipt(state["active"].with_suffix(".bak"))
    candidate = control.bootstrap_candidate(repo, state)
    project = control.load_project(state, repo)
    active_projection_error = active_error
    if project is not None:
        resolved, resolution = control.resolve_branch_task(repo, state)
        if resolved is not None:
            active = resolved
            active_error = None
            candidate = {
                "source": f"tasks/{resolved.get('id')}.json",
                "id": resolved.get("id"),
                "task": resolved.get("task"),
                "status": resolved.get("status"),
                "schema_version": resolved.get("schema_version", 1),
                "goal_available": bool(resolved.get("task")),
                "plan_available": control.continuity_has_plan(resolved),
            }
        else:
            active = None
            active_error = None
            candidate = None
    has_control = project is not None or any(
        path.exists() for path in (state["active"], state["active"].with_suffix(".bak"), state["history"], state["runs"])
    )
    if active is None and active_error:
        classification = "corrupt_recoverable" if backup is not None else "corrupt_unrecoverable"
        bootstrap_status = "needs_recovery"
        survey_required = False
    elif active is None and backup is not None:
        classification = "corrupt_recoverable"
        bootstrap_status = "needs_recovery"
        survey_required = False
    elif active is None:
        classification = "legacy_recoverable" if has_control and candidate else "no_control"
        bootstrap_status = "needs_plan_confirmation" if classification != "no_control" else "needs_plan_discovery"
        survey_required = True
    else:
        previous_schema = int(active.get("schema_version", 1))
        try:
            continuity = control.continuity_from_receipt(active)
        except (AttributeError, TypeError, ValueError):
            continuity = None
            malformed_continuity = True
        else:
            malformed_continuity = False
        if previous_schema > control.SCHEMA_VERSION:
            classification = "current_needs_reconcile"
            bootstrap_status = "needs_reconcile"
            survey_required = False
        elif malformed_continuity:
            classification = "current_needs_reconcile"
            bootstrap_status = "needs_reconcile"
            survey_required = False
        elif not continuity or not continuity.get("plan", {}).get("nodes"):
            classification = "legacy_recoverable"
            bootstrap_status = "needs_plan_confirmation"
            survey_required = True
        else:
            try:
                existing_nodes = {
                    node["id"]: node for node in continuity["plan"]["nodes"]
                    if isinstance(node, dict) and node.get("id")
                }
                control.validate_plan_nodes(continuity["plan"]["nodes"], existing_nodes)
                status_payload = control.build_status_payload(repo, state, view="compact")
                continuity_status = status_payload.get("continuity_status")
                classification = (
                    "current_ready"
                    if continuity_status in {"ready", "review_ready"}
                    else "current_needs_reconcile"
                )
                bootstrap_status = continuity_status if classification == "current_ready" else "needs_reconcile"
            except (KeyError, TypeError, ValueError):
                classification = "current_needs_reconcile"
                bootstrap_status = "needs_reconcile"
            survey_required = False
    dirty_paths = [control.status_path(line) for line in control.workspace_product_status(control.current_status(repo))]
    return {
        "status": "inspected",
        "classification": classification,
        "bootstrap_status": bootstrap_status,
        "survey_required": survey_required,
        "goal_available": bool(candidate and candidate.get("goal_available")),
        "plan_available": bool(candidate and candidate.get("plan_available")),
        "candidate": candidate,
        "active_error": active_error,
        "active_projection_error": active_projection_error,
        "backup_error": backup_error,
        "project_id": project.get("project_id") if project else None,
        "legacy_upgrade": control.control_plane_upgrade_projection(project, repo=repo, state=state) if project else {
            "status": "uninitialized",
            "current_version": None,
            "target_version": control.CONTROL_PLANE_UPGRADE_VERSION,
            "pending_step_ids": [],
        },
        "branch": control.current_branch(repo),
        "head": control.git_head(repo),
        "dirty_paths": dirty_paths,
        "dirty_count": len(dirty_paths),
        "repo_fingerprint": control.repo_fingerprint(repo),
        "codegraph": (repo / ".codegraph").is_dir(),
    }


def load_bootstrap_plan(control, args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], str]:
    payload = control.load_plan_input(args)
    raw_goal = payload.get("goal", {})
    if isinstance(raw_goal, str):
        raw_goal = {"statement": raw_goal}
    if not isinstance(raw_goal, dict):
        raise ValueError("bootstrap plan goal must be a string or object")
    goal_statement = control.require_concrete("goal statement", str(raw_goal.get("statement", "")))
    goal_acceptance = control.require_concrete_list("goal acceptance", raw_goal.get("acceptance", []))
    nodes = control.validate_plan_nodes(payload.get("nodes"), {})
    nodes, _ = control.normalize_plan_numbering(nodes)
    issues = control.plan_state_issues(nodes)
    if issues:
        raise ValueError("bootstrap plan has invalid state: " + json.dumps(issues, ensure_ascii=False))
    current_node = payload.get("current_node")
    if not current_node:
        raise ValueError("bootstrap plan requires a current_node")
    current_node = control.require_continuity_id("current node", str(current_node))
    current = next(node for node in nodes if node["id"] == current_node)
    if current.get("status") not in {"active", "blocked"}:
        raise ValueError("bootstrap current node must be active or blocked")
    if current.get("status") == "active" and not current.get("activated_at"):
        current["activated_at"] = control.now()
    next_action = control.require_concrete("next action", str(payload.get("next_action", "")))
    goal = {"revision": 1, "statement": goal_statement, "acceptance": goal_acceptance}
    return payload, goal, nodes, next_action


def command_bootstrap_inspect(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    print(json.dumps(control.bootstrap_inspection(repo), ensure_ascii=False, indent=2))
    return 0


def command_bootstrap_apply(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    payload, goal, nodes, next_action = control.load_bootstrap_plan(args)
    requirement_receipt = control.require_concrete("requirement receipt", args.requirement_receipt)
    goal_source = control.require_concrete("goal confirmation source", args.goal_confirmation_source)
    plan_source = control.require_concrete("plan confirmation source", args.plan_confirmation_source)
    scopes = control.normalize_scopes(repo, args.scope)
    requested_snapshot_scope = list(getattr(args, "snapshot_scope", []) or [])
    snapshot_scopes = (
        control.normalize_scopes(repo, requested_snapshot_scope)
        if requested_snapshot_scope
        else list(scopes)
    )
    branch = control.current_branch(repo)
    initial_status = control.current_status(repo)
    control.ensure_write_ready(state, branch, scopes, initial_status)
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
    existing, existing_resolution = control.resolve_branch_task(repo, state)
    if existing is None and existing_resolution.get("candidates"):
        raise ValueError("current branch requires an explicit task selection before bootstrap apply")
    if args.mode == "fresh" and existing is not None:
        raise ValueError(f"fresh bootstrap requires no active run: {existing.get('id')}")
    if args.mode in {"adopt", "replace"}:
        if existing is None:
            raise ValueError(f"{args.mode} bootstrap requires an existing readable active receipt")
        if control.require_concrete("expected task id", args.expected_task_id) != str(existing.get("id", "")):
            raise ValueError("expected task id does not match active receipt")
        if args.mode == "adopt" and control.continuity_has_plan(existing):
            raise ValueError("adopt only accepts a legacy active receipt without a usable plan; use replace")
    if args.mode == "fresh" and state["active"].with_suffix(".bak").exists() and existing is None:
        raise ValueError("active backup exists; recover or explicitly replace the control state")
    inherited_contract = (
        copy.deepcopy(existing.get("contract_snapshot"))
        if existing and isinstance(existing.get("contract_snapshot"), dict)
        else None
    )
    run_id = "AUTO-DEV-" + datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    surveyed_at = control.now()
    receipt = {
        "schema_version": control.SCHEMA_VERSION,
        "state_revision": 1,
        "id": run_id,
        "status": "active",
        "tier": args.tier,
        "task": goal["statement"],
        "requirement_receipt": requirement_receipt,
        "confirmation_source": goal_source,
        "project_context_id": existing.get("project_context_id") if existing else None,
        "primary_outcome_id": existing.get("primary_outcome_id") if existing else None,
        "intake_id": existing.get("intake_id") if existing else None,
        "acceptance": goal["acceptance"],
        "route_evidence": [control.require_concrete("route evidence", value) for value in args.evidence],
        "planned_scope": scopes,
        "preservation_scope": snapshot_scopes,
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
        "started_at": surveyed_at,
        "events": [],
        "contract_snapshot": inherited_contract,
        "contract_parent_hash": existing.get("contract_parent_hash") if existing else None,
        "contract_status": control.contract_status(inherited_contract),
        "contract_coverage_ids": list(existing.get("contract_coverage_ids", [])) if existing else [],
        "continuity": {
            "schema_version": control.CONTINUITY_SCHEMA_VERSION,
            "goal": {**goal, "source": goal_source, "updated_at": surveyed_at},
            "plan": {
                "revision": 1,
                "reason": control.require_concrete("plan reason", str(payload.get("reason", args.reason))),
                "nodes": nodes,
                "contract_hash": control.strict_contract_hash(inherited_contract),
                "updated_at": surveyed_at,
            },
            "current_node": control.require_continuity_id("current node", str(payload["current_node"])),
            "next_action": next_action,
            "gaps": [],
            "last_checkpoint": None,
            "pending_action": None,
            "evidence_links": [],
            "durability": {"level": args.durability or "local", "updated_at": surveyed_at},
            "updated_at": surveyed_at,
            "bootstrap": {
                "mode": args.mode,
                "status": "ready",
                "surveyed_at": surveyed_at,
                "goal_confirmation_source": goal_source,
                "plan_confirmation_source": plan_source,
                "adopted_from_task_id": existing.get("id") if existing else None,
                "superseded_control_ids": [existing.get("id")] if existing else [],
            },
        },
    }
    control.validate_contract_plan(receipt, nodes)
    control.continuity_event(
        receipt,
        "control_bootstrapped",
        mode=args.mode,
        goal_revision=1,
        plan_revision=1,
        adopted_from_task_id=existing.get("id") if existing else None,
        goal_confirmation_source=goal_source,
        plan_confirmation_source=plan_source,
    )
    state = control.ensure_root(repo)
    snapshot = control.capture_snapshot(
        repo,
        state["snapshots"] / run_id,
        scopes,
        mode=getattr(args, "snapshot_mode", "auto"),
        preservation_scopes=snapshot_scopes,
    )
    receipt["snapshot"] = snapshot
    expected_revision = int(existing.get("state_revision", 0)) if existing else 0
    with control.state_lock(state["active"]):
        current, current_error = control.readable_receipt(state["active"])
        if current_error:
            raise ValueError("active receipt changed and is now unreadable; bootstrap aborted")
        if existing is None:
            if current is not None:
                raise ValueError("an active run appeared while preparing fresh bootstrap")
        else:
            if not current or current.get("id") != existing.get("id") or int(current.get("state_revision", 0)) != expected_revision:
                raise ValueError("active receipt changed while preparing bootstrap")
            superseded = dict(current)
            superseded.update({
                "schema_version": control.SCHEMA_VERSION,
                "status": "superseded",
                "summary": f"superseded by {run_id} via bootstrap {args.mode}",
                "superseded_by": run_id,
                "finished_at": control.now(),
            })
            control.archive_receipt(state, superseded)
            if existing_resolution.get("legacy_projection"):
                control.clear_branch_active(state, branch, control.git_head(repo))
        # Do not leave a superseded task in the recovery slot if the new active write succeeds.
        state["active"].with_suffix(".bak").unlink(missing_ok=True)
        control.write_json(state["active"], receipt)
        control.write_json(state["active"].with_suffix(".bak"), receipt)
    control.sync_task_projection(state, receipt, selected=True)
    readback = control.build_status_payload(repo, state, view="compact")
    if readback.get("continuity_status") != "ready":
        raise ValueError(f"bootstrap readback is not ready: {readback.get('continuity_status')}")
    print(json.dumps({
        "status": "ready",
        "id": run_id,
        "mode": args.mode,
        "goal_revision": 1,
        "plan_revision": 1,
        "state_revision": receipt["state_revision"],
        "superseded_control_ids": receipt["continuity"]["bootstrap"]["superseded_control_ids"],
    }, ensure_ascii=False))
    return 0
