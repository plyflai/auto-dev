"""Continuity plan parsing, numbering, and dependency validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from typing import Any

DISPLAY_CODE_PREFIX_RE = re.compile(
    r"^\s*(?P<code>[A-Za-z][A-Za-z0-9]*(?:\.[0-9]+)*)\s*:\s*(?P<label>.*)$"
)
MAJOR_MILESTONE_CODE_RE = re.compile(r"M(?P<number>[0-9]+)", re.IGNORECASE)
FRACTIONAL_MILESTONE_CODE_RE = re.compile(r"M[0-9]+(?:\.[0-9]+)+", re.IGNORECASE)


def title_display_code(title: str) -> str | None:
    match = DISPLAY_CODE_PREFIX_RE.match(title)
    return match.group("code") if match else None


def major_milestone_number(code: str | None) -> int | None:
    if not code:
        return None
    match = MAJOR_MILESTONE_CODE_RE.fullmatch(code)
    return int(match.group("number")) if match else None


def normalized_numbered_title(title: str, display_code: str) -> str:
    match = DISPLAY_CODE_PREFIX_RE.match(title)
    if not match:
        return title
    previous_code = match.group("code")
    if (
        major_milestone_number(previous_code) is not None
        or FRACTIONAL_MILESTONE_CODE_RE.fullmatch(previous_code)
        or previous_code == display_code
    ):
        return f"{display_code}: {match.group('label')}"
    return title


def normalize_plan_numbering(nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Assign stable display codes from plan order and parent topology."""
    children_by_id: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []
    previous_codes: dict[str, str | None] = {}
    for node in nodes:
        previous_codes[node["id"]] = node.get("display_code") or title_display_code(node["title"])
        if node.get("parent_id"):
            children_by_id.setdefault(node["parent_id"], []).append(node)
        else:
            roots.append(node)

    assigned_codes: dict[str, str] = {}

    def assign_children(node: dict[str, Any], display_code: str) -> None:
        assigned_codes[node["id"]] = display_code
        for index, child in enumerate(children_by_id.get(node["id"], []), start=1):
            assign_children(child, f"{display_code}.{index}")

    next_major: int | None = None
    for root in roots:
        previous_code = previous_codes[root["id"]]
        declared_major = major_milestone_number(previous_code)
        if declared_major is not None:
            if next_major is None:
                next_major = declared_major
            display_code = f"M{next_major}"
            next_major += 1
        elif previous_code:
            display_code = previous_code
        else:
            if next_major is None:
                next_major = 0
            display_code = f"M{next_major}"
            next_major += 1
        assign_children(root, display_code)

    changes: list[dict[str, Any]] = []
    for node in nodes:
        previous_code = previous_codes[node["id"]]
        display_code = assigned_codes[node["id"]]
        node["display_code"] = display_code
        node["title"] = normalized_numbered_title(node["title"], display_code)
        node["contract_sha256"] = node_contract_digest(node)
        if previous_code != display_code:
            changes.append({"id": node["id"], "from": previous_code, "to": display_code})
    return nodes, changes


def load_plan_input(args: argparse.Namespace) -> dict[str, Any]:
    if bool(args.plan_file) == bool(args.plan_json):
        raise ValueError("provide exactly one of --plan-file or --plan-json")
    if args.plan_file:
        payload = json.loads(pathlib.Path(args.plan_file).expanduser().read_text(encoding="utf-8"))
    else:
        payload = json.loads(args.plan_json)
    if not isinstance(payload, dict):
        raise ValueError("continuity plan must be a JSON object")
    return payload


def _metadata_list(control, label: str, value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return list(dict.fromkeys(control.require_concrete_list(label, value) if value else []))


def _normalize_assertions(control, node_id: str, value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"node {node_id} assertions must be an array")
    assertions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError(f"node {node_id} assertion must be an object")
        unknown = sorted(set(raw) - {"id", "observable", "predicate", "expected", "proof_ids", "blocking"})
        if unknown:
            raise ValueError(
                f"node {node_id} assertion has unsupported fields: " + ", ".join(unknown)
            )
        assertion_id = control.require_continuity_id(
            "assertion id", str(raw.get("id", ""))
        )
        if assertion_id in seen:
            raise ValueError(f"node {node_id} has duplicate assertion id: {assertion_id}")
        seen.add(assertion_id)
        assertions.append({
            "id": assertion_id,
            "observable": control.require_concrete(
                "assertion observable", str(raw.get("observable", ""))
            ),
            "predicate": control.require_concrete(
                "assertion predicate", str(raw.get("predicate", ""))
            ),
            "expected": control.require_concrete(
                "assertion expected value", str(raw.get("expected", ""))
            ),
            "proof_ids": _metadata_list(
                control, "assertion proof id", raw.get("proof_ids")
            ),
            "blocking": bool(raw.get("blocking", True)),
        })
    return assertions


def _normalize_policy_list(control, label: str, value: Any) -> list[str]:
    return _metadata_list(control, label, value)


def _normalize_packet_policies(
    control,
    node_id: str,
    node_role: str | None,
    raw: dict[str, Any],
    previous: dict[str, Any],
) -> dict[str, Any]:
    """Normalize packet-local execution, proof, review, and merge policy.

    These fields refine a Team Core packet after compilation; they do not create
    a nested Direct/Team routing decision.
    """
    if node_role not in {"work_packet", "integration"}:
        return {}
    execution_profile = str(
        raw.get("execution_profile", previous.get("execution_profile", "bounded"))
    )
    if execution_profile not in control.PACKET_EXECUTION_PROFILES:
        raise ValueError(
            f"node {node_id} execution_profile must be one of: "
            + ", ".join(sorted(control.PACKET_EXECUTION_PROFILES))
        )
    required_capabilities = _normalize_policy_list(
        control,
        f"node {node_id} required capability",
        raw.get("required_capabilities", previous.get("required_capabilities", [])),
    )
    required_capabilities = control.validate_capabilities(required_capabilities)
    review_policy = str(
        raw.get(
            "review_policy",
            previous.get("review_policy", "full" if node_role == "integration" else "proof_only"),
        )
    )
    if review_policy not in control.PACKET_REVIEW_POLICIES:
        raise ValueError(
            f"node {node_id} review_policy must be one of: "
            + ", ".join(sorted(control.PACKET_REVIEW_POLICIES))
        )
    verification = raw.get("verification_policy", previous.get("verification_policy"))
    if verification is None:
        verification = {}
    if not isinstance(verification, dict):
        raise ValueError(f"node {node_id} verification_policy must be an object")
    unknown_verification = sorted(set(verification) - {"required", "post_merge", "blocking"})
    if unknown_verification:
        raise ValueError(
            f"node {node_id} verification_policy has unsupported fields: "
            + ", ".join(unknown_verification)
        )
    verification_policy = {
        "required": _normalize_policy_list(
            control,
            f"node {node_id} required verification",
            verification.get("required", []),
        ),
        "post_merge": _normalize_policy_list(
            control,
            f"node {node_id} post-merge verification",
            verification.get("post_merge", []),
        ),
        "blocking": bool(verification.get("blocking", True)),
    }
    merge = raw.get("merge_policy", previous.get("merge_policy"))
    if merge is None:
        merge = {}
    if not isinstance(merge, dict):
        raise ValueError(f"node {node_id} merge_policy must be an object")
    unknown_merge = sorted(set(merge) - {"mode", "conflict_owner", "pre_merge"})
    if unknown_merge:
        raise ValueError(
            f"node {node_id} merge_policy has unsupported fields: "
            + ", ".join(unknown_merge)
        )
    merge_mode = str(merge.get("mode", "accumulated_workspace"))
    if merge_mode not in control.PACKET_MERGE_MODES:
        raise ValueError(
            f"node {node_id} merge_policy.mode must be one of: "
            + ", ".join(sorted(control.PACKET_MERGE_MODES))
        )
    conflict_owner = str(merge.get("conflict_owner", "main"))
    if conflict_owner not in control.PACKET_CONFLICT_OWNERS:
        raise ValueError(
            f"node {node_id} merge_policy.conflict_owner must be one of: "
            + ", ".join(sorted(control.PACKET_CONFLICT_OWNERS))
        )
    model_profile = raw.get("model_profile", previous.get("model_profile"))
    if model_profile is not None:
        model_profile = control.require_concrete(f"node {node_id} model profile", str(model_profile))
    return {
        "execution_profile": execution_profile,
        "required_capabilities": required_capabilities,
        "review_policy": review_policy,
        "verification_policy": verification_policy,
        "merge_policy": {
            "mode": merge_mode,
            "conflict_owner": conflict_owner,
            "pre_merge": bool(merge.get("pre_merge", node_role == "work_packet")),
        },
        **({"model_profile": model_profile} if model_profile is not None else {}),
    }


def node_contract_digest(node: dict[str, Any]) -> str:
    dynamic = {
        "status", "activated_at", "historical_completion", "execution_base",
        "result_ref", "result_history", "milestone_state", "contract_sha256", "display_code",
    }
    payload = {key: node[key] for key in sorted(node) if key not in dynamic}
    title = payload.get("title")
    if isinstance(title, str):
        match = DISPLAY_CODE_PREFIX_RE.match(title)
        if match:
            payload["title"] = match.group("label")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def plan_graph_digest(
    nodes: list[dict[str, Any]], relations: list[dict[str, Any]]
) -> str:
    payload = {
        "nodes": [
            {
                "id": node.get("id"),
                "parent_id": node.get("parent_id"),
                "depends_on": node.get("depends_on", []),
                "node_role": node.get("node_role"),
                "contract_sha256": node.get("contract_sha256"),
            }
            for node in nodes
        ],
        "relations": relations,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def node_role(node: dict[str, Any]) -> str | None:
    value = node.get("node_role")
    return str(value) if value in {"milestone", "work_packet", "integration"} else None


def validate_rolling_plan(
    control,
    nodes: list[dict[str, Any]],
    *,
    strategy: str,
    relations: Any = None,
) -> list[dict[str, Any]]:
    if strategy not in control.PLAN_STRATEGIES:
        raise ValueError(
            f"unsupported plan strategy: {strategy}; expected "
            + ", ".join(sorted(control.PLAN_STRATEGIES))
        )
    if strategy == "legacy":
        return []
    by_id = {node["id"]: node for node in nodes}
    for node in nodes:
        role = node.get("node_role")
        if node.get("parent_id") is None:
            if role != "milestone":
                raise ValueError(
                    f"rolling graph root node {node['id']} must use node_role=milestone"
                )
            invalid_dependencies = [
                dependency for dependency in node.get("depends_on", [])
                if by_id[dependency].get("node_role") != "milestone"
            ]
            if invalid_dependencies:
                raise ValueError(
                    f"milestone {node['id']} can only depend on milestones: "
                    + ", ".join(invalid_dependencies)
                )
        else:
            parent = by_id[node["parent_id"]]
            if parent.get("node_role") != "milestone":
                raise ValueError(
                    f"rolling graph node {node['id']} must belong directly to a milestone"
                )
            if role not in {"work_packet", "integration"}:
                raise ValueError(
                    f"rolling graph child node {node['id']} must be work_packet or integration"
                )
            for dependency in node.get("depends_on", []):
                dependency_node = by_id[dependency]
                if dependency_node.get("parent_id") != node.get("parent_id"):
                    raise ValueError(
                        f"work packet {node['id']} cannot depend directly on another milestone"
                    )
        if role in {"work_packet", "integration"}:
            required_fields = {
                "target": node.get("target"),
                "write_scope": node.get("write_scope"),
                "owns": node.get("owns"),
                "assertions": node.get("assertions"),
                "escalation": node.get("escalation"),
            }
            missing = [key for key, value in required_fields.items() if value in (None, [], "")]
            if missing:
                raise ValueError(
                    f"rolling node {node['id']} is not execution-ready; missing: "
                    + ", ".join(missing)
                )
            declared_proofs = {
                str(proof.get("id")) for proof in (node.get("outcome") or {}).get("proofs", [])
            }
            blocking_assertions = [
                assertion for assertion in node.get("assertions", []) if assertion.get("blocking")
            ]
            uncovered = [
                assertion["id"] for assertion in blocking_assertions
                if not assertion.get("proof_ids")
                or not set(assertion["proof_ids"]).issubset(declared_proofs)
            ]
            if uncovered:
                raise ValueError(
                    f"rolling node {node['id']} has blocking assertions without declared proofs: "
                    + ", ".join(uncovered)
                )
            recipe_missing = [
                str(proof.get("id")) for proof in (node.get("outcome") or {}).get("proofs", [])
                if not isinstance(proof.get("recipe"), dict)
            ]
            if recipe_missing:
                raise ValueError(
                    f"rolling node {node['id']} proof recipes are incomplete: "
                    + ", ".join(recipe_missing)
                )
            for proof in (node.get("outcome") or {}).get("proofs", []):
                recipe = proof.get("recipe") if isinstance(proof, dict) else None
                if not isinstance(recipe, dict):
                    continue
                argv = recipe.get("argv")
                if not isinstance(argv, list) or not argv or not all(
                    isinstance(value, str) and value.strip() for value in argv
                ):
                    raise ValueError(
                        f"rolling node {node['id']} proof recipe argv must be a non-empty string array"
                    )
                evidence_file = recipe.get("evidence_file")
                if evidence_file is not None and (
                    not isinstance(evidence_file, str) or not evidence_file.strip()
                ):
                    raise ValueError(
                        f"rolling node {node['id']} proof recipe evidence_file must be a non-empty path"
                    )
                cwd = recipe.get("cwd", ".")
                if not isinstance(cwd, str) or not cwd.strip():
                    raise ValueError(
                        f"rolling node {node['id']} proof recipe cwd must be a non-empty path"
                    )
                for key in ("inputs", "observed_paths"):
                    values = recipe.get(key, [])
                    if not isinstance(values, list) or not all(
                        isinstance(value, str) and value.strip() for value in values
                    ):
                        raise ValueError(
                            f"rolling node {node['id']} proof recipe {key} must be a string array"
                        )
                preflight = recipe.get("preflight_argv")
                if preflight is not None and (
                    not isinstance(preflight, list) or not preflight or not all(
                        isinstance(value, str) and value.strip() for value in preflight
                    )
                ):
                    raise ValueError(
                        f"rolling node {node['id']} proof recipe preflight_argv must be a non-empty string array"
                    )

    relation_records: list[dict[str, Any]] = []
    if relations is not None:
        if not isinstance(relations, list):
            raise ValueError("rolling graph relations must be an array")
        for raw in relations:
            if not isinstance(raw, dict):
                raise ValueError("rolling graph relation must be an object")
            unknown = sorted(set(raw) - {"from", "to", "kind", "evidence"})
            if unknown:
                raise ValueError(
                    "rolling graph relation has unsupported fields: " + ", ".join(unknown)
                )
            source = control.require_continuity_id("relation source", str(raw.get("from", "")))
            target = control.require_continuity_id("relation target", str(raw.get("to", "")))
            if source == target or source not in by_id or target not in by_id:
                raise ValueError(f"rolling graph relation has invalid endpoints: {source} -> {target}")
            kind = str(raw.get("kind", ""))
            if kind not in control.ROLLING_RELATION_KINDS:
                raise ValueError(f"unsupported rolling graph relation kind: {kind}")
            relation_records.append({
                "from": source,
                "to": target,
                "kind": kind,
                "evidence": _metadata_list(control, "relation evidence", raw.get("evidence")),
            })
    return relation_records



def validate_plan_nodes(control, raw_nodes: Any, existing: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("continuity plan requires a non-empty nodes array")
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            raise ValueError("each continuity node must be a JSON object")
        node_id = control.require_continuity_id("node id", str(raw.get("id", "")))
        if node_id in seen:
            raise ValueError(f"duplicate continuity node id: {node_id}")
        seen.add(node_id)
        previous = existing.get(node_id, {})
        title = control.require_concrete("node title", str(raw.get("title", "")))
        raw_display_code = raw.get("display_code", previous.get("display_code"))
        if raw_display_code is None:
            raw_display_code = title_display_code(title)
        display_code = control.require_display_code("node display code", str(raw_display_code)) if raw_display_code else None
        status = str(raw.get("status", previous.get("status", "planned")))
        if status not in control.CONTINUITY_NODE_STATUSES:
            raise ValueError(f"invalid status for node {node_id}: {status}")
        node_kind = str(raw.get("node_kind", previous.get("node_kind", "delivery")))
        if node_kind not in control.CONTINUITY_NODE_KINDS:
            raise ValueError(
                f"invalid node kind for {node_id}: {node_kind}; expected "
                + ", ".join(sorted(control.CONTINUITY_NODE_KINDS))
            )
        raw_role = raw.get("node_role", previous.get("node_role"))
        node_role = None
        if raw_role is not None:
            node_role = str(raw_role)
            if node_role not in control.CONTINUITY_NODE_ROLES:
                raise ValueError(
                    f"invalid node role for {node_id}: {node_role}; expected "
                    + ", ".join(sorted(control.CONTINUITY_NODE_ROLES))
                )
        raw_verification = raw.get("verification", previous.get("verification"))
        verification: dict[str, Any] | None = None
        if raw_verification is not None:
            if not isinstance(raw_verification, dict):
                raise ValueError(f"node {node_id} verification metadata must be an object")
            allowed_verification = {
                "scope", "phase_refs", "gate", "placement_reason", "scenario_refs",
                "expected", "actual",
            }
            unknown_verification = sorted(set(raw_verification) - allowed_verification)
            if unknown_verification:
                raise ValueError(
                    f"node {node_id} verification has unsupported fields: "
                    + ", ".join(unknown_verification)
                )

            def normalize_metadata_list(label: str, value: Any) -> list[str]:
                if value is None:
                    return []
                if isinstance(value, str):
                    value = [value]
                if not isinstance(value, list):
                    raise ValueError(f"{label} must be an array")
                return control.require_concrete_list(label, value) if value else []

            verification = {
                "scope": normalize_metadata_list(
                    f"node {node_id} verification scope", raw_verification.get("scope")
                ),
                "phase_refs": normalize_metadata_list(
                    f"node {node_id} verification phase", raw_verification.get("phase_refs")
                ),
                "scenario_refs": normalize_metadata_list(
                    f"node {node_id} verification scenario", raw_verification.get("scenario_refs")
                ),
                "gate": str(raw_verification.get("gate", "blocking")),
            }
            if verification["gate"] not in control.VERIFICATION_GATES:
                raise ValueError(
                    f"node {node_id} verification gate must be one of: "
                    + ", ".join(sorted(control.VERIFICATION_GATES))
                )
            placement_reason = raw_verification.get("placement_reason")
            if placement_reason is not None:
                verification["placement_reason"] = control.require_concrete(
                    f"node {node_id} verification placement reason", str(placement_reason)
                )
            for field in ("expected", "actual"):
                value = raw_verification.get(field)
                if value is not None:
                    verification[field] = control.require_concrete(
                        f"node {node_id} verification {field}", str(value)
                    )
            if node_kind in {"verification", "release"} and "placement_reason" not in verification:
                raise ValueError(f"node {node_id} {node_kind} milestone requires placement_reason")
            verification = {
                key: value for key, value in verification.items()
                if value not in (None, [], "")
            }
        elif node_kind in {"verification", "release"}:
            raise ValueError(f"node {node_id} {node_kind} milestone requires verification metadata")
        historical_completion = previous.get("historical_completion")
        if status == "done" and previous.get("status") not in {"done", "superseded"}:
            if previous:
                raise ValueError(
                    f"node {node_id} cannot become done through plan; record proofs and use checkpoint"
                )
            raw_historical = raw.get("historical_completion")
            if not isinstance(raw_historical, dict):
                raise ValueError(
                    f"new done node {node_id} requires historical_completion; active work must use checkpoint"
                )
            historical_completion = {
                "summary": control.require_concrete(
                    "historical completion summary", str(raw_historical.get("summary", ""))
                ),
                "evidence": control.require_concrete_list(
                    "historical completion evidence", raw_historical.get("evidence", [])
                ),
                "confirmation_source": control.require_concrete(
                    "historical completion confirmation source",
                    str(raw_historical.get("confirmation_source", "")),
                ),
            }
        parent_id = raw.get("parent_id")
        if parent_id is not None:
            parent_id = control.require_continuity_id("parent id", str(parent_id))
        depends_on = [
            control.require_continuity_id("dependency id", str(value))
            for value in raw.get("depends_on", [])
        ]
        raw_coverage = raw.get("coverage_ids", previous.get("coverage_ids", []))
        if isinstance(raw_coverage, str):
            raw_coverage = [raw_coverage]
        if not isinstance(raw_coverage, list):
            raise ValueError(f"node {node_id} coverage_ids must be an array")
        coverage_ids = [
            control.require_control_id("node coverage id", str(value))
            for value in raw_coverage
        ]
        if node_role == "milestone" and raw.get("outcome") is None:
            outcome = previous.get("outcome")
        else:
            outcome = control.normalize_outcome(raw.get("outcome"), previous, node_id=node_id)
        target = raw.get("target", previous.get("target"))
        if target is not None:
            target = control.require_concrete("work packet target", str(target))
        escalation = raw.get("escalation", previous.get("escalation"))
        if escalation is not None:
            if not isinstance(escalation, dict):
                raise ValueError(f"node {node_id} escalation must be an object")
            unknown_escalation = sorted(
                set(escalation) - {"rework", "recompile", "roadmap_revision"}
            )
            if unknown_escalation:
                raise ValueError(
                    f"node {node_id} escalation has unsupported fields: "
                    + ", ".join(unknown_escalation)
                )
            escalation = {
                key: control.require_concrete(f"{key} escalation", str(escalation.get(key, "")))
                for key in ("rework", "recompile", "roadmap_revision")
            }
        packet_policies = _normalize_packet_policies(control, node_id, node_role, raw, previous)
        integration_wave = raw.get("integration_wave", previous.get("integration_wave"))
        if integration_wave is not None:
            if not isinstance(integration_wave, int) or integration_wave < 1:
                raise ValueError(f"node {node_id} integration_wave must be a positive integer")
        node = {
            "id": node_id,
            "title": title,
            "display_code": display_code,
            "node_kind": node_kind,
            **({"node_role": node_role} if node_role is not None else {}),
            "status": status,
            "parent_id": parent_id,
            "depends_on": list(dict.fromkeys(depends_on)),
            "acceptance": control.optional_concrete_list("node acceptance", raw.get("acceptance", [])),
            "coverage_ids": list(dict.fromkeys(coverage_ids)),
            "outcome": outcome,
            **({"target": target} if target is not None else {}),
            "context_refs": _metadata_list(
                control, "node context ref", raw.get("context_refs", previous.get("context_refs"))
            ),
            "write_scope": _metadata_list(
                control, "node write scope", raw.get("write_scope", previous.get("write_scope"))
            ),
            "owns": _metadata_list(
                control, "node ownership", raw.get("owns", previous.get("owns"))
            ),
            "provides": _metadata_list(
                control, "node provided contract", raw.get("provides", previous.get("provides"))
            ),
            "consumes": _metadata_list(
                control, "node consumed contract", raw.get("consumes", previous.get("consumes"))
            ),
            "exclusive_claims": _metadata_list(
                control, "node exclusive claim", raw.get("exclusive_claims", previous.get("exclusive_claims"))
            ),
            "assertions": _normalize_assertions(
                control, node_id, raw.get("assertions", previous.get("assertions"))
            ),
            **({"escalation": escalation} if escalation is not None else {}),
            **packet_policies,
            **({"integration_wave": integration_wave} if integration_wave is not None else {}),
            **({"verification": verification} if verification is not None else {}),
            "activated_at": previous.get("activated_at"),
            "historical_completion": historical_completion,
            **({"execution_base": previous["execution_base"]} if isinstance(previous.get("execution_base"), dict) else {}),
            **({"result_ref": previous["result_ref"]} if isinstance(previous.get("result_ref"), dict) else {}),
            **({"result_history": previous["result_history"]} if isinstance(previous.get("result_history"), list) else {}),
            **({"milestone_state": previous["milestone_state"]} if isinstance(previous.get("milestone_state"), dict) else {}),
        }
        node["contract_sha256"] = node_contract_digest(node)
        nodes.append(node)

    by_id = {node["id"]: node for node in nodes}
    for node in nodes:
        references = ([node["parent_id"]] if node["parent_id"] else []) + node["depends_on"]
        for reference in references:
            if reference not in by_id:
                raise ValueError(f"node {node['id']} references missing node {reference}")
            if reference == node["id"]:
                raise ValueError(f"node {node['id']} cannot reference itself")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError(f"continuity plan contains a cycle at {node_id}")
        if node_id in visited:
            return
        visiting.add(node_id)
        node = by_id[node_id]
        edges = ([node["parent_id"]] if node["parent_id"] else []) + node["depends_on"]
        for edge in edges:
            visit(edge)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in by_id:
        visit(node_id)
    return nodes


def plan_state_issues(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {node["id"]: node for node in nodes}
    issues: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("status") in {"active", "done"}:
            unfinished = [
                dependency for dependency in node.get("depends_on", [])
                if by_id[dependency].get("status") != "done"
            ]
            if unfinished:
                issues.append({"node_id": node["id"], "kind": "dependency_not_ready", "blocked_by": unfinished})
        if node.get("status") == "done":
            unfinished_children = [
                child["id"] for child in nodes
                if child.get("parent_id") == node["id"]
                and child.get("status") not in {"done", "superseded"}
            ]
            if unfinished_children:
                issues.append({"node_id": node["id"], "kind": "children_not_done", "blocked_by": unfinished_children})
    return issues


def node_dependency_satisfied(node: dict[str, Any], continuity: dict[str, Any]) -> bool:
    if node.get("status") in {"done", "superseded"}:
        return True
    verification = node.get("verification") if isinstance(node.get("verification"), dict) else {}
    if node.get("status") != "blocked" or verification.get("gate") != "advisory":
        return False
    return any(
        gap.get("status") == "open"
        and gap.get("node_id") == node.get("id")
        and not gap.get("blocking")
        for gap in continuity.get("gaps", [])
    )
