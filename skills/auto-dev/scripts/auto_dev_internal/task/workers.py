"""Deterministic worker worktree, context capsule, and merge-queue helpers."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import pathlib
import shlex
import shutil
import tempfile
from typing import Any


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _worker_path(state: dict[str, pathlib.Path], worker_id: str) -> pathlib.Path:
    return state["workers"] / f"{worker_id}.json"


def _patch_path(state: dict[str, pathlib.Path], worker_id: str) -> pathlib.Path:
    return state["workers"] / f"{worker_id}.patch"


def _read_worker(control, state: dict[str, pathlib.Path], worker_id: str) -> dict[str, Any]:
    path = _worker_path(state, worker_id)
    if not path.is_file():
        raise ValueError(f"worker does not exist: {worker_id}")
    worker = control.read_json(path)
    if worker.get("id") != worker_id:
        raise ValueError(f"worker record id mismatch: {worker_id}")
    # Additive migration for workers created by schema v1.
    if worker.get("status") == "prepared":
        worker["status"] = "dispatch_required"
    elif worker.get("status") == "captured":
        worker["status"] = "awaiting_main"
    return worker


def _write_worker(control, state: dict[str, pathlib.Path], worker: dict[str, Any]) -> None:
    worker["schema_version"] = control.WORKER_SCHEMA_VERSION
    worker["updated_at"] = control.now()
    control.write_json(_worker_path(state, str(worker["id"])), worker, backup=True)


def _packet_context(control, receipt: dict[str, Any], continuity: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    plan = continuity.get("plan", {})
    milestone_id = packet.get("parent_id")
    nodes = {
        str(node.get("id")): node
        for node in plan.get("nodes", [])
        if isinstance(node, dict) and node.get("id")
    }
    milestone = nodes.get(str(milestone_id), {})
    root_capabilities = receipt.get("capabilities", {})
    capsule = {
        "schema": "auto-dev/worker-context/v1",
        "task": {
            "id": receipt.get("id"),
            "statement": (continuity.get("goal") or {}).get("statement") or receipt.get("task"),
            "acceptance": (continuity.get("goal") or {}).get("acceptance") or receipt.get("acceptance", []),
            "tier": receipt.get("tier"),
        },
        "milestone": {
            "id": milestone.get("id"),
            "title": milestone.get("title"),
            "state": milestone.get("milestone_state", {}),
        },
        "packet": {
            "id": packet.get("id"),
            "title": packet.get("title"),
            "target": packet.get("target"),
            "write_scope": packet.get("write_scope", []),
            "owns": packet.get("owns", []),
            "provides": packet.get("provides", []),
            "consumes": packet.get("consumes", []),
            "depends_on": packet.get("depends_on", []),
            "execution_profile": packet.get("execution_profile", "bounded"),
            "required_capabilities": packet.get("required_capabilities", []),
            "verification_policy": packet.get("verification_policy", {}),
            "review_policy": packet.get("review_policy", "proof_only"),
            "merge_policy": packet.get("merge_policy", {}),
            "model_profile": packet.get("model_profile"),
            "proofs": (packet.get("outcome") or {}).get("proofs", []),
            "assertions": packet.get("assertions", []),
            "escalation": packet.get("escalation", {}),
        },
        "contract": {
            "status": receipt.get("contract_status"),
            "snapshot": receipt.get("contract_snapshot"),
            "coverage_ids": receipt.get("contract_coverage_ids", []),
        },
        "capabilities": {
            "enabled": root_capabilities.get("enabled", []),
            "evidence": root_capabilities.get("evidence", {}),
        },
        "revisions": {
            "plan": plan.get("revision", 0),
            "state": receipt.get("state_revision", 0),
            "contract": packet.get("contract_sha256"),
            "compilation": (packet.get("execution_base") or {}).get("compilation_revision"),
        },
        "instruction": (
            "Execute only this packet. Do not expand scope, change the Root Task, "
            "enable capabilities, create another Team, or edit .auto-dev directly. "
            "Return a structured result and stop when context or proof is insufficient."
        ),
    }
    capsule["context_sha256"] = _digest(capsule)
    return capsule


def _resolve_packet(control, repo: pathlib.Path, packet_id: str) -> tuple[dict[str, pathlib.Path], dict[str, Any], dict[str, Any], dict[str, Any]]:
    state = control.ensure_root(repo)
    receipt = control.require_working_task(state)
    continuity = control.continuity_from_receipt(receipt)
    if continuity is None or continuity.get("plan", {}).get("strategy") != "rolling_graph":
        raise ValueError("worker commands require a rolling_graph continuity plan")
    nodes = {
        str(node.get("id")): node
        for node in continuity.get("plan", {}).get("nodes", [])
        if isinstance(node, dict) and node.get("id")
    }
    packet = nodes.get(packet_id)
    if packet is None or packet.get("node_role") != "work_packet":
        raise ValueError(f"worker target must be a work_packet: {packet_id}")
    return state, receipt, continuity, packet


def _changed_paths(control, worktree: pathlib.Path, base_head: str) -> list[str]:
    result = control.run(["git", "diff", "--name-only", base_head], worktree, False)
    if result.returncode not in {0, 1}:
        raise ValueError(f"worker worktree diff failed: {result.stderr.strip()}")
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    untracked = control.run(["git", "ls-files", "--others", "--exclude-standard"], worktree, False)
    if untracked.returncode == 0:
        paths.extend(line.strip() for line in untracked.stdout.splitlines() if line.strip())
    return sorted(set(paths))


def _assert_scope(control, paths: list[str], scopes: list[str]) -> list[str]:
    return sorted(path for path in paths if not control.path_in_scope(path, scopes))


def _load_result(control, path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {}
    path = pathlib.Path(path_value).expanduser()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"worker result must be valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("worker result must be a JSON object")
    allowed = {"summary", "proof_refs", "capability_evidence", "contract_effects", "unresolved_findings", "next_action"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError("worker result has unsupported fields: " + ", ".join(unknown))
    if "summary" in value and not isinstance(value["summary"], str):
        raise ValueError("worker result summary must be a string")
    for key in ("proof_refs", "capability_evidence", "unresolved_findings"):
        if key in value and not isinstance(value[key], list):
            raise ValueError(f"worker result {key} must be an array")
    if "contract_effects" in value and not isinstance(value["contract_effects"], (dict, list)):
        raise ValueError("worker result contract_effects must be an object or array")
    return value


def command_worker_prepare(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state, receipt, continuity, packet = _resolve_packet(control, repo, control.require_continuity_id("packet id", args.packet))
    milestone = next(
        node for node in continuity["plan"]["nodes"]
        if node.get("id") == packet.get("parent_id")
    )
    policy = milestone.get("milestone_state", {}).get("compilation_policy", {})
    decision = milestone.get("milestone_state", {}).get("execution_decision")
    if not isinstance(decision, dict) or not control.decision_is_current(milestone):
        raise ValueError("worker prepare requires a current milestone execution decision")
    execution_mode = decision.get("selected_mode")
    if execution_mode not in {"single_worker", "multi_worker"}:
        raise ValueError("worker prepare requires selected_mode=single_worker or multi_worker")
    if execution_mode == "multi_worker":
        if policy.get("execution_topology") != "multi_agent":
            raise ValueError("multi_worker execution requires execution_topology=multi_agent")
        if policy.get("merge_mode") != "worktree_merge_queue":
            raise ValueError("multi_worker execution requires merge_mode=worktree_merge_queue")
        if "parallel-work" not in receipt.get("capabilities", {}).get("enabled", []):
            raise ValueError("multi_worker execution requires the root parallel-work capability")
    if packet.get("status") not in {"planned", "active"}:
        raise ValueError(f"packet is not dispatchable: {packet['id']}")
    worker_id = control.require_control_id(
        "worker id", args.worker_id or f"worker-{packet['id']}-{_digest(packet)[:10]}"
    )
    existing = _worker_path(state, worker_id)
    if existing.exists():
        raise ValueError(f"worker already exists: {worker_id}")
    base_head = (packet.get("execution_base") or {}).get("head") or control.git_head(repo)
    if not base_head:
        raise ValueError("worker prepare requires a verified Git base HEAD")
    temp_root = pathlib.Path(tempfile.mkdtemp(prefix="auto-dev-worker-"))
    temp_root.rmdir()
    worktree = temp_root
    result = control.run(["git", "worktree", "add", "--detach", str(worktree), base_head], repo, False)
    if result.returncode != 0:
        raise ValueError(f"worker worktree creation failed: {result.stderr.strip()}")
    capsule = _packet_context(control, receipt, continuity, packet)
    decision_executor = decision.get("executor") if isinstance(decision.get("executor"), dict) else None
    worker = {
        "schema_version": control.WORKER_SCHEMA_VERSION,
        "id": worker_id,
        "status": "dispatch_required",
        "task_id": receipt.get("id"),
        "packet_id": packet.get("id"),
        "milestone_id": packet.get("parent_id"),
        "base_head": base_head,
        "worktree_path": str(worktree),
        "capsule": capsule,
        "context_sha256": capsule["context_sha256"],
        "plan_revision": continuity["plan"].get("revision", 0),
        "state_revision": receipt.get("state_revision", 0),
        "execution_mode": execution_mode,
        "worker_profile": decision.get("worker_profile") or "light_worker",
        "executor": decision_executor,
        "launch_status": "dispatch_required",
        "handoff": {"required": True, "owner": "main_session", "stop_before": "proof"},
        "created_at": control.now(),
    }
    _write_worker(control, state, worker)
    print(json.dumps({"status": "dispatch_required", "worker": worker}, ensure_ascii=False))
    return 0


def command_worker_bind(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    worker = _read_worker(control, state, control.require_control_id("worker id", args.worker_id))
    if worker.get("status") != "dispatch_required":
        raise ValueError(f"worker is not awaiting dispatch: {worker['id']}")
    if args.blocked_reason:
        worker.update({
            "status": "dispatch_blocked",
            "launch_status": "dispatch_blocked",
            "blocked_reason": control.require_concrete(
                "worker dispatch blocked reason", args.blocked_reason
            ),
            "blocked_at": control.now(),
        })
        _write_worker(control, state, worker)
        print(json.dumps({"status": "dispatch_blocked", "worker": worker}, ensure_ascii=False))
        return 2
    if not args.executor_ref:
        raise ValueError("worker bind requires --executor-ref or --blocked-reason")
    expected = worker.get("executor") if isinstance(worker.get("executor"), dict) else {}
    actual = {
        "provider": str(args.provider or expected.get("provider") or ""),
        "model": str(args.model or expected.get("model") or ""),
        "reasoning": str(args.reasoning or expected.get("reasoning") or ""),
    }
    missing = [key for key, value in actual.items() if not value]
    if missing:
        raise ValueError("worker bind requires executor fields: " + ", ".join(missing))
    if expected and any(actual[key] != expected.get(key) for key in actual):
        raise ValueError("worker bind executor does not match the selected worker profile")
    worker.update({
        "status": "running",
        "launch_status": "running",
        "executor_ref": control.require_control_id("executor ref", args.executor_ref),
        "executor": {"name": worker.get("worker_profile", "light_worker"), **actual},
        "bound_at": control.now(),
    })
    _write_worker(control, state, worker)
    print(json.dumps({"status": "running", "worker": worker}, ensure_ascii=False))
    return 0


def command_worker_inspect(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    worker = _read_worker(control, state, control.require_control_id("worker id", args.worker_id))
    print(json.dumps(worker, ensure_ascii=False))
    return 0


def command_worker_capture(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    worker = _read_worker(control, state, control.require_control_id("worker id", args.worker_id))
    if worker.get("status") != "running":
        raise ValueError(f"worker is not capture-ready: {worker['id']}")
    worktree = pathlib.Path(str(worker.get("worktree_path")))
    if not worktree.is_dir():
        raise ValueError(f"worker worktree is unavailable: {worktree}")
    paths = _changed_paths(control, worktree, str(worker["base_head"]))
    scopes = list(worker.get("capsule", {}).get("packet", {}).get("write_scope", []))
    outside = _assert_scope(control, paths, scopes)
    if outside:
        worker["status"] = "blocked"
        worker["blocked_reason"] = "out_of_scope_changes"
        worker["outside_scope"] = outside
        _write_worker(control, state, worker)
        raise ValueError("worker produced out-of-scope changes: " + ", ".join(outside))
    for path in control.run(["git", "ls-files", "--others", "--exclude-standard"], worktree, False).stdout.splitlines():
        control.run(["git", "add", "-N", "--", path], worktree, False)
    diff = control.run(["git", "diff", "--binary", str(worker["base_head"])], worktree, False)
    if diff.returncode not in {0, 1}:
        raise ValueError(f"worker patch capture failed: {diff.stderr.strip()}")
    patch_path = _patch_path(state, str(worker["id"]))
    control.write_text(patch_path, diff.stdout)
    result = _load_result(control, args.result_file)
    worker.update({
        "status": "awaiting_main",
        "changed_paths": paths,
        "patch_path": str(patch_path),
        "result": result,
        "captured_at": control.now(),
        "handoff_required": True,
    })
    _write_worker(control, state, worker)
    print(json.dumps({"status": "captured", "worker": worker}, ensure_ascii=False))
    return 0


def _apply_worker_patch(control, repo: pathlib.Path, state: dict[str, pathlib.Path], worker: dict[str, Any]) -> dict[str, Any]:
    if worker.get("status") not in {"awaiting_main", "captured"}:
        raise ValueError(f"worker is not apply-ready: {worker['id']}")
    current_head = control.git_head(repo)
    if current_head != worker.get("base_head"):
        worker["status"] = "conflicted"
        worker["conflict"] = {"kind": "base_drift", "expected": worker.get("base_head"), "actual": current_head}
        _write_worker(control, state, worker)
        raise ValueError("worker base HEAD drifted; rebase or recompile before apply")
    patch_path = pathlib.Path(str(worker.get("patch_path")))
    if not patch_path.is_file():
        raise ValueError("worker patch is missing")
    patch_text = patch_path.read_text(encoding="utf-8")
    if patch_text.strip():
        result = control.run(["git", "apply", "--3way", "--binary", str(patch_path)], repo, False)
        if result.returncode != 0:
            worker["status"] = "conflicted"
            worker["conflict"] = {"kind": "patch_apply", "stderr": result.stderr.strip()[:2000]}
            _write_worker(control, state, worker)
            raise ValueError("worker patch could not be applied cleanly")
    worker["status"] = "applied"
    worker["applied_at"] = control.now()
    worker["applied_head"] = control.git_head(repo)
    _write_worker(control, state, worker)
    return worker


def command_worker_apply(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    worker = _read_worker(control, state, control.require_control_id("worker id", args.worker_id))
    worker = _apply_worker_patch(control, repo, state, worker)
    print(json.dumps({"status": "applied", "worker": worker}, ensure_ascii=False))
    return 0


def _worker_packet(control, repo: pathlib.Path, worker: dict[str, Any]):
    state, receipt, continuity, packet = _resolve_packet(control, repo, str(worker.get("packet_id")))
    milestone = next(
        (node for node in continuity.get("plan", {}).get("nodes", [])
         if node.get("id") == packet.get("parent_id")),
        None,
    )
    if not isinstance(milestone, dict):
        raise ValueError("worker packet milestone is missing")
    return state, receipt, continuity, packet, milestone


def command_worker_finalize_inspect(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    worker = _read_worker(control, state, control.require_control_id("worker id", args.worker_id))
    state, receipt, continuity, packet, milestone = _worker_packet(control, repo, worker)
    if worker.get("status") not in {"awaiting_main", "applied"}:
        raise ValueError("worker finalize requires status=awaiting_main or applied")
    proofs = (packet.get("outcome") or {}).get("proofs", [])
    print(json.dumps({
        "status": "ready",
        "worker": worker,
        "packet": {"id": packet.get("id"), "title": packet.get("title"), "status": packet.get("status")},
        "proofs": proofs,
        "milestone_id": milestone.get("id"),
        "plan_revision": continuity.get("plan", {}).get("revision", 0),
        "state_revision": receipt.get("state_revision", 0),
        "next_action": "Run host proof and checkpoint through packet finalize apply",
    }, ensure_ascii=False))
    return 0


def command_worker_finalize_apply(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    worker = _read_worker(control, state, control.require_control_id("worker id", args.worker_id))
    state, receipt, continuity, packet, milestone = _worker_packet(control, repo, worker)
    if worker.get("status") not in {"awaiting_main", "applied"}:
        raise ValueError("worker finalize requires status=awaiting_main or applied")
    if args.plan_revision != int(continuity.get("plan", {}).get("revision", 0)):
        raise ValueError("packet finalize plan revision conflict")
    if args.state_revision != int(receipt.get("state_revision", 0)):
        raise ValueError("packet finalize state revision conflict")
    decision = milestone.get("milestone_state", {}).get("execution_decision")
    if not isinstance(decision, dict) or decision.get("selected_mode") not in {"single_worker", "multi_worker"}:
        raise ValueError("packet finalize requires a selected worker execution mode")
    if worker.get("status") != "applied":
        worker = _apply_worker_patch(control, repo, state, worker)
    proof_ids: list[str] = []
    for proof in (packet.get("outcome") or {}).get("proofs", []):
        proof_id = str(proof.get("id"))
        recipe = proof.get("recipe") if isinstance(proof, dict) else None
        if not isinstance(recipe, dict) or not isinstance(recipe.get("argv"), list):
            raise ValueError(f"packet proof recipe is incomplete: {packet.get('id')}/{proof_id}")
        latest_receipt = control.require_working_task(control.ensure_root(repo))
        latest_continuity = control.continuity_from_receipt(latest_receipt)
        proof_args = argparse.Namespace(
            repo_root=str(repo), node=str(packet.get("id")), proof_id=proof_id,
            plan_revision=int(latest_continuity.get("plan", {}).get("revision", 0)),
            state_revision=int(latest_receipt.get("state_revision", 0)),
            command=shlex.join([str(value) for value in recipe["argv"]]),
            evidence_file=recipe.get("evidence_file"), revalidate=False,
            failure_classification=None,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            proof_result = control.command_proof(proof_args)
        if proof_result != 0:
            raise ValueError(f"packet finalize proof failed: {packet.get('id')}/{proof_id}")
        proof_ids.append(proof_id)
    latest_receipt = control.require_working_task(control.ensure_root(repo))
    latest_continuity = control.continuity_from_receipt(latest_receipt)
    checkpoint_args = argparse.Namespace(
        repo_root=str(repo), node=str(packet.get("id")),
        plan_revision=int(latest_continuity.get("plan", {}).get("revision", 0)),
        state_revision=int(latest_receipt.get("state_revision", 0)), status="done",
        summary=control.require_concrete("packet finalize summary", args.summary),
        evidence=control.require_concrete_list("packet finalize evidence", args.evidence),
        next_node=None, next_action=None, gap_id=None, gap_summary=None,
        gap_owner="agent", non_blocking=False, resolve_gap=[],
    )
    with contextlib.redirect_stdout(io.StringIO()):
        control.command_checkpoint(checkpoint_args)
    latest_state = control.ensure_root(repo)
    latest_receipt = control.require_working_task(latest_state)
    latest_continuity = control.continuity_from_receipt(latest_receipt)
    latest_nodes = {node.get("id"): node for node in latest_continuity.get("plan", {}).get("nodes", [])}
    latest_milestone = latest_nodes.get(packet.get("parent_id"))
    if isinstance(latest_milestone, dict):
        decision = latest_milestone.setdefault("milestone_state", {}).get("execution_decision")
        work_packets = [
            node for node in latest_nodes.values()
            if node.get("parent_id") == latest_milestone.get("id")
            and node.get("node_role") == "work_packet"
        ]
        if (
            isinstance(decision, dict)
            and decision.get("boundary") == "before_integration"
            and all(node.get("status") in {"done", "superseded"} for node in work_packets)
            and latest_continuity.get("current_node") is None
            and decision.get("status") != "awaiting_main"
        ):
            decision.update({
                "status": "awaiting_main",
                "owner": "main_session",
                "handoff_status": "required",
                "handoff_reason": "packets_complete_before_integration",
            })
            latest_continuity["next_action"] = "Main session owns Integration and Milestone Review"
            control.continuity_event(
                latest_receipt,
                "packet_handoff_required",
                milestone_id=latest_milestone.get("id"),
                packet_id=packet.get("id"),
                stop_before="integration",
            )
            next_state_revision = control.write_active(
                latest_state,
                latest_receipt,
                expected_revision=int(latest_receipt.get("state_revision", 0)),
            )
            latest_receipt["state_revision"] = next_state_revision
    worker = _read_worker(control, latest_state, str(worker.get("id")))
    worker["status"] = "finalized"
    worker["finalized_at"] = control.now()
    worker["proof_ids"] = proof_ids
    worker["handoff_required"] = False
    _write_worker(control, latest_state, worker)
    print(json.dumps({
        "status": "finalized", "worker": worker, "packet_id": packet.get("id"),
        "proof_ids": proof_ids,
        "current_node": latest_continuity.get("current_node"),
        "state_revision": latest_receipt.get("state_revision", 0),
    }, ensure_ascii=False))
    return 0


def command_worker_cleanup(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    worker = _read_worker(control, state, control.require_control_id("worker id", args.worker_id))
    worktree = pathlib.Path(str(worker.get("worktree_path")))
    if worktree.exists():
        result = control.run(["git", "worktree", "remove", "--force", str(worktree)], repo, False)
        if result.returncode != 0:
            raise ValueError(f"worker worktree cleanup failed: {result.stderr.strip()}")
    worker["status"] = "cleaned"
    worker["cleaned_at"] = control.now()
    _write_worker(control, state, worker)
    print(json.dumps({"status": "cleaned", "worker": worker}, ensure_ascii=False))
    return 0
