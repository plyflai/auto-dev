"""Requirement intake, inherited contracts, and intake gates."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import pathlib
import re
from typing import Any, Iterable

def contract_from_args(control, args: argparse.Namespace, source: dict[str, Any], *, default_id: str, default_mainline: str='', parent_refs: Iterable[str]=()) -> dict[str, Any] | None:
    raw = source.get('contract') if isinstance(source.get('contract'), dict) else None
    contract_json = getattr(args, 'contract_json', None)
    if contract_json:
        raw = control.decode_json_object('contract JSON', contract_json)
    return control.normalize_contract(raw, default_id=default_id, default_mainline=default_mainline, parent_refs=parent_refs)

def contract_status(control, contract: dict[str, Any] | None) -> str:
    if not contract:
        return 'unbound'
    return 'strict' if control.contract_is_strict(contract) else 'bound'

def strict_contract_hash(control, contract: dict[str, Any] | None) -> str | None:
    if not isinstance(contract, dict) or not control.contract_is_strict(contract):
        return None
    return str(contract.get('hash') or control.contract_hash(contract))

def strict_receipt_contract_hash(control, receipt: dict[str, Any]) -> str | None:
    contract = receipt.get('contract_snapshot')
    return strict_contract_hash(control, contract if isinstance(contract, dict) else None)

def outcome_identity_contract(control, record: dict[str, Any]) -> dict[str, Any]:
    """Fingerprint a strict parent Outcome without making it a second state model."""
    outcome_id = str(record.get('id') or 'outcome')
    title = str(record.get('title') or outcome_id)
    statement = str(record.get('statement') or '')
    acceptance = record.get('acceptance') if isinstance(record.get('acceptance'), list) else []
    acceptance_text = ' | '.join((str(item) for item in acceptance if str(item).strip()))
    text = f'Parent Outcome {title}: {statement}'
    if acceptance_text:
        text += f'. Acceptance: {acceptance_text}'
    contract = control.normalize_contract({'id': f'{outcome_id}-OUTCOME-GUARD', 'mode': 'standard', 'hard_constraints': [{'id': f'{outcome_id}-OUTCOME-STATEMENT', 'kind': 'parent_outcome', 'text': text}]}, default_id=f'{outcome_id}-OUTCOME-GUARD')
    assert contract is not None
    return contract

def outcome_contract_chain(control, state: dict[str, pathlib.Path], context_id: str, outcome_id: str | None, *, inherited: dict[str, Any] | None=None) -> dict[str, Any] | None:
    if not outcome_id:
        return inherited
    chain: list[dict[str, Any]] = []
    current_id: str | None = outcome_id
    visited: set[str] = set()
    while current_id:
        if current_id in visited:
            raise ValueError(f'outcome contract lineage contains a cycle at {current_id}')
        visited.add(current_id)
        record = control.read_outcome_record(state, context_id, current_id)
        chain.append(record)
        parent_id = record.get('parent_id')
        current_id = str(parent_id) if parent_id else None
    effective = copy.deepcopy(inherited)
    for record in reversed(chain):
        if isinstance(record.get('contract'), dict):
            effective = control.merge_contracts(effective, record['contract'])
        if control.contract_is_strict(effective):
            effective = control.merge_contracts(effective, outcome_identity_contract(control, record))
    return effective

def parent_contract_for_task(control, state: dict[str, pathlib.Path], repo: pathlib.Path, context_id: str, outcome_id: str | None, intake_id: str | None) -> dict[str, Any] | None:
    effective: dict[str, Any] | None = None
    try:
        frame = control.read_context_frame(state, context_id)
    except (OSError, json.JSONDecodeError, ValueError):
        frame = {}
    if isinstance(frame.get('contract'), dict):
        effective = control.merge_contracts(effective, frame['contract'])
    if intake_id:
        project = control.load_project(state, repo)
        if project is not None:
            (_, intake) = control.find_intake_record(state, project, intake_id)
            if isinstance(intake.get('contract'), dict):
                effective = control.merge_contracts(effective, intake['contract'])
    return outcome_contract_chain(control, state, context_id, outcome_id, inherited=effective)

def effective_contract_for_outcome(control, state: dict[str, pathlib.Path], repo: pathlib.Path, project: dict[str, Any], context_id: str, outcome_id: str) -> dict[str, Any] | None:
    """Resolve the contract an Outcome mutation would change for its children."""
    effective: dict[str, Any] | None = None
    try:
        frame = control.read_context_frame(state, context_id)
    except (OSError, json.JSONDecodeError, ValueError):
        frame = {}
    if isinstance(frame.get('contract'), dict):
        effective = control.merge_contracts(effective, frame['contract'])
    record = control.read_outcome_record(state, context_id, outcome_id)
    intake_id = record.get('intake_id')
    if isinstance(intake_id, str) and intake_id:
        (_, intake) = control.find_intake_record(state, project, intake_id)
        if isinstance(intake.get('contract'), dict):
            effective = control.merge_contracts(effective, intake['contract'])
    return outcome_contract_chain(control, state, context_id, outcome_id, inherited=effective)

def require_contract_diff_confirmation(control, value: str | None, *, action: str) -> str:
    return control.require_concrete(f'Requirement Diff confirmation for {action}', value or '')

def effective_contract_for_task(control, state: dict[str, pathlib.Path], repo: pathlib.Path, context_id: str, outcome_id: str | None, intake_id: str | None, local_contract: dict[str, Any] | None=None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    parent = parent_contract_for_task(control, state, repo, context_id, outcome_id, intake_id)
    return (control.merge_contracts(parent, local_contract), parent)

def contract_projection(control, receipt: dict[str, Any], continuity: dict[str, Any] | None, *, repo: pathlib.Path | None=None) -> dict[str, Any]:
    contract = receipt.get('contract_snapshot') if isinstance(receipt.get('contract_snapshot'), dict) else None
    task_coverage = receipt.get('contract_coverage_ids') if isinstance(receipt.get('contract_coverage_ids'), list) else []
    if contract is None:
        return {'status': 'legacy', 'capsule': {'status': 'legacy'}, 'missing_coverage': [], 'prewrite_required': [], 'prewrite_missing': []}
    nodes = continuity.get('plan', {}).get('nodes', []) if continuity else []
    planned = {str(value) for node in nodes if isinstance(node, dict) for value in node.get('coverage_ids', [])}
    proofs = continuity.get('proofs', []) if continuity else receipt.get('proofs', [])
    passed: set[str] = set()
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for proof in proofs:
        if not isinstance(proof, dict):
            continue
        key = (str(proof.get('node_id')), str(proof.get('proof_id')))
        previous = latest.get(key)
        if previous is None or int(proof.get('attempt_index', 1)) > int(previous.get('attempt_index', 1)):
            latest[key] = proof
    nodes_by_id = {str(node.get('id')): node for node in nodes if isinstance(node, dict) and node.get('id')}
    for proof in latest.values():
        if proof.get('status') != 'passed':
            continue
        if repo is not None:
            node_id = str(proof.get('node_id'))
            outcome = (nodes_by_id.get(node_id) or {}).get('outcome') if continuity else receipt.get('outcome')
            plan_revision = int(continuity.get('plan', {}).get('revision', 0)) if continuity else 0
            if not isinstance(outcome, dict) or not control.proof_is_fresh(
                proof, outcome=outcome, repo=repo, plan_revision=plan_revision,
                node=nodes_by_id.get(node_id),
            ):
                continue
        elif proof.get('fresh') is False:
            continue
        passed.update((str(value) for value in proof.get('coverage_ids', []) if value))
    required = list(dict.fromkeys((str(value) for value in task_coverage))) or control.contract_coverage_ids(contract)
    required_set = set(required)
    missing = [identifier for identifier in required if identifier not in passed]
    prewrite_required = [identifier for identifier in control.prewrite_coverage_ids(contract) if identifier in required_set]
    prewrite_missing = [identifier for identifier in prewrite_required if identifier not in passed]
    return {'status': contract_status(control, contract), 'mode': contract.get('mode', 'standard'), 'id': contract.get('id'), 'revision': contract.get('revision', 1), 'hash': contract.get('hash') or control.contract_hash(contract), 'task_coverage_ids': list(dict.fromkeys((str(value) for value in task_coverage))), 'required_coverage': required, 'planned_coverage': sorted(planned), 'passed_coverage': sorted(passed), 'missing_coverage': missing, 'prewrite_required': prewrite_required, 'prewrite_missing': prewrite_missing, 'capsule': control.contract_capsule(contract, current_node=(continuity or {}).get('current_node'), task_coverage=task_coverage)}

def contract_gate_for_receipt(control, repo: pathlib.Path, state: dict[str, pathlib.Path], receipt: dict[str, Any], continuity: dict[str, Any] | None) -> dict[str, Any]:
    projection = contract_projection(control, receipt, continuity, repo=repo)
    contract = receipt.get('contract_snapshot') if isinstance(receipt.get('contract_snapshot'), dict) else None
    expected_parent_hash = receipt.get('contract_parent_hash')
    if contract is not None and expected_parent_hash:
        try:
            current_parent = parent_contract_for_task(control, state, repo, str(receipt.get('project_context_id') or ''), str(receipt.get('primary_outcome_id') or '') or None, str(receipt.get('intake_id') or '') or None)
            current_parent_hash = current_parent.get('hash') if current_parent else None
        except (OSError, json.JSONDecodeError, ValueError) as error:
            projection['status'] = 'unavailable'
            projection['error'] = str(error)
        else:
            if current_parent_hash != expected_parent_hash:
                projection['status'] = 'stale'
                projection['stale_reason'] = 'parent_contract_changed'
    if control.contract_is_strict(contract) and continuity and continuity.get('plan', {}).get('nodes'):
        plan = continuity.get('plan', {})
        expected_plan_hash = contract.get('hash') or control.contract_hash(contract)
        plan_contract_hash = plan.get('contract_hash')
        if plan_contract_hash != expected_plan_hash and projection['status'] == 'strict':
            projection['status'] = 'plan_stale'
            projection['stale_reason'] = 'task_contract_changed_after_plan'
        planned = set(projection.get('planned_coverage', []))
        required = set(projection.get('required_coverage', []))
        projection['unplanned_coverage'] = sorted(required - planned)
        if projection['unplanned_coverage'] and projection['status'] == 'strict':
            projection['status'] = 'plan_incomplete'
    return projection

def validate_contract_plan(control, receipt: dict[str, Any], nodes: list[dict[str, Any]]) -> None:
    contract = receipt.get('contract_snapshot') if isinstance(receipt.get('contract_snapshot'), dict) else None
    if not control.contract_is_strict(contract):
        return
    required_by_id = {str(item.get('id')): item for item in contract.get('required_coverage', []) if isinstance(item, dict) and item.get('id')}
    task_coverage = {str(value) for value in receipt.get('contract_coverage_ids', []) if value} or set(required_by_id)
    declared = {str(value) for node in nodes for value in node.get('coverage_ids', [])}
    missing = sorted(task_coverage - declared)
    if missing:
        raise ValueError('strict contract plan is missing required coverage: ' + ', '.join(missing))
    for node in nodes:
        node_coverage = {str(value) for value in node.get('coverage_ids', [])}
        unknown_node_coverage = sorted(node_coverage - task_coverage)
        if unknown_node_coverage:
            raise ValueError(f"node {node.get('id')} references undeclared contract coverage: " + ', '.join(unknown_node_coverage))
        outcome = node.get('outcome') if isinstance(node.get('outcome'), dict) else None
        if node.get('node_role') == 'milestone':
            continue
        proofs = outcome.get('proofs', []) if outcome else []
        proof_coverage: set[str] = set()
        for proof in proofs:
            proof_ids = {str(value) for value in proof.get('coverage_ids', [])}
            unknown = sorted(proof_ids - task_coverage)
            if unknown:
                raise ValueError(f"node {node.get('id')} proof references undeclared contract coverage: " + ', '.join(unknown))
            outside_node = sorted(proof_ids - node_coverage)
            if outside_node:
                raise ValueError(f"node {node.get('id')} proof coverage is not assigned to the node: " + ', '.join(outside_node))
            proof_coverage.update(proof_ids)
            for coverage_id in proof_ids:
                expected_kind = str(required_by_id[coverage_id].get('evidence_kind') or 'supporting')
                actual_kind = str(proof.get('evidence_kind') or 'supporting')
                if expected_kind != 'supporting' and actual_kind != expected_kind:
                    raise ValueError(f"node {node.get('id')} proof for {coverage_id} requires evidence kind {expected_kind}, received {actual_kind}")
                allowed_proof_ids = required_by_id[coverage_id].get('proof_ids')
                if allowed_proof_ids and proof.get('id') not in allowed_proof_ids:
                    raise ValueError(f"node {node.get('id')} proof for {coverage_id} must use one of: " + ', '.join((str(value) for value in allowed_proof_ids)))
        missing_proofs = sorted(node_coverage - proof_coverage)
        if missing_proofs:
            raise ValueError(f"node {node.get('id')} has planned coverage without a declared proof: " + ', '.join(missing_proofs))

def validate_contract_readiness(control, receipt: dict[str, Any], continuity: dict[str, Any] | None, *, complete: bool, repo: pathlib.Path | None=None) -> None:
    contract = receipt.get('contract_snapshot') if isinstance(receipt.get('contract_snapshot'), dict) else None
    if not control.contract_is_strict(contract):
        return
    if continuity is None:
        raise ValueError('strict contract requires a continuity plan')
    task_coverage = {str(value) for value in receipt.get('contract_coverage_ids', []) if value} or set(control.contract_coverage_ids(contract))
    planned = {str(value) for node in continuity.get('plan', {}).get('nodes', []) for value in node.get('coverage_ids', [])}
    missing_plan = sorted(task_coverage - planned)
    if missing_plan:
        raise ValueError('strict contract coverage is not assigned to the plan: ' + ', '.join(missing_plan))
    if complete:
        projection = contract_projection(control, receipt, continuity, repo=repo)
        if projection['missing_coverage']:
            raise ValueError('strict contract has unproven coverage: ' + ', '.join(projection['missing_coverage']))

def validate_node_contract_proofs(control, repo: pathlib.Path, receipt: dict[str, Any], continuity: dict[str, Any], node: dict[str, Any]) -> None:
    contract = receipt.get('contract_snapshot') if isinstance(receipt.get('contract_snapshot'), dict) else None
    if not control.contract_is_strict(contract):
        return
    required = {str(value) for value in node.get('coverage_ids', [])}
    if not required:
        return
    passed: set[str] = set()
    for proof_spec in (node.get('outcome') or {}).get('proofs', []):
        proof = control.latest_proof(continuity.get('proofs', []), node_id=str(node.get('id')), proof_id=str(proof_spec.get('id')))
        if proof and proof.get('status') == 'passed' and control.proof_is_fresh(
            proof, outcome=node['outcome'], repo=repo,
            plan_revision=int(continuity.get('plan', {}).get('revision', 0)), node=node,
        ):
            passed.update((str(value) for value in proof.get('coverage_ids', []) if value))
    missing = sorted(required - passed)
    if missing:
        raise ValueError(f"node {node.get('id')} has unproven inherited coverage: " + ', '.join(missing))
