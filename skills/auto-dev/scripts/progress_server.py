#!/usr/bin/env python3
"""Serve the auto-dev continuity state as a small local, read-only progress view.

Usage:
  python3 auto_dev.py progress --repo-root /path/to/repo --port 0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import project_memory
import runctl
from plugin_identity import auto_dev_plugin_version
from auto_dev_internal.foundation.progress import ProgressSnapshotStore, monitor_ready_file


PAGE_PATH = pathlib.Path(__file__).with_name("progress_page.html")
PAGE = PAGE_PATH.read_text(encoding="utf-8")


def repo_fingerprint(repo: pathlib.Path) -> str:
    return hashlib.sha256(str(repo).encode("utf-8")).hexdigest()[:16]


def write_ready_file(
    path: pathlib.Path,
    *,
    repo: pathlib.Path,
    url: str,
    port: int,
    generation: str,
    bundle_version: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": url,
        "port": port,
        "pid": os.getpid(),
        "repo": str(repo),
        "repo_fingerprint": repo_fingerprint(repo),
        "generation": generation,
        "bundle_version": bundle_version,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def dependency_projection(repo: pathlib.Path) -> dict[str, object]:
    """Build a bounded, presentation-safe view of the existing dependency ledger."""
    empty: dict[str, object] = {"status": "ready", "trusted": [], "leases": [], "timeline": []}
    try:
        document = project_memory.load(project_memory.registry_path(repo))
        leases = project_memory.lease_items(project_memory.load_lease(repo))
    except (OSError, ValueError):
        return {**empty, "status": "unavailable"}

    lease_counts: dict[str, int] = {}
    lease_view = []
    for lease in leases:
        dependency_id = lease.get("dependency_id")
        if not isinstance(dependency_id, str):
            continue
        lease_counts[dependency_id] = lease_counts.get(dependency_id, 0) + 1
        lease_view.append({
            "dependency_id": dependency_id,
            "capability": lease.get("capability"),
            "scope": lease.get("scope"),
            "version": lease.get("version"),
            "validated_at": lease.get("validated_at") or lease.get("created_at"),
        })

    trusted = []
    timeline = []
    names: dict[str, str] = {}
    current = datetime.now().astimezone()
    for entry in document.get("entries", []):
        if not isinstance(entry, dict) or entry.get("kind") != "dependency":
            continue
        dependency_id = entry.get("id")
        if not isinstance(dependency_id, str):
            continue
        name = entry.get("name") if isinstance(entry.get("name"), str) else dependency_id
        names[dependency_id] = name
        if (
            entry.get("status") == "known-good"
            and entry.get("role") in {"preferred", "fallback"}
            and not project_memory.review_reasons(entry, current)
        ):
            trusted.append({
                "id": dependency_id,
                "name": name,
                "version": entry.get("version"),
                "capabilities": entry.get("capabilities", []),
                "scope": entry.get("scope", []),
                "role": entry.get("role"),
                "last_checked_at": entry.get("last_checked_at"),
                "updated_at": entry.get("updated_at"),
                "active_lease_count": lease_counts.get(dependency_id, 0),
            })
        if entry.get("updated_at"):
            timeline.append({
                "type": "record",
                "at": entry.get("updated_at"),
                "dependency_id": dependency_id,
                "name": name,
                "status": entry.get("status"),
                "role": entry.get("role"),
                "version": entry.get("version"),
            })
        for revision in entry.get("revisions", []):
            if not isinstance(revision, dict) or not revision.get("at"):
                continue
            previous = revision.get("entry") if isinstance(revision.get("entry"), dict) else {}
            timeline.append({
                "type": "revision",
                "at": revision.get("at"),
                "dependency_id": dependency_id,
                "name": previous.get("name") or name,
                "status": previous.get("status"),
                "role": previous.get("role"),
                "version": previous.get("version"),
            })
    for attempt in document.get("attempts", []):
        if not isinstance(attempt, dict) or not attempt.get("at"):
            continue
        dependency_id = attempt.get("dependency_id")
        if not isinstance(dependency_id, str):
            continue
        timeline.append({
            "type": "attempt",
            "at": attempt.get("at"),
            "dependency_id": dependency_id,
            "name": names.get(dependency_id, dependency_id),
            "result": attempt.get("result"),
            "classification": attempt.get("classification"),
            "version": attempt.get("version"),
        })

    trusted_ids = {item["id"] for item in trusted}
    lease_view = [lease for lease in lease_view if lease["dependency_id"] in trusted_ids]
    trusted.sort(key=lambda item: (item["role"] != "preferred", item["name"].casefold()))
    timeline.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
    return {
        "status": "ready",
        "updated_at": document.get("updated_at"),
        "trusted": trusted[:24],
        "leases": lease_view[:24],
        "timeline": timeline[:30],
    }


def progress_payload(
    repo: pathlib.Path,
    *,
    session_key: str | None = None,
    project_context_id: str | None = None,
) -> dict[str, object]:
    payload = runctl.build_status_payload(
        repo,
        runctl.paths(repo),
        view="compact",
        session_key=session_key,
        project_context_id=project_context_id,
        profile="progress",
    )
    payload["dependencies"] = dependency_projection(repo)
    transition_path = runctl.paths(repo)["last_transition"]
    if transition_path.is_file():
        try:
            payload["last_transition"] = runctl.read_json(transition_path)
        except (OSError, ValueError, json.JSONDecodeError):
            payload["last_transition"] = {"status": "unavailable"}
    return payload


def json_response(handler: BaseHTTPRequestHandler, payload: object, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def state_fingerprint(repo: pathlib.Path, *, session_key: str | None = None) -> str:
    with runctl.evaluation_scope(repo):
        active = repo / ".auto-dev" / "active.json"
        project = repo / ".auto-dev" / "project.json"
        if not active.exists() and not project.exists():
            return "idle"
        parts = [runctl.current_branch(repo) or "detached"]
        state = runctl.paths(repo)
        watched = [
            project,
            active,
            state["project_memory"],
            state["dependency_lease"],
            state["last_transition"],
        ]
        if session_key:
            try:
                watched.extend([runctl.intake_gate_path(state, session_key), runctl.view_focus_path(state, session_key)])
            except ValueError:
                pass
        for path in watched:
            if path.exists():
                stat = path.stat()
                parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
        try:
            project_state = runctl.load_project(state, repo)
            _, _, key = runctl.current_context(repo)
            task_id = (project_state or {}).get("branches", {}).get(key, {}).get("active_task_id")
            selected = runctl.task_path(state, str(task_id)) if task_id else None
            if selected and selected.exists():
                stat = selected.stat()
                parts.append(f"task:{stat.st_mtime_ns}:{stat.st_size}")
        except (OSError, ValueError):
            pass
        return "|".join(parts)


def quick_status_identity(repo: pathlib.Path) -> dict[str, object]:
    try:
        identity = runctl.build_status_identity(repo, runctl.paths(repo))
    except (OSError, ValueError):
        return {"task_id": None, "state_revision": 0}
    return {
        "task_id": identity.get("id"),
        "state_revision": identity.get("state_revision", 0),
    }


class AutoDevProgressServer(ThreadingHTTPServer):
    daemon_threads = True


class ProgressHandler(BaseHTTPRequestHandler):
    server_version = "AutoDevProgress/3"

    def log_message(self, format: str, *args: object) -> None:
        return

    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            return

    @property
    def repo(self) -> pathlib.Path:
        return self.server.repo  # type: ignore[attr-defined]

    @property
    def snapshots(self) -> ProgressSnapshotStore:
        return self.server.snapshots  # type: ignore[attr-defined]

    def session_key(self) -> str | None:
        values = parse_qs(urlsplit(self.path).query).get("session_key", [])
        if len(values) != 1:
            return None
        try:
            return runctl.require_session_key(values[0])
        except ValueError:
            return None

    def project_context_id(self) -> str | None:
        values = parse_qs(urlsplit(self.path).query).get("project_context", [])
        if len(values) != 1:
            return None
        try:
            return runctl.require_control_id("project context id", values[0])
        except ValueError:
            return None

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        session_key = self.session_key()
        project_context_id = self.project_context_id()
        if path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/health":
            identity = self.snapshots.health_identity()
            json_response(self, {
                "status": "ok",
                "task_id": identity.get("task_id"),
                "state_revision": identity.get("state_revision", 0),
                "repo_fingerprint": repo_fingerprint(self.repo),
                "generation": self.server.generation,  # type: ignore[attr-defined]
                "bundle_version": self.server.bundle_version,  # type: ignore[attr-defined]
            })
            return
        if path == "/api/state":
            snapshot = self.snapshots.snapshot(
                session_key=session_key,
                project_context_id=project_context_id,
            )
            body = snapshot.json_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_version = -1
            last_heartbeat = time.monotonic()
            try:
                while True:
                    snapshot = self.snapshots.snapshot(
                        session_key=session_key,
                        project_context_id=project_context_id,
                    )
                    if snapshot.version != last_version:
                        self.wfile.write(f"data: {snapshot.json_text}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        last_version = snapshot.version
                        last_heartbeat = time.monotonic()
                    elif time.monotonic() - last_heartbeat >= 15:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        last_heartbeat = time.monotonic()
                    time.sleep(0.5)
            except (BrokenPipeError, ConnectionResetError):
                return
            return
        json_response(self, {"error": "not found"}, 404)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, prog=os.environ.get("AUTO_DEV_CLI_PROG"))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="TCP port; 0 selects an available local port")
    parser.add_argument("--ready-file", help=argparse.SUPPRESS)
    parser.add_argument("--generation", help=argparse.SUPPRESS)
    args = parser.parse_args()
    repo = runctl.resolve_repo(args.repo_root)
    bundle_version = auto_dev_plugin_version(pathlib.Path(__file__))
    if not bundle_version:
        print("auto-dev progress: package version is unavailable", file=sys.stderr, flush=True)
        return 2
    generation = args.generation or hashlib.sha256(
        f"{os.getpid()}\0{time.time_ns()}".encode("utf-8")
    ).hexdigest()[:32]
    server = AutoDevProgressServer((args.host, args.port), ProgressHandler)
    server.repo = repo  # type: ignore[attr-defined]
    server.generation = generation  # type: ignore[attr-defined]
    server.bundle_version = bundle_version  # type: ignore[attr-defined]
    server.snapshots = ProgressSnapshotStore(  # type: ignore[attr-defined]
        fingerprint=lambda session_key: state_fingerprint(repo, session_key=session_key),
        payload=lambda session_key, project_context_id: progress_payload(
            repo,
            session_key=session_key,
            project_context_id=project_context_id,
        ),
        identity=lambda: quick_status_identity(repo),
    )
    url = f"http://{args.host}:{server.server_port}/"
    if args.ready_file:
        try:
            ready_path = pathlib.Path(args.ready_file).expanduser().resolve()
            write_ready_file(
                ready_path,
                repo=repo,
                url=url,
                port=server.server_port,
                generation=generation,
                bundle_version=bundle_version,
            )
            monitor_ready_file(server, ready_path, generation)
        except OSError as error:
            print(f"auto-dev progress: failed to publish ready file: {error}", file=sys.stderr, flush=True)
    print(f"auto-dev progress: {url} (repo {repo})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
