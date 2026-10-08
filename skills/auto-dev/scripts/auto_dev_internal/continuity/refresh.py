"""Read-only refresh diagnostics for the Auto Dev runtime and project."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows does not provide fcntl.
    fcntl = None  # type: ignore[assignment]


FINAL_STATUSES = {
    "ready",
    "work_blocked",
    "fresh_session_required",
    "confirmation_required",
    "runtime_unavailable",
}
AGENT_FOCUS_VIEW = "agent-focus"


@contextlib.contextmanager
def _refresh_singleflight(repo: pathlib.Path):
    """Serialize refresh evaluations for one repository without changing state semantics."""
    if fcntl is None:
        yield
        return
    configured = os.environ.get("PLUGIN_DATA")
    root = pathlib.Path(configured).expanduser() if configured else pathlib.Path(tempfile.gettempdir()) / "auto-dev"
    key = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:24]
    lock_path = root / "refresh-locks" / f"{key}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _package_root() -> pathlib.Path:
    current = pathlib.Path(__file__).resolve()
    for candidate in (current, *current.parents):
        manifest = candidate / ".codex-plugin" / "plugin.json"
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and str(value.get("name", "")).casefold() == "auto-dev":
            return candidate
    return current.parents[5]


def _path_value(value: str | None) -> pathlib.Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return pathlib.Path(value).expanduser().resolve()
    except OSError:
        return None


def _read_object(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _bundle_snapshot(root: pathlib.Path | None) -> dict[str, Any]:
    required = (
        ".codex-plugin/plugin.json",
        "hooks/hooks.json",
        "scripts/runtime_bootstrap.py",
        "scripts/hook_dispatch.py",
        "scripts/hook_session_state.py",
        "skills/auto-dev/SKILL.md",
        "skills/auto-dev/scripts/auto_dev.py",
        "skills/auto-dev/scripts/auto_dev_internal/task/milestones.py",
        "skills/auto-dev/scripts/auto_dev_internal/task/execution.py",
        "skills/auto-dev/scripts/auto_dev_internal/task/plan.py",
        "skills/auto-dev/scripts/auto_dev_internal/task/workers.py",
        "skills/refresh/SKILL.md",
    )
    if root is None:
        return {"status": "unavailable", "missing": list(required), "version": None}
    manifest = _read_object(root / ".codex-plugin" / "plugin.json")
    missing = [relative for relative in required if not (root / relative).is_file()]
    valid_manifest = bool(
        isinstance(manifest, dict)
        and str(manifest.get("name", "")).casefold() == "auto-dev"
        and isinstance(manifest.get("version"), str)
    )
    if not valid_manifest:
        missing.insert(0, ".codex-plugin/plugin.json(name/version)")
    return {
        "status": "complete" if not missing else "incomplete",
        "root": str(root),
        "version": manifest.get("version") if isinstance(manifest, dict) else None,
        "missing": sorted(set(missing)),
        "cli_schema_version": _cli_schema_version(root),
    }


def _cli_schema_version(root: pathlib.Path | None) -> int | None:
    if root is None:
        return None
    try:
        text = (root / "skills" / "auto-dev" / "scripts" / "auto_dev.py").read_text(
            encoding="utf-8"
        )
    except OSError:
        return None
    match = re.search(r"^CLI_SCHEMA_VERSION\s*=\s*([0-9]+)\s*$", text, re.MULTILINE)
    return int(match.group(1)) if match else None


def _hook_snapshot(root: pathlib.Path | None) -> dict[str, Any]:
    if root is None:
        return {"status": "unavailable", "entrypoint": None, "config": None}
    path = root / "hooks" / "hooks.json"
    payload = _read_object(path)
    if payload is None:
        return {"status": "unavailable", "entrypoint": None, "config": str(path)}
    commands: list[str] = []
    for entries in (payload.get("hooks") or {}).values():
        if not isinstance(entries, list):
            continue
        for group in entries:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks", []):
                if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                    commands.append(hook["command"])
    if any("runtime_bootstrap.py" in command for command in commands):
        entrypoint = "runtime_bootstrap"
    elif any("hook_dispatch.py" in command for command in commands):
        entrypoint = "hook_dispatch"
    else:
        entrypoint = "unknown"
    return {
        "status": "configured" if entrypoint != "unknown" else "invalid",
        "entrypoint": entrypoint,
        "config": str(path),
        "command_count": len(commands),
    }


def _runtime_snapshot() -> dict[str, Any]:
    source_root = _package_root()
    source = _bundle_snapshot(source_root)
    configured_root = _path_value(os.environ.get("PLUGIN_ROOT"))
    configured = _bundle_snapshot(configured_root) if configured_root else None
    source_version = source.get("version")
    runtime_version = os.environ.get("AUTO_DEV_RUNTIME_VERSION")
    observed_cli_schema = (
        int(os.environ["AUTO_DEV_CLI_SCHEMA_VERSION"])
        if os.environ.get("AUTO_DEV_CLI_SCHEMA_VERSION", "").isdigit()
        else None
    )
    reasons: list[str] = []
    fresh_session = False
    if source.get("status") != "complete":
        runtime_status = "runtime_unavailable"
        reasons.append("source_bundle_incomplete")
    elif configured_root is not None and configured and configured.get("status") != "complete":
        runtime_status = "fresh_session_required"
        fresh_session = True
        reasons.append("configured_hook_bundle_incomplete")
    elif (
        configured_root is not None
        and configured
        and source_version
        and configured.get("version")
        and configured.get("version") != source_version
    ):
        runtime_status = "fresh_session_required"
        fresh_session = True
        reasons.append("configured_hook_bundle_is_older_than_source")
    elif (
        configured_root is not None
        and configured
        and source.get("cli_schema_version") is not None
        and configured.get("cli_schema_version") is not None
        and configured.get("cli_schema_version") != source.get("cli_schema_version")
    ):
        runtime_status = "fresh_session_required"
        fresh_session = True
        reasons.append("configured_hook_cli_schema_differs_from_source")
    elif runtime_version and source_version and runtime_version != source_version:
        runtime_status = "fresh_session_required"
        fresh_session = True
        reasons.append("current_session_runtime_version_differs")
    elif (
        observed_cli_schema is not None
        and source.get("cli_schema_version") is not None
        and observed_cli_schema != source.get("cli_schema_version")
    ):
        runtime_status = "fresh_session_required"
        fresh_session = True
        reasons.append("current_session_cli_schema_differs_from_source")
    else:
        runtime_status = "package_ready"

    return {
        "status": runtime_status,
        "source": source,
        "configured": configured,
        "configured_root": str(configured_root) if configured_root else None,
        "hook": _hook_snapshot(configured_root or source_root),
        "runtime_version": runtime_version,
        "session_observation": (
            "observed"
            if runtime_version or configured_root or observed_cli_schema is not None
            else "not_observable"
        ),
        "fresh_session_required": fresh_session,
        "reasons": reasons,
        "cli_schema": {
            "source": source.get("cli_schema_version"),
            "configured": configured.get("cli_schema_version") if configured else None,
            "runtime_observed": (
                observed_cli_schema
            ),
        },
    }


def _progress_snapshot(repo: pathlib.Path) -> dict[str, Any]:
    scripts_root = _package_root() / "scripts"
    if str(scripts_root) not in sys.path:
        sys.path.insert(0, str(scripts_root))
    try:
        import hook_dispatch

        cli = _package_root() / "skills" / "auto-dev" / "scripts" / "auto_dev.py"
        url = hook_dispatch.ensure_progress_server(repo, cli=cli)
        record = hook_dispatch.progress_record_path(repo)
    except (ImportError, OSError, ValueError) as error:
        return {"status": "unavailable", "url": None, "reason": str(error)}
    if not url:
        return {
            "status": "unavailable",
            "url": None,
            "record": str(record),
            "reason": "progress_server_unavailable",
        }
    return {"status": "healthy", "url": url, "record": str(record)}


def _lease_snapshot(control, repo: pathlib.Path, status: dict[str, Any], session_id: str | None) -> dict[str, Any]:
    if not session_id:
        return {"status": "not_observable"}
    scripts_root = _package_root() / "scripts"
    if str(scripts_root) not in sys.path:
        sys.path.insert(0, str(scripts_root))
    try:
        from hook_session_state import writer_lease_status

        branch_key = str(status.get("context_key") or control.branch_context_key(
            control.current_branch(repo), control.git_head(repo)
        ))
        return writer_lease_status(repo, {"session_id": session_id}, branch_key=branch_key)
    except (ImportError, OSError, ValueError):
        return {"status": "unavailable"}


def _upgrade_snapshot(control, repo: pathlib.Path, state: dict[str, pathlib.Path], status: dict[str, Any]) -> dict[str, Any]:
    upgrade = ((status.get("hierarchy") or {}).get("control_plane_upgrade") or {})
    if not isinstance(upgrade, dict):
        return {"status": "not_observable"}
    upgrade_status = str(upgrade.get("status") or "unknown")
    result: dict[str, Any] = dict(upgrade)
    result["status"] = upgrade_status
    if upgrade_status in {"current", "not_applicable", "unknown"}:
        return result
    try:
        inspection = control.legacy_upgrade_inspection_payload(
            repo, state, include_legacy_material=False
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        result["inspection_error"] = str(error)
        return result
    result["inspection"] = inspection
    result["status"] = inspection.get("status", upgrade_status)
    return result


def _project_result(
    status: dict[str, Any], upgrade: dict[str, Any], rolling: dict[str, Any] | None = None
) -> tuple[str, str]:
    task_status = status.get("status")
    continuity = status.get("continuity_status")
    blockers = status.get("strict_blockers") or []
    if task_status in {"idle", "selection_required"} or not status.get("id"):
        return "confirmation_required", "select or start the current Auto Dev task"
    if task_status == "review_ready" or "review_ready" in blockers:
        return "confirmation_required", "review and confirm the current task before continuing"
    if upgrade.get("status") in {"upgrade_available", "manual_decision_required", "blocked", "reverification_required"}:
        return "work_blocked", "run auto_dev.py legacy-upgrade inspect and follow its explicit migration or revalidation result"
    if upgrade.get("status") == "newer_than_cli":
        return "runtime_unavailable", "use a compatible Auto Dev package before continuing"
    rolling = rolling if isinstance(rolling, dict) else {}
    revalidation = rolling.get("policy_revalidation")
    decision = rolling.get("execution_decision")
    handoff = rolling.get("handoff")
    if isinstance(revalidation, dict) and revalidation.get("status") == "required":
        return "work_blocked", "revalidate or recompile the current compiled Milestone before continuing"
    if isinstance(decision, dict) and decision.get("status") == "pending":
        return "confirmation_required", "select main_session, single_worker, or multi_worker for the compiled Milestone"
    if isinstance(handoff, dict) and handoff.get("required"):
        return "ready", "Main session must take over Proof, Checkpoint, Integration, or Review at the recorded boundary"
    if task_status in {"paused", "blocked"} or blockers or continuity not in {"ready", "review_ready"}:
        next_action = str((status.get("continuity_summary") or {}).get("next_action") or "resolve the reported Auto Dev blocker")
        return "work_blocked", next_action
    return "ready", "continue current task"


def _packet_snapshot(node: dict[str, Any]) -> dict[str, Any]:
    """Expose the compiled packet contract without copying execution history."""
    return {
        "id": node.get("id"),
        "display_code": node.get("display_code"),
        "title": node.get("title"),
        "status": node.get("status"),
        "parent_id": node.get("parent_id"),
        "integration_wave": node.get("integration_wave"),
        "execution_profile": node.get("execution_profile", "bounded"),
        "required_capabilities": node.get("required_capabilities", []),
        "verification_policy": node.get("verification_policy", {}),
        "review_policy": node.get("review_policy", "proof_only"),
        "merge_policy": node.get("merge_policy", {}),
        "model_profile": node.get("model_profile"),
        "result_ref": node.get("result_ref"),
    }


def _worker_snapshot(state: dict[str, pathlib.Path], *, packet_ids: set[str]) -> dict[str, Any]:
    """Read worker lifecycle records; absence means dispatch has not started."""
    workers_root = state.get("workers")
    if not isinstance(workers_root, pathlib.Path) or not workers_root.exists():
        return {
            "status": "not_started",
            "count": 0,
            "by_status": {},
            "active": [],
            "out_of_scope": [],
        }
    records: list[dict[str, Any]] = []
    unreadable = 0
    for path in sorted(workers_root.glob("*.json")):
        worker = _read_object(path)
        if not isinstance(worker, dict):
            unreadable += 1
            continue
        if worker.get("packet_id") not in packet_ids:
            continue
        records.append(worker)
    by_status: dict[str, int] = {}
    active: list[dict[str, Any]] = []
    out_of_scope: list[str] = []
    for worker in records:
        worker_status = str(worker.get("status") or "unknown")
        by_status[worker_status] = by_status.get(worker_status, 0) + 1
        if worker_status in {"prepared", "dispatch_required", "running", "captured", "awaiting_main", "applied", "conflicted", "blocked", "dispatch_blocked", "failed"}:
            changed_paths = worker.get("changed_paths", [])
            if not isinstance(changed_paths, list):
                changed_paths = []
            active.append({
                "id": worker.get("id"),
                "packet_id": worker.get("packet_id"),
                "status": worker_status,
                "launch_status": worker.get("launch_status"),
                "worker_profile": worker.get("worker_profile"),
                "executor_ref": worker.get("executor_ref"),
                "changed_paths": changed_paths,
                "blocked_reason": worker.get("blocked_reason"),
                "conflict": worker.get("conflict"),
            })
        if worker_status == "blocked" and worker.get("blocked_reason") == "out_of_scope_changes":
            outside_scope = worker.get("outside_scope", [])
            if isinstance(outside_scope, list):
                out_of_scope.extend(str(path) for path in outside_scope)
    return {
        "status": "unavailable" if unreadable else ("ready" if records else "not_started"),
        "count": len(records),
        "by_status": by_status,
        "active": active,
        "out_of_scope": sorted(set(out_of_scope)),
        "unreadable_records": unreadable,
    }


def _rolling_snapshot(
    control,
    repo: pathlib.Path,
    status: dict[str, Any],
    state: dict[str, pathlib.Path] | None = None,
) -> dict[str, Any]:
    continuity = status.get("continuity") if isinstance(status.get("continuity"), dict) else {}
    plan = continuity.get("plan") if isinstance(continuity.get("plan"), dict) else {}
    strategy = str(plan.get("strategy") or "legacy")
    state = state or control.paths(repo)
    if strategy != "rolling_graph":
        return {
            "capability": "available",
            "strategy": strategy,
            "roadmap": [],
            "ready_frontier": {},
            "compilation_focus": None,
            "execution_focus": continuity.get("current_node"),
            "integration": {"status": "not_applicable"},
            "exit_snapshots": {"count": 0, "latest": None},
            "compiler_inputs": {"status": "not_applicable"},
            "execution_decision": {"status": "not_applicable"},
            "policy_revalidation": {"status": "not_applicable"},
            "handoff": {"required": False, "owner": "main_session"},
            "packets": [],
            "workers": {"status": "not_applicable", "count": 0, "by_status": {}, "active": []},
        }
    nodes = [node for node in plan.get("nodes", []) if isinstance(node, dict)]
    milestones = [node for node in nodes if node.get("node_role") == "milestone"]
    roadmap = [
        {
            "id": node.get("id"),
            "display_code": node.get("display_code"),
            "title": node.get("title"),
            "depends_on": node.get("depends_on", []),
            "status": node.get("status"),
            "compilation_status": node.get("milestone_state", {}).get("compilation_status"),
            "integration_status": node.get("milestone_state", {}).get("integration_status"),
            "review_result": node.get("milestone_state", {}).get("review_result"),
            "exit_snapshot_id": node.get("milestone_state", {}).get("exit_snapshot_id"),
        }
        for node in milestones
    ]
    active_milestone = next(
        (
            node for node in milestones
            if node.get("id") == continuity.get("compilation_focus")
            or any(
                child.get("parent_id") == node.get("id")
                and child.get("id") == continuity.get("execution_focus")
                for child in nodes
            )
        ),
        None,
    )
    if active_milestone is None:
        active_milestone = next(
            (
                node for node in milestones
                if node.get("status") not in {"done", "superseded"}
                and node.get("milestone_state", {}).get("compilation_status")
                in {"compiled", "integration_ready", "integrated"}
            ),
            None,
        )
    active_milestone_state = (
        active_milestone.get("milestone_state", {})
        if isinstance(active_milestone, dict)
        else {}
    )
    compilation_policy = (
        active_milestone_state.get("compilation_policy", {})
        if isinstance(active_milestone_state.get("compilation_policy", {}), dict)
        else {}
    )
    active_milestone_id = active_milestone.get("id") if active_milestone else None
    packets = [
        node for node in nodes
        if node.get("node_role") == "work_packet"
        and (active_milestone_id is None or node.get("parent_id") == active_milestone_id)
    ]
    local_nodes = [
        node for node in nodes
        if active_milestone_id is not None and node.get("parent_id") == active_milestone_id
    ]
    packet_ids = {str(node.get("id")) for node in packets if node.get("id")}
    worker_state = _worker_snapshot(state, packet_ids=packet_ids)
    current_fingerprint = control.codegraph_index_fingerprint(repo)
    compilation_snapshot = (
        active_milestone.get("milestone_state", {}).get("compilation_snapshot", {})
        if isinstance(active_milestone, dict)
        else {}
    )
    compiled_fingerprint = compilation_snapshot.get("codegraph", {}).get("index_fingerprint")
    if not compilation_snapshot:
        compiler_status = "awaiting_compilation"
    elif compiled_fingerprint is None:
        compiler_status = "codegraph_unavailable_at_compilation"
    elif current_fingerprint == compiled_fingerprint:
        compiler_status = "fresh"
    else:
        compiler_status = "stale"
    snapshots = continuity.get("exit_snapshots", [])
    snapshots = snapshots if isinstance(snapshots, list) else []
    execution_decision = (
        active_milestone_state.get("execution_decision")
        if isinstance(active_milestone_state.get("execution_decision"), dict)
        else None
    )
    snapshot_contracts = compilation_snapshot.get("packet_contracts_sha256")
    decision_current = bool(
        execution_decision
        and execution_decision.get("compilation_revision")
        == active_milestone_state.get("compilation_revision")
        and execution_decision.get("packet_contracts_sha256") == snapshot_contracts
    )
    required_packet_fields = {
        "contract_sha256", "execution_base", "execution_profile",
        "verification_policy", "review_policy", "merge_policy",
    }
    incomplete_contracts = [
        {
            "node_id": node.get("id"),
            "missing": sorted(
                field for field in required_packet_fields
                if node.get(field) in (None, "")
            ),
        }
        for node in local_nodes
        if node.get("node_role") in {"work_packet", "integration"}
        and node.get("status") not in {"done", "superseded"}
        and any(node.get(field) in (None, "") for field in required_packet_fields)
    ]
    compiled_status = active_milestone_state.get("compilation_status")
    revalidation_reasons: list[str] = []
    if compiled_status in {"compiled", "integration_ready", "integrated"}:
        if execution_decision is None:
            revalidation_reasons.append("execution_decision_missing")
        elif not decision_current:
            revalidation_reasons.append("execution_decision_stale")
        if not snapshot_contracts:
            revalidation_reasons.append("packet_contract_digest_missing")
        if incomplete_contracts:
            revalidation_reasons.append("unfinished_packet_contract_incomplete")
    policy_revalidation = {
        "status": "required" if revalidation_reasons else "current",
        "reasons": revalidation_reasons,
        "incomplete_contracts": incomplete_contracts,
    }
    decision_projection = dict(execution_decision or {"status": "missing"})
    if execution_decision is not None and not decision_current:
        decision_projection["status"] = "stale"
    handoff = {
        "required": decision_projection.get("status") == "awaiting_main",
        "reason": decision_projection.get("handoff_reason"),
        "owner": "main_session",
        "boundary": decision_projection.get("boundary"),
    }
    return {
        "capability": "available",
        "strategy": "rolling_graph",
        "roadmap": roadmap,
        "ready_frontier": continuity.get("ready_frontier", {}),
        "compilation_focus": continuity.get("compilation_focus"),
        "execution_focus": continuity.get("execution_focus"),
        "execution_topology": compilation_policy.get(
            "execution_topology",
            (continuity.get("ready_frontier") or {}).get("execution_topology", "single_agent"),
        ),
        "dispatch_status": (
            "contract_revalidation_required" if policy_revalidation["status"] == "required"
            else "confirmation_required" if decision_projection.get("status") == "pending"
            else "handoff_required" if handoff["required"]
            else decision_projection.get("selected_mode")
            or compilation_policy.get(
                "dispatch_status",
                (continuity.get("ready_frontier") or {}).get("dispatch_status", "single_agent"),
            )
        ),
        "execution_decision": decision_projection,
        "policy_revalidation": policy_revalidation,
        "handoff": handoff,
        "compilation_policy": compilation_policy,
        "packets": [_packet_snapshot(node) for node in packets],
        "integration": {
            "milestone_id": active_milestone.get("id") if active_milestone else None,
            "mode": active_milestone_state.get(
                "merge_mode",
                active_milestone_state.get("integration_mode", "accumulated_workspace"),
            ),
            "required": bool(compilation_policy.get("integration_required", True)),
            "status": active_milestone.get("milestone_state", {}).get("integration_status")
            if active_milestone else "not_ready",
        },
        "workers": worker_state,
        "exit_snapshots": {"count": len(snapshots), "latest": snapshots[-1] if snapshots else None},
        "compiler_inputs": {
            "status": compiler_status,
            "compiled_codegraph_fingerprint": compiled_fingerprint,
            "current_codegraph_fingerprint": current_fingerprint,
            "compilation_revision": compilation_snapshot.get("compilation_revision"),
        },
    }


def _transition_snapshot(
    status: dict[str, Any], upgrade: dict[str, Any], *, readback_error: str | None = None
) -> dict[str, Any]:
    task_status = status.get("status")
    continuity_status = status.get("continuity_status")
    bootstrap_status = status.get("bootstrap_status")
    blockers = set(status.get("strict_blockers") or [])
    repair_blockers = {
        "degraded_recovery",
        "workspace_policy_unavailable",
        "workspace_checkpoint_protection_invalid",
        "contract_unavailable",
    }
    upgrade_status = upgrade.get("status")
    repair_upgrade_statuses = {
        "upgrade_available",
        "manual_decision_required",
        "blocked",
        "reverification_required",
        "newer_than_cli",
        "unavailable",
    }

    if (
        readback_error
        or task_status == "unavailable"
        or status.get("recovery_source")
        or continuity_status == "degraded_recovery"
        or bootstrap_status == "needs_recovery"
        or blockers & repair_blockers
        or upgrade_status in repair_upgrade_statuses
    ):
        transition_status = "repair_required"
        suggested_route = None
        available_routes: list[str] = []
    elif task_status == "idle" or not status.get("id"):
        transition_status = "transition_required"
        suggested_route = "start-new"
        available_routes = ["start-new"]
    elif task_status == "selection_required":
        transition_status = "adopt_required"
        suggested_route = None
        available_routes = []
    else:
        continuity = status.get("continuity") or {}
        plan = continuity.get("plan") if isinstance(continuity, dict) else None
        nodes = plan.get("nodes") if isinstance(plan, dict) else None
        rolling_ready = bool(
            isinstance(plan, dict)
            and plan.get("strategy") == "rolling_graph"
            and (
                continuity.get("compilation_focus")
                or continuity.get("execution_focus")
                or (continuity.get("ready_frontier") or {}).get("milestones")
                or (continuity.get("ready_frontier") or {}).get("work_packets")
                or task_status == "review_ready"
            )
        )
        usable_plan = bool(nodes and (continuity.get("current_node") or task_status == "review_ready" or rolling_ready))
        if continuity_status == "legacy" or bootstrap_status == "needs_plan_confirmation" or not usable_plan:
            transition_status = "adopt_required"
            suggested_route = None
            available_routes = ["switch-superseded"] if task_status in {"active", "paused", "blocked", "review_ready"} else []
        else:
            transition_status = "ready"
            suggested_route = None
            available_routes = []
            if task_status == "review_ready":
                available_routes = ["switch-passed", "switch-superseded"]
            elif task_status in {"active", "paused", "blocked"}:
                available_routes = ["switch-superseded"]

    return {
        "status": transition_status,
        "suggested_route": suggested_route,
        "available_routes": available_routes,
        "resume_original_intent": True,
        "after_resolution": "resume_original_intent",
    }


def _agent_focus_refresh_projection(payload: dict[str, Any]) -> dict[str, Any]:
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    readback = project.get("readback") if isinstance(project.get("readback"), dict) else {}
    upgrade = project.get("upgrade") if isinstance(project.get("upgrade"), dict) else {}
    rolling = project.get("rolling_graph") if isinstance(project.get("rolling_graph"), dict) else {}
    transition = project.get("transition") if isinstance(project.get("transition"), dict) else {}
    service = payload.get("service") if isinstance(payload.get("service"), dict) else {}
    progress = service.get("progress") if isinstance(service.get("progress"), dict) else {}
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    source = runtime.get("source") if isinstance(runtime.get("source"), dict) else {}
    integration = rolling.get("integration") if isinstance(rolling.get("integration"), dict) else {}
    compilation_policy = rolling.get("compilation_policy") if isinstance(rolling.get("compilation_policy"), dict) else {}
    workers = rolling.get("workers") if isinstance(rolling.get("workers"), dict) else {}
    execution_decision = rolling.get("execution_decision") if isinstance(rolling.get("execution_decision"), dict) else {}
    policy_revalidation = rolling.get("policy_revalidation") if isinstance(rolling.get("policy_revalidation"), dict) else {}
    execution_handoff = rolling.get("handoff") if isinstance(rolling.get("handoff"), dict) else {}
    revalidation_targets = upgrade.get("revalidation_targets")
    inspection = upgrade.get("inspection") if isinstance(upgrade.get("inspection"), dict) else {}
    inspection_upgrade = inspection.get("upgrade") if isinstance(inspection.get("upgrade"), dict) else {}
    pending_step_ids = upgrade.get("pending_step_ids")
    if not isinstance(pending_step_ids, list):
        pending_step_ids = [
            step.get("id") for step in inspection_upgrade.get("pending_steps", [])
            if isinstance(step, dict) and step.get("id")
        ]
    return {
        "view": AGENT_FOCUS_VIEW,
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "receipt": payload.get("receipt"),
        "next": payload.get("next"),
        "links": payload.get("links"),
        "runtime": {"status": runtime.get("status"), "source_version": source.get("version")},
        "project": {
            "status": project.get("status"),
            "readback": readback,
            "strict_exit_code": project.get("strict_exit_code"),
            "upgrade": {
                "status": upgrade.get("status"),
                "pending_step_ids": pending_step_ids,
                "confirmation_required": bool(
                    upgrade.get("confirmation_required")
                    or inspection_upgrade.get("confirmation_required")
                ),
                "revalidation_targets": len(revalidation_targets)
                if isinstance(revalidation_targets, list)
                else None,
            },
            "rolling_graph": {
                "capability": rolling.get("capability"),
                "strategy": rolling.get("strategy"),
                "execution_focus": rolling.get("execution_focus"),
                "execution_topology": rolling.get("execution_topology"),
                "dispatch_status": rolling.get("dispatch_status"),
                "execution_decision": {
                    "status": execution_decision.get("status"),
                    "recommended_mode": execution_decision.get("recommended_mode"),
                    "selected_mode": execution_decision.get("selected_mode"),
                    "worker_profile": execution_decision.get("worker_profile"),
                    "launch_status": execution_decision.get("launch_status"),
                    "boundary": execution_decision.get("boundary"),
                },
                "policy_revalidation": {
                    "status": policy_revalidation.get("status"),
                    "reasons": policy_revalidation.get("reasons", []),
                },
                "handoff": execution_handoff,
                "packet_count": len(rolling.get("packets", [])) if isinstance(rolling.get("packets"), list) else 0,
                "worker_status": workers.get("status"),
                "worker_count": workers.get("count", 0),
                "policy": {
                    "merge_mode": compilation_policy.get("merge_mode"),
                    "review_budget": compilation_policy.get("review_budget"),
                    "conflict_owner": compilation_policy.get("conflict_owner"),
                },
                "integration_status": integration.get("status"),
            },
            "transition": {
                "status": transition.get("status"),
                "suggested_route": transition.get("suggested_route"),
                "available_routes": transition.get("available_routes", []),
            },
        },
        "service": {
            "progress_status": progress.get("status"),
            "control_plane_url": progress.get("url"),
        },
        "handoff": payload.get("handoff"),
    }


def build_refresh_payload(
    control,
    repo: pathlib.Path,
    *,
    session_id: str | None = None,
    view: str = "full",
) -> dict[str, Any]:
    if view not in {"full", AGENT_FOCUS_VIEW}:
        raise ValueError(f"unsupported refresh view: {view}")
    repo = control.resolve_repo(str(repo))
    runtime = _runtime_snapshot()
    state = control.paths(repo)
    status_error: str | None = None
    try:
        with control.evaluation_scope(repo):
            status = control.build_status_payload(repo, state, view="compact")
            if not isinstance(status, dict):
                raise ValueError("status readback is not an object")
            upgrade = _upgrade_snapshot(control, repo, state, status)
            rolling = _rolling_snapshot(control, repo, status, state)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        status = {"status": "unavailable", "strict_blockers": []}
        status_error = str(error)
        upgrade = {"status": "unavailable"}
        rolling = {"capability": "unavailable"}
    transition = _transition_snapshot(status, upgrade, readback_error=status_error)
    project_status, project_next = _project_result(status, upgrade, rolling)
    progress = _progress_snapshot(repo)
    if status_error:
        final_status = "runtime_unavailable"
        next_action = "restore Auto Dev status readback, then run refresh again"
    elif runtime["status"] == "runtime_unavailable":
        final_status = "runtime_unavailable"
        next_action = "restore a complete Auto Dev bundle, then run refresh again"
    elif runtime["status"] == "fresh_session_required":
        final_status = "fresh_session_required"
        next_action = "open a new Codex conversation in the same checkout and run $auto-dev:refresh"
    elif progress.get("status") != "healthy" or not progress.get("url"):
        final_status = "runtime_unavailable"
        next_action = "restore the Auto Dev control-plane UI, then run refresh again"
    else:
        final_status = project_status
        next_action = project_next
    if final_status not in FINAL_STATUSES:
        final_status = "runtime_unavailable"
        next_action = "refresh could not produce a known final state"
    payload = {
        "schema_version": 1,
        "status": final_status,
        "receipt": f"⬆️ Auto Dev Refresh: {final_status}",
        "next": next_action,
        "links": {
            "project": {"label": repo.name, "path": str(repo)},
            "control_plane": {
                "label": "Auto Dev control plane",
                "url": progress.get("url"),
            },
        },
        "runtime": runtime,
        "project": {
            "status": project_status,
            "readback": (
                control.agent_focus_projection(status)
                if view == AGENT_FOCUS_VIEW
                else status
            ),
            "readback_error": status_error,
            "strict_exit_code": 0 if status.get("continuity_status") == "ready" else 2,
            "upgrade": upgrade,
            "rolling_graph": rolling,
            "transition": transition,
        },
        "service": {
            "progress": progress,
            "writer_lease": _lease_snapshot(control, repo, status, session_id),
        },
        "handoff": {
            "mode": "same_checkout_session_start",
            "import_required": False,
            "task_creation": False,
        },
    }
    return _agent_focus_refresh_projection(payload) if view == AGENT_FOCUS_VIEW else payload


def command_refresh(control, args) -> int:
    try:
        repo = control.resolve_repo(args.repo_root)
    except (OSError, ValueError) as error:
        payload = {
            "schema_version": 1,
            "status": "runtime_unavailable",
            "receipt": "⬆️ Auto Dev Refresh: runtime_unavailable",
            "next": "run refresh from a managed project checkout, then try again",
            "runtime": {"status": "runtime_unavailable", "reasons": [str(error)]},
            "links": {
                "project": {
                    "label": pathlib.Path(args.repo_root).expanduser().name or "project",
                    "path": str(pathlib.Path(args.repo_root).expanduser().resolve()),
                },
                "control_plane": {"label": "Auto Dev control plane", "url": None},
            },
            "project": {"status": "unavailable", "readback": None, "readback_error": str(error)},
            "service": {"progress": {"status": "not_observable"}, "writer_lease": {"status": "not_observable"}},
            "handoff": {"mode": "same_checkout_session_start", "import_required": False, "task_creation": False},
        }
        payload["project"]["transition"] = _transition_snapshot(
            {"status": "unavailable"}, {"status": "unavailable"}, readback_error=str(error)
        )
    else:
        with _refresh_singleflight(repo):
            payload = build_refresh_payload(
                control,
                repo,
                session_id=getattr(args, "session_id", None),
                view=getattr(args, "view", "full"),
            )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "ready" else 2
