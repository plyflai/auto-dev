"""Dependency and gotcha entry construction and compact projections."""

from __future__ import annotations

from auto_dev_internal.memory.store import *

def build_dependency(args: argparse.Namespace, repo: pathlib.Path) -> dict[str, Any]:
    status = args.status
    role = args.role or default_role(status)
    if role not in DEPENDENCY_ROLES:
        raise ValueError(f"unsupported dependency role: {role}")
    if status == "known-bad" and role != "avoid":
        raise ValueError("known-bad dependencies must use role avoid")
    if status != "known-bad" and role == "avoid":
        raise ValueError("role avoid requires status known-bad")
    purpose = safe("purpose", args.purpose or "")
    capabilities = safe_list("capability", args.capability or [purpose])
    commands_required = status != "known-bad"
    entry = {
        "id": identifier(args.entry_id),
        "kind": "dependency",
        "name": safe("name", args.name or ""),
        "purpose": purpose,
        "capabilities": capabilities,
        "source": safe("source", args.source or ""),
        "version": safe("version", args.version or ""),
        "status": status,
        "role": role,
        "prerequisites": safe_list("prerequisite", args.prerequisite, required=False),
        "conditions": safe_list("condition", args.condition, required=False),
        "environment": safe_list("environment", args.environment, required=False),
        "commands": safe_list("command", args.command, required=commands_required),
        "runtime_argvs": runtime_argvs(args.runtime_argv, repo),
        "success_criteria": safe_list("success criterion", args.success, required=commands_required),
        "evidence": safe_list("evidence", args.evidence),
        "scope": safe_list("scope", args.scope),
        "incompatibilities": safe_list("incompatibility", args.incompatible, required=False),
        "limitations": safe_list("limitation", args.limitation, required=False),
        "fallbacks": [identifier(value) for value in args.fallback],
        "check_policy": args.check_policy,
        "last_checked_at": now(),
        "next_review_at": parse_timestamp("next review", args.next_review),
        "update_signal": optional_safe("update signal", args.update_signal),
        "updated_at": now(),
        "observed_head": current_head(repo),
    }
    return entry


def build_gotcha(args: argparse.Namespace, repo: pathlib.Path) -> dict[str, Any]:
    return {
        "id": identifier(args.entry_id),
        "kind": "gotcha",
        "symptom": safe("symptom", args.symptom or ""),
        "observed_behavior": safe("behavior", args.behavior or ""),
        "impact": safe("impact", args.impact or ""),
        "evidence": safe_list("evidence", args.evidence),
        "avoid": safe_list("avoid", args.avoid, required=False),
        "confidence": args.confidence,
        "scope": safe_list("scope", args.scope, required=False),
        "observed_version": optional_safe("version", args.version),
        "updated_at": now(),
        "observed_head": current_head(repo),
    }


def record(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo_root)
    path = registry_path(repo)
    document = load(path)
    loaded_revision = int(document.get("memory_revision", 0))
    kind = normalize_kind(args.kind)
    entry = build_dependency(args, repo) if kind == "dependency" else build_gotcha(args, repo)
    upsert(document, entry)
    document["updated_at"] = entry["updated_at"]
    ensure_storage_root(repo)
    memory_revision = write_registry(repo, document, expected_revision=loaded_revision)
    print(json.dumps({
        "status": "recorded",
        "id": entry["id"],
        "kind": entry["kind"],
        "path": str(path.relative_to(repo)),
        "observed_head": entry["observed_head"],
        "memory_revision": memory_revision,
    }, ensure_ascii=False))
    return 0


def scope_matches(scopes: list[str], requested: str | None) -> bool:
    if requested is None or not scopes:
        return True
    return any(
        requested == scope
        or requested.startswith(scope.rstrip("/") + "/")
        or scope.startswith(requested.rstrip("/") + "/")
        for scope in scopes
    )


def capability_matches(entry: dict[str, Any], capability: str) -> bool:
    requested = capability.casefold()
    return requested in {str(value).casefold() for value in entry.get("capabilities", [])}


def environment_matches(entry: dict[str, Any], requested: list[str]) -> bool:
    required = {value.casefold() for value in entry.get("environment", [])}
    supplied = {value.casefold() for value in requested}
    return not required or not supplied or required.issubset(supplied)


def review_reasons(entry: dict[str, Any], current: datetime) -> list[str]:
    reasons: list[str] = []
    if entry.get("status") == "needs-recheck":
        reasons.append("status_needs_recheck")
    next_review = entry.get("next_review_at")
    if entry.get("check_policy") == "ttl" and next_review:
        try:
            due_at = datetime.fromisoformat(str(next_review).replace("Z", "+00:00"))
        except ValueError:
            reasons.append("invalid_next_review")
        else:
            if due_at <= current.astimezone(due_at.tzinfo):
                reasons.append("ttl_due")
    if entry.get("update_signal"):
        reasons.append("update_signal")
    return reasons


def compact(entry: dict[str, Any], *, review: list[str] | None = None) -> dict[str, Any]:
    keys = (
        "id", "kind", "name", "purpose", "capabilities", "source", "version", "status", "role",
        "scope", "environment", "conditions", "prerequisites", "commands", "runtime_argvs",
        "success_criteria", "incompatibilities", "limitations", "fallbacks",
        "check_policy", "last_checked_at", "next_review_at", "update_signal",
        "updated_at", "observed_head", "case_type", "title", "keywords", "symptom_signals",
        "component_refs", "observed_version", "root_cause", "cause_class", "distinguishing_signals",
        "resolution_summary", "protective_tests", "lesson", "evidence_refs", "source_task_id",
    )
    result = {key: entry.get(key) for key in keys if key in entry}
    if review:
        result["review_due"] = review
    return result
