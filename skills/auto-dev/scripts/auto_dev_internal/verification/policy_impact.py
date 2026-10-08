"""Workspace policy and CodeGraph impact domain commands."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import pathlib
import re
from typing import Any, Iterable

DEFAULT_PROTECTED_BRANCHES = ("main", "master", "production", "release/*")

def default_workspace_policy(control) -> dict[str, Any]:
    return {
        "schema_version": control.WORKSPACE_POLICY_SCHEMA_VERSION,
        "policy_revision": 0,
        "protected_branches": list(DEFAULT_PROTECTED_BRANCHES),
        "forbidden_paths": [],
        "approval_paths": [],
        "sensitive_paths": [],
        "confirmation_source": None,
        "reason": None,
        "updated_at": None,
    }


def normalize_policy_pattern(control, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("workspace policy pattern must be a non-empty repository-relative path")
    pattern = value.strip()
    if "\\" in pattern or "//" in pattern:
        raise ValueError(f"workspace policy pattern is not normalized: {value}")
    candidate = pathlib.PurePosixPath(pattern)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"workspace policy pattern must stay repository-relative: {value}")
    normalized = candidate.as_posix()
    if normalized in {"", "."}:
        raise ValueError("workspace policy pattern cannot target the repository root")
    return normalized


def normalize_policy_path(control, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("workspace policy path must be a non-empty repository-relative path")
    path = value.strip()
    if "\\" in path or "//" in path:
        raise ValueError(f"workspace policy path is not normalized: {value}")
    candidate = pathlib.PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"workspace policy path must stay repository-relative: {value}")
    normalized = candidate.as_posix()
    if normalized in {"", "."} or any(character in normalized for character in "*?["):
        raise ValueError(f"workspace policy inspection and approval require an exact path: {value}")
    return normalized


def normalize_policy_rule(control, kind: str, raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError(f"{kind} entries must be objects")
    unknown = sorted(set(raw) - {"id", "pattern", "reason"})
    if unknown:
        raise ValueError(f"{kind} entry has unsupported fields: {', '.join(unknown)}")
    pattern = normalize_policy_pattern(control, raw.get("pattern"))
    reason_value = raw.get("reason")
    if not isinstance(reason_value, str) or not reason_value.strip():
        raise ValueError(f"{kind} entry requires a concrete reason")
    rule_id = raw.get("id")
    if rule_id is None:
        digest = hashlib.sha256(f"{kind}\0{pattern}".encode("utf-8")).hexdigest()[:12]
        rule_id = f"{kind.removesuffix('_paths')}-{digest}"
    if not isinstance(rule_id, str) or not control.WORKSPACE_POLICY_ID_RE.fullmatch(rule_id):
        raise ValueError(f"{kind} rule id must use lowercase letters, digits, underscores, or hyphens")
    return {"id": rule_id, "pattern": pattern, "reason": reason_value.strip()}


def normalize_workspace_policy(control, 
    raw: Any,
    *,
    default_branches: Iterable[str] = DEFAULT_PROTECTED_BRANCHES,
    persisted: bool = False,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("workspace policy must be a JSON object")
    allowed = {
        "schema_version", "policy_revision", "protected_branches", *control.WORKSPACE_POLICY_RULE_KINDS,
        "confirmation_source", "reason", "updated_at",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"workspace policy has unsupported fields: {', '.join(unknown)}")
    schema_version = raw.get("schema_version", control.WORKSPACE_POLICY_SCHEMA_VERSION)
    if schema_version != control.WORKSPACE_POLICY_SCHEMA_VERSION:
        raise ValueError("unsupported workspace policy schema version")
    revision = raw.get("policy_revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("workspace policy revision must be a non-negative integer")
    branches_raw = raw.get("protected_branches", list(default_branches))
    if not isinstance(branches_raw, list):
        raise ValueError("protected_branches must be a list")
    branches: list[str] = []
    for value in branches_raw:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("protected branch patterns must be non-empty strings")
        branch = value.strip()
        if branch not in branches:
            branches.append(branch)
    if len(branches) != len(branches_raw):
        raise ValueError("protected branch patterns must be unique")
    if not branches:
        branches = list(DEFAULT_PROTECTED_BRANCHES)

    result: dict[str, Any] = {
        "schema_version": control.WORKSPACE_POLICY_SCHEMA_VERSION,
        "policy_revision": revision,
        "protected_branches": branches,
    }
    seen_ids: set[str] = set()
    seen_patterns: set[str] = set()
    for kind in control.WORKSPACE_POLICY_RULE_KINDS:
        values = raw.get(kind, [])
        if not isinstance(values, list):
            raise ValueError(f"{kind} must be a list")
        rules: list[dict[str, str]] = []
        for value in values:
            rule = normalize_policy_rule(control, kind, value)
            if rule["id"] in seen_ids:
                raise ValueError(f"workspace policy rule id is duplicated: {rule['id']}")
            if rule["pattern"] in seen_patterns:
                raise ValueError(f"workspace policy pattern is duplicated: {rule['pattern']}")
            seen_ids.add(rule["id"])
            seen_patterns.add(rule["pattern"])
            rules.append(rule)
        result[kind] = rules
    for key in ("confirmation_source", "reason", "updated_at"):
        value = raw.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"workspace policy {key} must be a string or null")
        result[key] = value.strip() if isinstance(value, str) else None
    if persisted and revision > 0:
        if not result["confirmation_source"] or not result["reason"] or not result["updated_at"]:
            raise ValueError("persisted workspace policy metadata is incomplete")
    return result


def load_workspace_policy(control, state: dict[str, pathlib.Path]) -> dict[str, Any]:
    if not state["config"].exists():
        return default_workspace_policy(control, )
    try:
        raw = control.read_json(state["config"])
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"workspace policy cannot be read: {error}") from error
    legacy = "schema_version" not in raw and "policy_revision" not in raw
    return normalize_workspace_policy(control, raw, persisted=not legacy)


def workspace_policy_digest(control, policy: dict[str, Any]) -> str:
    semantic = {
        "schema_version": policy["schema_version"],
        "protected_branches": policy["protected_branches"],
        **{kind: policy[kind] for kind in control.WORKSPACE_POLICY_RULE_KINDS},
    }
    return hashlib.sha256(control.canonical_json(semantic).encode("utf-8")).hexdigest()


def policy_pattern_matches(control, path: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    return pattern.endswith("/**") and path == pattern[:-3].rstrip("/")


def effective_workspace_policy_rules(control, policy: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for kind in control.WORKSPACE_POLICY_RULE_KINDS:
        result[kind] = [
            {**rule, "source": "system"} for rule in control.SYSTEM_WORKSPACE_POLICY_RULES[kind]
        ] + [
            {**rule, "source": "project"} for rule in policy[kind]
        ]
    return result


def workspace_policy_path_evaluation(control, path: str, policy: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_policy_path(control, path)
    rules = effective_workspace_policy_rules(control, policy)
    matches = {
        kind: [rule for rule in rules[kind] if policy_pattern_matches(control, normalized, rule["pattern"])]
        for kind in control.WORKSPACE_POLICY_RULE_KINDS
    }
    forbidden = bool(matches["forbidden_paths"])
    approval_required = bool(matches["approval_paths"])
    sensitive = bool(matches["sensitive_paths"])
    classification = (
        "forbidden" if forbidden else
        "approval_required" if approval_required else
        "sensitive" if sensitive else
        "allowed"
    )
    return {
        "path": normalized,
        "classification": classification,
        "forbidden": forbidden,
        "approval_required": approval_required,
        "sensitive": sensitive,
        "matches": matches,
    }


def policy_approval_projection(control, 
    repo: pathlib.Path,
    policy: dict[str, Any],
    continuity: dict[str, Any] | None,
) -> dict[str, Any]:
    approvals = continuity.get("policy_approvals", []) if continuity else []
    plan = continuity.get("plan", {}) if continuity else {}
    current_plan_revision = int(plan.get("revision", 0)) if isinstance(plan, dict) else 0
    current_node = continuity.get("current_node") if continuity else None
    digest = workspace_policy_digest(control, policy)
    fingerprint = control.project_fingerprint(repo)
    projected: list[dict[str, Any]] = []
    for raw in approvals if isinstance(approvals, list) else []:
        if not isinstance(raw, dict):
            continue
        reasons: list[str] = []
        if raw.get("policy_revision") != policy["policy_revision"]:
            reasons.append("policy_revision_changed")
        if raw.get("policy_digest") != digest:
            reasons.append("policy_changed")
        if raw.get("workspace_fingerprint") != fingerprint:
            reasons.append("workspace_changed")
        if raw.get("plan_revision") != current_plan_revision:
            reasons.append("plan_revision_changed")
        if raw.get("node_id") != current_node:
            reasons.append("current_node_changed")
        projected.append({**raw, "fresh": not reasons, "stale_reasons": reasons})
    return {
        "count": len(projected),
        "fresh_count": sum(1 for approval in projected if approval["fresh"]),
        "stale_count": sum(1 for approval in projected if not approval["fresh"]),
        "latest": projected[-1] if projected else None,
        "records": projected,
    }


def sensitive_policy_evidence(control, 
    receipt: dict[str, Any] | None,
    continuity: dict[str, Any] | None,
) -> dict[str, Any]:
    validation_plan = receipt.get("validation_plan", []) if receipt else []
    current_node = continuity.get("current_node") if continuity else None
    nodes = continuity.get("plan", {}).get("nodes", []) if continuity else []
    node = next(
        (item for item in nodes if isinstance(item, dict) and item.get("id") == current_node),
        None,
    )
    outcome = node.get("outcome") if isinstance(node, dict) and isinstance(node.get("outcome"), dict) else {}
    proofs = outcome.get("proofs", []) if isinstance(outcome.get("proofs"), list) else []
    missing: list[str] = []
    if not validation_plan:
        missing.append("validation_plan")
    if not current_node:
        missing.append("current_plan_node")
    if not proofs:
        missing.append("node_proof_contract")
    return {
        "ready": not missing,
        "missing": missing,
        "current_node": current_node,
        "validation_count": len(validation_plan) if isinstance(validation_plan, list) else 0,
        "proof_contract_count": len(proofs),
        "redaction_required": True,
    }


def workspace_policy_projection(control, 
    repo: pathlib.Path,
    state: dict[str, pathlib.Path],
    receipt: dict[str, Any] | None = None,
    continuity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        policy = load_workspace_policy(control, state)
        approvals = policy_approval_projection(control, repo, policy, continuity)
    except (OSError, ValueError) as error:
        return {
            "status": "unavailable",
            "active": state["config"].exists(),
            "error": str(error),
            "revision": None,
            "rule_counts": None,
            "approvals": {"count": 0, "fresh_count": 0, "stale_count": 0, "latest": None, "records": []},
            "sensitive_evidence": sensitive_policy_evidence(control, receipt, continuity),
        }
    project_rule_count = sum(len(policy[kind]) for kind in control.WORKSPACE_POLICY_RULE_KINDS)
    effective = effective_workspace_policy_rules(control, policy)
    return {
        "status": "configured" if policy["policy_revision"] > 0 else "default",
        "active": project_rule_count > 0,
        "schema_version": policy["schema_version"],
        "revision": policy["policy_revision"],
        "digest": workspace_policy_digest(control, policy),
        "protected_branches": policy["protected_branches"],
        "rule_counts": {
            kind: len(policy[kind]) for kind in control.WORKSPACE_POLICY_RULE_KINDS
        },
        "system_rule_counts": {
            kind: len(control.SYSTEM_WORKSPACE_POLICY_RULES[kind]) for kind in control.WORKSPACE_POLICY_RULE_KINDS
        },
        "effective_rules": effective,
        "approvals": approvals,
        "sensitive_evidence": sensitive_policy_evidence(control, receipt, continuity),
        "updated_at": policy.get("updated_at"),
    }


def protected_branches(control, state: dict[str, pathlib.Path]) -> list[str]:
    if not state["config"].exists():
        return list(DEFAULT_PROTECTED_BRANCHES)
    try:
        configured = load_workspace_policy(control, state).get("protected_branches", [])
    except (OSError, ValueError):
        return list(DEFAULT_PROTECTED_BRANCHES)
    values = [str(value) for value in configured if str(value).strip()]
    return values or list(DEFAULT_PROTECTED_BRANCHES)


def is_protected(control, branch: str | None, patterns: Iterable[str]) -> bool:
    return bool(branch) and any(fnmatch.fnmatch(branch, pattern) for pattern in patterns)


def impact_inspection(control, 
    repo: pathlib.Path,
    *,
    symbols: Iterable[str],
    files: Iterable[str],
    max_depth: int = 8,
    test_filters: Iterable[str] = (),
) -> dict[str, Any]:
    from auto_dev_internal.verification import codegraph_impact

    return codegraph_impact.impact_inspection(
        control,
        repo,
        symbols=symbols,
        files=files,
        max_depth=max_depth,
        test_filters=test_filters,
    )


def impact_projection(control, 
    repo: pathlib.Path,
    continuity: dict[str, Any] | None,
) -> dict[str, Any]:
    if continuity is None:
        return {"status": "missing", "receipt_count": 0, "receipts": [], "latest": None}
    source_receipts = [
        raw for raw in continuity.get("impact_receipts", []) if isinstance(raw, dict)
    ]
    if not source_receipts:
        return {"status": "missing", "receipt_count": 0, "receipts": [], "latest": None}
    current_index = control.codegraph_index_fingerprint(repo)
    current_plan_revision = int(continuity.get("plan", {}).get("revision", 0))
    current_node = continuity.get("current_node")
    projected: list[dict[str, Any]] = []
    for raw in source_receipts:
        view = dict(raw)
        stale_reasons: list[str] = []
        if raw.get("schema_version") != control.IMPACT_RECEIPT_SCHEMA_VERSION:
            stale_reasons.append("unsupported_receipt_schema")
        codegraph = raw.get("codegraph") if isinstance(raw.get("codegraph"), dict) else {}
        recorded_index = codegraph.get("index_fingerprint")
        if current_index is None:
            stale_reasons.append("codegraph_index_missing")
        elif recorded_index != current_index:
            stale_reasons.append("codegraph_index_changed")
        raw_scope = raw.get("scope") if isinstance(raw.get("scope"), list) else []
        try:
            scope = control.normalize_scopes(repo, [str(value) for value in raw_scope])
        except ValueError:
            scope = []
            stale_reasons.append("scope_invalid")
        if not scope:
            stale_reasons.append("scope_missing")
        elif raw.get("scope_sha256") != control.workspace_scope_digest(repo, scope):
            stale_reasons.append("scope_changed")
        try:
            recorded_plan_revision = int(raw.get("plan_revision", -1))
        except (TypeError, ValueError):
            recorded_plan_revision = -1
        if recorded_plan_revision != current_plan_revision:
            stale_reasons.append("plan_revision_changed")
        if raw.get("node_id") != current_node:
            stale_reasons.append("node_not_current")
        view["fresh"] = not stale_reasons
        view["stale_reasons"] = stale_reasons
        projected.append(view)
    latest_record = next(
        (record for record in reversed(projected) if record.get("node_id") == current_node),
        projected[-1] if projected else None,
    )
    latest = None if latest_record is None else {
        key: latest_record.get(key)
        for key in (
            "receipt_id", "node_id", "plan_revision", "targets", "affected_tests", "test_discovery",
            "known_scope", "scope", "coverage_status", "coverage_reasons",
            "preservation_items", "verification_actions", "dynamic_risks", "uncertainty", "at",
            "fresh", "stale_reasons",
        )
    }
    return {
        "status": "fresh" if latest and latest.get("fresh") else ("stale" if latest else "missing"),
        "receipt_count": len(projected),
        "fresh_count": sum(1 for record in projected if record.get("fresh")),
        "stale_count": sum(1 for record in projected if not record.get("fresh")),
        "latest": latest,
        "receipts": projected,
    }


def impact_receipt_text(control, key: str, payload: dict[str, Any]) -> str:
    targets = payload.get("targets", {})
    target_count = len(targets.get("symbols", [])) + len(targets.get("files", []))
    return control.bilingual_receipt(
        "💥 Auto Dev Impact",
        key,
        f"targets={target_count}",
        f"tests={len(payload.get('affected_tests', []))}",
        f"coverage={payload.get('coverage_status', 'unknown')}",
        f"uncertainty={len(payload.get('uncertainty', []))}",
    )


def policy_receipt_text(control, key: str, *details: str) -> str:
    return control.bilingual_receipt("🚧 Auto Dev Policy", key, *details)


def load_policy_input(control, args: argparse.Namespace) -> dict[str, Any]:
    if bool(args.policy_file) == bool(args.policy_json):
        raise ValueError("provide exactly one of --policy-file or --policy-json")
    try:
        raw = (
            pathlib.Path(args.policy_file).expanduser().read_text(encoding="utf-8")
            if args.policy_file
            else args.policy_json
        )
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"workspace policy must be valid JSON: {error}") from error
    return normalize_workspace_policy(control, payload)


def command_policy(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    if args.policy_command == "inspect":
        policy = load_workspace_policy(control, state)
        evaluations = [workspace_policy_path_evaluation(control, path, policy) for path in args.path]
        payload = {
            "status": "inspected",
            "policy": workspace_policy_projection(control, repo, state),
            "paths": evaluations,
        }
        payload["receipt"] = policy_receipt_text(control, 
            "policy_inspected",
            f"revision=R{policy['policy_revision']}",
            f"paths={len(evaluations)}",
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.policy_command == "set":
        if not state["project"].is_file():
            raise ValueError("workspace policy set requires an initialized Auto Dev project")
        confirmation_source = control.require_concrete("confirmation source", args.confirmation_source)
        reason = control.require_concrete("policy reason", args.reason)
        requested = load_policy_input(control, args)
        with control.state_lock(state["config"]):
            current = load_workspace_policy(control, state)
            current_revision = int(current["policy_revision"])
            if args.policy_revision != current_revision:
                raise ValueError(
                    f"policy revision conflict: expected {current_revision}, received {args.policy_revision}"
                )
            updated = {
                **requested,
                "policy_revision": current_revision + 1,
                "confirmation_source": confirmation_source,
                "reason": reason,
                "updated_at": control.now(),
            }
            control.write_json(state["config"], updated, backup=True)
            readback = load_workspace_policy(control, state)
            if control.canonical_json(readback) != control.canonical_json(updated):
                raise ValueError("workspace policy readback differs from the requested policy")
        counts = {kind: len(updated[kind]) for kind in control.WORKSPACE_POLICY_RULE_KINDS}
        payload = {
            "status": "set",
            "policy_revision": updated["policy_revision"],
            "policy_digest": workspace_policy_digest(control, updated),
            "rule_counts": counts,
        }
        payload["receipt"] = policy_receipt_text(control, 
            "policy_set",
            f"revision=R{updated['policy_revision']}",
            f"rules={sum(counts.values())}",
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.policy_command != "approve":
        raise ValueError(f"unsupported workspace policy command: {args.policy_command}")

    state = control.ensure_root(repo)
    receipt = control.require_working_task(state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    if args.state_revision != loaded_state_revision:
        raise ValueError(
            f"policy approval state revision conflict: expected {loaded_state_revision}, received {args.state_revision}"
        )
    policy = load_workspace_policy(control, state)
    if args.policy_revision != policy["policy_revision"]:
        raise ValueError(
            f"policy approval revision conflict: expected {policy['policy_revision']}, received {args.policy_revision}"
        )
    continuity = control.continuity_from_receipt(receipt)
    if continuity is None or not continuity.get("plan", {}).get("nodes"):
        raise ValueError("policy approval requires an initialized continuity plan")
    node_id, _ = control.require_action_node(continuity, args.node)
    approved_paths = control.merge_unique(normalize_policy_path(control, path) for path in args.path)
    evaluations = [workspace_policy_path_evaluation(control, path, policy) for path in approved_paths]
    forbidden = [item["path"] for item in evaluations if item["forbidden"]]
    if forbidden:
        raise ValueError("forbidden workspace paths cannot be approved: " + ", ".join(forbidden))
    unnecessary = [item["path"] for item in evaluations if not item["approval_required"]]
    if unnecessary:
        raise ValueError("paths do not require workspace policy approval: " + ", ".join(unnecessary))
    confirmation_source = control.require_concrete("confirmation source", args.confirmation_source)
    reason = control.require_concrete("policy approval reason", args.reason)
    policy_digest = workspace_policy_digest(control, policy)
    plan_revision = int(continuity["plan"].get("revision", 0))
    identity = control.canonical_json({
        "task_id": receipt["id"],
        "policy_digest": policy_digest,
        "policy_revision": policy["policy_revision"],
        "workspace_fingerprint": control.project_fingerprint(repo),
        "plan_revision": plan_revision,
        "node_id": node_id,
        "paths": approved_paths,
    })
    approval_id = "policy-approval-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    history = continuity.setdefault("policy_approvals", [])
    existing = next(
        (item for item in history if isinstance(item, dict) and item.get("approval_id") == approval_id),
        None,
    )
    if existing is not None:
        payload = {
            "status": "existing",
            "state_revision": loaded_state_revision,
            "approval": existing,
        }
        payload["receipt"] = policy_receipt_text(control, 
            "policy_approved", f"paths={len(approved_paths)}", f"node={node_id}"
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    approval = {
        "schema_version": control.WORKSPACE_POLICY_SCHEMA_VERSION,
        "approval_id": approval_id,
        "task_id": receipt["id"],
        "policy_revision": policy["policy_revision"],
        "policy_digest": policy_digest,
        "workspace_fingerprint": control.project_fingerprint(repo),
        "plan_revision": plan_revision,
        "node_id": node_id,
        "paths": approved_paths,
        "confirmation_source": confirmation_source,
        "reason": reason,
        "state_revision": loaded_state_revision,
        "approved_at": control.now(),
    }
    history.append(approval)
    continuity["updated_at"] = control.now()
    control.continuity_event(receipt, "workspace_policy_approved", policy_approval=approval)
    next_revision = control.write_active(state, receipt, expected_revision=loaded_state_revision)
    payload = {"status": "approved", "state_revision": next_revision, "approval": approval}
    payload["receipt"] = policy_receipt_text(control, 
        "policy_approved", f"paths={len(approved_paths)}", f"node={node_id}"
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def command_impact(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    if args.impact_command == "inspect":
        inspection = impact_inspection(
            control, repo, symbols=args.symbol, files=args.file,
            max_depth=args.max_depth, test_filters=args.test_filter,
        )
        payload = {
            "status": "inspected",
            **inspection,
            "needs_uncertainty": (
                not inspection["impact_signal"] or inspection["coverage_status"] != "complete"
            ),
        }
        payload["receipt"] = impact_receipt_text(control, "impact_inspected", payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    if args.impact_command != "record":
        raise ValueError(f"unsupported impact command: {args.impact_command}")

    state = control.ensure_root(repo)
    receipt = control.require_working_task(state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    if args.state_revision != loaded_state_revision:
        raise ValueError(
            f"impact state revision conflict: expected {loaded_state_revision}, received {args.state_revision}"
        )
    continuity = control.continuity_from_receipt(receipt)
    if continuity is None or not continuity.get("plan", {}).get("nodes"):
        raise ValueError("impact record requires an initialized continuity plan")
    node_id, _ = control.require_action_node(continuity, args.node)
    preservation_items = control.merge_unique(args.preserve)
    verification_actions = control.merge_unique(args.verify)
    uncertainty = control.merge_unique(args.uncertainty)
    inspection = impact_inspection(
        control, repo, symbols=args.symbol, files=args.file,
        max_depth=args.max_depth, test_filters=args.test_filter,
    )
    needs_uncertainty = (
        not inspection["impact_signal"] or inspection["coverage_status"] != "complete"
    )
    if needs_uncertainty and not uncertainty:
        raise ValueError(
            "CodeGraph impact coverage is incomplete or has no dependency signal; record at least one --uncertainty instead of treating the result as safe"
        )
    risks = control.merge_unique(inspection["dynamic_risks"], args.risk)
    history = continuity.setdefault("impact_receipts", [])
    recorded = {
        "schema_version": control.IMPACT_RECEIPT_SCHEMA_VERSION,
        "receipt_id": f"impact-{len(history) + 1:03d}-{inspection['inspection_sha256'][:12]}",
        "task_id": receipt["id"],
        "node_id": node_id,
        "plan_revision": int(continuity["plan"].get("revision", 0)),
        "state_revision": loaded_state_revision,
        **inspection,
        "preservation_items": preservation_items,
        "verification_actions": verification_actions,
        "dynamic_risks": risks,
        "uncertainty": uncertainty,
        "branch": control.current_branch(repo),
        "head": control.git_head(repo),
        "at": control.now(),
    }
    history.append(recorded)
    continuity["updated_at"] = control.now()
    control.continuity_event(receipt, "impact_recorded", impact_receipt=recorded)
    next_revision = control.write_active(state, receipt, expected_revision=loaded_state_revision)
    payload = {
        "status": "recorded",
        "state_revision": next_revision,
        "impact": recorded,
    }
    payload["receipt"] = impact_receipt_text(control, "impact_recorded", recorded)
    print(json.dumps(payload, ensure_ascii=False))
    return 0
