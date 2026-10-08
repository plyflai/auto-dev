"""Compile-time proof recipe validation and isolated preflight execution."""

from __future__ import annotations

import pathlib
import shutil
import tempfile
from typing import Any


def validate_executable_contracts(
    control,
    receipt: dict[str, Any],
    nodes: list[dict[str, Any]],
    milestone_id: str,
) -> None:
    """Reject packet contracts that current scopes and proof runtimes cannot execute."""
    task_scopes = [str(value) for value in receipt.get("planned_scope", [])]
    contract = receipt.get("contract_snapshot")
    coverage = {
        str(item.get("id")): item
        for item in (contract or {}).get("required_coverage", [])
        if isinstance(item, dict) and item.get("id")
    } if isinstance(contract, dict) else {}
    children = [
        node for node in nodes
        if node.get("parent_id") == milestone_id and node.get("status") != "superseded"
    ]
    for node in children:
        node_id = str(node.get("id"))
        for raw_scope in node.get("write_scope", []):
            scope = str(raw_scope)
            if any(token in scope for token in ("*", "?", "[", "]")):
                raise ValueError(
                    f"node {node_id} write_scope does not support glob patterns: {scope}"
                )
            if not control.path_in_scope(scope, task_scopes):
                raise ValueError(
                    f"node {node_id} write_scope is outside the Task planned_scope: {scope}"
                )
        for proof in (node.get("outcome") or {}).get("proofs", []):
            if not isinstance(proof, dict):
                continue
            recipe = proof.get("recipe")
            if not isinstance(recipe, dict):
                continue
            cwd = pathlib.PurePosixPath(str(recipe.get("cwd") or "."))
            if cwd.is_absolute() or ".." in cwd.parts:
                raise ValueError(
                    f"node {node_id} proof {proof.get('id')} cwd escapes the repository"
                )
            for key in ("inputs", "observed_paths"):
                for raw_path in recipe.get(key, []):
                    candidate = pathlib.PurePosixPath(str(raw_path))
                    if candidate.is_absolute() or ".." in candidate.parts:
                        raise ValueError(
                            f"node {node_id} proof {proof.get('id')} {key} path escapes the repository"
                        )
            if recipe.get("evidence_file") is None:
                continue
            proof_coverage = {str(value) for value in proof.get("coverage_ids", []) if value}
            artifact_backed = any(
                isinstance(coverage.get(coverage_id), dict)
                and coverage[coverage_id].get("artifact_schema")
                for coverage_id in proof_coverage
            )
            evidence_schema = recipe.get("evidence_schema")
            if not artifact_backed and evidence_schema not in {
                control.E2E_EVIDENCE_SCHEMA,
                control.RELEASE_EVIDENCE_SCHEMA,
                control.PERFORMANCE_EVIDENCE_SCHEMA,
            }:
                raise ValueError(
                    f"node {node_id} proof {proof.get('id')} evidence_file requires a supported "
                    "evidence_schema or artifact-backed coverage"
                )


def run_proof_preflights(
    control, repo: pathlib.Path, nodes: list[dict[str, Any]], milestone_id: str
) -> None:
    """Check recipe executability and run only explicitly declared preflights in isolation."""
    preflights: list[tuple[str, str, dict[str, Any]]] = []
    resolved_repo = repo.resolve()
    for node in nodes:
        if node.get("parent_id") != milestone_id or node.get("status") == "superseded":
            continue
        for proof in (node.get("outcome") or {}).get("proofs", []):
            recipe = proof.get("recipe") if isinstance(proof, dict) else None
            if not isinstance(recipe, dict):
                continue
            node_id = str(node.get("id"))
            proof_id = str(proof.get("id"))
            write_scope = [str(value) for value in node.get("write_scope", [])]
            cwd = (resolved_repo / str(recipe.get("cwd") or ".")).resolve()
            if not cwd.is_dir():
                raise ValueError(
                    f"node {node_id} proof {proof_id} cwd does not exist: {recipe.get('cwd')}"
                )
            for input_path in recipe.get("inputs", []):
                target = (resolved_repo / str(input_path)).resolve()
                if not target.exists() and not control.path_in_scope(str(input_path), write_scope):
                    raise ValueError(
                        f"node {node_id} proof {proof_id} input does not exist: {input_path}"
                    )
            argv = recipe.get("argv", [])
            if argv:
                executable = str(argv[0])
                if "/" in executable:
                    executable_path = pathlib.Path(executable)
                    if not executable_path.is_absolute():
                        executable_path = cwd / executable_path
                    if not executable_path.exists():
                        raise ValueError(
                            f"node {node_id} proof {proof_id} executable does not exist: {executable}"
                        )
                elif shutil.which(executable) is None:
                    raise ValueError(
                        f"node {node_id} proof {proof_id} executable is unavailable: {executable}"
                    )
            if argv and len(argv) > 1 and argv[0].startswith("python") and str(argv[1]).endswith(".py"):
                script = (cwd / str(argv[1])).resolve()
                if not script.is_file():
                    raise ValueError(
                        f"node {node_id} proof {proof_id} script does not exist: {argv[1]}"
                    )
            if recipe.get("preflight_argv"):
                preflights.append((node_id, proof_id, recipe))
    if not preflights:
        return

    head = control.git_head(repo)
    temp_root = pathlib.Path(tempfile.mkdtemp(prefix="auto-dev-proof-preflight-"))
    temp_root.rmdir()
    added = False
    try:
        result = control.run(
            ["git", "worktree", "add", "--detach", str(temp_root), head], repo, False
        )
        if result.returncode != 0:
            raise ValueError("proof preflight worktree creation failed: " + result.stderr.strip())
        added = True
        resolved_root = temp_root.resolve()
        for node_id, proof_id, recipe in preflights:
            cwd = (resolved_root / str(recipe.get("cwd") or ".")).resolve()
            try:
                cwd.relative_to(resolved_root)
            except ValueError as error:
                raise ValueError(
                    f"node {node_id} proof {proof_id} cwd escapes the repository"
                ) from error
            if not cwd.is_dir():
                raise ValueError(
                    f"node {node_id} proof {proof_id} cwd does not exist: {recipe.get('cwd')}"
                )
            completed = control.run(
                [str(value) for value in recipe["preflight_argv"]], cwd, False
            )
            if completed.returncode != 0:
                summary = (completed.stderr or completed.stdout).strip()[:500]
                raise ValueError(f"node {node_id} proof {proof_id} preflight failed: {summary}")
    finally:
        if added:
            control.run(["git", "worktree", "remove", "--force", str(temp_root)], repo, False)
        elif temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
