"""Read-only inspection helpers for interrupted control-plane upgrades."""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any


def file_digest(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def completed_upgrade_ids(history: pathlib.Path) -> set[str]:
    if not history.exists():
        return set()
    identifiers: set[str] = set()
    for line_number, line in enumerate(history.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"legacy upgrade history line {line_number} is unreadable"
            ) from error
        if not isinstance(record, dict) or not isinstance(record.get("upgrade_id"), str):
            raise ValueError(f"legacy upgrade history line {line_number} is malformed")
        identifiers.add(record["upgrade_id"])
    return identifiers


def safe_relative_path(value: Any, *, label: str) -> pathlib.Path:
    if not isinstance(value, str):
        raise ValueError(f"{label} is missing a path")
    relative = pathlib.Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"{label} contains an unsafe path")
    return relative


def read_upgrade_manifest(
    control, state: dict[str, pathlib.Path], backup_root: pathlib.Path
) -> tuple[dict[str, Any], list[dict[str, Any]], list[pathlib.Path]]:
    manifest_path = backup_root / "manifest.json"
    manifest = control.read_json(manifest_path)
    if manifest.get("upgrade_id") != backup_root.name:
        raise ValueError("legacy upgrade backup id does not match its directory")
    records = manifest.get("files")
    directories = manifest.get("created_directories")
    if not isinstance(records, list) or not isinstance(directories, list):
        raise ValueError("legacy upgrade backup manifest is malformed")
    normalized_records: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("legacy upgrade backup contains an invalid file record")
        relative = safe_relative_path(record.get("path"), label="legacy upgrade backup")
        existed = record.get("existed")
        if not isinstance(existed, bool):
            raise ValueError("legacy upgrade backup file record has no existence state")
        normalized = {**record, "relative": relative, "existed": existed}
        if existed:
            expected = record.get("sha256")
            source = backup_root / relative
            if (
                not isinstance(expected, str)
                or source.is_symlink()
                or not source.is_file()
            ):
                raise ValueError("legacy upgrade backup is missing a recorded file")
            if file_digest(source) != expected:
                raise ValueError("legacy upgrade backup file digest does not match its manifest")
        normalized_records.append(normalized)
    normalized_directories = [
        safe_relative_path(value, label="legacy upgrade backup directory")
        for value in directories
    ]
    return manifest, normalized_records, normalized_directories


def current_fingerprint(
    state: dict[str, pathlib.Path], records: list[dict[str, Any]]
) -> str:
    snapshot = []
    for record in sorted(records, key=lambda item: item["relative"].as_posix()):
        destination = state["root"] / record["relative"]
        snapshot.append(
            {
                "path": record["relative"].as_posix(),
                "exists": destination.is_file(),
                "sha256": file_digest(destination) if destination.is_file() else None,
            }
        )
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def matches_pre_upgrade_state(
    state: dict[str, pathlib.Path], records: list[dict[str, Any]]
) -> bool:
    for record in records:
        destination = state["root"] / record["relative"]
        if record["existed"]:
            if not destination.is_file() or file_digest(destination) != record.get("sha256"):
                return False
        elif destination.exists():
            return False
    return True


def created_directory_conflicts(
    state: dict[str, pathlib.Path],
    records: list[dict[str, Any]],
    directories: list[pathlib.Path],
) -> list[str]:
    recorded_paths = {record["relative"] for record in records}
    conflicts: list[str] = []
    for record in records:
        destination = state["root"] / record["relative"]
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            conflicts.append(record["relative"].as_posix())
    for relative in directories:
        directory = state["root"] / relative
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.is_dir():
            conflicts.append(relative.as_posix())
            continue
        for path in directory.rglob("*"):
            if path.is_symlink() or (
                path.is_file() and path.relative_to(state["root"]) not in recorded_paths
            ):
                conflicts.append(path.relative_to(state["root"]).as_posix())
    return sorted(set(conflicts))


def inspect_upgrade_transactions(
    control, state: dict[str, pathlib.Path]
) -> list[dict[str, Any]]:
    backup_root = state["upgrade_backups"]
    if not backup_root.is_dir():
        return []
    try:
        completed = completed_upgrade_ids(state["upgrade_history"])
    except (OSError, ValueError) as error:
        return [{"status": "unavailable", "error": str(error), "operations": []}]
    transactions = []
    for directory in sorted(backup_root.iterdir(), key=lambda path: path.name, reverse=True):
        if not directory.is_dir() or not (directory / "manifest.json").is_file():
            continue
        try:
            _manifest, records, created_directories = read_upgrade_manifest(
                control, state, directory
            )
            manifest_digest = file_digest(directory / "manifest.json")
            fingerprint = current_fingerprint(state, records)
            conflicts = created_directory_conflicts(
                state, records, created_directories
            )
            if directory.name in completed:
                status = "completed"
            elif matches_pre_upgrade_state(state, records):
                status = "rolled_back"
            elif conflicts:
                status = "conflict"
            else:
                status = "interrupted"
            operations = []
            if status == "interrupted":
                operations.append(
                    {
                        "operation": "recover-interrupted-upgrade",
                        "upgrade_id": directory.name,
                    }
                )
            transactions.append(
                {
                    "upgrade_id": directory.name,
                    "status": status,
                    "manifest_sha256": manifest_digest,
                    "current_fingerprint": fingerprint,
                    "conflicts": conflicts,
                    "operations": operations,
                }
            )
        except (OSError, json.JSONDecodeError, ValueError) as error:
            transactions.append(
                {
                    "upgrade_id": directory.name,
                    "status": "invalid_backup",
                    "error": str(error),
                    "operations": [],
                }
            )
    return transactions


def find_interrupted_upgrade(
    transactions: list[dict[str, Any]], upgrade_id: str
) -> dict[str, Any]:
    candidate = next(
        (item for item in transactions if item.get("upgrade_id") == upgrade_id),
        None,
    )
    if candidate is None:
        raise ValueError("interrupted legacy upgrade candidate no longer exists")
    if candidate.get("status") != "interrupted":
        raise ValueError(
            f"legacy upgrade is not recoverable from its current state: {candidate.get('status')}"
        )
    return candidate
