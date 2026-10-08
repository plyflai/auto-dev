#!/usr/bin/env python3
"""Manage local auto-dev Direct and Team run receipts.

Usage:
  python3 runctl.py start --tier direct --repo-root . --task "Fix X" \
    --requirement-receipt REQ-1 --confirmation-source "user confirmed" \
    --acceptance "X works" --scope src/x.ts --validation "target test"
  python3 runctl.py start --help
  python3 runctl.py escalate --repo-root . --reason "Schema changed" \
    --capability data-contract --capability-evidence data-contract="Schema changed"
  python3 runctl.py capabilities --help
  python3 runctl.py event --repo-root . --type repair_attempt \
    --summary "Target test still fails" --consume implementation_repair=1
  python3 runctl.py plan --repo-root . --base-revision 0 \
    --reason "Initial delivery plan" --plan-file /tmp/auto-dev-plan.json
  python3 runctl.py checkpoint --repo-root . --node implementation \
    --plan-revision 1 --state-revision 3 \
    --status done --summary "Implementation verified" \
    --next-node review --next-action "Run final review"
  python3 runctl.py status --repo-root . --compact --strict
  python3 runctl.py bootstrap inspect --repo-root .
  python3 runctl.py bootstrap apply --repo-root . --mode fresh --plan-file /tmp/plan.json \
    --requirement-receipt REQ-1 --goal-confirmation-source "user confirmed goal" \
    --plan-confirmation-source "user confirmed plan" --tier direct
  python3 runctl.py handoff export --repo-root . --out /tmp/auto-dev-handoff.json
  python3 runctl.py handoff import --repo-root . --file /tmp/auto-dev-handoff.json
  python3 runctl.py recover --repo-root .
  python3 runctl.py migrate --repo-root .
  python3 runctl.py legacy-upgrade inspect --repo-root .
  python3 runctl.py legacy-upgrade apply --repo-root . --project-revision 8 \
    --active-task-revision 171 --expected-upgrade-version 0 \
    --expected-step hierarchy-adoption-v1 --expected-fingerprint <inspect-fingerprint> \
    --reason "确认接手旧控制面" --confirmation-source "user confirmed"
  python3 runctl.py diagnostics --repo-root . --id checkout \
    --component checkout --scope src/checkout --layer app.logger \
    --storage "server log file" --retention "7 days" \
    --read "npm run logs -- --component checkout" --event checkout.failed \
    --field timestamp --field level --field component --field event \
    --field outcome --field correlation_id --field error \
    --correlation "request ID" --redaction "tokens are excluded" \
    --verify "failure path read back"
  python3 dependency_manager.py record dependency --repo-root . --id jadx ...
  python3 runctl.py abandon --repo-root . --reason "Requirement replaced"
  python3 runctl.py task review --repo-root . --state-revision 4 --summary "Done" \
    --validation "target test passed" --product-review-file /tmp/product-review.json
  python3 runctl.py finish --repo-root . --status passed --summary "Done" \
    --confirmation-source "user accepted review"
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass, field
import fnmatch
import hashlib
import json
import math
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Any, Callable, Iterable

from receipt_catalog import bilingual_label, receipt as bilingual_receipt
from plugin_identity import auto_dev_plugin_root
import project_memory
from auto_dev_internal.foundation.evaluation import current_evaluation, evaluation_scope
from contract_lineage import (
    EVIDENCE_KINDS,
    capsule as contract_capsule,
    contract_hash,
    coverage_ids as contract_coverage_ids,
    is_strict as contract_is_strict,
    merge_contracts,
    normalize_contract,
    prewrite_coverage_ids,
)

SCHEMA_VERSION = 15
PROJECT_SCHEMA_VERSION = 2
CONTROL_PLANE_UPGRADE_VERSION = 5
LEGACY_VERIFICATION_GATE_POLICY = "strict-reconciliation-prewrite-v1"
VERIFICATION_GATE_POLICY = "historical-stale-completion-v1"
INTAKE_SCHEMA_VERSION = 1
PROJECT_CONTEXT_SCHEMA_VERSION = 1
OUTCOME_SCHEMA_VERSION = 1
CAPABILITY_SCHEMA_VERSION = 1
ACTIVITY_SCHEMA_VERSION = 1
VIEW_FOCUS_SCHEMA_VERSION = 1
RUNTIME_DIAGNOSTICS_SCHEMA_VERSION = 1
CONTINUITY_SCHEMA_VERSION = 8
DIAGNOSTIC_SCHEMA_VERSION = 1
IMPACT_RECEIPT_SCHEMA_VERSION = 2
WORKSPACE_POLICY_SCHEMA_VERSION = 1
PRODUCT_REVIEW_SCHEMA_VERSION = 1
PRODUCT_REVIEW_TEST_STATUSES = {"ready", "blocked", "not_applicable"}
E2E_EVIDENCE_SCHEMA = "auto-dev/e2e-evidence/v1"
E2E_RESULT_STATUSES = {"passed", "partial", "blocked"}
RELEASE_EVIDENCE_SCHEMA = "auto-dev/release-evidence/v1"
RELEASE_RESULT_STATUSES = {"succeeded", "partial", "rolled_back", "blocked"}
RELEASE_CHECK_STATUSES = {"passed", "failed", "blocked"}
RELEASE_USER_FLOW_STATUSES = RELEASE_CHECK_STATUSES | {"not_applicable"}
RELEASE_ROLLBACK_STATUSES = {"ready", "executed", "not_ready", "not_applicable"}
PERFORMANCE_EVIDENCE_SCHEMA = "auto-dev/performance-evidence/v1"
PERFORMANCE_PHASES = {"baseline", "comparison"}
PERFORMANCE_DIRECTIONS = {"lower", "higher"}
MAX_EVIDENCE_FILE_BYTES = 1024 * 1024
CONTINUITY_NODE_STATUSES = {"planned", "active", "blocked", "done", "superseded"}
CONTINUITY_GAP_OWNERS = {"agent", "user", "external"}
CONTINUITY_DURABILITY_LEVELS = {"local", "portable", "shared"}
CONTINUITY_NODE_KINDS = {"delivery", "verification", "release"}
PLAN_STRATEGIES = {"legacy", "rolling_graph"}
CONTINUITY_NODE_ROLES = {"milestone", "work_packet", "integration"}
WORKER_SCHEMA_VERSION = 2
WORKER_STATUSES = {
    "prepared", "dispatch_required", "running", "captured", "awaiting_main",
    "applied", "finalized", "dispatch_blocked", "failed", "conflicted",
    "blocked", "cleaned",
}
MILESTONE_COMPILATION_STATUSES = {
    "thin", "compiled", "integration_ready", "integrated", "accepted",
    "recompile_required", "blocked",
}
MILESTONE_INTEGRATION_STATUSES = {
    "not_ready", "ready", "integrating", "integrated", "conflicted", "blocked",
}
PACKET_EXECUTION_PROFILES = {"bounded", "governed"}
PACKET_REVIEW_POLICIES = {"proof_only", "quick", "strong", "full"}
PACKET_MERGE_MODES = {"accumulated_workspace", "worktree_merge_queue"}
PACKET_CONFLICT_OWNERS = {"main", "integrator", "user"}
EXECUTION_TOPOLOGIES = {"single_agent", "multi_agent"}
EXECUTION_LANES = {"main_session", "single_worker", "multi_worker"}
EXECUTION_DECISION_STATUSES = {"pending", "selected", "awaiting_main", "complete", "stale"}
EXECUTION_BOUNDARIES = {"before_integration", "milestone_end"}
MILESTONE_REVIEW_RESULTS = {
    "accepted", "packet_rework_required", "milestone_recompile_required",
    "roadmap_revision_required", "blocked",
}
ROLLING_RELATION_KINDS = {
    "hard_dependency", "write_conflict", "contract_dependency",
    "shared_blast_radius", "revalidation", "integration",
    "resource_conflict", "uncertain",
}
VERIFICATION_GATES = {"blocking", "advisory"}
ACTION_EVIDENCE_CLASSIFICATIONS = {"partial", "failed", "rejected"}
PROOF_FAILURE_CLASSIFICATIONS = {
    "product", "test_asset", "environment", "dependency", "flaky",
    "timeout", "permission", "unknown",
}
DIAGNOSTIC_STATUSES = {
    "reproducing", "investigating", "resolved", "recovering",
    "awaiting_confirmation", "closed", "blocked",
}
DIAGNOSTIC_CASE_SEARCH_STATUSES = {"not_run", "match", "miss", "unavailable"}
DIAGNOSTIC_REPRODUCTION_GATES = {
    "not_ready", "ready_red", "ready_flaky", "ready_green_no_defect", "unavailable",
}
DIAGNOSTIC_HYPOTHESIS_STATUSES = {
    "pending", "rejected", "confirmed", "inconclusive", "superseded",
}
DIAGNOSTIC_VERDICTS = {"rejected", "confirmed", "inconclusive"}
DIAGNOSTIC_RESOLUTIONS = {
    "root_cause_confirmed", "no_defect_observed", "inconclusive", "blocked",
}
DIAGNOSTIC_RECOVERY_STATUSES = {
    "unverified", "verified", "failed", "awaiting_confirmation", "not_applicable",
}
DIAGNOSTIC_PROBE_CLEANUP = {"pending", "complete", "not_applicable"}
TERMINAL_TASK_STATUSES = {"passed", "failed", "blocked", "abandoned", "budget_exhausted", "superseded"}
DISPLAY_CODE_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:\.[0-9]+)*")
DISPLAY_CODE_PREFIX_RE = re.compile(
    r"^\s*(?P<code>[A-Za-z][A-Za-z0-9]*(?:\.[0-9]+)*)\s*:\s*(?P<label>.*)$"
)
MAJOR_MILESTONE_CODE_RE = re.compile(r"M(?P<number>[0-9]+)", re.IGNORECASE)
FRACTIONAL_MILESTONE_CODE_RE = re.compile(r"M[0-9]+(?:\.[0-9]+)+", re.IGNORECASE)
SENSITIVE_TEXT = re.compile(
    r"(?i)(authorization|bearer\s+[a-z0-9._-]+|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)"
)
RUNTIME_DIAGNOSTIC_FIELDS = {
    "timestamp",
    "level",
    "component",
    "event",
    "outcome",
    "correlation_id",
    "error",
}
CAPABILITIES = {
    "architecture",
    "data-contract",
    "debug-observability",
    "gui",
    "release",
    "parallel-work",
    "compliance",
}
DEFAULT_PROTECTED_BRANCHES = ("main", "master", "production", "release/*")
WORKSPACE_POLICY_RULE_KINDS = ("forbidden_paths", "approval_paths", "sensitive_paths")
WORKSPACE_POLICY_ID_RE = re.compile(r"[a-z][a-z0-9_-]{0,79}")
WORKSPACE_CONTROL_METADATA_ROOTS = frozenset({
    ".auto-dev", ".autodev", ".codegraph", ".conductor",
})
WORKSPACE_SENSITIVE_DIRECTORY_NAMES = frozenset({"credentials", "secrets"})
WORKSPACE_SENSITIVE_FILE_NAMES = frozenset({
    ".env", ".env.local", ".env.production", "credentials", "credentials.json",
    "secrets", "secrets.json", "token", "token.json",
})
SYSTEM_WORKSPACE_POLICY_RULES = {
    "forbidden_paths": (
        {"id": "system-git", "pattern": ".git", "reason": "Git control data is system-owned"},
        {"id": "system-git-tree", "pattern": ".git/**", "reason": "Git control data is system-owned"},
        {"id": "system-auto-dev", "pattern": ".auto-dev", "reason": "Auto Dev state is CLI-owned"},
        {"id": "system-auto-dev-tree", "pattern": ".auto-dev/**", "reason": "Auto Dev state is CLI-owned"},
    ),
    "approval_paths": (),
    "sensitive_paths": (
        {"id": "system-env", "pattern": ".env", "reason": "Environment files may contain credentials"},
        {"id": "system-env-root", "pattern": ".env.*", "reason": "Environment files may contain credentials"},
        {"id": "system-env-tree", "pattern": "**/.env", "reason": "Environment files may contain credentials"},
        {"id": "system-env-tree-variants", "pattern": "**/.env.*", "reason": "Environment files may contain credentials"},
        {"id": "system-credentials", "pattern": "**/credentials/**", "reason": "Credential stores require protected handling"},
        {"id": "system-secrets", "pattern": "**/secrets/**", "reason": "Secret stores require protected handling"},
        {"id": "system-private-key", "pattern": "**/*.key", "reason": "Private keys require protected handling"},
        {"id": "system-pem", "pattern": "**/*.pem", "reason": "Private keys require protected handling"},
        {"id": "system-p12", "pattern": "**/*.p12", "reason": "Credential bundles require protected handling"},
        {"id": "system-pfx", "pattern": "**/*.pfx", "reason": "Credential bundles require protected handling"},
    ),
}
DEFAULT_TEAM_BUDGETS = {
    "implementation_repair": 2,
    "same_class_findings": 2,
    "review_passes": 2,
    "gui_retries": 3,
    "parallel_agents": 1,
}
DEFAULT_TEAM_STOP_CONDITIONS = [
    "出现新的产品行为，需要进行需求差异确认",
    "同类失败连续出现两次",
    "实现修复预算已耗尽",
]
DEFAULT_PROJECT_CONTEXT_TITLE = "仓库交付上下文"
DEFAULT_PROJECT_AUTHORITY_BOUNDARY = "尚未建立"
DEFAULT_PROJECT_DELIVERY_BOUNDARY = "当前仓库与当前分支的交付范围"
DEFAULT_PROJECT_CONTEXT_BOUNDARY = "由 Auto Dev 逐步发现的仓库内工作"
DEFAULT_UNLINKED_OUTCOME_TITLE = "未归属工作收件箱"
DEFAULT_UNLINKED_OUTCOME_STATEMENT = "尚未关联到产品结果的有界工作"
OUTCOME_KINDS = {
    "behavior_change",
    "defect_resolution",
    "measured_improvement",
    "decision",
    "knowledge_gain",
    "document",
}
INTAKE_DEPTHS = {"clear", "clarify", "deep", "project-discovery"}
INTAKE_DECISION_STATUSES = {"pending", "accepted", "deferred", "excluded"}
WORKSPACE_STORAGE_MODES = {"git", "local"}
PROJECT_CONTEXT_LIFECYCLES = {
    "provisional",
    "active",
    "completed",
    "archived",
    "emerging",
    "maintained",
    "sunset",
}
PROJECT_CONTEXT_COVERAGE = {"partial", "bounded", "broad"}
OUTCOME_STATUSES = {"proposed", "ready", "active", "blocked", "completed", "superseded", "archived"}
OUTCOME_RELATIONS = {"contains", "depends_on", "enables", "contributes_to", "verifies", "supersedes"}
CAPABILITY_STATUSES = {"emerging", "active", "maintained", "sunset"}
CONTROL_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]{1,95}")
SESSION_KEY_RE = re.compile(r"[a-f0-9]{12,64}")


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run(command: list[str], cwd: pathlib.Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    evaluation = current_evaluation(cwd)
    if evaluation is not None:
        return evaluation.run(
            command,
            cwd,
            check,
            lambda: subprocess.run(
                command,
                cwd=cwd,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ),
        )
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def git(repo: pathlib.Path, *args: str, check: bool = True) -> str:
    return run(["git", *args], repo, check).stdout.strip()


def git_root(value: pathlib.Path) -> pathlib.Path | None:
    result = run(["git", "rev-parse", "--show-toplevel"], value, False)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return pathlib.Path(result.stdout.strip()).resolve()


def local_project_root(candidate: pathlib.Path) -> pathlib.Path | None:
    for root in (candidate, *candidate.parents):
        project_path = root / ".auto-dev" / "project.json"
        if not project_path.is_file():
            continue
        try:
            project = read_json(project_path)
        except (OSError, json.JSONDecodeError):
            continue
        if project.get("storage_mode") == "local":
            return root
    return None


def resolve_repo(value: str) -> pathlib.Path:
    candidate = pathlib.Path(value).expanduser().resolve()
    root = git_root(candidate)
    if root is not None:
        return root
    local_root = local_project_root(candidate)
    if local_root is not None:
        return local_root
    raise ValueError(f"not inside a managed Git or local workspace: {candidate}")


def workspace_storage_mode(repo: pathlib.Path) -> str:
    return "git" if git_root(repo) == repo.resolve() else "local"


def git_head(repo: pathlib.Path) -> str | None:
    """Return a verified Git HEAD, keeping unborn repositories headless."""
    if workspace_storage_mode(repo) != "git":
        return None
    result = run(["git", "rev-parse", "--verify", "HEAD"], repo, False)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip()


def local_workspace_fingerprint(repo: pathlib.Path) -> str:
    stat = repo.stat()
    identity = f"local\0{repo.resolve()}\0{stat.st_dev}\0{stat.st_ino}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def paths(repo: pathlib.Path) -> dict[str, pathlib.Path]:
    root = repo / ".auto-dev"
    return {
        "root": root,
        "active": root / "active.json",
        "project": root / "project.json",
        "projects": root / "projects",
        "tasks": root / "tasks",
        "activities": root / "activities",
        "intake_gates": root / "intake-gates",
        "view_focus": root / "view-focus",
        "history": root / "history.jsonl",
        "runs": root / "runs",
        "snapshots": root / "snapshots",
        "repair_backups": root / "repair-backups",
        "repair_history": root / "repair-history.jsonl",
        "upgrade_backups": root / "legacy-upgrade-backups",
        "upgrade_history": root / "legacy-upgrade-history.jsonl",
        "config": root / "config.json",
        "runtime_diagnostics": root / "runtime-diagnostics.json",
        "project_memory": root / "project-memory.json",
        "environment_projection": root / "path.md",
        "domain_projection": root / "project-domain.md",
        "dependency_lease": root / "dependency-lease.json",
        "last_transition": root / "last-transition.json",
        "transition_lock": root / "transition",
        "workers": root / "workers",
    }


def ensure_root(repo: pathlib.Path) -> dict[str, pathlib.Path]:
    if auto_dev_plugin_root(repo) == repo.resolve():
        raise ValueError(
            "Auto Dev will not create or mutate a control plane inside its own Plugin source; "
            "use a neutral workspace or an explicit test fixture"
        )
    result = paths(repo)
    for key in ("root", "runs", "snapshots", "tasks", "projects", "activities", "intake_gates", "view_focus", "workers"):
        result[key].mkdir(parents=True, exist_ok=True)
    if workspace_storage_mode(repo) != "git":
        return result
    exclude_value = git(repo, "rev-parse", "--git-path", "info/exclude")
    exclude_path = pathlib.Path(exclude_value)
    if not exclude_path.is_absolute():
        exclude_path = repo / exclude_path
    existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    if ".auto-dev/" not in {line.strip() for line in existing.splitlines()}:
        with exclude_path.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write("\n.auto-dev/\n")
    return result


def write_json(path: pathlib.Path, payload: dict[str, Any], *, backup: bool = False) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temporary.write_bytes(data)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(".bak"))
    temporary.replace(path)
    try:
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        # Some filesystems do not allow directory fsync; the atomic replace still holds.
        pass


def write_text(path: pathlib.Path, value: str, *, backup: bool = False) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(value.encode("utf-8"))
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    temporary.replace(path)
    try:
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        # Some filesystems do not allow directory fsync; the atomic replace still holds.
        pass


def read_json(path: pathlib.Path) -> dict[str, Any]:
    evaluation = current_evaluation()
    if evaluation is not None:
        return evaluation.read_json(path)
    return json.loads(path.read_text(encoding="utf-8"))


def branch_context_key(branch: str | None, head: str | None = None) -> str:
    return branch or f"@detached:{head or 'unborn'}"


def project_fingerprint(repo: pathlib.Path) -> str:
    if workspace_storage_mode(repo) == "local":
        return local_workspace_fingerprint(repo)
    common = git(repo, "rev-parse", "--git-common-dir", check=False)
    common_path = pathlib.Path(common) if common else repo / ".git"
    if not common_path.is_absolute():
        common_path = (repo / common_path).resolve()
    return hashlib.sha256(str(common_path).encode("utf-8")).hexdigest()[:16]


def blank_project(repo: pathlib.Path) -> dict[str, Any]:
    fingerprint = project_fingerprint(repo)
    return {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "state_revision": 0,
        "project_id": f"AUTO-DEV-PROJECT-{fingerprint.upper()}",
        "repo_fingerprint": fingerprint,
        "storage_mode": workspace_storage_mode(repo),
        "created_at": now(),
        "updated_at": now(),
        "branches": {},
        "contexts": {},
        "default_context_id": None,
        "control_plane_upgrade_version": CONTROL_PLANE_UPGRADE_VERSION,
        "verification_gate_policy": VERIFICATION_GATE_POLICY,
    }


def load_project(state: dict[str, pathlib.Path], repo: pathlib.Path) -> dict[str, Any] | None:
    if not state["project"].exists():
        return None
    project = read_json(state["project"])
    schema_version = project.get("schema_version", 1)
    if not isinstance(schema_version, int) or schema_version < 1 or schema_version > PROJECT_SCHEMA_VERSION:
        raise ValueError("unsupported project control schema version")
    branches = project.get("branches")
    if not isinstance(branches, dict) or not all(isinstance(value, dict) for value in branches.values()):
        raise ValueError("project branches must be an object of branch contexts")
    storage_mode = project.setdefault("storage_mode", "git")
    if storage_mode not in WORKSPACE_STORAGE_MODES:
        raise ValueError("project storage mode is unsupported")
    if project.get("repo_fingerprint") != project_fingerprint(repo):
        if storage_mode == "local" and workspace_storage_mode(repo) == "git":
            raise ValueError("local project control requires an explicit migration to Git")
        raise ValueError("project control belongs to a different workspace")
    project.setdefault("state_revision", 0)
    project.setdefault("contexts", {})
    if not isinstance(project["contexts"], dict):
        raise ValueError("project contexts must be an object")
    project.setdefault("default_context_id", None)
    upgrade_version = project.setdefault("control_plane_upgrade_version", 0)
    project.setdefault(
        "verification_gate_policy",
        (
            VERIFICATION_GATE_POLICY
            if isinstance(upgrade_version, int) and upgrade_version >= 3
            else LEGACY_VERIFICATION_GATE_POLICY
        ),
    )
    return project


def require_control_id(label: str, value: str) -> str:
    normalized = value.strip()
    if not CONTROL_ID_RE.fullmatch(normalized):
        raise ValueError(f"{label} contains unsupported characters")
    return normalized


def require_session_key(value: str) -> str:
    normalized = value.strip()
    if not SESSION_KEY_RE.fullmatch(normalized):
        raise ValueError("session key is malformed")
    return normalized


def generated_control_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S-%f')}"


def context_directory(state: dict[str, pathlib.Path], context_id: str) -> pathlib.Path:
    return state["projects"] / require_control_id("project context id", context_id)


def context_frame_path(state: dict[str, pathlib.Path], context_id: str) -> pathlib.Path:
    return context_directory(state, context_id) / "frame.json"


def context_outcomes_directory(state: dict[str, pathlib.Path], context_id: str) -> pathlib.Path:
    return context_directory(state, context_id) / "outcomes"


def context_capabilities_directory(state: dict[str, pathlib.Path], context_id: str) -> pathlib.Path:
    return context_directory(state, context_id) / "capabilities"


def context_intakes_directory(state: dict[str, pathlib.Path], context_id: str) -> pathlib.Path:
    return context_directory(state, context_id) / "intakes"


def outcome_record_path(state: dict[str, pathlib.Path], context_id: str, outcome_id: str) -> pathlib.Path:
    return context_outcomes_directory(state, context_id) / f"{require_control_id('outcome id', outcome_id)}.json"


def capability_record_path(state: dict[str, pathlib.Path], context_id: str, capability_id: str) -> pathlib.Path:
    return context_capabilities_directory(state, context_id) / f"{require_control_id('capability id', capability_id)}.json"


def intake_record_path(state: dict[str, pathlib.Path], context_id: str, intake_id: str) -> pathlib.Path:
    return context_intakes_directory(state, context_id) / f"{require_control_id('intake id', intake_id)}.json"


def intake_gate_path(state: dict[str, pathlib.Path], session_key: str) -> pathlib.Path:
    session_key = require_session_key(session_key)
    return state["intake_gates"] / f"{session_key}.json"


def view_focus_path(state: dict[str, pathlib.Path], session_key: str) -> pathlib.Path:
    session_key = require_session_key(session_key)
    return state["view_focus"] / f"{session_key}.json"


def default_context_id(project: dict[str, Any]) -> str:
    fingerprint = str(project.get("repo_fingerprint") or "local").upper()
    return f"CTX-{fingerprint}"


def default_unlinked_outcome_id(context_id: str) -> str:
    return f"OUTCOME-UNLINKED-{context_id.removeprefix('CTX-')}"


def context_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry.get("id"),
        "title": entry.get("title"),
        "lifecycle": entry.get("lifecycle"),
        "coverage": entry.get("coverage"),
        "unlinked_outcome_id": entry.get("unlinked_outcome_id"),
        "updated_at": entry.get("updated_at"),
    }


def ensure_context_storage(state: dict[str, pathlib.Path], context_id: str) -> None:
    for directory in (
        context_directory(state, context_id),
        context_outcomes_directory(state, context_id),
        context_capabilities_directory(state, context_id),
        context_intakes_directory(state, context_id),
    ):
        directory.mkdir(parents=True, exist_ok=True)


def write_context_frame(state: dict[str, pathlib.Path], frame: dict[str, Any]) -> None:
    context_id = require_control_id("project context id", str(frame.get("id") or ""))
    ensure_context_storage(state, context_id)
    write_json(context_frame_path(state, context_id), frame, backup=True)


def system_unlinked_outcome(
    context_id: str,
    outcome_id: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": OUTCOME_SCHEMA_VERSION,
        "id": outcome_id,
        "project_context_id": context_id,
        "title": DEFAULT_UNLINKED_OUTCOME_TITLE,
        "statement": DEFAULT_UNLINKED_OUTCOME_STATEMENT,
        "status": "active",
        "acceptance": [],
        "parent_id": None,
        "relations": [],
        "intake_id": None,
        "system_generated": True,
        "state_revision": 1,
        "created_at": created_at,
        "updated_at": created_at,
    }


def default_project_context_records(
    project: dict[str, Any],
    created_at: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build the standard provisional hierarchy without writing control state."""
    context_id = default_context_id(project)
    entry = {
        "id": context_id,
        "title": DEFAULT_PROJECT_CONTEXT_TITLE,
        "lifecycle": "provisional",
        "coverage": "partial",
        "unlinked_outcome_id": default_unlinked_outcome_id(context_id),
        "created_at": created_at,
        "updated_at": created_at,
    }
    frame = {
        "schema_version": PROJECT_CONTEXT_SCHEMA_VERSION,
        "id": context_id,
        "title": entry["title"],
        "lifecycle": entry["lifecycle"],
        "coverage": entry["coverage"],
        "authority_boundary": DEFAULT_PROJECT_AUTHORITY_BOUNDARY,
        "delivery_boundary": DEFAULT_PROJECT_DELIVERY_BOUNDARY,
        "context_boundary": DEFAULT_PROJECT_CONTEXT_BOUNDARY,
        "mission": None,
        "external_context": [],
        "evidence_sources": [],
        "created_at": created_at,
        "updated_at": created_at,
    }
    outcome = system_unlinked_outcome(context_id, entry["unlinked_outcome_id"], created_at)
    return entry, frame, outcome


def read_context_frame(state: dict[str, pathlib.Path], context_id: str) -> dict[str, Any]:
    path = context_frame_path(state, context_id)
    if not path.exists():
        raise ValueError(f"project context frame does not exist: {context_id}")
    frame = read_json(path)
    if not isinstance(frame, dict) or frame.get("id") != context_id:
        raise ValueError(f"project context frame is malformed: {context_id}")
    return frame


def promote_contract_to_frame(
    state: dict[str, pathlib.Path], context_id: str, contract: dict[str, Any] | None,
) -> None:
    """Persist the confirmed effective contract at the project-context boundary."""
    if not isinstance(contract, dict):
        return
    frame = read_context_frame(state, context_id)
    frame["contract"] = copy.deepcopy(contract)
    frame["contract_hash"] = contract.get("hash")
    frame["contract_revision"] = contract.get("revision", 1)
    frame["updated_at"] = now()
    write_context_frame(state, frame)


def ensure_default_project_context(
    state: dict[str, pathlib.Path],
    project: dict[str, Any],
) -> tuple[str, bool]:
    """Create the bounded provisional context only from an explicit control mutation."""
    current = project.get("default_context_id")
    if isinstance(current, str) and current in project.get("contexts", {}):
        return current, False
    created_at = now()
    entry, frame, outcome = default_project_context_records(project, created_at)
    context_id = entry["id"]
    outcome_id = entry["unlinked_outcome_id"]
    project["contexts"][context_id] = entry
    project["default_context_id"] = context_id
    project["schema_version"] = PROJECT_SCHEMA_VERSION
    write_context_frame(state, frame)
    write_json(outcome_record_path(state, context_id, outcome_id), outcome)
    return context_id, True


def resolve_project_context(
    state: dict[str, pathlib.Path],
    project: dict[str, Any],
    context_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected_id = context_id or project.get("default_context_id")
    if not isinstance(selected_id, str) or selected_id not in project.get("contexts", {}):
        raise ValueError("a managed project context must be selected or adopted first")
    entry = project["contexts"][selected_id]
    if not isinstance(entry, dict):
        raise ValueError(f"project context is malformed: {selected_id}")
    return entry, read_context_frame(state, selected_id)


def write_project_control(state: dict[str, pathlib.Path], project: dict[str, Any]) -> int:
    project["schema_version"] = PROJECT_SCHEMA_VERSION
    project["state_revision"] = int(project.get("state_revision", 0)) + 1
    project["updated_at"] = now()
    write_json(state["project"], project, backup=True)
    return int(project["state_revision"])


def require_project_revision(project: dict[str, Any], value: int) -> None:
    actual = int(project.get("state_revision", 0))
    if value != actual:
        raise ValueError(f"project revision conflict: expected {actual}, received {value}")
