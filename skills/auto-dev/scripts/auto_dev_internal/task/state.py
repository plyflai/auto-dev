"""Task continuity, branch association, and durable receipt projections."""

from __future__ import annotations

import contextlib
import json
import pathlib
import re
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback keeps single-writer behavior.
    fcntl = None


def prepare_task_attribution(
    control,
    repo: pathlib.Path,
    state: dict[str, pathlib.Path],
    *,
    requested_context_id: str | None,
    requested_outcome_id: str | None,
    requested_intake_id: str | None,
) -> tuple[str, str, str | None]:
    """Resolve a Task's semantic home without forcing users to model the whole product first."""
    with state_lock(state["project"]):
        project = control.load_project(state, repo) or control.blank_project(repo)
        context_id, context_created = control.ensure_default_project_context(state, project)
        if requested_context_id:
            context_id = control.require_control_id("project context id", requested_context_id)
        entry, _ = control.resolve_project_context(state, project, context_id)
        context_id = str(entry["id"])
        outcome_id = control.require_control_id(
            "task primary outcome id",
            requested_outcome_id or str(entry.get("unlinked_outcome_id") or ""),
        )
        control.read_outcome_record(state, context_id, outcome_id)
        intake = control.confirmed_intake_for_context(
            state, project, requested_intake_id, context_id
        )
        if context_created or not state["project"].exists():
            control.write_project_control(state, project)
    return context_id, outcome_id, intake.get("id") if intake else None


def bind_intake_to_task(
    control,
    state: dict[str, pathlib.Path],
    project_context_id: str,
    intake_id: str | None,
    task_id: str,
) -> None:
    if not intake_id:
        return
    with state_lock(state["project"]):
        record = control.read_intake_record(state, project_context_id, intake_id)
        if record.get("task_id") == task_id or record.get("task_id") is not None:
            return
        record["task_id"] = task_id
        record["state_revision"] = int(record.get("state_revision", 0)) + 1
        record["updated_at"] = control.now()
        record["baseline_hash"] = control.intake_baseline_hash(record)
        control.write_json(
            control.intake_record_path(state, project_context_id, intake_id),
            record,
            backup=True,
        )


def task_path(state: dict[str, pathlib.Path], task_id: str) -> pathlib.Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id):
        raise ValueError("task id contains unsupported path characters")
    return state["tasks"] / f"{task_id}.json"


def task_summary(control, receipt: dict[str, Any]) -> dict[str, Any]:
    continuity = control.continuity_from_receipt(receipt)
    review = receipt.get("review") if isinstance(receipt.get("review"), dict) else {}
    product_review = (
        review.get("product_review")
        if isinstance(review.get("product_review"), dict)
        else None
    )
    return {
        "id": receipt.get("id"),
        "task": receipt.get("task"),
        "status": receipt.get("status"),
        "project_context_id": receipt.get("project_context_id"),
        "primary_outcome_id": receipt.get("primary_outcome_id"),
        "intake_id": receipt.get("intake_id"),
        "branch": receipt.get("base_branch"),
        "state_revision": receipt.get("state_revision", 0),
        "current_node": continuity.get("current_node") if continuity else None,
        "next_action": continuity.get("next_action") if continuity else None,
        "review_ready_at": review.get("prepared_at"),
        "product_review_status": review.get("product_review_status") or (
            product_review.get("test", {}).get("status")
            if product_review
            else ("missing" if receipt.get("status") == "review_ready" else None)
        ),
        "updated_at": (continuity or {}).get("updated_at") or receipt.get("started_at"),
    }


def read_task(control, state: dict[str, pathlib.Path], task_id: str) -> dict[str, Any]:
    path = task_path(state, task_id)
    if not path.exists():
        raise ValueError(f"task receipt does not exist: {task_id}")
    receipt = control.read_json(path)
    if not isinstance(receipt, dict) or receipt.get("id") != task_id:
        raise ValueError(f"task receipt is malformed: {task_id}")
    return control.normalize_receipt(receipt)


def current_context(control, repo: pathlib.Path) -> tuple[str | None, str | None, str]:
    branch = control.current_branch(repo)
    head = control.git_head(repo)
    return branch, head, control.branch_context_key(branch, head)


def sync_task_projection(
    control,
    state: dict[str, pathlib.Path],
    receipt: dict[str, Any],
    *,
    selected: bool,
) -> None:
    repo = state["root"].parent
    state["tasks"].mkdir(parents=True, exist_ok=True)
    with state_lock(state["project"]):
        project = control.load_project(state, repo) or control.blank_project(repo)
        branch = receipt.get("base_branch")
        key = control.branch_context_key(branch, receipt.get("base_head"))
        changed = state["project"].exists() is False
        context_id, context_created = control.ensure_default_project_context(state, project)
        if context_created:
            changed = True
        if not receipt.get("project_context_id"):
            receipt["project_context_id"] = context_id
        if not receipt.get("primary_outcome_id"):
            entry = project["contexts"].get(str(receipt["project_context_id"]))
            if not isinstance(entry, dict):
                raise ValueError("task references an unknown managed project context")
            receipt["primary_outcome_id"] = entry.get("unlinked_outcome_id")
        context = project["branches"].get(key)
        if context is None:
            context = {
                "branch": branch,
                "active_task_id": None,
                "task_ids": [],
                "updated_at": control.now(),
            }
            project["branches"][key] = context
            changed = True
        if receipt["id"] not in context["task_ids"]:
            context["task_ids"].append(receipt["id"])
            changed = True
        if selected:
            current_id = context.get("active_task_id")
            if current_id and current_id != receipt["id"]:
                raise ValueError(f"branch already has an active task: {current_id}")
            if current_id != receipt["id"]:
                context["active_task_id"] = receipt["id"]
                changed = True
        elif context.get("active_task_id") == receipt["id"]:
            context["active_task_id"] = None
            changed = True
        control.write_json(task_path(state, str(receipt["id"])), receipt)
        if changed:
            context["updated_at"] = control.now()
            project["schema_version"] = control.PROJECT_SCHEMA_VERSION
            project["state_revision"] = int(project.get("state_revision", 0)) + 1
            project["updated_at"] = control.now()
            control.write_json(state["project"], project, backup=True)


def clear_branch_active(
    control,
    state: dict[str, pathlib.Path],
    branch: str | None,
    head: str | None,
) -> None:
    repo = state["root"].parent
    with state_lock(state["project"]):
        project = control.load_project(state, repo)
        if project is None:
            return
        context = project["branches"].get(control.branch_context_key(branch, head))
        if context is None or context.get("active_task_id") is None:
            return
        context["active_task_id"] = None
        context["updated_at"] = control.now()
        project["state_revision"] = int(project.get("state_revision", 0)) + 1
        project["updated_at"] = control.now()
        control.write_json(state["project"], project, backup=True)


def resolve_branch_task(
    control,
    repo: pathlib.Path,
    state: dict[str, pathlib.Path],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    branch, head, key = current_context(control, repo)
    project = control.load_project(state, repo)
    if project is not None:
        context = project["branches"].get(key, {})
        active_task_id = context.get("active_task_id")
        projected_active, projected_error = control.readable_receipt(state["active"])
        if projected_error:
            projected_active = None
        if projected_active is not None and projected_active.get("base_branch") == branch:
            if active_task_id != projected_active.get("id"):
                normalized = control.normalize_receipt(projected_active)
                return normalized, {
                    "project_id": project.get("project_id"),
                    "project_revision": project.get("state_revision", 0),
                    "branch": branch,
                    "head": head,
                    "context_key": key,
                    "active_task_id": projected_active.get("id"),
                    "candidates": [task_summary(control, normalized)],
                    "legacy_projection": True,
                }
        candidates = []
        for task_id in context.get("task_ids", []):
            try:
                candidate = read_task(control, state, str(task_id))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            if candidate.get("status") not in control.TERMINAL_TASK_STATUSES:
                candidates.append(task_summary(control, candidate))
        resolution = {
            "project_id": project.get("project_id"),
            "project_revision": project.get("state_revision", 0),
            "branch": branch,
            "head": head,
            "context_key": key,
            "active_task_id": active_task_id,
            "candidates": candidates,
        }
        if active_task_id:
            try:
                receipt = read_task(control, state, str(active_task_id))
            except (OSError, json.JSONDecodeError, ValueError):
                if projected_active is None or projected_active.get("id") != active_task_id:
                    raise
                receipt = control.normalize_receipt(projected_active)
                resolution["task_recovery_source"] = "active.json"
            if control.branch_context_key(receipt.get("base_branch"), receipt.get("base_head")) != key:
                raise ValueError("active task branch does not match the current branch context")
            return receipt, resolution
        return None, resolution

    active, active_error = control.readable_receipt(state["active"])
    if active_error:
        raise ValueError(f"active receipt is unreadable: {active_error}")
    if active is not None:
        recorded_key = control.branch_context_key(active.get("base_branch"), active.get("base_head"))
        if active.get("base_branch") is None or recorded_key == key:
            normalized = control.normalize_receipt(active)
            return normalized, {
                "project_id": None,
                "project_revision": 0,
                "branch": branch,
                "head": head,
                "context_key": key,
                "active_task_id": active.get("id"),
                "candidates": [task_summary(control, normalized)],
                "legacy": True,
            }
    return None, {
        "project_id": None,
        "project_revision": 0,
        "branch": branch,
        "head": head,
        "context_key": key,
        "active_task_id": None,
        "candidates": [],
        "legacy": True,
    }


@contextlib.contextmanager
def state_lock(path: pathlib.Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_active(
    control,
    state: dict[str, pathlib.Path],
    receipt: dict[str, Any],
    *,
    expected_revision: int | None = None,
) -> int:
    """Write the current branch's selected task projection."""
    active = state["active"]
    with state_lock(active):
        current_revision = 0
        projected = task_path(state, str(receipt["id"]))
        if projected.exists():
            current_revision = int(control.read_json(projected).get("state_revision", 0))
        elif active.exists():
            current = control.read_json(active)
            if current.get("id") == receipt.get("id"):
                current_revision = int(current.get("state_revision", 0))
        if expected_revision is not None and current_revision != expected_revision:
            raise ValueError(
                f"state revision conflict: expected {current_revision}, received {expected_revision}"
            )
        next_revision = current_revision + 1
        receipt["schema_version"] = control.SCHEMA_VERSION
        receipt["state_revision"] = next_revision
        sync_task_projection(control, state, receipt, selected=True)
        previous = control.read_json(active) if active.exists() else None
        if previous is not None and previous.get("id") != receipt.get("id"):
            active.with_suffix(".bak").unlink(missing_ok=True)
            control.write_json(active, receipt)
            control.write_json(active.with_suffix(".bak"), receipt)
        else:
            control.write_json(active, receipt, backup=True)
        return next_revision


def write_inactive_task(
    control,
    state: dict[str, pathlib.Path],
    receipt: dict[str, Any],
    *,
    expected_revision: int,
) -> int:
    path = task_path(state, str(receipt["id"]))
    with state_lock(path):
        current_revision = 0
        if path.exists():
            current_revision = int(control.read_json(path).get("state_revision", 0))
        elif state["active"].exists():
            current = control.read_json(state["active"])
            if current.get("id") == receipt.get("id"):
                current_revision = int(current.get("state_revision", 0))
        if current_revision != expected_revision:
            raise ValueError(
                f"state revision conflict: expected {current_revision}, received {expected_revision}"
            )
        next_revision = current_revision + 1
        receipt["schema_version"] = control.SCHEMA_VERSION
        receipt["state_revision"] = next_revision
        sync_task_projection(control, state, receipt, selected=False)
        if state["active"].exists() and control.read_json(state["active"]).get("id") == receipt.get("id"):
            state["active"].unlink(missing_ok=True)
            state["active"].with_suffix(".bak").unlink(missing_ok=True)
        return next_revision
