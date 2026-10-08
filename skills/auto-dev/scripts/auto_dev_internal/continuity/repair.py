"""Transactional control-plane repair and readback commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
from datetime import datetime
from typing import Any, Iterable

from auto_dev_internal.continuity.upgrade_repair import (
    find_interrupted_upgrade,
    inspect_upgrade_transactions,
    read_upgrade_manifest,
)

def repair_id(control, ) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return f"AUTO-DEV-FIX-{timestamp}-{os.urandom(3).hex().upper()}"


def control_file_digest(control, path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repair_backup(control, 
    state: dict[str, pathlib.Path],
    identifier: str,
    affected_paths: Iterable[pathlib.Path],
) -> pathlib.Path:
    backup_root = state["repair_backups"] / identifier
    backup_root.mkdir(parents=True, exist_ok=False)
    records = []
    for path in affected_paths:
        try:
            relative = path.relative_to(state["root"])
        except ValueError as error:
            raise ValueError("repair backup path escapes .auto-dev") from error
        existed = path.is_file()
        record: dict[str, Any] = {"path": relative.as_posix(), "existed": existed}
        if existed:
            destination = backup_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            record["sha256"] = control_file_digest(control, path)
        records.append(record)
    control.write_json(backup_root / "manifest.json", {
        "schema_version": 1,
        "repair_id": identifier,
        "created_at": control.now(),
        "files": records,
    })
    return backup_root


def restore_repair_backup(control, state: dict[str, pathlib.Path], backup_root: pathlib.Path) -> None:
    manifest = control.read_json(backup_root / "manifest.json")
    records = manifest.get("files")
    if not isinstance(records, list):
        raise ValueError("repair backup manifest is malformed")
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError("repair backup manifest has an invalid file record")
        relative = pathlib.Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("repair backup manifest contains an unsafe path")
        destination = state["root"] / relative
        if record.get("existed"):
            source = backup_root / relative
            if not source.is_file():
                raise ValueError("repair backup is missing a recorded file")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        else:
            destination.unlink(missing_ok=True)


def append_repair_audit(control, state: dict[str, pathlib.Path], payload: dict[str, Any]) -> None:
    history = state["repair_history"]
    with control.state_lock(history):
        with history.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def repair_context(control, 
    repo: pathlib.Path,
    state: dict[str, pathlib.Path],
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str | None]:
    project = control.load_project(state, repo)
    if project is None:
        raise ValueError("control-plane repair requires an initialized project")
    actual_project_revision = int(project.get("state_revision", 0))
    if args.expected_project_revision != actual_project_revision:
        raise ValueError(
            "project revision conflict: "
            f"expected {actual_project_revision}, received {args.expected_project_revision}"
        )
    branch, _head, key = control.current_context(repo)
    receipt = control.read_task(state, control.require_concrete("repair task id", args.task_id))
    if control.branch_context_key(receipt.get("base_branch"), receipt.get("base_head")) != key:
        raise ValueError("repair task belongs to a different branch context")
    actual_task_revision = int(receipt.get("state_revision", 0))
    if args.expected_task_revision != actual_task_revision:
        raise ValueError(
            "task revision conflict: "
            f"expected {actual_task_revision}, received {args.expected_task_revision}"
        )
    context = project["branches"].get(key)
    if not isinstance(context, dict):
        raise ValueError("current branch has no project control context")
    return project, context, receipt, key, branch


def repair_candidate(control, receipt: dict[str, Any], *, selected: bool) -> dict[str, Any]:
    summary = control.task_summary(receipt)
    review = receipt.get("review") if isinstance(receipt.get("review"), dict) else {}
    validation = review.get("validation_results") if isinstance(review.get("validation_results"), list) else []
    operations: list[dict[str, Any]] = []
    if receipt.get("status") in control.TERMINAL_TASK_STATUSES:
        targets = ["active"]
        if validation:
            targets.append("review_ready")
        operations.append({"operation": "restore-task", "target_statuses": targets})
    if selected and receipt.get("status") in {"active", "review_ready"}:
        operations.append({"operation": "reconcile-projection"})
    return {
        **summary,
        "selected": selected,
        "review_evidence_available": bool(validation),
        "operations": operations,
    }


def command_fix_inspect(control, args: argparse.Namespace) -> int:
    """Read repairable control-plane state without creating or changing it."""
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    branch, head, key = control.current_context(repo)
    if not state["root"].exists():
        print(json.dumps({
            "schema_version": 1,
            "status": "unavailable",
            "reason": "no_auto_dev_control",
            "branch": branch,
            "head": head,
            "context_key": key,
            "operations": [],
            "repair_candidates": [],
        }, ensure_ascii=False))
        return 0
    upgrade_transactions = inspect_upgrade_transactions(control, state)
    interrupted_upgrades = [
        transaction
        for transaction in upgrade_transactions
        if transaction.get("status") == "interrupted"
    ]
    try:
        upgrade_inspection = control.legacy_upgrade_inspection_payload(repo, state)
        upgrade_status = {
            "status": upgrade_inspection.get("status"),
            "pending_steps": upgrade_inspection.get("upgrade", {}).get("pending_steps", []),
            "revalidation_targets": upgrade_inspection.get("revalidation_targets", []),
            "manual_decisions": upgrade_inspection.get("manual_decisions", []),
            "blockers": upgrade_inspection.get("blockers", []),
        }
    except (KeyError, OSError, json.JSONDecodeError, RuntimeError, ValueError) as error:
        upgrade_status = {"status": "unavailable", "error": str(error)}
    try:
        project = control.load_project(state, repo)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        if not interrupted_upgrades:
            raise
        print(json.dumps({
            "schema_version": 1,
            "status": "repairable",
            "reason": "interrupted_upgrade_detected",
            "branch": branch,
            "head": head,
            "context_key": key,
            "project_error": str(error),
            "operations": ["recover-interrupted-upgrade"],
            "repair_candidates": [],
            "upgrade_status": upgrade_status,
            "upgrade_transactions": upgrade_transactions,
        }, ensure_ascii=False))
        return 0
    if project is None:
        print(json.dumps({
            "schema_version": 1,
            "status": "repairable" if interrupted_upgrades else "unavailable",
            "reason": (
                "interrupted_upgrade_detected"
                if interrupted_upgrades
                else "legacy_control_requires_bootstrap"
            ),
            "branch": branch,
            "head": head,
            "context_key": key,
            "operations": (
                ["recover-interrupted-upgrade"] if interrupted_upgrades else []
            ),
            "repair_candidates": [],
            "upgrade_status": upgrade_status,
            "upgrade_transactions": upgrade_transactions,
        }, ensure_ascii=False))
        return 0
    context = project["branches"].get(key, {})
    selected_id = context.get("active_task_id") if isinstance(context, dict) else None
    candidates = []
    for task_id in reversed(context.get("task_ids", []) if isinstance(context, dict) else []):
        try:
            receipt = control.read_task(state, str(task_id))
        except (OSError, json.JSONDecodeError, ValueError) as error:
            candidates.append({
                "id": task_id,
                "status": "unreadable",
                "selected": task_id == selected_id,
                "error": str(error),
                "operations": [],
            })
            continue
        candidates.append(repair_candidate(control, receipt, selected=task_id == selected_id))
    active, active_error = control.readable_receipt(state["active"])
    active_id = active.get("id") if active else None
    projection = {
        "selected_task_id": selected_id,
        "active_projection_id": active_id,
        "active_projection_error": active_error,
        "matches_selected": active_error is None and active_id == selected_id,
    }
    print(json.dumps({
        "schema_version": 1,
        "status": "ready",
        "repo_root": str(repo),
        "project_id": project.get("project_id"),
        "project_revision": project.get("state_revision", 0),
        "branch": branch,
        "head": head,
        "context_key": key,
        "projection": projection,
        "operations": [
            "restore-task",
            "reconcile-projection",
            "recover-interrupted-upgrade",
        ],
        "repair_candidates": candidates,
        "upgrade_status": upgrade_status,
        "upgrade_transactions": upgrade_transactions,
    }, ensure_ascii=False))
    return 0


def command_fix_recover_interrupted_upgrade(
    control,
    repo: pathlib.Path,
    state: dict[str, pathlib.Path],
    args: argparse.Namespace,
    *,
    identifier: str,
    reason: str,
    confirmation_source: str,
) -> int:
    if args.task_id is not None or args.expected_task_revision is not None:
        raise ValueError("recover-interrupted-upgrade does not accept task arguments")
    upgrade_id = control.require_concrete("interrupted upgrade id", args.upgrade_id or "")
    expected_manifest = control.require_concrete(
        "expected upgrade manifest digest",
        args.expected_upgrade_manifest_sha256 or "",
    )
    expected_fingerprint = control.require_concrete(
        "expected interrupted upgrade fingerprint",
        args.expected_current_fingerprint or "",
    )
    transactions = inspect_upgrade_transactions(control, state)
    candidate = find_interrupted_upgrade(transactions, upgrade_id)
    if candidate.get("manifest_sha256") != expected_manifest:
        raise ValueError("interrupted upgrade manifest changed; inspect again")
    if candidate.get("current_fingerprint") != expected_fingerprint:
        raise ValueError("interrupted upgrade state changed; inspect again")
    source_backup = state["upgrade_backups"] / upgrade_id
    _manifest, records, _directories = read_upgrade_manifest(control, state, source_backup)
    affected = [state["root"] / record["relative"] for record in records]
    affected.append(state["repair_history"])
    backup_root = repair_backup(control, state, identifier, affected)
    try:
        control.restore_legacy_upgrade_backup(state, source_backup)
        readback_transactions = inspect_upgrade_transactions(control, state)
        transaction = next(
            item for item in readback_transactions if item.get("upgrade_id") == upgrade_id
        )
        if transaction.get("status") != "rolled_back":
            raise ValueError("interrupted upgrade rollback did not restore its recorded pre-state")
        upgrade_inspection = control.legacy_upgrade_inspection_payload(repo, state)
        readback = {
            "upgrade_transaction": transaction,
            "legacy_upgrade_status": upgrade_inspection.get("status"),
            "pending_steps": upgrade_inspection.get("upgrade", {}).get("pending_steps", []),
        }
        audit = {
            "schema_version": 1,
            "repair_id": identifier,
            "at": control.now(),
            "operation": "recover-interrupted-upgrade",
            "upgrade_id": upgrade_id,
            "reason": reason,
            "confirmation_source": confirmation_source,
            "backup": str(backup_root.relative_to(state["root"])),
            "source_upgrade_backup": str(source_backup.relative_to(state["root"])),
            "readback": readback,
        }
        append_repair_audit(control, state, audit)
    except Exception:
        restore_repair_backup(control, state, backup_root)
        raise
    print(json.dumps({
        "status": "repaired",
        "repair_id": identifier,
        "operation": "recover-interrupted-upgrade",
        "upgrade_id": upgrade_id,
        "backup": audit["backup"],
        "source_upgrade_backup": audit["source_upgrade_backup"],
        "readback": readback,
    }, ensure_ascii=False))
    return 0


def repair_readback(control, 
    repo: pathlib.Path,
    state: dict[str, pathlib.Path],
    *,
    task_id: str,
    expected_status: str,
) -> dict[str, Any]:
    payload = control.build_status_payload(repo, state, view="compact")
    if payload.get("id") != task_id or payload.get("status") != expected_status:
        raise ValueError("repair readback does not match the requested task state")
    return {
        "task_id": payload.get("id"),
        "status": payload.get("status"),
        "state_revision": payload.get("state_revision"),
        "project_revision": payload.get("project_revision"),
        "continuity_status": payload.get("continuity_status"),
        "strict_blockers": payload.get("strict_blockers", []),
    }


def repair_selected_task(control, 
    state: dict[str, pathlib.Path],
    context: dict[str, Any],
    *,
    target_task_id: str,
    args: argparse.Namespace,
    identifier: str,
    reason: str,
    confirmation_source: str,
) -> str | None:
    selected_id = context.get("active_task_id")
    if not selected_id or selected_id == target_task_id:
        if args.replace_selected_task_id or args.expected_selected_task_revision is not None:
            raise ValueError("replace-selected arguments are only valid when another task is selected")
        return None
    if args.replace_selected_task_id != selected_id or args.expected_selected_task_revision is None:
        raise ValueError(
            "another task is selected on this branch; provide its id and expected revision to replace it"
        )
    selected = control.read_task(state, str(selected_id))
    actual_revision = int(selected.get("state_revision", 0))
    if args.expected_selected_task_revision != actual_revision:
        raise ValueError(
            "selected task revision conflict: "
            f"expected {actual_revision}, received {args.expected_selected_task_revision}"
        )
    selected["status"] = "paused"
    control.continuity_event(
        selected,
        "control_repair_displaced",
        repair_id=identifier,
        reason=reason,
        confirmation_source=confirmation_source,
        replaced_by=target_task_id,
    )
    control.write_inactive_task(state, selected, expected_revision=actual_revision)
    return str(selected_id)


def command_fix_apply(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    if not state["root"].is_dir():
        raise ValueError("control-plane repair requires an existing .auto-dev control")
    identifier = repair_id(control, )
    reason = control.require_concrete("repair reason", args.reason)
    confirmation_source = control.require_concrete("repair confirmation source", args.confirmation_source)
    with control.state_lock(state["root"] / "repair"):
        if args.operation == "recover-interrupted-upgrade":
            return command_fix_recover_interrupted_upgrade(
                control,
                repo,
                state,
                args,
                identifier=identifier,
                reason=reason,
                confirmation_source=confirmation_source,
            )
        if any(
            value is not None
            for value in (
                args.upgrade_id,
                args.expected_upgrade_manifest_sha256,
                args.expected_current_fingerprint,
            )
        ):
            raise ValueError("task repair operations do not accept upgrade arguments")
        _project, context, receipt, _key, _branch = repair_context(control, repo, state, args)
        target_path = control.task_path(state, str(receipt["id"]))
        selected_id = context.get("active_task_id")
        affected = [
            state["project"],
            state["project"].with_suffix(".bak"),
            state["active"],
            state["active"].with_suffix(".bak"),
            state["repair_history"],
            target_path,
            target_path.with_suffix(".bak"),
        ]
        if selected_id and selected_id != receipt["id"]:
            selected_path = control.task_path(state, str(selected_id))
            affected.extend([selected_path, selected_path.with_suffix(".bak")])
        backup_root = repair_backup(control, state, identifier, affected)
        displaced_task_id = None
        previous_status = str(receipt.get("status"))
        try:
            _projected, projection_error = control.readable_receipt(state["active"])
            if projection_error:
                state["active"].unlink(missing_ok=True)
            if args.operation == "restore-task":
                if previous_status not in control.TERMINAL_TASK_STATUSES:
                    raise ValueError("restore-task only accepts an archived terminal task")
                if args.target_status not in {"active", "review_ready"}:
                    raise ValueError("restore-task requires --target-status active or review_ready")
                if args.target_status == "review_ready":
                    review = receipt.get("review") if isinstance(receipt.get("review"), dict) else {}
                    validation = review.get("validation_results") if isinstance(review.get("validation_results"), list) else []
                    if not validation:
                        raise ValueError("restoring to review_ready requires preserved review validation evidence")
                displaced_task_id = repair_selected_task(control, 
                    state,
                    context,
                    target_task_id=str(receipt["id"]),
                    args=args,
                    identifier=identifier,
                    reason=reason,
                    confirmation_source=confirmation_source,
                )
                receipt["status"] = args.target_status
                receipt["reopened_at"] = control.now()
                control.continuity_event(
                    receipt,
                    "control_repaired",
                    repair_id=identifier,
                    operation="restore-task",
                    from_status=previous_status,
                    to_status=args.target_status,
                    reason=reason,
                    confirmation_source=confirmation_source,
                )
                next_revision = control.write_active(
                    state,
                    receipt,
                    expected_revision=args.expected_task_revision,
                )
                readback = repair_readback(control, 
                    repo,
                    state,
                    task_id=str(receipt["id"]),
                    expected_status=args.target_status,
                )
            elif args.operation == "reconcile-projection":
                if args.target_status is not None:
                    raise ValueError("reconcile-projection does not accept --target-status")
                if selected_id != receipt["id"]:
                    raise ValueError("reconcile-projection requires the task to remain selected")
                if receipt.get("status") not in {"active", "review_ready"}:
                    raise ValueError("reconcile-projection requires an active or review_ready task")
                if args.replace_selected_task_id or args.expected_selected_task_revision is not None:
                    raise ValueError("reconcile-projection cannot replace the selected task")
                control.continuity_event(
                    receipt,
                    "control_repaired",
                    repair_id=identifier,
                    operation="reconcile-projection",
                    reason=reason,
                    confirmation_source=confirmation_source,
                )
                next_revision = control.write_active(
                    state,
                    receipt,
                    expected_revision=args.expected_task_revision,
                )
                readback = repair_readback(control, 
                    repo,
                    state,
                    task_id=str(receipt["id"]),
                    expected_status=str(receipt["status"]),
                )
            else:  # argparse choices prevent this, but preserve a deterministic failure contract.
                raise ValueError(f"unsupported repair operation: {args.operation}")
            audit = {
                "schema_version": 1,
                "repair_id": identifier,
                "at": control.now(),
                "operation": args.operation,
                "task_id": receipt["id"],
                "from_status": previous_status,
                "to_status": readback["status"],
                "reason": reason,
                "confirmation_source": confirmation_source,
                "backup": str(backup_root.relative_to(state["root"])),
                "displaced_task_id": displaced_task_id,
                "readback": readback,
            }
            append_repair_audit(control, state, audit)
        except Exception:
            restore_repair_backup(control, state, backup_root)
            raise
    print(json.dumps({
        "status": "repaired",
        "repair_id": identifier,
        "operation": args.operation,
        "task_id": receipt["id"],
        "state_revision": next_revision,
        "backup": audit["backup"],
        "displaced_task_id": displaced_task_id,
        "readback": readback,
    }, ensure_ascii=False))
    return 0
