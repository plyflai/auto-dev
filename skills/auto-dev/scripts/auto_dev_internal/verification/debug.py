"""Deep Debug lifecycle and reusable incident-case orchestration."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import re
from typing import Any


def normalize_diagnostic(control, raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("diagnostic state must be an object")
    raw["schema_version"] = control.DIAGNOSTIC_SCHEMA_VERSION
    raw.setdefault("profile", "deep")
    raw.setdefault("status", "reproducing")
    if raw["profile"] != "deep":
        raise ValueError("diagnostic profile must be deep")
    if raw["status"] not in control.DIAGNOSTIC_STATUSES:
        raise ValueError(f"unsupported diagnostic status: {raw['status']}")
    raw.setdefault("symptom", {"summary": "", "scope": [], "environment_refs": []})
    raw.setdefault(
        "case_search",
        {
            "status": "not_run",
            "memory_revision": 0,
            "query_digest": None,
            "candidate_case_ids": [],
            "selected_case_ids": [],
            "warnings": [],
        },
    )
    if raw["case_search"].get("status") not in control.DIAGNOSTIC_CASE_SEARCH_STATUSES:
        raise ValueError("unsupported diagnostic case-search status")
    raw.setdefault(
        "reproduction",
        {
            "gate": "not_ready",
            "proof_refs": [],
            "evidence_refs": [],
            "original_proof_refs": [],
            "minimal_proof_refs": [],
            "runs": 0,
            "failures": 0,
            "agent_runnable": None,
        },
    )
    if raw["reproduction"].get("gate") not in control.DIAGNOSTIC_REPRODUCTION_GATES:
        raise ValueError("unsupported diagnostic reproduction gate")
    hypotheses = raw.setdefault("hypotheses", [])
    observations = raw.setdefault("observations", [])
    if not isinstance(hypotheses, list) or not all((isinstance(item, dict) for item in hypotheses)):
        raise ValueError("diagnostic hypotheses must be a list of objects")
    if not isinstance(observations, list) or not all(
        (isinstance(item, dict) for item in observations)
    ):
        raise ValueError("diagnostic observations must be a list of objects")
    hypothesis_ids: set[str] = set()
    for hypothesis in hypotheses:
        hypothesis_id = control.require_continuity_id(
            "hypothesis id", str(hypothesis.get("id") or "")
        )
        if hypothesis_id in hypothesis_ids:
            raise ValueError(f"duplicate diagnostic hypothesis: {hypothesis_id}")
        hypothesis_ids.add(hypothesis_id)
        hypothesis.setdefault("status", "pending")
        hypothesis.setdefault("proof_refs", [])
        hypothesis.setdefault("evidence_refs", [])
        if hypothesis["status"] not in control.DIAGNOSTIC_HYPOTHESIS_STATUSES:
            raise ValueError(f"unsupported diagnostic hypothesis status: {hypothesis['status']}")
    observation_ids: set[str] = set()
    for observation in observations:
        observation_id = control.require_continuity_id(
            "observation id", str(observation.get("id") or "")
        )
        if observation_id in observation_ids:
            raise ValueError(f"duplicate diagnostic observation: {observation_id}")
        observation_ids.add(observation_id)
        if observation.get("hypothesis_id") not in hypothesis_ids:
            raise ValueError(
                f"diagnostic observation references unknown hypothesis: {observation.get('hypothesis_id')}"
            )
        if observation.get("verdict") not in control.DIAGNOSTIC_VERDICTS:
            raise ValueError("unsupported diagnostic observation verdict")
        observation.setdefault("proof_refs", [])
        observation.setdefault("evidence_refs", [])
    active = raw.setdefault("active_hypothesis_id", None)
    if active is not None and active not in hypothesis_ids:
        raise ValueError(f"active diagnostic hypothesis does not exist: {active}")
    resolution = raw.setdefault("resolution", None)
    if resolution is not None:
        if (
            not isinstance(resolution, dict)
            or resolution.get("outcome") not in control.DIAGNOSTIC_RESOLUTIONS
        ):
            raise ValueError("unsupported diagnostic resolution")
        resolution.setdefault("evidence_refs", [])
    recovery = raw.setdefault(
        "recovery",
        {
            "status": "unverified",
            "proof_refs": [],
            "evidence_refs": [],
            "probe_cleanup": "pending",
            "remaining_risks": [],
            "confirmation_owner": None,
        },
    )
    if recovery.get("status") not in control.DIAGNOSTIC_RECOVERY_STATUSES:
        raise ValueError("unsupported diagnostic recovery status")
    if recovery.get("probe_cleanup") not in control.DIAGNOSTIC_PROBE_CLEANUP:
        raise ValueError("unsupported diagnostic probe-cleanup status")
    recovery.setdefault("proof_refs", [])
    recovery.setdefault("evidence_refs", [])
    recovery.setdefault("remaining_risks", [])
    raw.setdefault("next_probe", None)
    return raw


def diagnostic_refs_fresh(
    control,
    repo: pathlib.Path,
    continuity: dict[str, Any],
    *,
    proof_refs: control.Iterable[str],
    evidence_refs: control.Iterable[str],
    require_passed: bool = False,
) -> bool:
    proof_map = control.proof_attempts_by_id(continuity)
    evidence_map = control.evidence_links_by_id(continuity)
    proof_ids = list(proof_refs)
    evidence_ids = list(evidence_refs)
    if not proof_ids and (not evidence_ids):
        return False
    for proof_id in proof_ids:
        proof = proof_map.get(proof_id)
        if proof is None or not control.proof_context_is_fresh(
            proof, continuity=continuity, repo=repo
        ):
            return False
        if require_passed and proof.get("status") != "passed":
            return False
    return all((evidence_id in evidence_map for evidence_id in evidence_ids))


def diagnostic_projection(
    control, repo: pathlib.Path, continuity: dict[str, Any] | None
) -> dict[str, Any] | None:
    if continuity is None:
        return None
    diagnostic = normalize_diagnostic(control, continuity.get("diagnostic"))
    if diagnostic is None:
        return None
    projected = copy.deepcopy(diagnostic)
    for observation in projected.get("observations", []):
        observation["fresh"] = diagnostic_refs_fresh(
            control,
            repo,
            continuity,
            proof_refs=observation.get("proof_refs", []),
            evidence_refs=observation.get("evidence_refs", []),
        )
    observations_by_hypothesis: dict[str, list[dict[str, Any]]] = {}
    for observation in projected.get("observations", []):
        observations_by_hypothesis.setdefault(str(observation.get("hypothesis_id")), []).append(
            observation
        )
    for hypothesis in projected.get("hypotheses", []):
        observations = observations_by_hypothesis.get(str(hypothesis.get("id")), [])
        latest = observations[-1] if observations else None
        hypothesis["fresh"] = bool(latest and latest.get("fresh"))
        hypothesis["effective_status"] = (
            latest.get("verdict")
            if latest and latest.get("fresh")
            else "stale" if latest else "pending"
        )
    reproduction = projected.get("reproduction", {})
    reproduction["fresh"] = diagnostic_refs_fresh(
        control,
        repo,
        continuity,
        proof_refs=reproduction.get("proof_refs", []),
        evidence_refs=reproduction.get("evidence_refs", []),
    )
    resolution = projected.get("resolution")
    if isinstance(resolution, dict):
        if resolution.get("outcome") == "root_cause_confirmed":
            resolution["fresh"] = any(
                (
                    item.get("effective_status") == "confirmed"
                    for item in projected.get("hypotheses", [])
                )
            )
        elif resolution.get("outcome") == "no_defect_observed":
            resolution["fresh"] = bool(
                reproduction.get("gate") == "ready_green_no_defect" and reproduction.get("fresh")
            )
        else:
            resolution["fresh"] = True
    recovery = projected.get("recovery", {})
    recovery["fresh"] = recovery.get("status") == "not_applicable" or diagnostic_refs_fresh(
        control,
        repo,
        continuity,
        proof_refs=recovery.get("proof_refs", []),
        evidence_refs=recovery.get("evidence_refs", []),
        require_passed=recovery.get("status") == "verified",
    )
    return projected


def diagnostic_summary(control, projection: dict[str, Any] | None) -> dict[str, Any] | None:
    if projection is None:
        return None
    hypotheses = projection.get("hypotheses", [])
    observations = projection.get("observations", [])
    resolution = (
        projection.get("resolution") if isinstance(projection.get("resolution"), dict) else {}
    )
    recovery = projection.get("recovery") if isinstance(projection.get("recovery"), dict) else {}
    case_search = (
        projection.get("case_search") if isinstance(projection.get("case_search"), dict) else {}
    )
    return {
        "profile": projection.get("profile"),
        "status": projection.get("status"),
        "reproduction_gate": projection.get("reproduction", {}).get("gate"),
        "case_search_status": case_search.get("status"),
        "case_match_count": len(case_search.get("candidate_case_ids", [])),
        "active_hypothesis_id": projection.get("active_hypothesis_id"),
        "hypothesis_count": len(hypotheses),
        "last_verdict": observations[-1].get("verdict") if observations else None,
        "resolution_outcome": resolution.get("outcome"),
        "resolution_fresh": resolution.get("fresh") if resolution else None,
        "recovery_status": recovery.get("status"),
        "recovery_fresh": recovery.get("fresh"),
        "next_probe": projection.get("next_probe"),
    }


def debug_command_context(
    control, args: argparse.Namespace, *, require_existing: bool = True
) -> tuple[
    pathlib.Path,
    dict[str, pathlib.Path],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any] | None,
    int,
]:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_working_task(state)
    loaded_revision = int(receipt.get("state_revision", 0))
    if args.state_revision != loaded_revision:
        raise ValueError(
            f"state revision conflict: expected {loaded_revision}, received {args.state_revision}"
        )
    continuity = control.continuity_from_receipt(receipt)
    if continuity is None or not continuity.get("plan", {}).get("nodes"):
        raise ValueError("Deep Debug requires an initialized Team continuity plan")
    control.require_action_node(continuity, args.node)
    diagnostic = normalize_diagnostic(control, continuity.get("diagnostic"))
    if require_existing and diagnostic is None:
        raise ValueError("Deep Debug has not started for the current task")
    return (repo, state, receipt, continuity, diagnostic, loaded_revision)


def require_diagnostic_refs(
    control,
    repo: pathlib.Path,
    continuity: dict[str, Any],
    proof_refs: control.Iterable[str],
    evidence_refs: control.Iterable[str],
) -> tuple[list[str], list[str]]:
    proofs = [control.require_continuity_id("proof attempt ref", value) for value in proof_refs]
    evidence = [control.require_continuity_id("evidence ref", value) for value in evidence_refs]
    if not proofs and (not evidence):
        raise ValueError("diagnostic evidence requires at least one --proof-ref or --evidence-ref")
    proof_map = control.proof_attempts_by_id(continuity)
    evidence_map = control.evidence_links_by_id(continuity)
    missing_proofs = [value for value in proofs if value not in proof_map]
    missing_evidence = [value for value in evidence if value not in evidence_map]
    if missing_proofs or missing_evidence:
        raise ValueError(
            "diagnostic evidence refs are not present in the current task: "
            + ", ".join([*missing_proofs, *missing_evidence])
        )
    if not diagnostic_refs_fresh(
        control, repo, continuity, proof_refs=proofs, evidence_refs=evidence
    ):
        raise ValueError("diagnostic evidence refs are stale in the current task")
    return (list(dict.fromkeys(proofs)), list(dict.fromkeys(evidence)))


def command_debug_inspect(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    (receipt, _) = control.resolve_branch_task(repo, state)
    if receipt is None:
        print(json.dumps({"status": "inactive", "diagnostic": None}, ensure_ascii=False))
        return 0
    continuity = control.continuity_from_receipt(control.normalize_receipt(receipt))
    projection = diagnostic_projection(control, repo, continuity)
    print(
        json.dumps(
            {
                "status": "active" if projection else "inactive",
                "task_id": receipt.get("id"),
                "state_revision": receipt.get("state_revision", 0),
                "diagnostic": projection,
                "summary": diagnostic_summary(control, projection),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_debug_begin(control, args: argparse.Namespace) -> int:
    (repo, state, receipt, continuity, diagnostic, loaded_revision) = debug_command_context(
        control, args, require_existing=False
    )
    if diagnostic is not None:
        raise ValueError("Deep Debug is already active for the current task")
    capabilities = (
        receipt.get("capabilities") if isinstance(receipt.get("capabilities"), dict) else {}
    )
    if receipt.get("tier") != "team" or "debug-observability" not in capabilities.get(
        "enabled", []
    ):
        raise ValueError("Deep Debug requires Team Core with debug-observability enabled")
    symptom = control.require_concrete("diagnostic symptom", args.symptom)
    scope = (
        control.normalize_scopes(repo, args.scope)
        if args.scope
        else list(receipt.get("planned_scope", []))
    )
    diagnostic = normalize_diagnostic(
        control,
        {
            "schema_version": control.DIAGNOSTIC_SCHEMA_VERSION,
            "profile": "deep",
            "node_id": args.node,
            "status": "reproducing",
            "symptom": {
                "summary": symptom,
                "scope": scope,
                "environment_refs": (
                    control.require_concrete_list(
                        "diagnostic environment ref", args.environment_ref
                    )
                    if args.environment_ref
                    else []
                ),
            },
            "case_search": {
                "status": "not_run",
                "memory_revision": 0,
                "query_digest": None,
                "candidate_case_ids": [],
                "selected_case_ids": [],
                "warnings": [],
            },
            "reproduction": {
                "gate": "not_ready",
                "proof_refs": [],
                "evidence_refs": [],
                "original_proof_refs": [],
                "minimal_proof_refs": [],
                "runs": 0,
                "failures": 0,
                "agent_runnable": None,
            },
            "hypotheses": [],
            "observations": [],
            "active_hypothesis_id": None,
            "resolution": None,
            "recovery": {
                "status": "unverified",
                "proof_refs": [],
                "evidence_refs": [],
                "probe_cleanup": "pending",
                "remaining_risks": [],
                "confirmation_owner": None,
            },
            "baseline": {
                "head": control.git_head(repo),
                "worktree_status": control.workspace_product_status(control.current_status(repo)),
            },
            "next_probe": control.require_concrete("next diagnostic probe", args.next_probe),
            "started_at": control.now(),
            "updated_at": control.now(),
        },
    )
    continuity["diagnostic"] = diagnostic
    continuity["updated_at"] = diagnostic["updated_at"]
    control.continuity_event(receipt, "deep_debug_started", node_id=args.node)
    next_revision = control.write_active(state, receipt, expected_revision=loaded_revision)
    print(
        json.dumps(
            {
                "status": "debug_started",
                "task_id": receipt["id"],
                "state_revision": next_revision,
                "diagnostic": diagnostic,
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_debug_case_search_bind(control, args: argparse.Namespace) -> int:
    (repo, state, receipt, continuity, diagnostic, loaded_revision) = debug_command_context(
        control, args
    )
    assert diagnostic is not None
    case_ids = [control.project_memory.identifier(value) for value in args.case_id]
    selected_ids = [control.project_memory.identifier(value) for value in args.selected_case_id]
    if any((value not in case_ids for value in selected_ids)):
        raise ValueError("selected incident cases must be present in --case-id candidates")
    memory = control.project_memory.load(control.project_memory.registry_path(repo))
    current_memory_revision = int(memory.get("memory_revision", 0))
    current_memory_digest = control.project_memory.memory_digest(memory)
    if args.status != "unavailable" and (
        args.memory_revision != current_memory_revision
        or args.memory_digest != current_memory_digest
    ):
        raise ValueError(
            "bound incident-case search result is stale against current Project Memory"
        )
    known_case_ids = {
        str(entry.get("id"))
        for entry in memory.get("entries", [])
        if isinstance(entry, dict)
        and entry.get("kind") == "incident_case"
        and (entry.get("status") == "confirmed")
    }
    if args.status == "match" and (
        not case_ids or any((value not in known_case_ids for value in case_ids))
    ):
        raise ValueError("matched incident cases must exist as confirmed Project Memory entries")
    if args.status == "miss" and case_ids:
        raise ValueError("missed incident-case searches cannot bind candidate case IDs")
    if not re.fullmatch("sha256:[a-f0-9]{64}", args.query_digest):
        raise ValueError("case-search query digest must be sha256:<64 lowercase hex>")
    diagnostic["case_search"] = {
        "status": args.status,
        "memory_revision": args.memory_revision,
        "memory_digest": args.memory_digest,
        "query_digest": control.require_concrete("case-search query digest", args.query_digest),
        "candidate_case_ids": list(dict.fromkeys(case_ids)),
        "selected_case_ids": list(dict.fromkeys(selected_ids)),
        "warnings": control.optional_concrete_list("case-search warning", args.warning),
        "searched_at": control.now(),
    }
    diagnostic["updated_at"] = control.now()
    continuity["updated_at"] = diagnostic["updated_at"]
    control.continuity_event(
        receipt, "debug_case_search_bound", status=args.status, case_ids=case_ids
    )
    next_revision = control.write_active(state, receipt, expected_revision=loaded_revision)
    print(
        json.dumps(
            {
                "status": "case_search_bound",
                "state_revision": next_revision,
                "case_search": diagnostic["case_search"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_debug_reproduction_record(control, args: argparse.Namespace) -> int:
    (repo, state, receipt, continuity, diagnostic, loaded_revision) = debug_command_context(
        control, args
    )
    assert diagnostic is not None
    (proofs, evidence) = require_diagnostic_refs(
        control, repo, continuity, args.proof_ref, args.evidence_ref
    )
    original = [
        control.require_continuity_id("original proof ref", value)
        for value in args.original_proof_ref
    ]
    minimal = [
        control.require_continuity_id("minimal proof ref", value)
        for value in args.minimal_proof_ref
    ]
    if any((value not in proofs for value in [*original, *minimal])):
        raise ValueError("original/minimal proof refs must also be supplied as --proof-ref")
    if args.failures < 0 or args.runs < 0 or args.failures > args.runs:
        raise ValueError("reproduction failures must be between zero and runs")
    diagnostic["reproduction"] = {
        "gate": args.gate,
        "proof_refs": proofs,
        "evidence_refs": evidence,
        "original_proof_refs": list(dict.fromkeys(original)),
        "minimal_proof_refs": list(dict.fromkeys(minimal)),
        "runs": args.runs,
        "failures": args.failures,
        "agent_runnable": args.agent_runnable == "yes",
        "recorded_at": control.now(),
    }
    diagnostic["status"] = (
        "investigating" if args.gate in {"ready_red", "ready_flaky"} else "reproducing"
    )
    diagnostic["updated_at"] = control.now()
    continuity["updated_at"] = diagnostic["updated_at"]
    control.continuity_event(receipt, "debug_reproduction_recorded", gate=args.gate)
    next_revision = control.write_active(state, receipt, expected_revision=loaded_revision)
    print(
        json.dumps(
            {
                "status": "reproduction_recorded",
                "state_revision": next_revision,
                "reproduction": diagnostic["reproduction"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_debug_hypothesis_add(control, args: argparse.Namespace) -> int:
    (_, state, receipt, continuity, diagnostic, loaded_revision) = debug_command_context(
        control, args
    )
    assert diagnostic is not None
    if diagnostic.get("resolution") is not None:
        raise ValueError("resolved diagnostics cannot add hypotheses; resume or begin a new task")
    if diagnostic.get("case_search", {}).get("status") == "not_run":
        raise ValueError("search project incident cases before adding a diagnostic hypothesis")
    reproduction = diagnostic.get("reproduction", {})
    if not reproduction.get("proof_refs") and (not reproduction.get("evidence_refs")):
        raise ValueError("record reproduction evidence before adding a diagnostic hypothesis")
    hypothesis_id = control.require_continuity_id("hypothesis id", args.hypothesis_id)
    if any((item.get("id") == hypothesis_id for item in diagnostic.get("hypotheses", []))):
        raise ValueError(f"diagnostic hypothesis already exists: {hypothesis_id}")
    source_case_id = (
        control.project_memory.identifier(args.source_case_id) if args.source_case_id else None
    )
    candidates = diagnostic.get("case_search", {}).get("candidate_case_ids", [])
    if source_case_id and source_case_id not in candidates:
        raise ValueError("source incident case was not returned by the bound case search")
    hypothesis = {
        "id": hypothesis_id,
        "statement": control.require_concrete("hypothesis statement", args.statement),
        "prediction": control.require_concrete("hypothesis prediction", args.prediction),
        "minimal_probe": control.require_concrete("hypothesis probe", args.probe),
        "status": "pending",
        "source_case_id": source_case_id,
        "proof_refs": [],
        "evidence_refs": [],
        "created_at": control.now(),
        "updated_at": control.now(),
    }
    diagnostic["hypotheses"].append(hypothesis)
    diagnostic["active_hypothesis_id"] = hypothesis_id
    diagnostic["status"] = "investigating"
    diagnostic["next_probe"] = hypothesis["minimal_probe"]
    diagnostic["updated_at"] = control.now()
    continuity["updated_at"] = diagnostic["updated_at"]
    control.continuity_event(receipt, "debug_hypothesis_added", hypothesis_id=hypothesis_id)
    next_revision = control.write_active(state, receipt, expected_revision=loaded_revision)
    print(
        json.dumps(
            {
                "status": "hypothesis_added",
                "state_revision": next_revision,
                "hypothesis": hypothesis,
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_debug_observe(control, args: argparse.Namespace) -> int:
    (repo, state, receipt, continuity, diagnostic, loaded_revision) = debug_command_context(
        control, args
    )
    assert diagnostic is not None
    if diagnostic.get("resolution") is not None:
        raise ValueError(
            "resolved diagnostics cannot record new observations; resume the diagnostic first"
        )
    hypothesis_id = control.require_continuity_id("hypothesis id", args.hypothesis_id)
    hypothesis = next(
        (item for item in diagnostic.get("hypotheses", []) if item.get("id") == hypothesis_id), None
    )
    if hypothesis is None:
        raise ValueError(f"diagnostic hypothesis does not exist: {hypothesis_id}")
    observation_id = control.require_continuity_id("observation id", args.observation_id)
    if any((item.get("id") == observation_id for item in diagnostic.get("observations", []))):
        raise ValueError(f"diagnostic observation already exists: {observation_id}")
    (proofs, evidence) = require_diagnostic_refs(
        control, repo, continuity, args.proof_ref, args.evidence_ref
    )
    observation = {
        "id": observation_id,
        "hypothesis_id": hypothesis_id,
        "expected": control.require_concrete("expected observation", args.expected),
        "actual": control.require_concrete("actual observation", args.actual),
        "verdict": args.verdict,
        "proof_refs": proofs,
        "evidence_refs": evidence,
        "at": control.now(),
    }
    diagnostic["observations"].append(observation)
    hypothesis["status"] = args.verdict
    hypothesis["proof_refs"] = control.merge_unique(hypothesis.get("proof_refs", []), proofs)
    hypothesis["evidence_refs"] = control.merge_unique(
        hypothesis.get("evidence_refs", []), evidence
    )
    hypothesis["updated_at"] = control.now()
    diagnostic["active_hypothesis_id"] = hypothesis_id
    diagnostic["updated_at"] = control.now()
    continuity["updated_at"] = diagnostic["updated_at"]
    control.continuity_event(receipt, "debug_observation_recorded", observation=observation)
    next_revision = control.write_active(state, receipt, expected_revision=loaded_revision)
    print(
        json.dumps(
            {
                "status": "observation_recorded",
                "state_revision": next_revision,
                "observation": observation,
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_debug_resolve(control, args: argparse.Namespace) -> int:
    (repo, state, receipt, continuity, diagnostic, loaded_revision) = debug_command_context(
        control, args
    )
    assert diagnostic is not None
    projection = diagnostic_projection(control, repo, continuity)
    assert projection is not None
    if args.outcome == "root_cause_confirmed" and (
        not any(
            (
                item.get("effective_status") == "confirmed"
                for item in projection.get("hypotheses", [])
            )
        )
    ):
        raise ValueError("root_cause_confirmed requires a fresh confirmed hypothesis observation")
    if args.outcome == "no_defect_observed":
        reproduction = projection.get("reproduction", {})
        if reproduction.get("gate") != "ready_green_no_defect" or not reproduction.get("fresh"):
            raise ValueError(
                "no_defect_observed requires a fresh ready_green_no_defect reproduction"
            )
        baseline = diagnostic.get("baseline", {})
        baseline_status = baseline.get("worktree_status")
        if (
            baseline.get("head") != control.git_head(repo)
            or not isinstance(baseline_status, list)
            or control.workspace_product_status(baseline_status)
            != control.workspace_product_status(control.current_status(repo))
        ):
            raise ValueError(
                "no_defect_observed requires no product/worktree changes since Deep Debug began"
            )
    if args.outcome == "blocked" and (not args.owner):
        raise ValueError("blocked diagnostic resolution requires --owner")
    evidence_refs: list[str] = []
    for observation in projection.get("observations", []):
        if observation.get("fresh") and observation.get("verdict") == "confirmed":
            evidence_refs = control.merge_unique(
                evidence_refs,
                observation.get("proof_refs", []),
                observation.get("evidence_refs", []),
            )
    diagnostic["resolution"] = {
        "outcome": args.outcome,
        "summary": control.require_concrete("diagnostic resolution summary", args.summary),
        "evidence_refs": evidence_refs,
        "owner": args.owner,
        "resolved_at": control.now(),
    }
    diagnostic["status"] = "blocked" if args.outcome == "blocked" else "resolved"
    diagnostic["next_probe"] = (
        control.require_concrete("next diagnostic probe", args.next_probe)
        if args.next_probe
        else None
    )
    diagnostic["updated_at"] = control.now()
    continuity["updated_at"] = diagnostic["updated_at"]
    control.continuity_event(receipt, "deep_debug_resolved", resolution=diagnostic["resolution"])
    next_revision = control.write_active(state, receipt, expected_revision=loaded_revision)
    print(
        json.dumps(
            {
                "status": "debug_resolved",
                "state_revision": next_revision,
                "outcome": args.outcome,
                "resolution": diagnostic["resolution"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_debug_recovery(control, args: argparse.Namespace) -> int:
    (repo, state, receipt, continuity, diagnostic, loaded_revision) = debug_command_context(
        control, args
    )
    assert diagnostic is not None
    resolution = diagnostic.get("resolution")
    if not isinstance(resolution, dict):
        raise ValueError("record a diagnostic resolution before recovery")
    proof_refs: list[str] = []
    evidence_refs: list[str] = []
    if args.status != "not_applicable":
        (proof_refs, evidence_refs) = require_diagnostic_refs(
            control, repo, continuity, args.proof_ref, args.evidence_ref
        )
    if args.status == "verified":
        if resolution.get("outcome") != "root_cause_confirmed":
            raise ValueError("verified recovery requires root_cause_confirmed")
        if args.probe_cleanup != "complete":
            raise ValueError("verified recovery requires complete temporary-probe cleanup")
        if not diagnostic_refs_fresh(
            control,
            repo,
            continuity,
            proof_refs=proof_refs,
            evidence_refs=evidence_refs,
            require_passed=True,
        ):
            raise ValueError("verified recovery requires fresh passing proof evidence")
    if args.status == "not_applicable":
        if resolution.get("outcome") != "no_defect_observed":
            raise ValueError("not_applicable recovery is only valid for no_defect_observed")
        if args.probe_cleanup not in {"complete", "not_applicable"}:
            raise ValueError(
                "no-defect recovery requires completed or not-applicable probe cleanup"
            )
    if args.status == "awaiting_confirmation" and (not args.confirmation_owner):
        raise ValueError("awaiting_confirmation requires --confirmation-owner")
    if args.status == "awaiting_confirmation" and (
        not diagnostic_refs_fresh(
            control,
            repo,
            continuity,
            proof_refs=proof_refs,
            evidence_refs=evidence_refs,
            require_passed=True,
        )
    ):
        raise ValueError(
            "awaiting_confirmation requires fresh passing proof or valid external evidence"
        )
    recovery = {
        "status": args.status,
        "proof_refs": proof_refs,
        "evidence_refs": evidence_refs,
        "probe_cleanup": args.probe_cleanup,
        "remaining_risks": control.optional_concrete_list("remaining diagnostic risk", args.risk),
        "confirmation_owner": args.confirmation_owner,
        "recorded_at": control.now(),
    }
    diagnostic["recovery"] = recovery
    diagnostic["status"] = (
        "closed"
        if args.status in {"verified", "not_applicable"}
        else "awaiting_confirmation" if args.status == "awaiting_confirmation" else "recovering"
    )
    diagnostic["updated_at"] = control.now()
    continuity["updated_at"] = diagnostic["updated_at"]
    control.continuity_event(receipt, "debug_recovery_recorded", recovery=recovery)
    next_revision = control.write_active(state, receipt, expected_revision=loaded_revision)
    print(
        json.dumps(
            {
                "status": "recovery_recorded",
                "state_revision": next_revision,
                "recovery_status": args.status,
                "recovery": recovery,
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_memory_case_search(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    result = control.project_memory.search_incident_cases(
        repo,
        symptoms=args.symptom,
        keywords=args.keyword,
        scopes=args.scope,
        components=args.component,
        environment=args.environment,
        observed_version=args.observed_version,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_memory_case_promote(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_active(state)
    loaded_revision = int(receipt.get("state_revision", 0))
    if args.state_revision != loaded_revision:
        raise ValueError(
            f"state revision conflict: expected {loaded_revision}, received {args.state_revision}"
        )
    continuity = control.continuity_from_receipt(receipt)
    projection = diagnostic_projection(control, repo, continuity)
    if projection is None:
        raise ValueError("incident case promotion requires a Deep Debug source task")
    resolution = (
        projection.get("resolution") if isinstance(projection.get("resolution"), dict) else {}
    )
    recovery = projection.get("recovery") if isinstance(projection.get("recovery"), dict) else {}
    if recovery.get("status") == "awaiting_confirmation":
        raise ValueError("awaiting_confirmation diagnostics cannot promote an incident case")
    if receipt.get("status") != "review_ready":
        raise ValueError("incident case promotion requires the source task to be review_ready")
    outcome = resolution.get("outcome")
    if outcome == "root_cause_confirmed":
        if (
            not resolution.get("fresh")
            or recovery.get("status") != "verified"
            or (not recovery.get("fresh"))
        ):
            raise ValueError(
                "incident case promotion requires fresh confirmed cause and verified recovery"
            )
        case_type = "bug"
    elif outcome == "no_defect_observed":
        if recovery.get("status") != "not_applicable" or not resolution.get("fresh"):
            raise ValueError("no-defect case promotion requires a fresh no-defect resolution")
        case_type = "no_defect"
    else:
        raise ValueError("inconclusive or blocked diagnostics cannot promote an incident case")
    root_cause = control.require_concrete("case root cause", args.root_cause)
    resolution_summary = control.require_concrete(
        "diagnostic resolution summary", str(resolution.get("summary") or "")
    )
    if " ".join(root_cause.split()) != " ".join(resolution_summary.split()):
        raise ValueError("incident case root cause must match the diagnostic resolution summary")
    confirmation_source = control.require_concrete(
        "case confirmation source", args.confirmation_source
    )
    diagnostic_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
    )
    evidence_refs = control.merge_unique(
        args.evidence_ref,
        resolution.get("evidence_refs", []),
        recovery.get("proof_refs", []),
        recovery.get("evidence_refs", []),
    )
    (status, memory_revision) = control.project_memory.promote_incident_case(
        repo,
        expected_revision=args.memory_revision,
        entry={
            "id": args.case_id,
            "kind": "incident_case",
            "case_type": case_type,
            "title": args.title,
            "keywords": args.keyword,
            "symptom_signals": args.symptom_signal,
            "scope": args.scope,
            "component_refs": args.component,
            "environment": args.environment,
            "observed_version": args.observed_version,
            "root_cause": root_cause,
            "cause_class": args.cause_class,
            "distinguishing_signals": args.distinguishing_signal,
            "resolution_summary": args.resolution,
            "protective_tests": args.protective_test,
            "lesson": args.lesson,
            "evidence_refs": evidence_refs,
            "source_task_id": receipt.get("id"),
            "source_diagnostic_digest": diagnostic_digest,
            "confirmation_source_digest": "sha256:"
            + hashlib.sha256(confirmation_source.encode("utf-8")).hexdigest(),
            "review_policy": "on_mismatch",
        },
    )
    print(
        json.dumps(
            {
                "status": status,
                "case_id": args.case_id,
                "memory_revision": memory_revision,
                "path": ".auto-dev/project-memory.json",
            },
            ensure_ascii=False,
        )
    )
    return 0
