"""Rolling Milestone compilation, frontier, integration, and acceptance."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import pathlib
from typing import Any, Iterable

from auto_dev_internal.task.proof_contracts import (
    run_proof_preflights,
    validate_executable_contracts,
)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_object(file_value: str | None, json_value: str | None, *, label: str) -> dict[str, Any]:
    if bool(file_value) == bool(json_value):
        raise ValueError(f"provide exactly one of --{label}-file or --{label}-json")
    try:
        raw = (
            pathlib.Path(str(file_value)).expanduser().read_text(encoding="utf-8")
            if file_value
            else str(json_value)
        )
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _rolling_context(control, state: dict[str, pathlib.Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = control.require_working_task(state)
    continuity = control.continuity_from_receipt(receipt)
    if continuity is None or continuity.get("plan", {}).get("strategy") != "rolling_graph":
        raise ValueError("milestone commands require a rolling_graph continuity plan")
    return receipt, continuity


def _nodes(continuity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(node["id"]): node
        for node in continuity.get("plan", {}).get("nodes", [])
        if isinstance(node, dict) and node.get("id")
    }


def _milestone(nodes: dict[str, dict[str, Any]], milestone_id: str) -> dict[str, Any]:
    node = nodes.get(milestone_id)
    if node is None or node.get("node_role") != "milestone":
        raise ValueError(f"milestone does not exist: {milestone_id}")
    return node


def _children(nodes: dict[str, dict[str, Any]], milestone_id: str) -> list[dict[str, Any]]:
    return [node for node in nodes.values() if node.get("parent_id") == milestone_id]


def _accepted(node: dict[str, Any]) -> bool:
    return node.get("milestone_state", {}).get("review_result") == "accepted"


def _dependencies_satisfied(node: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> bool:
    return all(
        dependency in nodes
        and (
            _accepted(nodes[dependency])
            if nodes[dependency].get("node_role") == "milestone"
            else nodes[dependency].get("status") in {"done", "superseded"}
        )
        for dependency in node.get("depends_on", [])
    )


def _relation_pairs(continuity: dict[str, Any], kinds: set[str]) -> set[frozenset[str]]:
    return {
        frozenset((str(relation.get("from")), str(relation.get("to"))))
        for relation in continuity.get("plan", {}).get("relations", [])
        if isinstance(relation, dict) and relation.get("kind") in kinds
    }


def rolling_frontier_projection(
    control, continuity: dict[str, Any]
) -> dict[str, Any]:
    if continuity.get("plan", {}).get("strategy") != "rolling_graph":
        return {"strategy": "legacy", "milestones": [], "work_packets": []}
    nodes = _nodes(continuity)
    milestones = [node for node in nodes.values() if node.get("node_role") == "milestone"]
    milestone_frontier = [
        node["id"]
        for node in milestones
        if node.get("status") not in {"done", "superseded"}
        and _dependencies_satisfied(node, nodes)
        and node.get("milestone_state", {}).get("compilation_status")
        in {"thin", "recompile_required"}
    ]
    ready_packets: list[str] = []
    for milestone in milestones:
        state = milestone.get("milestone_state", {})
        if state.get("compilation_status") not in {
            "compiled", "integration_ready", "integrated",
        }:
            continue
        children = _children(nodes, milestone["id"])
        work_packets = [node for node in children if node.get("node_role") == "work_packet"]
        for node in children:
            if node.get("status") not in {"planned", "active"}:
                continue
            if not _dependencies_satisfied(node, nodes):
                continue
            if node.get("node_role") == "integration" and any(
                packet.get("status") not in {"done", "superseded"}
                for packet in work_packets
            ):
                continue
            ready_packets.append(node["id"])
    conflict_pairs = _relation_pairs(
        continuity, {"write_conflict", "resource_conflict", "uncertain"}
    )
    parallel_groups: list[list[str]] = []
    for packet_id in ready_packets:
        for group in parallel_groups:
            if all(frozenset((packet_id, other)) not in conflict_pairs for other in group):
                group.append(packet_id)
                break
        else:
            parallel_groups.append([packet_id])
    current = continuity.get("current_node")
    if current not in ready_packets:
        current = None
    current_parent = None
    if current in nodes:
        current_parent = nodes[current].get("parent_id")
    active_milestone_state = next(
        (
            node.get("milestone_state", {})
            for node in milestones
            if node.get("id") == current_parent or node.get("id") in milestone_frontier
        ),
        {},
    )
    if not active_milestone_state:
        active_milestone_state = next(
            (
                node.get("milestone_state", {})
                for node in milestones
                if node.get("milestone_state", {}).get("compilation_status")
                in {"compiled", "integration_ready", "integrated"}
            ),
            {},
        )
    compilation_policy = active_milestone_state.get("compilation_policy", {})
    execution_decision = active_milestone_state.get("execution_decision")
    decision_status = execution_decision.get("status") if isinstance(execution_decision, dict) else "pending"
    selected_mode = execution_decision.get("selected_mode") if isinstance(execution_decision, dict) else None
    decision_current = (
        bool(execution_decision)
        and execution_decision.get("compilation_revision") == active_milestone_state.get("compilation_revision")
        and execution_decision.get("packet_contracts_sha256") == active_milestone_state.get("compilation_snapshot", {}).get("packet_contracts_sha256")
    )
    dispatch_status = (
        "contract_revalidation_required" if not decision_current
        else "confirmation_required" if decision_status == "pending"
        else "handoff_required" if decision_status == "awaiting_main"
        else selected_mode or compilation_policy.get("dispatch_status", "single_agent")
    )
    next_execution = current or (ready_packets[0] if ready_packets else None)
    if not decision_current or decision_status in {"pending", "awaiting_main", "stale"}:
        next_execution = None
    if (
        execution_decision
        and execution_decision.get("boundary") == "before_integration"
        and execution_decision.get("selected_mode") != "main_session"
        and execution_decision.get("owner") != "main_session"
        and next_execution
    ):
        next_node = nodes.get(next_execution)
        if next_node and next_node.get("node_role") == "integration":
            next_execution = None
    return {
        "strategy": "rolling_graph",
        "milestones": milestone_frontier,
        "work_packets": ready_packets,
        "parallel_groups": parallel_groups,
        "phase1_execution_mode": "serial",
        "execution_topology": compilation_policy.get("execution_topology", "single_agent"),
        "dispatch_status": dispatch_status,
        "execution_mode": selected_mode,
        "execution_decision": execution_decision,
        "compilation_focus": continuity.get("compilation_focus"),
        "execution_focus": current or continuity.get("execution_focus"),
        "next_execution": next_execution,
    }


def refresh_rolling_frontier(control, continuity: dict[str, Any]) -> dict[str, Any]:
    frontier = rolling_frontier_projection(control, continuity)
    continuity["ready_frontier"] = {
        "milestones": frontier.get("milestones", []),
        "work_packets": frontier.get("work_packets", []),
        "parallel_groups": frontier.get("parallel_groups", []),
        "execution_decision": frontier.get("execution_decision"),
        "execution_mode": frontier.get("execution_mode"),
        "dispatch_status": frontier.get("dispatch_status"),
        "updated_at": control.now(),
    }
    return frontier


def _repo_facts(control, repo: pathlib.Path, scopes: Iterable[str]) -> dict[str, Any]:
    product_status = control.workspace_product_status(control.current_status(repo))
    status_paths = sorted({control.status_path(line) for line in product_status})
    codegraph: dict[str, Any]
    try:
        codegraph = {"status": "ready", **control.codegraph_status_snapshot(repo)}
    except ValueError as error:
        codegraph = {
            "status": "unavailable",
            "reason": str(error),
            "index_fingerprint": control.codegraph_index_fingerprint(repo),
        }
    scope_list = sorted(set(scopes))
    return {
        "captured_at": control.now(),
        "head": control.git_head(repo),
        "product_status": product_status,
        "product_status_sha256": _digest(product_status),
        "product_status_fingerprints": {
            path: _scope_fingerprint(control, repo, path) for path in status_paths
        },
        "scope": scope_list,
        "scope_sha256": control.workspace_scope_digest(repo, scope_list),
        "codegraph": codegraph,
    }


def _facts_digest(facts: dict[str, Any]) -> str:
    return _digest({key: value for key, value in facts.items() if key != "captured_at"})


def _scope_fingerprint(control, repo: pathlib.Path, scope: str) -> str:
    return _digest(control.local_scope_manifest(repo, [scope]))


def _normalize_compilation_policy(control, payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("policy")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("packet compilation policy must be an object")
    allowed = {
        "execution_topology", "merge_mode", "verification_floor",
        "integration_required", "review_budget", "conflict_owner",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError("packet compilation policy has unsupported fields: " + ", ".join(unknown))
    topology = str(raw.get("execution_topology", "single_agent"))
    if topology not in control.EXECUTION_TOPOLOGIES:
        raise ValueError(
            "packet compilation policy execution_topology must be one of: "
            + ", ".join(sorted(control.EXECUTION_TOPOLOGIES))
        )
    merge_mode = str(raw.get("merge_mode", "accumulated_workspace"))
    if merge_mode not in control.PACKET_MERGE_MODES:
        raise ValueError(
            "packet compilation policy merge_mode must be one of: "
            + ", ".join(sorted(control.PACKET_MERGE_MODES))
        )
    if topology == "single_agent" and merge_mode == "worktree_merge_queue":
        raise ValueError("worktree_merge_queue requires execution_topology=multi_agent")
    integration_required = bool(raw.get("integration_required", True))
    if not integration_required:
        raise ValueError("rolling_graph compilation requires integration_required=true")
    verification_floor = raw.get("verification_floor", ["packet_proof"])
    if isinstance(verification_floor, str):
        verification_floor = [verification_floor]
    if not isinstance(verification_floor, list):
        raise ValueError("packet compilation policy verification_floor must be an array")
    verification_floor = control.require_concrete_list(
        "verification floor", verification_floor
    ) if verification_floor else []
    review_budget = raw.get("review_budget", 1)
    if not isinstance(review_budget, int) or review_budget < 0:
        raise ValueError("packet compilation policy review_budget must be a non-negative integer")
    conflict_owner = str(raw.get("conflict_owner", "main"))
    if conflict_owner not in control.PACKET_CONFLICT_OWNERS:
        raise ValueError(
            "packet compilation policy conflict_owner must be one of: "
            + ", ".join(sorted(control.PACKET_CONFLICT_OWNERS))
        )
    return {
        "execution_topology": topology,
        "merge_mode": merge_mode,
        "verification_floor": verification_floor,
        "integration_required": integration_required,
        "review_budget": review_budget,
        "conflict_owner": conflict_owner,
        "dispatch_status": "planned" if topology == "multi_agent" else "single_agent",
    }


def _derive_packet_waves(nodes: list[dict[str, Any]], milestone_id: str) -> None:
    by_id = {node["id"]: node for node in nodes}
    packets = [
        node for node in nodes
        if node.get("parent_id") == milestone_id and node.get("node_role") == "work_packet"
    ]
    visiting: set[str] = set()

    def wave(node_id: str) -> int:
        node = by_id[node_id]
        if node.get("integration_wave") is not None:
            return int(node["integration_wave"])
        if node_id in visiting:
            raise ValueError(f"packet dependency cycle while deriving integration wave: {node_id}")
        visiting.add(node_id)
        dependencies = [
            dependency for dependency in node.get("depends_on", [])
            if dependency in by_id and by_id[dependency].get("node_role") == "work_packet"
        ]
        result = 1 + max((wave(dependency) for dependency in dependencies), default=0)
        visiting.remove(node_id)
        node["integration_wave"] = result
        return result

    for packet in packets:
        wave(packet["id"])


def _path_overlap(left: str, right: str) -> bool:
    a = left.strip().strip("/")
    b = right.strip().strip("/")
    if not a or not b:
        return False
    if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
        return True
    return fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a)


def _dependency_reaches(
    nodes: dict[str, dict[str, Any]], source: str, target: str, seen: set[str] | None = None
) -> bool:
    if source == target:
        return True
    seen = set() if seen is None else seen
    if source in seen or source not in nodes:
        return False
    seen.add(source)
    return any(
        dependency == target or _dependency_reaches(nodes, dependency, target, seen)
        for dependency in nodes[source].get("depends_on", [])
    )


def _ordered_pair(
    nodes: dict[str, dict[str, Any]], left: str, right: str
) -> tuple[str, str] | None:
    if _dependency_reaches(nodes, left, right):
        return (right, left)
    if _dependency_reaches(nodes, right, left):
        return (left, right)
    return None


def compile_relations(
    control,
    nodes: list[dict[str, Any]],
    declared: list[dict[str, Any]],
    *,
    milestone_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_id = {node["id"]: node for node in nodes}
    packets = [
        node for node in nodes
        if node.get("parent_id") == milestone_id
        and node.get("node_role") == "work_packet"
        and node.get("status") != "superseded"
    ]
    relations = list(declared)
    unresolved: list[dict[str, Any]] = []
    detected: list[dict[str, Any]] = []

    def add_relation(source: str, target: str, kind: str, evidence: list[str]) -> None:
        record = {"from": source, "to": target, "kind": kind, "evidence": evidence}
        key = (source, target, kind)
        if key not in {
            (item.get("from"), item.get("to"), item.get("kind")) for item in relations
        }:
            relations.append(record)
        detected.append(record)

    for index, left in enumerate(packets):
        for right in packets[index + 1:]:
            overlap = sorted({
                f"path:{a}<->{b}"
                for a in left.get("write_scope", [])
                for b in right.get("write_scope", [])
                if _path_overlap(a, b)
            })
            shared_owns = sorted(set(left.get("owns", [])) & set(right.get("owns", [])))
            shared_claims = sorted(
                set(left.get("exclusive_claims", [])) & set(right.get("exclusive_claims", []))
            )
            if overlap or shared_owns or shared_claims:
                ordered = _ordered_pair(by_id, left["id"], right["id"])
                evidence = overlap + [f"owns:{value}" for value in shared_owns]
                evidence += [f"exclusive:{value}" for value in shared_claims]
                if ordered is None:
                    unresolved.append({
                        "kind": "unordered_write_conflict",
                        "nodes": [left["id"], right["id"]],
                        "evidence": evidence,
                    })
                else:
                    add_relation(ordered[0], ordered[1], "write_conflict", evidence)
    children = [
        node for node in nodes
        if node.get("parent_id") == milestone_id and node.get("status") != "superseded"
    ]
    providers: dict[str, list[str]] = {}
    for child in children:
        for contract in child.get("provides", []):
            providers.setdefault(contract, []).append(child["id"])
    for consumer in children:
        for contract in consumer.get("consumes", []):
            candidates = providers.get(contract, [])
            if not candidates:
                unresolved.append({
                    "kind": "missing_contract_provider",
                    "node": consumer["id"],
                    "contract": contract,
                })
                continue
            if len(candidates) > 1:
                unresolved.append({
                    "kind": "ambiguous_contract_provider",
                    "node": consumer["id"],
                    "contract": contract,
                    "providers": candidates,
                })
                continue
            provider = candidates[0]
            if not _dependency_reaches(by_id, consumer["id"], provider):
                unresolved.append({
                    "kind": "unordered_contract_dependency",
                    "provider": provider,
                    "consumer": consumer["id"],
                    "contract": contract,
                })
            else:
                add_relation(
                    provider, consumer["id"], "contract_dependency", [f"contract:{contract}"]
                )
    relations.sort(key=lambda item: (str(item.get("from")), str(item.get("to")), str(item.get("kind"))))
    return relations, {
        "status": "blocked" if unresolved else "ready",
        "detected": detected,
        "unresolved": unresolved,
        "parallel_eligible": not unresolved,
    }


def milestone_projection(
    control, repo: pathlib.Path, continuity: dict[str, Any], milestone_id: str
) -> dict[str, Any]:
    nodes = _nodes(continuity)
    milestone = _milestone(nodes, milestone_id)
    children = _children(nodes, milestone_id)
    return {
        "id": milestone_id,
        "display_code": milestone.get("display_code"),
        "title": milestone.get("title"),
        "status": milestone.get("status"),
        "depends_on": milestone.get("depends_on", []),
        "dependencies_accepted": _dependencies_satisfied(milestone, nodes),
        "state": milestone.get("milestone_state", {}),
        "compilation_policy": milestone.get("milestone_state", {}).get("compilation_policy", {}),
        "work_packets": [node for node in children if node.get("node_role") == "work_packet"],
        "integration": next(
            (node for node in children if node.get("node_role") == "integration"), None
        ),
        "exit_snapshot": next(
            (
                snapshot for snapshot in continuity.get("exit_snapshots", [])
                if snapshot.get("milestone_id") == milestone_id
            ),
            None,
        ),
    }


def command_milestone_frontier(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    _, continuity = _rolling_context(control, control.paths(repo))
    print(json.dumps(rolling_frontier_projection(control, continuity), ensure_ascii=False))
    return 0


def command_milestone_compile_inspect(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    receipt, continuity = _rolling_context(control, control.paths(repo))
    milestone_id = control.require_continuity_id("milestone id", args.milestone)
    nodes = _nodes(continuity)
    milestone = _milestone(nodes, milestone_id)
    frontier = rolling_frontier_projection(control, continuity)
    ready = (
        milestone_id in frontier["milestones"]
        and continuity.get("compilation_focus") == milestone_id
    )
    dependency_snapshots = [
        snapshot
        for snapshot in continuity.get("exit_snapshots", [])
        if snapshot.get("milestone_id") in milestone.get("depends_on", [])
    ]
    facts = _repo_facts(control, repo, receipt.get("planned_scope", []))
    facts_sha256 = _facts_digest(facts)
    print(json.dumps({
        "status": "ready" if ready else "blocked",
        "milestone": milestone_projection(control, repo, continuity, milestone_id),
        "frontier": frontier,
        "repository_facts": facts,
        "repository_facts_sha256": facts_sha256,
        "dependency_exit_snapshots": dependency_snapshots,
        "compiler_contract": {
            "strategy": "rolling_graph",
            "integration_mode": "accumulated_workspace",
            "requires_one_integration_node": True,
            "unordered_overlapping_write_scopes": "rejected",
            "proof_recipes": "required",
            "blocking_assertions": "must reference declared proofs",
            "policy_timing": "packet-compiled",
            "packet_policies": [
                "execution_profile", "required_capabilities", "verification_policy",
                "review_policy", "merge_policy", "model_profile",
            ],
        },
        "plan_revision": continuity["plan"].get("revision", 0),
        "state_revision": receipt.get("state_revision", 0),
    }, ensure_ascii=False))
    return 0 if ready else 2


def _activate_execution_head(
    control, continuity: dict[str, Any], *, activate_all_ready_packets: bool = False
) -> str | None:
    frontier = rolling_frontier_projection(control, continuity)
    next_node = frontier.get("next_execution")
    if not next_node:
        return None
    nodes = _nodes(continuity)
    if activate_all_ready_packets:
        for node_id in frontier.get("work_packets", []):
            node = nodes.get(str(node_id))
            if node is None or node.get("node_role") != "work_packet":
                continue
            if node.get("status") == "planned":
                node["status"] = "active"
                node["activated_at"] = control.now()
    node = nodes.get(str(next_node))
    if node is None:
        return None
    if node.get("status") == "planned":
        node["status"] = "active"
        node["activated_at"] = control.now()
    continuity["current_node"] = next_node
    continuity["execution_focus"] = next_node
    return str(next_node)


def command_milestone_execution_inspect(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    receipt, continuity = _rolling_context(control, control.paths(repo))
    milestone_id = control.require_continuity_id("milestone id", args.milestone)
    nodes = _nodes(continuity)
    milestone = _milestone(nodes, milestone_id)
    state = milestone.get("milestone_state", {})
    decision = state.get("execution_decision")
    if not isinstance(decision, dict):
        print(json.dumps({
            "status": "policy_revalidation_required",
            "milestone_id": milestone_id,
            "reason": "compiled milestone has no current execution decision",
            "plan_revision": continuity["plan"].get("revision", 0),
            "state_revision": receipt.get("state_revision", 0),
        }, ensure_ascii=False))
        return 2
    current = control.decision_is_current(milestone)
    result = {
        "status": decision.get("status") if current else "stale",
        "milestone_id": milestone_id,
        "execution_decision": decision,
        "current": current,
        "compilation_policy": state.get("compilation_policy", {}),
        "frontier": rolling_frontier_projection(control, continuity),
        "plan_revision": continuity["plan"].get("revision", 0),
        "state_revision": receipt.get("state_revision", 0),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if current else 2


def command_milestone_execution_select(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt, continuity = _rolling_context(control, state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    plan_revision = int(continuity["plan"].get("revision", 0))
    if args.state_revision != loaded_state_revision or args.plan_revision != plan_revision:
        raise ValueError("execution selection revision conflict; inspect current milestone state")
    milestone_id = control.require_continuity_id("milestone id", args.milestone)
    nodes = _nodes(continuity)
    milestone = _milestone(nodes, milestone_id)
    state_value = milestone.get("milestone_state", {})
    if state_value.get("compilation_status") not in {"compiled", "integration_ready"}:
        raise ValueError("execution selection requires a compiled milestone")
    if not control.decision_is_current(milestone):
        raise ValueError("execution decision is stale or missing; recompile or revalidate the milestone")
    policy = state_value.get("compilation_policy", {})
    mode = str(args.mode)
    if mode == "multi_worker":
        if policy.get("execution_topology") != "multi_agent":
            raise ValueError("multi_worker execution requires execution_topology=multi_agent")
        if policy.get("merge_mode") != "worktree_merge_queue":
            raise ValueError("multi_worker execution requires merge_mode=worktree_merge_queue")
        if "parallel-work" not in receipt.get("capabilities", {}).get("enabled", []):
            raise ValueError("multi_worker execution requires the root parallel-work capability")
    selected = control.select_decision(
        milestone,
        mode=mode,
        confirmation_source=control.require_concrete(
            "execution selection confirmation source", args.confirmation_source
        ),
        worker_profile=getattr(args, "worker_profile", None),
        worker_executor={
            "provider": str(getattr(args, "worker_provider", None) or ""),
            "model": str(getattr(args, "worker_model", None) or ""),
            "reasoning": str(getattr(args, "worker_reasoning", None) or ""),
        },
    )
    if args.boundary:
        selected["boundary"] = args.boundary
    state_value["execution_decision"] = selected
    continuity["current_node"] = None
    continuity["execution_focus"] = None
    next_node = _activate_execution_head(
        control,
        continuity,
        activate_all_ready_packets=mode == "multi_worker",
    )
    continuity["next_action"] = (
        f"Execute work packet {next_node}" if next_node
        else "Take the Main control-plane handoff before Integration"
    )
    continuity["updated_at"] = control.now()
    control.continuity_event(
        receipt,
        "milestone_execution_selected",
        milestone_id=milestone_id,
        mode=mode,
        boundary=selected.get("boundary"),
        confirmation_source=selected.get("confirmation_source"),
    )
    frontier = refresh_rolling_frontier(control, continuity)
    next_revision = control.write_active(state, receipt, expected_revision=loaded_state_revision)
    print(json.dumps({
        "status": "selected",
        "milestone_id": milestone_id,
        "execution_decision": selected,
        "current_node": continuity.get("current_node"),
        "frontier": frontier,
        "state_revision": next_revision,
        "plan_revision": plan_revision,
    }, ensure_ascii=False))
    return 0


def command_milestone_handoff_take(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt, continuity = _rolling_context(control, state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    plan_revision = int(continuity["plan"].get("revision", 0))
    if args.state_revision != loaded_state_revision or args.plan_revision != plan_revision:
        raise ValueError("milestone handoff revision conflict; inspect current milestone state")
    milestone_id = control.require_continuity_id("milestone id", args.milestone)
    nodes = _nodes(continuity)
    milestone = _milestone(nodes, milestone_id)
    decision = milestone.get("milestone_state", {}).get("execution_decision")
    if not isinstance(decision, dict) or not control.decision_is_current(milestone):
        raise ValueError("milestone handoff requires a current execution decision")
    if decision.get("status") != "awaiting_main":
        raise ValueError("milestone handoff is not awaiting the main session")
    unfinished = [
        node["id"] for node in _children(nodes, milestone_id)
        if node.get("node_role") == "work_packet"
        and node.get("status") not in {"done", "superseded"}
    ]
    if unfinished:
        raise ValueError("milestone handoff cannot be taken before all work packets finish")
    decision.update({
        "status": "selected",
        "owner": "main_session",
        "handoff_status": "taken",
        "handoff_taken_at": control.now(),
        "handoff_confirmation_source": control.require_concrete(
            "milestone handoff confirmation source", args.confirmation_source
        ),
    })
    next_node = _activate_execution_head(control, continuity)
    if next_node is None or nodes.get(next_node, {}).get("node_role") != "integration":
        raise ValueError("milestone handoff did not resolve an integration node")
    continuity["next_action"] = f"Execute Integration node {next_node}"
    continuity["updated_at"] = control.now()
    control.continuity_event(
        receipt,
        "milestone_handoff_taken",
        milestone_id=milestone_id,
        integration_node=next_node,
        selected_mode=decision.get("selected_mode"),
    )
    frontier = refresh_rolling_frontier(control, continuity)
    next_revision = control.write_active(state, receipt, expected_revision=loaded_state_revision)
    print(json.dumps({
        "status": "taken",
        "milestone_id": milestone_id,
        "execution_decision": decision,
        "current_node": next_node,
        "frontier": frontier,
        "plan_revision": plan_revision,
        "state_revision": next_revision,
    }, ensure_ascii=False))
    return 0


def command_milestone_execution_revalidate(control, args: argparse.Namespace) -> int:
    """Upgrade one unfinished compiled Milestone's execution envelope in place."""
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt, continuity = _rolling_context(control, state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    plan_revision = int(continuity["plan"].get("revision", 0))
    if args.state_revision != loaded_state_revision or args.plan_revision != plan_revision:
        raise ValueError("execution revalidation revision conflict; inspect current milestone state")
    milestone_id = control.require_continuity_id("milestone id", args.milestone)
    nodes = _nodes(continuity)
    milestone = _milestone(nodes, milestone_id)
    milestone_state = milestone.get("milestone_state", {})
    if milestone_state.get("compilation_status") not in {"compiled", "integration_ready", "integrated"}:
        raise ValueError("execution revalidation requires a compiled milestone")
    snapshot = milestone_state.get("compilation_snapshot", {})
    facts = _repo_facts(control, repo, receipt.get("planned_scope", []))
    compiled_head = snapshot.get("head")
    if compiled_head and compiled_head != facts.get("head"):
        raise ValueError("compiled milestone repository HEAD drifted; recompile from fresh facts")
    children = [
        node for node in nodes.values()
        if node.get("parent_id") == milestone_id and node.get("status") != "superseded"
    ]
    validate_executable_contracts(control, receipt, list(nodes.values()), milestone_id)
    missing: dict[str, list[str]] = {}
    for node in children:
        required = {"target", "write_scope", "owns", "assertions", "escalation", "outcome"}
        absent = sorted(field for field in required if node.get(field) in (None, [], ""))
        if absent:
            missing[str(node.get("id"))] = absent
    if missing:
        raise ValueError("compiled milestone cannot be revalidated; incomplete contracts: " + json.dumps(missing, ensure_ascii=False))
    packet_ids = [
        str(node.get("id")) for node in children if node.get("node_role") == "work_packet"
    ]
    changed = False
    for node in children:
        role = node.get("node_role")
        if role not in {"work_packet", "integration"}:
            continue
        if role == "work_packet":
            node.setdefault("execution_profile", "bounded")
            node.setdefault("required_capabilities", [])
            node.setdefault("verification_policy", {"required": [], "post_merge": [], "blocking": True})
            node.setdefault("review_policy", "proof_only")
            node.setdefault("merge_policy", {
                "mode": "accumulated_workspace",
                "conflict_owner": "main",
                "pre_merge": True,
            })
        else:
            node.setdefault("execution_profile", "governed")
            node.setdefault("required_capabilities", [])
            node.setdefault("verification_policy", {"required": [], "post_merge": [], "blocking": True})
            node.setdefault("review_policy", "full")
            node.setdefault("merge_policy", {
                "mode": "accumulated_workspace",
                "conflict_owner": "main",
                "pre_merge": False,
            })
        if node.get("status") not in {"done", "superseded"} and not isinstance(node.get("execution_base"), dict):
            node["execution_base"] = {
                "milestone_id": milestone_id,
                "compilation_revision": milestone_state.get("compilation_revision", 0),
                "head": facts["head"],
                "product_status_sha256": facts["product_status_sha256"],
                "codegraph_index_fingerprint": facts["codegraph"].get("index_fingerprint"),
                "rework_revision": 0,
            }
        if not node.get("contract_sha256"):
            node["contract_sha256"] = control.node_contract_digest(node)
        changed = True
    packet_contracts_sha256 = _digest({
        node_id: nodes[node_id].get("contract_sha256") or control.node_contract_digest(nodes[node_id])
        for node_id in sorted(packet_ids)
    })
    snapshot["packet_contracts_sha256"] = packet_contracts_sha256
    milestone_state["compilation_snapshot"] = snapshot
    milestone_state["execution_decision"] = control.build_pending_decision(
        {"id": milestone_id, "milestone_state": milestone_state},
        compilation_revision=int(milestone_state.get("compilation_revision", 0)),
        packet_contracts_sha256=packet_contracts_sha256,
        packet_list=sorted(packet_ids),
    )
    continuity["plan"]["revision"] = plan_revision + 1
    continuity["plan"]["updated_at"] = control.now()
    continuity["current_node"] = None
    continuity["execution_focus"] = None
    continuity["next_action"] = "Select an execution mode for the revalidated milestone"
    refresh_rolling_frontier(control, continuity)
    control.continuity_event(
        receipt,
        "milestone_execution_revalidated",
        milestone_id=milestone_id,
        compilation_revision=milestone_state.get("compilation_revision"),
        packet_contracts_sha256=packet_contracts_sha256,
        changed=changed,
    )
    next_revision = control.write_active(state, receipt, expected_revision=loaded_state_revision)
    print(json.dumps({
        "status": "revalidated",
        "milestone_id": milestone_id,
        "execution_decision": milestone_state["execution_decision"],
        "plan_revision": continuity["plan"]["revision"],
        "state_revision": next_revision,
    }, ensure_ascii=False))
    return 0


def command_milestone_compile_apply(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt, continuity = _rolling_context(control, state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    plan_revision = int(continuity["plan"].get("revision", 0))
    if args.state_revision != loaded_state_revision:
        raise ValueError(
            f"state revision conflict: expected {loaded_state_revision}, received {args.state_revision}"
        )
    if args.plan_revision != plan_revision:
        raise ValueError(
            f"plan revision conflict: expected {plan_revision}, received {args.plan_revision}"
        )
    milestone_id = control.require_continuity_id("milestone id", args.milestone)
    old_nodes = _nodes(continuity)
    milestone = _milestone(old_nodes, milestone_id)
    frontier = rolling_frontier_projection(control, continuity)
    if milestone_id not in frontier["milestones"]:
        raise ValueError(f"milestone is not ready for compilation: {milestone_id}")
    if continuity.get("compilation_focus") != milestone_id:
        raise ValueError(
            f"milestone is not the current compilation_focus: {milestone_id}"
        )
    inspection_facts = _repo_facts(control, repo, receipt.get("planned_scope", []))
    inspection_facts_sha256 = _facts_digest(inspection_facts)
    if args.expected_facts_sha256 != inspection_facts_sha256:
        raise ValueError(
            "milestone compiler facts are stale; run milestone compile inspect again"
        )
    payload = _load_object(args.packet_file, args.packet_json, label="packet")
    allowed = {"nodes", "relations", "next_action", "compiler_notes", "policy"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError("packet compilation has unsupported fields: " + ", ".join(unknown))
    compilation_policy = _normalize_compilation_policy(control, payload)
    if (
        compilation_policy["execution_topology"] == "multi_agent"
        and "parallel-work" not in receipt.get("capabilities", {}).get("enabled", [])
    ):
        raise ValueError(
            "multi_agent execution requires the root parallel-work capability"
        )
    raw_packets = payload.get("nodes")
    if not isinstance(raw_packets, list) or not raw_packets:
        raise ValueError("packet compilation requires a non-empty nodes array")
    packet_ids: set[str] = set()
    prepared_packets: list[dict[str, Any]] = []
    for raw in raw_packets:
        if not isinstance(raw, dict):
            raise ValueError("compiled packet node must be an object")
        prepared = dict(raw)
        packet_id = control.require_continuity_id("packet id", str(prepared.get("id", "")))
        if packet_id in packet_ids or packet_id in {
            node_id for node_id, node in old_nodes.items()
            if node.get("parent_id") != milestone_id
        }:
            raise ValueError(f"compiled packet id is duplicated or owned elsewhere: {packet_id}")
        packet_ids.add(packet_id)
        prepared["parent_id"] = milestone_id
        prepared.setdefault("status", old_nodes.get(packet_id, {}).get("status", "planned"))
        prepared_packets.append(prepared)
    integration_ids = [
        str(node.get("id")) for node in prepared_packets if node.get("node_role") == "integration"
    ]
    if len(integration_ids) != 1:
        raise ValueError("packet compilation requires exactly one integration node")
    work_packet_ids = {
        str(node.get("id")) for node in prepared_packets if node.get("node_role") == "work_packet"
    }
    if not work_packet_ids:
        raise ValueError("packet compilation requires at least one work_packet")
    integration_raw = next(node for node in prepared_packets if node["id"] == integration_ids[0])
    if not work_packet_ids.issubset(set(integration_raw.get("depends_on", []))):
        raise ValueError("integration node must depend on every work_packet in the milestone")

    retained: list[dict[str, Any]] = []
    for node in continuity["plan"]["nodes"]:
        if node.get("parent_id") != milestone_id:
            retained.append(dict(node))
        elif node.get("id") not in packet_ids:
            superseded = dict(node)
            superseded["status"] = "superseded"
            retained.append(superseded)
    raw_nodes = retained + prepared_packets
    normalized = control.validate_plan_nodes(raw_nodes, old_nodes)
    normalized, numbering_changes = control.normalize_plan_numbering(normalized)
    enabled_capabilities = set(receipt.get("capabilities", {}).get("enabled", []))
    missing_packet_capabilities = [
        {
            "node_id": node["id"],
            "missing": sorted(set(node.get("required_capabilities", [])) - enabled_capabilities),
        }
        for node in normalized
        if node.get("parent_id") == milestone_id
        and node.get("node_role") in {"work_packet", "integration"}
        and set(node.get("required_capabilities", [])) - enabled_capabilities
    ]
    if missing_packet_capabilities:
        raise ValueError(
            "compiled packets require Root capabilities that are not enabled: "
            + json.dumps(missing_packet_capabilities, ensure_ascii=False)
        )
    control.validate_contract_plan(receipt, normalized)
    replaced_child_ids = {
        node_id for node_id, node in old_nodes.items() if node.get("parent_id") == milestone_id
    }
    preserved_relations = [
        relation
        for relation in continuity["plan"].get("relations", [])
        if relation.get("from") not in replaced_child_ids
        and relation.get("to") not in replaced_child_ids
    ]
    declared_relations = control.validate_rolling_plan(
        normalized,
        strategy="rolling_graph",
        relations=[*preserved_relations, *payload.get("relations", [])],
    )
    validate_executable_contracts(control, receipt, normalized, milestone_id)
    run_proof_preflights(control, repo, normalized, milestone_id)
    relations, conflict_report = compile_relations(
        control, normalized, declared_relations, milestone_id=milestone_id
    )
    if conflict_report["unresolved"]:
        raise ValueError(
            "packet compilation has unresolved conflicts: "
            + json.dumps(conflict_report["unresolved"], ensure_ascii=False)
        )
    by_id = {node["id"]: node for node in normalized}
    _derive_packet_waves(normalized, milestone_id)
    for node in normalized:
        if node.get("parent_id") == milestone_id and node.get("node_role") == "work_packet":
            node["contract_sha256"] = control.node_contract_digest(node)
    changed_contract_ids = {
        node_id
        for node_id in packet_ids
        if node_id in old_nodes
        and old_nodes[node_id].get("contract_sha256") != by_id[node_id].get("contract_sha256")
    }
    integration_id = integration_ids[0]
    local_ids = {milestone_id, *packet_ids}
    previous_local_relations = [
        relation for relation in continuity["plan"].get("relations", [])
        if relation.get("from") in local_ids or relation.get("to") in local_ids
    ]
    current_local_relations = [
        relation for relation in relations
        if relation.get("from") in local_ids or relation.get("to") in local_ids
    ]
    if _digest(previous_local_relations) != _digest(current_local_relations):
        changed_contract_ids.add(integration_id)
    if changed_contract_ids:
        changed_contract_ids.add(integration_id)
    for node_id in changed_contract_ids:
        node = by_id[node_id]
        if node.get("result_ref"):
            node.setdefault("result_history", []).append(node["result_ref"])
        node.pop("result_ref", None)
        node["status"] = "planned"
    child_scopes = sorted({
        scope
        for node in by_id.values()
        if node.get("parent_id") == milestone_id and node.get("status") != "superseded"
        for scope in node.get("write_scope", [])
    })
    milestone_coverage = set(by_id[milestone_id].get("coverage_ids", []))
    child_coverage = {
        coverage_id
        for node in by_id.values()
        if node.get("parent_id") == milestone_id and node.get("status") != "superseded"
        for coverage_id in node.get("coverage_ids", [])
    }
    missing_coverage = sorted(milestone_coverage - child_coverage)
    if missing_coverage:
        raise ValueError(
            "compiled work packets do not own all milestone coverage: "
            + ", ".join(missing_coverage)
        )
    facts = _repo_facts(control, repo, child_scopes)
    milestone = by_id[milestone_id]
    previous_state = milestone.get("milestone_state", {})
    compilation_revision = int(previous_state.get("compilation_revision", 0)) + 1
    snapshot = {
        **facts,
        "milestone_id": milestone_id,
        "compilation_revision": compilation_revision,
        "base_plan_revision": plan_revision,
        "inspection_facts_sha256": inspection_facts_sha256,
        "packet_contracts_sha256": _digest({
            node_id: by_id[node_id].get("contract_sha256") for node_id in sorted(packet_ids)
        }),
        "conflict_report": conflict_report,
        "compilation_policy": compilation_policy,
        "dependency_exit_snapshot_ids": [
            snapshot.get("id")
            for snapshot in continuity.get("exit_snapshots", [])
            if snapshot.get("milestone_id") in milestone.get("depends_on", [])
        ],
    }
    execution_decision = control.build_pending_decision(
        {"id": milestone_id, "milestone_state": {"compilation_policy": compilation_policy}},
        compilation_revision=compilation_revision,
        packet_contracts_sha256=snapshot["packet_contracts_sha256"],
        packet_list=sorted(work_packet_ids),
    )
    milestone["milestone_state"] = {
        **previous_state,
        "compilation_status": "compiled",
        "compilation_revision": compilation_revision,
        "compiled_at": facts["captured_at"],
        "compilation_snapshot": snapshot,
        "integration_mode": compilation_policy["merge_mode"],
        "execution_topology": compilation_policy["execution_topology"],
        "merge_mode": compilation_policy["merge_mode"],
        "compilation_policy": compilation_policy,
        "integration_status": "not_ready",
        "review_result": None,
        "exit_snapshot_id": None,
        "execution_decision": execution_decision,
    }
    for node in by_id.values():
        if node.get("parent_id") != milestone_id or node.get("status") == "superseded":
            continue
        if not (
            node.get("status") == "done"
            and node["id"] not in changed_contract_ids
            and isinstance(node.get("execution_base"), dict)
        ):
            node["execution_base"] = {
                "milestone_id": milestone_id,
                "compilation_revision": compilation_revision,
                "head": facts["head"],
                "product_status_sha256": facts["product_status_sha256"],
                "codegraph_index_fingerprint": facts["codegraph"].get("index_fingerprint"),
                "rework_revision": 0,
            }
    plan = continuity["plan"]
    plan["nodes"] = normalized
    plan["relations"] = relations
    plan["revision"] = plan_revision + 1
    plan["reason"] = control.require_concrete("compilation reason", args.reason)
    plan["graph_sha256"] = control.plan_graph_digest(normalized, relations)
    plan["updated_at"] = control.now()
    continuity["compilation_focus"] = None
    continuity["current_node"] = None
    continuity["execution_focus"] = None
    frontier = refresh_rolling_frontier(control, continuity)
    continuity["next_action"] = control.require_concrete(
        "next action",
        str(payload.get("next_action") or "Select an execution mode for the compiled milestone"),
    )
    continuity["updated_at"] = control.now()
    control.continuity_event(
        receipt,
        "milestone_compiled",
        milestone_id=milestone_id,
        compilation_revision=compilation_revision,
        packet_ids=sorted(packet_ids),
        graph_sha256=plan["graph_sha256"],
    )
    next_state_revision = control.write_active(
        state, receipt, expected_revision=loaded_state_revision
    )
    print(json.dumps({
        "status": "compiled",
        "milestone_id": milestone_id,
        "compilation_revision": compilation_revision,
        "plan_revision": plan["revision"],
        "state_revision": next_state_revision,
        "current_node": continuity.get("current_node"),
        "execution_decision": execution_decision,
        "frontier": frontier,
        "relations": relations,
        "conflict_report": conflict_report,
        "compilation_policy": compilation_policy,
        "repository_facts": facts,
        "numbering_changes": numbering_changes,
    }, ensure_ascii=False))
    return 0


def _latest_proof_state(
    control,
    repo: pathlib.Path,
    continuity: dict[str, Any],
    node: dict[str, Any],
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    stale: list[str] = []
    outcome = node.get("outcome") or {}
    for proof_spec in outcome.get("proofs", []):
        proof_id = str(proof_spec.get("id"))
        proof = control.latest_proof(
            continuity.get("proofs", []), node_id=node["id"], proof_id=proof_id
        )
        if proof is None or proof.get("status") != "passed":
            missing.append(proof_id)
        elif not control.proof_is_fresh(
            proof,
            outcome=outcome,
            repo=repo,
            plan_revision=int(continuity["plan"].get("revision", 0)),
            node=node,
        ):
            stale.append(proof_id)
    return missing, stale


def integration_inspection(
    control, repo: pathlib.Path, receipt: dict[str, Any], continuity: dict[str, Any], milestone_id: str
) -> dict[str, Any]:
    nodes = _nodes(continuity)
    milestone = _milestone(nodes, milestone_id)
    children = _children(nodes, milestone_id)
    packets = [node for node in children if node.get("node_role") == "work_packet"]
    integration = next(
        (node for node in children if node.get("node_role") == "integration"), None
    )
    unfinished = [node["id"] for node in packets if node.get("status") not in {"done", "superseded"}]
    missing: list[str] = []
    stale: list[str] = []
    if integration is not None and integration.get("status") == "done":
        missing, stale = _latest_proof_state(control, repo, continuity, integration)
    compilation = milestone.get("milestone_state", {}).get("compilation_snapshot", {})
    baseline_status = set(compilation.get("product_status", []))
    baseline_fingerprints = compilation.get("product_status_fingerprints", {})
    baseline_fingerprints = baseline_fingerprints if isinstance(baseline_fingerprints, dict) else {}
    current_status = control.workspace_product_status(control.current_status(repo))
    allowed_scopes = sorted({scope for node in children for scope in node.get("write_scope", [])})
    outside_scope = sorted({
        path
        for line in current_status
        for path in [control.status_path(line)]
        if not control.path_in_scope(path, allowed_scopes)
        and (
            line not in baseline_status
            or baseline_fingerprints.get(path) != _scope_fingerprint(control, repo, path)
        )
    })
    ready = bool(
        integration is not None
        and not unfinished
        and integration.get("status") == "done"
        and not missing
        and not stale
        and not outside_scope
    )
    return {
        "status": "ready" if ready else "blocked",
        "milestone_id": milestone_id,
        "integration_node": integration.get("id") if integration else None,
        "integration_node_status": integration.get("status") if integration else "missing",
        "unfinished_work_packets": unfinished,
        "missing_proofs": missing,
        "stale_proofs": stale,
        "outside_compiled_scope": outside_scope,
        "integration_mode": milestone.get("milestone_state", {}).get(
            "merge_mode", "accumulated_workspace"
        ),
        "allowed_scope": allowed_scopes,
    }


def command_milestone_integration_inspect(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    receipt, continuity = _rolling_context(control, control.paths(repo))
    milestone_id = control.require_continuity_id("milestone id", args.milestone)
    result = integration_inspection(control, repo, receipt, continuity, milestone_id)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ready" else 2


def command_milestone_integration_record(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt, continuity = _rolling_context(control, state)
    loaded_revision = int(receipt.get("state_revision", 0))
    plan_revision = int(continuity["plan"].get("revision", 0))
    if args.state_revision != loaded_revision or args.plan_revision != plan_revision:
        raise ValueError("integration record revision conflict; inspect current milestone state")
    milestone_id = control.require_continuity_id("milestone id", args.milestone)
    nodes = _nodes(continuity)
    milestone = _milestone(nodes, milestone_id)
    inspection = integration_inspection(control, repo, receipt, continuity, milestone_id)
    result = args.result
    if result == "integrated" and inspection["status"] != "ready":
        raise ValueError("integration cannot be recorded as integrated while inspection is blocked")
    milestone_state = milestone.setdefault("milestone_state", {})
    milestone_state["integration_status"] = result
    milestone_state["integration_receipt"] = {
        "result": result,
        "summary": control.require_concrete("integration summary", args.summary),
        "evidence": control.require_concrete_list("integration evidence", args.evidence),
        "inspection": inspection,
        "recorded_at": control.now(),
    }
    if result == "integrated":
        milestone_state["compilation_status"] = "integrated"
    else:
        milestone_state["compilation_status"] = (
            "recompile_required" if result == "conflicted" else "blocked"
        )
        continuity["compilation_focus"] = milestone_id if result == "conflicted" else None
    continuity["current_node"] = None
    continuity["execution_focus"] = None
    refresh_rolling_frontier(control, continuity)
    continuity["updated_at"] = control.now()
    control.continuity_event(
        receipt, "milestone_integration_recorded", milestone_id=milestone_id, result=result
    )
    next_revision = control.write_active(state, receipt, expected_revision=loaded_revision)
    print(json.dumps({
        "status": "recorded",
        "milestone_id": milestone_id,
        "integration_status": result,
        "state_revision": next_revision,
        "inspection": inspection,
    }, ensure_ascii=False))
    return 0


def review_inspection(
    control, repo: pathlib.Path, receipt: dict[str, Any], continuity: dict[str, Any], milestone_id: str
) -> dict[str, Any]:
    nodes = _nodes(continuity)
    milestone = _milestone(nodes, milestone_id)
    children = [node for node in _children(nodes, milestone_id) if node.get("status") != "superseded"]
    unfinished = [node["id"] for node in children if node.get("status") != "done"]
    proof_gaps: list[dict[str, Any]] = []
    proved_coverage: set[str] = set()
    for node in children:
        if node.get("status") != "done":
            continue
        missing, stale = _latest_proof_state(control, repo, continuity, node)
        if missing or stale:
            proof_gaps.append({"node_id": node["id"], "missing": missing, "stale": stale})
        for proof_spec in (node.get("outcome") or {}).get("proofs", []):
            proof = control.latest_proof(
                continuity.get("proofs", []),
                node_id=node["id"],
                proof_id=str(proof_spec.get("id")),
            )
            if proof is not None and proof.get("status") == "passed" and control.proof_is_fresh(
                proof,
                outcome=node["outcome"],
                repo=repo,
                plan_revision=int(continuity["plan"].get("revision", 0)),
                node=node,
            ):
                proved_coverage.update(str(value) for value in proof.get("coverage_ids", []))
    child_ids = {milestone_id, *(node["id"] for node in children)}
    blocking_gaps = [
        gap for gap in continuity.get("gaps", [])
        if gap.get("status") == "open"
        and gap.get("blocking", True)
        and gap.get("node_id") in child_ids
    ]
    integration_status = milestone.get("milestone_state", {}).get("integration_status")
    coverage_gaps = sorted(set(milestone.get("coverage_ids", [])) - proved_coverage)
    ready = (
        not unfinished and not proof_gaps and not blocking_gaps
        and not coverage_gaps and integration_status == "integrated"
    )
    return {
        "status": "ready" if ready else "blocked",
        "milestone_id": milestone_id,
        "unfinished_nodes": unfinished,
        "proof_gaps": proof_gaps,
        "blocking_gaps": blocking_gaps,
        "coverage_gaps": coverage_gaps,
        "integration_status": integration_status,
        "acceptance": milestone.get("acceptance", []),
        "assertion_count": sum(len(node.get("assertions", [])) for node in children),
        "ready_for_acceptance": ready,
    }


def command_milestone_review_inspect(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    receipt, continuity = _rolling_context(control, control.paths(repo))
    milestone_id = control.require_continuity_id("milestone id", args.milestone)
    result = review_inspection(control, repo, receipt, continuity, milestone_id)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ready" else 2


def _exit_snapshot(
    control,
    repo: pathlib.Path,
    continuity: dict[str, Any],
    milestone: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    nodes = _nodes(continuity)
    children = _children(nodes, milestone["id"])
    proof_refs = [
        proof.get("attempt_id")
        for proof in continuity.get("proofs", [])
        if proof.get("node_id") in {node["id"] for node in children}
        and proof.get("status") == "passed"
    ]
    accepted_at = control.now()
    snapshot_id = "exit-" + hashlib.sha256(
        f"{milestone['id']}:{accepted_at}:{continuity['plan'].get('graph_sha256')}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "id": snapshot_id,
        "milestone_id": milestone["id"],
        "accepted_at": accepted_at,
        "compilation_revision": milestone.get("milestone_state", {}).get("compilation_revision"),
        "plan_revision": continuity["plan"].get("revision", 0),
        "graph_sha256": continuity["plan"].get("graph_sha256"),
        "head": control.git_head(repo),
        "product_status": control.workspace_product_status(control.current_status(repo)),
        "child_results": [
            {
                "id": node["id"],
                "role": node.get("node_role"),
                "contract_sha256": node.get("contract_sha256"),
                "result_ref": node.get("result_ref"),
            }
            for node in children
            if node.get("status") != "superseded"
        ],
        "proof_attempt_ids": sorted({str(value) for value in proof_refs if value}),
        "review": review,
        "codegraph_index_fingerprint": milestone.get("milestone_state", {})
        .get("compilation_snapshot", {}).get("codegraph", {}).get("index_fingerprint"),
    }


def command_milestone_review_record(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt, continuity = _rolling_context(control, state)
    loaded_revision = int(receipt.get("state_revision", 0))
    plan_revision = int(continuity["plan"].get("revision", 0))
    if args.state_revision != loaded_revision or args.plan_revision != plan_revision:
        raise ValueError("milestone review revision conflict; inspect current milestone state")
    milestone_id = control.require_continuity_id("milestone id", args.milestone)
    nodes = _nodes(continuity)
    milestone = _milestone(nodes, milestone_id)
    result = args.result
    inspection = review_inspection(control, repo, receipt, continuity, milestone_id)
    review = {
        "result": result,
        "summary": control.require_concrete("milestone review summary", args.summary),
        "evidence": control.require_concrete_list("milestone review evidence", args.evidence),
        "recorded_at": control.now(),
        "inspection": inspection,
    }
    milestone_state = milestone.setdefault("milestone_state", {})
    exit_snapshot = None
    if result == "accepted":
        if inspection["status"] != "ready":
            raise ValueError("milestone cannot be accepted while review inspection is blocked")
        milestone["status"] = "done"
        milestone_state["review_result"] = "accepted"
        milestone_state["compilation_status"] = "accepted"
        exit_snapshot = _exit_snapshot(control, repo, continuity, milestone, review)
        continuity.setdefault("exit_snapshots", []).append(exit_snapshot)
        milestone_state["exit_snapshot_id"] = exit_snapshot["id"]
        milestone_state["accepted_at"] = exit_snapshot["accepted_at"]
        continuity["current_node"] = None
        continuity["execution_focus"] = None
    elif result == "packet_rework_required":
        packet_id = control.require_continuity_id("packet id", str(args.packet or ""))
        packet = nodes.get(packet_id)
        if packet is None or packet.get("parent_id") != milestone_id:
            raise ValueError("packet rework target must belong to the reviewed milestone")
        if packet.get("node_role") != "work_packet":
            raise ValueError("packet rework target must be a work_packet")
        if packet.get("result_ref"):
            packet.setdefault("result_history", []).append(packet["result_ref"])
        packet["status"] = "active"
        packet.pop("result_ref", None)
        packet_base = packet.setdefault("execution_base", {})
        packet_base["rework_revision"] = int(packet_base.get("rework_revision", 0)) + 1
        integration = next(
            (node for node in _children(nodes, milestone_id) if node.get("node_role") == "integration"),
            None,
        )
        if integration is not None:
            integration["status"] = "planned"
            if integration.get("result_ref"):
                integration.setdefault("result_history", []).append(integration["result_ref"])
            integration.pop("result_ref", None)
            integration_base = integration.setdefault("execution_base", {})
            integration_base["rework_revision"] = int(
                integration_base.get("rework_revision", 0)
            ) + 1
        milestone_state["review_result"] = result
        milestone_state["integration_status"] = "not_ready"
        milestone_state["compilation_status"] = "compiled"
        continuity["current_node"] = packet_id
        continuity["execution_focus"] = packet_id
    elif result == "milestone_recompile_required":
        milestone_state["review_result"] = result
        milestone_state["compilation_status"] = "recompile_required"
        milestone_state["integration_status"] = "not_ready"
        continuity["compilation_focus"] = milestone_id
        continuity["current_node"] = None
        continuity["execution_focus"] = None
    elif result == "roadmap_revision_required":
        milestone["status"] = "blocked"
        milestone_state["review_result"] = result
        milestone_state["compilation_status"] = "blocked"
        continuity["current_node"] = None
        continuity["execution_focus"] = None
    else:
        milestone["status"] = "blocked"
        milestone_state["review_result"] = "blocked"
        milestone_state["compilation_status"] = "blocked"
        continuity["current_node"] = None
        continuity["execution_focus"] = None
    milestone_state["review_receipt"] = review
    continuity["plan"]["revision"] = plan_revision + 1
    continuity["plan"]["updated_at"] = control.now()
    frontier = refresh_rolling_frontier(control, continuity)
    if result == "accepted":
        continuity["compilation_focus"] = (
            frontier["milestones"][0] if frontier.get("milestones") else None
        )
        continuity["next_action"] = (
            f"Compile milestone {continuity['compilation_focus']} from fresh repository facts"
            if continuity.get("compilation_focus")
            else "Complete final task review"
        )
    continuity["updated_at"] = control.now()
    control.continuity_event(
        receipt, "milestone_review_recorded", milestone_id=milestone_id, result=result,
        exit_snapshot_id=exit_snapshot.get("id") if exit_snapshot else None,
    )
    next_revision = control.write_active(state, receipt, expected_revision=loaded_revision)
    print(json.dumps({
        "status": "recorded",
        "milestone_id": milestone_id,
        "review_result": result,
        "state_revision": next_revision,
        "plan_revision": continuity["plan"]["revision"],
        "exit_snapshot": exit_snapshot,
        "frontier": frontier,
    }, ensure_ascii=False))
    return 0
