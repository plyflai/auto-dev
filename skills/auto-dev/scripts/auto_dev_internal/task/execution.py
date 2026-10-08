"""Small execution-decision and host-handoff helpers for rolling milestones."""

from __future__ import annotations

import hashlib
import json
from typing import Any


WORKER_PROFILES: dict[str, dict[str, str]] = {
    "light_worker": {
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "reasoning": "high",
    },
}


def resolve_worker_profile(
    profile: str | None, executor_override: dict[str, str] | None = None
) -> dict[str, str]:
    name = str(profile or "light_worker")
    if name == "external_worker":
        override = executor_override or {}
        missing = [
            key for key in ("provider", "model", "reasoning")
            if not str(override.get(key) or "").strip()
        ]
        if missing:
            raise ValueError(
                "external_worker requires explicit executor fields: " + ", ".join(missing)
            )
        return {
            "name": name,
            "provider": str(override["provider"]),
            "model": str(override["model"]),
            "reasoning": str(override["reasoning"]),
            "source": "explicit",
        }
    try:
        return {"name": name, **WORKER_PROFILES[name], "source": "built_in"}
    except KeyError as error:
        raise ValueError("unknown worker profile: " + name) from error


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def packet_ids(continuity: dict[str, Any], milestone_id: str) -> list[str]:
    return sorted(
        str(node.get("id"))
        for node in continuity.get("plan", {}).get("nodes", [])
        if isinstance(node, dict)
        and node.get("parent_id") == milestone_id
        and node.get("node_role") == "work_packet"
        and node.get("status") != "superseded"
    )


def decision_for(milestone: dict[str, Any]) -> dict[str, Any] | None:
    state = milestone.get("milestone_state", {})
    value = state.get("execution_decision")
    return value if isinstance(value, dict) else None


def _recommended_lane(policy: dict[str, Any], packets: list[str]) -> str:
    topology = policy.get("execution_topology")
    if topology == "multi_agent":
        return "multi_worker"
    return "main_session"


def build_pending_decision(
    milestone: dict[str, Any], *, compilation_revision: int, packet_contracts_sha256: str,
    packet_list: list[str] | None = None,
) -> dict[str, Any]:
    state = milestone.get("milestone_state", {})
    policy = state.get("compilation_policy", {}) if isinstance(state, dict) else {}
    packets = list(packet_list or [])
    # The caller may replace the derived packet list; keeping the envelope small
    # avoids copying execution history into the decision contract.
    return {
        "version": 2,
        "status": "pending",
        "recommended_mode": _recommended_lane(policy, packets),
        "selected_mode": None,
        "worker_profile": "light_worker",
        "executor": None,
        "launch_status": "not_selected",
        "compilation_revision": compilation_revision,
        "packet_contracts_sha256": packet_contracts_sha256,
        "packet_ids": packets,
        "boundary": "before_integration",
        "confirmation_source": None,
    }


def decision_is_current(milestone: dict[str, Any]) -> bool:
    state = milestone.get("milestone_state", {})
    decision = decision_for(milestone)
    snapshot = state.get("compilation_snapshot", {}) if isinstance(state, dict) else {}
    return bool(
        decision
        and decision.get("compilation_revision") == state.get("compilation_revision")
        and decision.get("packet_contracts_sha256") == snapshot.get("packet_contracts_sha256")
    )


def assignment_mode(assignments: dict[str, Any]) -> str:
    executors = {str(value.get("executor")) for value in assignments.values() if isinstance(value, dict)}
    if executors == {"main"}:
        return "main_session"
    worker_slots = {str(value.get("worker_slot")) for value in assignments.values() if isinstance(value, dict) and value.get("executor") == "worker"}
    return "single_worker" if len(worker_slots) <= 1 else "multi_worker"


def select_decision(
    milestone: dict[str, Any], *, mode: str, confirmation_source: str,
    worker_profile: str | None = None,
    worker_executor: dict[str, str] | None = None,
) -> dict[str, Any]:
    if mode not in {"main_session", "single_worker", "multi_worker"}:
        raise ValueError("execution mode must be main_session, single_worker, or multi_worker")
    decision = decision_for(milestone)
    if not decision:
        raise ValueError("milestone has no pending execution decision")
    if decision.get("status") not in {"pending", "selected"}:
        raise ValueError(f"milestone execution decision is not selectable: {decision.get('status')}")
    selected = dict(decision)
    profile = (
        resolve_worker_profile(worker_profile, worker_executor)
        if mode in {"single_worker", "multi_worker"} else None
    )
    selected.update({
        "status": "selected",
        "selected_mode": mode,
        "confirmation_source": confirmation_source,
        "worker_profile": profile.get("name") if profile else None,
        "executor": profile,
        "launch_status": "dispatch_required" if profile else "host_owned",
        "owner": "worker" if profile else "main_session",
        "handoff_status": "not_required",
    })
    return selected


def handoff_state(milestone: dict[str, Any], *, reason: str) -> dict[str, Any]:
    decision = decision_for(milestone)
    if not decision:
        raise ValueError("milestone has no execution decision")
    result = dict(decision)
    result.update({
        "status": "awaiting_main",
        "owner": "main_session",
        "handoff_status": "required",
        "handoff_reason": reason,
    })
    return result
