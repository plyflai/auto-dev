"""Read-only status projection for the Auto Dev control plane."""

from __future__ import annotations

import json
import pathlib
from typing import Any


AGENT_FOCUS_VIEW = "agent-focus"


def _bounded_values(value: Any, *, limit: int = 8) -> list[Any]:
    if not isinstance(value, list):
        return []
    result = value[:limit]
    if len(value) > limit:
        result.append(f"...+{len(value) - limit}")
    return result


def agent_focus_projection(control, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a decision-only read model without re-evaluating control state."""
    if payload is None:
        payload = control
    summary = payload.get("continuity_summary")
    summary = summary if isinstance(summary, dict) else {}
    current_state = payload.get("current_state")
    current_state = current_state if isinstance(current_state, dict) else {}
    contract_gate = payload.get("contract_gate")
    contract_gate = contract_gate if isinstance(contract_gate, dict) else {}
    policy = payload.get("workspace_policy")
    policy = policy if isinstance(policy, dict) else {}
    verification = summary.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    frontier = summary.get("ready_frontier")
    frontier = frontier if isinstance(frontier, dict) else {}
    hierarchy = payload.get("hierarchy")
    upgrade = hierarchy.get("control_plane_upgrade") if isinstance(hierarchy, dict) else {}
    upgrade = upgrade if isinstance(upgrade, dict) else {}

    focus_verification = {
        key: verification.get(key)
        for key in (
            "node_id",
            "display_code",
            "required_proofs",
            "passed_proofs",
            "failed_proofs",
            "pending_proofs",
            "attempt_count",
        )
        if key in verification
    }
    return {
        "view": AGENT_FOCUS_VIEW,
        "schema_version": payload.get("schema_version"),
        "state_revision": payload.get("state_revision", 0),
        "project_revision": payload.get("project_revision", 0),
        "status": payload.get("status"),
        "id": payload.get("id"),
        "tier": payload.get("tier"),
        "task": payload.get("task"),
        "project_context_id": payload.get("project_context_id"),
        "primary_outcome_id": payload.get("primary_outcome_id"),
        "continuity_status": payload.get("continuity_status"),
        "bootstrap_status": payload.get("bootstrap_status"),
        "strict_blockers": list(payload.get("strict_blockers") or []),
        "completion_blockers": list(payload.get("completion_blockers") or []),
        "product_write_blockers": list(payload.get("product_write_blockers") or []),
        "state_drift": _bounded_values(payload.get("state_drift")),
        "current": {
            "node": summary.get("current_node"),
            "node_role": summary.get("current_node_role"),
            "execution_focus": summary.get("execution_focus"),
            "compilation_focus": summary.get("compilation_focus"),
            "next_action": summary.get("next_action"),
            "pending_action": summary.get("pending_action"),
        },
        "ready_frontier": {
            "milestones": _bounded_values(frontier.get("milestones")),
            "work_packets": _bounded_values(frontier.get("work_packets")),
            "parallel_groups": _bounded_values(frontier.get("parallel_groups"), limit=4),
            "updated_at": frontier.get("updated_at"),
        },
        "verification": focus_verification,
        "outcome_summary": payload.get("outcome_summary") or {},
        "contract": {
            "status": contract_gate.get("status"),
            "prewrite_missing": bool(contract_gate.get("prewrite_missing")),
        },
        "workspace": {
            "branch": current_state.get("branch"),
            "head": current_state.get("head"),
            "out_of_scope_changes": _bounded_values(current_state.get("out_of_scope_changes")),
            "preexisting_changes": _bounded_values(current_state.get("preexisting_changes")),
            "policy_status": policy.get("status"),
            "policy_revision": policy.get("revision"),
        },
        "upgrade": {
            "status": upgrade.get("status"),
            "revalidation_required": upgrade.get("revalidation_required"),
        },
    }


def compact_outcome_projection(
    control,
    receipt: dict[str, Any],
    continuity: dict[str, Any] | None,
    *,
    include_history: bool = True,
) -> dict[str, Any]:
    if continuity is not None and continuity["plan"].get("nodes"):
        nodes = continuity["plan"]["nodes"]
        proofs = continuity.get("proofs", [])
    else:
        outcome = receipt.get("outcome")
        nodes = (
            [{"id": "run", "status": receipt.get("status"), "outcome": outcome}] if outcome else []
        )
        proofs = receipt.get("proofs", [])
    current_digests = {
        node["id"]: control.outcome_digest(node["outcome"])
        for node in nodes
        if node.get("id") and node.get("outcome")
    }
    compact_proofs = []
    proof_histories: dict[tuple[str, str], list[dict[str, Any]]] = {}
    raw_histories: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for proof in proofs:
        proof_key = (str(proof.get("node_id") or ""), str(proof.get("proof_id") or ""))
        if all(proof_key):
            raw_histories.setdefault(proof_key, []).append(proof)
    selected_proofs = proofs
    if not include_history:
        def selected_attempt_index(proof: dict[str, Any]) -> int:
            try:
                return int(proof.get("attempt_index", 1))
            except (TypeError, ValueError):
                return 0

        selected_proofs = [
            max(history, key=selected_attempt_index)
            for history in raw_histories.values()
        ]
    for proof in selected_proofs:
        node_id = proof.get("node_id")
        outcome = next((node.get("outcome") for node in nodes if node.get("id") == node_id), None)
        fresh = (
            bool(
                isinstance(outcome, dict)
                and control.proof_is_fresh(
                    proof,
                    outcome=outcome,
                    repo=pathlib.Path(receipt.get("repo_root", ".")),
                    plan_revision=(
                        int(continuity.get("plan", {}).get("revision", 0)) if continuity else 0
                    ),
                    node=next(
                        (candidate for candidate in nodes if candidate.get("id") == node_id),
                        None,
                    ),
                )
            )
            if outcome
            else bool(proof.get("fresh", False))
        )
        compact_proof = control.redact_for_handoff(
            {
                "task_id": proof.get("task_id", receipt.get("id")),
                "node_id": node_id,
                "proof_id": proof.get("proof_id"),
                "description": proof.get("description"),
                "status": proof.get("status"),
                "exit_code": proof.get("exit_code"),
                "head": proof.get("head"),
                "at": proof.get("at"),
                "attempt_id": proof.get("attempt_id"),
                "attempt_index": proof.get("attempt_index", 1),
                "fresh": fresh,
                "current_outcome": proof.get("outcome_sha256") == current_digests.get(node_id),
                **(
                    {"failure_classification": proof["failure_classification"]}
                    if proof.get("failure_classification")
                    else {}
                ),
                **(
                    {"evidence_artifact": proof["evidence_artifact"]}
                    if isinstance(proof.get("evidence_artifact"), dict)
                    else {}
                ),
                **(
                    {"e2e_evidence": proof["e2e_evidence"]}
                    if isinstance(proof.get("e2e_evidence"), dict)
                    else {}
                ),
                **(
                    {"release_evidence": proof["release_evidence"]}
                    if isinstance(proof.get("release_evidence"), dict)
                    else {}
                ),
                **(
                    {"performance_evidence": proof["performance_evidence"]}
                    if isinstance(proof.get("performance_evidence"), dict)
                    else {}
                ),
            }
        )
        compact_proofs.append(compact_proof)
        proof_key = (str(node_id or ""), str(proof.get("proof_id") or ""))
        if all(proof_key):
            proof_histories.setdefault(proof_key, []).append(compact_proof)

    def attempt_index(proof: dict[str, Any]) -> int:
        try:
            return int(proof.get("attempt_index", 1))
        except (TypeError, ValueError):
            return 0

    latest_proofs = []
    for proof_key, history in proof_histories.items():
        latest = max(history, key=attempt_index)
        attempt_count = len(raw_histories.get(proof_key, history))
        latest_proofs.append({**latest, "attempt_count": attempt_count})
    latest_proofs.sort(
        key=lambda proof: (str(proof.get("node_id", "")), str(proof.get("proof_id", "")))
    )
    summary = {
        "contracted_outcomes": 0,
        "proved_outcomes": 0,
        "legacy_nodes": 0,
        "historical_nodes": 0,
        "required_proofs": 0,
        "passed_proofs": 0,
        "failed_proofs": 0,
        "pending_proofs": 0,
    }
    for node in nodes:
        if node.get("historical_completion"):
            summary["historical_nodes"] += 1
        outcome = node.get("outcome")
        if not outcome:
            summary["legacy_nodes"] += 1
            continue
        summary["contracted_outcomes"] += 1
        required = {proof["id"] for proof in outcome.get("proofs", [])}
        matching = {
            proof.get("proof_id"): proof
            for proof in latest_proofs
            if proof.get("node_id") == node.get("id") and proof.get("current_outcome")
        }
        passed = {
            proof_id
            for (proof_id, proof) in matching.items()
            if proof.get("status") == "passed" and proof.get("fresh")
        }
        failed = {
            proof_id for (proof_id, proof) in matching.items() if proof.get("status") == "failed"
        }
        summary["required_proofs"] += len(required)
        summary["passed_proofs"] += len(required & passed)
        summary["failed_proofs"] += len(required & failed)
        summary["pending_proofs"] += len(required - passed - failed)
        if required and required <= passed:
            summary["proved_outcomes"] += 1
    return {"summary": summary, "proofs": compact_proofs, "latest_proofs": latest_proofs}


def current_verification_projection(
    control, continuity: dict[str, Any] | None, outcome_projection: dict[str, Any]
) -> dict[str, Any] | None:
    if continuity is None:
        return None
    node_id = continuity.get("current_node")
    node = next(
        (
            candidate
            for candidate in continuity.get("plan", {}).get("nodes", [])
            if isinstance(candidate, dict) and candidate.get("id") == node_id
        ),
        None,
    )
    if node is None:
        return None
    required = {
        str(proof.get("id"))
        for proof in (node.get("outcome") or {}).get("proofs", [])
        if isinstance(proof, dict) and proof.get("id")
    }
    latest = [
        proof
        for proof in outcome_projection.get("latest_proofs", [])
        if proof.get("node_id") == node_id and proof.get("current_outcome")
    ]
    by_id = {str(proof.get("proof_id")): proof for proof in latest if proof.get("proof_id")}
    passed = {
        proof_id
        for (proof_id, proof) in by_id.items()
        if proof.get("status") == "passed" and proof.get("fresh")
    }
    failed = {proof_id for (proof_id, proof) in by_id.items() if proof.get("status") == "failed"}
    return {
        "node_id": node_id,
        "display_code": node.get("display_code"),
        "node_kind": node.get("node_kind", "delivery"),
        "metadata": node.get("verification", {}),
        "required_proofs": len(required),
        "passed_proofs": len(required & passed),
        "failed_proofs": len(required & failed),
        "pending_proofs": len(required - passed - failed),
        "attempt_count": sum((int(proof.get("attempt_count", 1)) for proof in latest)),
        "latest_proofs": latest,
    }


def hierarchy_projection(
    control,
    state: dict[str, pathlib.Path],
    *,
    receipt: dict[str, Any] | None = None,
    session_key: str | None = None,
    view_context_id: str | None = None,
    upgrade_profile: str = "full",
    active_reconciliation_issues: list[dict[str, Any]] | None = None,
    compact: bool = False,
) -> dict[str, Any]:
    repo = state["root"].parent
    try:
        project = control.load_project(state, repo)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return {"status": "unavailable", "error": str(error)}
    if project is None:
        return {
            "status": "uninitialized",
            "contexts": [],
            "view_focus": None,
            "execution_focus": None,
        }
    context_id = (
        view_context_id
        or (receipt.get("project_context_id") if isinstance(receipt, dict) else None)
        or project.get("default_context_id")
    )
    if context_id not in project.get("contexts", {}):
        context_id = project.get("default_context_id")
    contexts = [
        {**control.context_summary(entry), "selected": context_id == entry.get("id")}
        for entry in project.get("contexts", {}).values()
        if isinstance(entry, dict)
    ]
    result: dict[str, Any] = {
        "status": "ready",
        "control_root_id": project.get("project_id"),
        "project_revision": project.get("state_revision", 0),
        "control_plane_upgrade": control.control_plane_upgrade_projection(
            project,
            repo=repo,
            state=state,
            profile=upgrade_profile,
            active_reconciliation_issues=active_reconciliation_issues,
        ),
        "contexts": contexts,
        "view_focus": control.read_view_focus(state, session_key) if session_key else None,
        "execution_focus": {
            "task_id": receipt.get("id") if isinstance(receipt, dict) else None,
            "project_context_id": (
                receipt.get("project_context_id") if isinstance(receipt, dict) else None
            ),
            "outcome_id": receipt.get("primary_outcome_id") if isinstance(receipt, dict) else None,
            "branch_context": receipt.get("base_branch") if isinstance(receipt, dict) else None,
        },
    }
    if not isinstance(context_id, str) or context_id not in project.get("contexts", {}):
        return result
    entry = project["contexts"][context_id]
    if compact:
        result["managed_context"] = {"summary": control.context_summary(entry)}
        return result
    try:
        frame = control.read_context_frame(state, context_id)
        outcomes = control.list_outcome_records(state, context_id)
        capabilities = control.list_capability_records(state, context_id)
        activities = control.list_activity_records(state, context_id)
        result["managed_context"] = {"summary": control.context_summary(entry), "frame": frame}
        result["outcome_graph"] = {
            "outcomes": outcomes,
            "edges": {
                source: sorted(targets)
                for (source, targets) in control.outcome_edges(outcomes).items()
                if targets
            },
        }
        result["capability_map"] = capabilities
        result["activities"] = {"count": len(activities), "recent": activities[:12]}
    except (OSError, json.JSONDecodeError, ValueError) as error:
        result["context_projection_status"] = "partial"
        result["context_projection_error"] = str(error)
    return result


def attach_intake_gate(
    control,
    payload: dict[str, Any],
    state: dict[str, pathlib.Path],
    session_key: str | None,
    view_context_id: str | None,
    *,
    hierarchy_compact: bool = False,
) -> dict[str, Any]:
    payload["intake_gate"] = control.intake_gate_projection(state, session_key)
    payload.setdefault("contract_gate", {"status": "unbound", "capsule": {"status": "legacy"}})
    payload.setdefault("contract_capsule", {"status": "legacy"})
    payload["hierarchy"] = hierarchy_projection(
        control,
        state,
        session_key=session_key,
        view_context_id=view_context_id,
        upgrade_profile="active",
        compact=hierarchy_compact,
    )
    return payload


def build_status_identity(
    control,
    repo: pathlib.Path,
    state: dict[str, pathlib.Path] | None = None,
) -> dict[str, Any]:
    """Read only the revision identity needed to suppress unchanged prompt refreshes."""
    with control.evaluation_scope(repo):
        state = state or control.paths(repo)
        receipt, resolution = control.resolve_branch_task(repo, state)
        if receipt is None:
            status = "selection_required" if resolution.get("candidates") else "idle"
            return {
                "status": status,
                "id": None,
                "state_revision": 0,
                "project_revision": resolution.get("project_revision", 0),
                "context_key": resolution.get("context_key"),
            }
        return {
            "status": receipt.get("status"),
            "id": receipt.get("id"),
            "state_revision": receipt.get("state_revision", 0),
            "project_revision": resolution.get("project_revision", 0),
            "context_key": resolution.get("context_key"),
        }


def build_status_payload(
    control,
    repo: pathlib.Path,
    state: dict[str, pathlib.Path] | None = None,
    *,
    view: str = "full",
    session_key: str | None = None,
    project_context_id: str | None = None,
    profile: str = "default",
) -> dict[str, Any]:
    requested_view = view
    internal_view = "compact" if view == AGENT_FOCUS_VIEW else view
    with control.evaluation_scope(repo):
        payload = _build_status_payload(
            control,
            repo,
            state,
            view=internal_view,
            session_key=session_key,
            project_context_id=project_context_id,
            profile=profile,
        )
    return agent_focus_projection(payload) if requested_view == AGENT_FOCUS_VIEW else payload


def _build_status_payload(
    control,
    repo: pathlib.Path,
    state: dict[str, pathlib.Path] | None = None,
    *,
    view: str = "full",
    session_key: str | None = None,
    project_context_id: str | None = None,
    profile: str = "default",
) -> dict[str, Any]:
    if profile not in {"default", "gate", "progress", "hook"}:
        raise ValueError(f"unsupported status profile: {profile}")
    gate_profile = profile == "gate"
    hook_profile = profile == "hook"
    include_history = profile == "default"
    state = state or control.paths(repo)
    workspace = control.workspace_summary(repo)
    (receipt, resolution) = control.resolve_branch_task(repo, state)
    if receipt is None:
        if resolution.get("candidates"):
            return attach_intake_gate(
                control,
                {
                    "status": "selection_required",
                    "bootstrap_status": "needs_task_selection",
                    "continuity_status": "needs_user",
                    "project_id": resolution.get("project_id"),
                    "project_revision": resolution.get("project_revision", 0),
                    "context_key": resolution.get("context_key"),
                    "workspace": workspace,
                    "workspace_policy": control.workspace_policy_projection(repo, state),
                    "protected_branch": control.is_protected(
                        resolution.get("branch"), control.protected_branches(state)
                    ),
                    "current_state": {
                        "branch": resolution.get("branch"),
                        "head": resolution.get("head"),
                        "status": control.workspace_product_status(control.current_status(repo)),
                        "out_of_scope_changes": [],
                        "preexisting_changes": [],
                    },
                    "task_candidates": resolution["candidates"],
                    "strict_blockers": ["needs_user"],
                },
                state,
                session_key,
                project_context_id,
                hierarchy_compact=hook_profile,
            )
        if resolution.get("project_id") is None:
            return {"status": "idle", "bootstrap_status": "needs_plan_discovery"}
        return attach_intake_gate(
            control,
            {
                "status": "idle",
                "bootstrap_status": "needs_plan_discovery",
                "project_id": resolution.get("project_id"),
                "project_revision": resolution.get("project_revision", 0),
                "context_key": resolution.get("context_key"),
                "workspace": workspace,
                "workspace_policy": control.workspace_policy_projection(repo, state),
                "protected_branch": control.is_protected(
                    resolution.get("branch"), control.protected_branches(state)
                ),
                "current_state": {
                    "branch": resolution.get("branch"),
                    "head": resolution.get("head"),
                    "status": control.workspace_product_status(control.current_status(repo)),
                    "out_of_scope_changes": [],
                    "preexisting_changes": [],
                },
            },
            state,
            session_key,
            project_context_id,
            hierarchy_compact=hook_profile,
        )
    recovery_source = resolution.get("task_recovery_source")
    try:
        receipt = control.normalize_receipt(receipt)
    except (OSError, json.JSONDecodeError, ValueError):
        backup = state["active"].with_suffix(".bak")
        if not backup.exists():
            raise ValueError("active receipt is unreadable and no backup exists")
        receipt = control.normalize_receipt(control.read_json(backup))
        recovery_source = "active.bak"
    branch = control.current_branch(repo)
    head = control.git_head(repo)
    status = control.current_status(repo)
    product_status = control.workspace_product_status(status)
    scopes = receipt.get("planned_scope", [])
    (out_of_scope, preexisting_changes) = control.worktree_drift(repo, receipt, status, scopes)
    drift = []
    if receipt.get("base_branch") and branch != receipt.get("base_branch"):
        drift.append("branch_changed")
    if out_of_scope:
        drift.append("out_of_scope_changes")
    continuity = control.continuity_from_receipt(receipt)
    policy_state = control.workspace_policy_projection(repo, state, receipt, continuity)
    workspace_points = control.workspace_checkpoint_refs(repo, state)
    workspace_point_counts: dict[str, int] = {}
    for point in workspace_points:
        point_status = str(point.get("status") or "unknown")
        workspace_point_counts[point_status] = workspace_point_counts.get(point_status, 0) + 1
    workspace_checkpoint_protection = control.workspace_checkpoint_protections_projection(
        receipt, workspace_points
    )
    current_plan_node_ids = [
        node["id"]
        for node in (continuity or {}).get("plan", {}).get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("id"), str) and node["id"]
    ]
    workspace_checkpoint_nodes = control.workspace_checkpoint_node_projection(
        workspace_checkpoint_protection,
        points=control.receipt_workspace_points(receipt),
        checkpoint_refs=workspace_points,
        node_ids=current_plan_node_ids,
    )
    outcome_projection = compact_outcome_projection(
        control, receipt, continuity, include_history=include_history
    )
    verification_projection = current_verification_projection(
        control, continuity, outcome_projection
    )
    impact_state = (
        {"status": "deferred", "receipt_count": 0, "receipts": [], "latest": None}
        if gate_profile or hook_profile
        else control.impact_projection(repo, continuity)
    )
    diagnostic_state = None if (gate_profile or hook_profile) else control.diagnostic_projection(repo, continuity)
    reconciliation_issues = control.continuity_reconciliation_issues(repo, continuity)
    try:
        contract_gate = control.contract_gate_for_receipt(repo, state, receipt, continuity)
    except (KeyError, TypeError, OSError, json.JSONDecodeError, ValueError) as error:
        contract_gate = {
            "status": "unavailable",
            "error": str(error),
            "capsule": {"status": "unavailable"},
        }
    contract_capsule = contract_gate.get("capsule", {"status": "legacy"})
    strict_contract = control.contract_is_strict(
        receipt.get("contract_snapshot")
        if isinstance(receipt.get("contract_snapshot"), dict)
        else None
    )
    unattributed_actions = control.unattributed_action_evidence(receipt, continuity)
    open_gaps = [gap for gap in (continuity or {}).get("gaps", []) if gap.get("status") == "open"]
    blocking_user_gaps = [
        gap for gap in open_gaps if gap.get("blocking") and gap.get("owner") == "user"
    ]
    blocking_external_gaps = [
        gap for gap in open_gaps if gap.get("blocking") and gap.get("owner") == "external"
    ]
    dependency_issues = []
    if continuity is not None:
        nodes = {node.get("id"): node for node in continuity["plan"].get("nodes", [])}
        for node in nodes.values():
            if node.get("status") not in {"active", "done"}:
                continue
            unfinished = [
                dependency
                for dependency in node.get("depends_on", [])
                if dependency in nodes and nodes[dependency].get("status") != "done"
            ]
            if unfinished:
                dependency_issues.append({"node_id": node.get("id"), "blocked_by": unfinished})
    pending_action = (continuity or {}).get("pending_action")
    strict_blockers = []
    review_ready = receipt.get("status") == "review_ready"
    if recovery_source:
        strict_blockers.append("degraded_recovery")
    if pending_action:
        strict_blockers.append("pending_action")
    if unattributed_actions:
        strict_blockers.append("unattributed_action_evidence")
    if blocking_user_gaps:
        strict_blockers.append("needs_user")
    if blocking_external_gaps:
        strict_blockers.append("blocked_external")
    if dependency_issues:
        strict_blockers.append("dependency_not_ready")
    if reconciliation_issues:
        strict_blockers.append("verification_reconcile")
    if policy_state.get("status") == "unavailable":
        strict_blockers.append("workspace_policy_unavailable")
    if review_ready:
        strict_blockers.append("review_ready")
    if (
        workspace_checkpoint_protection["before_invalid"]
        or workspace_checkpoint_protection["after_invalid"]
    ):
        strict_blockers.append("workspace_checkpoint_protection_invalid")
    if strict_contract and contract_gate.get("status") in {
        "stale",
        "plan_stale",
        "plan_incomplete",
        "unavailable",
    }:
        strict_blockers.append(f"contract_{contract_gate['status']}")
    if strict_contract and contract_gate.get("prewrite_missing"):
        strict_blockers.append("contract_prewrite_pending")
    strict_blockers.extend(drift)
    project_control = control.load_project(state, repo)
    verification_gate_policy = (
        project_control.get("verification_gate_policy")
        if isinstance(project_control, dict)
        else control.LEGACY_VERIFICATION_GATE_POLICY
    )
    active_node = next(
        (
            node
            for node in (continuity or {}).get("plan", {}).get("nodes", [])
            if node.get("id") == (continuity or {}).get("current_node")
        ),
        None,
    )
    deferred_verification_reconcile = bool(
        verification_gate_policy == control.VERIFICATION_GATE_POLICY
        and reconciliation_issues
        and all(issue.get("kind") == "stale_proof" for issue in reconciliation_issues)
        and isinstance(active_node, dict)
        and active_node.get("status") == "active"
    )
    product_write_blockers = [
        blocker
        for blocker in strict_blockers
        if not (deferred_verification_reconcile and blocker == "verification_reconcile")
    ]
    if recovery_source:
        continuity_state = "degraded_recovery"
    elif continuity is None:
        continuity_state = "legacy"
    elif pending_action:
        continuity_state = "interrupted"
    elif unattributed_actions:
        continuity_state = "needs_reconcile"
    elif blocking_user_gaps:
        continuity_state = "needs_user"
    elif blocking_external_gaps:
        continuity_state = "blocked_external"
    elif dependency_issues:
        continuity_state = "needs_reconcile"
    elif reconciliation_issues:
        continuity_state = "needs_reconcile"
    elif policy_state.get("status") == "unavailable":
        continuity_state = "needs_reconcile"
    elif strict_contract and contract_gate.get("status") in {
        "stale",
        "plan_stale",
        "plan_incomplete",
        "unavailable",
    }:
        continuity_state = "needs_reconcile"
    elif strict_contract and contract_gate.get("prewrite_missing"):
        continuity_state = "needs_reconcile"
    elif drift:
        continuity_state = "needs_reconcile"
    elif (
        workspace_checkpoint_protection["before_invalid"]
        or workspace_checkpoint_protection["after_invalid"]
    ):
        continuity_state = "needs_reconcile"
    elif review_ready:
        continuity_state = "review_ready"
    else:
        continuity_state = "ready"
    if recovery_source:
        bootstrap_status = "needs_recovery"
    elif continuity is None or not continuity.get("plan", {}).get("nodes"):
        bootstrap_status = "needs_plan_confirmation"
    elif continuity_state == "needs_reconcile":
        bootstrap_status = "needs_reconcile"
    else:
        bootstrap_status = (continuity.get("bootstrap") or {}).get("status", "ready")
    legacy_nodes = []
    if continuity is None:
        legacy_nodes = [
            {
                "id": f"legacy-{index}",
                "title": event.get("summary", "delivery unit"),
                "status": "done",
                "acceptance": event.get("evidence", []),
                "depends_on": [],
                "parent_id": None,
            }
            for (index, event) in enumerate(
                (
                    event
                    for event in receipt.get("events", [])
                    if event.get("type") == "delivery_unit_complete"
                )
            )
        ]
    intake_gate = control.intake_gate_projection(state, session_key)
    review_document = receipt.get("review") if isinstance(receipt.get("review"), dict) else {}
    product_review = (
        review_document.get("product_review")
        if isinstance(review_document.get("product_review"), dict)
        else None
    )
    product_review_status = review_document.get("product_review_status") or (
        product_review.get("test", {}).get("status")
        if product_review
        else "missing" if review_ready else None
    )
    review_e2e_evidence = (
        control.task_e2e_evidence(repo, receipt) if review_ready and not gate_profile else []
    )
    review_release_evidence = (
        control.task_release_evidence(repo, receipt) if review_ready and not gate_profile else []
    )
    product_receipt = (
        control.product_review_receipt(product_review, review_e2e_evidence, review_release_evidence)
        if review_ready and not gate_profile
        else None
    )
    payload = {
        **receipt,
        "project_id": resolution.get("project_id"),
        "project_revision": resolution.get("project_revision", 0),
        "context_key": resolution.get("context_key"),
        "workspace": workspace,
        "workspace_policy": policy_state,
        "workspace_checkpoint_protection": workspace_checkpoint_protection,
        "workspace_checkpoint_nodes": workspace_checkpoint_nodes,
        "protected_branch": control.is_protected(branch, control.protected_branches(state)),
        "continuity_status": continuity_state,
        "bootstrap_status": bootstrap_status,
        "continuity_summary": {
            "goal_revision": continuity["goal"].get("revision") if continuity else None,
            "plan_revision": continuity["plan"].get("revision") if continuity else None,
            "plan_strategy": continuity["plan"].get("strategy", "legacy") if continuity else None,
            "current_node": continuity.get("current_node") if continuity else None,
            "current_node_role": active_node.get("node_role") if isinstance(active_node, dict) else None,
            "active_write_scope": active_node.get("write_scope", []) if isinstance(active_node, dict) else [],
            "compilation_focus": continuity.get("compilation_focus") if continuity else None,
            "execution_focus": continuity.get("execution_focus") if continuity else None,
            "ready_frontier": continuity.get("ready_frontier", {}) if continuity else {},
            "exit_snapshot_count": len(continuity.get("exit_snapshots", [])) if continuity else 0,
            "next_action": continuity.get("next_action") if continuity else None,
            "open_gaps": len(open_gaps),
            "blocking_user_gaps": len(blocking_user_gaps),
            "blocking_external_gaps": len(blocking_external_gaps),
            "unattributed_actions": len(unattributed_actions),
            "durability": (continuity or {}).get("durability", {}).get("level", "local"),
            "updated_at": (continuity or {}).get("updated_at"),
            "pending_action": pending_action,
            "verification": verification_projection,
            "impact": {key: value for (key, value) in impact_state.items() if key != "receipts"},
            "diagnostic": control.diagnostic_summary(diagnostic_state),
            "workspace_points": workspace_points,
            "workspace_point_counts": workspace_point_counts,
            "workspace_checkpoint_protection": workspace_checkpoint_protection,
        },
        "current_state": {
            "branch": branch,
            "head": head,
            "status": product_status,
            "control_metadata": [
                control.status_path(line)
                for line in status
                if control.workspace_control_metadata_path(control.status_path(line))
            ],
            "out_of_scope_changes": out_of_scope,
            "preexisting_changes": preexisting_changes,
        },
        "state_drift": drift,
        "strict_blockers": strict_blockers,
        "completion_blockers": strict_blockers,
        "product_write_blockers": product_write_blockers,
        "verification_gate_policy": verification_gate_policy,
        "verification_reconcile_mode": (
            "completion_only" if deferred_verification_reconcile else "strict"
        ),
        "contract_gate": contract_gate,
        "contract_capsule": contract_capsule,
        "dependency_issues": dependency_issues,
        "verification_issues": reconciliation_issues,
        "unattributed_actions": unattributed_actions,
        "recovery_source": recovery_source,
        "intake_gate": intake_gate,
        "product_review": product_review,
        "product_review_status": product_review_status,
        "product_receipt": product_receipt,
        "hierarchy": (
            {}
            if gate_profile
            else hierarchy_projection(
                control,
                state,
                receipt=receipt,
                session_key=session_key,
                view_context_id=project_context_id,
                upgrade_profile="active",
                active_reconciliation_issues=reconciliation_issues,
                compact=hook_profile,
            )
        ),
    }
    if continuity is not None and not gate_profile:
        payload["continuity"] = {
            **continuity,
            "diagnostic": diagnostic_state,
            "impact_receipts": impact_state["receipts"],
            "policy_approvals": continuity.get("policy_approvals", []),
        }
    if view == "full":
        return payload
    if view != "compact":
        raise ValueError(f"unsupported status view: {view}")
    continuity_view = None
    if continuity is not None and not gate_profile:
        continuity_view = {
            "schema_version": continuity.get("schema_version", control.CONTINUITY_SCHEMA_VERSION),
            "goal": continuity.get("goal", {}),
            "plan": continuity.get("plan", {}),
            "current_node": continuity.get("current_node"),
            "compilation_focus": continuity.get("compilation_focus"),
            "execution_focus": continuity.get("execution_focus"),
            "ready_frontier": continuity.get("ready_frontier", {}),
            "exit_snapshots": continuity.get("exit_snapshots", []),
            "next_action": continuity.get("next_action"),
            "gaps": continuity.get("gaps", []),
            "last_checkpoint": continuity.get("last_checkpoint"),
            "pending_action": continuity.get("pending_action"),
            "evidence_links": continuity.get("evidence_links", []),
            "workspace_points": continuity.get("workspace_points", []),
            "workspace_checkpoint_protections": continuity.get(
                "workspace_checkpoint_protections", []
            ),
            "impact_receipts": impact_state["receipts"],
            "policy_approvals": continuity.get("policy_approvals", []),
            "diagnostic": diagnostic_state,
            "durability": continuity.get("durability", {}),
            "bootstrap": continuity.get("bootstrap"),
            "proofs": outcome_projection["proofs"],
            "latest_proofs": outcome_projection["latest_proofs"],
            "verification_issues": reconciliation_issues,
            "legacy_nodes": [],
        }
    elif continuity is None:
        continuity_view = {"legacy_nodes": legacy_nodes}
    else:
        continuity_view = {
            "current_node": continuity.get("current_node"),
            "pending_action": continuity.get("pending_action"),
            "gaps": continuity.get("gaps", []),
            "proofs": [],
            "latest_proofs": outcome_projection["latest_proofs"],
            "legacy_nodes": [],
        }
    return {
        "view": "compact",
        "schema_version": control.SCHEMA_VERSION,
        "state_revision": receipt.get("state_revision", 0),
        "status": receipt.get("status"),
        "id": receipt.get("id"),
        "tier": receipt.get("tier"),
        "task": receipt.get("task"),
        "project_context_id": receipt.get("project_context_id"),
        "primary_outcome_id": receipt.get("primary_outcome_id"),
        "intake_id": receipt.get("intake_id"),
        "project_id": payload.get("project_id"),
        "project_revision": payload.get("project_revision", 0),
        "context_key": payload.get("context_key"),
        "workspace": workspace,
        "workspace_policy": policy_state,
        "workspace_checkpoint_protection": workspace_checkpoint_protection,
        "workspace_checkpoint_nodes": workspace_checkpoint_nodes,
        "protected_branch": payload.get("protected_branch", False),
        "continuity_status": continuity_state,
        "bootstrap_status": bootstrap_status,
        "continuity_summary": payload["continuity_summary"],
        "outcome_summary": outcome_projection["summary"],
        "continuity": continuity_view,
        "contract_gate": contract_gate,
        "contract_capsule": contract_capsule,
        "delivery_contract": {
            "acceptance": receipt.get("acceptance", []),
            "planned_scope": receipt.get("planned_scope", []),
            "scope_amendments": receipt.get("scope_amendments", []),
            "validation_plan": receipt.get("validation_plan", []),
            "capabilities": receipt.get("capabilities", {}),
            "budgets": receipt.get("budgets", {}),
            "budget_usage": receipt.get("budget_usage", {}),
            "exhausted_budgets": receipt.get("exhausted_budgets", []),
            "stop_conditions": receipt.get("stop_conditions", []),
            "outcome": receipt.get("outcome"),
            "proofs": outcome_projection["proofs"] if continuity is None else [],
            "latest_proofs": outcome_projection["latest_proofs"] if continuity is None else [],
        },
        "current_state": payload["current_state"],
        "state_drift": drift,
        "strict_blockers": strict_blockers,
        "completion_blockers": strict_blockers,
        "product_write_blockers": product_write_blockers,
        "verification_gate_policy": verification_gate_policy,
        "verification_reconcile_mode": (
            "completion_only" if deferred_verification_reconcile else "strict"
        ),
        "dependency_issues": dependency_issues,
        "verification_issues": reconciliation_issues,
        "unattributed_actions": unattributed_actions,
        "recovery_source": recovery_source,
        "event_count": len(receipt.get("events", [])),
        "last_event": receipt.get("events", [])[-1] if receipt.get("events") else None,
        "intake_gate": intake_gate,
        "product_review": payload["product_review"],
        "product_review_status": payload["product_review_status"],
        "product_receipt": payload["product_receipt"],
        "hierarchy": payload["hierarchy"],
    }
