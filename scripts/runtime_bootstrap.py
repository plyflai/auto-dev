#!/usr/bin/env python3
"""Stable, version-independent launcher for the Auto Dev lifecycle Hook."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


BOOTSTRAP_ABI = 1
REGISTRY_NAME = "runtime-upgrade.json"
PLUGIN_NAME = "auto-dev"


def data_root() -> Path | None:
    value = os.environ.get("PLUGIN_DATA")
    return Path(value).expanduser().resolve() if value else None


def registry_path(root: Path | None = None) -> Path | None:
    base = root or data_root()
    return base / REGISTRY_NAME if base else None


def read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def bundle_manifest(bundle: Path) -> dict[str, Any] | None:
    return read_json(bundle / ".codex-plugin" / "plugin.json")


def bundle_is_usable(bundle: Path | None) -> bool:
    if bundle is None:
        return False
    try:
        bundle = bundle.expanduser().resolve()
    except OSError:
        return False
    manifest = bundle_manifest(bundle)
    return bool(
        isinstance(manifest, dict)
        and str(manifest.get("name", "")).casefold() == PLUGIN_NAME
        and (bundle / "scripts" / "runtime_bootstrap.py").is_file()
        and (bundle / "scripts" / "hook_dispatch.py").is_file()
        and (bundle / "skills" / "auto-dev" / "scripts" / "auto_dev.py").is_file()
        and (bundle / "skills" / "auto-dev" / "scripts" / "auto_dev_internal" / "task" / "workers.py").is_file()
        and (bundle / "skills" / "refresh" / "SKILL.md").is_file()
    )


def manifest_version(bundle: Path | None) -> str | None:
    manifest = bundle_manifest(bundle) if bundle else None
    value = manifest.get("version") if isinstance(manifest, dict) else None
    return value if isinstance(value, str) and value else None


def _path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return Path(value).expanduser().resolve()
    except OSError:
        return None


def candidate_bundles() -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    registry = read_json(registry_path())
    if registry:
        current = _path(registry.get("current_bundle"))
        if bundle_is_usable(current):
            candidates.append(("current", current))

    configured = _path(os.environ.get("PLUGIN_ROOT"))
    # A cache refresh can leave a valid sibling bundle while the configured
    # path is stale. Prefer the most recently installed usable sibling, while
    # keeping discovery bounded to the configured/current bundle parents.
    parents = []
    for value in (configured, Path(__file__).resolve().parents[1]):
        if value is not None:
            parents.append(value.parent)
    seen: set[str] = set()
    for parent in parents:
        try:
            children = sorted(parent.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)
        except OSError:
            continue
        for child in children:
            if str(child) in seen or not child.is_dir():
                continue
            seen.add(str(child))
            if bundle_is_usable(child):
                candidates.append(("sibling", child))
    if bundle_is_usable(configured):
        candidates.append(("configured", configured))
    if registry:
        previous = _path(registry.get("previous_bundle"))
        if bundle_is_usable(previous):
            candidates.append(("previous", previous))
    unique: list[tuple[str, Path]] = []
    seen_paths: set[str] = set()
    for label, bundle in candidates:
        key = str(bundle)
        if key not in seen_paths:
            seen_paths.add(key)
            unique.append((label, bundle))
    return unique


def resolve_bundle() -> tuple[str, Path] | None:
    candidates = candidate_bundles()
    return candidates[0] if candidates else None


def failure_payload(event: dict[str, Any], reason: str) -> dict[str, Any]:
    event_name = str(event.get("hook_event_name") or "Hook")
    receipt = f"⬆️ Auto Dev Upgrade: runtime_unavailable | 运行时不可用 / Runtime unavailable | event={event_name} | reason={reason}"
    payload: dict[str, Any] = {
        "systemMessage": receipt,
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": (
                "Auto Dev runtime could not resolve a verified bundle. Product and control-plane writes "
                "remain blocked; use the explicit auto-dev-refresh flow or start a fresh session.\n\n"
                + receipt
            ),
        },
    }
    if event_name == "PreToolUse":
        payload["hookSpecificOutput"]["permissionDecision"] = "deny"
        payload["hookSpecificOutput"]["permissionDecisionReason"] = (
            "Auto Dev runtime is unavailable; product/control writes are blocked until runtime recovery."
        )
    return payload


def main() -> int:
    resolved = resolve_bundle()
    if resolved is None:
        raw = sys.stdin.read()
        try:
            event = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            event = {}
        if not isinstance(event, dict):
            event = {}
        print(json.dumps(failure_payload(event, "no verified compatible bundle"), ensure_ascii=False))
        return 0
    source, bundle = resolved
    hook = bundle / "scripts" / "hook_dispatch.py"
    environment = dict(os.environ)
    environment["PLUGIN_ROOT"] = str(bundle)
    environment["AUTO_DEV_RUNTIME_RESOLVED_FROM"] = source
    environment["AUTO_DEV_RUNTIME_VERSION"] = manifest_version(bundle) or "unknown"
    configured = _path(os.environ.get("PLUGIN_ROOT"))
    if configured != bundle:
        environment["AUTO_DEV_RUNTIME_RECOVERED"] = "1"
    os.execvpe(sys.executable, [sys.executable, str(hook)], environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
