"""Managed project contexts, outcome DAGs, capabilities, activity, and focus."""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import re
from typing import Any, Iterable


def normalize_external_references(control, values: Iterable[str]) -> list[dict[str, Any]]:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.normalize_external_references(control, values)


def command_project_context_list(control, args: argparse.Namespace) -> int:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.command_project_context_list(control, args)


def command_project_context_show(control, args: argparse.Namespace) -> int:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.command_project_context_show(control, args)


def command_project_context_adopt(control, args: argparse.Namespace) -> int:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.command_project_context_adopt(control, args)


def command_project_context_set(control, args: argparse.Namespace) -> int:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.command_project_context_set(control, args)


def command_project_context_select(control, args: argparse.Namespace) -> int:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.command_project_context_select(control, args)


def read_outcome_record(
    control, state: dict[str, pathlib.Path], context_id: str, outcome_id: str
) -> dict[str, Any]:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.read_outcome_record(control, state, context_id, outcome_id)


def list_outcome_records(
    control, state: dict[str, pathlib.Path], context_id: str
) -> list[dict[str, Any]]:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.list_outcome_records(control, state, context_id)


def outcome_summary(control, record: dict[str, Any]) -> dict[str, Any]:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.outcome_summary(control, record)


def outcome_coverage_rollup(
    control,
    state: dict[str, pathlib.Path],
    context_id: str,
    outcome_id: str,
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.outcome_coverage_rollup(
        control, state, context_id, outcome_id, contract
    )


def outcome_edges(control, records: Iterable[dict[str, Any]]) -> dict[str, set[str]]:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.outcome_edges(control, records)


def outcome_graph_has_cycle(control, records: Iterable[dict[str, Any]]) -> bool:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.outcome_graph_has_cycle(control, records)


def validate_outcome_graph(control, records: Iterable[dict[str, Any]]) -> None:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.validate_outcome_graph(control, records)


def confirmed_intake_for_context(
    control,
    state: dict[str, pathlib.Path],
    project: dict[str, Any],
    intake_id: str | None,
    context_id: str,
) -> dict[str, Any] | None:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.confirmed_intake_for_context(
        control, state, project, intake_id, context_id
    )


def command_outcome_list(control, args: argparse.Namespace) -> int:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.command_outcome_list(control, args)


def command_outcome_show(control, args: argparse.Namespace) -> int:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.command_outcome_show(control, args)


def command_outcome_add(control, args: argparse.Namespace) -> int:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.command_outcome_add(control, args)


def command_outcome_set(control, args: argparse.Namespace) -> int:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.command_outcome_set(control, args)


def command_outcome_link(control, args: argparse.Namespace) -> int:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.command_outcome_link(control, args)


def command_outcome_move(control, args: argparse.Namespace) -> int:
    from auto_dev_internal.project import context as runctl_project_context

    return runctl_project_context.command_outcome_move(control, args)


def read_capability_record(
    control, state: dict[str, pathlib.Path], context_id: str, capability_id: str
) -> dict[str, Any]:
    path = control.capability_record_path(state, context_id, capability_id)
    if not path.exists():
        raise ValueError(f"capability does not exist: {capability_id}")
    record = control.read_json(path)
    if not isinstance(record, dict) or record.get("id") != capability_id:
        raise ValueError(f"capability record is malformed: {capability_id}")
    if record.get("project_context_id") != context_id:
        raise ValueError(f"capability belongs to a different project context: {capability_id}")
    return record


def list_capability_records(
    control, state: dict[str, pathlib.Path], context_id: str
) -> list[dict[str, Any]]:
    directory = control.context_capabilities_directory(state, context_id)
    if not directory.exists():
        return []
    records = []
    for path in sorted(directory.glob("*.json")):
        try:
            value = control.read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(value, dict)
            and value.get("project_context_id") == context_id
            and value.get("id")
        ):
            records.append(value)
    return records


def capability_summary(control, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "title": record.get("title"),
        "statement": record.get("statement"),
        "status": record.get("status"),
        "improves_outcomes": record.get("improves_outcomes", []),
        "evidence": record.get("evidence", []),
        "state_revision": record.get("state_revision", 0),
        "updated_at": record.get("updated_at"),
    }


def normalize_capability_outcomes(
    control, state: dict[str, pathlib.Path], context_id: str, values: Iterable[str]
) -> list[str]:
    result = []
    for value in values:
        outcome_id = control.require_control_id("capability outcome id", value)
        read_outcome_record(control, state, context_id, outcome_id)
        if outcome_id not in result:
            result.append(outcome_id)
    return result


def command_capability_list(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    project = control.load_project(state, repo)
    if project is None:
        print(json.dumps({"status": "uninitialized", "capabilities": []}, ensure_ascii=False))
        return 0
    (entry, _) = control.resolve_project_context(state, project, args.project_context)
    records = list_capability_records(control, state, str(entry["id"]))
    print(
        json.dumps(
            {
                "status": "ready",
                "project_context_id": entry["id"],
                "project_revision": project.get("state_revision", 0),
                "capabilities": [capability_summary(control, record) for record in records],
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_capability_add(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    capability_id = control.require_control_id("capability id", args.capability_id)
    with control.state_lock(state["project"]):
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("capability add requires an initialized project control")
        control.require_project_revision(project, args.project_revision)
        (entry, _) = control.resolve_project_context(state, project, args.project_context)
        context_id = str(entry["id"])
        path = control.capability_record_path(state, context_id, capability_id)
        if path.exists():
            raise ValueError(f"capability already exists: {capability_id}")
        if args.status not in control.CAPABILITY_STATUSES:
            raise ValueError(f"unsupported capability status: {args.status}")
        created_at = control.now()
        record = {
            "schema_version": control.CAPABILITY_SCHEMA_VERSION,
            "id": capability_id,
            "project_context_id": context_id,
            "title": control.require_concrete("capability title", args.title),
            "statement": control.require_concrete("capability statement", args.statement),
            "status": args.status,
            "improves_outcomes": normalize_capability_outcomes(
                control, state, context_id, args.outcome_id
            ),
            "evidence": [
                control.require_concrete("capability evidence", value) for value in args.evidence
            ],
            "state_revision": 1,
            "created_at": created_at,
            "updated_at": created_at,
        }
        control.write_json(path, record)
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": "created",
                "project_context_id": context_id,
                "project_revision": project_revision,
                "capability": capability_summary(control, record),
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "capability_recorded", f"capability={capability_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_capability_set(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    capability_id = control.require_control_id("capability id", args.capability_id)
    with control.state_lock(state["project"]):
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("capability set requires an initialized project control")
        control.require_project_revision(project, args.project_revision)
        (entry, _) = control.resolve_project_context(state, project, args.project_context)
        context_id = str(entry["id"])
        record = read_capability_record(control, state, context_id, capability_id)
        actual_revision = int(record.get("state_revision", 0))
        if args.capability_revision != actual_revision:
            raise ValueError(
                f"capability revision conflict: expected {actual_revision}, received {args.capability_revision}"
            )
        changed = False
        if args.title:
            record["title"] = control.require_concrete("capability title", args.title)
            changed = True
        if args.statement:
            record["statement"] = control.require_concrete("capability statement", args.statement)
            changed = True
        if args.status:
            if args.status not in control.CAPABILITY_STATUSES:
                raise ValueError(f"unsupported capability status: {args.status}")
            record["status"] = args.status
            changed = True
        if args.outcome_id:
            record["improves_outcomes"] = control.merge_unique(
                record.get("improves_outcomes", []),
                normalize_capability_outcomes(control, state, context_id, args.outcome_id),
            )
            changed = True
        if args.evidence:
            record["evidence"] = control.merge_unique(
                record.get("evidence", []),
                [control.require_concrete("capability evidence", value) for value in args.evidence],
            )
            changed = True
        if not changed:
            raise ValueError("capability set requires at least one changed field")
        record["state_revision"] = actual_revision + 1
        record["updated_at"] = control.now()
        control.write_json(
            control.capability_record_path(state, context_id, capability_id), record, backup=True
        )
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": "updated",
                "project_context_id": context_id,
                "project_revision": project_revision,
                "capability": capability_summary(control, record),
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "capability_recorded", f"capability={capability_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def activity_record_path(control, state: dict[str, pathlib.Path], activity_id: str) -> pathlib.Path:
    return state["activities"] / f"{control.require_control_id('activity id', activity_id)}.json"


def read_activity_record(
    control, state: dict[str, pathlib.Path], activity_id: str
) -> dict[str, Any]:
    path = activity_record_path(control, state, activity_id)
    if not path.exists():
        raise ValueError(f"activity does not exist: {activity_id}")
    record = control.read_json(path)
    if not isinstance(record, dict) or record.get("id") != activity_id:
        raise ValueError(f"activity record is malformed: {activity_id}")
    return record


def list_activity_records(
    control, state: dict[str, pathlib.Path], context_id: str | None = None
) -> list[dict[str, Any]]:
    if not state["activities"].exists():
        return []
    activities = []
    for path in sorted(state["activities"].glob("*.json"), reverse=True):
        try:
            record = control.read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or not record.get("id"):
            continue
        if context_id and record.get("project_context_id") != context_id:
            continue
        activities.append(record)
    return activities


def activity_summary(control, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "summary": record.get("summary"),
        "result": record.get("result"),
        "project_context_id": record.get("project_context_id"),
        "outcome_id": record.get("outcome_id"),
        "intake_id": record.get("intake_id"),
        "paths": record.get("paths", []),
        "validation": record.get("validation", []),
        "recorded_at": record.get("recorded_at"),
    }


def command_activity_list(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    project = control.load_project(state, repo)
    if project is None:
        print(json.dumps({"status": "uninitialized", "activities": []}, ensure_ascii=False))
        return 0
    (entry, _) = control.resolve_project_context(state, project, args.project_context)
    records = list_activity_records(control, state, str(entry["id"]))
    print(
        json.dumps(
            {
                "status": "ready",
                "project_context_id": entry["id"],
                "project_revision": project.get("state_revision", 0),
                "activities": [activity_summary(control, record) for record in records],
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_activity_record(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    activity_id = control.require_control_id(
        "activity id", args.activity_id or control.generated_control_id("ACTIVITY")
    )
    with control.state_lock(state["project"]):
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("activity record requires an initialized project control")
        control.require_project_revision(project, args.project_revision)
        (receipt, _) = control.resolve_branch_task(repo, state)
        if receipt is not None:
            raise ValueError(
                "quick activity cannot be recorded while a selected task owns the current branch"
            )
        (entry, _) = control.resolve_project_context(state, project, args.project_context)
        context_id = str(entry["id"])
        outcome_id = control.require_control_id(
            "activity outcome id", args.outcome_id or str(entry.get("unlinked_outcome_id") or "")
        )
        read_outcome_record(control, state, context_id, outcome_id)
        intake = confirmed_intake_for_context(control, state, project, args.intake_id, context_id)
        if intake is None:
            raise ValueError("managed Quick Write activity requires a confirmed intake baseline")
        path = activity_record_path(control, state, activity_id)
        if path.exists():
            raise ValueError(f"activity already exists: {activity_id}")
        recorded_at = control.now()
        record = {
            "schema_version": control.ACTIVITY_SCHEMA_VERSION,
            "id": activity_id,
            "summary": control.require_concrete("activity summary", args.summary),
            "result": args.result,
            "project_context_id": context_id,
            "outcome_id": outcome_id,
            "intake_id": intake.get("id"),
            "paths": control.normalize_scopes(repo, args.path),
            "validation": [
                control.require_concrete("activity validation", value) for value in args.validation
            ],
            "recorded_at": recorded_at,
        }
        if record["result"] not in {"passed", "failed", "partial"}:
            raise ValueError(f"unsupported activity result: {record['result']}")
        if not record["paths"]:
            raise ValueError("activity record requires at least one affected path")
        if not record["validation"]:
            raise ValueError("activity record requires at least one validation result")
        control.write_json(path, record)
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": "recorded",
                "project_revision": project_revision,
                "activity": activity_summary(control, record),
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "activity_recorded", f"activity={activity_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def read_view_focus(control, state: dict[str, pathlib.Path], session_key: str) -> dict[str, Any]:
    path = control.view_focus_path(state, session_key)
    value = control.read_optional_json(path)
    if value is None:
        return {"status": "unset", "session_key": session_key}
    if value.get("session_key") != session_key:
        raise ValueError("view focus belongs to a different session")
    return value


def command_focus_show(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    session_key = control.require_session_key(args.session_key)
    print(json.dumps(read_view_focus(control, state, session_key), ensure_ascii=False))
    return 0


def command_focus_set(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    session_key = control.require_session_key(args.session_key)
    focus_kind = args.kind
    if focus_kind not in {"project", "outcome", "task", "plan"}:
        raise ValueError("view focus kind must be project, outcome, task, or plan")
    with control.state_lock(state["project"]):
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("view focus requires an initialized project control")
        (entry, _) = control.resolve_project_context(state, project, args.project_context)
        context_id = str(entry["id"])
        focus_id = control.require_control_id("view focus id", args.focus_id)
        task_id = None
        if focus_kind == "project":
            if focus_id != context_id:
                raise ValueError("project view focus id must match the selected project context")
        elif focus_kind == "outcome":
            read_outcome_record(control, state, context_id, focus_id)
        elif focus_kind == "task":
            control.read_task(state, focus_id)
            task_id = focus_id
        else:
            task_id = control.require_control_id("plan task id", args.task_id or "")
            task = control.read_task(state, task_id)
            continuity = control.continuity_from_receipt(task)
            if continuity is None or focus_id not in control.continuity_nodes(continuity):
                raise ValueError(
                    "plan view focus must reference an existing node on the supplied task"
                )
        previous = read_view_focus(control, state, session_key)
        focus = {
            "schema_version": control.VIEW_FOCUS_SCHEMA_VERSION,
            "session_key": session_key,
            "status": "set",
            "kind": focus_kind,
            "id": focus_id,
            "project_context_id": context_id,
            "task_id": task_id,
            "state_revision": int(previous.get("state_revision", 0)) + 1,
            "updated_at": control.now(),
        }
        control.write_json(control.view_focus_path(state, session_key), focus, backup=True)
    print(
        json.dumps(
            {
                "status": "set",
                "view_focus": focus,
                "execution_focus_changed": False,
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "view_focus_changed", f"focus={focus_kind}:{focus_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0
