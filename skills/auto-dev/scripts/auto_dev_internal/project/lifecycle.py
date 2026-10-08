"""Project workspace lifecycle commands."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
from typing import Any

def command_project_inspect(control, args: argparse.Namespace) -> int:
    candidate = pathlib.Path(args.repo_root).expanduser().resolve()
    if not candidate.is_dir():
        raise ValueError(f"project path is not a directory: {candidate}")
    if control.auto_dev_plugin_root(candidate) == candidate:
        print(json.dumps({
            "status": "plugin_self_target",
            "git": (control.git_root(candidate) is not None),
            "project": False,
            "path": str(candidate),
            "next_action": "use_neutral_workspace",
        }, ensure_ascii=False))
        return 0
    repo = control.git_root(candidate)
    if repo is None:
        local_root = control.local_project_root(candidate)
        state = control.paths(local_root) if local_root is not None else control.paths(candidate)
        if state["project"].is_file():
            workspace = local_root or candidate
            project = control.load_project(state, workspace)
            branch, head, key = control.current_context(workspace)
            print(json.dumps({
                "status": "ready" if project is not None else "local_ready",
                "git": False,
                "project": project is not None,
                "storage_mode": "local",
                "workspace_root": str(workspace),
                "project_id": project.get("project_id") if project else None,
                "project_revision": project.get("state_revision", 0) if project else 0,
                "branch": branch,
                "head": head,
                "context_key": key,
                "branch_count": len(project.get("branches", {})) if project else 0,
                "limitations": ["no_branch", "no_commit", "no_git_diff"],
                "next_action": None,
            }, ensure_ascii=False))
            return 0
        git_available = shutil.which("git") is not None
        writable = os.access(candidate, os.W_OK)
        print(json.dumps({
            "status": "git_setup_recommended" if git_available and writable else "uninitialized",
            "git": False,
            "project": False,
            "path": str(candidate),
            "git_available": git_available,
            "writable": writable,
            "recommended_storage": "git" if git_available and writable else "local",
            "next_action": "project_init",
        }, ensure_ascii=False))
        return 0
    if repo != candidate:
        print(json.dumps({
            "status": "inside_parent_repository",
            "git": True,
            "project": False,
            "path": str(candidate),
            "repo_root": str(repo),
            "next_action": "choose_repository_root",
        }, ensure_ascii=False))
        return 0
    state = control.paths(repo)
    if state["project"].is_file():
        raw_project = control.read_json(state["project"])
        if raw_project.get("storage_mode") == "local":
            print(json.dumps({
                "status": "migration_available",
                "git": True,
                "project": True,
                "storage_mode": "local",
                "path": str(repo),
                "project_id": raw_project.get("project_id"),
                "project_revision": raw_project.get("state_revision", 0),
                "next_action": "project_migrate_to_git",
            }, ensure_ascii=False))
            return 0
    project = control.load_project(state, repo)
    branch, head, key = control.current_context(repo)
    print(json.dumps({
        "status": "ready" if project is not None else "git_ready",
        "git": True,
        "project": project is not None,
        "storage_mode": "git",
        "project_id": project.get("project_id") if project else None,
        "project_revision": project.get("state_revision", 0) if project else 0,
        "branch": branch,
        "head": head,
        "context_key": key,
        "branch_count": len(project.get("branches", {})) if project else 0,
        "next_action": None if project is not None else "project_init",
    }, ensure_ascii=False))
    return 0


def command_project_init(control, args: argparse.Namespace) -> int:
    candidate = pathlib.Path(args.repo_root).expanduser().resolve()
    if not candidate.is_dir():
        raise ValueError(f"project path is not a directory: {candidate}")
    if control.auto_dev_plugin_root(candidate) == candidate:
        raise ValueError(
            "Auto Dev will not initialize its own Plugin source as a project; "
            "use a neutral workspace or an explicit test fixture"
        )
    confirmation = control.require_concrete("project initialization confirmation", args.confirmation_source)
    repo = control.git_root(candidate)
    local_root = control.local_project_root(candidate)
    mode = args.mode or ("git" if args.git or repo is not None else None)
    if args.git and args.mode and args.mode != "git":
        raise ValueError("--git is only compatible with --mode git")
    if mode not in control.WORKSPACE_STORAGE_MODES:
        raise ValueError("project initialization requires --mode git or --mode local")
    if repo is None and local_root is not None and local_root != candidate:
        raise ValueError("project init cannot create a nested control inside an existing local workspace")
    git_initialized = False
    if repo is not None:
        if repo != candidate:
            raise ValueError("project init cannot attach a nested directory inside another repository")
        if mode != "git":
            raise ValueError("an existing Git repository must use --mode git")
    else:
        if mode == "git":
            initial_branch = control.require_concrete("initial branch", args.initial_branch)
            completed = control.run(["git", "init", "-q", "-b", initial_branch], candidate, False)
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip() or "git init failed"
                raise ValueError(detail)
            repo = control.git_root(candidate)
            if repo is None:
                raise ValueError("Git initialization completed but repository root could not be resolved")
            git_initialized = True
        else:
            repo = candidate
    state = control.paths(repo)
    if mode == "git" and state["project"].is_file():
        existing_project = control.read_json(state["project"])
        if existing_project.get("storage_mode") == "local":
            branch, head, key = control.current_context(repo)
            print(json.dumps({
                "status": "migration_available",
                "created": False,
                "git_initialized": git_initialized,
                "storage_mode": "local",
                "project_id": existing_project.get("project_id"),
                "project_revision": existing_project.get("state_revision", 0),
                "branch": branch,
                "head": head,
                "context_key": key,
                "next_action": "project_migrate_to_git",
            }, ensure_ascii=False))
            return 0
    state = control.ensure_root(repo)
    with control.state_lock(state["project"]):
        project = control.load_project(state, repo)
        created = project is None
        if project is None:
            project = control.blank_project(repo)
            branch, _, key = control.current_context(repo)
            project["branches"][key] = {
                "branch": branch,
                "active_task_id": None,
                "task_ids": [],
                "updated_at": control.now(),
            }
            project["confirmation_source"] = confirmation
        context_id, context_created = control.ensure_default_project_context(state, project)
        if created or context_created:
            project["state_revision"] = int(project.get("state_revision", 0)) + 1
            project["schema_version"] = control.PROJECT_SCHEMA_VERSION
            project["updated_at"] = control.now()
            control.write_json(state["project"], project)
    if control.project_upgrade_version(project) < control.CONTROL_PLANE_UPGRADE_VERSION:
        environment = {
            "status": "migration_required",
            "path": ".auto-dev/path.md",
            "domain_path": ".auto-dev/project-domain.md",
            "memory_revision": None,
        }
    else:
        environment = control.project_memory.initialize_profiles(
            repo, confirmation_source=confirmation
        )
    branch, head, key = control.current_context(repo)
    print(json.dumps({
        "status": "ready",
        "created": created,
        "git_initialized": git_initialized,
        "storage_mode": mode,
        "project_id": project["project_id"],
        "project_revision": project["state_revision"],
        "project_context_id": context_id,
        "environment": {
            "status": environment["status"],
            "path": environment["path"],
            "domain_path": environment["domain_path"],
            "memory_revision": environment["memory_revision"],
        },
        "receipt": control.bilingual_receipt("🧾 Auto Dev", "project_context_adopted", f"context={context_id}"),
        "branch": branch,
        "head": head,
        "context_key": key,
    }, ensure_ascii=False))
    return 0


def command_project_migrate(control, args: argparse.Namespace) -> int:
    candidate = pathlib.Path(args.repo_root).expanduser().resolve()
    repo = control.git_root(candidate)
    if repo is None or repo != candidate:
        raise ValueError("project migration to Git requires the selected workspace root to be a Git repository")
    state = control.paths(repo)
    if not state["project"].is_file():
        raise ValueError("project migration requires an existing local project control")
    confirmation = control.require_concrete("project migration confirmation", args.confirmation_source)
    state = control.ensure_root(repo)
    with control.state_lock(state["project"]):
        project = control.read_json(state["project"])
        if project.get("storage_mode") != "local":
            raise ValueError("project migration requires a local No-Git control")
        actual_revision = int(project.get("state_revision", 0))
        if args.project_revision != actual_revision:
            raise ValueError(f"project revision conflict: expected {actual_revision}, received {args.project_revision}")
        branch, head, key = control.current_context(repo)
        migration_at = control.now()
        migration_status = control.current_status(repo)
        migration_baseline = control.capture_worktree_baseline(repo, migration_status)

        def migrate_local_receipt(receipt: dict[str, Any]) -> None:
            receipt.update({
                "workspace_mode": "git",
                "base_branch": branch,
                "base_head": head,
                "initial_status": migration_status,
                "worktree_baseline": migration_baseline,
                "local_scope_baseline": None,
                "migrated_to_git_at": migration_at,
            })

        local_key = control.branch_context_key(None, None)
        local_context = project["branches"].pop(local_key, None)
        if local_context is not None:
            existing = project["branches"].get(key)
            if existing is not None and existing.get("active_task_id") not in {None, local_context.get("active_task_id")}:
                raise ValueError("Git branch already has a different active task")
            local_context["branch"] = branch
            local_context["updated_at"] = control.now()
            project["branches"][key] = local_context
        for path in state["tasks"].glob("*.json"):
            receipt = control.read_json(path)
            if receipt.get("workspace_mode") != "local":
                continue
            migrate_local_receipt(receipt)
            control.write_json(path, receipt, backup=True)
        active_updates: list[tuple[pathlib.Path, dict[str, Any]]] = []
        for path in (state["active"], state["active"].with_suffix(".bak")):
            if not path.exists():
                continue
            receipt = control.read_json(path)
            if receipt.get("workspace_mode") == "local":
                migrate_local_receipt(receipt)
                active_updates.append((path, receipt))
        for path, receipt in active_updates:
            # `active.bak` is itself a backup path; do not back it up to itself.
            control.write_json(path, receipt)
        active_path = state["active"]
        backup_path = active_path.with_suffix(".bak")
        if active_path.exists() and not backup_path.exists():
            active_receipt = next((receipt for path, receipt in active_updates if path == active_path), None)
            if active_receipt is not None:
                control.write_json(backup_path, active_receipt)
        project.update({
            "storage_mode": "git",
            "repo_fingerprint": control.project_fingerprint(repo),
            "state_revision": actual_revision + 1,
            "updated_at": control.now(),
            "migration": {
                "from": "local",
                "to": "git",
                "confirmation_source": confirmation,
                "at": migration_at,
            },
        })
        control.write_json(state["project"], project, backup=True)
    readback = control.load_project(state, repo)
    print(json.dumps({
        "status": "migrated",
        "storage_mode": "git",
        "project_id": readback["project_id"],
        "project_revision": readback["state_revision"],
        "branch": branch,
        "head": head,
        "receipt": control.bilingual_receipt("🧾 Auto Dev", "project_migrated", f"project={readback['project_id']}"),
    }, ensure_ascii=False))
    return 0
