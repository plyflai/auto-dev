"""Disposable session activation state for Auto Dev lifecycle hooks."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows does not provide fcntl.
    fcntl = None  # type: ignore[assignment]


SESSION_ACTIVATION_SCHEMA_VERSION = 1
WRITER_LEASE_SCHEMA_VERSION = 1
WRITER_LEASE_STALE_SECONDS = 5 * 60
# PreToolUse has no reliable completion callback in this host. Keep the
# contention fence short; the project CLI's revision/CAS remains authoritative.
WRITER_LEASE_INFLIGHT_SECONDS = 5


def activation_path(root: Path, event: dict[str, Any]) -> Path | None:
    data_root = os.environ.get("PLUGIN_DATA")
    session_id = event.get("session_id")
    if not data_root or not isinstance(session_id, str) or not session_id:
        return None
    resolved_root = root.expanduser().resolve()
    digest = hashlib.sha256(f"{session_id}\0{resolved_root}".encode("utf-8")).hexdigest()[:24]
    return Path(data_root).expanduser().resolve() / "session-activations" / f"{digest}.json"


def session_is_active(root: Path, event: dict[str, Any]) -> bool:
    path = activation_path(root, event)
    if path is None or not path.is_file():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(value, dict)
        and value.get("schema_version") == SESSION_ACTIVATION_SCHEMA_VERSION
        and value.get("active") is True
    )


def activate_session(
    root: Path,
    event: dict[str, Any],
    *,
    source: str = "explicit_user_reference",
) -> bool:
    path = activation_path(root, event)
    if path is None:
        return False
    value = {
        "schema_version": SESSION_ACTIVATION_SCHEMA_VERSION,
        "active": True,
        "source": source,
        "activated_at": int(time.time()),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError:
        return False
    return True


def _data_root() -> Path | None:
    value = os.environ.get("PLUGIN_DATA")
    return Path(value).expanduser().resolve() if value else None


def session_fingerprint(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]


def writer_lease_path(root: Path, branch_key: str) -> Path | None:
    data_root = _data_root()
    if data_root is None:
        return None
    resolved_root = root.expanduser().resolve()
    digest = hashlib.sha256(f"{resolved_root}\0{branch_key}".encode("utf-8")).hexdigest()[:24]
    return data_root / "session-writer-leases" / f"{digest}.json"


@contextlib.contextmanager
def writer_lease_lock(path: Path):
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


def _read_writer_lease(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != WRITER_LEASE_SCHEMA_VERSION:
        return None
    return value


def _write_writer_lease(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _lease_owner(event: dict[str, Any]) -> str | None:
    session_id = event.get("session_id")
    return session_fingerprint(session_id) if isinstance(session_id, str) and session_id else None


def _lease_expired(lease: dict[str, Any], now: int) -> bool:
    expires_at = lease.get("expires_at")
    return not isinstance(expires_at, int) or expires_at <= now


def _superseded_sessions(lease: dict[str, Any]) -> list[str]:
    values = lease.get("superseded_sessions")
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str) and value]


def writer_lease_status(
    root: Path,
    event: dict[str, Any],
    *,
    branch_key: str,
    now: int | None = None,
) -> dict[str, Any]:
    current_time = int(time.time()) if now is None else now
    path = writer_lease_path(root, branch_key)
    lease = _read_writer_lease(path)
    if lease is None or _lease_expired(lease, current_time):
        return {"status": "available"}
    owner = _lease_owner(event)
    if owner and lease.get("owner_session") == owner:
        return {"status": "owned", "lease": lease}
    if owner and owner in _superseded_sessions(lease):
        return {"status": "observer", "lease": lease}
    return {"status": "held", "lease": lease}


def touch_writer_lease(
    root: Path,
    event: dict[str, Any],
    *,
    branch_key: str,
    task_id: str | None,
    state_revision: int | None,
    now: int | None = None,
) -> dict[str, Any]:
    """Refresh only the current owner; a new session never steals at startup."""
    current_time = int(time.time()) if now is None else now
    path = writer_lease_path(root, branch_key)
    owner = _lease_owner(event)
    if path is None or owner is None:
        return {"status": "unavailable"}
    try:
        with writer_lease_lock(path):
            lease = _read_writer_lease(path)
            if lease is None or _lease_expired(lease, current_time):
                return {"status": "available"}
            if lease.get("owner_session") != owner:
                return writer_lease_status(root, event, branch_key=branch_key, now=current_time)
            lease.update({
                "task_id": task_id,
                "state_revision": state_revision,
                "last_activity_at": current_time,
                "expires_at": current_time + WRITER_LEASE_STALE_SECONDS,
                "inflight_until": 0,
            })
            _write_writer_lease(path, lease)
            return {"status": "owned", "lease": lease}
    except OSError:
        return {"status": "unavailable"}


def claim_writer_lease(
    root: Path,
    event: dict[str, Any],
    *,
    branch_key: str,
    task_id: str | None,
    state_revision: int | None,
    mutation: bool,
    now: int | None = None,
) -> dict[str, Any]:
    """Acquire or renew the single local writer lease for a project branch."""
    current_time = int(time.time()) if now is None else now
    path = writer_lease_path(root, branch_key)
    owner = _lease_owner(event)
    if path is None or owner is None:
        return {"status": "unavailable"}
    try:
        with writer_lease_lock(path):
            current = _read_writer_lease(path)
            if current is not None and not _lease_expired(current, current_time):
                current_owner = current.get("owner_session")
                if current_owner == owner:
                    current.update({
                        "task_id": task_id,
                        "state_revision": state_revision,
                        "last_activity_at": current_time,
                        "expires_at": current_time + WRITER_LEASE_STALE_SECONDS,
                        "inflight_until": (
                            current_time + WRITER_LEASE_INFLIGHT_SECONDS if mutation else 0
                        ),
                    })
                    _write_writer_lease(path, current)
                    return {"status": "owned", "lease": current}
                if owner in _superseded_sessions(current):
                    return {"status": "observer", "lease": current}
                inflight_until = current.get("inflight_until", 0)
                if isinstance(inflight_until, int) and inflight_until > current_time:
                    return {"status": "conflict", "lease": current}
                superseded = _superseded_sessions(current)
                if isinstance(current_owner, str) and current_owner not in superseded:
                    superseded.append(current_owner)
                status = "taken_over"
            else:
                superseded = _superseded_sessions(current) if current is not None else []
                if current is not None:
                    previous_owner = current.get("owner_session")
                    if isinstance(previous_owner, str) and previous_owner not in superseded:
                        superseded.append(previous_owner)
                status = "acquired"
            lease = {
                "schema_version": WRITER_LEASE_SCHEMA_VERSION,
                "owner_session": owner,
                "branch_key": branch_key,
                "task_id": task_id,
                "state_revision": state_revision,
                "lease_id": secrets.token_hex(12),
                "acquired_at": current_time,
                "last_activity_at": current_time,
                "expires_at": current_time + WRITER_LEASE_STALE_SECONDS,
                "inflight_until": (
                    current_time + WRITER_LEASE_INFLIGHT_SECONDS if mutation else 0
                ),
                "superseded_sessions": superseded[-8:],
            }
            _write_writer_lease(path, lease)
            return {"status": status, "lease": lease}
    except OSError:
        return {"status": "unavailable"}
