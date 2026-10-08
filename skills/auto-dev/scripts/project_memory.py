#!/usr/bin/env python3
"""Stable project-memory CLI facade and compatibility import surface.

Storage, entry, lease, and query domains live in the internal memory package while the
legacy ``project_memory.py`` path keeps its parser, handlers, and symbols.
"""
from __future__ import annotations

import argparse
import sys

from auto_dev_internal.memory.store import *
from auto_dev_internal.memory.entries import *
from auto_dev_internal.memory.leases import *
from auto_dev_internal.memory.queries import *
from auto_dev_internal.memory import cases as project_memory_cases
from auto_dev_internal.memory import profiles as project_memory_profiles

def memory_digest(document: dict[str, Any]) -> str:
    return project_memory_cases.memory_digest(sys.modules[__name__], document)


def query_digest(values: Iterable[str]) -> str:
    return project_memory_cases.query_digest(sys.modules[__name__], values)


def search_terms(values: Iterable[str]) -> set[str]:
    return project_memory_cases.search_terms(sys.modules[__name__], values)


def incident_case_compact(
    entry: dict[str, Any], *, score: int, warnings: list[str]
) -> dict[str, Any]:
    return project_memory_cases.incident_case_compact(
        sys.modules[__name__], entry, score=score, warnings=warnings
    )


def search_incident_cases(
    repo: pathlib.Path,
    *,
    symptoms: Iterable[str],
    keywords: Iterable[str],
    scopes: Iterable[str],
    components: Iterable[str],
    environment: Iterable[str],
    observed_version: str | None,
    limit: int,
) -> dict[str, Any]:
    return project_memory_cases.search_incident_cases(
        sys.modules[__name__], repo, symptoms=symptoms, keywords=keywords,
        scopes=scopes, components=components, environment=environment,
        observed_version=observed_version, limit=limit,
    )


def promote_incident_case(
    repo: pathlib.Path, *, expected_revision: int, entry: dict[str, Any]
) -> tuple[str, int]:
    return project_memory_cases.promote_incident_case(
        sys.modules[__name__], repo, expected_revision=expected_revision, entry=entry
    )


def materialize_profile_document(repo: pathlib.Path, document: dict[str, Any]) -> dict[str, Any]:
    return project_memory_profiles.materialize_profile_document(repo, document)


def render_environment_projection(repo: pathlib.Path, document: dict[str, Any]) -> str:
    return project_memory_profiles.render_environment_projection(repo, document)


def render_domain_projection(document: dict[str, Any]) -> str:
    return project_memory_profiles.render_domain_projection(document)


def initialize_profiles(repo: pathlib.Path, *, confirmation_source: str) -> dict[str, Any]:
    return project_memory_profiles.initialize_profiles(
        repo, confirmation_source=confirmation_source
    )

def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__, prog=os.environ.get("AUTO_DEV_CLI_PROG"))
    commands = root.add_subparsers(dest="command", required=True)

    record_parser = commands.add_parser("record")
    record_parser.add_argument("kind", choices=("dependency", "toolchain", "gotcha"))
    record_parser.add_argument("--repo-root", default=".")
    record_parser.add_argument("--id", dest="entry_id", required=True)
    record_parser.add_argument("--scope", action="append", default=[])
    record_parser.add_argument("--evidence", action="append", required=True)
    record_parser.add_argument("--version")
    record_parser.add_argument("--name")
    record_parser.add_argument("--purpose")
    record_parser.add_argument("--capability", action="append", default=[])
    record_parser.add_argument("--status", choices=tuple(sorted(DEPENDENCY_STATUSES)), default="known-good")
    record_parser.add_argument("--role", choices=tuple(sorted(DEPENDENCY_ROLES)))
    record_parser.add_argument("--source")
    record_parser.add_argument("--prerequisite", action="append", default=[])
    record_parser.add_argument("--condition", action="append", default=[])
    record_parser.add_argument("--environment", action="append", default=[])
    record_parser.add_argument("--command", action="append", default=[])
    record_parser.add_argument(
        "--runtime-argv",
        action="append",
        default=[],
        help="JSON argv prefix used by the managed external action; its program must be absolute.",
    )
    record_parser.add_argument("--success", action="append", default=[])
    record_parser.add_argument("--incompatible", action="append", default=[])
    record_parser.add_argument("--fallback", action="append", default=[])
    record_parser.add_argument("--limitation", action="append", default=[])
    record_parser.add_argument("--check-policy", choices=tuple(sorted(CHECK_POLICIES)), default="on_failure")
    record_parser.add_argument("--next-review")
    record_parser.add_argument("--update-signal")
    record_parser.add_argument("--symptom")
    record_parser.add_argument("--behavior")
    record_parser.add_argument("--impact")
    record_parser.add_argument("--avoid", action="append", default=[])
    record_parser.add_argument("--confidence", choices=("high", "medium", "low"), default="medium")
    record_parser.set_defaults(handler=record)

    list_parser = commands.add_parser("list")
    list_parser.add_argument("--repo-root", default=".")
    list_parser.add_argument("--kind", choices=("dependency", "toolchain", "gotcha", "incident_case"))
    list_parser.add_argument("--scope")
    list_parser.add_argument("--compact", action="store_true")
    list_parser.set_defaults(handler=list_entries)

    show_parser = commands.add_parser("show")
    show_parser.add_argument("entry_id")
    show_parser.add_argument("--repo-root", default=".")
    show_parser.add_argument("--attempts", action="store_true")
    show_parser.set_defaults(handler=show)

    resolve_parser = commands.add_parser("resolve")
    resolve_parser.add_argument("--repo-root", default=".")
    resolve_parser.add_argument("--capability", required=True)
    resolve_parser.add_argument("--scope")
    resolve_parser.add_argument("--environment", action="append", default=[])
    resolve_parser.add_argument("--write-lease", action="store_true")
    resolve_parser.set_defaults(handler=resolve)

    gate_parser = commands.add_parser("gate")
    gate_parser.add_argument("--repo-root", default=".")
    gate_parser.add_argument("--capability", required=True)
    gate_parser.add_argument("--scope")
    gate_parser.add_argument("--argv-json", required=True)
    gate_parser.set_defaults(handler=gate)

    preflight_parser = commands.add_parser("preflight")
    preflight_commands = preflight_parser.add_subparsers(dest="preflight_command", required=True)

    preflight_open_parser = preflight_commands.add_parser("open")
    preflight_open_parser.add_argument("--repo-root", default=".")
    preflight_open_parser.add_argument("--permit-id", required=True)
    preflight_open_parser.add_argument("--dependency-id", required=True)
    preflight_open_parser.add_argument("--capability", required=True)
    preflight_open_parser.add_argument("--scope")
    preflight_open_parser.add_argument("--action-id", required=True)
    preflight_open_parser.add_argument("--argv-json", required=True)
    preflight_open_parser.add_argument("--ttl-seconds", type=int, default=900)
    preflight_open_parser.set_defaults(handler=preflight_open)

    preflight_close_parser = preflight_commands.add_parser("close")
    preflight_close_parser.add_argument("--repo-root", default=".")
    preflight_close_parser.add_argument("--permit-id", required=True)
    preflight_close_parser.add_argument("--attempt-id")
    preflight_close_parser.add_argument("--result", choices=tuple(sorted(ATTEMPT_RESULTS)), required=True)
    preflight_close_parser.add_argument("--classification", choices=tuple(sorted(FAILURE_CLASSES)), required=True)
    preflight_close_parser.add_argument("--summary", required=True)
    preflight_close_parser.add_argument("--evidence", action="append", required=True)
    preflight_close_parser.add_argument("--version")
    preflight_close_parser.add_argument("--environment", action="append", default=[])
    preflight_close_parser.add_argument("--promote", action="store_true")
    preflight_close_parser.add_argument("--promote-role", choices=("preferred", "fallback"), default="preferred")
    preflight_close_parser.set_defaults(handler=preflight_close)

    attempt_parser = commands.add_parser("attempt")
    attempt_parser.add_argument("--repo-root", default=".")
    attempt_parser.add_argument("--dependency-id", required=True)
    attempt_parser.add_argument("--attempt-id")
    attempt_parser.add_argument("--result", choices=tuple(sorted(ATTEMPT_RESULTS)), required=True)
    attempt_parser.add_argument("--classification", choices=tuple(sorted(FAILURE_CLASSES)), required=True)
    attempt_parser.add_argument("--summary", required=True)
    attempt_parser.add_argument("--evidence", action="append", required=True)
    attempt_parser.add_argument("--version")
    attempt_parser.add_argument("--environment", action="append", default=[])
    attempt_parser.add_argument("--next-status", choices=tuple(sorted(DEPENDENCY_STATUSES)))
    attempt_parser.add_argument("--next-role", choices=tuple(sorted(DEPENDENCY_ROLES)))
    attempt_parser.set_defaults(handler=attempt)

    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--repo-root", default=".")
    verify_parser.add_argument("--kind", choices=("dependency", "toolchain", "gotcha", "incident_case"))
    verify_parser.add_argument("--id", dest="entry_id")
    verify_parser.add_argument("--strict", action="store_true")
    verify_parser.set_defaults(handler=verify)

    review_parser = commands.add_parser("review")
    review_parser.add_argument("--repo-root", default=".")
    review_parser.add_argument("--capability")
    review_parser.set_defaults(handler=review)

    environment_parser = commands.add_parser("environment")
    environment_commands = environment_parser.add_subparsers(
        dest="environment_command", required=True
    )
    environment_inspect = environment_commands.add_parser("inspect")
    environment_inspect.add_argument("--repo-root", default=".")
    environment_inspect.set_defaults(handler=project_memory_profiles.command_environment_inspect)
    environment_init = environment_commands.add_parser("init")
    environment_init.add_argument("--repo-root", default=".")
    environment_init.add_argument("--confirmation-source", required=True)
    environment_init.set_defaults(handler=project_memory_profiles.command_environment_init)
    environment_set = environment_commands.add_parser("set")
    environment_set.add_argument("--repo-root", default=".")
    environment_set.add_argument("--memory-revision", type=int, required=True)
    environment_set.add_argument("--confirmation-source", required=True)
    environment_input = environment_set.add_mutually_exclusive_group(required=True)
    environment_input.add_argument("--profile-json")
    environment_input.add_argument("--profile-file")
    environment_set.set_defaults(handler=project_memory_profiles.command_environment_set)

    domain_parser = commands.add_parser("domain")
    domain_commands = domain_parser.add_subparsers(dest="domain_command", required=True)
    domain_inspect = domain_commands.add_parser("inspect")
    domain_inspect.add_argument("--repo-root", default=".")
    domain_inspect.set_defaults(handler=project_memory_profiles.command_domain_inspect)
    domain_set = domain_commands.add_parser("set")
    domain_set.add_argument("--repo-root", default=".")
    domain_set.add_argument("--memory-revision", type=int, required=True)
    domain_set.add_argument("--confirmation-source", required=True)
    domain_input = domain_set.add_mutually_exclusive_group(required=True)
    domain_input.add_argument("--domain-json")
    domain_input.add_argument("--domain-file")
    domain_set.set_defaults(handler=project_memory_profiles.command_domain_set)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        return args.handler(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"{os.environ.get('AUTO_DEV_CLI_PROG', 'dependency_manager.py')}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
