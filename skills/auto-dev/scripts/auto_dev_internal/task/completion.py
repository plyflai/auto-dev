"""Completion, archival, and abandonment command lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
from typing import Any

def validate_completion_readiness(
    control,
    repo: pathlib.Path,
    state: dict[str, pathlib.Path],
    receipt: dict[str, Any],
    *,
    allow_review_ready: bool = False,
) -> None:
    if receipt["exhausted_budgets"]:
        raise ValueError(
            "passed runs cannot finish with exhausted budgets: "
            + ", ".join(receipt["exhausted_budgets"])
        )
    continuity = control.continuity_from_receipt(receipt)
    if continuity is not None:
        diagnostic = control.diagnostic_projection(repo, continuity)
        if diagnostic is not None:
            resolution = diagnostic.get("resolution") if isinstance(diagnostic.get("resolution"), dict) else {}
            recovery = diagnostic.get("recovery") if isinstance(diagnostic.get("recovery"), dict) else {}
            outcome = resolution.get("outcome")
            if outcome == "root_cause_confirmed":
                if not resolution.get("fresh"):
                    raise ValueError("Deep Debug root-cause evidence is stale")
                if recovery.get("status") != "verified" or not recovery.get("fresh"):
                    raise ValueError("Deep Debug requires fresh verified recovery before review")
                if recovery.get("probe_cleanup") != "complete":
                    raise ValueError("Deep Debug temporary probes must be cleaned before review")
            elif outcome == "no_defect_observed":
                if not resolution.get("fresh") or recovery.get("status") != "not_applicable":
                    raise ValueError("Deep Debug no-defect result requires fresh evidence and closed recovery")
            else:
                raise ValueError(
                    "Deep Debug must resolve to a confirmed recovered cause or no_defect_observed before review"
                )
        unfinished = [
            node["id"] for node in continuity["plan"].get("nodes", [])
            if node.get("status") not in {"done", "superseded"}
        ]
        blocking_gaps = [
            gap["id"] for gap in continuity.get("gaps", [])
            if gap.get("status") == "open" and gap.get("blocking")
        ]
        if unfinished:
            raise ValueError(f"passed run has unfinished continuity nodes: {', '.join(unfinished)}")
        if blocking_gaps:
            raise ValueError(f"passed run has blocking continuity gaps: {', '.join(blocking_gaps)}")
        if continuity.get("pending_action"):
            raise ValueError(
                f"passed run has pending action: {continuity['pending_action'].get('action_id')}"
            )
    else:
        outcome = receipt.get("outcome")
        if not outcome:
            raise ValueError("passed Direct run requires a run-level outcome contract")
        required_proofs = {proof["id"] for proof in outcome.get("proofs", [])}
        passed_proofs = {
            proof_id
            for proof_spec in outcome.get("proofs", [])
            for proof_id in [str(proof_spec.get("id"))]
            for proof in [control.latest_proof(receipt.get("proofs", []), node_id="run", proof_id=proof_id)]
            if proof
            and proof.get("status") == "passed"
            and control.proof_is_fresh(
                proof,
                outcome=outcome,
                repo=repo,
                plan_revision=0,
            )
            and proof.get("outcome_sha256") == control.outcome_digest(outcome)
        }
        missing_proofs = sorted(required_proofs - passed_proofs)
        if missing_proofs:
            raise ValueError(
                "passed Direct run has no successful proof for: " + ", ".join(missing_proofs)
            )
    checkpoint_protection = control.workspace_checkpoint_protection_state(repo, state, receipt)
    before_pending = checkpoint_protection["before_pending"]
    before_invalid = checkpoint_protection["before_invalid"]
    after_pending = checkpoint_protection["after_pending"]
    after_invalid = checkpoint_protection["after_invalid"]
    if before_pending:
        raise ValueError(
            "workspace checkpoint protection requires a recorded baseline before review: "
            + ", ".join(before_pending)
        )
    if before_invalid:
        raise ValueError(
            "workspace checkpoint protection baseline ref is missing or mismatched: "
            + ", ".join(before_invalid)
        )
    if after_pending:
        raise ValueError(
            "workspace checkpoint protection requires a recorded archive after the protected node: "
            + ", ".join(after_pending)
        )
    if after_invalid:
        raise ValueError(
            "workspace checkpoint protection archive ref is missing or mismatched: "
            + ", ".join(after_invalid)
        )
    control.validate_contract_readiness(receipt, continuity, complete=True, repo=repo)
    strict = control.build_status_payload(repo, state, view="compact")
    allowed_blockers = {"review_ready"} if allow_review_ready else set()
    blockers = [
        blocker for blocker in strict.get("strict_blockers", [])
        if blocker not in allowed_blockers
    ]
    if blockers:
        raise ValueError("passed run requires reconciled control state: " + ", ".join(blockers))


def archive_receipt(control, state: dict[str, pathlib.Path], receipt: dict[str, Any]) -> pathlib.Path:
    receipt["schema_version"] = control.SCHEMA_VERSION
    receipt["state_revision"] = int(receipt.get("state_revision", 0)) + 1
    control.sync_task_projection(state, receipt, selected=False)
    run_path = state["runs"] / f"{receipt['id']}.json"
    if not run_path.exists():
        control.write_json(run_path, receipt)
    history_has_run = False
    if state["history"].exists():
        with state["history"].open("r", encoding="utf-8") as handle:
            history_has_run = any(
                json.loads(line).get("id") == receipt["id"]
                for line in handle if line.strip()
            )
    if not history_has_run:
        with state["history"].open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return run_path


def archive(control, state: dict[str, pathlib.Path], receipt: dict[str, Any]) -> pathlib.Path:
    run_path = archive_receipt(control, state, receipt)
    if state["active"].exists() and control.read_json(state["active"]).get("id") == receipt.get("id"):
        state["active"].unlink(missing_ok=True)
        state["active"].with_suffix(".bak").unlink(missing_ok=True)
    return run_path


def command_finish(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_active(state)
    if args.status == "passed":
        if receipt.get("status") != "review_ready":
            raise ValueError("passed archival requires a selected review_ready task")
        if args.file or args.validation or args.risk:
            raise ValueError("passed archival uses review_ready evidence; resume and re-review to change files, validation, or risks")
        branch = control.current_branch(repo)
        if control.is_protected(branch, control.protected_branches(state)):
            raise ValueError(f"passed runs cannot finish on protected branch {branch}")
        review = receipt.get("review") if isinstance(receipt.get("review"), dict) else None
        if review is None or not review.get("validation_results"):
            raise ValueError("review_ready task is missing review evidence")
        current_head = control.git_head(repo)
        current_worktree = control.workspace_product_status(control.current_status(repo))
        prepared_worktree = review.get("prepared_status")
        if (
            review.get("prepared_head") != current_head
            or not isinstance(prepared_worktree, list)
            or control.workspace_product_status(prepared_worktree) != current_worktree
        ):
            raise ValueError("task changed after review_ready; resume and review it again before archival")
        validate_completion_readiness(control, repo, state, receipt, allow_review_ready=True)
        confirmation_source = control.require_concrete("passed confirmation source", args.confirmation_source or "")
        receipt.update({
            "schema_version": control.SCHEMA_VERSION,
            "status": "passed",
            "summary": control.require_concrete("passed summary", args.summary),
            "changed_files": review.get("changed_files", []),
            "validation_results": review["validation_results"],
            "remaining_risks": review.get("remaining_risks", []),
            "accepted_at": control.now(),
            "acceptance_confirmation_source": confirmation_source,
            "final_head": current_head,
            "final_status": current_worktree,
            "finished_at": control.now(),
        })
        control.continuity_event(
            receipt,
            "review_accepted",
            confirmation_source=confirmation_source,
        )
    else:
        if receipt.get("status") != "active":
            raise ValueError(f"only an active task can finish as {args.status}")
        receipt.update({
            "schema_version": control.SCHEMA_VERSION,
            "status": args.status,
            "summary": control.require_concrete("summary", args.summary),
            "changed_files": args.file,
            "validation_results": args.validation,
            "remaining_risks": args.risk,
            "final_head": control.git_head(repo),
            "final_status": control.workspace_product_status(control.current_status(repo)),
            "finished_at": control.now(),
        })
    run_path = archive(control, state, receipt)
    print(json.dumps({"status": args.status, "id": receipt["id"], "receipt": str(run_path.relative_to(repo))}, ensure_ascii=False))
    return 0


def command_abandon(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_active(state)
    receipt.update({
        "schema_version": control.SCHEMA_VERSION,
        "status": "abandoned",
        "summary": control.require_concrete("abandon reason", args.reason),
        "final_head": control.git_head(repo),
            "final_status": control.workspace_product_status(control.current_status(repo)),
        "finished_at": control.now(),
    })
    run_path = archive(control, state, receipt)
    print(json.dumps({
        "status": "abandoned",
        "id": receipt["id"],
        "receipt": str(run_path.relative_to(repo)),
    }, ensure_ascii=False))
    return 0
