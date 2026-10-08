"""Environment and product-domain facts stored in Project Memory."""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import re
from typing import Any

from auto_dev_internal.memory.store import (
    REGISTRY_SCHEMA_VERSION,
    identifier,
    load,
    now,
    registry_path,
    repo_root,
    safe,
    safe_list,
    write_registry,
)


ENVIRONMENT_PROFILE_SCHEMA_VERSION = 1
DOMAIN_MEMORY_SCHEMA_VERSION = 1
ENVIRONMENT_DOMAIN_CONTROL_PLANE_VERSION = 4
ENVIRONMENT_OPERATION_KINDS = {
    "start",
    "health",
    "observe",
    "test",
    "gui",
    "release",
    "rollback",
}
GUI_VISUAL_MODES = {"required", "unavailable"}
DOMAIN_TERM_STATUSES = {"active", "ambiguous", "deprecated"}
DOMAIN_DECISION_STATUSES = {"active", "superseded"}
PROFILE_SENSITIVE = re.compile(
    r"(?i)(authorization|bearer\s+|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"password\s*[:=]|secret\s*[:=]|cookie\s*[:=]|private[_ -]?key)"
)


def profile_text(label: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    normalized = safe(label, value)
    if PROFILE_SENSITIVE.search(normalized):
        raise ValueError(f"{label} appears to contain a credential or secret")
    return normalized


def optional_profile_text(label: str, value: Any) -> str | None:
    if value is None:
        return None
    return profile_text(label, value)


def profile_list(label: str, values: Any, *, required: bool = False) -> list[str]:
    if values is None:
        values = []
    if not isinstance(values, list):
        raise ValueError(f"{label} must be a list")
    result: list[str] = []
    for value in values:
        item = profile_text(label, value)
        if item not in result:
            result.append(item)
    if required and not result:
        raise ValueError(f"{label} requires at least one value")
    return result


def exact_object(label: str, value: Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} has unsupported fields: {', '.join(unknown)}")
    return value


def profile_root(value: str) -> pathlib.Path | None:
    candidate = pathlib.Path(value).expanduser().resolve()
    if not candidate.is_dir():
        raise ValueError(f"project path is not a directory: {candidate}")
    try:
        root = repo_root(str(candidate))
    except ValueError:
        root = next(
            (
                parent
                for parent in (candidate, *candidate.parents)
                if (parent / ".auto-dev" / "project.json").is_file()
            ),
            None,
        )
    if root is None or not (root / ".auto-dev" / "project.json").is_file():
        return None
    return root


def require_profile_root(value: str) -> pathlib.Path:
    root = profile_root(value)
    if root is None:
        raise ValueError("environment and domain memory require an initialized Auto Dev project")
    try:
        project = json.loads((root / ".auto-dev" / "project.json").read_text(encoding="utf-8"))
        version = project.get("control_plane_upgrade_version", 0)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"project control cannot be read: {error}") from error
    if not isinstance(version, int) or version < ENVIRONMENT_DOMAIN_CONTROL_PLANE_VERSION:
        raise ValueError(
            "environment and domain memory require legacy-upgrade apply to the current control-plane version"
        )
    return root


def profile_control_version(repo: pathlib.Path) -> int:
    try:
        project = json.loads((repo / ".auto-dev" / "project.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    version = project.get("control_plane_upgrade_version", 0)
    return version if isinstance(version, int) else 0


def environment_projection_path(repo: pathlib.Path) -> pathlib.Path:
    return repo / ".auto-dev" / "path.md"


def domain_projection_path(repo: pathlib.Path) -> pathlib.Path:
    return repo / ".auto-dev" / "project-domain.md"


def normalize_endpoint(raw: Any) -> dict[str, str]:
    value = exact_object("environment endpoint", raw, {"id", "url", "purpose", "environment"})
    result = {
        "id": identifier(str(value.get("id") or "")),
        "url": profile_text("environment endpoint url", value.get("url")),
        "purpose": profile_text("environment endpoint purpose", value.get("purpose")),
    }
    environment = optional_profile_text("environment endpoint environment", value.get("environment"))
    if environment:
        result["environment"] = environment
    return result


def normalize_location(raw: Any) -> dict[str, str]:
    value = exact_object("environment location", raw, {"id", "path", "purpose"})
    return {
        "id": identifier(str(value.get("id") or "")),
        "path": profile_text("environment location path", value.get("path")),
        "purpose": profile_text("environment location purpose", value.get("purpose")),
    }


def normalize_host(raw: Any) -> dict[str, str]:
    value = exact_object("environment host", raw, {"id", "kind", "address"})
    result = {
        "id": identifier(str(value.get("id") or "")),
        "kind": profile_text("environment host kind", value.get("kind")),
    }
    address = optional_profile_text("environment host address", value.get("address"))
    if address:
        result["address"] = address
    return result


def normalize_operation(raw: Any) -> dict[str, Any]:
    value = exact_object(
        "environment operation",
        raw,
        {"id", "kind", "argv", "purpose", "working_directory", "evidence_root"},
    )
    kind = profile_text("environment operation kind", value.get("kind"))
    if kind not in ENVIRONMENT_OPERATION_KINDS:
        raise ValueError(
            "environment operation kind must be one of: "
            + ", ".join(sorted(ENVIRONMENT_OPERATION_KINDS))
        )
    argv = profile_list("environment operation argv", value.get("argv"), required=True)
    result: dict[str, Any] = {
        "id": identifier(str(value.get("id") or "")),
        "kind": kind,
        "argv": argv,
        "purpose": profile_text("environment operation purpose", value.get("purpose")),
    }
    for key in ("working_directory", "evidence_root"):
        item = optional_profile_text(f"environment operation {key}", value.get(key))
        if item:
            result[key] = item
    return result


def normalize_gui(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {
            "executor": "manual_only",
            "visual_mode": "unavailable",
            "evidence_roots": [],
            "devices": [],
        }
    value = exact_object(
        "environment gui",
        raw,
        {"executor", "visual_mode", "evidence_roots", "devices"},
    )
    visual_mode = profile_text("environment gui visual mode", value.get("visual_mode"))
    if visual_mode not in GUI_VISUAL_MODES:
        raise ValueError(
            "environment gui visual mode must be one of: " + ", ".join(sorted(GUI_VISUAL_MODES))
        )
    return {
        "executor": profile_text("environment gui executor", value.get("executor")),
        "visual_mode": visual_mode,
        "evidence_roots": profile_list("environment gui evidence root", value.get("evidence_roots")),
        "devices": profile_list("environment gui device", value.get("devices")),
    }


def normalize_environment_profile(raw: Any, repo: pathlib.Path) -> dict[str, Any]:
    value = exact_object(
        "environment profile",
        {} if raw is None else raw,
        {
            "schema_version",
            "host",
            "working_roots",
            "allowed_roots",
            "endpoints",
            "locations",
            "operations",
            "gui",
        },
    )
    schema_version = value.get("schema_version", ENVIRONMENT_PROFILE_SCHEMA_VERSION)
    if schema_version != ENVIRONMENT_PROFILE_SCHEMA_VERSION:
        raise ValueError("environment profile schema version is unsupported")
    endpoints = [normalize_endpoint(item) for item in value.get("endpoints", [])]
    working_roots = [normalize_location(item) for item in value.get("working_roots", [{
        "id": "repository",
        "path": str(repo.resolve()),
        "purpose": "project workspace",
    }])]
    locations = [normalize_location(item) for item in value.get("locations", [])]
    operations = [normalize_operation(item) for item in value.get("operations", [])]
    for label, entries in (
        ("environment endpoint", endpoints),
        ("environment working root", working_roots),
        ("environment location", locations),
        ("environment operation", operations),
    ):
        ids = [entry["id"] for entry in entries]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{label} ids must be unique")
    allowed_roots = profile_list(
        "environment allowed root",
        value.get("allowed_roots", [str(repo.resolve())]),
        required=True,
    )
    return {
        "schema_version": ENVIRONMENT_PROFILE_SCHEMA_VERSION,
        "host": normalize_host(value.get("host", {"id": "local", "kind": "local"})),
        "working_roots": working_roots,
        "allowed_roots": allowed_roots,
        "endpoints": endpoints,
        "locations": locations,
        "operations": operations,
        "gui": normalize_gui(value.get("gui")),
    }


def normalize_term(raw: Any) -> dict[str, Any]:
    value = exact_object("domain term", raw, {"name", "definition", "relations", "source", "status"})
    status = profile_text("domain term status", value.get("status", "active"))
    if status not in DOMAIN_TERM_STATUSES:
        raise ValueError("domain term status is unsupported")
    return {
        "name": profile_text("domain term name", value.get("name")),
        "definition": profile_text("domain term definition", value.get("definition")),
        "relations": profile_list("domain term relation", value.get("relations")),
        "source": profile_text("domain term source", value.get("source")),
        "status": status,
    }


def normalize_invariant(raw: Any) -> dict[str, str]:
    value = exact_object("domain invariant", raw, {"id", "rule", "scope", "source"})
    return {
        "id": identifier(str(value.get("id") or "")),
        "rule": profile_text("domain invariant rule", value.get("rule")),
        "scope": profile_text("domain invariant scope", value.get("scope")),
        "source": profile_text("domain invariant source", value.get("source")),
    }


def normalize_ambiguity(raw: Any) -> dict[str, str]:
    value = exact_object("domain ambiguity", raw, {"term", "meaning_a", "meaning_b", "source"})
    return {
        "term": profile_text("domain ambiguity term", value.get("term")),
        "meaning_a": profile_text("domain ambiguity meaning a", value.get("meaning_a")),
        "meaning_b": profile_text("domain ambiguity meaning b", value.get("meaning_b")),
        "source": profile_text("domain ambiguity source", value.get("source")),
    }


def normalize_decision(raw: Any) -> dict[str, str]:
    value = exact_object("domain decision", raw, {"id", "decision", "rationale", "source", "status"})
    status = profile_text("domain decision status", value.get("status", "active"))
    if status not in DOMAIN_DECISION_STATUSES:
        raise ValueError("domain decision status is unsupported")
    return {
        "id": identifier(str(value.get("id") or "")),
        "decision": profile_text("domain decision", value.get("decision")),
        "rationale": profile_text("domain decision rationale", value.get("rationale")),
        "source": profile_text("domain decision source", value.get("source")),
        "status": status,
    }


def normalize_domain_memory(raw: Any) -> dict[str, Any]:
    value = exact_object(
        "domain memory",
        {} if raw is None else raw,
        {"schema_version", "terms", "invariants", "ambiguities", "decisions"},
    )
    schema_version = value.get("schema_version", DOMAIN_MEMORY_SCHEMA_VERSION)
    if schema_version != DOMAIN_MEMORY_SCHEMA_VERSION:
        raise ValueError("domain memory schema version is unsupported")
    collections = {
        "terms": [normalize_term(item) for item in value.get("terms", [])],
        "invariants": [normalize_invariant(item) for item in value.get("invariants", [])],
        "ambiguities": [normalize_ambiguity(item) for item in value.get("ambiguities", [])],
        "decisions": [normalize_decision(item) for item in value.get("decisions", [])],
    }
    term_names = [item["name"].casefold() for item in collections["terms"]]
    if len(term_names) != len(set(term_names)):
        raise ValueError("domain term names must be unique")
    for name in ("invariants", "decisions"):
        identifiers = [item["id"] for item in collections[name]]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"domain {name} ids must be unique")
    return {"schema_version": DOMAIN_MEMORY_SCHEMA_VERSION, **collections}


def materialize_profile_document(
    repo: pathlib.Path,
    document: dict[str, Any],
) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result["schema_version"] = REGISTRY_SCHEMA_VERSION
    result["environment_profile"] = normalize_environment_profile(
        result.get("environment_profile"), repo
    )
    result["domain_memory"] = normalize_domain_memory(result.get("domain_memory"))
    return result


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(markdown_cell(cell) for cell in row) + " |" for row in rows)
    return lines


def render_environment_projection(repo: pathlib.Path, document: dict[str, Any]) -> str:
    profile = normalize_environment_profile(document.get("environment_profile"), repo)
    lines = [
        "# Auto Dev Environment Profile",
        "",
        "> Generated from `.auto-dev/project-memory.json`. Use `auto_dev.py environment set` to change it.",
        "> This projection is human-readable only; the structured profile is the runtime source of truth.",
        "",
        "## Workspace",
    ]
    lines.extend(markdown_table(["Field", "Value"], [
        ["Host", profile["host"]["id"]],
        ["Host kind", profile["host"]["kind"]],
        ["Host address", profile["host"].get("address", "")],
        ["Workspace root", str(repo.resolve())],
        ["Allowed roots", "<br>".join(profile["allowed_roots"])],
    ]))
    lines.extend(["", "## Working Roots"])
    lines.extend(markdown_table(["ID", "Path", "Purpose"], [
        [entry["id"], entry["path"], entry["purpose"]]
        for entry in profile["working_roots"]
    ]))
    lines.extend(["", "## Endpoints"])
    lines.extend(markdown_table(["ID", "URL", "Purpose", "Environment"], [
        [entry["id"], entry["url"], entry["purpose"], entry.get("environment", "")]
        for entry in profile["endpoints"]
    ]))
    lines.extend(["", "## Locations"])
    lines.extend(markdown_table(["ID", "Path", "Purpose"], [
        [entry["id"], entry["path"], entry["purpose"]]
        for entry in profile["locations"]
    ]))
    lines.extend(["", "## Operations"])
    lines.extend(markdown_table(["ID", "Kind", "Command argv", "Purpose", "Working directory", "Evidence root"], [
        [
            entry["id"], entry["kind"], json.dumps(entry["argv"], ensure_ascii=False),
            entry["purpose"], entry.get("working_directory", ""), entry.get("evidence_root", ""),
        ]
        for entry in profile["operations"]
    ]))
    gui = profile["gui"]
    lines.extend(["", "## GUI"])
    lines.extend(markdown_table(["Field", "Value"], [
        ["Executor", gui["executor"]],
        ["Visual mode", gui["visual_mode"]],
        ["Evidence roots", "<br>".join(gui["evidence_roots"])],
        ["Devices", "<br>".join(gui["devices"])],
    ]))
    return "\n".join(lines) + "\n"


def render_domain_projection(document: dict[str, Any]) -> str:
    domain = normalize_domain_memory(document.get("domain_memory"))
    lines = [
        "# Auto Dev Project Domain Memory",
        "",
        "> Generated from `.auto-dev/project-memory.json`. Use `auto_dev.py domain set` to change it.",
        "> Keep cross-feature business language and durable decisions here; task-local implementation details stay in the task record.",
        "",
        "## Terms",
    ]
    lines.extend(markdown_table(["Term", "Definition", "Relations", "Source", "Status"], [
        [entry["name"], entry["definition"], "; ".join(entry["relations"]), entry["source"], entry["status"]]
        for entry in domain["terms"]
    ]))
    lines.extend(["", "## Invariants"])
    lines.extend(markdown_table(["ID", "Rule", "Scope", "Source"], [
        [entry["id"], entry["rule"], entry["scope"], entry["source"]]
        for entry in domain["invariants"]
    ]))
    lines.extend(["", "## Ambiguities"])
    lines.extend(markdown_table(["Term", "Meaning A", "Meaning B", "Source"], [
        [entry["term"], entry["meaning_a"], entry["meaning_b"], entry["source"]]
        for entry in domain["ambiguities"]
    ]))
    lines.extend(["", "## Durable Decisions"])
    lines.extend(markdown_table(["ID", "Decision", "Rationale", "Source", "Status"], [
        [entry["id"], entry["decision"], entry["rationale"], entry["source"], entry["status"]]
        for entry in domain["decisions"]
    ]))
    return "\n".join(lines) + "\n"


def projection_writes(repo: pathlib.Path, document: dict[str, Any]) -> dict[pathlib.Path, str]:
    materialized = materialize_profile_document(repo, document)
    return {
        environment_projection_path(repo): render_environment_projection(repo, materialized),
        domain_projection_path(repo): render_domain_projection(materialized),
    }


def document_payload(repo: pathlib.Path, document: dict[str, Any]) -> dict[str, Any]:
    profile = document.get("environment_profile")
    domain = document.get("domain_memory")
    return {
        "status": "configured" if isinstance(profile, dict) else "unconfigured",
        "path": ".auto-dev/path.md",
        "projection_exists": environment_projection_path(repo).is_file(),
        "memory_revision": int(document.get("memory_revision", 0)),
        "profile": normalize_environment_profile(profile, repo) if isinstance(profile, dict) else None,
        "domain_path": ".auto-dev/project-domain.md",
        "domain_projection_exists": domain_projection_path(repo).is_file(),
        "domain_memory": normalize_domain_memory(domain) if isinstance(domain, dict) else None,
    }


def write_profile_document(
    repo: pathlib.Path,
    document: dict[str, Any],
    *,
    expected_revision: int,
) -> int:
    materialized = materialize_profile_document(repo, document)
    materialized["updated_at"] = now()
    return write_registry(
        repo,
        materialized,
        expected_revision=expected_revision,
        projection_writes=projection_writes(repo, materialized),
    )


def initialize_profiles(repo: pathlib.Path, *, confirmation_source: str) -> dict[str, Any]:
    profile_text("environment initialization confirmation", confirmation_source)
    path = registry_path(repo)
    document = load(path)
    needs_write = (
        not isinstance(document.get("environment_profile"), dict)
        or not isinstance(document.get("domain_memory"), dict)
        or not environment_projection_path(repo).is_file()
        or not domain_projection_path(repo).is_file()
        or document.get("schema_version") != REGISTRY_SCHEMA_VERSION
    )
    if not needs_write:
        return {"status": "current", **document_payload(repo, document)}
    revision = write_profile_document(
        repo,
        document,
        expected_revision=int(document.get("memory_revision", 0)),
    )
    written = load(path)
    return {**document_payload(repo, written), "status": "initialized", "memory_revision": revision}


def read_profile_json(label: str, *, value: str | None, path: str | None) -> dict[str, Any]:
    if bool(value) == bool(path):
        raise ValueError(f"{label} requires exactly one of --json or --file")
    try:
        raw = value if value is not None else pathlib.Path(str(path)).expanduser().read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} cannot be read as JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


def command_environment_inspect(args: argparse.Namespace) -> int:
    repo = profile_root(args.repo_root)
    if repo is None:
        print(json.dumps({"status": "uninitialized", "path": ".auto-dev/path.md"}, ensure_ascii=False))
        return 0
    if profile_control_version(repo) < ENVIRONMENT_DOMAIN_CONTROL_PLANE_VERSION:
        print(json.dumps({
            "status": "migration_required",
            "path": ".auto-dev/path.md",
            "next_action": "legacy-upgrade inspect",
        }, ensure_ascii=False))
        return 0
    print(json.dumps(document_payload(repo, load(registry_path(repo))), ensure_ascii=False))
    return 0


def command_environment_init(args: argparse.Namespace) -> int:
    repo = require_profile_root(args.repo_root)
    print(json.dumps(initialize_profiles(repo, confirmation_source=args.confirmation_source), ensure_ascii=False))
    return 0


def command_environment_set(args: argparse.Namespace) -> int:
    repo = require_profile_root(args.repo_root)
    profile_text("environment update confirmation", args.confirmation_source)
    document = load(registry_path(repo))
    raw = read_profile_json(
        "environment profile",
        value=args.profile_json,
        path=args.profile_file,
    )
    document["environment_profile"] = normalize_environment_profile(raw, repo)
    revision = write_profile_document(repo, document, expected_revision=args.memory_revision)
    written = load(registry_path(repo))
    print(json.dumps({**document_payload(repo, written), "status": "updated", "memory_revision": revision}, ensure_ascii=False))
    return 0


def command_domain_inspect(args: argparse.Namespace) -> int:
    repo = profile_root(args.repo_root)
    if repo is None:
        print(json.dumps({"status": "uninitialized", "path": ".auto-dev/project-domain.md"}, ensure_ascii=False))
        return 0
    if profile_control_version(repo) < ENVIRONMENT_DOMAIN_CONTROL_PLANE_VERSION:
        print(json.dumps({
            "status": "migration_required",
            "path": ".auto-dev/project-domain.md",
            "next_action": "legacy-upgrade inspect",
        }, ensure_ascii=False))
        return 0
    document = load(registry_path(repo))
    domain = document.get("domain_memory")
    print(json.dumps({
        "status": "configured" if isinstance(domain, dict) else "unconfigured",
        "path": ".auto-dev/project-domain.md",
        "projection_exists": domain_projection_path(repo).is_file(),
        "memory_revision": int(document.get("memory_revision", 0)),
        "domain_memory": normalize_domain_memory(domain) if isinstance(domain, dict) else None,
    }, ensure_ascii=False))
    return 0


def command_domain_set(args: argparse.Namespace) -> int:
    repo = require_profile_root(args.repo_root)
    profile_text("domain update confirmation", args.confirmation_source)
    document = load(registry_path(repo))
    raw = read_profile_json(
        "domain memory",
        value=args.domain_json,
        path=args.domain_file,
    )
    document["domain_memory"] = normalize_domain_memory(raw)
    revision = write_profile_document(repo, document, expected_revision=args.memory_revision)
    written = load(registry_path(repo))
    print(json.dumps({
        "status": "updated",
        "memory_revision": revision,
        "path": ".auto-dev/project-domain.md",
        "domain_memory": written["domain_memory"],
    }, ensure_ascii=False))
    return 0
