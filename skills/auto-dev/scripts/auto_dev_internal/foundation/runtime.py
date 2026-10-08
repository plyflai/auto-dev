"""Runtime diagnostics, CodeGraph adapters, recovery, and migration."""

from __future__ import annotations

from auto_dev_internal.foundation.core import *

def command_diagnostics(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_root)
    state = ensure_root(repo)
    document = load_runtime_diagnostics(state["runtime_diagnostics"])
    entry = {
        "id": require_diagnostic_id(args.diagnostic_id),
        "updated_at": now(),
        "components": require_concrete_list("diagnostic component", args.component),
        "scope": normalize_scopes(repo, args.scope),
        "layer": require_concrete("diagnostic layer", args.layer),
        "storage": require_concrete("diagnostic storage", args.storage),
        "retention": require_concrete("diagnostic retention", args.retention),
        "read": require_concrete_list("diagnostic read method", args.read),
        "events": require_concrete_list("diagnostic event", args.event),
        "fields": normalize_diagnostic_fields(args.field),
        "correlation": require_concrete("diagnostic correlation", args.correlation),
        "redaction": require_concrete_list("diagnostic redaction", args.redaction),
        "verification": require_concrete_list("diagnostic verification", args.verify),
        "limitations": require_concrete_list("diagnostic limitation", args.limit) if args.limit else [],
    }
    entries = document["entries"]
    for index, existing in enumerate(entries):
        if existing.get("id") == entry["id"]:
            entries[index] = entry
            break
    else:
        entries.append(entry)
    document["updated_at"] = entry["updated_at"]
    write_json(state["runtime_diagnostics"], document)
    print(json.dumps({
        "status": "updated",
        "id": entry["id"],
        "path": str(state["runtime_diagnostics"].relative_to(repo)),
    }, ensure_ascii=False))
    return 0

def archive_slug(value: str) -> str:
    from auto_dev_internal.continuity import workspace as runctl_workspace
    return runctl_workspace.archive_slug(sys.modules[__name__], value)


def workspace_sensitive_path(relative: str) -> bool:
    from auto_dev_internal.continuity import workspace as runctl_workspace
    return runctl_workspace.workspace_sensitive_path(sys.modules[__name__], relative)


def workspace_dirty_paths(status: Iterable[str]) -> list[str]:
    from auto_dev_internal.continuity import workspace as runctl_workspace
    return runctl_workspace.workspace_dirty_paths(sys.modules[__name__], status)


def workspace_scope_digest(repo: pathlib.Path, scopes: Iterable[str]) -> str:
    from auto_dev_internal.continuity import workspace as runctl_workspace
    return runctl_workspace.workspace_scope_digest(sys.modules[__name__], repo, scopes)


def codegraph_binary() -> str:
    configured = os.environ.get("AUTO_DEV_CODEGRAPH_BIN")
    resolved = shutil.which(configured or "codegraph")
    if resolved:
        return resolved
    if configured:
        candidate = pathlib.Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    raise ValueError("CodeGraph CLI is unavailable; install codegraph or set AUTO_DEV_CODEGRAPH_BIN")


def codegraph_index_fingerprint(repo: pathlib.Path) -> str | None:
    """Read the local index fingerprint without invoking CodeGraph or mutating it."""
    database = repo / ".codegraph" / "codegraph.db"
    if not database.is_file():
        return None
    digest = hashlib.sha256()
    for relative in (".codegraph/codegraph.db", ".codegraph/codegraph.db-wal"):
        path = repo / relative
        if not path.is_file():
            continue
        fingerprint = worktree_fingerprint(repo, relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(fingerprint.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def codegraph_json(repo: pathlib.Path, arguments: list[str]) -> dict[str, Any]:
    completed = run([codegraph_binary(), *arguments], repo, False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[:320]
        raise ValueError(f"CodeGraph {' '.join(arguments)} failed: {detail or 'unknown error'}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"CodeGraph {' '.join(arguments)} returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"CodeGraph {' '.join(arguments)} must return a JSON object")
    return payload


def codegraph_status_snapshot(repo: pathlib.Path) -> dict[str, Any]:
    payload = codegraph_json(repo, ["status", "-j"])
    pending = payload.get("pendingChanges")
    index = payload.get("index")
    project_path = payload.get("projectPath")
    stale = (
        payload.get("initialized") is not True
        or not isinstance(pending, dict)
        or any(
            isinstance(pending.get(key), bool)
            or not isinstance(pending.get(key), int)
            or pending.get(key) != 0
            for key in ("added", "modified", "removed")
        )
        or "worktreeMismatch" not in payload
        or payload.get("worktreeMismatch") is not None
        or not isinstance(index, dict)
        or index.get("reindexRecommended") is not False
        or index.get("builtWithExtractionVersion") is None
        or index.get("builtWithExtractionVersion") != index.get("currentExtractionVersion")
        or not isinstance(project_path, str)
        or pathlib.Path(project_path).resolve() != repo.resolve()
    )
    if stale:
        raise ValueError("CodeGraph index is not up to date; refresh it explicitly before impact inspection")
    fingerprint = codegraph_index_fingerprint(repo)
    if fingerprint is None:
        raise ValueError("CodeGraph index database is missing; impact inspection cannot be made durable")
    languages = sorted({
        value.strip().casefold()
        for value in payload.get("languages", [])
        if isinstance(value, str) and value.strip()
    }) if isinstance(payload.get("languages"), list) else []
    canonical_status = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return {
        "ready": True,
        "index_fingerprint": fingerprint,
        "status_sha256": hashlib.sha256(canonical_status.encode("utf-8")).hexdigest(),
        "version": payload.get("version"),
        "languages": languages,
        "last_indexed": payload.get("lastIndexed"),
        "pending_changes": {key: pending[key] for key in ("added", "modified", "removed")},
        "extraction_version": index["currentExtractionVersion"],
    }


def normalized_codegraph_path(repo: pathlib.Path, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return normalize_scopes(repo, [value])[0]
    except (IndexError, ValueError):
        return None


def impact_inspection(
    repo: pathlib.Path,
    *,
    symbols: Iterable[str],
    files: Iterable[str],
    max_depth: int = 8,
    test_filters: Iterable[str] = (),
) -> dict[str, Any]:
    from auto_dev_internal.verification import policy_impact as runctl_policy_impact
    return runctl_policy_impact.impact_inspection(
        sys.modules[__name__], repo, symbols=symbols, files=files,
        max_depth=max_depth, test_filters=test_filters,
    )

def command_recover(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_root)
    state = ensure_root(repo)
    backup = state["active"].with_suffix(".bak")
    if not backup.exists():
        raise ValueError("no active backup exists")
    receipt = normalize_receipt(read_json(backup))
    branch, head, key = current_context(repo)
    if branch_context_key(receipt.get("base_branch"), receipt.get("base_head")) != key:
        raise ValueError("active backup belongs to a different branch context")
    receipt["events"].append({"type": "active_recovered", "at": now(), "source": "active.bak"})
    receipt["schema_version"] = SCHEMA_VERSION
    receipt["state_revision"] = int(receipt.get("state_revision", 0)) + 1
    with state_lock(state["active"]):
        write_json(state["active"], receipt)
    sync_task_projection(state, receipt, selected=True)
    print(json.dumps({
        "status": "recovered",
        "id": receipt.get("id"),
        "state_revision": receipt["state_revision"],
    }, ensure_ascii=False))
    return 0

def command_migrate(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_root)
    state = ensure_root(repo)
    receipt = require_active(state)
    loaded_state_revision = int(receipt.get("state_revision", 0))
    previous_schema = int(receipt.get("schema_version", 1))
    if previous_schema > SCHEMA_VERSION:
        raise ValueError(
            f"active receipt schema {previous_schema} is newer than supported schema {SCHEMA_VERSION}"
        )
    normalize_receipt(receipt)
    if receipt.get("continuity") is not None:
        continuity_from_receipt(receipt)
    receipt["events"].append({
        "type": "schema_migrated",
        "at": now(),
        "from_schema": previous_schema,
        "to_schema": SCHEMA_VERSION,
    })
    next_revision = write_active(state, receipt, expected_revision=loaded_state_revision)
    print(json.dumps({
        "status": "migrated",
        "id": receipt.get("id"),
        "from_schema": previous_schema,
        "to_schema": SCHEMA_VERSION,
        "state_revision": next_revision,
    }, ensure_ascii=False))
    return 0

def bind(control) -> None:
    """Bind shared control-plane helpers through the facade."""
    for name in dir(control):
        if not name.startswith("_"):
            globals()[name] = getattr(control, name)
