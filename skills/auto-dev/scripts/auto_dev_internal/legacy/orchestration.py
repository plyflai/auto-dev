"""Versioned legacy control-plane inspection and migration orchestration."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
from typing import Any, Iterable


def legacy_upgrade_source_fingerprint(control, state: dict[str, pathlib.Path]) -> str:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_source_fingerprint(control, state)


def legacy_upgrade_historical_runs(control, state: dict[str, pathlib.Path]) -> dict[str, Any]:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_historical_runs(control, state)


def legacy_upgrade_read_receipt(
    control, plan: control.LegacyUpgradePlan, path: pathlib.Path, *, source: str
) -> control.LegacyUpgradeTask | None:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_read_receipt(control, plan, path, source=source)


def collect_legacy_upgrade_tasks(control, plan: control.LegacyUpgradePlan) -> None:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.collect_legacy_upgrade_tasks(control, plan)


def legacy_upgrade_has_control_artifacts(control, state: dict[str, pathlib.Path]) -> bool:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_has_control_artifacts(control, state)


def legacy_upgrade_branch_context(
    control, plan: control.LegacyUpgradePlan, branch_key: str
) -> dict[str, Any] | None:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_branch_context(control, plan, branch_key)


def preserve_legacy_branch_index(control, plan: control.LegacyUpgradePlan) -> None:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.preserve_legacy_branch_index(control, plan)


def legacy_upgrade_step_hierarchy_adoption(control, plan: control.LegacyUpgradePlan) -> None:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_step_hierarchy_adoption(control, plan)


def normalize_legacy_proof_attempts(control, continuity: dict[str, Any]) -> None:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.normalize_legacy_proof_attempts(control, continuity)


def legacy_upgrade_step_state_contract_adoption(control, plan: control.LegacyUpgradePlan) -> None:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_step_state_contract_adoption(control, plan)


def legacy_upgrade_step_verification_gate_policy(
    control, plan: control.LegacyUpgradePlan
) -> None:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_step_verification_gate_policy(control, plan)


def legacy_upgrade_step_environment_domain_memory(
    control, plan: control.LegacyUpgradePlan
) -> None:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_step_environment_domain_memory(control, plan)


def legacy_upgrade_step_plan_strategy_adoption(
    control, plan: control.LegacyUpgradePlan
) -> None:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_step_plan_strategy_adoption(control, plan)


def validate_legacy_upgrade_registry(control) -> None:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.validate_legacy_upgrade_registry(control)


def pending_legacy_upgrade_steps(control, current_version: int) -> list[control.LegacyUpgradeStep]:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.pending_legacy_upgrade_steps(control, current_version)


def control_plane_surface_status(
    control,
    plan: control.LegacyUpgradePlan,
    surface: control.ControlPlaneStateSurface,
    *,
    present: bool,
    source_schema: int | str | None,
) -> str:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.control_plane_surface_status(
        control, plan, surface, present=present, source_schema=source_schema
    )


def assess_control_plane_state(control, plan: control.LegacyUpgradePlan) -> None:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.assess_control_plane_state(control, plan)


def build_legacy_upgrade_plan(
    control, repo: pathlib.Path, state: dict[str, pathlib.Path]
) -> control.LegacyUpgradePlan:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.build_legacy_upgrade_plan(control, repo, state)


def legacy_upgrade_status(control, plan: control.LegacyUpgradePlan) -> str:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_status(control, plan)


def control_plane_upgrade_projection(
    control,
    project: dict[str, Any],
    *,
    repo: pathlib.Path | None = None,
    state: dict[str, pathlib.Path] | None = None,
    profile: str = "full",
    active_reconciliation_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.control_plane_upgrade_projection(
        control,
        project,
        repo=repo,
        state=state,
        profile=profile,
        active_reconciliation_issues=active_reconciliation_issues,
    )


def legacy_upgrade_step_payload(
    control, steps: Iterable[control.LegacyUpgradeStep]
) -> list[dict[str, Any]]:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_step_payload(control, steps)


def legacy_upgrade_inspection_payload(
    control,
    repo: pathlib.Path,
    state: dict[str, pathlib.Path],
    *,
    include_legacy_material: bool = False,
) -> dict[str, Any]:
    from auto_dev_internal.legacy import plan as runctl_legacy_plan

    return runctl_legacy_plan.legacy_upgrade_inspection_payload(
        control,
        repo,
        state,
        include_legacy_material=include_legacy_material,
    )


def legacy_upgrade_created_directories(
    control, state: dict[str, pathlib.Path], paths_to_write: Iterable[pathlib.Path]
) -> list[str]:
    directories: set[pathlib.Path] = set()
    for path in paths_to_write:
        parent = path.parent
        while parent != state["root"] and (not parent.exists()):
            directories.add(parent)
            parent = parent.parent
    return [
        control.upgrade_relative_path(state, directory)
        for directory in sorted(directories, key=lambda value: (len(value.parts), value.as_posix()))
    ]


def legacy_upgrade_backup(
    control,
    state: dict[str, pathlib.Path],
    identifier: str,
    affected_paths: Iterable[pathlib.Path],
    created_directories: Iterable[str],
) -> pathlib.Path:
    backup_root = state["upgrade_backups"] / identifier
    state["upgrade_backups"].mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=False)
    records = []
    for path in affected_paths:
        relative = control.upgrade_relative_path(state, path)
        existed = path.is_file()
        record: dict[str, Any] = {"path": relative, "existed": existed}
        if existed:
            destination = backup_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            record["sha256"] = control.hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(record)
    control.write_json(
        backup_root / "manifest.json",
        {
            "schema_version": 1,
            "upgrade_id": identifier,
            "created_at": control.now(),
            "files": records,
            "created_directories": list(created_directories),
        },
    )
    return backup_root


def restore_legacy_upgrade_backup(
    control, state: dict[str, pathlib.Path], backup_root: pathlib.Path
) -> None:
    manifest = control.read_json(backup_root / "manifest.json")
    records = manifest.get("files")
    directories = manifest.get("created_directories")
    if not isinstance(records, list) or not isinstance(directories, list):
        raise ValueError("legacy upgrade backup manifest is malformed")
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError("legacy upgrade backup contains an invalid file record")
        relative = pathlib.Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("legacy upgrade backup contains an unsafe path")
        destination = state["root"] / relative
        if record.get("existed"):
            source = backup_root / relative
            if not source.is_file():
                raise ValueError("legacy upgrade backup is missing a recorded file")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        else:
            destination.unlink(missing_ok=True)
    safe_directories = []
    for value in directories:
        if not isinstance(value, str):
            raise ValueError("legacy upgrade backup contains an invalid directory record")
        relative = pathlib.Path(value)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError("legacy upgrade backup contains an unsafe directory")
        safe_directories.append(relative)
    for relative in sorted(safe_directories, key=lambda value: len(value.parts), reverse=True):
        destination = state["root"] / relative
        if destination.exists():
            shutil.rmtree(destination)


def append_legacy_upgrade_audit(
    control, state: dict[str, pathlib.Path], payload: dict[str, Any]
) -> None:
    history = state["upgrade_history"]
    with control.state_lock(history):
        with history.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def legacy_upgrade_readback(control, plan: control.LegacyUpgradePlan) -> dict[str, Any]:
    project = control.load_project(plan.state, plan.repo)
    if project is None:
        raise ValueError("legacy upgrade readback cannot find project registry")
    if control.project_upgrade_version(project) != plan.target_version:
        raise ValueError("legacy upgrade readback has an unexpected upgrade version")
    context_id = project.get("default_context_id")
    if not isinstance(context_id, str) or context_id not in project.get("contexts", {}):
        raise ValueError("legacy upgrade readback has no selected managed project context")
    entry = project["contexts"][context_id]
    if not isinstance(entry, dict) or not control.require_upgrade_context_storage(
        plan, context_id, entry
    ):
        raise ValueError("legacy upgrade readback cannot load the default managed project context")
    task_updates = []
    for path, expected in plan.writes.items():
        if isinstance(expected, str):
            actual_text = path.read_text(encoding="utf-8")
            if actual_text != expected:
                raise ValueError(
                    f"legacy upgrade readback differs for {control.upgrade_relative_path(plan.state, path)}"
                )
            continue
        actual = control.read_json(path)
        if control.canonical_json(actual) != control.canonical_json(expected):
            raise ValueError(
                f"legacy upgrade readback differs for {control.upgrade_relative_path(plan.state, path)}"
            )
        if path.parent == plan.state["tasks"]:
            task_updates.append(
                {"id": actual.get("id"), "state_revision": actual.get("state_revision")}
            )
    post_plan = build_legacy_upgrade_plan(control, plan.repo, plan.state)
    return {
        "project_revision": project.get("state_revision"),
        "upgrade_version": control.project_upgrade_version(project),
        "default_context_id": context_id,
        "unlinked_outcome_id": entry.get("unlinked_outcome_id"),
        "task_updates": task_updates,
        "active_task_id": plan.active_task_id,
        "upgrade_status": legacy_upgrade_status(control, post_plan),
        "revalidation_targets": post_plan.revalidation_targets,
        "manual_decisions": post_plan.manual_decisions,
    }


def command_legacy_upgrade_inspect(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    # Keep all plan construction and legacy-material inspection in one
    # request context so proof/scope fingerprints are computed once.
    with control.evaluation_scope(repo):
        payload = legacy_upgrade_inspection_payload(
            control, repo, state, include_legacy_material=True
        )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def command_legacy_upgrade_apply(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    if not state["root"].exists():
        raise ValueError("no auto-dev control exists to upgrade")
    reason = control.require_concrete("legacy upgrade reason", args.reason)
    confirmation_source = control.require_concrete(
        "legacy upgrade confirmation source", args.confirmation_source
    )
    with control.state_lock(state["root"] / "legacy-upgrade"):
        plan = build_legacy_upgrade_plan(control, repo, state)
        if legacy_upgrade_status(control, plan) != "upgrade_available":
            raise ValueError(
                f"legacy upgrade is not applicable: {legacy_upgrade_status(control, plan)}"
            )
        if args.project_revision != plan.project_revision:
            raise ValueError(
                f"project revision conflict: expected {plan.project_revision}, received {args.project_revision}"
            )
        if args.expected_upgrade_version != plan.current_version:
            raise ValueError(
                f"upgrade version conflict: expected {plan.current_version}, received {args.expected_upgrade_version}"
            )
        expected_steps = [step.identifier for step in plan.pending_steps]
        if args.expected_step != expected_steps:
            raise ValueError("legacy upgrade step set is stale or incomplete; inspect again")
        if args.expected_fingerprint != plan.fingerprint:
            raise ValueError("legacy upgrade fingerprint is stale; inspect again")
        if plan.active_task_id is None:
            if args.active_task_revision is not None:
                raise ValueError("active task revision was supplied but no active task is selected")
        elif args.active_task_revision is None:
            raise ValueError("active task revision is required for legacy upgrade")
        elif args.active_task_revision != plan.active_task_revision:
            raise ValueError(
                f"active task revision conflict: expected {plan.active_task_revision}, received {args.active_task_revision}"
            )
        upgrade_id = control.generated_control_id("LEGACY-UPGRADE")
        affected_paths = [*plan.writes.keys(), state["upgrade_history"]]
        created_directories = legacy_upgrade_created_directories(control, state, affected_paths)
        backup_root = legacy_upgrade_backup(
            control, state, upgrade_id, affected_paths, created_directories
        )
        try:
            for path, payload in sorted(
                plan.writes.items(),
                key=lambda item: (
                    item[0] == state["project"],
                    control.upgrade_relative_path(state, item[0]),
                ),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(payload, str):
                    control.write_text(path, payload)
                else:
                    control.write_json(path, payload)
            readback = legacy_upgrade_readback(control, plan)
            audit = {
                "schema_version": 1,
                "upgrade_id": upgrade_id,
                "at": control.now(),
                "from_upgrade_version": plan.current_version,
                "to_upgrade_version": plan.target_version,
                "steps": expected_steps,
                "project_revision_before": plan.project_revision,
                "project_revision_after": readback["project_revision"],
                "active_task_id": plan.active_task_id,
                "active_task_revision_before": plan.active_task_revision,
                "reason": reason,
                "confirmation_source": confirmation_source,
                "backup": control.upgrade_relative_path(state, backup_root),
                "readback": readback,
            }
            append_legacy_upgrade_audit(control, state, audit)
        except Exception:
            restore_legacy_upgrade_backup(control, state, backup_root)
            raise
    print(
        json.dumps(
            {
                "status": "upgraded",
                "upgrade_id": upgrade_id,
                "project_revision": readback["project_revision"],
                "upgrade_version": readback["upgrade_version"],
                "backup": audit["backup"],
                "readback": readback,
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "legacy_upgrade_completed", f"upgrade={upgrade_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0
