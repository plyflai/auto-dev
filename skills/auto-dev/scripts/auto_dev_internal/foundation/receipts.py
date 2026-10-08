"""Receipt normalization, continuity state, and workspace snapshot helpers."""

from __future__ import annotations

from auto_dev_internal.foundation.core import *

def require_concrete(label: str, value: str) -> str:
    normalized = value.strip()
    invalid = {"", "none", "unknown", "n/a", "待确认"}
    if normalized.lower() in invalid or "replace-me" in normalized.lower():
        raise ValueError(f"{label} must be concrete")
    if normalized.startswith("<") and normalized.endswith(">"):
        raise ValueError(f"{label} still contains a placeholder")
    return normalized


def require_concrete_list(label: str, values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        concrete = require_concrete(label, value)
        if concrete not in result:
            result.append(concrete)
    if not result:
        raise ValueError(f"{label} requires at least one value")
    return result


def optional_concrete_list(label: str, values: Iterable[str] | None) -> list[str]:
    if values is None:
        return []
    return require_concrete_list(label, values) if list(values) else []


def require_continuity_id(label: str, value: str) -> str:
    normalized = require_concrete(label, value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", normalized):
        raise ValueError(f"{label} must use 1-80 letters, digits, dot, underscore, or hyphen")
    return normalized


def require_display_code(label: str, value: str) -> str:
    normalized = require_concrete(label, value)
    if not DISPLAY_CODE_RE.fullmatch(normalized):
        raise ValueError(f"{label} must use a display code such as M9, M9.1, or Control")
    return normalized

def outcome_digest(outcome: dict[str, Any]) -> str:
    encoded = json.dumps(outcome, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def redact_command_parts(parts: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for part in parts:
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            continue
        if re.search(r"(?i)(authorization|bearer|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)(=|$)", part):
            redacted.append("[REDACTED]")
            if "=" not in part:
                redact_next = True
            continue
        redacted.append(part)
    return redacted

def require_diagnostic_id(value: str) -> str:
    identifier = require_concrete("diagnostic id", value)
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", identifier):
        raise ValueError("diagnostic id must use lowercase letters, digits, hyphens, or underscores")
    return identifier


def normalize_diagnostic_fields(values: Iterable[str]) -> list[str]:
    fields = require_concrete_list("diagnostic field", values)
    normalized = [field.lower() for field in fields]
    unknown = sorted(set(normalized) - RUNTIME_DIAGNOSTIC_FIELDS)
    if unknown:
        raise ValueError(f"unknown diagnostic fields: {', '.join(unknown)}")
    missing = sorted(RUNTIME_DIAGNOSTIC_FIELDS - set(normalized))
    if missing:
        raise ValueError(f"runtime diagnostics require fields: {', '.join(missing)}")
    return normalized


def load_runtime_diagnostics(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": RUNTIME_DIAGNOSTICS_SCHEMA_VERSION,
            "entries": [],
        }
    try:
        document = read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"runtime diagnostics cannot be read: {error}") from error
    if document.get("schema_version") != RUNTIME_DIAGNOSTICS_SCHEMA_VERSION:
        raise ValueError("unsupported runtime diagnostics schema version")
    entries = document.get("entries")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("runtime diagnostics entries must be a list of objects")
    return document


def current_branch(repo: pathlib.Path) -> str | None:
    if workspace_storage_mode(repo) != "git":
        return None
    return git(repo, "branch", "--show-current", check=False) or None


def current_status(repo: pathlib.Path) -> list[str]:
    if workspace_storage_mode(repo) != "git":
        return []
    return git(repo, "status", "--short", check=False).splitlines()

def status_path(line: str) -> str:
    if len(line) > 2 and line[2] == " ":
        value = line[3:].strip()
    elif len(line) > 1 and line[1] == " ":
        # git() strips the leading space from the first short-status line.
        value = line[2:].strip()
    else:
        value = line.strip()
    if " -> " in value:
        value = value.split(" -> ", 1)[1]
    return value.strip('"')


def workspace_control_metadata_path(relative: str) -> bool:
    parts = pathlib.PurePosixPath(relative).parts
    return bool(parts) and parts[0].casefold() in WORKSPACE_CONTROL_METADATA_ROOTS


def workspace_product_status(status: Iterable[str]) -> list[str]:
    """Keep project-control metadata out of product-worktree decisions."""
    return [line for line in status if not workspace_control_metadata_path(status_path(line))]


def worktree_fingerprint(repo: pathlib.Path, relative: str) -> str:
    source = repo / relative
    if source.is_symlink():
        try:
            return "symlink:" + os.readlink(source)
        except OSError:
            return "symlink:<unreadable>"
    if not source.is_file():
        return "missing" if not source.exists() else "other"
    try:
        evaluation = current_evaluation(repo)
        digest = evaluation.file_digest(source) if evaluation is not None else None
        if digest is None:
            digest_state = hashlib.sha256()
            with source.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest_state.update(chunk)
            digest = digest_state.hexdigest()
    except OSError:
        return "file:<unreadable>"
    return "file:" + digest


def local_scope_manifest(repo: pathlib.Path, scopes: Iterable[str]) -> dict[str, str]:
    scope_list = list(scopes)
    with evaluation_scope(repo) as evaluation:
        cache_key = tuple(scope_list)
        cached = evaluation.scope_manifest_cache.get(cache_key)
        if cached is not None:
            return dict(cached)
        manifest: dict[str, str] = {}
        for scope in scope_list:
            root_manifest = evaluation.scope_root_cache.get(scope)
            if root_manifest is None:
                root_manifest = {}
                globbed = any(token in scope for token in ("*", "?", "[", "]"))
                sources = sorted(repo.glob(scope)) if globbed else [repo / scope]
                if not sources:
                    root_manifest[scope] = "missing"
                for source in sources:
                    relative_source = source.relative_to(repo).as_posix()
                    if source.is_symlink() or source.is_file():
                        root_manifest[relative_source] = worktree_fingerprint(repo, relative_source)
                    elif not source.exists():
                        root_manifest[scope] = "missing"
                    elif not source.is_dir():
                        root_manifest[relative_source] = "other"
                    else:
                        for path in source.rglob("*"):
                            if not (path.is_symlink() or path.is_file()):
                                continue
                            relative = path.relative_to(repo).as_posix()
                            if workspace_control_metadata_path(relative):
                                continue
                            root_manifest[relative] = worktree_fingerprint(repo, relative)
                evaluation.scope_root_cache[scope] = root_manifest
            manifest.update(root_manifest)
        result = dict(sorted(manifest.items()))
        evaluation.scope_manifest_cache[cache_key] = result
        return dict(result)


SNAPSHOT_MODES = {"auto", "none", "manifest", "full"}


def _snapshot_stat_record(repo: pathlib.Path, relative: str) -> dict[str, Any] | None:
    source = repo / relative
    try:
        stat = source.lstat()
    except OSError:
        return None
    if source.is_symlink():
        try:
            return {
                "path": relative,
                "kind": "symlink",
                "target": os.readlink(source),
                "size_bytes": 0,
                "mode": int(stat.st_mode),
                "mtime_ns": int(stat.st_mtime_ns),
            }
        except OSError:
            return None
    if not source.is_file():
        return None
    return {
        "path": relative,
        "kind": "file",
        "size_bytes": int(stat.st_size),
        "mode": int(stat.st_mode),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _snapshot_entries(repo: pathlib.Path, scopes: Iterable[str]) -> list[dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for scope in scopes:
        source = repo / scope
        if source.is_symlink() or source.is_file():
            candidates = [source]
        elif not source.is_dir():
            candidates = []
        else:
            candidates = list(source.rglob("*"))
        for path in candidates:
            try:
                relative = path.relative_to(repo).as_posix()
            except ValueError:
                continue
            if workspace_control_metadata_path(relative):
                continue
            record = _snapshot_stat_record(repo, relative)
            if record is not None:
                entries[relative] = record
    return [entries[key] for key in sorted(entries)]


def _snapshot_manifest_digest(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _snapshot_result(
    repo: pathlib.Path,
    destination: pathlib.Path,
    *,
    mode: str,
    patch_path: pathlib.Path | None,
    entries: list[dict[str, Any]],
    scopes: list[str],
) -> dict[str, Any]:
    if mode == "none":
        return {
            "mode": "none",
            "snapshot_ref": None,
            "digest": None,
            "count": 0,
            "size_bytes": 0,
            "patch": None,
            "untracked": [],
            "scope": list(scopes),
        }
    manifest = {
        "schema_version": 1,
        "mode": mode,
        "scope": list(scopes),
        "entries": entries,
    }
    manifest_path = destination / "manifest.json"
    write_json(manifest_path, manifest)
    total_bytes = sum(int(entry.get("size_bytes", 0)) for entry in entries)
    return {
        "mode": mode,
        "snapshot_ref": str(manifest_path.relative_to(repo)),
        "digest": _snapshot_manifest_digest(manifest),
        "count": len(entries),
        "size_bytes": total_bytes,
        "patch": str(patch_path.relative_to(repo)) if patch_path else None,
        # Keep the legacy key for readers that only check its presence. New
        # receipts deliberately keep the path list in the external manifest.
        "untracked": [],
        "scope": list(scopes),
    }


def capture_local_snapshot(
    repo: pathlib.Path,
    destination: pathlib.Path,
    scopes: list[str],
    *,
    mode: str = "full",
) -> dict[str, Any]:
    entries = _snapshot_entries(repo, scopes)
    if not entries:
        return _snapshot_result(
            repo, destination, mode="none", patch_path=None, entries=[], scopes=scopes
        )
    destination.mkdir(parents=True, exist_ok=True)
    if mode == "manifest":
        return _snapshot_result(
            repo, destination, mode=mode, patch_path=None, entries=entries, scopes=scopes
        )
    for entry in entries:
        relative = str(entry["path"])
        source = repo / relative
        target = destination / "local" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
        elif source.is_file():
            shutil.copy2(source, target)
    return _snapshot_result(
        repo, destination, mode="full", patch_path=None, entries=entries, scopes=scopes
    )


def capture_worktree_baseline(repo: pathlib.Path, status: list[str]) -> dict[str, dict[str, str]]:
    with evaluation_scope(repo):
        return {
            status_path(line): {
                "status": line,
                "fingerprint": worktree_fingerprint(repo, status_path(line)),
            }
            for line in workspace_product_status(status)
        }


def worktree_drift(
    repo: pathlib.Path,
    receipt: dict[str, Any],
    status: list[str],
    scopes: Iterable[str],
) -> tuple[list[str], list[str]]:
    if workspace_storage_mode(repo) == "local":
        # Local workspaces have no VCS-wide dirty set. The Hook enforces the
        # declared write scope, while this manifest remains evidence for the
        # explicitly scoped files only.
        return [], []
    current = capture_worktree_baseline(repo, status)
    baseline = receipt.get("worktree_baseline")
    if isinstance(baseline, dict):
        changed = [
            path for path, value in current.items()
            if not isinstance(baseline.get(path), dict) or baseline.get(path) != value
        ]
        preexisting = [path for path in current if path in baseline and path not in changed]
    else:
        initial_paths = {
            status_path(line)
            for line in workspace_product_status(
                line for line in receipt.get("initial_status", []) if isinstance(line, str)
            )
        }
        changed = [path for path in current if path not in initial_paths]
        preexisting = [path for path in current if path in initial_paths and path not in changed]
    scope_list = list(scopes)
    return (
        [path for path in changed if not path_in_scope(path, scope_list)],
        [path for path in preexisting if not path_in_scope(path, scope_list)],
    )


def path_in_scope(path: str, scopes: Iterable[str]) -> bool:
    candidates = [scopes] if isinstance(scopes, str) else scopes
    normalized_path = pathlib.PurePosixPath(
        str(path).replace("\\", "/")
    ).as_posix().removeprefix("./")
    for raw_scope in candidates:
        scope = pathlib.PurePosixPath(
            str(raw_scope).replace("\\", "/")
        ).as_posix().removeprefix("./")
        if any(token in scope for token in ("*", "?", "[", "]")):
            if fnmatch.fnmatchcase(normalized_path, scope):
                return True
            continue
        if normalized_path == scope or normalized_path.startswith(scope.rstrip("/") + "/"):
            return True
    return False


def normalize_scopes(repo: pathlib.Path, values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        raw = str(value).strip().replace("\\", "/")
        if not raw:
            raise ValueError("scope must not be empty")
        path = pathlib.Path(raw)
        if path.is_absolute():
            try:
                relative = path.resolve().relative_to(repo).as_posix()
            except ValueError as error:
                raise ValueError(f"scope escapes repository: {value}") from error
        else:
            pure = pathlib.PurePosixPath(raw)
            if ".." in pure.parts:
                raise ValueError(f"scope escapes repository: {value}")
            relative = pure.as_posix().removeprefix("./")
        fixed_prefix = relative
        for token in ("*", "?", "["):
            fixed_prefix = fixed_prefix.split(token, 1)[0]
        fixed_prefix = fixed_prefix.rstrip("/")
        if relative == "." or not relative or workspace_control_metadata_path(fixed_prefix or relative):
            raise ValueError(f"scope must target product files, not {value}")
        if relative not in normalized:
            normalized.append(relative)
    return normalized


def capture_snapshot(
    repo: pathlib.Path,
    destination: pathlib.Path,
    scopes: list[str],
    *,
    mode: str = "auto",
    preservation_scopes: list[str] | None = None,
) -> dict[str, Any]:
    if mode not in SNAPSHOT_MODES:
        raise ValueError(f"unsupported snapshot mode: {mode}")
    if not scopes:
        return _snapshot_result(
            repo, destination, mode="none", patch_path=None, entries=[], scopes=[]
        )
    effective_scopes = list(preservation_scopes or scopes)
    if workspace_storage_mode(repo) == "local":
        # Without Git there is no repository-wide dirty set to reconstruct;
        # retain the explicit scoped files as a full recovery snapshot.
        return capture_local_snapshot(repo, destination, effective_scopes, mode="full")
    if mode == "none":
        return _snapshot_result(
            repo, destination, mode="none", patch_path=None, entries=[], scopes=effective_scopes
        )
    diff = git(repo, "diff", "--binary", "HEAD", "--", *effective_scopes, check=False)
    patch_path: pathlib.Path | None = None
    untracked_output = git(
        repo,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        *effective_scopes,
        check=False,
    )
    untracked: list[str] = []
    for relative_text in untracked_output.splitlines():
        # Preserve symlink identity instead of resolving it. A workspace can
        # intentionally point a sample or generated artifact at a sibling
        # checkout; dereferencing that link both escapes the snapshot root and
        # changes the state being protected.
        source = repo / relative_text
        if not source.is_file() and not source.is_symlink():
            continue
        relative = pathlib.Path(relative_text)
        untracked.append(relative.as_posix())
    entries = []
    for relative in sorted(set(untracked)):
        record = _snapshot_stat_record(repo, relative)
        if record is not None:
            entries.append(record)
    if not diff and not entries:
        return _snapshot_result(
            repo, destination, mode="none", patch_path=None, entries=[], scopes=effective_scopes
        )
    resolved_mode = "manifest" if mode == "auto" else mode
    destination.mkdir(parents=True, exist_ok=True)
    if diff:
        patch_path = destination / "baseline.patch"
        patch_path.write_text(diff + "\n", encoding="utf-8")
    if resolved_mode == "full":
        for entry in entries:
            relative = str(entry["path"])
            source = repo / relative
            target = destination / "untracked" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                target.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
            elif source.is_file():
                shutil.copy2(source, target)
    return _snapshot_result(
        repo,
        destination,
        mode=resolved_mode,
        patch_path=patch_path,
        entries=entries,
        scopes=effective_scopes,
    )


def snapshot_prune_projection(
    repo: pathlib.Path, state: dict[str, pathlib.Path]
) -> dict[str, Any]:
    """Classify snapshot directories without deleting or rewriting any state."""
    root = state["snapshots"]
    if not root.is_dir():
        return {
            "status": "dry_run",
            "snapshot_root": str(root),
            "total_bytes": 0,
            "referenced_bytes": 0,
            "candidate_bytes": 0,
            "snapshots": [],
            "deletion_performed": False,
        }

    metadata_files = [
        path
        for path in state["root"].rglob("*")
        if path.is_file() and "snapshots" not in path.relative_to(state["root"]).parts
    ]
    directories = sorted(path for path in root.iterdir() if path.is_dir())
    records: list[dict[str, Any]] = []
    for directory in directories:
        size_bytes = sum(
            int(path.stat().st_size)
            for path in directory.rglob("*")
            if path.is_file()
        )
        references: list[str] = []
        token = directory.name
        task_path = state["tasks"] / f"{token}.json"
        run_path = state["runs"] / f"{token}.json"
        if task_path.is_file():
            references.append(str(task_path.relative_to(repo)))
        if run_path.is_file():
            references.append(str(run_path.relative_to(repo)))
        for path in metadata_files:
            if path in {task_path, run_path}:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if token in content:
                references.append(str(path.relative_to(repo)))
        references = sorted(set(references))
        records.append(
            {
                "id": token,
                "path": str(directory.relative_to(repo)),
                "bytes": size_bytes,
                "classification": "referenced" if references else "orphan_candidate",
                "references": references,
            }
        )
    total_bytes = sum(int(record["bytes"]) for record in records)
    referenced_bytes = sum(
        int(record["bytes"])
        for record in records
        if record["classification"] == "referenced"
    )
    return {
        "status": "dry_run",
        "snapshot_root": str(root),
        "total_bytes": total_bytes,
        "referenced_bytes": referenced_bytes,
        "candidate_bytes": total_bytes - referenced_bytes,
        "snapshots": records,
        "deletion_performed": False,
    }


def parse_budgets(values: Iterable[str]) -> dict[str, int]:
    budgets: dict[str, int] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"budget must use key=value: {value}")
        key, raw = value.split("=", 1)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ValueError(f"invalid budget key: {key}")
        try:
            amount = int(raw)
        except ValueError as error:
            raise ValueError(f"budget must be an integer: {value}") from error
        if amount < 0:
            raise ValueError(f"budget cannot be negative: {value}")
        budgets[key] = amount
    return budgets


def parse_skips(values: Iterable[str]) -> dict[str, str]:
    skipped: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"skip must use capability=reason: {value}")
        capability, reason = value.split("=", 1)
        validate_capabilities([capability])
        skipped[capability] = require_concrete("skip reason", reason)
    return skipped


def parse_capability_evidence(values: Iterable[str]) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"capability evidence must use capability=reason: {value}")
        capability, reason = value.split("=", 1)
        validate_capabilities([capability])
        evidence[capability] = require_concrete("capability evidence", reason)
    return evidence


def validate_capabilities(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in CAPABILITIES:
            raise ValueError(f"unknown capability: {value}")
        if value not in result:
            result.append(value)
    return result


def classify_capabilities(
    enabled_values: Iterable[str],
    skipped_values: Iterable[str],
    evidence_values: Iterable[str],
    *,
    require_complete: bool,
) -> dict[str, Any]:
    enabled = validate_capabilities(enabled_values)
    skipped = parse_skips(skipped_values)
    evidence = parse_capability_evidence(evidence_values)
    overlap = sorted(set(enabled) & set(skipped))
    if overlap:
        raise ValueError(f"capabilities cannot be enabled and skipped: {', '.join(overlap)}")
    missing = sorted(CAPABILITIES - set(enabled) - set(skipped))
    if require_complete and missing:
        raise ValueError(f"Team capability receipt is incomplete; classify: {', '.join(missing)}")
    missing_evidence = sorted(set(enabled) - set(evidence))
    if require_complete and missing_evidence:
        raise ValueError(f"enabled capabilities require evidence: {', '.join(missing_evidence)}")
    unused_evidence = sorted(set(evidence) - set(enabled))
    if unused_evidence:
        raise ValueError(f"capability evidence provided for disabled packs: {', '.join(unused_evidence)}")
    return {"enabled": enabled, "skipped": skipped, "evidence": evidence}


def merge_unique(*groups: Iterable[str]) -> list[str]:
    result: list[str] = []
    for group in groups:
        for value in group:
            concrete = require_concrete("stop condition", value)
            if concrete not in result:
                result.append(concrete)
    return result


def sync_budget_state(receipt: dict[str, Any]) -> None:
    budgets = {str(key): int(value) for key, value in receipt.get("budgets", {}).items()}
    raw_usage = receipt.get("budget_usage", {})
    usage = {key: int(raw_usage.get(key, 0)) for key in budgets}
    receipt["budgets"] = budgets
    receipt["budget_usage"] = usage
    receipt["exhausted_budgets"] = sorted(
        key for key, limit in budgets.items() if usage[key] > 0 and usage[key] >= limit
    )


def normalize_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    receipt.setdefault("schema_version", 1)
    receipt.setdefault("events", [])
    receipt.setdefault("budgets", {})
    receipt.setdefault("budget_usage", {})
    receipt.setdefault("stop_conditions", [])
    receipt.setdefault("proofs", [])
    receipt.setdefault("workspace_points", [])
    receipt.setdefault("workspace_checkpoint_protections", [])
    receipt.setdefault("scope_amendments", [])
    capabilities = receipt.setdefault("capabilities", {"enabled": [], "skipped": {}})
    capabilities.setdefault("enabled", [])
    capabilities.setdefault("skipped", {})
    capabilities.setdefault("evidence", {})
    receipt.setdefault("project_context_id", None)
    receipt.setdefault("primary_outcome_id", None)
    receipt.setdefault("intake_id", None)
    receipt.setdefault("contract_snapshot", None)
    receipt.setdefault("contract_parent_hash", None)
    receipt.setdefault("contract_status", contract_status(receipt.get("contract_snapshot")))
    receipt.setdefault("contract_coverage_ids", [])
    sync_budget_state(receipt)
    return receipt


def continuity_from_receipt(receipt: dict[str, Any]) -> dict[str, Any] | None:
    continuity = receipt.get("continuity")
    if not isinstance(continuity, dict):
        return None
    try:
        continuity["schema_version"] = max(
            int(continuity.get("schema_version", 1)), CONTINUITY_SCHEMA_VERSION
        )
    except (TypeError, ValueError):
        continuity["schema_version"] = CONTINUITY_SCHEMA_VERSION
    goal = continuity.setdefault("goal", {})
    goal.setdefault("revision", 1)
    goal.setdefault("statement", receipt.get("task", ""))
    goal.setdefault("acceptance", receipt.get("acceptance", []))
    goal.setdefault("source", receipt.get("confirmation_source", ""))
    plan = continuity.setdefault("plan", {})
    plan.setdefault("revision", 0)
    plan.setdefault("reason", "")
    plan.setdefault("strategy", "legacy")
    plan.setdefault("nodes", [])
    plan.setdefault("relations", [])
    plan.setdefault("graph_sha256", None)
    plan.setdefault("updated_at", continuity.get("updated_at", receipt.get("started_at")))
    continuity.setdefault("current_node", None)
    continuity.setdefault("compilation_focus", None)
    continuity.setdefault("execution_focus", continuity.get("current_node"))
    continuity.setdefault("ready_frontier", {"milestones": [], "work_packets": []})
    continuity.setdefault("exit_snapshots", [])
    continuity.setdefault("next_action", None)
    continuity.setdefault("gaps", [])
    continuity.setdefault("last_checkpoint", None)
    continuity.setdefault("pending_action", None)
    continuity.setdefault("evidence_links", [])
    continuity.setdefault("proofs", [])
    continuity.setdefault("workspace_points", [])
    continuity.setdefault("workspace_checkpoint_protections", [])
    continuity.setdefault("impact_receipts", [])
    continuity.setdefault("policy_approvals", [])
    if "diagnostic" in continuity:
        continuity["diagnostic"] = normalize_diagnostic(continuity.get("diagnostic"))
    for proof in continuity["proofs"]:
        if not isinstance(proof, dict):
            continue
        proof.setdefault("attempt_index", 1)
        proof.setdefault(
            "attempt_id",
            f"legacy-{proof.get('node_id', 'run')}-{proof.get('proof_id', 'proof')}",
        )
        proof.setdefault("fresh", proof.get("status") == "passed")
    durability = continuity.setdefault("durability", {})
    durability.setdefault("level", "local")
    durability.setdefault("updated_at", continuity.get("updated_at", receipt.get("started_at")))
    return continuity


def continuity_reconciliation_issues(
    repo: pathlib.Path, continuity: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Find terminal plan nodes whose recorded completion lacks current proof."""
    if continuity is None:
        return []
    issues: list[dict[str, Any]] = []
    proofs = continuity.get("proofs", [])
    nodes = {
        str(node.get("id")): node
        for node in continuity.get("plan", {}).get("nodes", [])
        if isinstance(node, dict) and node.get("id")
    }
    accepted_milestones = {
        node_id for node_id, node in nodes.items()
        if node.get("node_role") == "milestone"
        and node.get("milestone_state", {}).get("review_result") == "accepted"
        and node.get("milestone_state", {}).get("exit_snapshot_id")
    }
    for node in continuity.get("plan", {}).get("nodes", []):
        if not isinstance(node, dict) or node.get("status") != "done":
            continue
        if (
            node.get("node_role") == "milestone"
            and node.get("milestone_state", {}).get("review_result") == "accepted"
        ):
            continue
        if node.get("parent_id") in accepted_milestones:
            continue
        node_id = str(node.get("id"))
        outcome = node.get("outcome") if isinstance(node.get("outcome"), dict) else None
        if outcome is None:
            issues.append({
                "node_id": node_id,
                "kind": "legacy_unverified",
                "reason": "done node has no outcome contract",
            })
            continue
        for proof_spec in outcome.get("proofs", []):
            proof_id = str(proof_spec.get("id"))
            latest = latest_proof(proofs, node_id=node_id, proof_id=proof_id)
            if latest is None:
                issues.append({
                    "node_id": node_id,
                    "proof_id": proof_id,
                    "kind": "legacy_unverified" if node.get("historical_completion") else "missing_proof",
                    "reason": "done node has no recorded proof attempt",
                })
                continue
            if latest.get("status") != "passed":
                issues.append({
                    "node_id": node_id,
                    "proof_id": proof_id,
                    "kind": "latest_proof_failed",
                    "reason": f"latest proof attempt is {latest.get('status')}",
                })
                continue
            if not proof_is_fresh(
                latest,
                outcome=outcome,
                repo=repo,
                plan_revision=int(continuity.get("plan", {}).get("revision", 0)),
                node=node,
            ):
                kind = (
                    "migration_revalidation_required"
                    if latest.get("migration_revalidation_required")
                    else "stale_proof"
                )
                issues.append({
                    "node_id": node_id,
                    "proof_id": proof_id,
                    "kind": kind,
                    "reason": "latest proof no longer matches outcome or worktree",
                })
    return issues


def continuity_event(receipt: dict[str, Any], event_type: str, **details: Any) -> None:
    receipt["schema_version"] = SCHEMA_VERSION
    receipt.setdefault("events", []).append({"type": event_type, "at": now(), **details})


def continuity_nodes(continuity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(node["id"]): node
        for node in continuity.get("plan", {}).get("nodes", [])
        if isinstance(node, dict) and node.get("id")
    }


def action_evidence_links(continuity: dict[str, Any]) -> set[tuple[str, str]]:
    links: set[tuple[str, str]] = set()
    for link in continuity.get("evidence_links", []):
        if not isinstance(link, dict):
            continue
        source_task_id = link.get("source_task_id")
        action_id = link.get("action_id")
        if source_task_id and action_id:
            links.add((str(source_task_id), str(action_id)))
    return links


def unattributed_action_evidence(
    receipt: dict[str, Any], continuity: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return action evidence that is neither node-bound nor append-only linked."""
    if continuity is None or not continuity.get("plan", {}).get("nodes"):
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in receipt.get("events", []):
        if not isinstance(event, dict):
            continue
        action_id = event.get("action_id")
        if not action_id or event.get("phase") not in {"started", "result", "failed"}:
            continue
        grouped.setdefault(str(action_id), []).append(event)

    nodes = continuity_nodes(continuity)
    linked = action_evidence_links(continuity)
    source_task_id = str(receipt.get("id", ""))
    findings: list[dict[str, Any]] = []
    for action_id, events in grouped.items():
        if (source_task_id, action_id) in linked:
            continue
        node_ids = {
            str(event["node_id"])
            for event in events
            if isinstance(event.get("node_id"), str) and event.get("node_id")
        }
        missing_node = any(not event.get("node_id") for event in events)
        if not missing_node and len(node_ids) == 1 and next(iter(node_ids)) in nodes:
            continue
        if missing_node:
            reason = "missing_node"
        elif len(node_ids) > 1:
            reason = "conflicting_nodes"
        else:
            reason = "node_missing_from_plan"
        evidence_count = sum(
            len(event.get("evidence", []))
            for event in events
            if isinstance(event.get("evidence"), list)
        )
        findings.append({
            "action_id": action_id,
            "type": events[-1].get("type"),
            "first_at": events[0].get("at"),
            "last_at": events[-1].get("at"),
            "phases": [str(event.get("phase")) for event in events],
            "summary": events[-1].get("summary"),
            "evidence_count": evidence_count,
            "reason": reason,
        })
    return findings


def require_action_node(continuity: dict[str, Any], value: str | None) -> tuple[str, dict[str, Any]]:
    if not value:
        raise ValueError("action phases require --node matching the current continuity node")
    node_id = require_continuity_id("action node", value)
    current_node = continuity.get("current_node")
    if current_node != node_id:
        raise ValueError(
            "action node must match current_node; revise the plan or checkpoint the intended node first"
        )
    node = continuity_nodes(continuity).get(node_id)
    if node is None:
        raise ValueError(f"action node does not exist: {node_id}")
    if node.get("status") not in {"active", "blocked"}:
        raise ValueError(f"action node is not executable: {node_id} ({node.get('status')})")
    return node_id, node


def current_plan_revision(receipt: dict[str, Any]) -> int:
    continuity = continuity_from_receipt(receipt)
    return int(continuity["plan"].get("revision", 0)) if continuity else 0


def redact_for_handoff(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_for_handoff(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_for_handoff(item) for item in value]
    if isinstance(value, str) and SENSITIVE_TEXT.search(value):
        return "[REDACTED]"
    return value


def repo_fingerprint(repo: pathlib.Path) -> str:
    remote = git(repo, "config", "--get", "remote.origin.url", check=False)
    identity = remote or str(repo)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def workspace_summary(repo: pathlib.Path) -> dict[str, Any]:
    storage_mode = workspace_storage_mode(repo)
    return {
        "storage_mode": storage_mode,
        "vcs": "git" if storage_mode == "git" else "none",
        "limitations": [] if storage_mode == "git" else ["no_branch", "no_commit", "no_git_diff"],
    }


def ensure_write_ready(
    state: dict[str, pathlib.Path],
    branch: str | None,
    scopes: list[str],
    status: list[str],
) -> None:
    if is_protected(branch, protected_branches(state)):
        raise ValueError(f"product writes cannot start on protected branch {branch}; switch to a task branch")
    if workspace_product_status(status) and not scopes:
        raise ValueError("dirty worktree requires at least one explicit --scope before a run can start")


def require_active(state: dict[str, pathlib.Path]) -> dict[str, Any]:
    repo = state["root"].parent
    receipt, resolution = resolve_branch_task(repo, state)
    if receipt is None:
        if resolution.get("candidates"):
            raise ValueError("current branch requires an explicit task selection")
        raise ValueError("no active auto-dev run")
    return receipt


def require_working_task(state: dict[str, pathlib.Path]) -> dict[str, Any]:
    receipt = require_active(state)
    if receipt.get("status") == "review_ready":
        raise ValueError(
            "current task is review_ready; resume it after related user feedback before changing delivery state"
        )
    if receipt.get("status") != "active":
        raise ValueError(f"current task is not active: {receipt.get('status')}")
    return receipt


def continuity_has_plan(receipt: dict[str, Any]) -> bool:
    try:
        continuity = continuity_from_receipt(receipt)
    except (AttributeError, TypeError, ValueError):
        return False
    return bool(continuity and continuity.get("plan", {}).get("nodes"))


def readable_receipt(path: pathlib.Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, None
    try:
        receipt = read_json(path)
        if not isinstance(receipt, dict):
            raise ValueError("receipt must be a JSON object")
        return receipt, None
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return None, str(error)

def bind(control) -> None:
    """Bind cross-domain helpers through the stable runctl facade."""
    for name in dir(control):
        if not name.startswith("_"):
            globals()[name] = getattr(control, name)
