#!/usr/bin/env python3
"""Single CLI front door for the auto-dev control plane.

Usage:
  python3 auto_dev.py --help
  python3 auto_dev.py status --repo-root . --compact --strict
  python3 auto_dev.py checkpoint --help
  python3 auto_dev.py deps resolve --repo-root . --capability android-instrumentation --write-lease
  python3 auto_dev.py deps gate --repo-root . --capability android-instrumentation --argv-json '["/absolute/tool"]'
  python3 auto_dev.py environment inspect --repo-root .
  python3 auto_dev.py domain inspect --repo-root .
  python3 auto_dev.py progress --repo-root . --port 0
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

import runctl


CLI_SCHEMA_VERSION = 17
RUN_COMMANDS = {
    "project",
    "project-context",
    "intake",
    "outcome",
    "capability",
    "activity",
    "focus",
    "task",
    "fix",
    "legacy-upgrade",
    "snapshot",
    "start",
    "escalate",
    "capabilities",
    "event",
    "evidence",
    "plan",
    "milestone",
    "proof",
    "debug",
    "memory",
    "checkpoint",
    "policy",
    "impact",
    "workspace",
    "diagnostics",
    "finish",
    "abandon",
    "handoff",
    "recover",
    "migrate",
    "bootstrap",
    "refresh",
    "resume",
    "status",
    "transition",
}
SPECIAL_COMMANDS = {"deps", "progress", "environment", "domain", "version", "help"}


def script_path(name: str) -> pathlib.Path:
    return pathlib.Path(__file__).resolve().with_name(name)


def help_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stable CLI front door for auto-dev continuity, dependencies, and progress.",
        epilog=(
            "Run `auto_dev.py help <command>` for command help. "
            "Existing runctl.py, dependency_manager.py, and progress_server.py entrypoints remain compatible."
        ),
    )
    parser.add_argument(
        "command",
        nargs="?",
        help=(
            "run control: start/escalate/capabilities/event/evidence/plan/milestone/checkpoint/diagnostics/"
            "proof/debug/memory/policy/impact/finish/abandon/handoff/recover/migrate/legacy-upgrade/snapshot/bootstrap/project/project-context/intake/"
            "outcome/capability/activity/focus/task/fix/refresh/resume/status/workspace; "
            "transition; "
            "other: deps/environment/domain/progress/version/help"
        ),
    )
    return parser


def run_child(script: str, arguments: list[str]) -> int:
    display = "auto_dev.py"
    if script == "dependency_manager.py":
        display += " deps"
    elif script == "progress_server.py":
        display += " progress"
    environment = dict(os.environ)
    environment["AUTO_DEV_CLI_PROG"] = display
    argv = [sys.executable, str(script_path(script)), *arguments]
    try:
        os.execvpe(sys.executable, argv, environment)
    except OSError as error:
        print(f"auto_dev.py: cannot execute {script}: {error}", file=sys.stderr)
        return 126


def command_help(arguments: list[str]) -> int:
    if not arguments:
        help_parser().print_help()
        return 0
    target, *rest = arguments
    if rest:
        print("auto_dev.py: help accepts exactly one command", file=sys.stderr)
        return 2
    if target in RUN_COMMANDS:
        return run_child("runctl.py", [target, "--help"])
    if target == "deps":
        return run_child("dependency_manager.py", ["--help"])
    if target == "progress":
        return run_child("progress_server.py", ["--help"])
    if target in {"environment", "domain"}:
        return run_child("project_memory.py", [target, "--help"])
    print(f"auto_dev.py: unknown command for help: {target}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"-h", "--help"}:
        help_parser().print_help()
        return 0

    command, *forwarded = arguments
    if command not in RUN_COMMANDS | SPECIAL_COMMANDS:
        print(f"auto_dev.py: unknown command: {command}", file=sys.stderr)
        return 2
    if command in RUN_COMMANDS:
        return run_child("runctl.py", [command, *forwarded])
    if command == "deps":
        return run_child("dependency_manager.py", forwarded)
    if command == "progress":
        return run_child("progress_server.py", forwarded)
    if command in {"environment", "domain"}:
        return run_child("project_memory.py", [command, *forwarded])
    if command == "version":
        if forwarded:
            print("auto_dev.py: version accepts no arguments", file=sys.stderr)
            return 2
        print(json.dumps({
            "cli_schema_version": CLI_SCHEMA_VERSION,
            "state_schema_version": runctl.SCHEMA_VERSION,
            "project_schema_version": runctl.PROJECT_SCHEMA_VERSION,
            "control_plane_upgrade_version": runctl.CONTROL_PLANE_UPGRADE_VERSION,
        }, ensure_ascii=False))
        return 0
    return command_help(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
