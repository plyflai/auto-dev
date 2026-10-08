"""Proof attempts and structured E2E, release, and performance evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import pathlib
import shlex
import subprocess
from typing import Any


def task_proof_evidence(
    control, repo: pathlib.Path, receipt: dict[str, Any], evidence_key: str
) -> list[dict[str, Any]]:
    """Return latest, fresh evidence attached to passed task proofs."""
    continuity = control.continuity_from_receipt(receipt)
    proofs = (
        continuity.get("proofs", []) if isinstance(continuity, dict) else receipt.get("proofs", [])
    )
    if not isinstance(proofs, list):
        return []
    nodes = control.continuity_nodes(continuity) if isinstance(continuity, dict) else {}
    plan_revision = int(continuity.get("plan", {}).get("revision", 0)) if continuity else 0
    histories: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for proof in proofs:
        if not isinstance(proof, dict) or not isinstance(proof.get(evidence_key), dict):
            continue
        key = (str(proof.get("node_id") or "run"), str(proof.get("proof_id") or ""))
        if key[1]:
            histories.setdefault(key, []).append(proof)

    def attempt_index(item: dict[str, Any]) -> int:
        try:
            return int(item.get("attempt_index", 1))
        except (TypeError, ValueError):
            return 0

    result: list[dict[str, Any]] = []
    for (node_id, _proof_id), history in histories.items():
        latest = max(history, key=attempt_index)
        if latest.get("status") != "passed":
            continue
        outcome = nodes.get(node_id, {}).get("outcome") if nodes else receipt.get("outcome")
        fresh = (
            proof_is_fresh(
                control, latest, outcome=outcome, repo=repo,
                plan_revision=plan_revision, node=nodes.get(node_id),
            )
            if isinstance(outcome, dict)
            else bool(latest.get("fresh"))
            and evidence_file_is_fresh(control, repo, latest[evidence_key])
        )
        if not fresh:
            continue
        evidence = copy.deepcopy(latest[evidence_key])
        evidence["node_id"] = node_id
        evidence["proof_id"] = latest.get("proof_id")
        evidence["attempt_id"] = latest.get("attempt_id")
        result.append(evidence)
    result.sort(key=lambda item: (str(item.get("node_id") or ""), str(item.get("proof_id") or "")))
    return result


def task_e2e_evidence(control, repo: pathlib.Path, receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only the latest, fresh, passed E2E evidence for product review."""
    return task_proof_evidence(control, repo, receipt, "e2e_evidence")


def task_release_evidence(
    control, repo: pathlib.Path, receipt: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return only the latest, fresh, successful release evidence for product review."""
    return task_proof_evidence(control, repo, receipt, "release_evidence")


def require_proof_id(control, value: str) -> str:
    identifier = control.require_concrete("proof id", value)
    if not control.re.fullmatch("[a-z][a-z0-9_-]{0,79}", identifier):
        raise ValueError("proof id must use lowercase letters, digits, hyphens, or underscores")
    return identifier


def proof_attempt_id(control, node_id: str, proof_id: str, attempt_index: int) -> str:
    raw = f"{node_id}:{proof_id}:{attempt_index}"
    return "attempt-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def proof_history(
    control, proofs: control.Iterable[dict[str, Any]], *, node_id: str, proof_id: str
) -> list[dict[str, Any]]:
    history = [
        proof
        for proof in proofs
        if isinstance(proof, dict)
        and str(proof.get("node_id")) == node_id
        and (str(proof.get("proof_id")) == proof_id)
    ]
    history.sort(key=lambda proof: int(proof.get("attempt_index", 1)))
    return history


def latest_proof(
    control, proofs: control.Iterable[dict[str, Any]], *, node_id: str, proof_id: str
) -> dict[str, Any] | None:
    history = proof_history(control, proofs, node_id=node_id, proof_id=proof_id)
    return history[-1] if history else None


def proof_is_fresh(
    control,
    proof: dict[str, Any],
    *,
    outcome: dict[str, Any],
    repo: pathlib.Path,
    plan_revision: int,
    node: dict[str, Any] | None = None,
) -> bool:
    evaluation = control.current_evaluation(repo)
    outcome_sha256 = control.outcome_digest(outcome)
    proof_identity = proof.get("attempt_id") or hashlib.sha256(
        json.dumps(proof, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cache_key = (
        "proof_freshness",
        proof_identity,
        proof.get("node_id"),
        proof.get("proof_id"),
        proof.get("attempt_index"),
        outcome_sha256,
        plan_revision,
        node.get("contract_sha256") if isinstance(node, dict) else None,
    )
    if evaluation is not None and cache_key in evaluation.proof_freshness_cache:
        return evaluation.proof_freshness_cache[cache_key]

    def finish(value: bool) -> bool:
        if evaluation is not None:
            evaluation.proof_freshness_cache[cache_key] = value
        return value

    performance_evidence = proof.get("performance_evidence")
    recorded_performance_baseline = (
        proof.get("status") == "recorded"
        and isinstance(performance_evidence, dict)
        and (performance_evidence.get("phase") == "baseline")
    )
    if proof.get("status") != "passed" and (not recorded_performance_baseline):
        return finish(False)
    e2e_evidence = proof.get("e2e_evidence")
    if isinstance(e2e_evidence, dict) and (not evidence_file_is_fresh(control, repo, e2e_evidence)):
        return finish(False)
    release_evidence = proof.get("release_evidence")
    if isinstance(release_evidence, dict) and (
        not evidence_file_is_fresh(control, repo, release_evidence)
    ):
        return finish(False)
    if isinstance(performance_evidence, dict) and (
        not performance_evidence_is_fresh(control, repo, performance_evidence)
    ):
        return finish(False)
    if proof.get("outcome_sha256") != outcome_sha256:
        return finish(False)
    rolling_node = isinstance(node, dict) and node.get("node_role") in {
        "work_packet", "integration",
    }
    if rolling_node:
        execution_base = node.get("execution_base") if isinstance(node.get("execution_base"), dict) else {}
        execution_base_sha256 = hashlib.sha256(
            json.dumps(
                execution_base, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        if proof.get("node_contract_sha256") != node.get("contract_sha256"):
            return finish(False)
        if proof.get("compilation_revision") != execution_base.get("compilation_revision"):
            return finish(False)
        if proof.get("execution_base_sha256") != execution_base_sha256:
            return finish(False)
    elif proof.get("plan_revision") != plan_revision:
        return finish(False)
    observed_paths = (
        proof.get("observed_paths") if isinstance(proof.get("observed_paths"), list) else []
    )
    if observed_paths:
        return finish(
            proof.get("observed_paths_sha256")
            == control.workspace_scope_digest(repo, observed_paths)
        )
    scopes = proof.get("scope") if isinstance(proof.get("scope"), list) else []
    if not scopes and proof.get("head") != control.git_head(repo):
        return finish(False)
    recorded_status = proof.get("worktree_status")
    if (
        not scopes
        and isinstance(recorded_status, list)
        and (
            control.workspace_product_status(recorded_status)
            != control.workspace_product_status(control.current_status(repo))
        )
    ):
        return finish(False)
    if scopes and proof.get("scope_sha256") != control.workspace_scope_digest(repo, scopes):
        return finish(False)
    return finish(True)


def proof_attempts_by_id(control, continuity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(proof.get("attempt_id")): proof
        for proof in continuity.get("proofs", [])
        if isinstance(proof, dict) and proof.get("attempt_id")
    }


def evidence_links_by_id(control, continuity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(link.get("id")): link
        for link in continuity.get("evidence_links", [])
        if isinstance(link, dict) and link.get("id")
    }


def proof_context_is_fresh(
    control, proof: dict[str, Any], *, continuity: dict[str, Any], repo: pathlib.Path
) -> bool:
    node = control.continuity_nodes(continuity).get(str(proof.get("node_id")))
    outcome = (
        node.get("outcome")
        if isinstance(node, dict) and isinstance(node.get("outcome"), dict)
        else None
    )
    if outcome is None:
        return False
    if proof.get("outcome_sha256") != control.outcome_digest(outcome):
        return False
    rolling_node = isinstance(node, dict) and node.get("node_role") in {
        "work_packet", "integration",
    }
    if rolling_node:
        execution_base = node.get("execution_base") if isinstance(node.get("execution_base"), dict) else {}
        execution_base_sha256 = hashlib.sha256(
            json.dumps(
                execution_base, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        if proof.get("node_contract_sha256") != node.get("contract_sha256"):
            return False
        if proof.get("compilation_revision") != execution_base.get("compilation_revision"):
            return False
        if proof.get("execution_base_sha256") != execution_base_sha256:
            return False
    else:
        if proof.get("plan_revision") != int(continuity.get("plan", {}).get("revision", 0)):
            return False
    observed_paths = (
        proof.get("observed_paths") if isinstance(proof.get("observed_paths"), list) else []
    )
    if observed_paths:
        return proof.get("observed_paths_sha256") == control.workspace_scope_digest(
            repo, observed_paths
        )
    scopes = proof.get("scope") if isinstance(proof.get("scope"), list) else []
    if not scopes:
        recorded_status = proof.get("worktree_status")
        return (
            proof.get("head") == control.git_head(repo)
            and isinstance(recorded_status, list)
            and (
                control.workspace_product_status(recorded_status)
                == control.workspace_product_status(control.current_status(repo))
            )
        )
    return proof.get("scope_sha256") == control.workspace_scope_digest(repo, scopes)


def read_json_evidence_manifest(
    control, repo: pathlib.Path, raw_path: str, *, label: str
) -> tuple[pathlib.Path, dict[str, Any], str]:
    """Read and hash one bounded JSON evidence object."""
    repo = repo.resolve()
    candidate = pathlib.Path(raw_path).expanduser()
    path = (repo / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not path.is_file():
        raise ValueError(f"{label} file does not exist: {raw_path}")
    try:
        content = path.read_bytes()
        if len(content) > control.MAX_EVIDENCE_FILE_BYTES:
            raise ValueError(f"{label} file exceeds {control.MAX_EVIDENCE_FILE_BYTES} bytes")
        payload = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} file is not valid JSON: {raw_path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return (path, payload, hashlib.sha256(content).hexdigest())


def evidence_path(control, repo: pathlib.Path, path: pathlib.Path) -> str:
    return (
        str(path.relative_to(repo.resolve())) if path.is_relative_to(repo.resolve()) else str(path)
    )


def evidence_text(control, label: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    result = control.require_concrete(label, value)
    if control.SENSITIVE_TEXT.search(result):
        raise ValueError(f"{label} appears to contain a credential or secret")
    return result


def read_evidence_artifact(
    control,
    repo: pathlib.Path,
    raw_path: str,
    *,
    expected_schemas: set[str],
    coverage_ids: set[str],
) -> dict[str, Any]:
    """Read a small evidence manifest without allowing the proof to write it."""
    (path, payload, digest) = read_json_evidence_manifest(
        control, repo, raw_path, label="evidence artifact"
    )
    schema = str(payload.get("schema") or payload.get("artifact_schema") or "").strip()
    if not schema or schema not in expected_schemas:
        raise ValueError(
            "evidence artifact schema mismatch: expected " + ", ".join(sorted(expected_schemas))
        )
    artifact_coverage = payload.get("coverage_ids")
    if isinstance(artifact_coverage, str):
        artifact_coverage = [artifact_coverage]
    if not isinstance(artifact_coverage, list) or not coverage_ids.issubset(
        {str(value) for value in artifact_coverage}
    ):
        raise ValueError("evidence artifact does not cover every declared coverage id")
    if not str(payload.get("source_ref") or "").strip():
        raise ValueError("evidence artifact requires a source_ref")
    if not isinstance(payload.get("entries"), list) or not payload["entries"]:
        raise ValueError("evidence artifact requires a non-empty entries array")
    return {
        "path": evidence_path(control, repo, path),
        "schema": schema,
        "coverage_ids": sorted(coverage_ids),
        "source_ref": str(payload["source_ref"]),
        "sha256": digest,
    }


def normalize_e2e_evidence(
    control, repo: pathlib.Path, path: pathlib.Path, payload: dict[str, Any], digest: str
) -> dict[str, Any]:
    allowed = {
        "schema",
        "source_ref",
        "result",
        "user_flow",
        "environment",
        "checks",
        "unverified",
        "next_step",
        "gui",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"E2E evidence has unsupported fields: {', '.join(unknown)}")
    schema = str(payload.get("schema") or "").strip()
    if schema != control.E2E_EVIDENCE_SCHEMA:
        raise ValueError(f"E2E evidence schema must be {control.E2E_EVIDENCE_SCHEMA}")
    result = evidence_text(control, "E2E evidence result", payload.get("result"))
    if result not in control.E2E_RESULT_STATUSES:
        raise ValueError(
            "E2E evidence result must be one of: " + ", ".join(sorted(control.E2E_RESULT_STATUSES))
        )
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("E2E evidence checks must be an object")
    expected_checks = {"page", "data_interaction", "system_result"}
    if set(checks) != expected_checks:
        missing = sorted(expected_checks - set(checks))
        extra = sorted(set(checks) - expected_checks)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("unsupported=" + ",".join(extra))
        raise ValueError(
            "E2E evidence checks must contain page, data_interaction, system_result ("
            + "; ".join(details)
            + ")"
        )
    normalized_checks = {
        key: evidence_text(control, f"E2E evidence {key}", checks[key])
        for key in sorted(expected_checks)
    }
    raw_unverified = payload.get("unverified", [])
    if not isinstance(raw_unverified, list) or not all(
        (isinstance(item, str) for item in raw_unverified)
    ):
        raise ValueError("E2E evidence unverified must be a list of strings")
    unverified: list[str] = []
    for item in raw_unverified:
        value = evidence_text(control, "E2E evidence unverified item", item)
        if value not in unverified:
            unverified.append(value)
    result_payload = {
        "path": evidence_path(control, repo, path),
        "schema": schema,
        "source_ref": evidence_text(control, "E2E evidence source ref", payload.get("source_ref")),
        "result": result,
        "user_flow": evidence_text(control, "E2E evidence user flow", payload.get("user_flow")),
        "environment": evidence_text(
            control, "E2E evidence environment", payload.get("environment")
        ),
        "checks": normalized_checks,
        "unverified": unverified,
        "next_step": evidence_text(control, "E2E evidence next step", payload.get("next_step")),
        "sha256": digest,
    }
    if "gui" in payload:
        result_payload["gui"] = normalize_gui_evidence(
            control, payload.get("gui"), result=result
        )
    return result_payload


def evidence_text_list(control, label: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    result: list[str] = []
    for item in value:
        text = evidence_text(control, label, item)
        if text not in result:
            result.append(text)
    if not result:
        raise ValueError(f"{label} must not be empty")
    return result


def normalize_gui_evidence(
    control, value: Any, *, result: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("E2E evidence gui must be an object")
    allowed = {"executor", "visual_mode", "cases", "evidence", "manual_fallback"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"E2E evidence gui has unsupported fields: {', '.join(unknown)}")
    executor = evidence_text(control, "GUI executor", value.get("executor"))
    visual_mode = evidence_text(control, "GUI visual mode", value.get("visual_mode"))
    if visual_mode not in {"required", "unavailable"}:
        raise ValueError("GUI visual mode must be required or unavailable")
    raw_cases = value.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("E2E evidence gui cases must be a non-empty list")
    cases: list[dict[str, str]] = []
    case_ids: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise ValueError("E2E evidence gui case must be an object")
        if set(raw_case) - {"id", "type", "status", "scope"}:
            raise ValueError("E2E evidence gui case has unsupported fields")
        case_id = evidence_text(control, "GUI case id", raw_case.get("id"))
        case_type = evidence_text(control, "GUI case type", raw_case.get("type"))
        case_status = evidence_text(control, "GUI case status", raw_case.get("status"))
        if case_type not in {"happy", "negative", "boundary", "recovery"}:
            raise ValueError("GUI case type is unsupported")
        if case_status not in {"passed", "failed", "blocked", "manual_only"}:
            raise ValueError("GUI case status is unsupported")
        if case_id in case_ids:
            raise ValueError(f"GUI case id is duplicated: {case_id}")
        case_ids.add(case_id)
        normalized_case = {"id": case_id, "type": case_type, "status": case_status}
        if "scope" in raw_case:
            normalized_case["scope"] = evidence_text(control, "GUI case scope", raw_case["scope"])
        cases.append(normalized_case)
    raw_evidence = value.get("evidence")
    if not isinstance(raw_evidence, dict):
        raise ValueError("E2E evidence gui evidence must be an object")
    evidence_keys = {
        "action_timeline",
        "screenshots",
        "browser_console",
        "network_trace",
        "page_state",
        "backend_trace",
    }
    if set(raw_evidence) != evidence_keys:
        missing = sorted(evidence_keys - set(raw_evidence))
        extra = sorted(set(raw_evidence) - evidence_keys)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("unsupported=" + ",".join(extra))
        raise ValueError("E2E evidence gui evidence fields must be complete (" + "; ".join(details) + ")")
    evidence_bundle: dict[str, list[str]] = {}
    for key in sorted(evidence_keys):
        raw_items = raw_evidence[key]
        if not isinstance(raw_items, list) or not all(isinstance(item, str) for item in raw_items):
            raise ValueError(f"E2E evidence gui {key} must be a list of strings")
        evidence_bundle[key] = [
            evidence_text(control, f"GUI {key} item", item) for item in raw_items
        ]
    for required_key in ("action_timeline", "screenshots", "page_state"):
        if not evidence_bundle[required_key]:
            raise ValueError(f"E2E evidence gui {required_key} must not be empty")
    raw_fallback = value.get("manual_fallback")
    fallback = None
    if visual_mode == "unavailable" or executor == "manual_only":
        if not isinstance(raw_fallback, dict):
            raise ValueError("GUI unavailable/manual-only evidence requires manual_fallback")
        if set(raw_fallback) != {"reason", "steps", "expected", "evidence_request"}:
            raise ValueError("GUI manual_fallback fields must be reason, steps, expected, evidence_request")
        fallback = {
            "reason": evidence_text(control, "GUI fallback reason", raw_fallback["reason"]),
            "steps": evidence_text_list(control, "GUI fallback step", raw_fallback["steps"]),
            "expected": evidence_text_list(control, "GUI fallback expectation", raw_fallback["expected"]),
            "evidence_request": evidence_text_list(
                control, "GUI fallback evidence request", raw_fallback["evidence_request"]
            ),
        }
    elif raw_fallback is not None:
        raise ValueError("GUI manual_fallback is only valid for unavailable/manual-only execution")
    if result == "passed" and (
        visual_mode != "required"
        or executor == "manual_only"
        or any(case["status"] != "passed" for case in cases)
    ):
        raise ValueError("passed E2E evidence requires a headed GUI executor and passed GUI cases")
    normalized = {
        "executor": executor,
        "visual_mode": visual_mode,
        "cases": cases,
        "evidence": evidence_bundle,
    }
    if fallback is not None:
        normalized["manual_fallback"] = fallback
    return normalized


def read_e2e_evidence(control, repo: pathlib.Path, raw_path: str) -> dict[str, Any]:
    """Read the small product-facing summary emitted by an E2E run."""
    (path, payload, digest) = read_json_evidence_manifest(
        control, repo, raw_path, label="E2E evidence"
    )
    return normalize_e2e_evidence(control, repo, path, payload, digest)


def exact_evidence_fields(control, label: str, value: Any, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("unsupported=" + ",".join(extra))
        raise ValueError(
            f"{label} fields must contain {', '.join(sorted(expected))} ({'; '.join(details)})"
        )
    return value


def normalize_release_evidence(
    control, repo: pathlib.Path, path: pathlib.Path, payload: dict[str, Any], digest: str
) -> dict[str, Any]:
    expected = {
        "schema",
        "source_ref",
        "result",
        "environment",
        "version",
        "health",
        "user_flow",
        "rollback",
        "unverified",
        "next_step",
    }
    exact_evidence_fields(control, "Release evidence", payload, expected)
    schema = str(payload.get("schema") or "").strip()
    if schema != control.RELEASE_EVIDENCE_SCHEMA:
        raise ValueError(f"Release evidence schema must be {control.RELEASE_EVIDENCE_SCHEMA}")
    result = evidence_text(control, "Release evidence result", payload.get("result"))
    if result not in control.RELEASE_RESULT_STATUSES:
        raise ValueError(
            "Release evidence result must be one of: "
            + ", ".join(sorted(control.RELEASE_RESULT_STATUSES))
        )
    health_raw = exact_evidence_fields(
        control, "Release evidence health", payload.get("health"), {"status", "summary"}
    )
    health_status = evidence_text(
        control, "Release evidence health status", health_raw.get("status")
    )
    if health_status not in control.RELEASE_CHECK_STATUSES:
        raise ValueError(
            "Release evidence health status must be one of: "
            + ", ".join(sorted(control.RELEASE_CHECK_STATUSES))
        )
    user_flow_raw = exact_evidence_fields(
        control, "Release evidence user flow", payload.get("user_flow"), {"status", "summary"}
    )
    user_flow_status = evidence_text(
        control, "Release evidence user flow status", user_flow_raw.get("status")
    )
    if user_flow_status not in control.RELEASE_USER_FLOW_STATUSES:
        raise ValueError(
            "Release evidence user flow status must be one of: "
            + ", ".join(sorted(control.RELEASE_USER_FLOW_STATUSES))
        )
    rollback_raw = exact_evidence_fields(
        control,
        "Release evidence rollback",
        payload.get("rollback"),
        {"status", "trigger", "target"},
    )
    rollback_status = evidence_text(
        control, "Release evidence rollback status", rollback_raw.get("status")
    )
    if rollback_status not in control.RELEASE_ROLLBACK_STATUSES:
        raise ValueError(
            "Release evidence rollback status must be one of: "
            + ", ".join(sorted(control.RELEASE_ROLLBACK_STATUSES))
        )
    if result == "rolled_back" and rollback_status != "executed":
        raise ValueError("rolled_back release evidence requires rollback status executed")
    if result == "succeeded" and (
        health_status != "passed"
        or user_flow_status not in {"passed", "not_applicable"}
        or rollback_status not in {"ready", "not_applicable"}
    ):
        raise ValueError(
            "succeeded release evidence requires passed health, passed or not_applicable user flow, and ready or not_applicable rollback"
        )
    raw_unverified = payload.get("unverified")
    if not isinstance(raw_unverified, list) or not all(
        (isinstance(item, str) for item in raw_unverified)
    ):
        raise ValueError("Release evidence unverified must be a list of strings")
    unverified: list[str] = []
    for item in raw_unverified:
        value = evidence_text(control, "Release evidence unverified item", item)
        if value not in unverified:
            unverified.append(value)
    return {
        "path": evidence_path(control, repo, path),
        "schema": schema,
        "source_ref": evidence_text(
            control, "Release evidence source ref", payload.get("source_ref")
        ),
        "result": result,
        "environment": evidence_text(
            control, "Release evidence environment", payload.get("environment")
        ),
        "version": evidence_text(control, "Release evidence version", payload.get("version")),
        "health": {
            "status": health_status,
            "summary": evidence_text(
                control, "Release evidence health summary", health_raw.get("summary")
            ),
        },
        "user_flow": {
            "status": user_flow_status,
            "summary": evidence_text(
                control, "Release evidence user flow summary", user_flow_raw.get("summary")
            ),
        },
        "rollback": {
            "status": rollback_status,
            "trigger": evidence_text(
                control, "Release evidence rollback trigger", rollback_raw.get("trigger")
            ),
            "target": evidence_text(
                control, "Release evidence rollback target", rollback_raw.get("target")
            ),
        },
        "unverified": unverified,
        "next_step": evidence_text(control, "Release evidence next step", payload.get("next_step")),
        "sha256": digest,
    }


def read_release_evidence(control, repo: pathlib.Path, raw_path: str) -> dict[str, Any]:
    """Read the small product-facing summary emitted by a release pipeline."""
    (path, payload, digest) = read_json_evidence_manifest(
        control, repo, raw_path, label="Release evidence"
    )
    return normalize_release_evidence(control, repo, path, payload, digest)


def evidence_number(control, label: str, value: Any, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    if positive and result <= 0:
        raise ValueError(f"{label} must be greater than zero")
    if not positive and result < 0:
        raise ValueError(f"{label} must be zero or greater")
    return result


def normalize_performance_evidence(
    control, repo: pathlib.Path, path: pathlib.Path, payload: dict[str, Any], digest: str
) -> dict[str, Any]:
    common_fields = {
        "schema",
        "phase",
        "source_ref",
        "hypothesis",
        "metric",
        "unit",
        "direction",
        "target_value",
        "workload",
        "environment",
        "samples",
        "noise_tolerance_pct",
    }
    phase = evidence_text(control, "Performance evidence phase", payload.get("phase"))
    if phase not in control.PERFORMANCE_PHASES:
        raise ValueError(
            "Performance evidence phase must be one of: "
            + ", ".join(sorted(control.PERFORMANCE_PHASES))
        )
    expected = common_fields | ({"baseline_attempt_id"} if phase == "comparison" else set())
    exact_evidence_fields(control, "Performance evidence", payload, expected)
    schema = str(payload.get("schema") or "").strip()
    if schema != control.PERFORMANCE_EVIDENCE_SCHEMA:
        raise ValueError(
            f"Performance evidence schema must be {control.PERFORMANCE_EVIDENCE_SCHEMA}"
        )
    direction = evidence_text(control, "Performance evidence direction", payload.get("direction"))
    if direction not in control.PERFORMANCE_DIRECTIONS:
        raise ValueError(
            "Performance evidence direction must be one of: "
            + ", ".join(sorted(control.PERFORMANCE_DIRECTIONS))
        )
    raw_samples = payload.get("samples")
    if not isinstance(raw_samples, list) or len(raw_samples) < 2:
        raise ValueError("Performance evidence requires at least two samples")
    if len(raw_samples) > 1000:
        raise ValueError("Performance evidence supports at most 1000 samples")
    samples = [
        evidence_number(control, "Performance evidence sample", sample) for sample in raw_samples
    ]
    noise_tolerance_pct = evidence_number(
        control,
        "Performance evidence noise tolerance",
        payload.get("noise_tolerance_pct"),
        positive=False,
    )
    if noise_tolerance_pct >= 100:
        raise ValueError("Performance evidence noise tolerance must be below 100 percent")
    result = {
        "path": evidence_path(control, repo, path),
        "schema": schema,
        "phase": phase,
        "source_ref": evidence_text(
            control, "Performance evidence source ref", payload.get("source_ref")
        ),
        "hypothesis": evidence_text(
            control, "Performance evidence hypothesis", payload.get("hypothesis")
        ),
        "metric": evidence_text(control, "Performance evidence metric", payload.get("metric")),
        "unit": evidence_text(control, "Performance evidence unit", payload.get("unit")),
        "direction": direction,
        "target_value": evidence_number(
            control, "Performance evidence target value", payload.get("target_value")
        ),
        "workload": evidence_text(
            control, "Performance evidence workload", payload.get("workload")
        ),
        "environment": evidence_text(
            control, "Performance evidence environment", payload.get("environment")
        ),
        "samples": samples,
        "sample_count": len(samples),
        "observed_value": sum(samples) / len(samples),
        "noise_tolerance_pct": noise_tolerance_pct,
        "result": "recorded" if phase == "baseline" else "pending",
        "sha256": digest,
    }
    if phase == "comparison":
        result["baseline_attempt_id"] = evidence_text(
            control, "Performance evidence baseline attempt id", payload.get("baseline_attempt_id")
        )
    return result


def read_performance_evidence(control, repo: pathlib.Path, raw_path: str) -> dict[str, Any]:
    """Read a bounded baseline or comparison emitted by a project benchmark."""
    (path, payload, digest) = read_json_evidence_manifest(
        control, repo, raw_path, label="Performance evidence"
    )
    return normalize_performance_evidence(control, repo, path, payload, digest)


def bind_performance_baseline(
    control,
    repo: pathlib.Path,
    evidence: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    outcome: dict[str, Any],
    plan_revision: int,
    node: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline_attempt_id = evidence.get("baseline_attempt_id")
    baseline_proof = next(
        (
            proof
            for proof in history
            if proof.get("attempt_id") == baseline_attempt_id
            and proof.get("status") == "recorded"
            and isinstance(proof.get("performance_evidence"), dict)
            and (proof["performance_evidence"].get("phase") == "baseline")
        ),
        None,
    )
    if baseline_proof is None:
        raise ValueError(
            "performance comparison requires a recorded baseline attempt from this proof"
        )
    baseline = baseline_proof["performance_evidence"]
    if baseline_proof.get("outcome_sha256") != control.outcome_digest(outcome):
        raise ValueError("performance baseline outcome no longer matches the current outcome")
    if isinstance(node, dict) and node.get("node_role") in {"work_packet", "integration"}:
        execution_base = node.get("execution_base") if isinstance(node.get("execution_base"), dict) else {}
        execution_base_sha256 = hashlib.sha256(
            json.dumps(
                execution_base, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        if (
            baseline_proof.get("node_contract_sha256") != node.get("contract_sha256")
            or baseline_proof.get("compilation_revision") != execution_base.get("compilation_revision")
            or baseline_proof.get("execution_base_sha256") != execution_base_sha256
        ):
            raise ValueError("performance baseline node contract no longer matches")
    elif baseline_proof.get("plan_revision") != plan_revision:
        raise ValueError("performance baseline plan revision no longer matches")
    if not evidence_file_is_fresh(control, repo, baseline):
        raise ValueError("performance baseline evidence file is stale")
    matching_fields = (
        "hypothesis",
        "metric",
        "unit",
        "direction",
        "target_value",
        "workload",
        "environment",
        "noise_tolerance_pct",
    )
    mismatched = [field for field in matching_fields if evidence.get(field) != baseline.get(field)]
    if mismatched:
        raise ValueError(
            "performance comparison fields must match baseline: " + ", ".join(mismatched)
        )
    baseline_value = float(baseline["observed_value"])
    observed_value = float(evidence["observed_value"])
    direction = str(evidence["direction"])
    if direction == "lower":
        improvement_pct = (baseline_value - observed_value) / baseline_value * 100
        target_met = observed_value <= float(evidence["target_value"])
    else:
        improvement_pct = (observed_value - baseline_value) / baseline_value * 100
        target_met = observed_value >= float(evidence["target_value"])
    change_exceeds_noise = improvement_pct > float(evidence["noise_tolerance_pct"])
    result = copy.deepcopy(evidence)
    result.update(
        {
            "baseline": {
                "attempt_id": baseline_attempt_id,
                "path": baseline["path"],
                "sha256": baseline["sha256"],
                "source_ref": baseline["source_ref"],
                "observed_value": baseline_value,
                "sample_count": baseline["sample_count"],
            },
            "improvement_pct": improvement_pct,
            "target_met": target_met,
            "change_exceeds_noise": change_exceeds_noise,
            "result": "passed" if target_met and change_exceeds_noise else "failed",
        }
    )
    return result


def read_proof_evidence(control, repo: pathlib.Path, raw_path: str) -> tuple[str, dict[str, Any]]:
    (path, payload, digest) = read_json_evidence_manifest(
        control, repo, raw_path, label="proof evidence"
    )
    schema = str(payload.get("schema") or "").strip()
    if schema == control.E2E_EVIDENCE_SCHEMA:
        return ("e2e_evidence", normalize_e2e_evidence(control, repo, path, payload, digest))
    if schema == control.RELEASE_EVIDENCE_SCHEMA:
        return (
            "release_evidence",
            normalize_release_evidence(control, repo, path, payload, digest),
        )
    if schema == control.PERFORMANCE_EVIDENCE_SCHEMA:
        return (
            "performance_evidence",
            normalize_performance_evidence(control, repo, path, payload, digest),
        )
    raise ValueError(
        "proof evidence schema must be one of: "
        + ", ".join(
            sorted(
                {
                    control.E2E_EVIDENCE_SCHEMA,
                    control.RELEASE_EVIDENCE_SCHEMA,
                    control.PERFORMANCE_EVIDENCE_SCHEMA,
                }
            )
        )
    )


def read_product_evidence(control, repo: pathlib.Path, raw_path: str) -> tuple[str, dict[str, Any]]:
    (key, evidence) = read_proof_evidence(control, repo, raw_path)
    if key in {"e2e_evidence", "release_evidence"}:
        return (key, evidence)
    raise ValueError(
        "product evidence schema must be one of: "
        + ", ".join(sorted({control.E2E_EVIDENCE_SCHEMA, control.RELEASE_EVIDENCE_SCHEMA}))
    )


def evidence_file_is_fresh(control, repo: pathlib.Path, evidence: dict[str, Any]) -> bool:
    raw_path = evidence.get("path")
    expected_digest = evidence.get("sha256")
    if not isinstance(raw_path, str) or not raw_path or (not isinstance(expected_digest, str)):
        return False
    path = pathlib.Path(raw_path)
    if not path.is_absolute():
        path = repo / path
    try:
        if not path.is_file():
            return False
        evaluation = control.current_evaluation(repo)
        actual = evaluation.file_digest(path) if evaluation is not None else hashlib.sha256(path.read_bytes()).hexdigest()
        return actual == expected_digest
    except OSError:
        return False


def e2e_evidence_is_fresh(control, repo: pathlib.Path, evidence: dict[str, Any]) -> bool:
    return evidence_file_is_fresh(control, repo, evidence)


def performance_evidence_is_fresh(control, repo: pathlib.Path, evidence: dict[str, Any]) -> bool:
    if not evidence_file_is_fresh(control, repo, evidence):
        return False
    if evidence.get("phase") != "comparison":
        return True
    baseline = evidence.get("baseline")
    return isinstance(baseline, dict) and evidence_file_is_fresh(control, repo, baseline)


def command_proof(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_working_task(state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    continuity = control.continuity_from_receipt(receipt)
    has_plan = continuity is not None and bool(continuity["plan"].get("nodes"))
    if not has_plan and args.node != "run":
        raise ValueError("proof without a continuity plan must target --node run")
    plan_revision = int(continuity["plan"].get("revision", 0)) if has_plan else 0
    if args.plan_revision != plan_revision:
        raise ValueError(
            f"proof plan revision conflict: expected {plan_revision}, received {args.plan_revision}"
        )
    if args.state_revision != loaded_state_revision:
        raise ValueError(
            f"proof state revision conflict: expected {loaded_state_revision}, received {args.state_revision}"
        )
    node_id = control.require_continuity_id("node id", args.node)
    node: dict[str, Any] | None = None
    if has_plan:
        nodes = {node["id"]: node for node in continuity["plan"]["nodes"]}
        if node_id not in nodes:
            raise ValueError(f"proof node does not exist: {node_id}")
        node = nodes[node_id]
        node_status = node.get("status")
        if args.revalidate:
            if node_status != "done":
                raise ValueError(f"proof revalidation requires a completed node: {node_id}")
            project = control.load_project(state, repo)
            if (
                not isinstance(project, dict)
                or control.project_upgrade_version(project)
                != control.CONTROL_PLANE_UPGRADE_VERSION
            ):
                raise ValueError(
                    "proof revalidation is not currently required by upgrade inspection"
                )
            # Revalidation only mutates the selected task. Full historical
            # inspection stays explicit; use the same active proof freshness
            # check enforced by status and write gates.
            active_issues = control.continuity_reconciliation_issues(repo, continuity)
            authorized = any(
                (
                    target.get("node_id") == node_id
                    and (target.get("proof_id") == args.proof_id)
                    for target in active_issues
                )
            )
            if not authorized:
                raise ValueError(
                    f"proof revalidation target is not listed by legacy-upgrade inspect: {node_id}/{args.proof_id}"
                )
        elif node_status != "active":
            raise ValueError(f"proof node must be active: {node_id}")
        outcome = node.get("outcome")
    else:
        if args.revalidate:
            raise ValueError("proof revalidation requires a completed continuity plan node")
        outcome = receipt.get("outcome")
    if not outcome:
        raise ValueError(f"proof node lacks an outcome contract: {node_id}")
    proof_id = require_proof_id(control, args.proof_id)
    expected = {proof["id"]: proof for proof in outcome.get("proofs", [])}
    if proof_id not in expected:
        raise ValueError(f"proof is not declared by node {node_id}: {proof_id}")
    proofs = continuity.setdefault("proofs", []) if has_plan else receipt.setdefault("proofs", [])
    history = proof_history(control, proofs, node_id=node_id, proof_id=proof_id)
    command = control.require_concrete("proof command", args.command)
    command_parts = shlex.split(command)
    if not command_parts:
        raise ValueError("proof command must not be empty")
    declared_recipe = expected[proof_id].get("recipe")
    if isinstance(node, dict) and node.get("node_role") in {"work_packet", "integration"}:
        if not isinstance(declared_recipe, dict) or command_parts != declared_recipe.get("argv"):
            raise ValueError(
                f"rolling proof command must match the declared recipe for {node_id}/{proof_id}"
            )
        recipe_evidence = declared_recipe.get("evidence_file")
        if recipe_evidence is not None and args.evidence_file != recipe_evidence:
            raise ValueError(
                f"rolling proof evidence must match the declared recipe for {node_id}/{proof_id}"
            )
    contract = (
        receipt.get("contract_snapshot")
        if isinstance(receipt.get("contract_snapshot"), dict)
        else {}
    )
    contract_coverage = {
        str(item.get("id")): item
        for item in contract.get("required_coverage", [])
        if isinstance(item, dict) and item.get("id")
    }
    proof_coverage = {str(value) for value in expected[proof_id].get("coverage_ids", []) if value}
    artifact_requirements = {
        coverage_id: str(contract_coverage[coverage_id].get("artifact_schema"))
        for coverage_id in proof_coverage
        if coverage_id in contract_coverage
        and contract_coverage[coverage_id].get("artifact_schema")
    }
    evidence = None
    e2e_evidence = None
    release_evidence = None
    performance_evidence = None
    if artifact_requirements:
        if not args.evidence_file:
            raise ValueError(
                "proof requires --evidence-file for artifact-backed coverage: "
                + ", ".join(sorted(artifact_requirements))
            )
        schemas = set(artifact_requirements.values())
        if len(schemas) != 1:
            raise ValueError("one proof cannot combine coverage with different artifact schemas")
        evidence = read_evidence_artifact(
            control,
            repo,
            args.evidence_file,
            expected_schemas=schemas,
            coverage_ids=set(artifact_requirements),
        )
    elif args.evidence_file:
        (evidence_key, product_evidence) = read_proof_evidence(control, repo, args.evidence_file)
        expected_schema = (
            declared_recipe.get("evidence_schema")
            if isinstance(declared_recipe, dict) else None
        )
        if expected_schema is not None and product_evidence.get("schema") != expected_schema:
            raise ValueError(
                f"proof evidence schema does not match the declared recipe for {node_id}/{proof_id}"
            )
        if evidence_key == "e2e_evidence":
            e2e_evidence = product_evidence
        elif evidence_key == "release_evidence":
            release_evidence = product_evidence
            enabled_capabilities = receipt.get("capabilities", {}).get("enabled", [])
            if "release" not in enabled_capabilities:
                raise ValueError("release evidence requires the enabled release capability")
            if node is None or node.get("node_kind") != "release":
                raise ValueError("release evidence requires a release plan node")
        else:
            performance_evidence = product_evidence
            if outcome.get("kind") != "measured_improvement":
                raise ValueError("performance evidence requires a measured_improvement outcome")
            if performance_evidence["phase"] == "comparison":
                performance_evidence = bind_performance_baseline(
                    control,
                    repo,
                    performance_evidence,
                    history,
                    outcome=outcome,
                    plan_revision=plan_revision,
                    node=node,
                )
    proof_cwd = repo
    if isinstance(declared_recipe, dict) and declared_recipe.get("cwd"):
        proof_cwd = (repo / str(declared_recipe["cwd"])).resolve()
        try:
            proof_cwd.relative_to(repo)
        except ValueError as error:
            raise ValueError("proof recipe cwd escapes the repository") from error
    completed = subprocess.run(
        command_parts,
        cwd=proof_cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output_digest = hashlib.sha256(
        (completed.stdout + "\n" + completed.stderr).encode("utf-8")
    ).hexdigest()
    if completed.returncode != 0:
        proof_status = "failed"
    elif e2e_evidence is not None and e2e_evidence["result"] != "passed":
        proof_status = "failed"
    elif release_evidence is not None and release_evidence["result"] != "succeeded":
        proof_status = "failed"
    elif performance_evidence is not None:
        proof_status = (
            "recorded"
            if performance_evidence["phase"] == "baseline"
            else "passed" if performance_evidence["result"] == "passed" else "failed"
        )
    else:
        proof_status = "passed"
    proof_scope = (
        list(node.get("write_scope", []))
        if isinstance(node, dict) and node.get("node_role") in {"work_packet", "integration"}
        else list(receipt.get("planned_scope", []))
    )
    observed_paths: list[str] = []
    if isinstance(declared_recipe, dict):
        declared_observed = declared_recipe.get("observed_paths")
        if not isinstance(declared_observed, list) or not declared_observed:
            declared_observed = list(declared_recipe.get("inputs", []))
            if declared_recipe.get("evidence_file"):
                declared_observed.append(str(declared_recipe["evidence_file"]))
        observed_paths = list(dict.fromkeys(str(value) for value in declared_observed if value))
    proof = {
        "task_id": receipt["id"],
        "node_id": node_id,
        "proof_id": proof_id,
        "description": expected[proof_id]["description"],
        "evidence_kind": expected[proof_id].get("evidence_kind", "supporting"),
        "coverage_ids": list(expected[proof_id].get("coverage_ids", [])),
        "outcome_sha256": control.outcome_digest(outcome),
        "plan_revision": plan_revision,
        "state_revision": loaded_state_revision,
        "status": proof_status,
        "command": control.redact_command_parts(command_parts),
        "command_sha256": hashlib.sha256(
            json.dumps(command_parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "recipe_sha256": hashlib.sha256(
            json.dumps(
                expected[proof_id].get("recipe", {}),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "exit_code": completed.returncode,
        "output_sha256": output_digest,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
        "output_summary": (completed.stderr or completed.stdout).strip()[:240],
        "scope": proof_scope,
        "scope_sha256": control.workspace_scope_digest(repo, proof_scope),
        "observed_paths": observed_paths,
        "observed_paths_sha256": (
            control.workspace_scope_digest(repo, observed_paths) if observed_paths else None
        ),
        "head": control.git_head(repo),
        "worktree_status": control.workspace_product_status(control.current_status(repo)),
        "at": control.now(),
        "revalidation": bool(args.revalidate),
    }
    if isinstance(node, dict) and node.get("node_role") in {"work_packet", "integration"}:
        execution_base = node.get("execution_base") if isinstance(node.get("execution_base"), dict) else {}
        proof.update({
            "node_contract_sha256": node.get("contract_sha256"),
            "compilation_revision": execution_base.get("compilation_revision"),
            "execution_base_sha256": hashlib.sha256(
                json.dumps(
                    execution_base, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest(),
        })
    if evidence is not None:
        proof["evidence_artifact"] = evidence
    if e2e_evidence is not None:
        proof["e2e_evidence"] = e2e_evidence
    if release_evidence is not None:
        proof["release_evidence"] = release_evidence
    if performance_evidence is not None:
        proof["performance_evidence"] = performance_evidence
    if completed.returncode != 0:
        proof["failure_classification"] = args.failure_classification or "unknown"
    elif e2e_evidence is not None and e2e_evidence["result"] != "passed":
        proof["failure_classification"] = args.failure_classification or "unknown"
    elif release_evidence is not None and release_evidence["result"] != "succeeded":
        proof["failure_classification"] = args.failure_classification or "unknown"
    elif performance_evidence is not None and (
        performance_evidence["phase"] == "comparison" and performance_evidence["result"] != "passed"
    ):
        proof["failure_classification"] = args.failure_classification or "unknown"
    attempt_index = int(history[-1].get("attempt_index", len(history))) + 1 if history else 1
    proof["attempt_index"] = attempt_index
    proof["attempt_id"] = proof_attempt_id(control, node_id, proof_id, attempt_index)
    proof["fresh"] = proof_is_fresh(
        control, proof, outcome=outcome, repo=repo, plan_revision=plan_revision, node=node
    )
    proofs.append(proof)
    control.continuity_event(
        receipt,
        "outcome_proof_revalidated" if args.revalidate else "outcome_proof_recorded",
        proof=proof,
    )
    control.write_active(state, receipt, expected_revision=loaded_state_revision)
    print(json.dumps(proof, ensure_ascii=False))
    return 0 if proof["status"] in {"passed", "recorded"} else 1
