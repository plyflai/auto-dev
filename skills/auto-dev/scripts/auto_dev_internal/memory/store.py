"""Project-memory registry storage, schema, and atomic persistence."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any, Iterable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback retains revision CAS.
    fcntl = None


REGISTRY_SCHEMA_VERSION = 4
LEASE_SCHEMA_VERSION = 2
PREFLIGHT_SCHEMA_VERSION = 1
DEPENDENCY_STATUSES = {"known-good", "known-bad", "candidate", "needs-recheck"}
DEPENDENCY_ROLES = {"preferred", "fallback", "candidate", "avoid"}
CHECK_POLICIES = {"on_miss", "on_failure", "on_demand", "ttl", "disabled"}
ATTEMPT_RESULTS = {"passed", "failed", "inconclusive"}
FAILURE_CLASSES = {
    "tool-task-mismatch",
    "usage",
    "environment",
    "input",
    "compatibility",
    "output",
    "downstream",
    "unknown",
}
SENSITIVE = re.compile(
    r"(?i)(authorization|bearer\s+|api[_-]?key|access[_-]?token|refresh[_-]?token|password\s*[:=]|secret\s*[:=])"
)
ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,79}")


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run(command: list[str], cwd: pathlib.Path) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or "command failed")
    return result.stdout.strip()


def repo_root(value: str) -> pathlib.Path:
    candidate = pathlib.Path(value).expanduser().resolve()
    try:
        return pathlib.Path(run(["git", "rev-parse", "--show-toplevel"], candidate)).resolve()
    except (OSError, ValueError) as error:
        raise ValueError(f"not inside a git repository: {candidate}") from error


def storage_root(repo: pathlib.Path) -> pathlib.Path:
    return repo / ".auto-dev"


def ensure_storage_root(repo: pathlib.Path) -> pathlib.Path:
    root = storage_root(repo)
    root.mkdir(parents=True, exist_ok=True)
    exclude = pathlib.Path(run(["git", "rev-parse", "--git-path", "info/exclude"], repo))
    if not exclude.is_absolute():
        exclude = repo / exclude
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if ".auto-dev/" not in {line.strip() for line in existing.splitlines()}:
        with exclude.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write("\n.auto-dev/\n")
    return root


def registry_path(repo: pathlib.Path) -> pathlib.Path:
    # Keep the legacy filename so prior handoff packets remain portable.
    return storage_root(repo) / "project-memory.json"


def lease_path(repo: pathlib.Path) -> pathlib.Path:
    return storage_root(repo) / "dependency-lease.json"


def preflight_path(repo: pathlib.Path) -> pathlib.Path:
    return storage_root(repo) / "dependency-preflight.json"


def current_head(repo: pathlib.Path) -> str | None:
    return run(["git", "rev-parse", "HEAD"], repo) or None


def safe(label: str, value: str) -> str:
    text = value.strip()
    if not text or text.lower() in {"none", "unknown", "n/a", "待确认"}:
        raise ValueError(f"{label} must be concrete")
    if SENSITIVE.search(text):
        raise ValueError(f"{label} appears to contain a credential or secret")
    return text


def optional_safe(label: str, value: str | None) -> str | None:
    return safe(label, value) if value else None


def safe_list(label: str, values: Iterable[str], *, required: bool = True) -> list[str]:
    result: list[str] = []
    for value in values:
        item = safe(label, value)
        if item not in result:
            result.append(item)
    if required and not result:
        raise ValueError(f"{label} requires at least one value")
    return result


def runtime_argv(
    label: str,
    value: str,
    repo: pathlib.Path,
    *,
    require_absolute_program: bool = True,
) -> list[str]:
    """Parse a declared command prefix without accepting a shell fragment."""
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} must be a JSON argv array") from error
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"{label} must be a non-empty JSON argv array")
    argv = [safe(label, item) for item in raw]
    program = pathlib.Path(argv[0]).expanduser()
    if require_absolute_program and not program.is_absolute():
        raise ValueError(f"{label} program must be an absolute path")
    if program.is_absolute():
        argv[0] = str(program.resolve())
    return argv


def runtime_argvs(values: Iterable[str], repo: pathlib.Path) -> list[list[str]]:
    result: list[list[str]] = []
    for value in values:
        argv = runtime_argv("runtime argv", value, repo)
        if argv not in result:
            result.append(argv)
    return result


def identifier(value: str) -> str:
    value = safe("id", value)
    if not ID_PATTERN.fullmatch(value):
        raise ValueError("id must use lowercase letters, digits, underscores, or hyphens")
    return value


def parse_timestamp(label: str, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = safe(label, value)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from error
    return parsed.astimezone().isoformat() if parsed.tzinfo is None else parsed.isoformat()


def default_role(status: str) -> str:
    if status == "known-good":
        return "preferred"
    if status == "known-bad":
        return "avoid"
    return "candidate"


def normalize_kind(value: str) -> str:
    return "dependency" if value == "toolchain" else value


def blank_registry() -> dict[str, Any]:
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "memory_revision": 0,
        "updated_at": None,
        "entries": [],
        "attempts": [],
        "environment_profile": None,
        "domain_memory": None,
    }


def legacy_dependency(raw: dict[str, Any]) -> dict[str, Any]:
    entry = dict(raw)
    if entry.get("kind") == "toolchain":
        entry["kind"] = "dependency"
        entry.setdefault("capabilities", [entry.get("purpose", entry.get("name", entry.get("id", "")))])
        entry.setdefault("status", "known-good")
        entry.setdefault("role", "preferred")
        entry.setdefault("conditions", entry.get("prerequisites", []))
        entry.setdefault("incompatibilities", [])
        entry.setdefault("fallbacks", [])
        entry.setdefault("check_policy", "on_failure")
        entry.setdefault("last_checked_at", entry.get("updated_at"))
        entry.setdefault("next_review_at", None)
        entry.setdefault("update_signal", None)
    entry.setdefault("revisions", [])
    entry.setdefault("runtime_argvs", [])
    return entry


def load(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return blank_registry()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"dependency registry cannot be read: {error}") from error
    version = document.get("schema_version")
    entries = document.get("entries")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("dependency registry entries must be a list of objects")
    if version in {1, 2}:
        legacy_attempts = document.get("attempts", []) if version == 2 else []
        if not isinstance(legacy_attempts, list) or not all(
            isinstance(attempt, dict) for attempt in legacy_attempts
        ):
            raise ValueError("dependency registry attempts must be a list of objects")
        return {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "memory_revision": 0,
            "updated_at": document.get("updated_at"),
            "entries": [legacy_dependency(entry) for entry in entries],
            "attempts": legacy_attempts,
            "environment_profile": document.get("environment_profile"),
            "domain_memory": document.get("domain_memory"),
        }
    if version == 3:
        attempts = document.get("attempts", [])
        if not isinstance(attempts, list) or not all(isinstance(attempt, dict) for attempt in attempts):
            raise ValueError("dependency registry attempts must be a list of objects")
        memory_revision = document.get("memory_revision", 0)
        if not isinstance(memory_revision, int) or memory_revision < 0:
            raise ValueError("project memory revision must be a non-negative integer")
        return {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "memory_revision": memory_revision,
            "updated_at": document.get("updated_at"),
            "entries": [legacy_dependency(entry) for entry in entries],
            "attempts": attempts,
            "environment_profile": document.get("environment_profile"),
            "domain_memory": document.get("domain_memory"),
        }
    if version != REGISTRY_SCHEMA_VERSION:
        raise ValueError("unsupported dependency registry schema version")
    attempts = document.get("attempts", [])
    if not isinstance(attempts, list) or not all(isinstance(attempt, dict) for attempt in attempts):
        raise ValueError("dependency registry attempts must be a list of objects")
    document.setdefault("updated_at", None)
    memory_revision = document.get("memory_revision", 0)
    if not isinstance(memory_revision, int) or memory_revision < 0:
        raise ValueError("project memory revision must be a non-negative integer")
    document["memory_revision"] = memory_revision
    document.setdefault("attempts", [])
    document["entries"] = [legacy_dependency(entry) for entry in entries]
    environment_profile = document.get("environment_profile")
    if environment_profile is not None and not isinstance(environment_profile, dict):
        raise ValueError("environment profile must be an object or null")
    domain_memory = document.get("domain_memory")
    if domain_memory is not None and not isinstance(domain_memory, dict):
        raise ValueError("domain memory must be an object or null")
    document.setdefault("environment_profile", None)
    document.setdefault("domain_memory", None)
    return document


def write(path: pathlib.Path, document: dict[str, Any], *, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(".bak"))
    temporary.replace(path)
    try:
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        pass


def write_text(path: pathlib.Path, value: str, *, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    temporary.replace(path)
    try:
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        pass


def restore_bytes(path: pathlib.Path, value: bytes | None) -> None:
    if value is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".restore.tmp")
    temporary.write_bytes(value)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(path)


@contextlib.contextmanager
def registry_lock(path: pathlib.Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_registry(
    repo: pathlib.Path,
    document: dict[str, Any],
    *,
    expected_revision: int,
    projection_writes: dict[pathlib.Path, str] | None = None,
) -> int:
    path = registry_path(repo)
    with registry_lock(path):
        current = load(path)
        current_revision = int(current.get("memory_revision", 0))
        if current_revision != expected_revision:
            raise ValueError(
                f"project memory revision conflict: expected {current_revision}, received {expected_revision}"
            )
        next_revision = current_revision + 1
        document["schema_version"] = REGISTRY_SCHEMA_VERSION
        document["memory_revision"] = next_revision
        projections = projection_writes or {}
        previous = {
            candidate: candidate.read_bytes() if candidate.exists() else None
            for candidate in (path, *projections)
        }
        try:
            write(path, document, backup=True)
            for projection_path, projection in projections.items():
                write_text(projection_path, projection, backup=True)
            try:
                readback = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError(f"project memory readback failed: {error}") from error
            if json.dumps(readback, ensure_ascii=False, sort_keys=True) != json.dumps(
                document, ensure_ascii=False, sort_keys=True,
            ):
                raise ValueError("project memory readback differs from the requested registry")
            for projection_path, projection in projections.items():
                if projection_path.read_text(encoding="utf-8") != projection:
                    raise ValueError(f"project memory projection readback differs: {projection_path.name}")
        except Exception:
            for candidate, value in previous.items():
                restore_bytes(candidate, value)
            raise
        return next_revision


def snapshot(entry: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(entry))
    result.pop("revisions", None)
    return result


def find_entry(document: dict[str, Any], entry_id: str) -> tuple[int, dict[str, Any]] | tuple[None, None]:
    for index, entry in enumerate(document["entries"]):
        if entry.get("id") == entry_id:
            return index, entry
    return None, None


def upsert(document: dict[str, Any], entry: dict[str, Any]) -> None:
    index, previous = find_entry(document, entry["id"])
    if previous is None:
        entry.setdefault("revisions", [])
        document["entries"].append(entry)
        return
    revisions = list(previous.get("revisions", []))
    revisions.append({"at": now(), "entry": snapshot(previous)})
    entry["revisions"] = revisions
    document["entries"][index] = entry
