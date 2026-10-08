"""Requirement intake, inherited contracts, and intake gates."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import re
from typing import Any, Iterable


def read_optional_json(control, path: pathlib.Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = control.read_json(path)
    return value if isinstance(value, dict) else None


def read_intake_gate(
    control, state: dict[str, pathlib.Path], session_key: str | None
) -> dict[str, Any]:
    if not session_key:
        return {"status": "unobserved"}
    path = control.intake_gate_path(state, session_key)
    value = read_optional_json(control, path)
    if value is None:
        return {"status": "unobserved", "session_key": session_key}
    if value.get("session_key") != session_key:
        raise ValueError("intake gate belongs to a different session")
    value.setdefault("schema_version", control.INTAKE_SCHEMA_VERSION)
    value.setdefault("status", "pending")
    return value


def write_intake_gate(control, state: dict[str, pathlib.Path], gate: dict[str, Any]) -> None:
    session_key = str(gate.get("session_key") or "")
    path = control.intake_gate_path(state, session_key)
    gate["schema_version"] = control.INTAKE_SCHEMA_VERSION
    gate["state_revision"] = int(gate.get("state_revision", 0)) + 1
    gate["updated_at"] = control.now()
    control.write_json(path, gate, backup=True)


def read_intake_record(
    control, state: dict[str, pathlib.Path], context_id: str, intake_id: str
) -> dict[str, Any]:
    path = control.intake_record_path(state, context_id, intake_id)
    if not path.exists():
        raise ValueError(f"intake record does not exist: {intake_id}")
    record = control.read_json(path)
    if not isinstance(record, dict) or record.get("id") != intake_id:
        raise ValueError(f"intake record is malformed: {intake_id}")
    return record


def find_intake_record(
    control, state: dict[str, pathlib.Path], project: dict[str, Any], intake_id: str
) -> tuple[str, dict[str, Any]]:
    normalized_id = control.require_control_id("intake id", intake_id)
    for context_id in project.get("contexts", {}):
        path = control.intake_record_path(state, str(context_id), normalized_id)
        if path.exists():
            return (
                str(context_id),
                read_intake_record(control, state, str(context_id), normalized_id),
            )
    raise ValueError(f"intake record does not exist: {normalized_id}")


def intake_baseline_hash(control, record: dict[str, Any]) -> str:
    keys = (
        "id",
        "depth",
        "project_context_id",
        "outcome_id",
        "task_id",
        "summary",
        "goal",
        "inference",
        "scope",
        "acceptance",
        "non_goals",
        "assumptions",
        "repository_facts",
        "expert_completions",
        "decisions",
        "contract",
    )
    canonical = {key: record.get(key) for key in keys}
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def contract_from_args(
    control,
    args: argparse.Namespace,
    source: dict[str, Any],
    *,
    default_id: str,
    default_mainline: str = "",
    parent_refs: Iterable[str] = (),
) -> dict[str, Any] | None:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.contract_from_args(
        control,
        args,
        source,
        default_id=default_id,
        default_mainline=default_mainline,
        parent_refs=parent_refs,
    )


def contract_status(control, contract: dict[str, Any] | None) -> str:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.contract_status(control, contract)


def strict_contract_hash(control, contract: dict[str, Any] | None) -> str | None:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.strict_contract_hash(control, contract)


def strict_receipt_contract_hash(control, receipt: dict[str, Any]) -> str | None:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.strict_receipt_contract_hash(control, receipt)


def outcome_identity_contract(control, record: dict[str, Any]) -> dict[str, Any]:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.outcome_identity_contract(control, record)


def outcome_contract_chain(
    control,
    state: dict[str, pathlib.Path],
    context_id: str,
    outcome_id: str | None,
    *,
    inherited: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.outcome_contract_chain(
        control, state, context_id, outcome_id, inherited=inherited
    )


def parent_contract_for_task(
    control,
    state: dict[str, pathlib.Path],
    repo: pathlib.Path,
    context_id: str,
    outcome_id: str | None,
    intake_id: str | None,
) -> dict[str, Any] | None:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.parent_contract_for_task(
        control, state, repo, context_id, outcome_id, intake_id
    )


def effective_contract_for_outcome(
    control,
    state: dict[str, pathlib.Path],
    repo: pathlib.Path,
    project: dict[str, Any],
    context_id: str,
    outcome_id: str,
) -> dict[str, Any] | None:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.effective_contract_for_outcome(
        control, state, repo, project, context_id, outcome_id
    )


def require_contract_diff_confirmation(control, value: str | None, *, action: str) -> str:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.require_contract_diff_confirmation(control, value, action=action)


def effective_contract_for_task(
    control,
    state: dict[str, pathlib.Path],
    repo: pathlib.Path,
    context_id: str,
    outcome_id: str | None,
    intake_id: str | None,
    local_contract: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.effective_contract_for_task(
        control, state, repo, context_id, outcome_id, intake_id, local_contract
    )


def contract_projection(
    control,
    receipt: dict[str, Any],
    continuity: dict[str, Any] | None,
    *,
    repo: pathlib.Path | None = None,
) -> dict[str, Any]:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.contract_projection(control, receipt, continuity, repo=repo)


def contract_gate_for_receipt(
    control,
    repo: pathlib.Path,
    state: dict[str, pathlib.Path],
    receipt: dict[str, Any],
    continuity: dict[str, Any] | None,
) -> dict[str, Any]:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.contract_gate_for_receipt(control, repo, state, receipt, continuity)


def validate_contract_plan(control, receipt: dict[str, Any], nodes: list[dict[str, Any]]) -> None:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.validate_contract_plan(control, receipt, nodes)


def validate_contract_readiness(
    control,
    receipt: dict[str, Any],
    continuity: dict[str, Any] | None,
    *,
    complete: bool,
    repo: pathlib.Path | None = None,
) -> None:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.validate_contract_readiness(
        control, receipt, continuity, complete=complete, repo=repo
    )


def validate_node_contract_proofs(
    control,
    repo: pathlib.Path,
    receipt: dict[str, Any],
    continuity: dict[str, Any],
    node: dict[str, Any],
) -> None:
    from auto_dev_internal.intake import contract as runctl_contract

    return runctl_contract.validate_node_contract_proofs(control, repo, receipt, continuity, node)


def intake_summary(control, record: dict[str, Any]) -> dict[str, Any]:
    decisions = record.get("decisions") if isinstance(record.get("decisions"), list) else []
    contract = record.get("contract") if isinstance(record.get("contract"), dict) else None
    return {
        "id": record.get("id"),
        "depth": record.get("depth"),
        "status": record.get("status"),
        "state_revision": record.get("state_revision", 0),
        "baseline_hash": record.get("baseline_hash"),
        "project_context_id": record.get("project_context_id"),
        "outcome_id": record.get("outcome_id"),
        "task_id": record.get("task_id"),
        "pending_decision_count": sum(
            (
                1
                for decision in decisions
                if isinstance(decision, dict) and decision.get("status") == "pending"
            )
        ),
        "contract_status": contract_status(control, contract),
        "contract_hash": contract.get("hash") if contract else None,
        "updated_at": record.get("updated_at"),
    }


def intake_gate_projection(
    control, state: dict[str, pathlib.Path], session_key: str | None
) -> dict[str, Any]:
    gate = read_intake_gate(control, state, session_key)
    if gate.get("status") == "unobserved":
        return gate
    projection = {
        key: gate.get(key)
        for key in (
            "status",
            "session_key",
            "pending_turn_id",
            "classification",
            "intake_id",
            "project_context_id",
            "outcome_id",
            "task_id",
            "state_revision",
            "updated_at",
        )
    }
    intake_id = gate.get("intake_id")
    context_id = gate.get("project_context_id")
    if isinstance(intake_id, str) and isinstance(context_id, str):
        try:
            projection["intake"] = intake_summary(
                control, read_intake_record(control, state, context_id, intake_id)
            )
        except (OSError, json.JSONDecodeError, ValueError):
            projection["intake"] = {"id": intake_id, "status": "unreadable"}
    return projection


def require_pending_turn(
    control, state: dict[str, pathlib.Path], session_key: str, turn_id: str
) -> dict[str, Any]:
    gate = read_intake_gate(control, state, session_key)
    if gate.get("status") == "unobserved" or gate.get("pending_turn_id") != turn_id:
        raise ValueError("Intake mutation must bind to the current pending user turn")
    return gate


def decode_json_object(control, label: str, value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} must be valid JSON: {error.msg}") from error
    if not isinstance(decoded, dict):
        raise ValueError(f"{label} must be a JSON object")
    return decoded


def decode_json_decisions(control, values: Iterable[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for value in values:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"decision JSON must be valid: {error.msg}") from error
        candidates = decoded if isinstance(decoded, list) else [decoded]
        if not all((isinstance(candidate, dict) for candidate in candidates)):
            raise ValueError("decision JSON must contain decision objects")
        result.extend((candidate for candidate in candidates if isinstance(candidate, dict)))
    return result


def normalize_intake_decisions(control, raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("intake decisions must be a list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, decision in enumerate(raw, start=1):
        if not isinstance(decision, dict):
            raise ValueError("each intake decision must be an object")
        decision_id = control.require_control_id(
            "decision id", str(decision.get("id") or f"decision-{index}")
        )
        if decision_id in seen:
            raise ValueError(f"duplicate intake decision id: {decision_id}")
        seen.add(decision_id)
        status = str(decision.get("status") or "pending")
        if status not in control.INTAKE_DECISION_STATUSES:
            raise ValueError(f"unsupported intake decision status: {status}")
        normalized = {
            "id": decision_id,
            "question": control.require_concrete(
                "intake decision question", str(decision.get("question") or "")
            ),
            "impact": control.require_concrete(
                "intake decision impact", str(decision.get("impact") or "")
            ),
            "recommendation": control.require_concrete(
                "intake decision recommendation", str(decision.get("recommendation") or "")
            ),
            "status": status,
        }
        if decision.get("resolution") is not None:
            normalized["resolution"] = decision["resolution"]
        result.append(normalized)
    return result


def intake_text_list(control, label: str, value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return [control.require_concrete(label, str(item)) for item in value]


def command_intake_turn(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    session_key = control.require_session_key(args.session_key)
    turn_id = control.require_concrete("turn id", args.turn_id)
    with control.state_lock(state["project"]):
        existing = read_intake_gate(control, state, session_key)
        if existing.get("pending_turn_id") == turn_id and existing.get("status") == "pending":
            gate = existing
            created = False
        else:
            gate = {
                "schema_version": control.INTAKE_SCHEMA_VERSION,
                "session_key": session_key,
                "pending_turn_id": turn_id,
                "status": "pending",
                "classification": None,
                "intake_id": None,
                "project_context_id": None,
                "outcome_id": None,
                "task_id": args.task_id or None,
                "created_at": control.now(),
                "updated_at": control.now(),
                "state_revision": int(existing.get("state_revision", 0)),
            }
            write_intake_gate(control, state, gate)
            created = True
    print(
        json.dumps(
            {
                "status": "pending",
                "created": created,
                "turn_id": turn_id,
                "session_key": session_key,
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "intake_turn_pending", f"turn={turn_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_intake_status(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    session_key = control.require_session_key(args.session_key)
    print(json.dumps(intake_gate_projection(control, state, session_key), ensure_ascii=False))
    return 0


def command_intake_assess(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    session_key = control.require_session_key(args.session_key)
    turn_id = control.require_concrete("turn id", args.turn_id)
    source = decode_json_object(control, "assessment JSON", args.assessment_json)
    depth = str(args.depth or source.get("depth") or "")
    if depth not in control.INTAKE_DEPTHS:
        raise ValueError("intake depth must be clear, clarify, deep, or project-discovery")
    decisions = normalize_intake_decisions(
        control,
        (
            decode_json_decisions(control, args.decision_json)
            if args.decision_json
            else source.get("decisions")
        ),
    )
    pending_decisions = [item for item in decisions if item["status"] == "pending"]
    if depth == "clear" and pending_decisions:
        raise ValueError("clear intake cannot retain pending decisions")
    if depth == "clarify" and (not pending_decisions):
        raise ValueError("clarify intake requires one to three pending decisions")
    if depth == "clarify" and len(pending_decisions) > 3:
        raise ValueError("clarify intake may ask at most three pending decisions")
    with control.state_lock(state["project"]):
        gate = require_pending_turn(control, state, session_key, turn_id)
        project = control.load_project(state, repo) or control.blank_project(repo)
        (context_id, context_created) = control.ensure_default_project_context(state, project)
        requested_context = args.project_context or source.get("project_context_id")
        if requested_context:
            context_id = control.require_control_id("project context id", str(requested_context))
            control.resolve_project_context(state, project, context_id)
        (entry, _) = control.resolve_project_context(state, project, context_id)
        outcome_id = args.outcome_id or source.get("outcome_id")
        if outcome_id:
            outcome_id = control.require_control_id("outcome id", str(outcome_id))
            if not control.outcome_record_path(state, context_id, outcome_id).exists():
                raise ValueError(
                    f"outcome does not exist in the selected project context: {outcome_id}"
                )
        intake_id = control.require_control_id(
            "intake id",
            args.intake_id or str(source.get("id") or control.generated_control_id("INTAKE")),
        )
        contract = contract_from_args(
            control,
            args,
            source,
            default_id=f"{intake_id}-CONTRACT",
            default_mainline=str(args.goal or source.get("goal") or ""),
        )
        record = {
            "schema_version": control.INTAKE_SCHEMA_VERSION,
            "id": intake_id,
            "depth": depth,
            "status": "confirmed" if depth == "clear" else "awaiting_decisions",
            "project_context_id": context_id,
            "outcome_id": outcome_id,
            "task_id": args.task_id or source.get("task_id") or gate.get("task_id"),
            "summary": control.require_concrete(
                "intake summary", str(args.summary or source.get("summary") or "")
            ),
            "goal": control.require_concrete(
                "intake goal", str(args.goal or source.get("goal") or "")
            ),
            "inference": control.require_concrete(
                "intake inference", str(args.inference or source.get("inference") or "")
            ),
            "scope": intake_text_list(
                control, "intake scope", args.scope if args.scope else source.get("scope")
            ),
            "acceptance": intake_text_list(
                control,
                "intake acceptance",
                args.acceptance if args.acceptance else source.get("acceptance"),
            ),
            "non_goals": intake_text_list(
                control,
                "intake non-goal",
                args.non_goal if args.non_goal else source.get("non_goals"),
            ),
            "assumptions": intake_text_list(
                control,
                "intake assumption",
                args.assumption if args.assumption else source.get("assumptions"),
            ),
            "repository_facts": intake_text_list(
                control,
                "repository fact",
                args.fact if args.fact else source.get("repository_facts"),
            ),
            "expert_completions": intake_text_list(
                control,
                "expert completion",
                (
                    args.expert_completion
                    if args.expert_completion
                    else source.get("expert_completions")
                ),
            ),
            "decisions": decisions,
            "contract": contract,
            "source_turn": {
                "turn_id": turn_id,
                "session_key": session_key,
                "recorded_at": control.now(),
            },
            "state_revision": 1,
            "created_at": control.now(),
            "updated_at": control.now(),
        }
        if depth in {"deep", "project-discovery"} and (not pending_decisions):
            record["status"] = "awaiting_confirmation"
        if depth == "clear":
            record["confirmation"] = {
                "kind": "autonomous_clear",
                "turn_id": turn_id,
                "session_key": session_key,
                "at": control.now(),
            }
            gate_status = "authorized"
        elif depth == "clarify":
            gate_status = "awaiting_user"
        else:
            gate_status = "awaiting_user" if pending_decisions else "awaiting_confirmation"
        record["baseline_hash"] = intake_baseline_hash(control, record)
        control.write_json(
            control.intake_record_path(state, context_id, intake_id), record, backup=True
        )
        if depth == "clear":
            control.promote_contract_to_frame(state, context_id, contract)
        gate.update(
            {
                "status": gate_status,
                "classification": depth,
                "intake_id": intake_id,
                "project_context_id": context_id,
                "outcome_id": outcome_id,
                "task_id": record["task_id"],
            }
        )
        write_intake_gate(control, state, gate)
        if context_created or not state["project"].exists():
            project["schema_version"] = control.PROJECT_SCHEMA_VERSION
        project_revision = control.write_project_control(state, project)
        _ = entry
    key = f"intake_{depth.replace('-', '_')}"
    print(
        json.dumps(
            {
                "status": record["status"],
                "intake": intake_summary(control, record),
                "project_revision": project_revision,
                "gate": intake_gate_projection(control, state, session_key),
                "receipt": control.bilingual_receipt("🧾 Auto Dev", key, f"intake={intake_id}"),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_intake_resolve(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    session_key = control.require_session_key(args.session_key)
    turn_id = control.require_concrete("turn id", args.turn_id)
    decision_id = control.require_control_id("decision id", args.decision_id)
    decision_status = args.status
    if decision_status not in {"accepted", "deferred", "excluded"}:
        raise ValueError("intake decision resolution must be accepted, deferred, or excluded")
    with control.state_lock(state["project"]):
        gate = require_pending_turn(control, state, session_key, turn_id)
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("intake resolution requires an initialized project control")
        (context_id, record) = find_intake_record(control, state, project, args.intake_id)
        actual_revision = int(record.get("state_revision", 0))
        if args.intake_revision != actual_revision:
            raise ValueError(
                f"intake revision conflict: expected {actual_revision}, received {args.intake_revision}"
            )
        if record.get("status") not in {"awaiting_decisions", "awaiting_confirmation"}:
            raise ValueError("only a pending intake can resolve decisions")
        source_turn = (
            record.get("source_turn") if isinstance(record.get("source_turn"), dict) else {}
        )
        if source_turn.get("turn_id") == turn_id:
            raise ValueError("intake decisions require a later user turn")
        decisions = record.get("decisions") if isinstance(record.get("decisions"), list) else []
        decision = next(
            (
                item
                for item in decisions
                if isinstance(item, dict) and item.get("id") == decision_id
            ),
            None,
        )
        if decision is None:
            raise ValueError(f"intake decision does not exist: {decision_id}")
        if decision.get("status") != "pending":
            raise ValueError("intake decision has already been resolved")
        decision.update(
            {
                "status": decision_status,
                "resolution": control.require_concrete("decision resolution", args.resolution),
                "resolution_source": control.require_concrete(
                    "decision resolution source", args.source
                ),
                "resolved_turn_id": turn_id,
                "resolved_at": control.now(),
            }
        )
        pending = [
            item for item in decisions if isinstance(item, dict) and item.get("status") == "pending"
        ]
        if not pending and record.get("depth") == "clarify":
            record["status"] = "confirmed"
            record["confirmation"] = {
                "kind": "clarify_decisions_resolved",
                "turn_id": turn_id,
                "session_key": session_key,
                "at": control.now(),
            }
            gate_status = "authorized"
        elif not pending:
            record["status"] = "awaiting_confirmation"
            gate_status = "awaiting_confirmation"
        else:
            record["status"] = "awaiting_decisions"
            gate_status = "awaiting_user"
        record["state_revision"] = actual_revision + 1
        record["updated_at"] = control.now()
        record["baseline_hash"] = intake_baseline_hash(control, record)
        control.write_json(
            control.intake_record_path(state, context_id, record["id"]), record, backup=True
        )
        if gate_status == "authorized":
            control.promote_contract_to_frame(state, context_id, record.get("contract"))
        gate.update(
            {
                "status": gate_status,
                "classification": record.get("depth"),
                "intake_id": record.get("id"),
                "project_context_id": context_id,
                "outcome_id": record.get("outcome_id"),
                "task_id": record.get("task_id"),
            }
        )
        write_intake_gate(control, state, gate)
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": record["status"],
                "intake": intake_summary(control, record),
                "project_revision": project_revision,
                "gate": intake_gate_projection(control, state, session_key),
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev",
                    "intake_decision_resolved",
                    f"intake={record['id']}",
                    f"decision={decision_id}",
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_intake_confirm(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    session_key = control.require_session_key(args.session_key)
    turn_id = control.require_concrete("turn id", args.turn_id)
    with control.state_lock(state["project"]):
        gate = require_pending_turn(control, state, session_key, turn_id)
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("intake confirmation requires an initialized project control")
        (context_id, record) = find_intake_record(control, state, project, args.intake_id)
        actual_revision = int(record.get("state_revision", 0))
        if args.intake_revision != actual_revision:
            raise ValueError(
                f"intake revision conflict: expected {actual_revision}, received {args.intake_revision}"
            )
        if record.get("depth") not in {"deep", "project-discovery"}:
            raise ValueError("only deep or project-discovery intakes require final confirmation")
        source_turn = (
            record.get("source_turn") if isinstance(record.get("source_turn"), dict) else {}
        )
        if source_turn.get("turn_id") == turn_id:
            raise ValueError("final intake confirmation requires a later user turn")
        pending = [
            item
            for item in record.get("decisions", [])
            if isinstance(item, dict) and item.get("status") == "pending"
        ]
        if pending:
            raise ValueError("all intake decisions must be resolved before confirmation")
        record["status"] = "confirmed"
        record["confirmation"] = {
            "kind": "explicit_requirement_baseline",
            "source": control.require_concrete("confirmation source", args.confirmation_source),
            "turn_id": turn_id,
            "session_key": session_key,
            "at": control.now(),
        }
        record["state_revision"] = actual_revision + 1
        record["updated_at"] = control.now()
        record["baseline_hash"] = intake_baseline_hash(control, record)
        control.write_json(
            control.intake_record_path(state, context_id, record["id"]), record, backup=True
        )
        control.promote_contract_to_frame(state, context_id, record.get("contract"))
        gate.update(
            {
                "status": "authorized",
                "classification": record.get("depth"),
                "intake_id": record.get("id"),
                "project_context_id": context_id,
                "outcome_id": record.get("outcome_id"),
                "task_id": record.get("task_id"),
            }
        )
        write_intake_gate(control, state, gate)
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": "confirmed",
                "intake": intake_summary(control, record),
                "project_revision": project_revision,
                "gate": intake_gate_projection(control, state, session_key),
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "intake_confirmed", f"intake={record['id']}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_intake_reopen(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    session_key = control.require_session_key(args.session_key)
    turn_id = control.require_concrete("turn id", args.turn_id)
    with control.state_lock(state["project"]):
        gate = require_pending_turn(control, state, session_key, turn_id)
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("intake reopen requires an initialized project control")
        (context_id, record) = find_intake_record(control, state, project, args.intake_id)
        actual_revision = int(record.get("state_revision", 0))
        if args.intake_revision != actual_revision:
            raise ValueError(
                f"intake revision conflict: expected {actual_revision}, received {args.intake_revision}"
            )
        record["status"] = "reopened"
        record["reopened"] = {
            "reason": control.require_concrete("reopen reason", args.reason),
            "turn_id": turn_id,
            "at": control.now(),
        }
        record["state_revision"] = actual_revision + 1
        record["updated_at"] = control.now()
        control.write_json(
            control.intake_record_path(state, context_id, record["id"]), record, backup=True
        )
        gate.update(
            {
                "status": "pending",
                "classification": None,
                "intake_id": None,
                "project_context_id": context_id,
                "outcome_id": record.get("outcome_id"),
                "task_id": record.get("task_id"),
            }
        )
        write_intake_gate(control, state, gate)
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": "reopened",
                "intake": intake_summary(control, record),
                "project_revision": project_revision,
                "gate": intake_gate_projection(control, state, session_key),
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "intake_reopened", f"intake={record['id']}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_intake_show(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    project = control.load_project(state, repo)
    if project is None:
        raise ValueError("intake show requires an initialized project control")
    (context_id, record) = find_intake_record(control, state, project, args.intake_id)
    print(
        json.dumps(
            {"project_context_id": context_id, "intake": record}, ensure_ascii=False, indent=2
        )
    )
    return 0
