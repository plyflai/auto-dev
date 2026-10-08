#!/usr/bin/env python3
"""Route Codex lifecycle events through the Auto Dev control plane."""

from __future__ import annotations

import contextlib
import contextvars
import fnmatch
import hashlib
import io
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote, urlsplit

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

SKILL_SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "auto-dev" / "scripts"
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

from hook_session_state import (
    activate_session,
    claim_writer_lease,
    session_is_active,
    touch_writer_lease,
    writer_lease_status,
)
from receipt_catalog import bilingual_label, receipt as bilingual_receipt
from plugin_identity import auto_dev_plugin_root, auto_dev_plugin_version
import project_memory
import runctl

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows does not provide fcntl.
    fcntl = None  # type: ignore[assignment]


MUTATING_RUN_COMMANDS = (
    "start|escalate|capabilities|event|plan|checkpoint|diagnostics|finish|"
    "abandon|recover|migrate|(?:handoff\\s+import)|(?:bootstrap\\s+apply)|"
    "(?:legacy-upgrade\\s+apply)|"
    "(?:project\\s+(?:init|migrate))|(?:project-context\\s+(?:adopt|set|select))|"
    "(?:intake\\s+(?:turn|assess|resolve|confirm|reopen))|"
    "(?:outcome\\s+(?:add|set|link|move))|(?:capability\\s+(?:add|set))|"
    "(?:activity\\s+record)|(?:focus\\s+set)|"
    "(?:task\\s+(?:select|pause|amend-scope|review|resume|attribute))|(?:fix\\s+apply)|"
    "(?:debug\\s+(?:begin|observe|resolve|recovery|case-search\\s+bind|reproduction\\s+record|hypothesis\\s+add))|"
    "(?:memory\\s+case\\s+promote)|"
    "(?:workspace\\s+(?:checkpoint\\s+(?:create|protect)|rollback\\s+apply))|(?:impact\\s+record)|"
    "(?:policy\\s+(?:set|approve))"
)
LEGACY_RUN_MUTATION = re.compile(
    rf"(?:^|[\s/])runctl\.py(?:[\s'\"])+(?:{MUTATING_RUN_COMMANDS})(?:\s|$)",
    re.IGNORECASE,
)
LEGACY_DEP_MUTATION = re.compile(
    r"(?:^|[\s/])(?:dependency_manager|project_memory)\.py(?:[\s'\"])+"
    r"(?:record|attempt|preflight|resolve\b[^\n;|]*--write-lease)(?:\s|$)",
    re.IGNORECASE,
)
LEGACY_POLICY_COMMAND = re.compile(
    r"(?:^|[\s/])runctl\.py(?:[\s'\"])+policy(?:\s|$)",
    re.IGNORECASE,
)
PATCH_PATH = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File:|Move to:)\s*(.+?)\s*$")
HOOK_RECEIPT_PREFIX = "🪝 Auto Dev Hook"
SHELL_BOUNDARIES = {";", "&&", "||", "|", "&"}
DIRECT_WRITE_PROGRAMS = {"rm", "mv", "cp", "install", "touch", "truncate"}
PYTHON_WRITE_CALL = re.compile(r"\b(?:write_text|write_bytes)\s*\(")
QUICK_WRITE_MAX_FILES = 2
QUICK_WRITE_MAX_CHANGED_LINES = 40
QUICK_WRITE_ALLOWED_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html", ".java",
    ".js", ".jsx", ".kt", ".kts", ".m", ".mm", ".php", ".py", ".rb", ".rs",
    ".scss", ".swift", ".ts", ".tsx", ".vue", ".md",
}
QUICK_WRITE_BLOCKED_PARTS = {".auto-dev", ".git", ".github", ".conductor"}
CONTROL_METADATA_ROOTS = frozenset({".auto-dev", ".autodev", ".codegraph", ".conductor"})
ADB_EXTERNAL_ACTIONS = {"am", "input", "install", "monkey", "pm", "screencap", "screenrecord", "uninstall"}
FRIDA_EXTERNAL_ACTIONS = {"frida", "frida-ps", "frida-trace"}
ANDROID_INSTRUMENTATION = "android-instrumentation"
PROGRESS_START_TIMEOUT_SECONDS = 0.8
PRE_GIT_STATE_SCHEMA_VERSION = 1
EXPLICIT_AUTO_DEV_REFERENCE = re.compile(r"\$auto-dev(?:[:\]\s]|$)", re.IGNORECASE)
AUTO_RESUME_STATUSES = {"active", "review_ready", "selection_required"}
_HOOK_EVALUATION: contextvars.ContextVar[dict[str, dict[tuple[str, ...], Any]] | None] = (
    contextvars.ContextVar("auto_dev_hook_evaluation", default=None)
)


@contextlib.contextmanager
def hook_evaluation_scope() -> Iterator[None]:
    """Memoize immutable control reads for one Hook dispatch only."""
    if _HOOK_EVALUATION.get() is not None:
        yield
        return
    token = _HOOK_EVALUATION.set({"status": {}, "identity": {}, "lease": {}})
    try:
        yield
    finally:
        _HOOK_EVALUATION.reset(token)


def invalidate_hook_control_cache(root: Path) -> None:
    cache = _HOOK_EVALUATION.get()
    if cache is None:
        return
    root_key = str(root.resolve())
    for values in cache.values():
        for key in [key for key in values if key and key[0] == root_key]:
            values.pop(key, None)


def plugin_root() -> Path:
    configured = os.environ.get("PLUGIN_ROOT")
    return Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parents[1]


def cli_path() -> Path:
    return plugin_root() / "skills" / "auto-dev" / "scripts" / "auto_dev.py"


def progress_runtime_root() -> Path:
    configured = os.environ.get("AUTO_DEV_PROGRESS_RUNTIME_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    data_root = os.environ.get("PLUGIN_DATA")
    if data_root:
        return Path(data_root).expanduser().resolve() / "progress-servers"
    return Path(tempfile.gettempdir()).resolve() / "auto-dev-progress"


def progress_record_path(root: Path) -> Path:
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:24]
    return progress_runtime_root() / f"{digest}.json"


def progress_repo_fingerprint(root: Path) -> str:
    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]


def progress_url_from_record(
    root: Path, path: Path, *, expected_bundle_version: str | None = None
) -> str | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict) or record.get("repo") != str(root):
        return None
    expected_bundle_version = expected_bundle_version or auto_dev_plugin_version(plugin_root())
    if (
        not expected_bundle_version
        or record.get("bundle_version") != expected_bundle_version
    ):
        return None
    value = record.get("url")
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not port:
        return None
    url = f"http://127.0.0.1:{port}/"
    generation = record.get("generation")
    try:
        with urllib.request.urlopen(url + "api/health", timeout=0.3) as response:
            health = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError):
        return None
    if not isinstance(health, dict) or health.get("repo_fingerprint") != progress_repo_fingerprint(root):
        return None
    if health.get("bundle_version") != expected_bundle_version:
        return None
    if isinstance(generation, str) and health.get("generation") != generation:
        return None
    return url


@contextlib.contextmanager
def progress_record_lock(path: Path) -> Iterator[None]:
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


def ensure_progress_server(root: Path, *, cli: Path | None = None) -> str | None:
    path = progress_record_path(root)
    progress_cli = (cli or cli_path()).expanduser().resolve()
    expected_bundle_version = auto_dev_plugin_version(progress_cli)
    if not expected_bundle_version:
        return None
    try:
        with progress_record_lock(path):
            existing = progress_url_from_record(
                root, path, expected_bundle_version=expected_bundle_version
            )
            if existing:
                return existing
            generation = secrets.token_hex(16)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            subprocess.Popen(
                [
                    sys.executable,
                    str(progress_cli),
                    "progress",
                    "--repo-root",
                    str(root),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "0",
                    "--ready-file",
                    str(path),
                    "--generation",
                    generation,
                ],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            deadline = time.monotonic() + PROGRESS_START_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                url = progress_url_from_record(
                    root, path, expected_bundle_version=expected_bundle_version
                )
                if url:
                    return url
                time.sleep(0.05)
    except OSError:
        return None
    return None


def progress_link_detail(root: Path, session_key: str | None = None) -> str:
    url = ensure_progress_server(root)
    if not url:
        return "control-plane=unavailable"
    suffix = f"?session_key={quote(session_key)}" if session_key else ""
    return f"[control-plane]({url}{suffix})"


def shell_segments(command: str) -> list[list[str]]:
    import hook_commands
    return hook_commands.shell_segments(sys.modules[__name__], command)


def segment_program_index(tokens: list[str]) -> int | None:
    import hook_commands
    return hook_commands.segment_program_index(sys.modules[__name__], tokens)


def segment_program(tokens: list[str]) -> str | None:
    import hook_commands
    return hook_commands.segment_program(sys.modules[__name__], tokens)


def segment_arguments(tokens: list[str]) -> list[str]:
    import hook_commands
    return hook_commands.segment_arguments(sys.modules[__name__], tokens)


def segment_argv(tokens: list[str]) -> list[str]:
    import hook_commands
    return hook_commands.segment_argv(sys.modules[__name__], tokens)


def has_in_place_option(tokens: list[str]) -> bool:
    import hook_commands
    return hook_commands.has_in_place_option(sys.modules[__name__], tokens)


def redirection_targets(tokens: list[str]) -> list[str]:
    import hook_commands
    return hook_commands.redirection_targets(sys.modules[__name__], tokens)


def product_redirection_targets(tokens: list[str]) -> list[str]:
    import hook_commands
    return hook_commands.product_redirection_targets(sys.modules[__name__], tokens)


def is_auto_dev_path(value: str) -> bool:
    import hook_commands
    return hook_commands.is_auto_dev_path(sys.modules[__name__], value)


def is_control_metadata_path(value: str) -> bool:
    import hook_commands
    return hook_commands.is_control_metadata_path(sys.modules[__name__], value)


def resolved_command_path(value: str, cwd: Path) -> Path | None:
    import hook_commands
    return hook_commands.resolved_command_path(sys.modules[__name__], value, cwd)


def canonical_control_segment(tokens: list[str], cwd: Path) -> bool:
    import hook_commands
    return hook_commands.canonical_control_segment(sys.modules[__name__], tokens, cwd)


def mutating_control_parts(parts: list[str]) -> bool:
    import hook_commands
    return hook_commands.mutating_control_parts(sys.modules[__name__], parts)


def self_target_control_segment(tokens: list[str]) -> bool:
    import hook_commands
    return hook_commands.self_target_control_segment(sys.modules[__name__], tokens)


def direct_state_write(command: str, cwd: Path) -> bool:
    import hook_commands
    return hook_commands.direct_state_write(sys.modules[__name__], command, cwd)


def product_write_segment(tokens: list[str], cwd: Path) -> bool:
    import hook_commands
    return hook_commands.product_write_segment(sys.modules[__name__], tokens, cwd)


def patch_paths(command: str) -> list[str]:
    import hook_commands
    return hook_commands.patch_paths(sys.modules[__name__], command)


def quick_patch_details(root: Path, command: str) -> tuple[list[str], int] | None:
    import hook_commands
    return hook_commands.quick_patch_details(sys.modules[__name__], root, command)


def normalize_patch_path(root: Path, value: str) -> str:
    import hook_commands
    return hook_commands.normalize_patch_path(sys.modules[__name__], root, value)


def locate_project(start: Path) -> Path | None:
    current = start.expanduser().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".auto-dev" / "active.json").is_file() or (candidate / ".auto-dev" / "project.json").is_file():
            return candidate
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=current,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is not None and result.returncode == 0:
        root = Path(result.stdout.strip()).resolve()
        if (root / ".auto-dev" / "active.json").is_file() or (root / ".auto-dev" / "project.json").is_file():
            return root
    return None


def read_status(
    root: Path, *, session_key: str | None = None, profile: str = "hook",
) -> tuple[dict[str, Any] | None, str | None]:
    cache = _HOOK_EVALUATION.get()
    cache_key = (str(root.resolve()), session_key or "", profile)
    if cache is not None and cache_key in cache["status"]:
        return cache["status"][cache_key]
    if not cli_path().is_file():
        result = (None, f"status invocation failed: CLI is missing at {cli_path()}")
        if cache is not None:
            cache["status"][cache_key] = result
        return result
    try:
        repo = runctl.resolve_repo(str(root))
        value = runctl.build_status_payload(
            repo,
            runctl.paths(repo),
            view="compact",
            session_key=session_key,
            profile=profile,
        )
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        result = (None, f"status invocation failed: {error}")
    else:
        result = (value, None) if isinstance(value, dict) else (None, "status returned no JSON")
    if cache is not None:
        cache["status"][cache_key] = result
    return result


def read_status_identity(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    cache = _HOOK_EVALUATION.get()
    cache_key = (str(root.resolve()),)
    if cache is not None and cache_key in cache["identity"]:
        return cache["identity"][cache_key]
    if not cli_path().is_file():
        result = (None, f"status identity failed: CLI is missing at {cli_path()}")
        if cache is not None:
            cache["identity"][cache_key] = result
        return result
    try:
        repo = runctl.resolve_repo(str(root))
        value = runctl.build_status_identity(repo, runctl.paths(repo))
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        result = (None, f"status identity failed: {error}")
    else:
        result = (value, None) if isinstance(value, dict) else (None, "status identity returned no JSON")
    if cache is not None:
        cache["identity"][cache_key] = result
    return result


def read_writer_lease_status(root: Path, event: dict[str, Any], *, branch_key: str) -> dict[str, Any]:
    cache = _HOOK_EVALUATION.get()
    cache_key = (str(root.resolve()), branch_key)
    if cache is not None and cache_key in cache["lease"]:
        return cache["lease"][cache_key]
    value = writer_lease_status(root, event, branch_key=branch_key)
    if cache is not None:
        cache["lease"][cache_key] = value
    return value


def invoke_handler(parser, arguments: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            args = parser.parse_args(arguments)
            result = args.handler(args)
    except SystemExit as error:
        return int(error.code or 0), stdout.getvalue(), stderr.getvalue()
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        return 2, stdout.getvalue(), str(error)
    return int(result or 0), stdout.getvalue(), stderr.getvalue()


def intake_session_key(root: Path, event: dict[str, Any]) -> str | None:
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    return hashlib.sha256(f"{root}\0{session_id}".encode("utf-8")).hexdigest()[:24]


def record_intake_turn(
    root: Path, event: dict[str, Any], status: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    session_key = intake_session_key(root, event)
    turn_id = event.get("turn_id")
    if session_key is None or not isinstance(turn_id, str) or not turn_id:
        return None, None
    arguments = [
        "intake",
        "turn",
        "--repo-root",
        str(root),
        "--session-key",
        session_key,
        "--turn-id",
        turn_id,
    ]
    task_id = status.get("id") if isinstance(status, dict) else None
    if isinstance(task_id, str) and task_id:
        arguments.extend(["--task-id", task_id])
    _, stdout, stderr = invoke_handler(runctl.build_parser(), arguments)
    if stdout.strip():
        try:
            value = json.loads(stdout)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return value, None
    detail = stderr.strip().splitlines()[-1] if stderr.strip() else "intake turn returned no JSON"
    return None, detail[:500]


def limited(values: Any, limit: int = 8) -> list[Any]:
    return list(values)[:limit] if isinstance(values, list) else []


def bounded(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 320 else value[:317] + "..."
    if isinstance(value, list):
        return [bounded(item) for item in value[:6]]
    if isinstance(value, dict):
        return {str(key): bounded(item) for key, item in list(value.items())[:16]}
    return value


def performance_context(proof: Any) -> dict[str, Any] | None:
    if not isinstance(proof, dict):
        return None
    evidence = proof.get("performance_evidence")
    if not isinstance(evidence, dict):
        return None
    summary: dict[str, Any] = {
        "node_id": proof.get("node_id"),
        "proof_id": proof.get("proof_id"),
        "status": proof.get("status"),
        "fresh": proof.get("fresh"),
        "phase": evidence.get("phase"),
        "metric": evidence.get("metric"),
        "unit": evidence.get("unit"),
        "sample_count": evidence.get("sample_count"),
        "observed_value": evidence.get("observed_value"),
        "target_value": evidence.get("target_value"),
        "noise_tolerance_pct": evidence.get("noise_tolerance_pct"),
    }
    for key in ("baseline_attempt_id", "improvement_pct", "target_met", "change_exceeds_noise"):
        if key in evidence:
            summary[key] = evidence.get(key)
    baseline = evidence.get("baseline")
    if isinstance(baseline, dict):
        summary["baseline"] = {
            "attempt_id": baseline.get("attempt_id"),
            "observed_value": baseline.get("observed_value"),
            "sample_count": baseline.get("sample_count"),
        }
    return summary


def dependency_context(root: Path) -> dict[str, Any]:
    lease_path = root / ".auto-dev" / "dependency-lease.json"
    preflight_path = root / ".auto-dev" / "dependency-preflight.json"
    result: dict[str, Any] = {"leases": [], "preflight": None}
    try:
        if lease_path.is_file():
            lease_data = json.loads(lease_path.read_text(encoding="utf-8"))
            if isinstance(lease_data, dict):
                leases = lease_data.get("leases") if lease_data.get("schema_version") == 2 else [lease_data]
                if isinstance(leases, list):
                    result["leases"] = [
                        {
                            "dependency_id": item.get("dependency_id"),
                            "capability": item.get("capability"),
                            "scope": item.get("scope"),
                            "version": item.get("version"),
                            "validated_at": item.get("validated_at") or item.get("created_at"),
                        }
                        for item in leases[:6]
                        if isinstance(item, dict)
                    ]
        if preflight_path.is_file():
            permit = json.loads(preflight_path.read_text(encoding="utf-8"))
            if isinstance(permit, dict):
                result["preflight"] = {
                    "permit_id": permit.get("permit_id"),
                    "dependency_id": permit.get("dependency_id"),
                    "capability": permit.get("capability"),
                    "action_id": permit.get("action_id"),
                    "expires_at": permit.get("expires_at"),
                }
    except (OSError, json.JSONDecodeError):
        return {"status": "unavailable"}
    return result


def contract_pulse(status: dict[str, Any], reason: str) -> str | None:
    """Build a small repeated reminder without replaying the full control state."""
    capsule = status.get("contract_capsule") if isinstance(status.get("contract_capsule"), dict) else {}
    if capsule.get("status") != "strict":
        return None
    gate = status.get("contract_gate") if isinstance(status.get("contract_gate"), dict) else {}
    summary = status.get("continuity_summary") if isinstance(status.get("continuity_summary"), dict) else {}
    hard = capsule.get("hard_constraints") if isinstance(capsule.get("hard_constraints"), list) else []
    forbidden = capsule.get("forbidden_moves") if isinstance(capsule.get("forbidden_moves"), list) else []
    hard_text = "; ".join(
        str(item.get("text"))[:120]
        for item in hard[:2]
        if isinstance(item, dict) and item.get("text")
    )
    forbidden_text = "; ".join(str(value)[:120] for value in forbidden[:1] if value)
    prewrite = limited(gate.get("prewrite_missing"), limit=4)
    missing = limited(gate.get("missing_coverage"), limit=4)
    gate_text = (
        f"prewrite pending={','.join(str(value) for value in prewrite)}"
        if prewrite
        else (f"coverage pending={','.join(str(value) for value in missing)}" if missing else "coverage ready")
    )
    lines = [
        "Auto Dev mainline pulse / 主线脉冲:",
        f"contract={capsule.get('id')}@R{capsule.get('revision', 1)} node={summary.get('current_node') or '-'} trigger={reason}",
        f"mainline={str(capsule.get('mainline') or '')[:220]}",
        f"preserve={hard_text or '-'}",
        f"forbid={forbidden_text or '-'}",
        f"gate={gate_text}; strict blockers={','.join(str(value) for value in limited(status.get('strict_blockers'), limit=4)) or '-'}",
        "If the next action changes this line, stop and require Requirement Diff; do not silently narrow or replace it.",
    ]
    return "\n".join(lines)


def control_context(root: Path, status: dict[str, Any], reason: str, *, subagent: bool = False) -> str:
    continuity = status.get("continuity") if isinstance(status.get("continuity"), dict) else {}
    summary = status.get("continuity_summary") if isinstance(status.get("continuity_summary"), dict) else {}
    contract = status.get("delivery_contract") if isinstance(status.get("delivery_contract"), dict) else {}
    current_state = status.get("current_state") if isinstance(status.get("current_state"), dict) else {}
    goal = continuity.get("goal") if isinstance(continuity.get("goal"), dict) else {}
    plan = continuity.get("plan") if isinstance(continuity.get("plan"), dict) else {}
    nodes = plan.get("nodes") if isinstance(plan.get("nodes"), list) else []
    current_node_id = summary.get("current_node")
    current_node = next(
        (node for node in nodes if isinstance(node, dict) and node.get("id") == current_node_id),
        None,
    )
    verification_summary = summary.get("verification") if isinstance(summary.get("verification"), dict) else {}
    impact_summary = summary.get("impact") if isinstance(summary.get("impact"), dict) else {}
    diagnostic_summary = summary.get("diagnostic") if isinstance(summary.get("diagnostic"), dict) else {}
    policy_summary = status.get("workspace_policy") if isinstance(status.get("workspace_policy"), dict) else {}
    latest_proofs = (
        continuity.get("latest_proofs")
        if isinstance(continuity.get("latest_proofs"), list)
        else continuity.get("proofs")
    )
    performance_summaries = [
        summary
        for proof in (latest_proofs if isinstance(latest_proofs, list) else [])
        for summary in [performance_context(proof)]
        if summary is not None
    ]
    capabilities = contract.get("capabilities") if isinstance(contract.get("capabilities"), dict) else {}
    evidence = capabilities.get("evidence") if isinstance(capabilities.get("evidence"), dict) else {}
    enabled = limited(capabilities.get("enabled"))
    intake_gate = status.get("intake_gate") if isinstance(status.get("intake_gate"), dict) else {}
    contract_gate = status.get("contract_gate") if isinstance(status.get("contract_gate"), dict) else {}
    contract_capsule = status.get("contract_capsule") if isinstance(status.get("contract_capsule"), dict) else {}
    hierarchy = status.get("hierarchy") if isinstance(status.get("hierarchy"), dict) else {}
    managed_context = hierarchy.get("managed_context") if isinstance(hierarchy.get("managed_context"), dict) else {}
    upgrade = hierarchy.get("control_plane_upgrade") if isinstance(
        hierarchy.get("control_plane_upgrade"), dict,
    ) else {}
    payload = {
        "trigger": reason,
        "project": {
            "id": status.get("project_id"),
            "revision": status.get("project_revision"),
            "context": status.get("context_key"),
            "branch": current_state.get("branch"),
            "head": current_state.get("head"),
            "managed_context": managed_context.get("summary"),
            "legacy_upgrade": upgrade,
        },
        "task": {
            "id": status.get("id"),
            "statement": goal.get("statement") or status.get("task"),
            "acceptance": limited(goal.get("acceptance") or contract.get("acceptance")),
            "tier": status.get("tier"),
            "lifecycle": status.get("status"),
        },
        "revisions": {
            "goal": summary.get("goal_revision"),
            "plan": summary.get("plan_revision"),
            "state": status.get("state_revision"),
        },
        "position": {
            "current_node": current_node or current_node_id,
            "node_kind": current_node.get("node_kind") if isinstance(current_node, dict) else None,
            "verification": current_node.get("verification") if isinstance(current_node, dict) else None,
            "verification_summary": bounded(verification_summary),
            "next_action": summary.get("next_action"),
            "continuity_status": status.get("continuity_status"),
            "bootstrap_status": status.get("bootstrap_status"),
        },
        # Keep the inherited contract visible on every refresh, but use the
        # bounded capsule rather than replaying the full Intake/Project text.
        "contract": contract_capsule,
        "contract_gate": {
            "status": contract_gate.get("status"),
            "missing_coverage": limited(contract_gate.get("missing_coverage")),
            "unplanned_coverage": limited(contract_gate.get("unplanned_coverage")),
            "prewrite_required": limited(contract_gate.get("prewrite_required")),
            "prewrite_missing": limited(contract_gate.get("prewrite_missing")),
            "stale_reason": contract_gate.get("stale_reason"),
        },
        "workspace_policy": bounded({
            "status": policy_summary.get("status"),
            "active": policy_summary.get("active"),
            "revision": policy_summary.get("revision"),
            "rule_counts": policy_summary.get("rule_counts"),
            "approvals": policy_summary.get("approvals"),
            "sensitive_evidence": policy_summary.get("sensitive_evidence"),
        }),
        "delivery": {
            "planned_scope": limited(contract.get("planned_scope")),
            "scope_amendments": limited(contract.get("scope_amendments")),
            "validation_plan": limited(contract.get("validation_plan")),
            "enabled_capabilities": enabled,
            "capability_evidence": {key: evidence.get(key) for key in enabled if key in evidence},
            "budgets": contract.get("budgets", {}),
            "budget_usage": contract.get("budget_usage", {}),
            "exhausted_budgets": limited(contract.get("exhausted_budgets")),
            "stop_conditions": limited(contract.get("stop_conditions")),
        },
        "risks": {
            "strict_blockers": limited(status.get("strict_blockers")),
            "state_drift": limited(status.get("state_drift")),
            "pending_action": summary.get("pending_action"),
            "unattributed_actions": limited(status.get("unattributed_actions")),
            "open_gaps": limited(continuity.get("gaps")),
            "out_of_scope_changes": limited(current_state.get("out_of_scope_changes")),
            "verification_issues": limited(status.get("verification_issues")),
            "impact": bounded(impact_summary),
        },
        "evidence": {
            "review": bounded({
                "status": status.get("product_review_status"),
                "receipt": status.get("product_receipt")
                if status.get("status") == "review_ready" else None,
            }),
            "performance": limited(performance_summaries, limit=4),
            "proofs": limited(latest_proofs if isinstance(latest_proofs, list) else [], limit=8),
            "workspace_points": limited(
                summary.get("workspace_points")
                if isinstance(summary.get("workspace_points"), list)
                else (continuity.get("workspace_points") if isinstance(continuity.get("workspace_points"), list) else []),
                limit=4,
            ),
        },
        "dependencies": dependency_context(root),
        "task_candidates": limited(status.get("task_candidates")),
        "intake": bounded(intake_gate),
        "focus": {
            "view": hierarchy.get("view_focus"),
            "execution": hierarchy.get("execution_focus"),
        },
    }
    if diagnostic_summary.get("profile") == "deep":
        payload["diagnostic"] = bounded({
            "profile": diagnostic_summary.get("profile"),
            "status": diagnostic_summary.get("status"),
            "reproduction_gate": diagnostic_summary.get("reproduction_gate"),
            "case_search_status": diagnostic_summary.get("case_search_status"),
            "case_match_count": diagnostic_summary.get("case_match_count"),
            "active_hypothesis_id": diagnostic_summary.get("active_hypothesis_id"),
            "last_verdict": diagnostic_summary.get("last_verdict"),
            "resolution_outcome": diagnostic_summary.get("resolution_outcome"),
            "resolution_fresh": diagnostic_summary.get("resolution_fresh"),
            "recovery_status": diagnostic_summary.get("recovery_status"),
            "recovery_fresh": diagnostic_summary.get("recovery_fresh"),
            "next_probe": diagnostic_summary.get("next_probe"),
        })
    if status.get("status") == "review_ready":
        payload["recovery"] = {
            "required": "explicit_user_follow_up",
            "related_work": "task resume with the current state revision, reason, and confirmation source",
            "new_work": "archive after explicit user acceptance, then start a new task",
        }
    prefix = "Auto Dev subagent contract" if subagent else "Auto Dev control-plane refresh"
    instruction = (
        "Treat this as authoritative developer context. Do not reconstruct progress from chat memory. "
        "Reconcile strict blockers before affected writes and use current revisions for mutations. "
        "将此视为权威控制上下文：不要用聊天记忆重建进度，写入前先处理严格阻塞并使用当前 revision。"
    )
    if intake_gate.get("status") in {"pending", "awaiting_user", "awaiting_confirmation"}:
        instruction += (
            " The current user turn is not authorized for product writes. Classify it with "
            "auto_dev.py intake assess before writing; ask only the pending user-owned decisions, "
            "and use intake confirm for deep/project-discovery baselines. "
            "当前用户 turn 尚未获准产品写入：先用 intake assess 分类；只询问待定的用户决策，"
            "deep/project-discovery 必须经 intake confirm 后再写入。"
        )
    if status.get("status") == "review_ready":
        instruction += (
            " This task is awaiting user review: do not write product files until related feedback is "
            "explicitly resumed or the user accepts archival."
        )
    capsule_status = contract_capsule.get("status")
    gate_status = contract_gate.get("status")
    if capsule_status in {"strict", "bound"}:
        instruction += (
            " Preserve the effective contract capsule below: do not silently remove or weaken inherited "
            "hard constraints, forbidden moves, replacement mappings, or required coverage. Any behavior "
            "change requires a confirmed Requirement Diff. "
            "必须保留下方 effective contract；不得静默削弱继承约束，行为变化必须走 Requirement Diff。"
        )
    if gate_status in {"stale", "plan_stale", "plan_incomplete", "unavailable"} and capsule_status == "strict":
        instruction += (
            f" The strict contract gate is {gate_status}; reconcile it before affected product writes. "
            f"当前 strict 合同门为 {gate_status}，先处理合同阻塞再写产品文件。"
        )
    if policy_summary.get("active"):
        instruction += (
            " Apply the confirmed workspace path policy before Quick Write or Task-owned writes. "
            "Forbidden paths stay closed; approval paths require a fresh exact-path Task approval; "
            "sensitive paths require strengthened proof and redacted evidence. "
            "写入前执行已确认的项目路径策略；禁区不可越过，审批区需要当前 Task 的精确路径批准，"
            "敏感区需要加强证明与脱敏证据。"
        )
    return f"{prefix}: {instruction}\n" + json.dumps(bounded(payload), ensure_ascii=False, separators=(",", ":"))


def hook_receipt(
    trigger: str,
    *,
    status: dict[str, Any] | None = None,
    detail: str | None = None,
) -> str:
    parts = [bilingual_receipt(HOOK_RECEIPT_PREFIX, trigger)]
    if status is not None:
        summary = status.get("continuity_summary") if isinstance(status.get("continuity_summary"), dict) else {}
        verification = summary.get("verification") if isinstance(summary.get("verification"), dict) else {}
        task_id = status.get("id")
        state_revision = status.get("state_revision")
        current_node = summary.get("current_node")
        if task_id:
            parts.append(f"task={task_id}")
        if state_revision is not None:
            parts.append(f"state=R{state_revision}")
        if current_node:
            parts.append(f"node={current_node}")
        display_code = verification.get("display_code")
        node_kind = verification.get("node_kind")
        if display_code:
            parts.append(f"milestone={display_code}:{node_kind or 'delivery'}")
        failed = verification.get("failed_proofs", 0)
        pending = verification.get("pending_proofs", 0)
        if failed:
            parts.append(f"verification=failed:{failed}")
        elif pending:
            parts.append(f"verification=pending:{pending}")
        diagnostic = summary.get("diagnostic") if isinstance(summary.get("diagnostic"), dict) else {}
        if diagnostic.get("profile") == "deep":
            recovery_status = diagnostic.get("recovery_status")
            parts.append(
                "debug="
                + str(
                    (recovery_status if recovery_status != "unverified" else None)
                    or diagnostic.get("resolution_outcome")
                    or diagnostic.get("status")
                )
            )
    if detail:
        parts.append(detail)
    return " | ".join(parts)


def legacy_upgrade_detail(status: dict[str, Any]) -> str | None:
    hierarchy = status.get("hierarchy") if isinstance(status.get("hierarchy"), dict) else {}
    upgrade = hierarchy.get("control_plane_upgrade") if isinstance(
        hierarchy.get("control_plane_upgrade"), dict,
    ) else {}
    upgrade_status = upgrade.get("status")
    receipt_keys = {
        "upgrade_available": "legacy_upgrade_available",
        "reverification_required": "legacy_upgrade_reverification_required",
        "manual_decision_required": "legacy_upgrade_manual_decision_required",
        "blocked": "legacy_upgrade_blocked",
        "newer_than_cli": "legacy_upgrade_newer_than_cli",
    }
    if upgrade_status not in receipt_keys:
        return None
    steps = upgrade.get("pending_step_ids") if isinstance(upgrade.get("pending_step_ids"), list) else []
    suffix = f"steps={','.join(str(step) for step in steps)}" if steps else None
    return " | ".join(part for part in (
        bilingual_label(receipt_keys[str(upgrade_status)]),
        "action=legacy-upgrade inspect",
        suffix,
    ) if part)


def receipt_instruction(receipt: str) -> str:
    return (
        "在任何其他用户可见文本之前，逐字转发下面这条 Hook 回执一次，然后继续任务。"
        " Before any other user-visible text, relay the following Hook receipt verbatim exactly once, "
        "then continue the task:\n"
        f"{receipt}"
    )


def additional_context(event_name: str, text: str, receipt: str) -> dict[str, Any]:
    return {
        "systemMessage": receipt,
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": f"{text}\n\n{receipt_instruction(receipt)}",
        }
    }


def marker_path(root: Path, event: dict[str, Any]) -> Path | None:
    data_root = os.environ.get("PLUGIN_DATA")
    session_id = event.get("session_id")
    if not data_root or not isinstance(session_id, str) or not session_id:
        return None
    digest = hashlib.sha256(f"{session_id}\0{root}".encode("utf-8")).hexdigest()[:24]
    return Path(data_root).expanduser().resolve() / "session-markers" / f"{digest}.json"


def read_marker(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_marker(path: Path | None, event: dict[str, Any], status: dict[str, Any]) -> None:
    if path is None:
        return
    value = {
        "model": event.get("model"),
        "turn_id": event.get("turn_id"),
        "task_id": status.get("id"),
        "state_revision": status.get("state_revision"),
        "project_revision": status.get("project_revision"),
        "context_key": status.get("context_key"),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError:
        return


def pre_git_state_path(event: dict[str, Any]) -> Path | None:
    data_root = os.environ.get("PLUGIN_DATA")
    session_id = event.get("session_id")
    if not data_root or not isinstance(session_id, str) or not session_id:
        return None
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]
    return Path(data_root).expanduser().resolve() / "pre-git" / "sessions" / f"{digest}.json"


def read_pre_git_state(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or value.get("schema_version") != PRE_GIT_STATE_SCHEMA_VERSION:
        return {}
    return value


@contextlib.contextmanager
def pre_git_state_lock(path: Path) -> Iterator[None]:
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


def write_pre_git_state(path: Path | None, state: dict[str, Any]) -> bool:
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError:
        return False
    return True


def explicit_auto_dev_request(event: dict[str, Any]) -> bool:
    prompt = event.get("prompt")
    return isinstance(prompt, str) and EXPLICIT_AUTO_DEV_REFERENCE.search(prompt) is not None


def branch_context_key(root: Path) -> str:
    """Return the same branch identity used by the project/task resolver."""
    try:
        return runctl.branch_context_key(runctl.current_branch(root), runctl.git_head(root))
    except (OSError, ValueError, subprocess.CalledProcessError):
        return "unknown"


def auto_resume_status(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read the small identity projection used only to decide SessionStart activation."""
    return read_status_identity(root)


def should_auto_resume(status: dict[str, Any] | None) -> bool:
    if not isinstance(status, dict):
        return False
    state = status.get("status")
    if state not in AUTO_RESUME_STATUSES:
        return False
    if state == "selection_required":
        return True
    return bool(status.get("id"))


def writer_lease_detail(
    root: Path,
    event: dict[str, Any],
    status: dict[str, Any] | None = None,
) -> str:
    """Return a compact, non-sensitive role marker for receipts/context."""
    key = str((status or {}).get("context_key") or branch_context_key(root))
    lease = read_writer_lease_status(root, event, branch_key=key)
    state = lease.get("status")
    if state == "owned":
        role = "writer"
    elif state == "observer":
        role = "observer"
    elif state == "held":
        role = "writer-held"
    elif state == "conflict":
        role = "handoff-pending"
    elif state == "available":
        role = "writer-available"
    else:
        role = "writer-unavailable"
    return f"session-role={role}"


def mutation_intent(root: Path, event: dict[str, Any]) -> tuple[bool, bool, str]:
    """Classify a tool call as (control mutation, writer mutation, human label)."""
    tool_name = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = tool_input.get("command")
    if not isinstance(command, str):
        return False, False, "none"
    cwd = Path(str(event.get("cwd") or root)).expanduser().resolve()
    if tool_name == "apply_patch":
        return False, product_write_paths(root, event) is not None, "product-write"
    if tool_name != "Bash":
        return False, False, "none"
    segments = shell_segments(command)
    control = any(canonical_control_segment(tokens, cwd) for tokens in segments)
    product = any(product_write_segment(tokens, cwd) for tokens in segments)
    external = bool(external_action_labels(command))
    if control:
        return True, True, "control-mutation"
    if product:
        return False, True, "product-write"
    if external:
        return False, False, "external-action"
    return False, False, "none"


def writer_lease_gate(
    root: Path,
    event: dict[str, Any],
    status: dict[str, Any] | None,
    *,
    mutation: bool,
    label: str,
) -> str | None:
    """Acquire the branch writer only at the point a managed write is allowed."""
    if not mutation:
        return None
    if not isinstance(status, dict):
        return (
            f"Auto Dev status is unavailable before {label}; the session writer lease cannot be verified. "
            "Product/control writes are blocked until compact status is readable."
        )
    key_value = status.get("context_key")
    if not isinstance(key_value, str) or not key_value:
        return (
            f"Auto Dev has no branch context for {label}; the session writer lease cannot be verified. "
            "Reconcile the current control state before writing."
        )
    key = key_value
    task_id = status.get("id") if isinstance(status, dict) else None
    revision = status.get("state_revision") if isinstance(status, dict) else None
    lease = claim_writer_lease(
        root,
        event,
        branch_key=key,
        task_id=task_id if isinstance(task_id, str) else None,
        state_revision=revision if isinstance(revision, int) else None,
        mutation=True,
    )
    state = lease.get("status")
    if state in {"owned", "acquired", "taken_over"}:
        return None
    if state == "observer":
        return (
            f"This session is an Auto Dev observer after writer handoff; {label} is read-only. "
            "Continue reading status/progress, or start a fresh handoff after the current writer releases/ expires."
        )
    if state == "conflict":
        return (
            f"Another Auto Dev session is in an in-flight {label}; writer handoff is temporarily paused. "
            "Wait for that mutation to settle, then retry so revision/CAS protection remains intact."
        )
    return (
        f"Auto Dev could not acquire the session writer lease for {label}; product/control writes are blocked. "
        "Restore PLUGIN_DATA access and retry after the lease becomes available."
    )


def pre_git_state_for_event(cwd: Path, event: dict[str, Any], *, create: bool) -> dict[str, Any] | None:
    path = pre_git_state_path(event)
    explicit_request = create and explicit_auto_dev_request(event)
    if path is None or (not path.is_file() and not explicit_request):
        return None
    try:
        with pre_git_state_lock(path):
            state = read_pre_git_state(path)
            workspace_root = state.get("workspace_root") if state else None
            if isinstance(workspace_root, str):
                try:
                    root = Path(workspace_root).resolve()
                    cwd.resolve().relative_to(root)
                except (OSError, ValueError):
                    state = {}
            if not state and explicit_request:
                root = cwd.expanduser().resolve()
                session_id = event.get("session_id")
                if not isinstance(session_id, str) or not session_id:
                    return None
                state = {
                    "schema_version": PRE_GIT_STATE_SCHEMA_VERSION,
                    "workspace_root": str(root),
                    "workspace_fingerprint": hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16],
                    "session_fingerprint": hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24],
                    "status": "pending",
                    "created_at": int(time.time()),
                }
            if not state:
                return None
            if event.get("hook_event_name") == "UserPromptSubmit":
                turn_id = event.get("turn_id")
                if isinstance(turn_id, str) and turn_id:
                    state["pending_turn_id"] = turn_id
                state["updated_at"] = int(time.time())
                state["status"] = "pending"
                if not write_pre_git_state(path, state):
                    return None
            return state
    except OSError:
        # PLUGIN_DATA can be unavailable or read-only; dispatch emits the existing fallback receipt.
        return None


def pre_git_context(state: dict[str, Any]) -> str:
    turn_id = state.get("pending_turn_id") or "current-turn"
    return (
        "Auto Dev is in a pre-Git project-discovery gate. Do not write product files and do not "
        "claim a canonical Intake assessment yet. First inspect the workspace, then present one menu: "
        "[1] initialize Git and establish the control plane (recommended when Git is available), "
        "[2] continue read-only discovery and choose storage later, or [3] explicitly establish "
        "a local No-Git control plane. After Git/local initialization, record this same user turn "
        f"through canonical intake turn and assess before product writes. pending_turn={turn_id}.\n"
        "当前处于 pre-Git 项目发现 gate：不得写产品文件，也不得伪造 Intake 已评估。先检查工作区，"
        "再让用户选择初始化 Git、继续只读澄清，或明确建立 local No-Git 控制面；建立控制面后，"
        "必须为当前用户 turn 记录 canonical intake turn/assess。"
    )


def pre_git_gate_reason(root: Path, event: dict[str, Any]) -> str | None:
    if product_write_paths(root, event) is None:
        return None
    return (
        "Pre-Git project discovery is active; product write blocked. "
        "First choose Git setup, explicit local No-Git control, or continue read-only requirement discovery."
    )


def protection_reason(root: Path, event: dict[str, Any]) -> str | None:
    tool_name = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    if tool_name == "apply_patch":
        if any(is_auto_dev_path(path) for path in patch_paths(command)):
            return "Direct edits to .auto-dev state are not allowed; use auto_dev.py mutations."
        return None
    if tool_name != "Bash":
        return None
    if LEGACY_POLICY_COMMAND.search(command):
        return "Workspace policy commands require the canonical auto_dev.py policy entrypoint."
    if LEGACY_RUN_MUTATION.search(command) or LEGACY_DEP_MUTATION.search(command):
        return "Compatibility entrypoints cannot mutate Auto Dev state; use auto_dev.py."
    cwd = Path(str(event.get("cwd") or root)).expanduser().resolve()
    if direct_state_write(command, cwd):
        return "Direct shell writes to .auto-dev are not allowed; use auto_dev.py mutations."
    return None


def product_write_paths(root: Path, event: dict[str, Any]) -> list[str] | None:
    tool_name = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = tool_input.get("command")
    if tool_name == "apply_patch" and isinstance(command, str):
        paths = [normalize_patch_path(root, path) for path in patch_paths(command)]
        if not paths:
            return []
        product_paths = [path for path in paths if not is_control_metadata_path(path)]
        return product_paths or None
    if tool_name == "Bash" and isinstance(command, str):
        cwd = Path(str(event.get("cwd") or root)).expanduser().resolve()
        if any(product_write_segment(tokens, cwd) for tokens in shell_segments(command)):
            return []
    return None


def intake_gate_reason(
    root: Path,
    event: dict[str, Any],
    status: dict[str, Any] | None = None,
) -> str | None:
    if product_write_paths(root, event) is None:
        return None
    if status is None:
        status, error = read_status(root, session_key=intake_session_key(root, event))
        if status is None:
            return f"需求澄清状态不可用 / Intake state is unavailable: {error or 'unknown error'}"
    gate = status.get("intake_gate") if isinstance(status.get("intake_gate"), dict) else {}
    gate_status = gate.get("status")
    if gate_status not in {"pending", "awaiting_user", "awaiting_confirmation"}:
        return None
    turn_id = gate.get("pending_turn_id") or "current-turn"
    session_key = gate.get("session_key") or "current-session"
    if gate_status == "pending":
        next_action = (
            "run auto_dev.py intake assess --session-key "
            f"{session_key} --turn-id {turn_id} ..."
        )
    elif gate_status == "awaiting_user":
        next_action = "ask only the recorded pending user decisions, then resolve them on the later user turn"
    else:
        next_action = "obtain the explicit Requirement Baseline confirmation, then run intake confirm"
    return (
        "需求澄清尚未完成，产品写入已阻止 / Requirement intake is incomplete; product write blocked. "
        f"Next: {next_action}."
    )


def policy_rule_matches(path: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    return pattern.endswith("/**") and path == pattern[:-3].rstrip("/")


def workspace_policy_reason(
    root: Path,
    event: dict[str, Any],
    status: dict[str, Any] | None = None,
) -> str | None:
    paths = product_write_paths(root, event)
    if paths is None:
        return None
    if status is None:
        status, error = read_status(root, session_key=intake_session_key(root, event))
        if status is None:
            return f"🚧 Auto Dev Policy: policy_unavailable | {error or 'unknown error'}"
    projection = status.get("workspace_policy")
    if not isinstance(projection, dict):
        return None
    if projection.get("status") == "unavailable":
        return (
            "🚧 Auto Dev Policy: policy_unavailable | product write blocked until config.json is repaired: "
            + str(projection.get("error") or "unknown error")
        )
    if not paths:
        if projection.get("active"):
            return (
                "🚧 Auto Dev Policy: path_required | active path policy cannot verify this Bash write; "
                "use apply_patch or another operation whose target paths are explicit."
            )
        return None

    effective = projection.get("effective_rules") if isinstance(projection.get("effective_rules"), dict) else {}
    approvals = projection.get("approvals") if isinstance(projection.get("approvals"), dict) else {}
    fresh_approvals = [
        approval for approval in limited(approvals.get("records"), limit=100)
        if isinstance(approval, dict) and approval.get("fresh")
    ]
    sensitive = projection.get("sensitive_evidence") if isinstance(
        projection.get("sensitive_evidence"), dict,
    ) else {}
    for path in paths:
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts or any(character in path for character in "*?["):
            return f"🚧 Auto Dev Policy: invalid_path | product write path is not repository-relative: {path}"
        matches = {
            kind: [
                rule for rule in limited(effective.get(kind), limit=200)
                if isinstance(rule, dict)
                and isinstance(rule.get("pattern"), str)
                and policy_rule_matches(path, str(rule["pattern"]))
            ]
            for kind in ("forbidden_paths", "approval_paths", "sensitive_paths")
        }
        if matches["forbidden_paths"]:
            rule = matches["forbidden_paths"][0]
            return (
                f"🚧 Auto Dev Policy: forbidden_path | {path} matches {rule.get('id')}: "
                f"{rule.get('reason')}."
            )
        if matches["approval_paths"] and not any(
            path in limited(approval.get("paths"), limit=100) for approval in fresh_approvals
        ):
            revision = projection.get("revision")
            state_revision = status.get("state_revision")
            node = (status.get("continuity_summary") or {}).get("current_node")
            return (
                f"🚧 Auto Dev Policy: approval_required | {path} requires current user approval. "
                "Run auto_dev.py policy approve "
                f"--policy-revision {revision} --state-revision {state_revision} --node {node} "
                f"--path {path} --confirmation-source ... --reason ...."
            )
        if matches["sensitive_paths"] and not sensitive.get("ready"):
            missing = ",".join(str(value) for value in limited(sensitive.get("missing"), limit=8))
            return (
                f"🚧 Auto Dev Policy: sensitive_evidence_required | {path} requires an active Plan node, "
                f"validation plan, node proof contract, and redacted evidence; missing={missing or 'unknown'}."
            )
    return None


def product_write_reason(
    root: Path, event: dict[str, Any], status: dict[str, Any] | None = None,
) -> str | None:
    paths = product_write_paths(root, event)
    if paths is None:
        return None
    if status is None:
        status, error = read_status(root, session_key=intake_session_key(root, event))
        if status is None:
            return f"Auto Dev status is unavailable before product write: {error or 'unknown error'}"
    if status.get("status") == "review_ready":
        revision = status.get("state_revision")
        return (
            "Product writes are blocked while the current task is review_ready; "
            "for related user feedback run auto_dev.py task resume "
            f"--state-revision {revision} --reason ... --confirmation-source ..., "
            "or archive it with finish --status passed after explicit user acceptance."
        )
    if not status.get("id") or status.get("status") != "active":
        return "Product writes require an active Auto Dev task selected for the current branch."
    checkpoint_protection = status.get("workspace_checkpoint_protection")
    checkpoint_protection = checkpoint_protection if isinstance(checkpoint_protection, dict) else {}
    before_pending = [
        str(value) for value in limited(checkpoint_protection.get("before_pending"), limit=8)
        if str(value)
    ]
    before_invalid = [
        str(value) for value in limited(checkpoint_protection.get("before_invalid"), limit=8)
        if str(value)
    ]
    if before_pending:
        return (
            "Product writes are blocked until the protected baseline checkpoint is recorded: "
            + ", ".join(before_pending)
            + ". Run auto_dev.py workspace checkpoint inspect --kind baseline --protection-id ... "
            "then workspace checkpoint create --kind baseline --protection-id ... --confirmation-source ...."
        )
    if before_invalid:
        return (
            "Product writes are blocked because the protected baseline ref is missing or mismatched: "
            + ", ".join(before_invalid)
            + ". Inspect workspace checkpoint list and reconcile the protection before writing."
        )
    contract_gate = status.get("contract_gate") if isinstance(status.get("contract_gate"), dict) else {}
    contract_capsule = status.get("contract_capsule") if isinstance(status.get("contract_capsule"), dict) else {}
    gate_status = contract_gate.get("status")
    if gate_status in {"stale", "plan_stale", "plan_incomplete", "unavailable"} and contract_capsule.get("status") == "strict":
        return (
            "Product writes are blocked by the strict inherited contract gate: "
            f"contract_{gate_status}. Reconcile the effective contract and current plan first."
        )
    prewrite_missing = limited(contract_gate.get("prewrite_missing"), limit=8)
    if contract_capsule.get("status") == "strict" and prewrite_missing:
        return (
            "Product writes are blocked until inherited prewrite coverage passes: "
            + ", ".join(str(value) for value in prewrite_missing)
            + ". Complete the reference/compatibility proof first."
        )
    write_blockers = status.get("product_write_blockers")
    if not isinstance(write_blockers, list):
        write_blockers = status.get("strict_blockers")
    blockers = [str(value) for value in limited(write_blockers, limit=20) if str(value)]
    if blockers:
        return "Product writes are blocked by unresolved Auto Dev strict state: " + ", ".join(blockers)
    summary = status.get("continuity_summary")
    summary = summary if isinstance(summary, dict) else {}
    if paths and summary.get("plan_strategy") == "rolling_graph":
        role = summary.get("current_node_role")
        node_id = summary.get("current_node")
        scopes = [
            str(value) for value in limited(summary.get("active_write_scope"), limit=100)
            if isinstance(value, str) and value
        ]
        if role not in {"work_packet", "integration"} or not node_id:
            return (
                "Rolling Graph product writes require an active work_packet or integration node; "
                "compile the ready Milestone or advance the ready frontier first."
            )
        outside = [
            path for path in paths
            if not any(
                policy_rule_matches(path, scope)
                or path.startswith(scope.rstrip("/") + "/")
                for scope in scopes
            )
        ]
        if outside:
            return (
                f"Rolling Graph product write escapes active node {node_id} write_scope: "
                + ", ".join(outside[:4])
            )
    if paths:
        contract = status.get("delivery_contract") if isinstance(status.get("delivery_contract"), dict) else {}
        scopes = limited(contract.get("planned_scope"), limit=100)
        if scopes:
            outside = [
                path for path in paths
                if not any(path == scope or path.startswith(scope.rstrip("/") + "/") for scope in scopes)
            ]
            if outside:
                return "Product write escapes the active task scope: " + ", ".join(outside[:4])
    return None


def quick_write_allowed(
    root: Path, event: dict[str, Any], status: dict[str, Any] | None = None,
) -> bool:
    """Allow a bounded one-turn patch only when no task currently owns the branch."""
    if str(event.get("tool_name") or "") != "apply_patch":
        return False
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = tool_input.get("command")
    if not isinstance(command, str) or quick_patch_details(root, command) is None:
        return False
    if status is None:
        status, _ = read_status(root, session_key=intake_session_key(root, event))
    if not isinstance(status, dict):
        return False
    gate = status.get("intake_gate") if isinstance(status.get("intake_gate"), dict) else {}
    if gate.get("status") not in {None, "unobserved", "authorized"}:
        return False
    if status.get("protected_branch") is not False:
        return False
    return status.get("status") in {"idle", "selection_required"}


def external_action_requirements(command: str) -> list[dict[str, Any]]:
    import hook_commands
    return hook_commands.external_action_requirements(sys.modules[__name__], command)


def external_action_labels(command: str) -> list[str]:
    import hook_commands
    return hook_commands.external_action_labels(sys.modules[__name__], command)


def external_action_reason(
    root: Path, event: dict[str, Any], status: dict[str, Any] | None = None,
) -> str | None:
    tool_name = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = tool_input.get("command")
    if tool_name != "Bash" or not isinstance(command, str):
        return None
    labels = external_action_labels(command)
    if not labels:
        return None
    error = None
    if status is None:
        status, error = read_status(root, profile="gate")
    if status is None:
        return f"Auto Dev status is unavailable before external action: {error or 'unknown error'}"
    if not status.get("id") or status.get("status") != "active":
        return "External actions require an active Auto Dev task selected for the current branch."
    summary = status.get("continuity_summary") if isinstance(status.get("continuity_summary"), dict) else {}
    node_id = summary.get("current_node")
    if not node_id:
        return (
            "External actions require a current continuity node; revise the plan or checkpoint the "
            "intended node before starting device work."
        )
    blockers = [
        str(value) for value in limited(status.get("strict_blockers"), limit=20)
        if str(value) and str(value) != "pending_action"
    ]
    if blockers:
        return "External actions are blocked by unresolved Auto Dev strict state: " + ", ".join(blockers)
    pending = summary.get("pending_action")
    if not isinstance(pending, dict):
        return (
            "External actions require an opened action record; first run auto_dev.py event "
            f"--phase started --node {node_id} --action-id ... ."
        )
    if pending.get("node_id") != node_id:
        return (
            "Pending action does not belong to the current continuity node; close or reconcile it "
            "before starting another external action."
        )
    return None


def dependency_gate(root: Path, capability: str, argv: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    _, stdout, stderr = invoke_handler(
        project_memory.parser(),
        [
            "gate",
            "--repo-root",
            str(root),
            "--capability",
            capability,
            "--argv-json",
            json.dumps(argv, ensure_ascii=False),
        ],
    )
    try:
        value = json.loads(stdout) if stdout.strip() else None
    except json.JSONDecodeError:
        value = None
    if not isinstance(value, dict):
        detail = stderr.strip().splitlines()[-1] if stderr.strip() else "dependency gate returned no JSON"
        return None, detail[:500]
    return value, None


def dependency_gate_reason(
    root: Path, event: dict[str, Any], control_status: dict[str, Any] | None = None,
) -> str | None:
    tool_name = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = tool_input.get("command")
    if tool_name != "Bash" or not isinstance(command, str):
        return None
    for requirement in external_action_requirements(command):
        capability = requirement.get("capability")
        if not isinstance(capability, str):
            continue
        argv = requirement.get("argv")
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            return f"Dependency gate could not parse the managed action: {requirement['label']}"
        decision, error = dependency_gate(root, capability, argv)
        if decision is None:
            return f"Dependency gate is unavailable before {requirement['label']}: {error or 'unknown error'}"
        status = decision.get("status")
        if status == "allowed":
            continue
        if status == "preflight-permitted":
            permit = decision.get("permit") if isinstance(decision.get("permit"), dict) else {}
            control = control_status
            control_error = None
            if control is None:
                control, control_error = read_status(root, profile="gate")
            pending = (
                control.get("continuity_summary", {}).get("pending_action")
                if isinstance(control, dict) and isinstance(control.get("continuity_summary"), dict)
                else None
            )
            if control is None:
                return f"Auto Dev status is unavailable before dependency preflight: {control_error or 'unknown error'}"
            if not isinstance(pending, dict) or pending.get("action_id") != permit.get("action_id"):
                return "Dependency preflight permit does not match the current node-bound pending action."
            continue
        reason = str(decision.get("reason") or "lease_required")
        return (
            f"Managed dependency lease required for {capability} before {requirement['label']}: {reason}. "
            "Resolve a known-good recipe and write its lease, or open a bounded canonical deps preflight."
        )
    return None


def deny(reason: str) -> dict[str, Any]:
    receipt = hook_receipt("pre_tool_use_denied", detail=reason)
    return {
        "systemMessage": receipt,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
            "additionalContext": receipt_instruction(receipt),
        },
    }


def self_target_protection_reason(root: Path, event: dict[str, Any]) -> str | None:
    reason = protection_reason(root, event)
    if reason:
        return reason
    if str(event.get("tool_name") or "") != "Bash":
        return None
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = tool_input.get("command")
    if isinstance(command, str) and any(self_target_control_segment(tokens) for tokens in shell_segments(command)):
        return (
            "Auto Dev will not create or mutate a control plane inside its own Plugin source. "
            "Use a neutral workspace or an explicit test fixture."
        )
    return None


def self_target_dispatch(root: Path, event: dict[str, Any]) -> dict[str, Any] | None:
    event_name = event.get("hook_event_name")
    if event_name == "PreToolUse":
        reason = self_target_protection_reason(root, event)
        return deny(reason) if reason else None
    if event_name != "SessionStart":
        return None
    receipt = hook_receipt("plugin_self_target", detail="target=auto-dev")
    text = (
        "Auto Dev detected its own Plugin source directory. The directory is read/write source material, "
        "not a managed product project: do not create .auto-dev, initialize Git for control-plane adoption, "
        "or restore stale pre-Git state here. Use a neutral workspace for Auto Dev delivery."
    )
    return additional_context("SessionStart", text, receipt)


def _dispatch(event: dict[str, Any]) -> dict[str, Any] | None:
    event_name = event.get("hook_event_name")
    cwd = Path(str(event.get("cwd") or os.getcwd()))
    self_target = auto_dev_plugin_root(cwd)
    if self_target is not None:
        return self_target_dispatch(self_target, event)
    root = locate_project(cwd)
    if root is None:
        pre_git = pre_git_state_for_event(
            cwd,
            event,
            create=event_name == "UserPromptSubmit",
        )
        if event_name == "PreToolUse":
            if pre_git is None:
                return None
            workspace_root = Path(str(pre_git["workspace_root"])).expanduser().resolve()
            reason = pre_git_gate_reason(workspace_root, event)
            return deny(reason) if reason else None
        if event_name == "UserPromptSubmit" and pre_git is not None:
            if explicit_auto_dev_request(event) and not activate_session(cwd, event):
                receipt = hook_receipt("session_activation_unavailable")
                text = (
                    "Auto Dev recorded the pre-Git discovery gate but could not persist the current session "
                    "activation for the post-initialization control plane. Keep this workspace read-only, "
                    "restore PLUGIN_DATA access, then invoke $auto-dev again after project initialization "
                    "before product writes."
                )
                return additional_context("UserPromptSubmit", text, receipt)
            receipt = hook_receipt(
                "pre_git_intake_pending",
                detail=f"turn={pre_git.get('pending_turn_id') or 'current-turn'}",
            )
            return additional_context("UserPromptSubmit", pre_git_context(pre_git), receipt)
        if event_name == "UserPromptSubmit" and explicit_auto_dev_request(event):
            receipt = hook_receipt("pre_git_guard_unavailable")
            text = (
                "Auto Dev detected an explicit pre-Git request but PLUGIN_DATA is unavailable, so a hard "
                "pre-Git gate cannot be recorded. Stay read-only, report this limitation, and ask the user "
                "to choose Git setup or an explicit local control plane before product writes."
            )
            return additional_context("UserPromptSubmit", text, receipt)
        return None

    # A managed project is enough evidence to restore a new session's compact
    # context. Activation remains disposable runtime state; it does not alter
    # the project/task receipt and it does not claim the writer lease.
    if event_name == "SessionStart" and not session_is_active(root, event):
        resume_status, resume_error = auto_resume_status(root)
        if should_auto_resume(resume_status):
            if not activate_session(root, event, source="session_start_auto_resume"):
                receipt = hook_receipt("session_activation_unavailable")
                text = (
                    "Auto Dev found an existing branch task but could not persist this session's read-only "
                    "resume activation. Restore PLUGIN_DATA access before product or control writes."
                )
                return additional_context("SessionStart", text, receipt)
        elif resume_error and event.get("source") in {"startup", "resume", "clear", "compact"}:
            # Preserve the existing quiet behavior when identity cannot be read;
            # the normal active-session path below will emit a diagnostic only
            # for sessions that were already explicitly enabled.
            return None

    explicit_request = event_name == "UserPromptSubmit" and explicit_auto_dev_request(event)
    if explicit_request and not activate_session(root, event):
        receipt = hook_receipt("session_activation_unavailable")
        text = (
            "Auto Dev received an explicit request but could not persist the current session activation. "
            "Restore PLUGIN_DATA access, then invoke $auto-dev again before product writes. "
            "Do not treat this session as mechanically protected."
        )
        return additional_context("UserPromptSubmit", text, receipt)

    if event_name == "PreToolUse":
        reason = protection_reason(root, event)
        if reason is not None:
            return deny(reason)
        if not session_is_active(root, event):
            return None
        control_mutation, side_effect, mutation_label = mutation_intent(root, event)
        status: dict[str, Any] | None = None
        if side_effect or control_mutation:
            status, _ = read_status(
                root, session_key=intake_session_key(root, event), profile="gate"
            )
            if status is None:
                return deny(
                    f"Auto Dev status is unavailable before {mutation_label}; "
                    "the session writer lease cannot be verified."
                )
            # A superseded session must be rejected before ordinary policy
            # diagnostics obscure the handoff explanation.
            lease_key = str(status.get("context_key") or branch_context_key(root))
            lease_state = read_writer_lease_status(root, event, branch_key=lease_key)
            if lease_state.get("status") == "observer":
                reason = writer_lease_gate(root, event, status, mutation=True, label=mutation_label)
                return deny(reason or "This session is read-only after writer handoff.")
            if product_write_paths(root, event) is not None:
                reason = intake_gate_reason(root, event, status)
        if reason is None:
            reason = workspace_policy_reason(root, event, status)
        if reason is None and quick_write_allowed(root, event, status):
            reason = writer_lease_gate(root, event, status, mutation=True, label=mutation_label)
            return deny(reason) if reason else None
        if reason is None:
            reason = external_action_reason(root, event, status)
        if reason is None:
            reason = dependency_gate_reason(root, event, status)
        if reason is None:
            reason = product_write_reason(root, event, status)
        if reason is None and side_effect:
            reason = writer_lease_gate(root, event, status, mutation=True, label=mutation_label)
        return deny(reason) if reason else None

    if not session_is_active(root, event):
        return None

    marker = marker_path(root, event)
    session_key = intake_session_key(root, event)
    if event_name == "SessionStart":
        reason = f"session_{event.get('source') or 'startup'}"
    elif event_name == "SubagentStart":
        reason = f"subagent_{event.get('agent_type') or 'unknown'}"
    elif event_name == "UserPromptSubmit":
        reason = "hook_activated"
    else:
        return None

    identity_only = event_name == "UserPromptSubmit"
    if identity_only:
        status, error = read_status_identity(root)
    else:
        status, error = read_status(root, session_key=session_key)
    if status is None:
        text = (
            "Auto Dev control state exists but compact status is unavailable. "
            f"Diagnostic: {error or 'unknown error'}. Run auto_dev.py status --compact --strict, "
            "then recover or reconcile before affected writes."
        )
        receipt = hook_receipt("status_unavailable", detail=f"event={event_name}")
        return additional_context(str(event_name), text, receipt)

    lease_key = str(status.get("context_key") or branch_context_key(root))
    if event_name == "SessionStart":
        # Refresh only an existing owner. A newly resumed session remains an
        # observer until its first canonical mutation or product write.
        touch_writer_lease(
            root,
            event,
            branch_key=lease_key,
            task_id=status.get("id") if isinstance(status.get("id"), str) else None,
            state_revision=status.get("state_revision") if isinstance(status.get("state_revision"), int) else None,
        )
        invalidate_hook_control_cache(root)
    elif event_name == "UserPromptSubmit" and not (
        isinstance(event.get("turn_id"), str) and event.get("turn_id")
    ):
        # Older hosts may omit turn_id. Keep an existing owner alive without
        # letting a reader session claim ownership merely by observing.
        touch_writer_lease(
            root,
            event,
            branch_key=lease_key,
            task_id=status.get("id") if isinstance(status.get("id"), str) else None,
            state_revision=status.get("state_revision") if isinstance(status.get("state_revision"), int) else None,
        )
        invalidate_hook_control_cache(root)

    intake_detail = None
    if event_name == "UserPromptSubmit":
        turn_id = event.get("turn_id")
        if isinstance(turn_id, str) and turn_id:
            # The Hook's bounded intake turn is itself a canonical control
            # mutation. Serialize it with the same lease as CLI/product writes.
            lease_reason = writer_lease_gate(
                root, event, status, mutation=True, label="intake-turn"
            )
            if lease_reason:
                receipt = hook_receipt(
                    "hook_activated",
                    status=status,
                    detail="session-role=observer",
                )
                return additional_context(
                    "UserPromptSubmit",
                    lease_reason + " No intake turn was recorded for this observer session.",
                    receipt,
                )
        recorded, intake_error = record_intake_turn(root, event, status)
        if intake_error:
            text = (
                "Auto Dev could not record the current Intake turn. "
                f"需求澄清 turn 无法记录。Diagnostic / 诊断: {intake_error}. "
                "Do not write product files until the canonical Intake state is available."
            )
            receipt = hook_receipt("status_unavailable", status=status, detail="intake_turn")
            return additional_context(str(event_name), text, receipt)
        if recorded is not None:
            invalidate_hook_control_cache(root)
            status, error = read_status(root, session_key=session_key)
            identity_only = False
            if status is None:
                text = (
                    "Auto Dev recorded an Intake turn but could not read the resulting control state. "
                    f"需求澄清 turn 已记录但控制状态不可读。Diagnostic / 诊断: {error or 'unknown error'}."
                )
                receipt = hook_receipt("status_unavailable", detail="intake_turn_readback")
                return additional_context(str(event_name), text, receipt)
            intake_detail = f"{bilingual_label('intake_turn_pending')} | turn={recorded.get('turn_id')}"

    identity = {
        "task_id": status.get("id"),
        "state_revision": status.get("state_revision"),
        "project_revision": status.get("project_revision"),
        "context_key": status.get("context_key"),
    }
    if event_name == "UserPromptSubmit" and intake_detail is None:
        previous = read_marker(marker)
        current = {"model": event.get("model"), **identity}
        if previous == current:
            return None
        if previous and previous.get("model") != current["model"]:
            reason = "model_changed"
        elif previous and (
            previous.get("task_id") != current.get("task_id")
            or previous.get("context_key") != current.get("context_key")
        ):
            reason = "active_task_changed"
        elif previous:
            reason = "control_state_changed"

    if identity_only:
        status, error = read_status(root, session_key=session_key)
        if status is None:
            text = (
                "Auto Dev control identity changed but compact status is unavailable. "
                f"Diagnostic: {error or 'unknown error'}. Reconcile before affected writes."
            )
            receipt = hook_receipt("status_unavailable", detail="identity_readback")
            return additional_context(str(event_name), text, receipt)

    if status.get("status") == "selection_required":
        write_marker(marker, event, status)
        detail_parts = []
        if event_name == "SessionStart":
            detail_parts.extend([progress_link_detail(root, session_key), writer_lease_detail(root, event, status)])
        detail = " | ".join(part for part in detail_parts if part) or None
        receipt = hook_receipt("task_selection_required", status=status, detail=detail)
        return additional_context(
            str(event_name),
            control_context(root, status, "task_selection_required"),
            receipt,
        )

    if event_name == "SubagentStart":
        contract = status.get("delivery_contract") if isinstance(status.get("delivery_contract"), dict) else {}
        capabilities = contract.get("capabilities") if isinstance(contract.get("capabilities"), dict) else {}
        continuity = status.get("continuity") if isinstance(status.get("continuity"), dict) else {}
        plan = continuity.get("plan") if isinstance(continuity.get("plan"), dict) else {}
        worker_lane_selected = any(
            isinstance(node, dict)
            and node.get("node_role") == "milestone"
            and isinstance(node.get("milestone_state"), dict)
            and isinstance(node["milestone_state"].get("execution_decision"), dict)
            and node["milestone_state"]["execution_decision"].get("status")
            in {"selected", "awaiting_main"}
            and node["milestone_state"]["execution_decision"].get("selected_mode")
            in {"single_worker", "multi_worker"}
            for node in plan.get("nodes", [])
        )
        if (
            "parallel-work" not in limited(capabilities.get("enabled"), limit=20)
            and not worker_lane_selected
        ):
            return None
        receipt = hook_receipt(reason, status=status)
        return additional_context(
            "SubagentStart",
            control_context(root, status, reason, subagent=True),
            receipt,
        )

    write_marker(marker, event, status)
    if event_name == "SessionStart":
        detail_parts = [
            progress_link_detail(root, session_key),
            writer_lease_detail(root, event, status),
            legacy_upgrade_detail(status),
        ]
        detail = " | ".join(part for part in detail_parts if part)
    else:
        detail = intake_detail
    receipt = hook_receipt(reason, status=status, detail=detail)
    pulse = contract_pulse(status, reason) if event_name == "UserPromptSubmit" else None
    context = pulse or control_context(root, status, reason)
    return additional_context(str(event_name), context, receipt)


def dispatch(event: dict[str, Any]) -> dict[str, Any] | None:
    with hook_evaluation_scope():
        return _dispatch(event)


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        if not isinstance(event, dict):
            return 0
        output = dispatch(event)
        if output is not None:
            print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        # Lifecycle assistance must not make an unrelated coding turn fail.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
