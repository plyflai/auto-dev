"""Request-scoped evaluation and disposable runtime fingerprint caching."""

from __future__ import annotations

import contextlib
import contextvars
import copy
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows does not provide fcntl.
    fcntl = None  # type: ignore[assignment]


CACHE_SCHEMA_VERSION = 1
MAX_FINGERPRINT_ENTRIES = 50000
_CURRENT: contextvars.ContextVar["EvaluationContext | None"] = contextvars.ContextVar(
    "auto_dev_evaluation", default=None
)


def runtime_cache_root() -> pathlib.Path:
    configured = os.environ.get("AUTO_DEV_RUNTIME_CACHE_ROOT")
    if configured:
        return pathlib.Path(configured).expanduser().resolve()
    plugin_data = os.environ.get("PLUGIN_DATA")
    if plugin_data:
        return pathlib.Path(plugin_data).expanduser().resolve() / "runtime-cache"
    return pathlib.Path(tempfile.gettempdir()).resolve() / "auto-dev-runtime-cache"


def repo_cache_key(repo: pathlib.Path) -> str:
    return hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:24]


def _stat_signature(path: pathlib.Path, *, follow_symlinks: bool = True) -> list[int]:
    stat = path.stat() if follow_symlinks else path.lstat()
    return [
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_mode),
        int(stat.st_size),
        int(stat.st_mtime_ns),
        int(stat.st_ctime_ns),
    ]


@dataclass
class EvaluationContext:
    repo: pathlib.Path
    command_cache: dict[tuple[str, tuple[str, ...]], subprocess.CompletedProcess[str]] = field(
        default_factory=dict
    )
    json_cache: dict[pathlib.Path, Any] = field(default_factory=dict)
    scope_manifest_cache: dict[tuple[str, ...], dict[str, str]] = field(default_factory=dict)
    scope_root_cache: dict[str, dict[str, str]] = field(default_factory=dict)
    scope_digest_cache: dict[tuple[str, ...], str] = field(default_factory=dict)
    proof_freshness_cache: dict[tuple[Any, ...], bool] = field(default_factory=dict)
    value_cache: dict[tuple[Any, ...], Any] = field(default_factory=dict)
    _fingerprints: dict[str, dict[str, Any]] = field(default_factory=dict)
    _fingerprint_updates: set[str] = field(default_factory=set)
    _fingerprints_dirty: bool = False
    _lock_handle: Any = None
    digest_reads: int = 0
    digest_hits: int = 0

    def __post_init__(self) -> None:
        self.repo = self.repo.resolve()
        key = repo_cache_key(self.repo)
        root = runtime_cache_root()
        self.cache_path = root / "fingerprints" / f"{key}.json"
        self.lock_path = root / "locks" / f"{key}.lock"

    def __enter__(self) -> "EvaluationContext":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_handle = self.lock_path.open("a+", encoding="utf-8")
        if fcntl is not None:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_SH)
        try:
            self._fingerprints = self._read_persistent_entries()
        finally:
            if fcntl is not None:
                fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
        return self

    def _read_persistent_entries(self) -> dict[str, dict[str, Any]]:
        try:
            document = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if (
            isinstance(document, dict)
            and document.get("schema_version") == CACHE_SCHEMA_VERSION
            and document.get("repo") == str(self.repo)
            and isinstance(document.get("entries"), dict)
        ):
            return {
                str(path): value
                for path, value in document["entries"].items()
                if isinstance(value, dict)
            }
        return {}

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if self._fingerprints_dirty:
                if fcntl is not None:
                    fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX)
                entries = self._read_persistent_entries()
                for path in self._fingerprint_updates:
                    value = self._fingerprints.get(path)
                    if isinstance(value, dict):
                        entries[path] = value
                if len(entries) > MAX_FINGERPRINT_ENTRIES:
                    entries = dict(list(entries.items())[-MAX_FINGERPRINT_ENTRIES:])
                payload = {
                    "schema_version": CACHE_SCHEMA_VERSION,
                    "repo": str(self.repo),
                    "entries": entries,
                }
                temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(self.cache_path)
        finally:
            if self._lock_handle is not None:
                if fcntl is not None:
                    fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
                self._lock_handle.close()
                self._lock_handle = None

    def run(
        self,
        command: list[str],
        cwd: pathlib.Path,
        check: bool,
        runner: Callable[[], subprocess.CompletedProcess[str]],
    ) -> subprocess.CompletedProcess[str]:
        key = (str(cwd.resolve()), tuple(command))
        completed = self.command_cache.get(key)
        if completed is None:
            completed = runner()
            self.command_cache[key] = completed
        if check and completed.returncode != 0:
            raise subprocess.CalledProcessError(
                completed.returncode,
                command,
                output=completed.stdout,
                stderr=completed.stderr,
            )
        return completed

    def read_json(self, path: pathlib.Path) -> Any:
        resolved = path.resolve()
        if resolved not in self.json_cache:
            self.json_cache[resolved] = json.loads(resolved.read_text(encoding="utf-8"))
        return copy.deepcopy(self.json_cache[resolved])

    def file_digest(self, path: pathlib.Path, *, follow_symlinks: bool = True) -> str:
        resolved = path.resolve() if follow_symlinks else path.absolute()
        signature = _stat_signature(path, follow_symlinks=follow_symlinks)
        cache_key = str(resolved)
        cached = self._fingerprints.get(cache_key)
        if isinstance(cached, dict) and cached.get("stat") == signature:
            digest = cached.get("sha256")
            if isinstance(digest, str):
                self.digest_hits += 1
                return digest
        self.digest_reads += 1
        digest_state = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest_state.update(chunk)
        digest = digest_state.hexdigest()
        self._fingerprints[cache_key] = {"stat": signature, "sha256": digest}
        self._fingerprint_updates.add(cache_key)
        self._fingerprints_dirty = True
        return digest


def current_evaluation(repo: pathlib.Path | None = None) -> EvaluationContext | None:
    current = _CURRENT.get()
    if current is None:
        return None
    if repo is not None and current.repo != repo.resolve():
        return None
    return current


@contextlib.contextmanager
def evaluation_scope(repo: pathlib.Path) -> Iterator[EvaluationContext]:
    existing = current_evaluation(repo)
    if existing is not None:
        yield existing
        return
    context = EvaluationContext(repo)
    token = _CURRENT.set(context)
    try:
        with context:
            yield context
    finally:
        _CURRENT.reset(token)
