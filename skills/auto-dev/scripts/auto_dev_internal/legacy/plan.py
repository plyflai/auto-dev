"""Versioned legacy control-plane inspection and migration orchestration."""
from __future__ import annotations
import argparse
import json
import os
import pathlib
import shutil
from typing import Any, Iterable

def legacy_upgrade_source_fingerprint(control, state: dict[str, pathlib.Path]) -> str:
    candidates = [state['project'], state['active'], state['project_memory'], state['environment_projection'], state['domain_projection'], state['dependency_lease'], state['runtime_diagnostics'], state['config']]
    if state['tasks'].is_dir():
        candidates.extend(sorted(state['tasks'].glob('*.json')))
    if state['projects'].is_dir():
        candidates.extend(sorted(state['projects'].rglob('*.json')))
    digest = control.hashlib.sha256()
    for path in candidates:
        if not path.exists():
            continue
        digest.update(control.upgrade_relative_path(state, path).encode('utf-8'))
        digest.update(b'\x00')
        digest.update(path.read_bytes())
        digest.update(b'\x00')
    return digest.hexdigest()

def legacy_upgrade_historical_runs(control, state: dict[str, pathlib.Path]) -> dict[str, Any]:
    records = []
    unreadable = []
    if not state['runs'].is_dir():
        return {'count': 0, 'preserved': True, 'records': records, 'unreadable': unreadable}
    for path in sorted(state['runs'].glob('*.json')):
        try:
            receipt = control.read_json(path)
            if not isinstance(receipt, dict):
                raise ValueError('run record must be a JSON object')
            records.append({'path': control.upgrade_relative_path(state, path), 'id': receipt.get('id'), 'schema_version': receipt.get('schema_version', 1)})
        except (OSError, json.JSONDecodeError, ValueError) as error:
            unreadable.append({'path': control.upgrade_relative_path(state, path), 'error': str(error)})
    return {'count': len(records) + len(unreadable), 'preserved': True, 'records': records, 'unreadable': unreadable}

def legacy_upgrade_read_receipt(control, plan: control.LegacyUpgradePlan, path: pathlib.Path, *, source: str) -> control.LegacyUpgradeTask | None:
    try:
        receipt = control.read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        plan.unsupported_records.append({'source': source, 'path': control.upgrade_relative_path(plan.state, path), 'reason': 'unreadable_json', 'error': str(error)})
        return None
    if not isinstance(receipt, dict):
        plan.unsupported_records.append({'source': source, 'path': control.upgrade_relative_path(plan.state, path), 'reason': 'not_json_object'})
        return None
    identifier = receipt.get('id')
    try:
        if not isinstance(identifier, str):
            raise ValueError('task id is missing')
        control.require_control_id('task id', identifier)
        schema_version = receipt.get('schema_version', 1)
        if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 1:
            raise ValueError('task schema version is malformed')
        if schema_version > control.SCHEMA_VERSION:
            raise ValueError('task schema is newer than this Auto Dev version')
        revision = receipt.get('state_revision', 0)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError('task state revision is malformed')
    except ValueError as error:
        plan.unsupported_records.append({'source': source, 'path': control.upgrade_relative_path(plan.state, path), 'reason': 'unsupported_task_record', 'error': str(error)})
        return None
    return control.LegacyUpgradeTask(identifier=identifier, receipt=control.clone_json(receipt), task_path=None)

def collect_legacy_upgrade_tasks(control, plan: control.LegacyUpgradePlan) -> None:
    state = plan.state
    if state['tasks'].is_dir():
        for path in sorted(state['tasks'].glob('*.json')):
            candidate = legacy_upgrade_read_receipt(control, plan, path, source='task_projection')
            if candidate is None:
                plan.add_blocker('unsupported_task_projection', 'task projection cannot be safely upgraded', path=path)
                continue
            if path.stem != candidate.identifier:
                plan.add_blocker('task_filename_mismatch', f'task projection filename does not match receipt id: {candidate.identifier}', path=path)
                continue
            if candidate.identifier in plan.tasks:
                plan.add_blocker('duplicate_task_id', f'duplicate task id: {candidate.identifier}', path=path)
                continue
            candidate.task_path = path
            plan.tasks[candidate.identifier] = candidate
    if not state['active'].exists():
        return
    active = legacy_upgrade_read_receipt(control, plan, state['active'], source='active_projection')
    if active is None:
        plan.add_blocker('active_projection_unreadable', 'active.json cannot be safely preserved', path=state['active'])
        return
    existing = plan.tasks.get(active.identifier)
    if existing is not None:
        if control.canonical_json(existing.receipt) != control.canonical_json(active.receipt):
            plan.add_blocker('active_projection_diverges', f'active.json and tasks/{active.identifier}.json differ; reconcile before upgrading', path=state['active'])
            return
        existing.active_projection = True
    else:
        active.active_projection = True
        plan.tasks[active.identifier] = active
    plan.active_task_id = active.identifier
    plan.active_task_revision = int(active.receipt.get('state_revision', 0))

def legacy_upgrade_has_control_artifacts(control, state: dict[str, pathlib.Path]) -> bool:
    if not state['root'].exists():
        return False
    if state['project'].exists() or state['active'].exists() or state['history'].exists():
        return True
    return bool(state['tasks'].is_dir() and any(state['tasks'].glob('*.json')) or (state['runs'].is_dir() and any(state['runs'].glob('*.json'))))

def legacy_upgrade_branch_context(control, plan: control.LegacyUpgradePlan, branch_key: str) -> dict[str, Any] | None:
    context = plan.project['branches'].get(branch_key)
    if context is None:
        branch = None if branch_key.startswith('@detached:') else branch_key
        context = {'branch': branch, 'active_task_id': None, 'task_ids': [], 'updated_at': plan.timestamp}
        plan.project['branches'][branch_key] = context
        return context
    if not isinstance(context, dict):
        plan.add_blocker('branch_context_malformed', f'branch context is malformed: {branch_key}')
        return None
    task_ids = context.get('task_ids')
    if not isinstance(task_ids, list) or not all((isinstance(item, str) for item in task_ids)):
        plan.add_blocker('branch_task_index_malformed', f'branch task index is malformed: {branch_key}')
        return None
    active_task_id = context.get('active_task_id')
    if active_task_id is not None and (not isinstance(active_task_id, str)):
        plan.add_blocker('branch_active_task_malformed', f'branch active task is malformed: {branch_key}')
        return None
    return context

def preserve_legacy_branch_index(control, plan: control.LegacyUpgradePlan) -> None:
    branches = plan.project.get('branches')
    if not isinstance(branches, dict):
        plan.add_blocker('project_branches_malformed', 'project branches must be an object')
        return
    for (key, context) in list(branches.items()):
        if not isinstance(key, str):
            plan.add_blocker('branch_key_malformed', 'project branch key must be text')
            continue
        validated = legacy_upgrade_branch_context(control, plan, key)
        if validated is None:
            continue
        for task_id in validated['task_ids']:
            if task_id not in plan.tasks:
                plan.add_blocker('branch_references_missing_task', f'branch {key} references a missing or unreadable task: {task_id}')
        selected = validated.get('active_task_id')
        if selected is not None and selected not in plan.tasks:
            plan.add_blocker('branch_references_missing_active_task', f'branch {key} selects a missing or unreadable task: {selected}')
    for task in plan.tasks.values():
        branch = task.receipt.get('base_branch')
        head = task.receipt.get('base_head')
        if branch is not None and (not isinstance(branch, str)):
            plan.add_blocker('task_branch_malformed', f'task branch is malformed: {task.identifier}')
            continue
        if head is not None and (not isinstance(head, str)):
            plan.add_blocker('task_head_malformed', f'task head is malformed: {task.identifier}')
            continue
        key = control.branch_context_key(branch, head)
        context = legacy_upgrade_branch_context(control, plan, key)
        if context is None:
            continue
        if task.identifier not in context['task_ids']:
            context['task_ids'].append(task.identifier)
            context['updated_at'] = plan.timestamp
    if plan.active_task_id is None:
        return
    active = plan.tasks[plan.active_task_id]
    key = control.branch_context_key(active.receipt.get('base_branch'), active.receipt.get('base_head'))
    context = legacy_upgrade_branch_context(control, plan, key)
    if context is None:
        return
    selected = context.get('active_task_id')
    if selected not in {None, active.identifier}:
        plan.add_blocker('active_projection_conflicts_with_branch', f'active.json selects {active.identifier} but branch {key} selects {selected}')
        return
    if selected != active.identifier:
        context['active_task_id'] = active.identifier
        context['updated_at'] = plan.timestamp

def legacy_upgrade_step_hierarchy_adoption(control, plan: control.LegacyUpgradePlan) -> None:
    project = plan.project
    contexts = project.get('contexts')
    if not isinstance(contexts, dict):
        plan.add_blocker('project_contexts_malformed', 'project contexts must be an object')
        return
    default_context = project.get('default_context_id')
    context_id: str
    unlinked_outcome_id: str
    if isinstance(default_context, str) and default_context in contexts:
        entry = contexts[default_context]
        if not isinstance(entry, dict):
            plan.add_blocker('default_context_malformed', 'default managed project context is malformed')
            return
        if not control.require_upgrade_context_storage(plan, default_context, entry):
            return
        context_id = default_context
        unlinked_outcome_id = str(entry['unlinked_outcome_id'])
    elif default_context is not None:
        plan.add_blocker('default_context_missing', 'default managed project context is missing from the registry')
        return
    else:
        (entry, frame, outcome) = control.default_project_context_records(project, plan.timestamp)
        context_id = str(entry['id'])
        existing = contexts.get(context_id)
        if existing is not None:
            if not isinstance(existing, dict) or not control.require_upgrade_context_storage(plan, context_id, existing):
                return
            entry = existing
            unlinked_outcome_id = str(entry['unlinked_outcome_id'])
        else:
            contexts[context_id] = entry
            plan.queue_write(control.context_frame_path(plan.state, context_id), frame, record_type='project_context_frame', record_id=context_id)
            plan.queue_write(control.outcome_record_path(plan.state, context_id, str(entry['unlinked_outcome_id'])), outcome, record_type='outcome', record_id=str(entry['unlinked_outcome_id']))
            unlinked_outcome_id = str(entry['unlinked_outcome_id'])
        project['default_context_id'] = context_id
    for task in plan.tasks.values():
        receipt = control.clone_json(task.receipt)
        existing_context_id = receipt.get('project_context_id')
        if existing_context_id is None:
            task_context_id = context_id
        elif isinstance(existing_context_id, str) and existing_context_id in contexts:
            task_context_id = existing_context_id
        else:
            plan.add_blocker('task_context_unresolved', f'task {task.identifier} references an unknown managed project context')
            continue
        entry = contexts[task_context_id]
        if not isinstance(entry, dict):
            plan.add_blocker('task_context_malformed', f'task {task.identifier} context is malformed')
            continue
        task_outcome_id = receipt.get('primary_outcome_id')
        if task_outcome_id is None:
            candidate_outcome = entry.get('unlinked_outcome_id')
            if not isinstance(candidate_outcome, str):
                plan.add_blocker('task_outcome_unresolved', f'task {task.identifier} has no safe outcome target')
                continue
            task_outcome_id = candidate_outcome
        elif not isinstance(task_outcome_id, str):
            plan.add_blocker('task_outcome_malformed', f'task {task.identifier} outcome is malformed')
            continue
        if task_context_id != context_id and (not control.require_upgrade_context_storage(plan, task_context_id, entry)):
            continue
        unlinked_outcome_id = entry.get('unlinked_outcome_id')
        if task_outcome_id != unlinked_outcome_id and (not control.outcome_record_path(plan.state, task_context_id, task_outcome_id).exists()):
            plan.add_blocker('task_outcome_missing', f'task {task.identifier} references a missing outcome: {task_outcome_id}')
            continue
        control.normalize_receipt(receipt)
        receipt['project_context_id'] = task_context_id
        receipt['primary_outcome_id'] = task_outcome_id
        receipt['schema_version'] = control.SCHEMA_VERSION
        changed = control.canonical_json(receipt) != control.canonical_json(task.receipt)
        if not changed:
            continue
        previous_schema = int(task.receipt.get('schema_version', 1))
        receipt['state_revision'] = int(task.receipt.get('state_revision', 0)) + 1
        events = receipt.setdefault('events', [])
        if not isinstance(events, list):
            plan.add_blocker('task_events_malformed', f'task {task.identifier} events are malformed')
            continue
        events.append({'type': 'legacy_control_plane_upgraded', 'at': plan.timestamp, 'upgrade_step': 'hierarchy-adoption-v1', 'from_schema': previous_schema, 'to_schema': control.SCHEMA_VERSION, 'project_context_id': task_context_id, 'primary_outcome_id': task_outcome_id})
        target_path = task.task_path or control.task_path(plan.state, task.identifier)
        plan.queue_write(target_path, receipt, record_type='task_projection', record_id=task.identifier)
        if task.active_projection:
            plan.queue_write(plan.state['active'], receipt, record_type='active_projection', record_id=task.identifier)
    preserve_legacy_branch_index(control, plan)
    if plan.blockers:
        return
    project['schema_version'] = control.PROJECT_SCHEMA_VERSION

def normalize_legacy_proof_attempts(control, continuity: dict[str, Any]) -> None:
    counts: dict[tuple[str, str], int] = {}
    for proof in continuity.get('proofs', []):
        if not isinstance(proof, dict):
            continue
        node_id = str(proof.get('node_id') or 'run')
        proof_id = str(proof.get('proof_id') or 'proof')
        key = (node_id, proof_id)
        counts[key] = counts.get(key, 0) + 1
        proof.setdefault('attempt_index', counts[key])
        proof.setdefault('attempt_id', f"legacy-{node_id}-{proof_id}-{proof['attempt_index']}")
        missing_freshness_context = any((field not in proof for field in ('outcome_sha256', 'plan_revision', 'scope_sha256')))
        if missing_freshness_context:
            proof['fresh'] = False
            proof['migration_revalidation_required'] = True

def legacy_upgrade_step_state_contract_adoption(control, plan: control.LegacyUpgradePlan) -> None:
    for task in plan.tasks.values():
        receipt = control.staged_upgrade_task_receipt(plan, task)
        before = control.canonical_json(receipt)
        previous_schema = int(task.receipt.get('schema_version', 1))
        control.normalize_receipt(receipt)
        continuity = control.continuity_from_receipt(receipt)
        if continuity is not None:
            continuity['schema_version'] = control.CONTINUITY_SCHEMA_VERSION
            normalize_legacy_proof_attempts(control, continuity)
        receipt['schema_version'] = control.SCHEMA_VERSION
        if control.canonical_json(receipt) == before:
            continue
        receipt['state_revision'] = int(receipt.get('state_revision', 0)) + 1
        receipt.setdefault('events', []).append({'type': 'state_contract_upgraded', 'at': plan.timestamp, 'upgrade_step': 'state-contract-adoption-v2', 'from_schema': previous_schema, 'to_schema': control.SCHEMA_VERSION, 'continuity_schema': control.CONTINUITY_SCHEMA_VERSION if continuity is not None else None})
        target_path = task.task_path or control.task_path(plan.state, task.identifier)
        plan.queue_write(target_path, receipt, record_type='task_projection', record_id=task.identifier)
        if task.active_projection:
            plan.queue_write(plan.state['active'], receipt, record_type='active_projection', record_id=task.identifier)
    if plan.state['project_memory'].exists():
        try:
            raw_memory = control.read_json(plan.state['project_memory'])
            version = raw_memory.get('schema_version', 1)
            if isinstance(version, int) and version > control.project_memory.REGISTRY_SCHEMA_VERSION:
                plan.newer_than_cli.append({'surface': 'project_memory', 'source_schema': version, 'target_schema': control.project_memory.REGISTRY_SCHEMA_VERSION})
            else:
                memory = control.project_memory.load(plan.state['project_memory'])
                if control.canonical_json(memory) != control.canonical_json(raw_memory):
                    plan.queue_write(plan.state['project_memory'], memory, record_type='project_memory')
        except (OSError, json.JSONDecodeError, ValueError) as error:
            plan.add_blocker('project_memory_unreadable', str(error), path=plan.state['project_memory'])
    if plan.state['dependency_lease'].exists():
        try:
            raw_lease = control.read_json(plan.state['dependency_lease'])
            version = raw_lease.get('schema_version', 1)
            if isinstance(version, int) and version > control.project_memory.LEASE_SCHEMA_VERSION:
                plan.newer_than_cli.append({'surface': 'dependency_lease', 'source_schema': version, 'target_schema': control.project_memory.LEASE_SCHEMA_VERSION})
            else:
                lease = control.project_memory.load_lease(plan.repo)
                if lease is not None and control.canonical_json(lease) != control.canonical_json(raw_lease):
                    plan.queue_write(plan.state['dependency_lease'], lease, record_type='dependency_lease')
        except (OSError, json.JSONDecodeError, ValueError) as error:
            plan.add_blocker('dependency_lease_unreadable', str(error), path=plan.state['dependency_lease'])
    for (surface_id, path, target_schema, record_type) in (('runtime_diagnostics', plan.state['runtime_diagnostics'], control.RUNTIME_DIAGNOSTICS_SCHEMA_VERSION, 'runtime_diagnostics'), ('workspace_policy', plan.state['config'], control.WORKSPACE_POLICY_SCHEMA_VERSION, 'workspace_policy')):
        if not path.exists():
            continue
        try:
            raw = control.read_json(path)
            version = raw.get('schema_version', 0)
            if isinstance(version, int) and version > target_schema:
                plan.newer_than_cli.append({'surface': surface_id, 'source_schema': version, 'target_schema': target_schema})
                continue
            if surface_id == 'runtime_diagnostics':
                entries = raw.get('entries')
                if not isinstance(entries, list) or not all((isinstance(entry, dict) for entry in entries)):
                    raise ValueError('runtime diagnostics entries must be a list of objects')
                normalized = {**raw, 'schema_version': target_schema}
            else:
                normalized = control.normalize_workspace_policy(raw, persisted=bool(raw.get('policy_revision', 0)))
            if control.canonical_json(normalized) != control.canonical_json(raw):
                plan.queue_write(path, normalized, record_type=record_type)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            plan.add_blocker(f'{surface_id}_unreadable', str(error), path=path)

def legacy_upgrade_step_verification_gate_policy(control, plan: control.LegacyUpgradePlan) -> None:
    plan.project['verification_gate_policy'] = control.VERIFICATION_GATE_POLICY


def legacy_upgrade_step_environment_domain_memory(control, plan: control.LegacyUpgradePlan) -> None:
    memory_path = plan.state['project_memory']
    staged = plan.writes.get(memory_path)
    try:
        if isinstance(staged, dict):
            memory = control.clone_json(staged)
        else:
            memory = control.project_memory.load(memory_path)
        materialized = control.project_memory.materialize_profile_document(plan.repo, memory)
        materialized['memory_revision'] = int(memory.get('memory_revision', 0)) + 1
        materialized['updated_at'] = plan.timestamp
        plan.queue_write(memory_path, materialized, record_type='project_memory')
        environment_text = control.project_memory.render_environment_projection(
            plan.repo, materialized
        )
        domain_text = control.project_memory.render_domain_projection(materialized)
        if (
            not plan.state['environment_projection'].is_file()
            or plan.state['environment_projection'].read_text(encoding='utf-8') != environment_text
        ):
            plan.queue_text(
                plan.state['environment_projection'],
                environment_text,
                record_type='environment_projection',
            )
        if (
            not plan.state['domain_projection'].is_file()
            or plan.state['domain_projection'].read_text(encoding='utf-8') != domain_text
        ):
            plan.queue_text(
                plan.state['domain_projection'],
                domain_text,
                record_type='domain_projection',
            )
    except (OSError, ValueError, TypeError) as error:
        plan.add_blocker('project_memory_profile_unreadable', str(error), path=memory_path)


def legacy_upgrade_step_plan_strategy_adoption(
    control, plan: control.LegacyUpgradePlan
) -> None:
    """Adopt the v5 plan envelope without inferring Rolling Graph structure."""
    for task in plan.tasks.values():
        receipt = control.staged_upgrade_task_receipt(plan, task)
        before = control.canonical_json(receipt)
        continuity = control.continuity_from_receipt(receipt)
        if continuity is None:
            continue
        plan_record = continuity.setdefault('plan', {})
        plan_record.setdefault('strategy', 'legacy')
        plan_record.setdefault('relations', [])
        plan_record.setdefault('graph_sha256', None)
        continuity.setdefault('compilation_focus', None)
        continuity.setdefault('execution_focus', continuity.get('current_node'))
        continuity.setdefault('ready_frontier', {'milestones': [], 'work_packets': []})
        continuity.setdefault('exit_snapshots', [])
        continuity['schema_version'] = control.CONTINUITY_SCHEMA_VERSION
        receipt['schema_version'] = control.SCHEMA_VERSION
        if control.canonical_json(receipt) == before:
            continue
        receipt['state_revision'] = int(receipt.get('state_revision', 0)) + 1
        receipt.setdefault('events', []).append({
            'type': 'plan_strategy_adopted',
            'at': plan.timestamp,
            'upgrade_step': 'rolling-plan-envelope-v5',
            'strategy': plan_record['strategy'],
        })
        target_path = task.task_path or control.task_path(plan.state, task.identifier)
        plan.queue_write(
            target_path, receipt, record_type='task_projection', record_id=task.identifier
        )
        if task.active_projection:
            plan.queue_write(
                plan.state['active'], receipt,
                record_type='active_projection', record_id=task.identifier,
            )


def validate_legacy_upgrade_registry(control) -> None:
    versions = [step.version for step in control.LEGACY_UPGRADE_STEPS]
    if versions != list(range(1, control.CONTROL_PLANE_UPGRADE_VERSION + 1)):
        raise RuntimeError('legacy upgrade registry must contain one ordered step per upgrade version')
    identifiers = [step.identifier for step in control.LEGACY_UPGRADE_STEPS]
    if len(set(identifiers)) != len(identifiers):
        raise RuntimeError('legacy upgrade registry contains duplicate step ids')
    control.validate_control_plane_state_surface_registry()

def pending_legacy_upgrade_steps(control, current_version: int) -> list[control.LegacyUpgradeStep]:
    validate_legacy_upgrade_registry(control)
    return [step for step in control.LEGACY_UPGRADE_STEPS if step.version > current_version]

def control_plane_surface_status(control, plan: control.LegacyUpgradePlan, surface: control.ControlPlaneStateSurface, *, present: bool, source_schema: int | str | None) -> str:
    if any((item.get('surface') == surface.identifier for item in plan.newer_than_cli)):
        return 'newer_than_cli'
    if any((blocker.get('code', '').startswith(surface.identifier) for blocker in plan.blockers)):
        return 'blocked'
    if surface.identifier == 'proof_attempts':
        if plan.manual_decisions:
            return 'manual_decision_required'
        if plan.revalidation_targets:
            return 'reverification_required'
    task_write_queued = any(
        path == plan.state['active'] or path.parent == plan.state['tasks']
        for path in plan.writes
    )
    queued_by_surface = {'project': plan.state['project'] in plan.writes, 'task_receipts': task_write_queued, 'continuity': task_write_queued and isinstance(source_schema, int) and (source_schema < control.CONTINUITY_SCHEMA_VERSION), 'project_memory': plan.state['project_memory'] in plan.writes, 'environment_projection': plan.state['environment_projection'] in plan.writes, 'domain_projection': plan.state['domain_projection'] in plan.writes, 'dependency_lease': plan.state['dependency_lease'] in plan.writes, 'runtime_diagnostics': plan.state['runtime_diagnostics'] in plan.writes, 'workspace_policy': plan.state['config'] in plan.writes, 'handoff_packet': False, 'verification_gate_policy': plan.state['project'] in plan.writes and source_schema != surface.target_schema, 'plan_strategy': task_write_queued and source_schema != surface.target_schema}
    if queued_by_surface.get(surface.identifier, False):
        return 'upgrade_available'
    if not present:
        return 'current'
    if isinstance(source_schema, int) and isinstance(surface.target_schema, int):
        if source_schema > surface.target_schema:
            return 'newer_than_cli'
        if source_schema < surface.target_schema:
            return 'blocked'
    return 'current'

def assess_control_plane_state(control, plan: control.LegacyUpgradePlan) -> None:
    plan.revalidation_targets = []
    plan.manual_decisions = []
    inactive_issue_count = 0
    for task in plan.tasks.values():
        receipt = control.staged_upgrade_task_receipt(plan, task)
        continuity = control.continuity_from_receipt(receipt)
        issues = control.continuity_reconciliation_issues(plan.repo, continuity)
        if not task.active_projection:
            inactive_issue_count += len(issues)
            continue
        for issue in issues:
            payload = {'task_id': task.identifier, **issue}
            if issue.get('proof_id'):
                plan.revalidation_targets.append(payload)
            else:
                plan.manual_decisions.append(payload)
    if inactive_issue_count:
        plan.add_warning('inactive_task_revalidation_deferred', f'{inactive_issue_count} completed proof issue(s) belong to inactive tasks and remain preserved for later selection')
    task_schemas = sorted({int(task.receipt.get('schema_version', 1)) for task in plan.tasks.values()})
    continuity_schemas = sorted({int(task.receipt.get('continuity', {}).get('schema_version', 1)) for task in plan.tasks.values() if isinstance(task.receipt.get('continuity'), dict)})
    legacy_attempts = sum((1 for task in plan.tasks.values() for proof in (task.receipt.get('continuity', {}).get('proofs', []) if isinstance(task.receipt.get('continuity'), dict) else []) if isinstance(proof, dict) and any((field not in proof for field in ('attempt_id', 'attempt_index', 'outcome_sha256', 'plan_revision', 'scope_sha256')))))

    def optional_schema(path: pathlib.Path, default: int=1) -> tuple[bool, int | None]:
        if not path.exists():
            return (False, None)
        try:
            raw = control.read_json(path)
            version = raw.get('schema_version', default)
            return (True, version if isinstance(version, int) else None)
        except (OSError, json.JSONDecodeError, ValueError):
            return (True, None)
    (memory_present, memory_schema) = optional_schema(plan.state['project_memory'])
    environment_projection_present = plan.state['environment_projection'].is_file()
    domain_projection_present = plan.state['domain_projection'].is_file()
    (lease_present, lease_schema) = optional_schema(plan.state['dependency_lease'])
    (diagnostics_present, diagnostics_schema) = optional_schema(plan.state['runtime_diagnostics'])
    (policy_present, policy_schema) = optional_schema(plan.state['config'], 0)
    source_verification_policy = (
        control.VERIFICATION_GATE_POLICY
        if plan.current_version >= 3
        else control.LEGACY_VERIFICATION_GATE_POLICY
    )
    plan_records = [
        control.staged_upgrade_task_receipt(plan, task).get('continuity', {}).get('plan', {})
        for task in plan.tasks.values()
        if isinstance(control.staged_upgrade_task_receipt(plan, task).get('continuity'), dict)
    ]
    plan_strategy_adopted = bool(plan_records) and all(
        isinstance(record, dict)
        and record.get('strategy') in control.PLAN_STRATEGIES
        and isinstance(record.get('relations'), list)
        for record in plan_records
    )
    surface_sources: dict[str, tuple[bool, int | str | None, dict[str, Any]]] = {'project': (plan.project_exists, plan.source_project_schema, {}), 'task_receipts': (bool(plan.tasks), task_schemas[0] if len(task_schemas) == 1 else None, {'record_count': len(plan.tasks), 'source_schemas': task_schemas}), 'continuity': (bool(continuity_schemas), continuity_schemas[0] if len(continuity_schemas) == 1 else None, {'record_count': len(continuity_schemas), 'source_schemas': continuity_schemas}), 'proof_attempts': (legacy_attempts > 0 or bool(plan.revalidation_targets), 'append-only-v1', {'legacy_attempt_count': legacy_attempts, 'revalidation_count': len(plan.revalidation_targets), 'manual_decision_count': len(plan.manual_decisions)}), 'project_memory': (memory_present, memory_schema, {}), 'environment_projection': (environment_projection_present, 'environment-profile-v1' if environment_projection_present else None, {}), 'domain_projection': (domain_projection_present, 'domain-memory-v1' if domain_projection_present else None, {}), 'dependency_lease': (lease_present, lease_schema, {}), 'runtime_diagnostics': (diagnostics_present, diagnostics_schema, {}), 'workspace_policy': (policy_present, policy_schema, {}), 'handoff_packet': (False, 1, {'runtime_artifact': True}), 'verification_gate_policy': (True, source_verification_policy, {}), 'plan_strategy': (bool(plan_records), 'plan-strategy-v1' if plan_strategy_adopted else 'legacy-unversioned', {'record_count': len(plan_records)})}
    plan.state_surfaces = []
    for surface in control.CONTROL_PLANE_STATE_SURFACES:
        (present, source_schema, details) = surface_sources[surface.identifier]
        plan.state_surfaces.append({'id': surface.identifier, 'storage': surface.storage, 'impact': surface.impact, 'contract_revision': surface.contract_revision, 'present': present, 'source_schema': source_schema, 'target_schema': surface.target_schema, 'status': control_plane_surface_status(control, plan, surface, present=present, source_schema=source_schema), **details})

def build_legacy_upgrade_plan(control, repo: pathlib.Path, state: dict[str, pathlib.Path]) -> control.LegacyUpgradePlan:
    if not legacy_upgrade_has_control_artifacts(control, state):
        return control.LegacyUpgradePlan(repo=repo, state=state, project=control.blank_project(repo), project_exists=False, project_revision=0, current_version=control.CONTROL_PLANE_UPGRADE_VERSION, target_version=control.CONTROL_PLANE_UPGRADE_VERSION, timestamp=control.now(), source_project_schema=None)
    project_exists = state['project'].exists()
    if project_exists:
        try:
            loaded = control.load_project(state, repo)
            if loaded is None:
                raise ValueError('project registry disappeared during inspection')
            project = control.clone_json(loaded)
            project_revision = project.get('state_revision', 0)
            if isinstance(project_revision, bool) or not isinstance(project_revision, int) or project_revision < 0:
                raise ValueError('project state revision is malformed')
            current_version = control.project_upgrade_version(project)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            plan = control.LegacyUpgradePlan(repo=repo, state=state, project=control.blank_project(repo), project_exists=True, project_revision=0, current_version=0, target_version=control.CONTROL_PLANE_UPGRADE_VERSION, timestamp=control.now(), source_project_schema=None)
            plan.add_blocker('project_registry_unreadable', str(error), path=state['project'])
            plan.fingerprint = legacy_upgrade_source_fingerprint(control, state)
            return plan
    else:
        project = control.blank_project(repo)
        project['control_plane_upgrade_version'] = 0
        project_revision = 0
        current_version = 0
    plan = control.LegacyUpgradePlan(repo=repo, state=state, project=project, project_exists=project_exists, project_revision=project_revision, current_version=current_version, target_version=control.CONTROL_PLANE_UPGRADE_VERSION, timestamp=control.now(), source_project_schema=int(project.get('schema_version', 1)) if project_exists else None)
    plan.historical_runs = legacy_upgrade_historical_runs(control, state)
    if current_version > control.CONTROL_PLANE_UPGRADE_VERSION:
        plan.newer_than_cli.append({'surface': 'project', 'source_schema': current_version, 'target_schema': control.CONTROL_PLANE_UPGRADE_VERSION, 'reason': 'control plane was upgraded by a newer Auto Dev version'})
    collect_legacy_upgrade_tasks(control, plan)
    if plan.active_task_id is not None and plan.active_task_id not in plan.tasks:
        plan.add_blocker('active_task_missing', 'active task is missing from readable task records')
    if not plan.tasks and (not project_exists) and (current_version < control.CONTROL_PLANE_UPGRADE_VERSION):
        plan.add_blocker('no_task_projection_to_adopt', 'legacy control has no readable active or task projection; historical runs remain immutable evidence')
    if not plan.blockers:
        plan.pending_steps = pending_legacy_upgrade_steps(control, current_version)
        for step in plan.pending_steps:
            step.planner(plan)
            if plan.blockers:
                break
        if not plan.blockers and plan.pending_steps:
            plan.project['control_plane_upgrade_version'] = plan.target_version
            plan.project['state_revision'] = plan.project_revision + 1
            plan.project['updated_at'] = plan.timestamp
            plan.queue_write(state['project'], plan.project, record_type='project_registry')
    if not plan.blockers:
        assess_control_plane_state(control, plan)
    plan.fingerprint = legacy_upgrade_source_fingerprint(control, state)
    return plan

def legacy_upgrade_status(control, plan: control.LegacyUpgradePlan) -> str:
    if not legacy_upgrade_has_control_artifacts(control, plan.state):
        return 'unavailable'
    if plan.current_version > plan.target_version or plan.newer_than_cli:
        return 'newer_than_cli'
    if plan.blockers:
        return 'blocked'
    if plan.pending_steps or plan.current_version < plan.target_version:
        return 'upgrade_available'
    if plan.manual_decisions:
        return 'manual_decision_required'
    if plan.revalidation_targets:
        return 'reverification_required'
    return 'current'

def control_plane_upgrade_projection(
    control,
    project: dict[str, Any],
    *,
    repo: pathlib.Path | None = None,
    state: dict[str, pathlib.Path] | None = None,
    profile: str = 'full',
    active_reconciliation_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from auto_dev_internal.legacy import inspection as runctl_legacy_inspection
    return runctl_legacy_inspection.control_plane_upgrade_projection(
        control,
        project,
        repo=repo,
        state=state,
        profile=profile,
        active_reconciliation_issues=active_reconciliation_issues,
    )

def legacy_upgrade_step_payload(control, steps: Iterable[control.LegacyUpgradeStep]) -> list[dict[str, Any]]:
    from auto_dev_internal.legacy import inspection as runctl_legacy_inspection
    return runctl_legacy_inspection.legacy_upgrade_step_payload(control, steps)

def legacy_upgrade_inspection_payload(
    control,
    repo: pathlib.Path,
    state: dict[str, pathlib.Path],
    *,
    include_legacy_material: bool = False,
) -> dict[str, Any]:
    from auto_dev_internal.legacy import inspection as runctl_legacy_inspection
    return runctl_legacy_inspection.legacy_upgrade_inspection_payload(
        control,
        repo,
        state,
        include_legacy_material=include_legacy_material,
    )
