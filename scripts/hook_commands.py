"""Shell command parsing and deterministic write/action classification."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any


def shell_segments(control, command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        segments: list[list[str]] = []
        current: list[str] = []
        for token in lexer:
            if token in control.SHELL_BOUNDARIES:
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(token)
        if current:
            segments.append(current)
        return segments
    except ValueError:
        return []


def segment_program_index(control, tokens: list[str]) -> int | None:
    index = 0
    while index < len(tokens) and re.fullmatch("[A-Za-z_][A-Za-z0-9_]*=.*", tokens[index]):
        index += 1
    if index < len(tokens) and tokens[index] == "env":
        index += 1
        while index < len(tokens) and (
            tokens[index].startswith("-")
            or re.fullmatch("[A-Za-z_][A-Za-z0-9_]*=.*", tokens[index])
        ):
            index += 1
    if index >= len(tokens):
        return None
    return index


def segment_program(control, tokens: list[str]) -> str | None:
    index = segment_program_index(control, tokens)
    return Path(tokens[index]).name.casefold() if index is not None else None


def segment_arguments(control, tokens: list[str]) -> list[str]:
    index = segment_program_index(control, tokens)
    return tokens[index + 1 :] if index is not None else []


def segment_argv(control, tokens: list[str]) -> list[str]:
    index = segment_program_index(control, tokens)
    return tokens[index:] if index is not None else []


def has_in_place_option(control, tokens: list[str]) -> bool:
    return any(
        (
            token == "-i"
            or (token.startswith("-i") and token != "-")
            or token == "--in-place"
            or token.startswith("--in-place=")
            for token in tokens
        )
    )


def redirection_targets(control, tokens: list[str]) -> list[str]:
    targets: list[str] = []
    for index, token in enumerate(tokens[:-1]):
        if token in {">", ">>"}:
            targets.append(tokens[index + 1])
    return targets


def product_redirection_targets(control, tokens: list[str]) -> list[str]:
    """Return stdout redirection targets without treating `2>/dev/null` as a write."""
    targets: list[str] = []
    for index, token in enumerate(tokens[:-1]):
        if token not in {">", ">>"}:
            continue
        if index and tokens[index - 1] == "2":
            continue
        targets.append(tokens[index + 1])
    return targets


def is_auto_dev_path(control, value: str) -> bool:
    return ".auto-dev" in Path(value).parts


def is_control_metadata_path(control, value: str) -> bool:
    parts = Path(value).parts
    return bool(parts) and parts[0].casefold() in control.CONTROL_METADATA_ROOTS


def resolved_command_path(control, value: str, cwd: Path) -> Path | None:
    expanded = value.replace("$" + "{PLUGIN_ROOT}", str(control.plugin_root())).replace(
        "$PLUGIN_ROOT", str(control.plugin_root())
    )
    try:
        candidate = Path(expanded).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        return candidate.resolve()
    except OSError:
        return None


def canonical_control_segment(control, tokens: list[str], cwd: Path) -> bool:
    if redirection_targets(control, tokens):
        return False
    for index, token in enumerate(tokens):
        if resolved_command_path(control, token, cwd) != control.cli_path():
            continue
        if mutating_control_parts(control, tokens[index + 1 :]):
            return True
    return False


def mutating_control_parts(control, parts: list[str]) -> bool:
    if not parts:
        return False
    command = parts[0]
    if command in {
        "start",
        "escalate",
        "capabilities",
        "event",
        "plan",
        "proof",
        "checkpoint",
        "diagnostics",
        "finish",
        "abandon",
        "recover",
        "migrate",
    }:
        return True
    if command == "project":
        return len(parts) > 1 and parts[1] in {"init", "migrate"}
    if command == "project-context":
        return len(parts) > 1 and parts[1] in {"adopt", "set", "select"}
    if command == "intake":
        return len(parts) > 1 and parts[1] in {"turn", "assess", "resolve", "confirm", "reopen"}
    if command == "outcome":
        return len(parts) > 1 and parts[1] in {"add", "set", "link", "move"}
    if command == "capability":
        return len(parts) > 1 and parts[1] in {"add", "set"}
    if command == "activity":
        return len(parts) > 1 and parts[1] == "record"
    if command == "focus":
        return len(parts) > 1 and parts[1] == "set"
    if command == "task":
        return len(parts) > 1 and parts[1] in {
            "select",
            "pause",
            "amend-scope",
            "review",
            "resume",
            "attribute",
        }
    if command == "fix":
        return len(parts) > 1 and parts[1] == "apply"
    if command == "legacy-upgrade":
        return len(parts) > 1 and parts[1] == "apply"
    if command == "handoff":
        return len(parts) > 1 and parts[1] == "import"
    if command == "bootstrap":
        return len(parts) > 1 and parts[1] == "apply"
    if command == "deps":
        return len(parts) > 1 and (
            parts[1] in {"record", "attempt", "preflight"}
            or (parts[1] == "resolve" and "--write-lease" in parts[2:])
        )
    if command == "evidence":
        return len(parts) > 1 and parts[1] == "link"
    if command == "impact":
        return len(parts) > 1 and parts[1] == "record"
    if command == "policy":
        return len(parts) > 1 and parts[1] in {"set", "approve"}
    if command == "debug":
        return len(parts) > 1 and parts[1] in {
            "begin",
            "observe",
            "resolve",
            "recovery",
            "case-search",
            "reproduction",
            "hypothesis",
        }
    if command == "memory":
        return len(parts) > 2 and parts[1:3] == ["case", "promote"]
    if command == "workspace":
        return len(parts) > 2 and parts[1] == "checkpoint" and (parts[2] in {"create", "protect"})
    return False


def self_target_control_segment(control, tokens: list[str]) -> bool:
    """Recognize a source-tree auto_dev.py mutation even when it is not installed CLI."""
    if redirection_targets(control, tokens):
        return False
    program = segment_program(control, tokens)
    argv = segment_argv(control, tokens)
    if program == "auto_dev.py":
        return mutating_control_parts(control, argv[1:])
    if program and program.startswith("python") and (len(argv) > 1):
        if Path(argv[1]).name.casefold() == "auto_dev.py":
            return mutating_control_parts(control, argv[2:])
    return False


def direct_state_write(control, command: str, cwd: Path) -> bool:
    for tokens in shell_segments(control, command):
        if canonical_control_segment(control, tokens, cwd):
            continue
        program = segment_program(control, tokens)
        targets = redirection_targets(control, tokens)
        if any((is_auto_dev_path(control, target) for target in targets)):
            return True
        if not any((is_auto_dev_path(control, token) for token in tokens)):
            continue
        if program in control.DIRECT_WRITE_PROGRAMS or program == "tee":
            return True
        if program in {"sed", "perl"} and has_in_place_option(control, tokens):
            return True
        if (
            program
            and program.startswith("python")
            and any((control.PYTHON_WRITE_CALL.search(token) for token in tokens))
        ):
            return True
    return False


def product_write_segment(control, tokens: list[str], cwd: Path) -> bool:
    if canonical_control_segment(control, tokens, cwd):
        return False
    program = segment_program(control, tokens)
    if program in control.DIRECT_WRITE_PROGRAMS or program == "tee":
        return True
    if program in {"sed", "perl"} and has_in_place_option(control, tokens):
        return True
    if product_redirection_targets(control, tokens):
        return True
    return bool(
        program
        and program.startswith("python")
        and any((control.PYTHON_WRITE_CALL.search(token) for token in tokens))
    )


def patch_paths(control, command: str) -> list[str]:
    return [
        match.group(1).strip()
        for line in command.splitlines()
        if (match := control.PATCH_PATH.match(line))
    ]


def quick_patch_details(control, root: Path, command: str) -> tuple[list[str], int] | None:
    paths: list[str] = []
    changed_lines = 0
    operations: list[str] = []
    for line in command.splitlines():
        match = control.PATCH_PATH.match(line)
        if match:
            header = line[4:].split(":", 1)[0].strip().casefold()
            operations.append(header)
            value = match.group(1).strip()
            normalized = normalize_patch_path(control, root, value)
            if normalized == value and (Path(value).is_absolute() or value.startswith("../")):
                return None
            path = Path(normalized)
            if path.is_absolute() or ".." in path.parts:
                return None
            if any((part in control.QUICK_WRITE_BLOCKED_PARTS for part in path.parts)):
                return None
            if path.suffix.casefold() not in control.QUICK_WRITE_ALLOWED_SUFFIXES:
                return None
            paths.append(normalized)
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            changed_lines += 1
    if not paths or len(set(paths)) > control.QUICK_WRITE_MAX_FILES:
        return None
    if changed_lines == 0 or changed_lines > control.QUICK_WRITE_MAX_CHANGED_LINES:
        return None
    if any((operation != "update file" for operation in operations)):
        return None
    return (list(dict.fromkeys(paths)), changed_lines)


def normalize_patch_path(control, root: Path, value: str) -> str:
    candidate = Path(value).expanduser()
    absolute = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        return absolute.relative_to(root).as_posix()
    except ValueError:
        return value


def external_action_requirements(control, command: str) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for tokens in shell_segments(control, command):
        program = segment_program(control, tokens)
        arguments = segment_arguments(control, tokens)
        argv = segment_argv(control, tokens)
        if program == "adb":
            shell_index = next(
                (index for (index, value) in enumerate(arguments) if value == "shell"), None
            )
            if shell_index is not None and shell_index + 1 < len(arguments):
                shell_arguments = arguments[shell_index + 1 :]
                if (
                    len(shell_arguments) >= 3
                    and shell_arguments[0] in {"sh", "bash"}
                    and (shell_arguments[1] == "-c")
                ):
                    shell_arguments = shell_arguments[2:]
                subcommand = shell_arguments[0].split(maxsplit=1)[0].casefold()
                if subcommand in control.ADB_EXTERNAL_ACTIONS:
                    requirements.append(
                        {"label": f"adb shell {subcommand}", "capability": None, "argv": argv}
                    )
                    continue
            for index, value in enumerate(arguments[:-1]):
                if value in {"exec-out", "exec-in"}:
                    subcommand = arguments[index + 1].split(maxsplit=1)[0].casefold()
                    if subcommand in control.ADB_EXTERNAL_ACTIONS:
                        requirements.append(
                            {"label": f"adb {value} {subcommand}", "capability": None, "argv": argv}
                        )
                        break
            else:
                direct = next(
                    (
                        value.split(maxsplit=1)[0].casefold()
                        for value in arguments
                        if value.split(maxsplit=1)[0].casefold() in control.ADB_EXTERNAL_ACTIONS
                    ),
                    None,
                )
                if direct:
                    requirements.append(
                        {"label": f"adb {direct}", "capability": None, "argv": argv}
                    )
        elif program in control.FRIDA_EXTERNAL_ACTIONS:
            if not any((value in {"--help", "-h", "--version"} for value in arguments)):
                requirements.append(
                    {"label": program, "capability": control.ANDROID_INSTRUMENTATION, "argv": argv}
                )
        elif program and program.startswith("python"):
            probe = next(
                (
                    value
                    for value in arguments
                    if value.replace("\\", "/").endswith("tools/frida/run_probe.py")
                ),
                None,
            )
            if probe is not None:
                requirements.append(
                    {
                        "label": "python tools/frida/run_probe.py",
                        "capability": control.ANDROID_INSTRUMENTATION,
                        "argv": argv,
                    }
                )
    return requirements


def external_action_labels(control, command: str) -> list[str]:
    return [
        str(requirement["label"]) for requirement in external_action_requirements(control, command)
    ]
