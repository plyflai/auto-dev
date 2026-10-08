#!/usr/bin/env python3
"""Stable CLI facade for the Auto Dev control plane.

Domain implementations live in the sibling modules; this file keeps the
historical import path, public symbols, parser, and process-level error policy.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys

from auto_dev_internal.foundation.core import *
from auto_dev_internal.legacy.models import (
    LegacyUpgradePlan,
    LegacyUpgradeStep,
    LegacyUpgradeTask,
    ControlPlaneStateSurface,
    CONTROL_PLANE_STATE_SURFACES,
)
from auto_dev_internal.foundation import receipts as runctl_receipts
from auto_dev_internal.foundation import runtime as runctl_runtime
from auto_dev_internal.legacy import models as runctl_legacy_models
from auto_dev_internal.task import commands as runctl_task_commands

WORKSPACE_CHECKPOINT_PHASES = {
    "baseline": "before_change",
    "milestone": "after_change",
    "archive": "after_change",
}
WORKSPACE_CHECKPOINT_RECEIPT_KEYS = {
    "before_change": "workspace_checkpoint_before",
    "after_change": "workspace_checkpoint_after",
}

_CONTROL = sys.modules[__name__]


def _control_delegate(module_name: str, function_name: str):
    def delegate(*args, **kwargs):
        module = importlib.import_module(module_name)
        return getattr(module, function_name)(_CONTROL, *args, **kwargs)

    delegate.__name__ = function_name
    delegate.__qualname__ = function_name
    return delegate


def _plain_delegate(module_name: str, function_name: str):
    def delegate(*args, **kwargs):
        module = importlib.import_module(module_name)
        return getattr(module, function_name)(*args, **kwargs)

    delegate.__name__ = function_name
    delegate.__qualname__ = function_name
    return delegate


def upgrade_relative_path(state, path):
    try:
        return path.relative_to(state["root"]).as_posix()
    except ValueError as error:
        raise ValueError("legacy upgrade path escapes .auto-dev") from error


def clone_json(value):
    return copy.deepcopy(value)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def project_upgrade_version(project):
    value = project.get("control_plane_upgrade_version", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("control-plane upgrade version is malformed")
    return value


def require_upgrade_context_storage(plan, context_id, entry):
    try:
        unlinked_outcome_id = entry["unlinked_outcome_id"]
        if not isinstance(unlinked_outcome_id, str):
            raise ValueError("unlinked outcome id is malformed")
        require_control_id("unlinked outcome id", unlinked_outcome_id)
        frame = read_context_frame(plan.state, context_id)
        if frame.get("id") != context_id:
            raise ValueError("context frame id is malformed")
        outcome = read_json(outcome_record_path(plan.state, context_id, unlinked_outcome_id))
        if outcome.get("id") != unlinked_outcome_id:
            raise ValueError("unlinked outcome id is malformed")
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as error:
        plan.add_blocker(
            "existing_context_storage_unreadable",
            f"managed project context {context_id} cannot be safely upgraded: {error}",
        )
        return False
    return True


def staged_upgrade_task_receipt(plan, task):
    target_path = task.task_path or task_path(plan.state, task.identifier)
    staged = plan.writes.get(target_path)
    if staged is None and task.active_projection:
        staged = plan.writes.get(plan.state["active"])
    return clone_json(staged if staged is not None else task.receipt)


# Legacy upgrade orchestration remains a compatibility surface, but its
# implementation is owned by runctl_legacy_plan through runctl_legacy.
for _name in (
    "legacy_upgrade_source_fingerprint",
    "legacy_upgrade_historical_runs",
    "legacy_upgrade_read_receipt",
    "collect_legacy_upgrade_tasks",
    "legacy_upgrade_has_control_artifacts",
    "legacy_upgrade_branch_context",
    "preserve_legacy_branch_index",
    "legacy_upgrade_step_hierarchy_adoption",
    "normalize_legacy_proof_attempts",
    "legacy_upgrade_step_state_contract_adoption",
    "legacy_upgrade_step_verification_gate_policy",
    "legacy_upgrade_step_environment_domain_memory",
    "legacy_upgrade_step_plan_strategy_adoption",
    "validate_legacy_upgrade_registry",
    "pending_legacy_upgrade_steps",
    "control_plane_surface_status",
    "assess_control_plane_state",
    "build_legacy_upgrade_plan",
    "legacy_upgrade_status",
    "control_plane_upgrade_projection",
    "legacy_upgrade_step_payload",
    "legacy_upgrade_inspection_payload",
    "legacy_upgrade_created_directories",
    "legacy_upgrade_backup",
    "restore_legacy_upgrade_backup",
    "append_legacy_upgrade_audit",
    "legacy_upgrade_readback",
    "command_legacy_upgrade_inspect",
    "command_legacy_upgrade_apply",
):
    globals()[_name] = _control_delegate(
        "auto_dev_internal.legacy.orchestration", _name
    )


LEGACY_UPGRADE_STEPS = (
    LegacyUpgradeStep(
        version=1,
        identifier="hierarchy-adoption-v1",
        title="收编旧任务投影到分层控制面",
        description="建立临时项目上下文和未归属结果节点，并安全归属可读的旧任务投影。",
        planner=legacy_upgrade_step_hierarchy_adoption,
        surface_ids=("project", "task_receipts"),
    ),
    LegacyUpgradeStep(
        version=2,
        identifier="state-contract-adoption-v2",
        title="采用版本化控制面状态契约",
        description="统一升级任务、连续性、Proof 元数据、项目记忆和其他持久状态面；旧验证结果只标记待复验。",
        planner=legacy_upgrade_step_state_contract_adoption,
        surface_ids=tuple(
            surface.identifier
            for surface in CONTROL_PLANE_STATE_SURFACES
            if surface.adopted_in_version <= 2
        ),
    ),
    LegacyUpgradeStep(
        version=3,
        identifier="verification-gate-policy-v3",
        title="区分开发写入门与交付复验门",
        description="历史节点 Proof 因后续开发变 stale 时保留交付阻断，但允许当前节点在既定范围内继续修复。",
        planner=legacy_upgrade_step_verification_gate_policy,
        surface_ids=("verification_gate_policy",),
    ),
    LegacyUpgradeStep(
        version=4,
        identifier="environment-domain-memory-v4",
        title="采用环境与项目领域记忆",
        description="在新的 Project Memory 中建立结构化环境与领域事实，并生成可再生的人读投影。",
        planner=legacy_upgrade_step_environment_domain_memory,
        surface_ids=("project_memory", "environment_projection", "domain_projection"),
    ),
    LegacyUpgradeStep(
        version=5,
        identifier="rolling-plan-envelope-v5",
        title="采用滚动里程碑计划信封",
        description=(
            "为历史计划显式标记 legacy 策略并初始化滚动图字段；"
            "不推断 Milestone、Work Packet 或历史依赖。"
        ),
        planner=legacy_upgrade_step_plan_strategy_adoption,
        surface_ids=("task_receipts", "continuity", "plan_strategy"),
    ),
)


def validate_control_plane_state_surface_registry() -> None:
    identifiers = [surface.identifier for surface in CONTROL_PLANE_STATE_SURFACES]
    if len(set(identifiers)) != len(identifiers):
        raise RuntimeError("control-plane state surface registry contains duplicate ids")
    expected = {
        "project": PROJECT_SCHEMA_VERSION,
        "task_receipts": SCHEMA_VERSION,
        "continuity": CONTINUITY_SCHEMA_VERSION,
        "proof_attempts": "append-only-v1",
        "project_memory": project_memory.REGISTRY_SCHEMA_VERSION,
        "environment_projection": "environment-profile-v1",
        "domain_projection": "domain-memory-v1",
        "dependency_lease": project_memory.LEASE_SCHEMA_VERSION,
        "runtime_diagnostics": RUNTIME_DIAGNOSTICS_SCHEMA_VERSION,
        "workspace_policy": WORKSPACE_POLICY_SCHEMA_VERSION,
        "handoff_packet": 1,
        "verification_gate_policy": VERIFICATION_GATE_POLICY,
        "plan_strategy": "plan-strategy-v1",
    }
    for surface in CONTROL_PLANE_STATE_SURFACES:
        if surface.identifier not in expected:
            raise RuntimeError(f"unknown control-plane state surface: {surface.identifier}")
        if surface.target_schema != expected[surface.identifier]:
            raise RuntimeError(
                f"state surface {surface.identifier} targets {surface.target_schema!r}, "
                f"expected {expected[surface.identifier]!r}"
            )
        if surface.adopted_in_version > CONTROL_PLANE_UPGRADE_VERSION:
            raise RuntimeError(
                f"state surface {surface.identifier} is adopted after the current upgrade version"
            )


# Small helpers retained by the historical facade.
for _name in (
    "require_concrete",
    "require_concrete_list",
    "optional_concrete_list",
    "require_continuity_id",
    "require_display_code",
    "outcome_digest",
    "redact_command_parts",
    "require_diagnostic_id",
    "normalize_diagnostic_fields",
    "load_runtime_diagnostics",
    "current_branch",
    "current_status",
    "status_path",
    "workspace_control_metadata_path",
    "workspace_product_status",
    "worktree_fingerprint",
    "local_scope_manifest",
    "capture_local_snapshot",
    "capture_worktree_baseline",
    "worktree_drift",
    "path_in_scope",
    "normalize_scopes",
    "capture_snapshot",
    "snapshot_prune_projection",
    "parse_budgets",
    "parse_skips",
    "parse_capability_evidence",
    "validate_capabilities",
    "classify_capabilities",
    "merge_unique",
    "sync_budget_state",
    "normalize_receipt",
    "continuity_from_receipt",
    "continuity_reconciliation_issues",
    "continuity_event",
    "continuity_nodes",
    "action_evidence_links",
    "unattributed_action_evidence",
    "require_action_node",
    "current_plan_revision",
    "redact_for_handoff",
    "repo_fingerprint",
    "workspace_summary",
    "ensure_write_ready",
    "require_active",
    "require_working_task",
    "continuity_has_plan",
    "readable_receipt",
):
    globals()[_name] = getattr(runctl_receipts, _name)


for _name in (
    "command_task_list",
    "command_task_pause",
    "command_task_select",
    "command_task_amend_scope",
    "command_task_resume",
    "command_task_attribute",
):
    globals()[_name] = getattr(runctl_task_commands, _name)

for _name in (
    "command_diagnostics",
    "codegraph_binary",
    "codegraph_index_fingerprint",
    "codegraph_json",
    "codegraph_status_snapshot",
    "normalized_codegraph_path",
    "command_recover",
    "command_migrate",
):
    globals()[_name] = getattr(runctl_runtime, _name)


_CONTROL_ADAPTERS = {
    "auto_dev_internal.intake.workflow": (
        "read_optional_json", "read_intake_gate", "write_intake_gate",
        "read_intake_record", "find_intake_record", "intake_baseline_hash",
        "contract_from_args", "contract_status", "strict_contract_hash",
        "strict_receipt_contract_hash", "outcome_identity_contract",
        "outcome_contract_chain", "parent_contract_for_task",
        "effective_contract_for_outcome", "require_contract_diff_confirmation",
        "effective_contract_for_task", "contract_projection",
        "contract_gate_for_receipt", "validate_contract_plan",
        "validate_contract_readiness", "validate_node_contract_proofs",
        "intake_summary", "intake_gate_projection", "require_pending_turn",
        "decode_json_object", "decode_json_decisions", "normalize_intake_decisions",
        "intake_text_list", "command_intake_turn", "command_intake_status",
        "command_intake_assess", "command_intake_resolve", "command_intake_confirm",
        "command_intake_reopen", "command_intake_show",
    ),
    "auto_dev_internal.project.model": (
        "normalize_external_references", "command_project_context_list",
        "command_project_context_show", "command_project_context_adopt",
        "command_project_context_set", "command_project_context_select",
        "read_outcome_record", "list_outcome_records", "outcome_summary",
        "outcome_coverage_rollup", "outcome_edges", "outcome_graph_has_cycle",
        "validate_outcome_graph", "confirmed_intake_for_context",
        "command_outcome_list", "command_outcome_show", "command_outcome_add",
        "command_outcome_set", "command_outcome_link", "command_outcome_move",
        "read_capability_record", "list_capability_records", "capability_summary",
        "normalize_capability_outcomes", "command_capability_list",
        "command_capability_add", "command_capability_set", "activity_record_path",
        "read_activity_record", "list_activity_records", "activity_summary",
        "command_activity_list", "command_activity_record", "read_view_focus",
        "command_focus_show", "command_focus_set",
    ),
    "auto_dev_internal.task.state": (
        "prepare_task_attribution", "bind_intake_to_task", "task_summary",
        "read_task", "current_context", "sync_task_projection",
        "clear_branch_active", "resolve_branch_task", "write_active",
        "write_inactive_task",
    ),
    "auto_dev_internal.project.outcome_review": (
        "load_product_review_input", "normalize_product_review",
        "product_review_receipt", "normalize_outcome", "command_task_review",
    ),
    "auto_dev_internal.verification.evidence": (
        "task_proof_evidence", "task_e2e_evidence", "task_release_evidence",
        "require_proof_id", "proof_attempt_id", "proof_history", "latest_proof",
        "proof_is_fresh", "proof_attempts_by_id", "evidence_links_by_id",
        "proof_context_is_fresh", "read_json_evidence_manifest", "evidence_path",
        "evidence_text", "read_evidence_artifact", "normalize_e2e_evidence",
        "read_e2e_evidence", "exact_evidence_fields", "normalize_release_evidence",
        "read_release_evidence", "evidence_number", "normalize_performance_evidence",
        "read_performance_evidence", "bind_performance_baseline",
        "read_proof_evidence", "read_product_evidence", "evidence_file_is_fresh",
        "e2e_evidence_is_fresh", "performance_evidence_is_fresh", "command_proof",
    ),
    "auto_dev_internal.verification.debug": (
        "normalize_diagnostic", "diagnostic_refs_fresh", "diagnostic_projection",
        "diagnostic_summary", "debug_command_context", "require_diagnostic_refs",
        "command_debug_inspect", "command_debug_begin", "command_debug_case_search_bind",
        "command_debug_reproduction_record", "command_debug_hypothesis_add",
        "command_debug_observe", "command_debug_resolve", "command_debug_recovery",
        "command_memory_case_search", "command_memory_case_promote",
    ),
    "auto_dev_internal.verification.policy_impact": (
        "default_workspace_policy", "normalize_policy_pattern", "normalize_policy_path",
        "normalize_policy_rule", "normalize_workspace_policy", "load_workspace_policy",
        "workspace_policy_digest", "policy_pattern_matches",
        "effective_workspace_policy_rules", "workspace_policy_path_evaluation",
        "policy_approval_projection", "sensitive_policy_evidence",
        "workspace_policy_projection", "protected_branches", "is_protected",
        "impact_inspection", "impact_projection", "impact_receipt_text",
        "policy_receipt_text", "load_policy_input", "command_policy", "command_impact",
    ),
    "auto_dev_internal.project.bootstrap": (
        "bootstrap_candidate", "bootstrap_inspection", "load_bootstrap_plan",
        "command_bootstrap_inspect", "command_bootstrap_apply",
    ),
    "auto_dev_internal.task.delivery": (
        "command_start", "command_escalate", "command_capabilities",
        "command_event", "command_evidence_link", "command_plan",
        "command_checkpoint",
    ),
    "auto_dev_internal.task.milestones": (
        "rolling_frontier_projection", "refresh_rolling_frontier",
        "milestone_projection", "integration_inspection", "review_inspection",
        "command_milestone_frontier", "command_milestone_compile_inspect",
        "command_milestone_compile_apply", "command_milestone_integration_inspect",
        "command_milestone_integration_record", "command_milestone_review_inspect",
        "command_milestone_review_record", "command_milestone_execution_inspect",
        "command_milestone_execution_select", "command_milestone_execution_revalidate",
        "command_milestone_handoff_take",
    ),
    "auto_dev_internal.task.workers": (
        "command_worker_prepare", "command_worker_bind", "command_worker_inspect", "command_worker_capture",
        "command_worker_apply", "command_worker_cleanup",
        "command_worker_finalize_inspect", "command_worker_finalize_apply",
    ),
    "auto_dev_internal.task.completion": (
        "validate_completion_readiness", "archive_receipt", "archive",
        "command_finish", "command_abandon",
    ),
    "auto_dev_internal.continuity.workspace": (
        "archive_slug", "workspace_sensitive_path", "workspace_dirty_paths",
        "workspace_scope_digest", "workspace_checkpoint_phase",
        "workspace_checkpoint_receipt_key", "workspace_checkpoint_short_hash",
        "workspace_checkpoint_receipt",
        "workspace_point_projection", "workspace_checkpoint_protection_receipt",
        "receipt_workspace_checkpoint_protections", "find_workspace_checkpoint_protection",
        "workspace_checkpoint_protection_point_projection",
        "workspace_checkpoint_protection_projection",
        "workspace_checkpoint_protections_projection",
        "workspace_checkpoint_node_point_projection", "workspace_checkpoint_node_projection",
        "receipt_workspace_points",
        "workspace_checkpoint_records", "workspace_required_proofs",
        "workspace_checkpoint_refs", "workspace_checkpoint_protection_state",
        "workspace_checkpoint_preview", "command_workspace_checkpoint_protect",
        "command_workspace_checkpoint", "command_workspace_rollback_inspect",
    ),
    "auto_dev_internal.foundation.status": (
        "build_status_identity", "build_status_payload", "agent_focus_projection",
    ),
    "auto_dev_internal.continuity.handoff": (
        "command_handoff_export", "command_handoff_import"
    ),
    "auto_dev_internal.continuity.refresh": ("command_refresh",),
    "auto_dev_internal.transition": ("command_transition",),
    "auto_dev_internal.continuity.repair": (
        "repair_id", "control_file_digest", "repair_backup", "restore_repair_backup",
        "append_repair_audit", "repair_context", "repair_candidate", "command_fix_inspect",
        "repair_readback", "repair_selected_task", "command_fix_apply",
    ),
    "auto_dev_internal.project.lifecycle": (
        "command_project_inspect", "command_project_init", "command_project_migrate",
    ),
}

for _module_name, _names in _CONTROL_ADAPTERS.items():
    for _name in _names:
        globals()[_name] = _control_delegate(_module_name, _name)

# Plan utilities intentionally preserve their old mixed signatures.
for _name in (
    "title_display_code", "major_milestone_number", "normalized_numbered_title",
    "normalize_plan_numbering", "load_plan_input", "plan_state_issues",
    "node_dependency_satisfied", "node_contract_digest", "plan_graph_digest", "node_role",
):
    globals()[_name] = _plain_delegate("auto_dev_internal.task.plan", _name)
for _name in (
    "decision_for", "decision_is_current", "build_pending_decision",
    "select_decision", "handoff_state", "assignment_mode", "resolve_worker_profile",
):
    globals()[_name] = _plain_delegate("auto_dev_internal.task.execution", _name)
validate_plan_nodes = _control_delegate(
    "auto_dev_internal.task.plan", "validate_plan_nodes"
)
validate_rolling_plan = _control_delegate(
    "auto_dev_internal.task.plan", "validate_rolling_plan"
)

# A few task-state helpers historically accepted no facade argument.
task_path = _plain_delegate("auto_dev_internal.task.state", "task_path")
state_lock = _plain_delegate("auto_dev_internal.task.state", "state_lock")


def command_status(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_root)
    state = paths(repo)
    requested_view = getattr(args, "view", None)
    view = requested_view or ("compact" if (args.compact or args.strict) else "full")
    payload = build_status_payload(
        repo,
        state,
        view=view,
        session_key=getattr(args, "session_key", None),
        project_context_id=getattr(args, "project_context", None),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict and payload.get("continuity_status") != "ready":
        return 2
    return 0


def command_snapshot_prune(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_root)
    print(json.dumps(snapshot_prune_projection(repo, paths(repo)), ensure_ascii=False))
    return 0


def command_resume(args: argparse.Namespace) -> int:
    args.compact = True
    args.strict = True
    return command_status(args)


def build_parser() -> argparse.ArgumentParser:
    return importlib.import_module("auto_dev_internal.foundation.cli").build_parser(_CONTROL)


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            detail = error.stderr.strip() or error.stdout.strip() or str(error)
        else:
            detail = str(error)
        print(f"{os.environ.get('AUTO_DEV_CLI_PROG', 'runctl.py')}: {detail}", file=sys.stderr)
        return 2


# Bind global helpers for the extracted implementations after all facade
# delegates and compatibility constants exist.
runctl_legacy_models.bind(_CONTROL)
runctl_receipts.bind(_CONTROL)
runctl_task_commands.bind(_CONTROL)
runctl_runtime.bind(_CONTROL)


if __name__ == "__main__":
    raise SystemExit(main())
