"""Versioned legacy control-plane inspection and migration orchestration."""

from __future__ import annotations
import argparse
import hashlib
import json
import os
import pathlib
import shutil
from typing import Any, Iterable


LEGACY_ARTIFACT_SPECS = (
    ("path.md", "environment_path", "auto_dev.py environment set"),
    ("ai-sot.json", "environment_machine_facts", "manual re-entry into auto_dev.py environment set; credentials are rejected"),
    ("project-domain.md", "project_domain", "auto_dev.py domain set"),
    ("current-test.md", "verification_history", "fresh proof --evidence-file or task verification"),
    ("current-debug.md", "diagnostic_history", "current task diagnostic evidence only"),
    ("current-handoff.md", "handoff_history", "handoff import after current contract review"),
    ("postmortem.md", "incident_history", "confirmed incident-case promotion with fresh evidence"),
    ("gui-case-matrix.md", "gui_case_matrix", "current task GUI case matrix"),
    ("gui-evidence-bundle.md", "gui_evidence_bundle", "current task E2E GUI evidence"),
    ("current-gui-test.js", "gui_test_asset", "task-scoped GUI asset reference"),
)
LEGACY_ARTIFACT_HASH_LIMIT = 2 * 1024 * 1024


def legacy_artifact_candidates(repo: pathlib.Path) -> list[dict[str, Any]]:
    """Digest known legacy materials without parsing or importing their contents."""
    legacy_root = repo / ".autodev"
    if not legacy_root.is_dir() or legacy_root.is_symlink():
        return []
    resolved_root = legacy_root.resolve()
    candidates: list[dict[str, Any]] = []
    for relative, kind, suggested_route in LEGACY_ARTIFACT_SPECS:
        path = legacy_root / relative
        if not path.is_file() or path.is_symlink():
            continue
        try:
            path.resolve().relative_to(resolved_root)
            size = path.stat().st_size
        except OSError:
            continue
        candidate: dict[str, Any] = {
            "path": f".autodev/{relative}",
            "kind": kind,
            "size_bytes": size,
            "suggested_route": suggested_route,
            "import_policy": "manual_reentry_required",
            "content_handling": "digest_only",
        }
        if size > LEGACY_ARTIFACT_HASH_LIMIT:
            candidate["sha256"] = None
            candidate["digest_status"] = "skipped_oversize"
        else:
            digest = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(64 * 1024), b""):
                        digest.update(chunk)
            except OSError:
                continue
            candidate["sha256"] = digest.hexdigest()
            candidate["digest_status"] = "collected"
        candidates.append(candidate)
    return candidates


def control_plane_upgrade_projection(
    control,
    project: dict[str, Any],
    *,
    repo: pathlib.Path | None = None,
    state: dict[str, pathlib.Path] | None = None,
    profile: str = "full",
    active_reconciliation_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if profile not in {"full", "active"}:
        raise ValueError(f"unsupported control-plane upgrade projection profile: {profile}")
    if profile == "active":
        try:
            current_version = control.project_upgrade_version(project)
        except ValueError as error:
            return {
                "status": "unavailable",
                "error": str(error),
                "target_version": control.CONTROL_PLANE_UPGRADE_VERSION,
                "audit_scope": "active_task",
                "historical_audit": "deferred",
            }
        if current_version > control.CONTROL_PLANE_UPGRADE_VERSION:
            status = "newer_than_cli"
            pending_steps: list[control.LegacyUpgradeStep] = []
        else:
            pending_steps = control.pending_legacy_upgrade_steps(current_version)
            status = "current" if not pending_steps else "upgrade_available"
        issues = active_reconciliation_issues or []
        revalidation_count = sum(1 for issue in issues if issue.get("proof_id"))
        manual_decision_count = len(issues) - revalidation_count
        if not pending_steps:
            if manual_decision_count:
                status = "manual_decision_required"
            elif revalidation_count:
                status = "reverification_required"
        return {
            "status": status,
            "current_version": current_version,
            "target_version": control.CONTROL_PLANE_UPGRADE_VERSION,
            "pending_step_ids": [step.identifier for step in pending_steps],
            "state_surfaces": [],
            "revalidation_count": revalidation_count,
            "manual_decision_count": manual_decision_count,
            "blocker_count": 0,
            "audit_scope": "active_task",
            "historical_audit": "deferred",
        }
    if repo is not None and state is not None:
        plan = control.build_legacy_upgrade_plan(repo, state)
        return {
            "status": control.legacy_upgrade_status(plan),
            "current_version": plan.current_version,
            "target_version": plan.target_version,
            "pending_step_ids": [step.identifier for step in plan.pending_steps],
            "state_surfaces": plan.state_surfaces,
            "revalidation_count": len(plan.revalidation_targets),
            "manual_decision_count": len(plan.manual_decisions),
            "blocker_count": len(plan.blockers),
            "audit_scope": "full_history",
            "historical_audit": "complete",
        }
    try:
        current_version = control.project_upgrade_version(project)
    except ValueError as error:
        return {
            "status": "unavailable",
            "error": str(error),
            "target_version": control.CONTROL_PLANE_UPGRADE_VERSION,
        }
    if current_version > control.CONTROL_PLANE_UPGRADE_VERSION:
        status = "newer_than_cli"
        pending_steps: list[control.LegacyUpgradeStep] = []
    else:
        pending_steps = control.pending_legacy_upgrade_steps(current_version)
        status = "current" if not pending_steps else "upgrade_available"
    return {
        "status": status,
        "current_version": current_version,
        "target_version": control.CONTROL_PLANE_UPGRADE_VERSION,
        "pending_step_ids": [step.identifier for step in pending_steps],
        "audit_scope": "project_only",
        "historical_audit": "deferred",
    }


def legacy_upgrade_step_payload(
    control, steps: Iterable[control.LegacyUpgradeStep]
) -> list[dict[str, Any]]:
    return [
        {
            "version": step.version,
            "id": step.identifier,
            "title": step.title,
            "description": step.description,
        }
        for step in steps
    ]


def legacy_upgrade_inspection_payload(
    control,
    repo: pathlib.Path,
    state: dict[str, pathlib.Path],
    *,
    include_legacy_material: bool = False,
) -> dict[str, Any]:
    plan = control.build_legacy_upgrade_plan(repo, state)
    status = control.legacy_upgrade_status(plan)
    active_task = None
    if plan.active_task_id is not None:
        active_task = {
            "id": plan.active_task_id,
            "state_revision": plan.active_task_revision,
            "task": plan.tasks[plan.active_task_id].receipt.get("task"),
        }
    task_candidates = [
        {
            "id": task.identifier,
            "state_revision": task.receipt.get("state_revision", 0),
            "schema_version": task.receipt.get("schema_version", 1),
            "status": task.receipt.get("status"),
            "selected": task.active_projection,
            "source": "task_projection" if task.task_path is not None else "active_projection",
        }
        for task in plan.tasks.values()
    ]
    receipt_keys = {
        "upgrade_available": "legacy_upgrade_available",
        "reverification_required": "legacy_upgrade_reverification_required",
        "manual_decision_required": "legacy_upgrade_manual_decision_required",
        "blocked": "legacy_upgrade_blocked",
        "newer_than_cli": "legacy_upgrade_newer_than_cli",
    }
    return {
        "schema_version": 1,
        "status": status,
        "repo_root": str(repo),
        "project": {
            "exists": plan.project_exists,
            "schema_version": plan.source_project_schema,
            "target_schema_version": control.PROJECT_SCHEMA_VERSION,
            "state_revision": plan.project_revision,
            "control_plane_upgrade_version": plan.current_version,
            "target_upgrade_version": plan.target_version,
        },
        "upgrade": {
            "pending_steps": legacy_upgrade_step_payload(control, plan.pending_steps),
            "fingerprint": plan.fingerprint,
            "confirmation_required": status == "upgrade_available",
        },
        "active_task": active_task,
        "task_candidates": task_candidates,
        "changes": plan.changes,
        "state_surfaces": plan.state_surfaces,
        "revalidation_targets": plan.revalidation_targets,
        "manual_decisions": plan.manual_decisions,
        "newer_than_cli": plan.newer_than_cli,
        "unsupported_records": plan.unsupported_records,
        "blockers": plan.blockers,
        "warnings": plan.warnings,
        "historical_runs": plan.historical_runs,
        "legacy_material_scan": {
            "performed": include_legacy_material,
            "scope": ".autodev known migration materials" if include_legacy_material else None,
            "policy": "explicit legacy-upgrade inspect only; never imported automatically",
        },
        "legacy_artifact_candidates": legacy_artifact_candidates(repo) if include_legacy_material else [],
        "apply_contract": {
            "project_revision": plan.project_revision,
            "active_task_revision": plan.active_task_revision,
            "upgrade_version": plan.current_version,
            "expected_steps": [step.identifier for step in plan.pending_steps],
            "fingerprint": plan.fingerprint,
        },
        "receipt": control.bilingual_receipt(
            "🧾 Auto Dev", receipt_keys.get(status, "legacy_upgrade_current")
        ),
    }
