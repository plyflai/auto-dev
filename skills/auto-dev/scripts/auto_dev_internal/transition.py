"""Atomic execution-focus transitions built from existing Auto Dev commands."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import pathlib
import shutil
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class TransitionRoute:
    identifier: str
    source_statuses: frozenset[str | None]
    source_action: str
    proof_policy: str


TRANSITION_REGISTRY = {
    "start-new": TransitionRoute(
        "start-new", frozenset({None}), "keep", "target-only"
    ),
    "switch-passed": TransitionRoute(
        "switch-passed", frozenset({"review_ready"}), "pass", "strict-completion"
    ),
    "switch-superseded": TransitionRoute(
        "switch-superseded",
        frozenset({"active", "review_ready", "paused", "blocked"}),
        "supersede",
        "target-only",
    ),
}

CONTROL_BACKUP_DIRS = ("projects", "tasks", "runs", "intake-gates")
CONTROL_BACKUP_FILES = (
    "active.json",
    "active.bak",
    "project.json",
    "project.bak",
    "history.jsonl",
    "last-transition.json",
)
FINGERPRINT_FILES = tuple(name for name in CONTROL_BACKUP_FILES if name != "last-transition.json")


def _object(label: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _list(label: str, value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _strings(label: str, value: Any) -> list[str]:
    result = _list(label, value)
    if not all(isinstance(item, str) and item.strip() for item in result):
        raise ValueError(f"{label} must contain non-empty strings")
    return [item.strip() for item in result]


def _load_spec(control, args: argparse.Namespace) -> dict[str, Any]:
    if args.spec_json:
        raw = control.decode_json_object("transition spec", args.spec_json)
    else:
        path = pathlib.Path(args.spec_file).expanduser().resolve()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"transition spec is unreadable: {path}") from error
    spec = _object("transition spec", raw)
    allowed = {"request_id", "route", "expected", "confirmation_source", "target"}
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValueError("transition spec has unsupported fields: " + ", ".join(unknown))
    return spec


def _request_key(control, value: Any) -> str:
    raw = control.require_concrete("transition request id", str(value or ""))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _transition_backup(root: pathlib.Path) -> tuple[tempfile.TemporaryDirectory[str], pathlib.Path, set[str]]:
    temporary = tempfile.TemporaryDirectory(prefix="auto-dev-transition-")
    backup = pathlib.Path(temporary.name) / "control"
    backup.mkdir()
    for name in CONTROL_BACKUP_FILES:
        source = root / name
        if source.is_file():
            destination = backup / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    for name in CONTROL_BACKUP_DIRS:
        source = root / name
        if source.is_dir():
            shutil.copytree(source, backup / name)
    snapshots = root / "snapshots"
    snapshot_names = {path.name for path in snapshots.iterdir()} if snapshots.is_dir() else set()
    return temporary, backup, snapshot_names


def _restore_transition(root: pathlib.Path, backup: pathlib.Path, snapshot_names: set[str]) -> None:
    for name in CONTROL_BACKUP_FILES:
        destination = root / name
        source = backup / name
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        else:
            destination.unlink(missing_ok=True)
    for name in CONTROL_BACKUP_DIRS:
        destination = root / name
        source = backup / name
        if destination.exists():
            shutil.rmtree(destination)
        if source.is_dir():
            shutil.copytree(source, destination)
    snapshots = root / "snapshots"
    if snapshots.is_dir():
        for path in snapshots.iterdir():
            if path.name not in snapshot_names:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)


def _control_fingerprint(root: pathlib.Path) -> str:
    digest = hashlib.sha256()
    candidates: list[pathlib.Path] = []
    for name in FINGERPRINT_FILES:
        path = root / name
        if path.is_file():
            candidates.append(path)
    for name in CONTROL_BACKUP_DIRS:
        path = root / name
        if path.is_dir():
            candidates.extend(item for item in path.rglob("*") if item.is_file())
    for path in sorted(candidates, key=lambda value: value.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _run_existing(control, arguments: list[str]) -> dict[str, Any]:
    parser = control.build_parser()
    try:
        namespace = parser.parse_args(arguments)
    except SystemExit as error:
        raise ValueError(
            "transition subcommand arguments are invalid: " + " ".join(arguments[:2])
        ) from error
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = namespace.handler(namespace)
    if code not in (None, 0):
        raise ValueError(f"transition subcommand failed with exit code {code}")
    lines = [line for line in output.getvalue().splitlines() if line.strip()]
    if not lines:
        return {}
    try:
        value = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise ValueError("transition subcommand returned non-JSON output") from error
    return value if isinstance(value, dict) else {}


def _progress_url(repo: pathlib.Path) -> str | None:
    plugin_root = pathlib.Path(__file__).resolve().parents[4]
    hook_root = plugin_root / "scripts"
    if str(hook_root) not in sys.path:
        sys.path.insert(0, str(hook_root))
    try:
        import hook_dispatch

        cli = plugin_root / "skills" / "auto-dev" / "scripts" / "auto_dev.py"
        return hook_dispatch.ensure_progress_server(repo, cli=cli)
    except (ImportError, OSError, ValueError):
        return None


def _progress_state(url: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not url:
        return None, None
    try:
        with urllib.request.urlopen(url + "api/health", timeout=2) as response:
            health = json.loads(response.read().decode("utf-8"))
        with urllib.request.urlopen(url + "api/state", timeout=2) as response:
            state = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None, None
    return health, state


def _verify_progress(url: str | None, task_id: str) -> bool:
    if not url:
        return False
    # The progress server may briefly cache the task active before this transition.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        health, state = _progress_state(url)
        if health and state and health.get("status") == "ok" and state.get("id") == task_id:
            return True
        time.sleep(0.05)
    return False


def _verify_ready_transition(url: str | None, task_id: str, request_id: str) -> bool:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        health, state = _progress_state(url)
        transition = state.get("last_transition") if isinstance(state, dict) else None
        if (
            health
            and state
            and health.get("status") == "ok"
            and state.get("id") == task_id
            and isinstance(transition, dict)
            and transition.get("request_id") == request_id
            and transition.get("status") == "ready"
        ):
            return True
        time.sleep(0.05)
    return False


def _write_transition(control, state: dict[str, pathlib.Path], payload: dict[str, Any]) -> None:
    control.write_json(state["last_transition"], payload, backup=True)


def _completed_transition(control, repo: pathlib.Path, state: dict[str, pathlib.Path], request_id: str) -> dict[str, Any] | None:
    path = state["last_transition"]
    if not path.is_file():
        return None
    try:
        record = control.read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    task_id = record.get("task_id")
    if (
        record.get("request_id") != request_id
        or record.get("status") != "ready"
        or not isinstance(task_id, str)
    ):
        return None
    readback = control.build_status_payload(repo, state, view="compact")
    if readback.get("id") != task_id or readback.get("continuity_status") != "ready":
        return None
    url = record.get("control_plane_url")
    if not isinstance(url, str) or not _verify_ready_transition(url, task_id, request_id):
        return None
    return record


def _expected_state(control, repo: pathlib.Path, state: dict[str, pathlib.Path], spec: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    current, resolution = control.resolve_branch_task(repo, state)
    expected = _object("transition expected", spec.get("expected") or {})
    project = control.load_project(state, repo)
    if project is None:
        raise ValueError("transition requires initialized project control")
    project_revision = expected.get("project_revision")
    if not isinstance(project_revision, int):
        raise ValueError("transition expected.project_revision must be an integer")
    control.require_project_revision(project, project_revision)
    expected_task_id = expected.get("task_id")
    if current is None:
        if expected_task_id not in (None, ""):
            raise ValueError("transition expected task does not exist")
    else:
        if str(expected_task_id or "") != str(current.get("id") or ""):
            raise ValueError("transition expected.task_id does not match the selected task")
        task_revision = expected.get("task_revision")
        if not isinstance(task_revision, int):
            raise ValueError("transition expected.task_revision must be an integer")
        if task_revision != int(current.get("state_revision", 0)):
            raise ValueError(
                f"transition task revision conflict: expected {current.get('state_revision', 0)}, received {task_revision}"
            )
    return current, resolution


def _ensure_context(control, repo: pathlib.Path, target: dict[str, Any]) -> str:
    context = _object("transition target.context", target.get("context"))
    context_id = control.require_control_id("transition context id", str(context.get("id") or ""))
    state = control.paths(repo)
    project = control.load_project(state, repo)
    assert project is not None
    if context_id in project.get("contexts", {}):
        return context_id
    required = ("title", "authority_boundary", "delivery_boundary", "context_boundary")
    missing = [name for name in required if not str(context.get(name) or "").strip()]
    if missing:
        raise ValueError("new transition context requires: " + ", ".join(missing))
    arguments = [
        "project-context", "adopt", "--repo-root", str(repo),
        "--project-revision", str(project.get("state_revision", 0)),
        "--context-id", context_id, "--title", str(context["title"]),
        "--lifecycle", str(context.get("lifecycle") or "active"),
        "--coverage", str(context.get("coverage") or "bounded"),
        "--authority-boundary", str(context["authority_boundary"]),
        "--delivery-boundary", str(context["delivery_boundary"]),
        "--context-boundary", str(context["context_boundary"]),
    ]
    if context.get("mission"):
        arguments.extend(["--mission", str(context["mission"])])
    _run_existing(control, arguments)
    return context_id


def _ensure_outcomes(control, repo: pathlib.Path, context_id: str, target: dict[str, Any]) -> str:
    outcomes = _list("transition target.outcomes", target.get("outcomes"))
    task = _object("transition target.task", target.get("task"))
    selected_id = control.require_control_id(
        "transition task outcome id", str(task.get("outcome_id") or "")
    )
    state = control.paths(repo)
    for raw in outcomes:
        outcome = _object("transition outcome", raw)
        outcome_id = control.require_control_id("transition outcome id", str(outcome.get("id") or ""))
        if control.outcome_record_path(state, context_id, outcome_id).exists():
            continue
        project = control.load_project(state, repo)
        assert project is not None
        arguments = [
            "outcome", "add", "--repo-root", str(repo),
            "--project-revision", str(project.get("state_revision", 0)),
            "--project-context", context_id, "--outcome-id", outcome_id,
            "--title", str(outcome.get("title") or ""),
            "--statement", str(outcome.get("statement") or ""),
            "--status", str(outcome.get("status") or "active"),
        ]
        for value in _strings("outcome acceptance", outcome.get("acceptance")):
            arguments.extend(["--acceptance", value])
        if outcome.get("parent_id"):
            arguments.extend(["--parent-id", str(outcome["parent_id"])])
        if outcome.get("contract") is not None:
            arguments.extend(["--contract-json", json.dumps(outcome["contract"], ensure_ascii=False)])
        _run_existing(control, arguments)
    control.read_outcome_record(state, context_id, selected_id)
    return selected_id


def _ensure_intake(control, repo: pathlib.Path, request_key: str, context_id: str, outcome_id: str, target: dict[str, Any]) -> str:
    intake = _object("transition target.intake", target.get("intake"))
    state = control.paths(repo)
    project = control.load_project(state, repo)
    assert project is not None
    existing_id = intake.get("id")
    if existing_id:
        intake_id = control.require_control_id("transition intake id", str(existing_id))
        try:
            found_context, record = control.find_intake_record(state, project, intake_id)
        except ValueError:
            record = None
        else:
            if found_context != context_id or record.get("status") != "confirmed":
                raise ValueError("transition intake must be confirmed in the target context")
            return intake_id
    intake_id = control.require_control_id(
        "transition intake id", str(existing_id or f"INTAKE-TRANSITION-{request_key.upper()}")
    )
    session_key = hashlib.sha256(("session:" + request_key).encode("utf-8")).hexdigest()[:24]
    turn_id = "transition:" + request_key
    _run_existing(control, [
        "intake", "turn", "--repo-root", str(repo),
        "--session-key", session_key, "--turn-id", turn_id,
    ])
    assessment = {
        "id": intake_id,
        "depth": "clear",
        "summary": intake.get("summary"),
        "goal": intake.get("goal"),
        "inference": intake.get("inference"),
        "project_context_id": context_id,
        "outcome_id": outcome_id,
        "scope": _strings("intake scope", intake.get("scope")),
        "acceptance": _strings("intake acceptance", intake.get("acceptance")),
        "non_goals": _strings("intake non-goals", intake.get("non_goals")),
        "assumptions": _strings("intake assumptions", intake.get("assumptions")),
        "repository_facts": _strings("intake facts", intake.get("repository_facts")),
        "expert_completions": _strings("intake expert completions", intake.get("expert_completions")),
        "decisions": [],
    }
    if intake.get("contract") is not None:
        assessment["contract"] = intake["contract"]
    _run_existing(control, [
        "intake", "assess", "--repo-root", str(repo),
        "--session-key", session_key, "--turn-id", turn_id,
        "--assessment-json", json.dumps(assessment, ensure_ascii=False),
    ])
    return intake_id


def _exit_source(control, repo: pathlib.Path, route: TransitionRoute, current: dict[str, Any] | None, confirmation: str) -> None:
    if route.source_action == "keep":
        return
    assert current is not None
    if route.source_action == "pass":
        _run_existing(control, [
            "finish", "--repo-root", str(repo), "--status", "passed",
            "--summary", "accepted before execution-focus transition",
            "--confirmation-source", confirmation,
        ])
        return
    state = control.paths(repo)
    superseded = dict(current)
    superseded.update({
        "schema_version": control.SCHEMA_VERSION,
        "status": "superseded",
        "summary": "superseded by a confirmed execution-focus transition",
        "superseded_by_transition": True,
        "transition_confirmation_source": confirmation,
        "finished_at": control.now(),
    })
    control.continuity_event(
        superseded,
        "execution_focus_superseded",
        confirmation_source=confirmation,
    )
    control.archive(state, superseded)


def _start_target(control, repo: pathlib.Path, context_id: str, outcome_id: str, intake_id: str, target: dict[str, Any]) -> str:
    task = _object("transition target.task", target.get("task"))
    tier = str(task.get("tier") or "team")
    arguments = [
        "start", "--repo-root", str(repo), "--tier", tier,
        "--task", str(task.get("title") or task.get("task") or ""),
        "--requirement-receipt", str(task.get("requirement_receipt") or intake_id),
        "--confirmation-source", str(task.get("confirmation_source") or "transition-confirmed"),
        "--project-context", context_id, "--outcome-id", outcome_id, "--intake-id", intake_id,
    ]
    for flag, key in (("--acceptance", "acceptance"), ("--scope", "scope"), ("--validation", "validation"), ("--evidence", "evidence"), ("--stop-condition", "stop_conditions"), ("--coverage-id", "coverage_ids")):
        for value in _strings(f"task {key}", task.get(key)):
            arguments.extend([flag, value])
    capabilities = _object("task capabilities", task.get("capabilities") or {})
    for value in _strings("enabled capabilities", capabilities.get("enabled")):
        arguments.extend(["--capability", value])
    for key, value in _object("skipped capabilities", capabilities.get("skipped") or {}).items():
        arguments.extend(["--skip", f"{key}={value}"])
    for key, value in _object("capability evidence", capabilities.get("evidence") or {}).items():
        arguments.extend(["--capability-evidence", f"{key}={value}"])
    for key, value in _object("task budgets", task.get("budgets") or {}).items():
        arguments.extend(["--budget", f"{key}={value}"])
    result = _run_existing(control, arguments)
    return control.require_concrete("transition task id", str(result.get("id") or ""))


def _set_plan(control, repo: pathlib.Path, target: dict[str, Any]) -> None:
    plan = _object("transition target.plan", target.get("plan"))
    arguments = [
        "plan", "--repo-root", str(repo), "--base-revision", "0",
        "--reason", str(plan.get("reason") or "execution-focus transition"),
        "--plan-json", json.dumps(plan, ensure_ascii=False),
    ]
    if plan.get("next_action"):
        arguments.extend(["--next-action", str(plan["next_action"])])
    if plan.get("durability"):
        arguments.extend(["--durability", str(plan["durability"])])
    _run_existing(control, arguments)


def _command_transition(control, args: argparse.Namespace, repo: pathlib.Path, url: str | None) -> int:
    spec = _load_spec(control, args)
    state = control.ensure_root(repo)
    request_key = _request_key(control, spec.get("request_id"))
    completed = _completed_transition(control, repo, state, request_key)
    if completed is not None:
        print(json.dumps(completed, ensure_ascii=False))
        return 0
    route_id = str(spec.get("route") or "")
    route = TRANSITION_REGISTRY.get(route_id)
    if route is None:
        raise ValueError("transition route must be start-new, switch-passed, or switch-superseded")
    confirmation = control.require_concrete(
        "transition confirmation source", str(spec.get("confirmation_source") or "")
    )
    target = _object("transition target", spec.get("target"))
    current, _resolution = _expected_state(control, repo, state, spec)
    source_status = current.get("status") if current else None
    if source_status not in route.source_statuses:
        raise ValueError(
            f"transition route {route.identifier} does not accept source status {source_status or 'idle'}"
        )
    temporary, backup, snapshot_names = _transition_backup(state["root"])
    _write_transition(control, state, {
        "schema_version": 1,
        "request_id": request_key,
        "route": route.identifier,
        "status": "preparing",
        "proof_policy": route.proof_policy,
        "source_task_id": current.get("id") if current else None,
        "updated_at": control.now(),
    })
    owned_fingerprint = _control_fingerprint(state["root"])
    try:
        context_id = _ensure_context(control, repo, target)
        owned_fingerprint = _control_fingerprint(state["root"])
        outcome_id = _ensure_outcomes(control, repo, context_id, target)
        owned_fingerprint = _control_fingerprint(state["root"])
        intake_id = _ensure_intake(control, repo, request_key, context_id, outcome_id, target)
        owned_fingerprint = _control_fingerprint(state["root"])
        _exit_source(control, repo, route, current, confirmation)
        owned_fingerprint = _control_fingerprint(state["root"])
        task_id = _start_target(control, repo, context_id, outcome_id, intake_id, target)
        owned_fingerprint = _control_fingerprint(state["root"])
        _set_plan(control, repo, target)
        owned_fingerprint = _control_fingerprint(state["root"])
        readback = control.build_status_payload(repo, control.paths(repo), view="compact")
        current_node = (readback.get("continuity_summary") or {}).get("current_node")
        if readback.get("id") != task_id or readback.get("continuity_status") != "ready" or not current_node:
            raise ValueError("transition readback is not a ready executable focus")
        if readback.get("project_context_id") != context_id or readback.get("primary_outcome_id") != outcome_id or readback.get("intake_id") != intake_id:
            raise ValueError("transition readback attribution does not match the target")
        if not _verify_progress(url, task_id):
            url = _progress_url(repo)
        if not _verify_progress(url, task_id):
            raise ValueError("transition control-plane UI readback is unavailable")
        result = {
            "schema_version": 1,
            "request_id": request_key,
            "route": route.identifier,
            "status": "ready",
            "proof_policy": route.proof_policy,
            "source_task_id": current.get("id") if current else None,
            "task_id": task_id,
            "project_context_id": context_id,
            "primary_outcome_id": outcome_id,
            "intake_id": intake_id,
            "current_node": current_node,
            "state_revision": readback.get("state_revision"),
            "project_revision": readback.get("project_revision"),
            "control_plane_url": url,
            "updated_at": control.now(),
        }
        _write_transition(control, control.paths(repo), result)
        if not _verify_ready_transition(url, task_id, request_key):
            raise ValueError("transition control-plane UI did not publish the ready state")
    except Exception as error:
        rollback_safe = _control_fingerprint(state["root"]) == owned_fingerprint
        if rollback_safe:
            _restore_transition(state["root"], backup, snapshot_names)
        failed_state = control.paths(repo)
        failure = {
            "schema_version": 1,
            "request_id": request_key,
            "route": route.identifier,
            "status": "failed",
            "committed": False if rollback_safe else None,
            "rollback_status": "restored" if rollback_safe else "refused_state_changed",
            "error": str(error),
            "control_plane_url": url,
            "updated_at": control.now(),
        }
        _write_transition(control, failed_state, failure)
        temporary.cleanup()
        print(json.dumps(failure, ensure_ascii=False))
        return 2
    temporary.cleanup()
    print(json.dumps(result, ensure_ascii=False))
    return 0


def command_transition(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    url = _progress_url(repo)
    state = control.ensure_root(repo)
    with control.state_lock(state["transition_lock"]):
        try:
            return _command_transition(control, args, repo, url)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            failure = {
                "schema_version": 1,
                "request_id": None,
                "route": None,
                "status": "failed",
                "committed": False,
                "rollback_status": "not_started",
                "error": str(error),
                "control_plane_url": url,
                "updated_at": control.now(),
            }
            _write_transition(control, state, failure)
            print(json.dumps(failure, ensure_ascii=False))
            return 2
