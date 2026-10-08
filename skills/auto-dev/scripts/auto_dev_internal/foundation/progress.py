"""Single-producer snapshots and lease fencing for the progress service."""

from __future__ import annotations

import json
import pathlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ProgressSnapshot:
    payload: dict[str, object]
    json_text: str
    version: int


@dataclass
class _SnapshotEntry:
    fingerprint: str | None = None
    snapshot: ProgressSnapshot | None = None
    last_checked: float = 0.0
    last_built: float = 0.0
    computing: bool = False


class ProgressSnapshotStore:
    """Coalesce status work across HTTP requests and connected SSE clients."""

    def __init__(
        self,
        *,
        fingerprint: Callable[[str | None], str],
        payload: Callable[[str | None, str | None], dict[str, object]],
        identity: Callable[[], dict[str, object]],
        check_interval: float = 0.5,
        refresh_interval: float = 60.0,
    ) -> None:
        self._fingerprint = fingerprint
        self._payload = payload
        self._identity = identity
        self._check_interval = check_interval
        self._refresh_interval = refresh_interval
        self._condition = threading.Condition()
        self._entries: dict[tuple[str | None, str | None], _SnapshotEntry] = {}
        self._version = 0

    def snapshot(
        self,
        *,
        session_key: str | None,
        project_context_id: str | None,
        force: bool = False,
    ) -> ProgressSnapshot:
        key = (session_key, project_context_id)
        while True:
            now = time.monotonic()
            with self._condition:
                entry = self._entries.setdefault(key, _SnapshotEntry())
                if (
                    not force
                    and entry.snapshot is not None
                    and now - entry.last_checked < self._check_interval
                ):
                    return entry.snapshot
                if entry.computing:
                    self._condition.wait(timeout=self._check_interval)
                    continue
                entry.computing = True
                break

        try:
            current = self._fingerprint(session_key)
            rebuilt = False
            if (
                entry.snapshot is None
                or current != entry.fingerprint
                or time.monotonic() - entry.last_built >= self._refresh_interval
            ):
                payload = self._payload(session_key, project_context_id)
                json_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                with self._condition:
                    self._version += 1
                    snapshot = ProgressSnapshot(payload, json_text, self._version)
                    rebuilt = True
            else:
                snapshot = entry.snapshot
        finally:
            with self._condition:
                entry.computing = False
                self._condition.notify_all()

        with self._condition:
            entry.fingerprint = current
            entry.snapshot = snapshot
            entry.last_checked = time.monotonic()
            if rebuilt:
                entry.last_built = entry.last_checked
            return snapshot

    def health_identity(self) -> dict[str, object]:
        with self._condition:
            snapshots = [
                entry.snapshot
                for entry in self._entries.values()
                if entry.snapshot is not None
            ]
        if snapshots:
            latest = max(snapshots, key=lambda item: item.version)
            return {
                "task_id": latest.payload.get("id"),
                "state_revision": latest.payload.get("state_revision", 0),
            }
        return self._identity()


def monitor_ready_file(
    server,
    ready_file: pathlib.Path,
    generation: str,
    *,
    interval: float = 1.0,
) -> threading.Thread:
    """Stop a superseded server after another generation owns its ready record."""

    def monitor() -> None:
        while True:
            time.sleep(interval)
            try:
                record = json.loads(ready_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            current = record.get("generation") if isinstance(record, dict) else None
            if isinstance(current, str) and current != generation:
                server.shutdown()
                return

    thread = threading.Thread(target=monitor, name="auto-dev-progress-lease", daemon=True)
    thread.start()
    return thread
