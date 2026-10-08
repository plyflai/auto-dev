"""Task inspection and branch-task command orchestration."""

from __future__ import annotations

from auto_dev_internal.foundation.core import *

def command_task_list(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_root)
    state = paths(repo)
    project = load_project(state, repo)
    branch, head, key = current_context(repo)
    if project is None:
        active, _ = readable_receipt(state["active"])
        tasks = [task_summary(normalize_receipt(active))] if active else []
        print(json.dumps({
            "status": "legacy" if active else "idle",
            "project_revision": 0,
            "branch": branch,
            "head": head,
            "active_task_id": active.get("id") if active else None,
            "tasks": tasks,
        }, ensure_ascii=False))
        return 0
    contexts = project["branches"] if args.all else {key: project["branches"].get(key, {})}
    tasks = []
    for context_key, context in contexts.items():
        for task_id in context.get("task_ids", []):
            try:
                summary = task_summary(read_task(state, str(task_id)))
            except (OSError, json.JSONDecodeError, ValueError) as error:
                summary = {"id": task_id, "status": "unreadable", "error": str(error)}
            summary["context_key"] = context_key
            summary["selected"] = task_id == context.get("active_task_id")
            tasks.append(summary)
    print(json.dumps({
        "status": "ready",
        "project_id": project["project_id"],
        "project_revision": project["state_revision"],
        "branch": branch,
        "head": head,
        "context_key": key,
        "active_task_id": project["branches"].get(key, {}).get("active_task_id"),
        "tasks": tasks,
    }, ensure_ascii=False))
    return 0


def command_task_pause(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_root)
    state = ensure_root(repo)
    receipt = require_active(state)
    if args.task_id and args.task_id != receipt.get("id"):
        raise ValueError("task id does not match the current branch active task")
    if receipt.get("status") not in {"active", "blocked"}:
        raise ValueError("only an active or blocked task can be paused")
    loaded_revision = int(receipt.get("state_revision", 0))
    if args.state_revision != loaded_revision:
        raise ValueError(
            f"state revision conflict: expected {loaded_revision}, received {args.state_revision}"
        )
    receipt["status"] = "paused"
    receipt.setdefault("events", []).append({
        "type": "task_paused",
        "at": now(),
        "reason": require_concrete("pause reason", args.reason),
    })
    next_revision = write_inactive_task(state, receipt, expected_revision=loaded_revision)
    print(json.dumps({
        "status": "paused",
        "task_id": receipt["id"],
        "state_revision": next_revision,
        "branch": receipt.get("base_branch"),
        "receipt": bilingual_receipt("🧾 Auto Dev", "task_paused", f"task={receipt['id']}"),
    }, ensure_ascii=False))
    return 0


def command_task_select(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_root)
    state = ensure_root(repo)
    project = load_project(state, repo)
    if project is None:
        raise ValueError("task selection requires an initialized project control")
    actual_revision = int(project.get("state_revision", 0))
    if args.project_revision != actual_revision:
        raise ValueError(
            f"project revision conflict: expected {actual_revision}, received {args.project_revision}"
        )
    receipt = read_task(state, require_concrete("task id", args.task_id))
    branch, head, key = current_context(repo)
    task_key = branch_context_key(receipt.get("base_branch"), receipt.get("base_head"))
    if task_key != key:
        raise ValueError("task belongs to a different branch context")
    context = project["branches"].get(key, {})
    selected = context.get("active_task_id")
    if selected and selected != receipt["id"]:
        raise ValueError(f"branch already has an active task: {selected}")
    if receipt.get("status") in TERMINAL_TASK_STATUSES:
        raise ValueError("terminal tasks cannot be selected")
    loaded_revision = int(receipt.get("state_revision", 0))
    selected_status = receipt.get("status")
    if selected_status != "review_ready":
        receipt["status"] = "active"
    receipt.setdefault("events", []).append({
        "type": "task_selected",
        "at": now(),
        "confirmation_source": require_concrete("selection confirmation", args.confirmation_source),
        "branch": branch,
        "head": head,
        "status": receipt["status"],
    })
    next_revision = write_active(state, receipt, expected_revision=loaded_revision)
    print(json.dumps({
        "status": receipt["status"],
        "task_id": receipt["id"],
        "state_revision": next_revision,
        "branch": branch,
        "receipt": bilingual_receipt("🧾 Auto Dev", "execution_focus_changed", f"task={receipt['id']}"),
    }, ensure_ascii=False))
    return 0


def command_task_amend_scope(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_root)
    state = ensure_root(repo)
    receipt = require_working_task(state)
    loaded_revision = int(receipt.get("state_revision", 0))
    if args.state_revision != loaded_revision:
        raise ValueError(
            f"state revision conflict: expected {loaded_revision}, received {args.state_revision}"
        )
    current_scopes = list(receipt.get("planned_scope", []))
    requested_scopes = normalize_scopes(repo, args.scope)
    added_scopes = [scope for scope in requested_scopes if not path_in_scope(scope, current_scopes)]
    if not added_scopes:
        raise ValueError("scope amendment must add at least one path outside the declared scope")
    confirmation_source = None
    if args.kind == "requirement-diff":
        confirmation_source = require_concrete(
            "Requirement Diff confirmation source", args.confirmation_source or ""
        )
    elif args.confirmation_source:
        confirmation_source = require_concrete("scope amendment confirmation source", args.confirmation_source)
    amendment = {
        "kind": args.kind,
        "reason": require_concrete("scope amendment reason", args.reason),
        "added_scope": added_scopes,
        "at": now(),
    }
    if confirmation_source:
        amendment["confirmation_source"] = confirmation_source
    receipt["planned_scope"] = merge_unique(current_scopes, added_scopes)
    receipt.setdefault("scope_amendments", []).append(amendment)
    continuity_event(receipt, "scope_amended", **amendment)
    next_revision = write_active(state, receipt, expected_revision=loaded_revision)
    print(json.dumps({
        "status": "active",
        "task_id": receipt["id"],
        "state_revision": next_revision,
        "kind": args.kind,
        "added_scope": added_scopes,
        "planned_scope": receipt["planned_scope"],
        "receipt": bilingual_receipt("🧾 Auto Dev", "scope_amended", f"task={receipt['id']}"),
    }, ensure_ascii=False))
    return 0

def command_task_resume(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_root)
    state = ensure_root(repo)
    receipt = require_active(state)
    if receipt.get("status") != "review_ready":
        raise ValueError("only a review_ready task can be resumed")
    loaded_revision = int(receipt.get("state_revision", 0))
    if args.state_revision != loaded_revision:
        raise ValueError(
            f"state revision conflict: expected {loaded_revision}, received {args.state_revision}"
        )
    receipt["status"] = "active"
    continuity_event(
        receipt,
        "task_resumed",
        reason=require_concrete("resume reason", args.reason),
        confirmation_source=require_concrete("resume confirmation source", args.confirmation_source),
    )
    next_revision = write_active(state, receipt, expected_revision=loaded_revision)
    print(json.dumps({
        "status": "active",
        "task_id": receipt["id"],
        "state_revision": next_revision,
        "receipt": bilingual_receipt("🧾 Auto Dev", "task_resumed", f"task={receipt['id']}"),
    }, ensure_ascii=False))
    return 0


def command_task_attribute(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_root)
    state = ensure_root(repo)
    receipt = require_working_task(state)
    loaded_revision = int(receipt.get("state_revision", 0))
    if args.state_revision != loaded_revision:
        raise ValueError(
            f"state revision conflict: expected {loaded_revision}, received {args.state_revision}"
        )
    project = load_project(state, repo)
    if project is None:
        raise ValueError("task attribution requires an initialized project control")
    context_id = args.project_context or receipt.get("project_context_id") or project.get("default_context_id")
    entry, _ = resolve_project_context(state, project, context_id)
    context_id = str(entry["id"])
    outcome_id = require_control_id(
        "task primary outcome id", args.outcome_id or str(receipt.get("primary_outcome_id") or "")
    )
    read_outcome_record(state, context_id, outcome_id)
    intake_id = args.intake_id or receipt.get("intake_id")
    intake = confirmed_intake_for_context(state, project, intake_id, context_id)
    receipt["project_context_id"] = context_id
    receipt["primary_outcome_id"] = outcome_id
    receipt["intake_id"] = intake.get("id") if intake else None
    continuity_event(
        receipt,
        "task_attributed",
        project_context_id=context_id,
        primary_outcome_id=outcome_id,
        intake_id=receipt.get("intake_id"),
        source=require_concrete("task attribution source", args.source),
    )
    next_revision = write_active(state, receipt, expected_revision=loaded_revision)
    print(json.dumps({
        "status": "active",
        "task_id": receipt["id"],
        "state_revision": next_revision,
        "project_context_id": context_id,
        "primary_outcome_id": outcome_id,
        "intake_id": receipt.get("intake_id"),
        "receipt": bilingual_receipt("🧾 Auto Dev", "task_attributed", f"task={receipt['id']}"),
    }, ensure_ascii=False))
    return 0

def bind(control) -> None:
    """Bind shared control-plane helpers through the facade."""
    for name in dir(control):
        if not name.startswith("_"):
            globals()[name] = getattr(control, name)
