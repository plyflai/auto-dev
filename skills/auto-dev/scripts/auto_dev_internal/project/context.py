"""Managed project contexts, outcome DAGs, capabilities, activity, and focus."""

from __future__ import annotations
import argparse
import copy
import json
import pathlib
import re
from typing import Any, Iterable


def normalize_external_references(control, values: Iterable[str]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for value in values:
        decoded = control.decode_json_object("external reference JSON", value)
        repository = control.require_concrete(
            "external repository", str(decoded.get("repository") or "")
        )
        label = control.require_concrete("external context label", str(decoded.get("label") or ""))
        status = str(decoded.get("status") or "needs-recheck")
        if status not in {"verified", "stale", "needs-recheck", "blocked"}:
            raise ValueError(f"unsupported external reference status: {status}")
        reference = {"repository": repository, "label": label, "status": status}
        for field in ("initiative_ref", "contract_ref", "owner", "observed_version", "observed_at"):
            if decoded.get(field) is not None:
                reference[field] = control.require_concrete(
                    f"external reference {field}", str(decoded[field])
                )
        if any(
            (
                key in decoded
                for key in ("control_root", "state_path", "foreign_state", "mutation_command")
            )
        ):
            raise ValueError(
                "cross-repository references may not contain foreign control-state handles"
            )
        references.append(reference)
    return references


def command_project_context_list(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    project = control.load_project(state, repo)
    if project is None:
        print(json.dumps({"status": "uninitialized", "contexts": []}, ensure_ascii=False))
        return 0
    contexts = []
    for context_id, entry in project.get("contexts", {}).items():
        if not isinstance(entry, dict):
            continue
        summary = control.context_summary(entry)
        summary["selected"] = context_id == project.get("default_context_id")
        try:
            frame = control.read_context_frame(state, str(context_id))
            summary["mission"] = frame.get("mission")
            summary["authority_boundary"] = frame.get("authority_boundary")
        except (OSError, json.JSONDecodeError, ValueError):
            summary["frame_status"] = "unreadable"
        contexts.append(summary)
    print(
        json.dumps(
            {
                "status": "ready",
                "project_id": project.get("project_id"),
                "project_revision": project.get("state_revision", 0),
                "default_context_id": project.get("default_context_id"),
                "contexts": contexts,
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_project_context_show(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    project = control.load_project(state, repo)
    if project is None:
        raise ValueError("project context show requires an initialized project control")
    (entry, frame) = control.resolve_project_context(state, project, args.context_id)
    print(
        json.dumps(
            {
                "project_id": project.get("project_id"),
                "project_revision": project.get("state_revision", 0),
                "selected": entry.get("id") == project.get("default_context_id"),
                "context": frame,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_project_context_adopt(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    context_id = control.require_control_id("project context id", args.context_id)
    lifecycle = args.lifecycle
    coverage = args.coverage
    if lifecycle not in control.PROJECT_CONTEXT_LIFECYCLES:
        raise ValueError(f"unsupported project context lifecycle: {lifecycle}")
    if coverage not in control.PROJECT_CONTEXT_COVERAGE:
        raise ValueError(f"unsupported project context coverage: {coverage}")
    with control.state_lock(state["project"]):
        project = control.load_project(state, repo) or control.blank_project(repo)
        control.require_project_revision(project, args.project_revision)
        if context_id in project.get("contexts", {}):
            raise ValueError(f"project context already exists: {context_id}")
        created_at = control.now()
        title = control.require_concrete("project context title", args.title)
        unlinked_outcome_id = control.default_unlinked_outcome_id(context_id)
        entry = {
            "id": context_id,
            "title": title,
            "lifecycle": lifecycle,
            "coverage": coverage,
            "unlinked_outcome_id": unlinked_outcome_id,
            "created_at": created_at,
            "updated_at": created_at,
        }
        frame = {
            "schema_version": control.PROJECT_CONTEXT_SCHEMA_VERSION,
            "id": context_id,
            "title": title,
            "lifecycle": lifecycle,
            "coverage": coverage,
            "authority_boundary": control.require_concrete(
                "authority boundary", args.authority_boundary
            ),
            "delivery_boundary": control.require_concrete(
                "delivery boundary", args.delivery_boundary
            ),
            "context_boundary": control.require_concrete("context boundary", args.context_boundary),
            "mission": args.mission.strip() if args.mission else None,
            "external_context": normalize_external_references(control, args.external_ref_json),
            "evidence_sources": [
                control.require_concrete("evidence source", value) for value in args.evidence_source
            ],
            "created_at": created_at,
            "updated_at": created_at,
        }
        unlinked = control.system_unlinked_outcome(context_id, unlinked_outcome_id, created_at)
        project["contexts"][context_id] = entry
        if args.select or not project.get("default_context_id"):
            project["default_context_id"] = context_id
        control.write_context_frame(state, frame)
        control.write_json(
            control.outcome_record_path(state, context_id, unlinked_outcome_id), unlinked
        )
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": "adopted",
                "project_id": project.get("project_id"),
                "project_revision": project_revision,
                "context": control.context_summary(entry),
                "selected": project.get("default_context_id") == context_id,
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "project_context_adopted", f"context={context_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_project_context_set(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    context_id = control.require_control_id("project context id", args.context_id)
    with control.state_lock(state["project"]):
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("project context set requires an initialized project control")
        control.require_project_revision(project, args.project_revision)
        (entry, frame) = control.resolve_project_context(state, project, context_id)
        changed = False
        if args.title:
            title = control.require_concrete("project context title", args.title)
            entry["title"] = title
            frame["title"] = title
            changed = True
        if args.lifecycle:
            if args.lifecycle not in control.PROJECT_CONTEXT_LIFECYCLES:
                raise ValueError(f"unsupported project context lifecycle: {args.lifecycle}")
            entry["lifecycle"] = args.lifecycle
            frame["lifecycle"] = args.lifecycle
            changed = True
        if args.coverage:
            if args.coverage not in control.PROJECT_CONTEXT_COVERAGE:
                raise ValueError(f"unsupported project context coverage: {args.coverage}")
            entry["coverage"] = args.coverage
            frame["coverage"] = args.coverage
            changed = True
        for argument, field, label in (
            (args.authority_boundary, "authority_boundary", "authority boundary"),
            (args.delivery_boundary, "delivery_boundary", "delivery boundary"),
            (args.context_boundary, "context_boundary", "context boundary"),
            (args.mission, "mission", "mission"),
        ):
            if argument is not None:
                frame[field] = control.require_concrete(label, argument)
                changed = True
        if args.external_ref_json:
            frame["external_context"] = normalize_external_references(
                control, args.external_ref_json
            )
            changed = True
        if args.evidence_source:
            frame["evidence_sources"] = [
                control.require_concrete("evidence source", value) for value in args.evidence_source
            ]
            changed = True
        if not changed:
            raise ValueError("project context set requires at least one changed field")
        updated_at = control.now()
        entry["updated_at"] = updated_at
        frame["updated_at"] = updated_at
        control.write_context_frame(state, frame)
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": "updated",
                "project_revision": project_revision,
                "context": control.context_summary(entry),
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "project_context_adopted", f"context={context_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_project_context_select(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    context_id = control.require_control_id("project context id", args.context_id)
    with control.state_lock(state["project"]):
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("project context selection requires an initialized project control")
        control.require_project_revision(project, args.project_revision)
        control.resolve_project_context(state, project, context_id)
        project["default_context_id"] = context_id
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": "selected",
                "project_context_id": context_id,
                "project_revision": project_revision,
                "execution_focus_changed": False,
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "project_context_selected", f"context={context_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def read_outcome_record(
    control, state: dict[str, pathlib.Path], context_id: str, outcome_id: str
) -> dict[str, Any]:
    path = control.outcome_record_path(state, context_id, outcome_id)
    if not path.exists():
        raise ValueError(f"outcome does not exist: {outcome_id}")
    record = control.read_json(path)
    if not isinstance(record, dict) or record.get("id") != outcome_id:
        raise ValueError(f"outcome record is malformed: {outcome_id}")
    if record.get("project_context_id") != context_id:
        raise ValueError(f"outcome belongs to a different project context: {outcome_id}")
    return record


def list_outcome_records(
    control, state: dict[str, pathlib.Path], context_id: str
) -> list[dict[str, Any]]:
    directory = control.context_outcomes_directory(state, context_id)
    if not directory.exists():
        return []
    outcomes = []
    for path in sorted(directory.glob("*.json")):
        try:
            record = control.read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(record, dict)
            and record.get("project_context_id") == context_id
            and record.get("id")
        ):
            outcomes.append(record)
    return outcomes


def outcome_summary(control, record: dict[str, Any]) -> dict[str, Any]:
    relations = record.get("relations") if isinstance(record.get("relations"), list) else []
    contract = record.get("contract") if isinstance(record.get("contract"), dict) else None
    return {
        "id": record.get("id"),
        "title": record.get("title"),
        "statement": record.get("statement"),
        "status": record.get("status"),
        "parent_id": record.get("parent_id"),
        "relation_count": len(relations),
        "intake_id": record.get("intake_id"),
        "system_generated": record.get("system_generated", False),
        "state_revision": record.get("state_revision", 0),
        "contract_status": control.contract_status(contract),
        "contract_hash": contract.get("hash") if contract else None,
        "updated_at": record.get("updated_at"),
    }


def outcome_coverage_rollup(
    control,
    state: dict[str, pathlib.Path],
    context_id: str,
    outcome_id: str,
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """Aggregate child-task evidence without making a second outcome state tree."""
    required = set(control.contract_coverage_ids(contract))
    if not required:
        return {"required": [], "owned": [], "passed": [], "missing": [], "task_ids": []}
    outcomes = list_outcome_records(control, state, context_id)
    descendants = {outcome_id}
    changed = True
    while changed:
        changed = False
        for record in outcomes:
            if record.get("parent_id") in descendants and record.get("id") not in descendants:
                descendants.add(str(record["id"]))
                changed = True
    owned: set[str] = set()
    passed: set[str] = set()
    task_ids: list[str] = []
    for path in state["tasks"].glob("*.json"):
        try:
            receipt = control.normalize_receipt(control.read_json(path))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if (
            receipt.get("project_context_id") != context_id
            or receipt.get("primary_outcome_id") not in descendants
        ):
            continue
        task_ids.append(str(receipt.get("id") or path.stem))
        owned.update((str(value) for value in receipt.get("contract_coverage_ids", []) if value))
        continuity = control.continuity_from_receipt(receipt)
        proofs = continuity.get("proofs", []) if continuity else receipt.get("proofs", [])
        for proof in proofs:
            if isinstance(proof, dict) and proof.get("status") == "passed":
                passed.update((str(value) for value in proof.get("coverage_ids", []) if value))
    return {
        "required": sorted(required),
        "owned": sorted(required & owned),
        "passed": sorted(required & passed),
        "missing": sorted(required - passed),
        "task_ids": sorted(task_ids),
    }


def outcome_edges(control, records: Iterable[dict[str, Any]]) -> dict[str, set[str]]:
    edges: dict[str, set[str]] = {}
    for record in records:
        outcome_id = record.get("id")
        if not isinstance(outcome_id, str):
            continue
        edges.setdefault(outcome_id, set())
        parent_id = record.get("parent_id")
        if isinstance(parent_id, str):
            edges.setdefault(parent_id, set()).add(outcome_id)
        relations = record.get("relations") if isinstance(record.get("relations"), list) else []
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            target_id = relation.get("target_id")
            if isinstance(target_id, str):
                edges[outcome_id].add(target_id)
                edges.setdefault(target_id, set())
    return edges


def outcome_graph_has_cycle(control, records: Iterable[dict[str, Any]]) -> bool:
    edges = outcome_edges(control, records)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        try:
            return any((visit(child) for child in edges.get(node, set())))
        finally:
            visiting.discard(node)
            visited.add(node)

    return any((visit(node) for node in edges))


def validate_outcome_graph(control, records: Iterable[dict[str, Any]]) -> None:
    records = list(records)
    ids = {record.get("id") for record in records if isinstance(record.get("id"), str)}
    for record in records:
        outcome_id = record.get("id")
        parent_id = record.get("parent_id")
        if parent_id is not None and parent_id not in ids:
            raise ValueError(f"outcome parent does not exist: {parent_id}")
        if parent_id == outcome_id:
            raise ValueError("outcome cannot contain itself")
        for relation in record.get("relations", []):
            if not isinstance(relation, dict):
                raise ValueError("outcome relation must be an object")
            relation_type = relation.get("type")
            target_id = relation.get("target_id")
            if relation_type not in control.OUTCOME_RELATIONS - {"contains"}:
                raise ValueError(f"unsupported outcome relation: {relation_type}")
            if target_id not in ids:
                raise ValueError(f"outcome relation target does not exist: {target_id}")
            if target_id == outcome_id:
                raise ValueError("outcome cannot relate to itself")
    if outcome_graph_has_cycle(control, records):
        raise ValueError("outcome graph must remain acyclic")


def confirmed_intake_for_context(
    control,
    state: dict[str, pathlib.Path],
    project: dict[str, Any],
    intake_id: str | None,
    context_id: str,
) -> dict[str, Any] | None:
    if not intake_id:
        return None
    (found_context, intake) = control.find_intake_record(state, project, intake_id)
    if found_context != context_id:
        raise ValueError("intake belongs to a different project context")
    if intake.get("status") != "confirmed":
        raise ValueError("task or outcome attribution requires a confirmed intake baseline")
    return intake


def command_outcome_list(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    project = control.load_project(state, repo)
    if project is None:
        print(json.dumps({"status": "uninitialized", "outcomes": []}, ensure_ascii=False))
        return 0
    (entry, _) = control.resolve_project_context(state, project, args.project_context)
    outcomes = list_outcome_records(control, state, str(entry["id"]))
    validate_outcome_graph(control, outcomes)
    print(
        json.dumps(
            {
                "status": "ready",
                "project_context_id": entry["id"],
                "project_revision": project.get("state_revision", 0),
                "outcomes": [outcome_summary(control, record) for record in outcomes],
                "edges": {
                    source: sorted(targets)
                    for (source, targets) in outcome_edges(control, outcomes).items()
                    if targets
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_outcome_show(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    project = control.load_project(state, repo)
    if project is None:
        raise ValueError("outcome show requires an initialized project control")
    (entry, _) = control.resolve_project_context(state, project, args.project_context)
    record = read_outcome_record(
        control, state, str(entry["id"]), control.require_control_id("outcome id", args.outcome_id)
    )
    print(
        json.dumps(
            {
                "project_context_id": entry["id"],
                "project_revision": project.get("state_revision", 0),
                "outcome": record,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_outcome_add(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    outcome_id = control.require_control_id("outcome id", args.outcome_id)
    with control.state_lock(state["project"]):
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("outcome add requires an initialized project control")
        control.require_project_revision(project, args.project_revision)
        (entry, _) = control.resolve_project_context(state, project, args.project_context)
        context_id = str(entry["id"])
        path = control.outcome_record_path(state, context_id, outcome_id)
        if path.exists():
            raise ValueError(f"outcome already exists: {outcome_id}")
        parent_id = (
            control.require_control_id("outcome parent id", args.parent_id)
            if args.parent_id
            else None
        )
        parent_record = None
        if parent_id:
            parent_record = read_outcome_record(control, state, context_id, parent_id)
        intake = confirmed_intake_for_context(control, state, project, args.intake_id, context_id)
        created_at = control.now()
        record = {
            "schema_version": control.OUTCOME_SCHEMA_VERSION,
            "id": outcome_id,
            "project_context_id": context_id,
            "title": control.require_concrete("outcome title", args.title),
            "statement": control.require_concrete("outcome statement", args.statement),
            "status": args.status,
            "acceptance": [
                control.require_concrete("outcome acceptance", value) for value in args.acceptance
            ],
            "parent_id": parent_id,
            "relations": [],
            "intake_id": intake.get("id") if intake else None,
            "contract": control.contract_from_args(
                args,
                {},
                default_id=f"{outcome_id}-CONTRACT",
                default_mainline=str(args.statement),
                parent_refs=(
                    [str(parent_record.get("contract", {}).get("hash"))]
                    if isinstance(parent_record, dict)
                    and isinstance(parent_record.get("contract"), dict)
                    else []
                ),
            ),
            "system_generated": False,
            "state_revision": 1,
            "created_at": created_at,
            "updated_at": created_at,
        }
        if record["status"] not in control.OUTCOME_STATUSES:
            raise ValueError(f"unsupported outcome status: {record['status']}")
        outcomes = list_outcome_records(control, state, context_id) + [record]
        validate_outcome_graph(control, outcomes)
        control.write_json(path, record)
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": "created",
                "project_context_id": context_id,
                "project_revision": project_revision,
                "outcome": outcome_summary(control, record),
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "outcome_created", f"outcome={outcome_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_outcome_set(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    outcome_id = control.require_control_id("outcome id", args.outcome_id)
    with control.state_lock(state["project"]):
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("outcome set requires an initialized project control")
        control.require_project_revision(project, args.project_revision)
        (entry, _) = control.resolve_project_context(state, project, args.project_context)
        context_id = str(entry["id"])
        record = read_outcome_record(control, state, context_id, outcome_id)
        actual_revision = int(record.get("state_revision", 0))
        if args.outcome_revision != actual_revision:
            raise ValueError(
                f"outcome revision conflict: expected {actual_revision}, received {args.outcome_revision}"
            )
        contract_sensitive_change = bool(
            args.statement or args.acceptance or args.intake_id or (args.contract_json is not None)
        )
        effective_before = control.effective_contract_for_outcome(
            state, repo, project, context_id, outcome_id
        )
        strict_before = control.contract_is_strict(effective_before)
        if args.status == "completed" and strict_before:
            rollup = outcome_coverage_rollup(
                control, state, context_id, outcome_id, effective_before
            )
            if rollup["missing"]:
                raise ValueError(
                    "strict Outcome cannot be completed with unproven coverage: "
                    + ", ".join(rollup["missing"])
                )
        diff_confirmation = (
            control.require_contract_diff_confirmation(
                args.requirement_diff_confirmation, action=f"outcome {outcome_id}"
            )
            if strict_before and contract_sensitive_change
            else None
        )
        changed = False
        if args.title:
            record["title"] = control.require_concrete("outcome title", args.title)
            changed = True
        if args.statement:
            record["statement"] = control.require_concrete("outcome statement", args.statement)
            changed = True
        if args.status:
            if args.status not in control.OUTCOME_STATUSES:
                raise ValueError(f"unsupported outcome status: {args.status}")
            record["status"] = args.status
            changed = True
        if args.acceptance:
            record["acceptance"] = [
                control.require_concrete("outcome acceptance", value) for value in args.acceptance
            ]
            changed = True
        if args.intake_id:
            intake = confirmed_intake_for_context(
                control, state, project, args.intake_id, context_id
            )
            record["intake_id"] = intake.get("id") if intake else None
            changed = True
        if args.contract_json is not None:
            parent = (
                read_outcome_record(control, state, context_id, str(record.get("parent_id")))
                if record.get("parent_id")
                else None
            )
            record["contract"] = control.contract_from_args(
                args,
                {},
                default_id=f"{outcome_id}-CONTRACT",
                default_mainline=str(record.get("statement") or ""),
                parent_refs=(
                    [str(parent.get("contract", {}).get("hash"))]
                    if isinstance(parent, dict) and isinstance(parent.get("contract"), dict)
                    else []
                ),
            )
            changed = True
        if not changed:
            raise ValueError("outcome set requires at least one changed field")
        if diff_confirmation:
            changed_fields = [
                name
                for (name, changed_value) in (
                    ("statement", args.statement),
                    ("acceptance", args.acceptance),
                    ("intake_id", args.intake_id),
                    ("contract", args.contract_json),
                )
                if changed_value
            ]
            record.setdefault("contract_diffs", []).append(
                {
                    "at": control.now(),
                    "fields": changed_fields,
                    "confirmation_source": diff_confirmation,
                }
            )
        record["state_revision"] = actual_revision + 1
        record["updated_at"] = control.now()
        control.write_json(
            control.outcome_record_path(state, context_id, outcome_id), record, backup=True
        )
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": "updated",
                "project_context_id": context_id,
                "project_revision": project_revision,
                "outcome": outcome_summary(control, record),
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "outcome_created", f"outcome={outcome_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_outcome_link(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    source_id = control.require_control_id("source outcome id", args.source_id)
    target_id = control.require_control_id("target outcome id", args.target_id)
    if args.relation == "contains":
        raise ValueError("use outcome move to change a contains relationship")
    with control.state_lock(state["project"]):
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("outcome link requires an initialized project control")
        control.require_project_revision(project, args.project_revision)
        (entry, _) = control.resolve_project_context(state, project, args.project_context)
        context_id = str(entry["id"])
        source = read_outcome_record(control, state, context_id, source_id)
        read_outcome_record(control, state, context_id, target_id)
        actual_revision = int(source.get("state_revision", 0))
        if args.outcome_revision != actual_revision:
            raise ValueError(
                f"outcome revision conflict: expected {actual_revision}, received {args.outcome_revision}"
            )
        relations = source.setdefault("relations", [])
        if any(
            (
                isinstance(relation, dict)
                and relation.get("type") == args.relation
                and (relation.get("target_id") == target_id)
                for relation in relations
            )
        ):
            raise ValueError("outcome relation already exists")
        relations.append(
            {"type": args.relation, "target_id": target_id, "created_at": control.now()}
        )
        outcomes = list_outcome_records(control, state, context_id)
        outcomes = [source if item.get("id") == source_id else item for item in outcomes]
        validate_outcome_graph(control, outcomes)
        source["state_revision"] = actual_revision + 1
        source["updated_at"] = control.now()
        control.write_json(
            control.outcome_record_path(state, context_id, source_id), source, backup=True
        )
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": "linked",
                "project_context_id": context_id,
                "project_revision": project_revision,
                "source_id": source_id,
                "target_id": target_id,
                "relation": args.relation,
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "outcome_linked", f"outcome={source_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_outcome_move(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    outcome_id = control.require_control_id("outcome id", args.outcome_id)
    parent_id = (
        control.require_control_id("outcome parent id", args.parent_id) if args.parent_id else None
    )
    with control.state_lock(state["project"]):
        project = control.load_project(state, repo)
        if project is None:
            raise ValueError("outcome move requires an initialized project control")
        control.require_project_revision(project, args.project_revision)
        (entry, _) = control.resolve_project_context(state, project, args.project_context)
        context_id = str(entry["id"])
        record = read_outcome_record(control, state, context_id, outcome_id)
        if record.get("system_generated"):
            raise ValueError("the generated unlinked outcome cannot be moved")
        if parent_id:
            read_outcome_record(control, state, context_id, parent_id)
        actual_revision = int(record.get("state_revision", 0))
        if args.outcome_revision != actual_revision:
            raise ValueError(
                f"outcome revision conflict: expected {actual_revision}, received {args.outcome_revision}"
            )
        strict_before = control.contract_is_strict(
            control.effective_contract_for_outcome(state, repo, project, context_id, outcome_id)
        )
        strict_target = bool(
            parent_id
            and control.contract_is_strict(
                control.effective_contract_for_outcome(state, repo, project, context_id, parent_id)
            )
        )
        diff_confirmation = (
            control.require_contract_diff_confirmation(
                args.requirement_diff_confirmation, action=f"move outcome {outcome_id}"
            )
            if strict_before or strict_target
            else None
        )
        record["parent_id"] = parent_id
        outcomes = list_outcome_records(control, state, context_id)
        outcomes = [record if item.get("id") == outcome_id else item for item in outcomes]
        validate_outcome_graph(control, outcomes)
        if diff_confirmation:
            record.setdefault("contract_diffs", []).append(
                {
                    "at": control.now(),
                    "fields": ["parent_id"],
                    "confirmation_source": diff_confirmation,
                }
            )
        record["state_revision"] = actual_revision + 1
        record["updated_at"] = control.now()
        control.write_json(
            control.outcome_record_path(state, context_id, outcome_id), record, backup=True
        )
        project_revision = control.write_project_control(state, project)
    print(
        json.dumps(
            {
                "status": "moved",
                "project_context_id": context_id,
                "project_revision": project_revision,
                "outcome": outcome_summary(control, record),
                "receipt": control.bilingual_receipt(
                    "🧾 Auto Dev", "outcome_moved", f"outcome={outcome_id}"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0
