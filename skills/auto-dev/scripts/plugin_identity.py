"""Shared identity checks for the Auto Dev Plugin package."""

from __future__ import annotations

import json
from pathlib import Path


AUTO_DEV_PLUGIN_NAME = "auto-dev"
PLUGIN_MANIFEST = (".codex-plugin", "plugin.json")


def auto_dev_plugin_root(start: Path) -> Path | None:
    """Return the nearest package root whose manifest identifies Auto Dev."""
    current = start.expanduser().resolve()
    for candidate in (current, *current.parents):
        manifest = candidate.joinpath(*PLUGIN_MANIFEST)
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and str(payload.get("name", "")).casefold() == AUTO_DEV_PLUGIN_NAME:
            return candidate
    return None


def auto_dev_plugin_version(start: Path) -> str | None:
    """Return the version of the nearest valid Auto Dev package."""
    root = auto_dev_plugin_root(start)
    if root is None:
        return None
    try:
        payload = json.loads(root.joinpath(*PLUGIN_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    version = payload.get("version") if isinstance(payload, dict) else None
    return version if isinstance(version, str) and version.strip() else None
