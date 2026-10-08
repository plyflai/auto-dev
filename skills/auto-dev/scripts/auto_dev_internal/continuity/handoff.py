"""Portable task handoff export and import commands."""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

def command_handoff_export(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_active(state)
    continuity = control.continuity_from_receipt(receipt)
    if continuity is None:
        raise ValueError("handoff export requires an initialized continuity plan")
    dependency_registry = None
    if state["project_memory"].exists():
        try:
            dependency_registry = control.redact_for_handoff(control.read_json(state["project_memory"]))
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"dependency registry cannot be exported: {error}") from error
    dependency_lease = None
    if state["dependency_lease"].exists():
        try:
            dependency_lease = control.redact_for_handoff(control.read_json(state["dependency_lease"]))
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"dependency lease cannot be exported: {error}") from error
    packet = control.redact_for_handoff({
        "packet_schema_version": 4,
        "exported_at": control.now(),
        "task_id": receipt["id"],
        "receipt": {
            "tier": receipt.get("tier"),
            "task": receipt.get("task"),
            "requirement_receipt": receipt.get("requirement_receipt"),
            "project_context_id": receipt.get("project_context_id"),
            "primary_outcome_id": receipt.get("primary_outcome_id"),
            "intake_id": receipt.get("intake_id"),
            "acceptance": receipt.get("acceptance", []),
            "planned_scope": receipt.get("planned_scope", []),
            "scope_amendments": receipt.get("scope_amendments", []),
            "validation_plan": receipt.get("validation_plan", []),
            "capabilities": receipt.get("capabilities", {}),
            "budgets": receipt.get("budgets", {}),
            "budget_usage": receipt.get("budget_usage", {}),
            "contract_snapshot": receipt.get("contract_snapshot"),
            "contract_parent_hash": receipt.get("contract_parent_hash"),
            "contract_status": receipt.get("contract_status"),
            "contract_coverage_ids": receipt.get("contract_coverage_ids", []),
        },
        "continuity": {
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
            "proofs": continuity.get("proofs", []),
            "workspace_points": continuity.get("workspace_points", []),
            "workspace_checkpoint_protections": continuity.get("workspace_checkpoint_protections", []),
            "impact_receipts": continuity.get("impact_receipts", []),
            "policy_approvals": continuity.get("policy_approvals", []),
            "diagnostic": continuity.get("diagnostic"),
            "durability": {"level": "portable", "updated_at": control.now()},
            "bootstrap": continuity.get("bootstrap"),
            "updated_at": continuity.get("updated_at"),
        },
        "source": {
            "repo_fingerprint": control.repo_fingerprint(repo),
            "branch": control.current_branch(repo),
            "head": control.git_head(repo),
            "state_revision": receipt.get("state_revision", 0),
        },
        "dependency_registry": dependency_registry,
        "dependency_lease": dependency_lease,
    })
    if args.out == "-":
        print(json.dumps(packet, ensure_ascii=False, indent=2))
        return 0
    destination = pathlib.Path(args.out).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    control.write_json(destination, packet)
    print(json.dumps({
        "status": "exported",
        "task_id": receipt["id"],
        "path": str(destination),
        "state_revision": receipt.get("state_revision", 0),
    }, ensure_ascii=False))
    return 0


def command_handoff_import(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    current, resolution = control.resolve_branch_task(repo, state)
    if current is not None:
        raise ValueError(f"run already active on current branch: {current.get('id')}")
    if resolution.get("candidates"):
        raise ValueError("current branch requires task selection before handoff import")
    packet = control.read_json(pathlib.Path(args.file).expanduser().resolve())
    if packet.get("packet_schema_version") not in {1, 2, 3, 4}:
        raise ValueError("unsupported handoff packet schema")
    source_receipt = packet.get("receipt", {})
    source_branch = packet.get("source", {}).get("branch")
    if source_branch and source_branch != control.current_branch(repo):
        raise ValueError("handoff source branch does not match the current target branch")
    continuity = packet.get("continuity")
    if not isinstance(continuity, dict) or not continuity.get("plan", {}).get("nodes"):
        raise ValueError("handoff packet lacks a continuity plan")
    continuity["durability"] = {"level": "portable", "updated_at": control.now()}
    continuity["updated_at"] = control.now()
    continuity.setdefault("evidence_links", [])
    continuity.setdefault("proofs", [])
    continuity.setdefault("compilation_focus", None)
    continuity.setdefault("execution_focus", continuity.get("current_node"))
    continuity.setdefault("ready_frontier", {"milestones": [], "work_packets": []})
    continuity.setdefault("exit_snapshots", [])
    continuity.setdefault("workspace_points", [])
    continuity.setdefault("workspace_checkpoint_protections", [])
    continuity.setdefault("impact_receipts", [])
    continuity.setdefault("policy_approvals", [])
    if "diagnostic" in continuity:
        continuity["diagnostic"] = control.normalize_diagnostic(continuity.get("diagnostic"))
    for proof in continuity["proofs"]:
        if isinstance(proof, dict):
            proof.setdefault("attempt_index", 1)
            proof.setdefault(
                "attempt_id",
                f"legacy-{proof.get('node_id', 'run')}-{proof.get('proof_id', 'proof')}",
            )
    if not isinstance(continuity.get("bootstrap"), dict):
        continuity["bootstrap"] = {
            "mode": "fresh",
            "status": "ready",
            "surveyed_at": control.now(),
            "goal_confirmation_source": "handoff import",
            "plan_confirmation_source": "handoff import",
            "adopted_from_task_id": packet.get("task_id"),
            "superseded_control_ids": [],
        }
    initial_status = control.current_status(repo)
    receipt = {
        "schema_version": control.SCHEMA_VERSION,
        "state_revision": 0,
        "id": control.require_concrete("task id", str(packet.get("task_id", ""))),
        "status": "active",
        "tier": source_receipt.get("tier", "direct"),
        "task": control.require_concrete("task", str(source_receipt.get("task", ""))),
        "requirement_receipt": control.require_concrete(
            "requirement receipt", str(source_receipt.get("requirement_receipt", "handoff-import"))
        ),
        "confirmation_source": "handoff import",
        "project_context_id": source_receipt.get("project_context_id"),
        "primary_outcome_id": source_receipt.get("primary_outcome_id"),
        "intake_id": source_receipt.get("intake_id"),
        "acceptance": source_receipt.get("acceptance", []),
        "route_evidence": [],
        "planned_scope": source_receipt.get("planned_scope", []),
        "scope_amendments": source_receipt.get("scope_amendments", []),
        "validation_plan": source_receipt.get("validation_plan", []),
        "capabilities": source_receipt.get("capabilities", {"enabled": [], "skipped": {}, "evidence": {}}),
        "budgets": source_receipt.get("budgets", {}),
        "budget_usage": source_receipt.get("budget_usage", {}),
        "exhausted_budgets": [],
        "stop_conditions": [],
        "repo_root": str(repo),
        "base_head": packet.get("source", {}).get("head"),
        "base_branch": source_branch,
        "initial_status": initial_status,
        "worktree_baseline": control.capture_worktree_baseline(repo, initial_status),
        "snapshot": {"patch": None, "untracked": []},
        "started_at": control.now(),
        "continuity": continuity,
        "workspace_points": continuity.get("workspace_points", []),
        "workspace_checkpoint_protections": continuity.get("workspace_checkpoint_protections", []),
        "contract_snapshot": source_receipt.get("contract_snapshot"),
        "contract_parent_hash": source_receipt.get("contract_parent_hash"),
        "contract_status": source_receipt.get("contract_status"),
        "contract_coverage_ids": source_receipt.get("contract_coverage_ids", []),
        "events": [{
            "type": "handoff_imported",
            "at": control.now(),
            "source_repo_fingerprint": packet.get("source", {}).get("repo_fingerprint"),
            "source_state_revision": packet.get("source", {}).get("state_revision"),
        }],
    }
    dependency_registry = packet.get("dependency_registry", packet.get("project_memory"))
    if dependency_registry is not None:
        if (
            not isinstance(dependency_registry, dict)
            or dependency_registry.get("schema_version") not in {1, 2, 3, 4}
            or not isinstance(dependency_registry.get("entries"), list)
            or (
                dependency_registry.get("schema_version") in {2, 3, 4}
                and not isinstance(dependency_registry.get("attempts", []), list)
            )
        ):
            raise ValueError("handoff dependency registry is malformed")
    dependency_lease = packet.get("dependency_lease")
    if dependency_lease is not None:
        if not isinstance(dependency_lease, dict) or dependency_lease.get("schema_version") not in {1, 2}:
            raise ValueError("handoff dependency lease is malformed")
        if dependency_lease.get("schema_version") == 2 and (
            not isinstance(dependency_lease.get("leases"), list)
            or not all(isinstance(item, dict) for item in dependency_lease["leases"])
        ):
            raise ValueError("handoff dependency lease set is malformed")
    control.sync_budget_state(receipt)
    control.write_active(state, receipt)
    if dependency_registry is not None:
        control.write_json(state["project_memory"], dependency_registry)
    if dependency_lease is not None:
        control.write_json(state["dependency_lease"], dependency_lease)
    payload = control.build_status_payload(repo, state, view="compact")
    print(json.dumps({
        "status": "imported",
        "task_id": receipt["id"],
        "continuity_status": payload.get("continuity_status"),
        "state_revision": payload.get("state_revision"),
    }, ensure_ascii=False))
    return 0
