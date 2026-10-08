"""Dependency leases, bounded preflight gates, resolution, and attempts."""

from __future__ import annotations

from auto_dev_internal.memory.store import *
from auto_dev_internal.memory.entries import *

def load_json_object(path: pathlib.Path, label: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} cannot be read: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def load_lease(repo: pathlib.Path) -> dict[str, Any] | None:
    value = load_json_object(lease_path(repo), "dependency lease")
    if value is None:
        return None
    schema_version = value.get("schema_version", 1)
    if schema_version == 1:
        return {"schema_version": LEASE_SCHEMA_VERSION, "leases": [value]}
    if schema_version != LEASE_SCHEMA_VERSION:
        raise ValueError("unsupported dependency lease schema version")
    leases = value.get("leases")
    if not isinstance(leases, list) or not all(isinstance(item, dict) for item in leases):
        raise ValueError("dependency lease set must contain a leases array")
    return value


def lease_key(value: dict[str, Any]) -> tuple[str, str | None]:
    capability = str(value.get("capability") or "").casefold()
    scope = value.get("scope") if isinstance(value.get("scope"), str) else None
    return capability, scope


def lease_items(value: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list(value.get("leases", [])) if isinstance(value, dict) else []


def write_lease(repo: pathlib.Path, value: dict[str, Any]) -> None:
    current = load_lease(repo)
    key = lease_key(value)
    leases = [item for item in lease_items(current) if lease_key(item) != key]
    leases.append(value)
    ensure_storage_root(repo)
    write(lease_path(repo), {"schema_version": LEASE_SCHEMA_VERSION, "leases": leases})


def remove_matching_lease(
    repo: pathlib.Path,
    *,
    dependency_id: str,
    capability: str,
    scope: str | None,
) -> None:
    current = load_lease(repo)
    if current is None:
        return
    leases = [
        item for item in lease_items(current)
        if not (
            item.get("dependency_id") == dependency_id
            and str(item.get("capability", "")).casefold() == capability.casefold()
            and (scope is None or item.get("scope") == scope)
        )
    ]
    if leases:
        write(lease_path(repo), {"schema_version": LEASE_SCHEMA_VERSION, "leases": leases})
    else:
        lease_path(repo).unlink(missing_ok=True)


def build_lease(
    entry: dict[str, Any],
    *,
    repo: pathlib.Path,
    capability: str,
    scope: str | None,
    environment: list[str],
    runtime_bindings: list[list[str]] | None = None,
) -> dict[str, Any]:
    bindings = runtime_bindings if runtime_bindings is not None else entry.get("runtime_argvs", [])
    return {
        "schema_version": LEASE_SCHEMA_VERSION,
        "created_at": now(),
        "validated_at": now(),
        "dependency_id": entry["id"],
        "capability": capability,
        "scope": scope,
        "environment": environment,
        "version": entry.get("version"),
        "status": entry.get("status"),
        "role": entry.get("role"),
        "runtime_argvs": bindings,
        "observed_head": current_head(repo),
    }


def argv_prefix_matches(argv: list[str], binding: list[str]) -> bool:
    return len(argv) >= len(binding) and argv[:len(binding)] == binding


def matching_runtime_binding(entry: dict[str, Any], argv: list[str]) -> list[str] | None:
    bindings = entry.get("runtime_argvs", [])
    if not isinstance(bindings, list):
        return None
    for binding in bindings:
        if isinstance(binding, list) and all(isinstance(item, str) for item in binding):
            if argv_prefix_matches(argv, binding):
                return binding
    return None


def parse_expiry(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone() if parsed.tzinfo is None else parsed


def active_lease_gate(
    repo: pathlib.Path,
    document: dict[str, Any],
    *,
    capability: str,
    scope: str | None,
    argv: list[str],
) -> dict[str, Any]:
    lease_set = load_lease(repo)
    if lease_set is None:
        return {"status": "preflight-required", "reason": "lease_missing", "lease": None}
    matching = [
        lease for lease in lease_items(lease_set)
        if str(lease.get("capability", "")).casefold() == capability.casefold()
        and (not scope or not isinstance(lease.get("scope"), str) or scope_matches([lease["scope"]], scope))
    ]
    if not matching:
        return {"status": "preflight-required", "reason": "lease_capability_mismatch", "lease": None}
    last_reason = "lease_dependency_not_usable"
    for lease in matching:
        _, entry = find_entry(document, str(lease.get("dependency_id") or ""))
        if entry is None or entry.get("kind") != "dependency":
            last_reason = "lease_dependency_missing"
            continue
        if entry.get("status") != "known-good" or entry.get("role") not in {"preferred", "fallback"}:
            last_reason = "lease_dependency_not_usable"
            continue
        if review_reasons(entry, datetime.now().astimezone()):
            last_reason = "lease_needs_recheck"
            continue
        binding = matching_runtime_binding(lease, argv)
        if binding is None:
            last_reason = "lease_runtime_binding_missing" if not lease.get("runtime_argvs") else "lease_runtime_binding_mismatch"
            continue
        return {
            "status": "allowed",
            "reason": "active_lease",
            "lease": lease,
            "dependency": compact(entry),
            "runtime_argv": binding,
        }
    return {"status": "preflight-required", "reason": last_reason, "lease": matching[0]}


def preflight_gate(
    repo: pathlib.Path,
    *,
    capability: str,
    scope: str | None,
    argv: list[str],
) -> dict[str, Any] | None:
    permit = load_json_object(preflight_path(repo), "dependency preflight permit")
    if permit is None:
        return None
    expires_at = parse_expiry(permit.get("expires_at"))
    if expires_at is None or expires_at <= datetime.now().astimezone(expires_at.tzinfo):
        return {"status": "preflight-required", "reason": "preflight_permit_expired", "permit": permit}
    if str(permit.get("capability", "")).casefold() != capability.casefold():
        return None
    permit_scope = permit.get("scope")
    if scope and isinstance(permit_scope, str) and not scope_matches([permit_scope], scope):
        return None
    binding = permit.get("runtime_argv")
    if not isinstance(binding, list) or not all(isinstance(item, str) for item in binding):
        return {"status": "preflight-required", "reason": "preflight_permit_invalid", "permit": permit}
    if not argv_prefix_matches(argv, binding):
        return {"status": "preflight-required", "reason": "preflight_runtime_binding_mismatch", "permit": permit}
    return {
        "status": "preflight-permitted",
        "reason": "bounded_preflight",
        "permit": permit,
        "runtime_argv": binding,
    }


def gate(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo_root)
    document = load(registry_path(repo))
    argv = runtime_argv("argv", args.argv_json, repo, require_absolute_program=False)
    permit_result = preflight_gate(
        repo,
        capability=args.capability,
        scope=args.scope,
        argv=argv,
    )
    result = permit_result or active_lease_gate(
        repo,
        document,
        capability=args.capability,
        scope=args.scope,
        argv=argv,
    )
    result.update({"capability": args.capability, "scope": args.scope, "argv": argv})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"allowed", "preflight-permitted"} else 3


def preflight_open(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo_root)
    document = load(registry_path(repo))
    dependency_id = identifier(args.dependency_id)
    _, entry = find_entry(document, dependency_id)
    if entry is None or entry.get("kind") != "dependency":
        raise ValueError(f"dependency recipe not found: {dependency_id}")
    if entry.get("status") == "known-bad" or entry.get("role") == "avoid":
        raise ValueError("known-bad dependencies cannot open a preflight permit")
    if not capability_matches(entry, args.capability):
        raise ValueError("dependency does not provide the requested capability")
    if not scope_matches(entry.get("scope", []), args.scope):
        raise ValueError("dependency does not match the requested scope")
    argv = runtime_argv("runtime argv", args.argv_json, repo)
    binding = matching_runtime_binding(entry, argv)
    if binding is None:
        raise ValueError("preflight argv must match a declared dependency runtime argv")
    ttl_seconds = int(args.ttl_seconds)
    if not 60 <= ttl_seconds <= 3600:
        raise ValueError("preflight ttl must be between 60 and 3600 seconds")
    permit_id = identifier(args.permit_id)
    existing = load_json_object(preflight_path(repo), "dependency preflight permit")
    if existing is not None:
        expires_at = parse_expiry(existing.get("expires_at"))
        if expires_at is not None and expires_at > datetime.now().astimezone(expires_at.tzinfo):
            if existing.get("permit_id") == permit_id and existing.get("runtime_argv") == binding:
                print(json.dumps({"status": "preflight_open", "permit": existing, "reused": True}, ensure_ascii=False))
                return 0
            raise ValueError(f"a dependency preflight permit is already open: {existing.get('permit_id')}")
    created = datetime.now().astimezone()
    permit = {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "permit_id": permit_id,
        "dependency_id": dependency_id,
        "capability": args.capability,
        "scope": args.scope,
        "action_id": identifier(args.action_id),
        "runtime_argv": binding,
        "created_at": created.isoformat(timespec="seconds"),
        "expires_at": (created + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds"),
    }
    ensure_storage_root(repo)
    write(preflight_path(repo), permit)
    print(json.dumps({"status": "preflight_open", "permit": permit, "reused": False}, ensure_ascii=False))
    return 0


def preflight_close(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo_root)
    permit_path = preflight_path(repo)
    permit = load_json_object(permit_path, "dependency preflight permit")
    if permit is None:
        raise ValueError("dependency preflight permit not found")
    if permit.get("permit_id") != identifier(args.permit_id):
        raise ValueError("dependency preflight permit id does not match")
    expires_at = parse_expiry(permit.get("expires_at"))
    if expires_at is None or expires_at <= datetime.now().astimezone(expires_at.tzinfo):
        raise ValueError("dependency preflight permit has expired")
    dependency_id = identifier(str(permit.get("dependency_id") or ""))
    document = load(registry_path(repo))
    loaded_revision = int(document.get("memory_revision", 0))
    _, entry = find_entry(document, dependency_id)
    if entry is None or entry.get("kind") != "dependency":
        raise ValueError(f"dependency recipe not found: {dependency_id}")
    event = {
        "id": identifier(args.attempt_id) if args.attempt_id else f"{dependency_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "dependency_id": dependency_id,
        "at": now(),
        "result": args.result,
        "classification": args.classification,
        "summary": safe("attempt summary", args.summary),
        "evidence": safe_list("attempt evidence", args.evidence),
        "version": optional_safe("attempt version", args.version),
        "environment": safe_list("attempt environment", args.environment, required=False),
        "observed_head": current_head(repo),
    }
    if args.promote and args.result != "passed":
        raise ValueError("promotion requires a passed preflight")
    document["attempts"].append(event)
    promoted = False
    lease = None
    if args.promote:
        updated = dict(entry)
        updated["status"] = "known-good"
        updated["role"] = args.promote_role
        updated["updated_at"] = now()
        updated["observed_head"] = current_head(repo)
        upsert(document, updated)
        entry = updated
        promoted = True
    if (
        args.result == "failed"
        and args.classification in {"environment", "compatibility", "unknown"}
        and entry.get("status") == "known-good"
    ):
        updated = dict(entry)
        updated["status"] = "needs-recheck"
        updated["role"] = "candidate"
        updated["updated_at"] = now()
        updated["observed_head"] = current_head(repo)
        upsert(document, updated)
        entry = updated
    if args.result == "passed" and entry.get("status") == "known-good" and entry.get("role") in {"preferred", "fallback"}:
        binding = permit.get("runtime_argv")
        if not isinstance(binding, list) or not all(isinstance(item, str) for item in binding):
            raise ValueError("dependency preflight permit has no valid runtime argv")
        bindings = [binding]
        current = load_lease(repo)
        for existing in lease_items(current):
            if (
                existing.get("dependency_id") == dependency_id
                and existing.get("capability") == permit.get("capability")
                and existing.get("scope") == permit.get("scope")
            ):
                for existing_binding in existing.get("runtime_argvs", []):
                    if isinstance(existing_binding, list) and all(isinstance(item, str) for item in existing_binding):
                        if existing_binding not in bindings:
                            bindings.append(existing_binding)
        lease = build_lease(
            entry,
            repo=repo,
            capability=str(permit["capability"]),
            scope=permit.get("scope") if isinstance(permit.get("scope"), str) else None,
            environment=event["environment"],
            runtime_bindings=bindings,
        )
        write_lease(repo, lease)
    elif args.result == "failed" and args.classification in {"environment", "compatibility", "unknown"}:
        remove_matching_lease(
            repo,
            dependency_id=dependency_id,
            capability=str(permit["capability"]),
            scope=permit.get("scope") if isinstance(permit.get("scope"), str) else None,
        )
    document["updated_at"] = now()
    ensure_storage_root(repo)
    memory_revision = write_registry(repo, document, expected_revision=loaded_revision)
    permit_path.unlink(missing_ok=True)
    print(json.dumps({
        "status": "preflight_closed",
        "permit_id": permit["permit_id"],
        "dependency_id": dependency_id,
        "result": args.result,
        "promoted": promoted,
        "lease": lease,
        "memory_revision": memory_revision,
    }, ensure_ascii=False))
    return 0


def resolve(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo_root)
    document = load(registry_path(repo))
    current = datetime.now().astimezone()
    requested_environment = safe_list("environment", args.environment, required=False)
    matches = [
        entry for entry in document["entries"]
        if entry.get("kind") == "dependency"
        and capability_matches(entry, args.capability)
        and scope_matches(entry.get("scope", []), args.scope)
    ]
    compatible = [entry for entry in matches if environment_matches(entry, requested_environment)]
    blocked = [
        compact(entry, review=review_reasons(entry, current))
        for entry in matches
        if entry.get("status") == "known-bad" or entry.get("role") == "avoid"
    ]
    usable = [
        entry for entry in compatible
        if entry.get("status") == "known-good" and entry.get("role") in {"preferred", "fallback"}
    ]
    preferred = sorted(
        (entry for entry in usable if entry.get("role") == "preferred"),
        key=lambda entry: entry.get("updated_at", ""),
        reverse=True,
    )
    fallbacks = sorted(
        (entry for entry in usable if entry.get("role") == "fallback"),
        key=lambda entry: entry.get("updated_at", ""),
        reverse=True,
    )
    candidates = [
        compact(entry, review=review_reasons(entry, current))
        for entry in compatible if entry.get("status") == "candidate"
    ]
    selected = preferred[0] if preferred else (fallbacks[0] if fallbacks else None)
    review_due = [
        compact(entry, review=reasons)
        for entry in compatible
        if (reasons := review_reasons(entry, current))
    ]
    if selected is None:
        status = "miss" if not matches else "needs-investigation"
    elif selected.get("role") == "fallback":
        status = "fallback"
    elif review_reasons(selected, current):
        status = "needs-recheck"
    else:
        status = "resolved"
    lease = None
    if selected is not None:
        lease = build_lease(
            selected,
            repo=repo,
            capability=args.capability,
            scope=args.scope,
            environment=requested_environment,
        )
        if args.write_lease:
            write_lease(repo, lease)
    payload = {
        "status": status,
        "capability": args.capability,
        "scope": args.scope,
        "selected": compact(selected, review=review_reasons(selected, current)) if selected else None,
        "fallbacks": [compact(entry, review=review_reasons(entry, current)) for entry in fallbacks],
        "blocked": blocked,
        "candidates": candidates,
        "review_due": review_due,
        "lease": lease,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def attempt(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo_root)
    path = registry_path(repo)
    document = load(path)
    loaded_revision = int(document.get("memory_revision", 0))
    dependency_id = identifier(args.dependency_id)
    index, entry = find_entry(document, dependency_id)
    if entry is None or entry.get("kind") != "dependency":
        raise ValueError(f"dependency recipe not found: {dependency_id}")
    event = {
        "id": identifier(args.attempt_id) if args.attempt_id else f"{dependency_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "dependency_id": dependency_id,
        "at": now(),
        "result": args.result,
        "classification": args.classification,
        "summary": safe("attempt summary", args.summary),
        "evidence": safe_list("attempt evidence", args.evidence),
        "version": optional_safe("attempt version", args.version),
        "environment": safe_list("attempt environment", args.environment, required=False),
        "observed_head": current_head(repo),
    }
    if args.next_status == "known-good" and args.result != "passed":
        raise ValueError("known-good requires a passed attempt")
    if args.next_status == "known-bad" and args.result != "failed":
        raise ValueError("known-bad requires a failed attempt")
    document["attempts"].append(event)
    if args.next_status:
        updated = dict(entry)
        updated["status"] = args.next_status
        updated["role"] = args.next_role or default_role(args.next_status)
        if updated["role"] not in DEPENDENCY_ROLES:
            raise ValueError(f"unsupported dependency role: {updated['role']}")
        if updated["status"] == "known-bad" and updated["role"] != "avoid":
            raise ValueError("known-bad dependencies must use role avoid")
        if updated["status"] != "known-bad" and updated["role"] == "avoid":
            raise ValueError("role avoid requires status known-bad")
        updated["updated_at"] = now()
        updated["observed_head"] = current_head(repo)
        upsert(document, updated)
    document["updated_at"] = now()
    ensure_storage_root(repo)
    memory_revision = write_registry(repo, document, expected_revision=loaded_revision)
    print(json.dumps({
        "status": "attempt_recorded",
        "attempt_id": event["id"],
        "dependency_id": dependency_id,
        "next_status": args.next_status,
        "path": str(path.relative_to(repo)),
        "memory_revision": memory_revision,
    }, ensure_ascii=False))
    return 0
