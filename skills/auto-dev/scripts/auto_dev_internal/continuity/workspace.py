"""Workspace checkpoint, protection, and rollback inspection."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Any, Iterable


def archive_slug(control, value: str) -> str:
    slug = re.sub("[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:48] or "workspace"


def workspace_sensitive_path(control, relative: str) -> bool:
    path = pathlib.PurePosixPath(relative)
    parts = {part.casefold() for part in path.parts}
    name = path.name.casefold()
    return bool(
        parts & control.WORKSPACE_SENSITIVE_DIRECTORY_NAMES
        or name in control.WORKSPACE_SENSITIVE_FILE_NAMES
        or name.endswith((".pem", ".key", ".p12", ".pfx"))
    )


def workspace_dirty_paths(control, status: Iterable[str]) -> list[str]:
    return sorted({control.status_path(line) for line in status if control.status_path(line)})


def workspace_scope_digest(control, repo: pathlib.Path, scopes: Iterable[str]) -> str:
    scope_list = list(scopes)
    with control.evaluation_scope(repo) as evaluation:
        cache_key = tuple(scope_list)
        cached = evaluation.scope_digest_cache.get(cache_key)
        if cached is not None:
            return cached
        manifest = control.local_scope_manifest(repo, scope_list)
        digest = control.hashlib.sha256()
        for relative, fingerprint in manifest.items():
            digest.update(relative.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(fingerprint.encode("utf-8"))
            digest.update(b"\x00")
        result = digest.hexdigest()
        evaluation.scope_digest_cache[cache_key] = result
        return result


def workspace_checkpoint_phase(control, kind: str | None) -> str:
    return control.WORKSPACE_CHECKPOINT_PHASES.get(kind or "", "after_change")


def workspace_checkpoint_receipt_key(control, phase: str) -> str:
    return control.WORKSPACE_CHECKPOINT_RECEIPT_KEYS.get(phase, "workspace_checkpoint_after")


def workspace_checkpoint_short_hash(value: Any) -> str | None:
    object_id = value.strip() if isinstance(value, str) else ""
    return object_id[:8] if object_id else None


def workspace_checkpoint_receipt(control, point: dict[str, Any]) -> str:
    phase = point.get("archive_phase")
    if not isinstance(phase, str) or phase not in control.WORKSPACE_CHECKPOINT_RECEIPT_KEYS:
        phase = workspace_checkpoint_phase(control, str(point.get("kind") or ""))
    key = workspace_checkpoint_receipt_key(control, phase)
    label = control.bilingual_label(key)
    display_label = label.split(" / ", 1)[0]
    scope = point.get("scope")
    scope_text = (
        ",".join((str(item) for item in scope)) if isinstance(scope, list) and scope else "-"
    )
    details = [
        f"kind={point.get('kind') or 'unknown'}",
        f"ref={point.get('ref') or 'unresolved'}",
    ]
    short_hash = workspace_checkpoint_short_hash(point.get("object"))
    if short_hash:
        details.append(f"commit={short_hash}")
    details.append(f"scope={scope_text}")
    proof_refs = point.get("proof_refs", point.get("required_proofs", []))
    if isinstance(proof_refs, list) and proof_refs:
        details.append(f"proofs={','.join((str(item) for item in proof_refs))}")
    if point.get("protection_id"):
        details.append(f"protection={point['protection_id']}")
    return " | ".join([f"💾 Auto Dev 存档点：{display_label}", key, label, *details])


def workspace_point_projection(control, point: dict[str, Any]) -> dict[str, Any]:
    """Derive a display-safe point view without rewriting historical receipts."""
    view = dict(point)
    phase = view.get("archive_phase")
    if not isinstance(phase, str) or phase not in control.WORKSPACE_CHECKPOINT_RECEIPT_KEYS:
        phase = workspace_checkpoint_phase(control, str(view.get("kind") or ""))
    view["archive_phase"] = phase
    view.setdefault("receipt_key", workspace_checkpoint_receipt_key(control, phase))
    if not isinstance(view.get("proof_refs"), list):
        required_proofs = view.get("required_proofs")
        view["proof_refs"] = list(required_proofs) if isinstance(required_proofs, list) else []
    if not isinstance(view.get("receipt"), str):
        view["receipt"] = workspace_checkpoint_receipt(control, view)
    return view


def workspace_checkpoint_protection_receipt(control, protection: dict[str, Any]) -> str:
    key = "workspace_checkpoint_protection_armed"
    label = control.bilingual_label(key)
    display_label = label.split(" / ", 1)[0]
    scope = protection.get("scope")
    scope_text = (
        ",".join((str(item) for item in scope)) if isinstance(scope, list) and scope else "-"
    )
    return " | ".join(
        [
            f"💾 Auto Dev 存档保护：{display_label}",
            key,
            label,
            f"protection={protection.get('id') or 'unresolved'}",
            f"node={protection.get('node_id') or 'unresolved'}",
            f"scope={scope_text}",
        ]
    )


def receipt_workspace_checkpoint_protections(
    control, receipt: dict[str, Any]
) -> list[dict[str, Any]]:
    """Read protection records in either legacy or continuity storage without copying them."""
    containers: list[Any] = [receipt.get("workspace_checkpoint_protections")]
    continuity = receipt.get("continuity")
    if isinstance(continuity, dict):
        containers.append(continuity.get("workspace_checkpoint_protections"))
    protections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in containers:
        if not isinstance(value, list):
            continue
        for index, protection in enumerate(value):
            if not isinstance(protection, dict):
                continue
            identity = str(protection.get("id") or f"protection:{index}")
            if identity in seen:
                continue
            seen.add(identity)
            protections.append(protection)
    return protections


def find_workspace_checkpoint_protection(
    control, receipt: dict[str, Any], protection_id: str | None
) -> dict[str, Any] | None:
    if not protection_id:
        return None
    return next(
        (
            protection
            for protection in receipt_workspace_checkpoint_protections(control, receipt)
            if protection.get("id") == protection_id
        ),
        None,
    )


def workspace_checkpoint_protection_point_projection(
    control, protection: dict[str, Any], phase: str, checkpoint_refs: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    recorded = protection.get(phase)
    raw = recorded if isinstance(recorded, dict) else {}
    point_id = raw.get("point_id")
    ref = raw.get("ref")
    if not point_id and (not ref):
        return {
            "phase": phase,
            "status": "pending",
            "point_id": None,
            "ref": None,
            "object": None,
            "short_hash": None,
            "required_proofs": (
                list(raw.get("required_proofs", []))
                if isinstance(raw.get("required_proofs"), list)
                else []
            ),
        }
    matching = next(
        (
            entry
            for entry in checkpoint_refs
            if isinstance(entry.get("checkpoint"), dict)
            and point_id
            and (entry["checkpoint"].get("id") == point_id)
            or (ref and entry.get("ref") == ref)
        ),
        None,
    )
    checkpoint = matching.get("checkpoint") if isinstance(matching, dict) else None
    object_id = raw.get("object")
    return {
        "phase": phase,
        "status": (
            matching.get("status", "missing_ref") if isinstance(matching, dict) else "missing_ref"
        ),
        "point_id": point_id,
        "ref": ref,
        "object": object_id,
        "short_hash": workspace_checkpoint_short_hash(object_id),
        "required_proofs": (
            list(raw.get("required_proofs", []))
            if isinstance(raw.get("required_proofs"), list)
            else []
        ),
        "checkpoint": checkpoint,
    }


def workspace_checkpoint_protection_projection(
    control, protection: dict[str, Any], checkpoint_refs: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    before = workspace_checkpoint_protection_point_projection(
        control, protection, "before", checkpoint_refs
    )
    after = workspace_checkpoint_protection_point_projection(
        control, protection, "after", checkpoint_refs
    )
    if before["status"] == "pending":
        status = "before_pending"
    elif before["status"] != "recorded":
        status = "before_invalid"
    elif after["status"] == "pending":
        status = "after_pending"
    elif after["status"] != "recorded":
        status = "after_invalid"
    else:
        status = "protected"
    return {
        "id": protection.get("id"),
        "node_id": protection.get("node_id"),
        "scope": (
            list(protection.get("scope", [])) if isinstance(protection.get("scope"), list) else []
        ),
        "scope_sha256": protection.get("scope_sha256"),
        "plan_revision": protection.get("plan_revision"),
        "created_at": protection.get("created_at"),
        "confirmation_source": protection.get("confirmation_source"),
        "status": status,
        "before": before,
        "after": after,
    }


def workspace_checkpoint_protections_projection(
    control, receipt: dict[str, Any], checkpoint_refs: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    protections = [
        workspace_checkpoint_protection_projection(control, protection, checkpoint_refs)
        for protection in receipt_workspace_checkpoint_protections(control, receipt)
    ]
    before_pending = [entry["id"] for entry in protections if entry["status"] == "before_pending"]
    before_invalid = [entry["id"] for entry in protections if entry["status"] == "before_invalid"]
    after_pending = [entry["id"] for entry in protections if entry["status"] == "after_pending"]
    after_invalid = [entry["id"] for entry in protections if entry["status"] == "after_invalid"]
    return {
        "status": (
            "invalid"
            if before_invalid or after_invalid
            else (
                "pending"
                if before_pending or after_pending
                else "protected" if protections else "unprotected"
            )
        ),
        "protections": protections,
        "before_pending": before_pending,
        "before_invalid": before_invalid,
        "after_pending": after_pending,
        "after_invalid": after_invalid,
    }


def workspace_checkpoint_node_point_projection(point: Any) -> dict[str, Any]:
    value = point if isinstance(point, dict) else {}
    object_id = value.get("object")
    return {
        "phase": value.get("phase"),
        "status": value.get("status", "pending"),
        "ref": value.get("ref"),
        "object": object_id,
        "short_hash": value.get("short_hash") or workspace_checkpoint_short_hash(object_id),
    }


def workspace_checkpoint_standalone_node_ids(
    point: dict[str, Any], node_ids: Iterable[str]
) -> list[str]:
    """Return the uniquely attributable current-plan node for an unpaired point."""
    valid_node_ids = {node_id for node_id in node_ids if isinstance(node_id, str) and node_id}
    proof_refs = point.get("proof_refs")
    if not isinstance(proof_refs, list):
        proof_refs = point.get("required_proofs")
    if not valid_node_ids or not isinstance(proof_refs, list):
        return []
    candidates = {
        proof_ref.partition(":")[0]
        for proof_ref in proof_refs
        if isinstance(proof_ref, str)
        and ":" in proof_ref
        and proof_ref.partition(":")[0] in valid_node_ids
    }
    return sorted(candidates) if len(candidates) == 1 else []


def workspace_checkpoint_standalone_point_projection(
    point: dict[str, Any], phase: str, checkpoint_refs: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Reconcile a historical unpaired point with its durable Git ref."""
    point_id = point.get("id")
    ref = point.get("ref")
    matching = next(
        (
            entry
            for entry in checkpoint_refs
            if isinstance(entry, dict)
            and (
                (
                    point_id
                    and isinstance(entry.get("checkpoint"), dict)
                    and entry["checkpoint"].get("id") == point_id
                )
                or (ref and entry.get("ref") == ref)
            )
        ),
        None,
    )
    object_id = point.get("object") or (matching.get("object") if isinstance(matching, dict) else None)
    return {
        "phase": phase,
        "status": (
            matching.get("status", "missing_ref")
            if isinstance(matching, dict)
            else "missing_ref" if ref else "untracked"
        ),
        "point_id": point_id,
        "ref": ref,
        "object": object_id,
        "short_hash": workspace_checkpoint_short_hash(object_id),
    }


def workspace_checkpoint_pending_node_point(phase: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "status": "pending",
        "point_id": None,
        "ref": None,
        "object": None,
        "short_hash": None,
    }


def workspace_checkpoint_node_projection(
    control,
    protection_state: dict[str, Any],
    *,
    points: Iterable[dict[str, Any]] = (),
    checkpoint_refs: Iterable[dict[str, Any]] = (),
    node_ids: Iterable[str] = (),
) -> dict[str, list[dict[str, Any]]]:
    """Bind paired protections and attributable standalone points to Plan nodes."""
    by_node: dict[str, list[dict[str, Any]]] = {}
    refs = list(checkpoint_refs)
    paired_point_ids: set[str] = set()
    paired_refs: set[str] = set()
    protections = protection_state.get("protections", [])
    if not isinstance(protections, list):
        protections = []
    for protection in protections:
        if not isinstance(protection, dict):
            continue
        node_id = protection.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            continue
        before = workspace_checkpoint_node_point_projection(protection.get("before"))
        after = workspace_checkpoint_node_point_projection(protection.get("after"))
        for projected_point in (before, after):
            point_id = projected_point.get("point_id")
            ref = projected_point.get("ref")
            if isinstance(point_id, str) and point_id:
                paired_point_ids.add(point_id)
            if isinstance(ref, str) and ref:
                paired_refs.add(ref)
        by_node.setdefault(node_id, []).append(
            {
                "protection_id": protection.get("id"),
                "status": protection.get("status"),
                "before": before,
                "after": after,
            }
        )
    for point in points:
        if not isinstance(point, dict):
            continue
        point_id = point.get("id")
        ref = point.get("ref")
        if (isinstance(point_id, str) and point_id in paired_point_ids) or (
            isinstance(ref, str) and ref in paired_refs
        ):
            continue
        owners = workspace_checkpoint_standalone_node_ids(point, node_ids)
        if not owners:
            continue
        archive_phase = point.get("archive_phase")
        if not isinstance(archive_phase, str):
            archive_phase = workspace_checkpoint_phase(control, str(point.get("kind") or ""))
        point_phase = "before" if archive_phase == "before_change" else "after"
        standalone = workspace_checkpoint_standalone_point_projection(point, point_phase, refs)
        before = (
            standalone
            if point_phase == "before"
            else workspace_checkpoint_pending_node_point("before")
        )
        after = (
            standalone
            if point_phase == "after"
            else workspace_checkpoint_pending_node_point("after")
        )
        by_node.setdefault(owners[0], []).append(
            {
                "protection_id": None,
                "status": "standalone",
                "projection": "standalone",
                "before": before,
                "after": after,
            }
        )
    return by_node


def receipt_workspace_points(control, receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Read both legacy and continuity point locations without mutating a receipt."""
    containers: list[tuple[str, Any]] = [("receipt", receipt.get("workspace_points"))]
    continuity = receipt.get("continuity")
    if isinstance(continuity, dict):
        containers.append(("continuity", continuity.get("workspace_points")))
    points: list[dict[str, Any]] = []
    seen: set[str] = set()
    for location, value in containers:
        if not isinstance(value, list):
            continue
        for index, point in enumerate(value):
            if not isinstance(point, dict):
                continue
            identity = str(point.get("id") or point.get("ref") or f"{location}:{index}")
            if identity in seen:
                continue
            seen.add(identity)
            points.append(workspace_point_projection(control, point))
    return points


def workspace_checkpoint_records(control, state: dict[str, pathlib.Path]) -> list[dict[str, Any]]:
    """Collect point records from every durable receipt projection, read-only."""
    evaluation = control.current_evaluation(state["root"].parent)
    cache_key = ("workspace_checkpoint_records",)
    if evaluation is not None and cache_key in evaluation.value_cache:
        return control.copy.deepcopy(evaluation.value_cache[cache_key])
    candidates: list[tuple[str, pathlib.Path]] = [("active", state["active"])]
    for location, directory in (("task", state["tasks"]), ("run", state["runs"])):
        if directory.exists():
            candidates.extend(((location, path) for path in sorted(directory.glob("*.json"))))
    records: list[dict[str, Any]] = []
    seen_paths: set[pathlib.Path] = set()
    for location, path in candidates:
        if path in seen_paths or not path.exists():
            continue
        seen_paths.add(path)
        try:
            receipt = control.read_json(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(receipt, dict):
            continue
        task_id = str(receipt.get("id") or "unknown")
        for point in receipt_workspace_points(control, receipt):
            ref = point.get("ref")
            if not isinstance(ref, str) or not ref:
                continue
            records.append({"task_id": task_id, "source": location, "point": point})
    if evaluation is not None:
        evaluation.value_cache[cache_key] = control.copy.deepcopy(records)
    return records


def workspace_required_proofs(
    control,
    repo: pathlib.Path,
    receipt: dict[str, Any],
    continuity: dict[str, Any] | None,
    *,
    node_ids: Iterable[str] | None = None,
) -> tuple[list[str], list[str]]:
    if continuity is None:
        outcome = receipt.get("outcome") if isinstance(receipt.get("outcome"), dict) else None
        nodes = (
            [{"id": "run", "status": receipt.get("status"), "outcome": outcome}] if outcome else []
        )
        proofs = receipt.get("proofs", [])
    else:
        nodes = continuity.get("plan", {}).get("nodes", [])
        proofs = continuity.get("proofs", [])
    selected_node_ids = {str(node_id) for node_id in node_ids} if node_ids is not None else None
    required: list[str] = []
    missing: list[str] = []
    for node in nodes:
        if not isinstance(node, dict) or node.get("status") not in {"active", "done"}:
            continue
        outcome = node.get("outcome") if isinstance(node.get("outcome"), dict) else None
        if not outcome:
            continue
        node_id = str(node.get("id"))
        if selected_node_ids is not None and node_id not in selected_node_ids:
            continue
        for proof_spec in outcome.get("proofs", []):
            proof_id = str(proof_spec.get("id"))
            reference = f"{node_id}:{proof_id}"
            required.append(reference)
            latest = control.latest_proof(proofs, node_id=node_id, proof_id=proof_id)
            plan_revision = int(continuity.get("plan", {}).get("revision", 0)) if continuity else 0
            if latest is None or not control.proof_is_fresh(
                latest, outcome=outcome, repo=repo, plan_revision=plan_revision, node=node
            ):
                missing.append(reference)
    return (required, missing)


def workspace_checkpoint_refs(
    control, repo: pathlib.Path, state: dict[str, pathlib.Path] | None = None
) -> list[dict[str, Any]]:
    if control.workspace_storage_mode(repo) != "git":
        return []
    records_by_ref: dict[str, list[dict[str, Any]]] = {}
    if state is not None:
        for record in workspace_checkpoint_records(control, state):
            records_by_ref.setdefault(str(record["point"]["ref"]), []).append(record)
    result = control.git(
        repo,
        "for-each-ref",
        "--sort=-creatordate",
        "--format=%(refname)\t%(objectname)\t%(*objectname)\t%(creatordate:iso-strict)\t%(subject)",
        "refs/tags/auto-dev",
        check=False,
    )
    entries: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for line in result.splitlines():
        (ref, object_name, peeled_object, created_at, subject) = (
            line.split("\t", 4) + [""] * 5
        )[:5]
        if not ref:
            continue
        object_id = peeled_object or object_name
        records = records_by_ref.get(ref, [])
        checkpoint = records[0]["point"] if records else None
        expected_objects = {
            str(record["point"].get("object"))
            for record in records
            if record["point"].get("object")
        }
        record_status = (
            "untracked"
            if not records
            else (
                "recorded"
                if not expected_objects or object_id in expected_objects
                else "mismatched_ref"
            )
        )
        entries.append(
            {
                "ref": ref,
                "object": object_id,
                "tag_object": object_name,
                "created_at": created_at,
                "subject": subject,
                "status": record_status,
                "record_status": record_status,
                "checkpoint": checkpoint,
                "task_ids": sorted({record["task_id"] for record in records}),
                "record_sources": [
                    {
                        "task_id": record["task_id"],
                        "source": record["source"],
                        "point_id": record["point"].get("id"),
                    }
                    for record in records
                ],
            }
        )
        seen_refs.add(ref)
    missing_entries: list[dict[str, Any]] = []
    for ref, records in records_by_ref.items():
        if ref in seen_refs:
            continue
        checkpoint = records[0]["point"]
        missing_entries.append(
            {
                "ref": ref,
                "object": checkpoint.get("object"),
                "tag_object": None,
                "created_at": checkpoint.get("created_at"),
                "subject": "",
                "status": "missing_ref",
                "record_status": "missing_ref",
                "checkpoint": checkpoint,
                "task_ids": sorted({record["task_id"] for record in records}),
                "record_sources": [
                    {
                        "task_id": record["task_id"],
                        "source": record["source"],
                        "point_id": record["point"].get("id"),
                    }
                    for record in records
                ],
            }
        )
    missing_entries.sort(key=lambda entry: str(entry.get("created_at") or ""), reverse=True)
    entries.extend(missing_entries)
    return entries


def workspace_checkpoint_protection_state(
    control, repo: pathlib.Path, state: dict[str, pathlib.Path], receipt: dict[str, Any]
) -> dict[str, Any]:
    return workspace_checkpoint_protections_projection(
        control, receipt, workspace_checkpoint_refs(control, repo, state)
    )


def workspace_checkpoint_preview(
    control,
    repo: pathlib.Path,
    state: dict[str, pathlib.Path],
    *,
    kind: str | None,
    scopes: list[str],
    protection_id: str | None = None,
) -> dict[str, Any]:
    if control.workspace_storage_mode(repo) != "git":
        return {
            "status": "not_applicable",
            "reason": "git_workspace_required",
            "kind": kind,
            "scope": list(scopes),
            "dirty": [],
            "staged": [],
            "control_metadata": [],
            "control_metadata_staged": [],
            "out_of_scope": [],
            "user_owned": [],
            "forbidden": [],
            "required_proofs": [],
            "missing_proofs": [],
            "protection": None,
            "dirty_baseline_requires_protection": False,
            "head": None,
            "branch": None,
            "workspace_fingerprint": None,
        }
    status = control.current_status(repo)
    all_dirty = workspace_dirty_paths(control, status)
    control_metadata = sorted(
        (path for path in all_dirty if control.workspace_control_metadata_path(path))
    )
    dirty = [path for path in all_dirty if not control.workspace_control_metadata_path(path)]
    staged_output = control.git(repo, "diff", "--cached", "--name-only", check=False)
    all_staged = sorted((path for path in staged_output.splitlines() if path))
    control_metadata_staged = [
        path for path in all_staged if control.workspace_control_metadata_path(path)
    ]
    staged = [path for path in all_staged if not control.workspace_control_metadata_path(path)]
    normalized_scopes = control.normalize_scopes(repo, scopes) if scopes else []
    receipt = None
    continuity = None
    try:
        (receipt, _) = control.resolve_branch_task(repo, state)
        if receipt:
            receipt = control.normalize_receipt(receipt)
            continuity = control.continuity_from_receipt(receipt)
    except (OSError, ValueError, json.JSONDecodeError):
        receipt = None
    protection = (
        find_workspace_checkpoint_protection(control, receipt, protection_id) if receipt else None
    )
    protection_scope_mismatch = False
    if protection is not None:
        protected_scope = (
            list(protection.get("scope", [])) if isinstance(protection.get("scope"), list) else []
        )
        if normalized_scopes and normalized_scopes != protected_scope:
            protection_scope_mismatch = True
        elif not normalized_scopes:
            normalized_scopes = protected_scope
    out_of_scope = [
        path
        for path in dirty
        if normalized_scopes and (not control.path_in_scope(path, normalized_scopes))
    ]
    forbidden = [path for path in normalized_scopes if workspace_sensitive_path(control, path)]
    baseline_paths = set(receipt.get("worktree_baseline", {})) if receipt else set()
    user_owned = sorted((path for path in dirty if path in baseline_paths))
    if protection is not None and kind == "archive" and (receipt is not None):
        (required_proofs, missing_proofs) = workspace_required_proofs(
            control, repo, receipt, continuity, node_ids=[str(protection.get("node_id"))]
        )
    elif protection is not None:
        (required_proofs, missing_proofs) = ([], [])
    else:
        (required_proofs, missing_proofs) = (
            workspace_required_proofs(control, repo, receipt, continuity) if receipt else ([], [])
        )
    checkpoint_refs = (
        workspace_checkpoint_refs(control, repo, state) if protection is not None else []
    )
    protection_view = (
        workspace_checkpoint_protection_projection(control, protection, checkpoint_refs)
        if protection is not None
        else None
    )
    protected_baseline = protection is not None and kind == "baseline"
    dirty_baseline_requires_protection = bool(dirty and kind == "baseline" and (protection is None))
    return {
        "status": (
            "blocked"
            if staged
            or forbidden
            or out_of_scope
            or (user_owned and protection is None)
            or (protection_id and protection is None)
            or protection_scope_mismatch
            or dirty_baseline_requires_protection
            else "ready"
        ),
        "kind": kind,
        "scope": normalized_scopes,
        "dirty": dirty,
        "staged": staged,
        "control_metadata": control_metadata,
        "control_metadata_staged": control_metadata_staged,
        "out_of_scope": out_of_scope,
        "user_owned": user_owned,
        "forbidden": forbidden,
        "required_proofs": required_proofs,
        "missing_proofs": missing_proofs,
        "protection": protection_view,
        "protection_scope_mismatch": protection_scope_mismatch,
        "allow_dirty_baseline": protected_baseline,
        "dirty_baseline_requires_protection": dirty_baseline_requires_protection,
        "head": control.git_head(repo),
        "branch": control.current_branch(repo),
        "workspace_fingerprint": workspace_scope_digest(control, repo, normalized_scopes),
    }


def command_workspace_checkpoint_protect(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    if control.workspace_storage_mode(repo) != "git":
        raise ValueError("workspace checkpoint protection requires a managed Git workspace")
    state = control.ensure_root(repo)
    receipt = control.require_active(state)
    loaded_revision = int(receipt.get("state_revision", 0))
    continuity = control.continuity_from_receipt(receipt)
    if continuity is None or not continuity.get("plan", {}).get("nodes"):
        raise ValueError("workspace checkpoint protection requires an initialized continuity plan")
    node_id = control.require_continuity_id("protection node", args.node)
    nodes = {node["id"]: node for node in continuity["plan"]["nodes"]}
    if node_id not in nodes:
        raise ValueError(f"workspace checkpoint protection node does not exist: {node_id}")
    if continuity.get("current_node") != node_id or nodes[node_id].get("status") != "active":
        raise ValueError("workspace checkpoint protection requires the current active plan node")
    confirmation_source = control.require_concrete(
        "workspace checkpoint protection confirmation source", args.confirmation_source
    )
    requested_scope = list(args.scope or [])
    if requested_scope:
        protected_scope = control.normalize_scopes(repo, requested_scope)
    else:
        planned_scope = receipt.get("planned_scope", [])
        protected_scope = (
            control.normalize_scopes(repo, planned_scope) if isinstance(planned_scope, list) else []
        )
    if not protected_scope:
        raise ValueError("workspace checkpoint protection requires at least one product --scope")
    protections = continuity.setdefault("workspace_checkpoint_protections", [])
    existing = next(
        (
            protection
            for protection in protections
            if isinstance(protection, dict) and protection.get("node_id") == node_id
        ),
        None,
    )
    if existing is not None:
        existing_scope = existing.get("scope") if isinstance(existing.get("scope"), list) else []
        if existing_scope != protected_scope:
            raise ValueError(
                "current node already has a workspace checkpoint protection with a different scope"
            )
        protection_view = workspace_checkpoint_protection_projection(
            control, existing, workspace_checkpoint_refs(control, repo, state)
        )
        print(
            json.dumps(
                {
                    "status": "existing",
                    "protection": protection_view,
                    "receipt": workspace_checkpoint_protection_receipt(control, existing),
                },
                ensure_ascii=False,
            )
        )
        return 0
    protection_id = f"workspace-protection-{archive_slug(control, node_id)}-{len(protections) + 1}"
    protection = {
        "id": protection_id,
        "node_id": node_id,
        "scope": protected_scope,
        "scope_sha256": workspace_scope_digest(control, repo, protected_scope),
        "plan_revision": int(continuity.get("plan", {}).get("revision", 0)),
        "confirmation_source": confirmation_source,
        "created_at": control.now(),
        "updated_at": control.now(),
        "before": {"status": "pending"},
        "after": {"status": "pending", "required_proofs": []},
    }
    protections.append(protection)
    continuity["updated_at"] = control.now()
    control.continuity_event(receipt, "workspace_checkpoint_protected", protection=protection)
    next_revision = control.write_active(state, receipt, expected_revision=loaded_revision)
    print(
        json.dumps(
            {
                "status": "armed",
                "protection": workspace_checkpoint_protection_projection(control, protection, []),
                "state_revision": next_revision,
                "receipt": workspace_checkpoint_protection_receipt(control, protection),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_workspace_checkpoint(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.paths(repo)
    kind = getattr(args, "kind", None)
    scopes = list(getattr(args, "scope", []) or [])
    protection_id = getattr(args, "protection_id", None)
    if protection_id:
        protection_id = control.require_continuity_id(
            "workspace checkpoint protection id", protection_id
        )
    if args.workspace_checkpoint_command == "list":
        if control.workspace_storage_mode(repo) != "git":
            print(
                json.dumps(
                    {
                        "status": "not_applicable",
                        "reason": "git_workspace_required",
                        "checkpoints": [],
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        print(
            json.dumps(
                {"status": "ready", "checkpoints": workspace_checkpoint_refs(control, repo, state)},
                ensure_ascii=False,
            )
        )
        return 0
    if args.workspace_checkpoint_command == "protect":
        return command_workspace_checkpoint_protect(control, args)
    preview = workspace_checkpoint_preview(
        control, repo, state, kind=kind, scopes=scopes, protection_id=protection_id
    )
    if args.workspace_checkpoint_command == "inspect":
        print(json.dumps(preview, ensure_ascii=False))
        return 0
    if args.workspace_checkpoint_command != "create":
        raise ValueError("unsupported workspace checkpoint command")
    if preview["status"] == "not_applicable":
        raise ValueError("workspace checkpoint requires a managed Git workspace")
    receipt = control.require_active(state)
    confirmation_source = control.require_concrete(
        "workspace checkpoint confirmation source", args.confirmation_source or ""
    )
    if kind not in {"baseline", "milestone", "archive"}:
        raise ValueError(
            "workspace checkpoint create requires --kind baseline, milestone, or archive"
        )
    protection = find_workspace_checkpoint_protection(control, receipt, protection_id)
    if protection_id and protection is None:
        raise ValueError(f"workspace checkpoint protection does not exist: {protection_id}")
    if preview["protection_scope_mismatch"]:
        raise ValueError("workspace checkpoint scope must match the armed protection scope")
    if protection is not None and kind not in {"baseline", "archive"}:
        raise ValueError(
            "protected workspace checkpoint only supports kind=baseline or kind=archive"
        )
    if protection is not None:
        protection_view = (
            preview.get("protection") if isinstance(preview.get("protection"), dict) else {}
        )
        if kind == "baseline" and protection_view.get("before", {}).get("status") != "pending":
            raise ValueError("protected baseline checkpoint is already recorded or invalid")
        if kind == "archive":
            if protection_view.get("before", {}).get("status") != "recorded":
                raise ValueError(
                    "protected archive checkpoint requires a recorded baseline checkpoint"
                )
            if protection_view.get("after", {}).get("status") != "pending":
                raise ValueError("protected archive checkpoint is already recorded or invalid")
    if kind == "archive" and (not scopes) and (protection is None):
        raise ValueError("archive checkpoint requires at least one explicit --scope")
    if preview["staged"]:
        raise ValueError("workspace checkpoint rejects pre-existing staged changes")
    if preview["forbidden"]:
        raise ValueError(
            "workspace checkpoint rejects sensitive paths: " + ", ".join(preview["forbidden"])
        )
    if preview["out_of_scope"]:
        raise ValueError(
            "workspace checkpoint scope does not cover dirty paths: "
            + ", ".join(preview["out_of_scope"])
        )
    if preview["user_owned"] and protection is None:
        raise ValueError(
            "workspace checkpoint rejects user-owned baseline changes: "
            + ", ".join(preview["user_owned"])
        )
    if preview["missing_proofs"] and kind == "archive":
        raise ValueError(
            "archive checkpoint requires fresh proofs: " + ", ".join(preview["missing_proofs"])
        )
    state = control.ensure_root(repo)
    loaded_revision = int(receipt.get("state_revision", 0))
    before_head = control.git_head(repo)
    recorded_scope = preview["scope"]
    if not recorded_scope and kind in {"baseline", "milestone"}:
        planned_scope = receipt.get("planned_scope", [])
        recorded_scope = (
            control.normalize_scopes(repo, planned_scope) if isinstance(planned_scope, list) else []
        )
    before_digest = workspace_scope_digest(control, repo, recorded_scope)
    task_slug = archive_slug(control, str(receipt.get("id") or "task"))
    prefix = f"auto-dev/{task_slug}/{kind}"
    tag_name = prefix
    index = 2
    while control.git(repo, "rev-parse", "--verify", tag_name, check=False):
        tag_name = f"{prefix}-{index}"
        index += 1
    if preview["dirty"]:
        if kind != "archive" and (not (protection is not None and kind == "baseline")):
            raise ValueError("dirty workspace checkpoints only support kind=archive")
        if not recorded_scope:
            raise ValueError("dirty workspace checkpoint requires a product scope")
        control.git(repo, "add", "--", *preview["scope"])
        staged_after = [
            path
            for path in control.git(
                repo, "diff", "--cached", "--name-only", check=False
            ).splitlines()
            if not control.workspace_control_metadata_path(path)
        ]
        if not staged_after or any(
            (not control.path_in_scope(path, recorded_scope) for path in staged_after)
        ):
            raise ValueError("workspace checkpoint staged scope is invalid")
        control.git(
            repo,
            "commit",
            "--only",
            "-m",
            f"Auto Dev {kind} point: {receipt.get('id')}",
            "--",
            *recorded_scope,
        )
    control.git(repo, "tag", "-a", tag_name, "-m", f"Auto Dev {kind}: {receipt.get('id')}")
    ref_name = f"refs/tags/{tag_name}"
    point = {
        "id": f"workspace-{control.hashlib.sha256((tag_name + before_digest).encode('utf-8')).hexdigest()[:16]}",
        "kind": kind,
        "archive_phase": workspace_checkpoint_phase(control, kind),
        "receipt_key": workspace_checkpoint_receipt_key(
            control, workspace_checkpoint_phase(control, kind)
        ),
        "ref": ref_name,
        "object": control.git(repo, "rev-list", "-n", "1", tag_name),
        "branch": control.current_branch(repo),
        "head_before": before_head,
        "head_after": control.git_head(repo),
        "scope": recorded_scope,
        "scope_sha256": before_digest,
        "required_proofs": preview["required_proofs"],
        "proof_refs": preview["required_proofs"],
        "task_id": receipt.get("id"),
        "task_state_revision": loaded_revision + 1,
        "plan_revision": (
            int(control.continuity_from_receipt(receipt).get("plan", {}).get("revision", 0))
            if control.continuity_from_receipt(receipt)
            else 0
        ),
        "confirmation_source": confirmation_source,
        "created_at": control.now(),
    }
    if protection is not None:
        protection_phase = "before" if kind == "baseline" else "after"
        point["protection_id"] = protection["id"]
        point["protection_phase"] = protection_phase
    point["receipt"] = workspace_checkpoint_receipt(control, point)
    continuity = control.continuity_from_receipt(receipt)
    if continuity is None:
        receipt.setdefault("workspace_points", []).append(point)
    else:
        continuity.setdefault("workspace_points", []).append(point)
        if protection is not None:
            protection_phase = str(point["protection_phase"])
            protected_point = protection.setdefault(protection_phase, {})
            protected_point.update(
                {
                    "status": "recorded",
                    "point_id": point["id"],
                    "ref": point["ref"],
                    "object": point["object"],
                    "recorded_at": point["created_at"],
                    "required_proofs": list(point["proof_refs"]),
                }
            )
            protection["updated_at"] = control.now()
        continuity["updated_at"] = control.now()
    control.continuity_event(receipt, "workspace_checkpoint_created", point=point)
    next_revision = control.write_active(state, receipt, expected_revision=loaded_revision)
    readback = control.git(repo, "rev-parse", "--verify", ref_name, check=False)
    if not readback:
        raise ValueError("workspace checkpoint ref readback failed")
    print(
        json.dumps(
            {
                "status": "created",
                "kind": kind,
                "ref": ref_name,
                "object": point["object"],
                "state_revision": next_revision,
                "checkpoint": workspace_point_projection(control, point),
                "protection_id": protection.get("id") if protection is not None else None,
                "receipt": point["receipt"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_workspace_rollback_inspect(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    target = control.require_concrete("rollback target", args.target or "")
    result = control.git(repo, "rev-parse", "--verify", f"{target}^{{}}", check=False)
    if not result:
        raise ValueError(f"rollback target is not a resolvable Git ref: {target}")
    resolved_ref = control.git(
        repo, "rev-parse", "--symbolic-full-name", "--verify", target, check=False
    )
    state = control.paths(repo)
    point = next(
        (
            entry
            for entry in workspace_checkpoint_refs(control, repo, state)
            if entry.get("ref") == resolved_ref
        ),
        None,
    )
    checkpoint = point.get("checkpoint") if isinstance(point, dict) else None
    scope = checkpoint.get("scope", []) if isinstance(checkpoint, dict) else []
    current_changes = workspace_dirty_paths(
        control, control.workspace_product_status(control.current_status(repo))
    )
    scoped_changes = [
        path
        for path in current_changes
        if any((control.path_in_scope(path, scope_item) for scope_item in scope))
    ]
    risks = ["rollback apply is deferred in P0; this command does not modify the workspace"]
    if not point:
        risks.append("target is not a recorded Auto Dev workspace point")
    elif point.get("status") != "recorded":
        risks.append(f"workspace point record status is {point.get('status')}")
    if current_changes:
        risks.append(
            "current workspace changes must be reconciled before any future rollback apply"
        )
    print(
        json.dumps(
            {
                "status": "preview",
                "target": target,
                "resolved_ref": resolved_ref or None,
                "object": result,
                "current_head": control.git_head(repo),
                "current_status": control.workspace_product_status(control.current_status(repo)),
                "current_workspace_changes": current_changes,
                "current_changes_in_scope": scoped_changes,
                "task_owned_paths": scope,
                "archive_point": point,
                "risks": risks,
                "apply": "deferred",
                "strategy": "inspect only; no workspace mutation",
            },
            ensure_ascii=False,
        )
    )
    return 0
