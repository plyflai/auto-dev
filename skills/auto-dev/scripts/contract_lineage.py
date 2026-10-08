"""Normalize and merge inherited Auto Dev outcome contracts.

The module is deliberately pure.  ``runctl.py`` owns persistence and revision
checks; this file owns the small, deterministic contract algebra shared by
Intake, Outcome, Task, Plan, Proof, and Hook projections.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Iterable


CONTRACT_SCHEMA_VERSION = 1
STRICT_CONTRACT_MODES = {"strict", "legacy-parity", "migration", "fork", "compatibility"}
CONTRACT_MODES = {"standard", "strict", *STRICT_CONTRACT_MODES}
EVIDENCE_KINDS = {
    "supporting",
    "build",
    "test",
    "route-matrix",
    "workflow",
    "visual-parity",
    "compatibility",
    "artifact",
}
WRITE_GATES = {"before_product_write"}
PREWRITE_EVIDENCE_KINDS = {"route-matrix", "workflow", "visual-parity", "compatibility"}


def _text(label: str, value: Any, *, required: bool = True) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{label} requires a value")
    return result


def _unique_strings(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        raise ValueError("contract list must be an array")
    result: list[str] = []
    for value in values:
        item = _text("contract item", value)
        if item not in result:
            result.append(item)
    return result


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value) if key not in {"hash", "effective_hash"}}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def contract_hash(contract: dict[str, Any]) -> str:
    encoded = json.dumps(_canonical(contract), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def with_contract_hash(contract: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(contract)
    result["hash"] = contract_hash(result)
    return result


def _normalize_hard_constraints(raw: Any, *, namespace: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("contract hard_constraints must be an array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            item = {"id": f"{namespace}.H{index}", "kind": "must_preserve", "text": item}
        if not isinstance(item, dict):
            raise ValueError("each hard constraint must be an object or string")
        identifier = _text(
            "hard constraint id", item.get("id") or f"{namespace}.H{index}"
        )
        if identifier in seen:
            raise ValueError(f"duplicate hard constraint id: {identifier}")
        seen.add(identifier)
        kind = _text("hard constraint kind", item.get("kind") or "must_preserve")
        text = _text("hard constraint text", item.get("text") or item.get("description"))
        normalized = {"id": identifier, "kind": kind, "text": text}
        if item.get("anchor") is True:
            normalized["anchor"] = True
        result.append(normalized)
    return result


def _normalize_replacements(raw: Any, *, namespace: str) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("contract replacement_map must be an array")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError("each replacement mapping must be an object")
        identifier = _text(
            "replacement id", item.get("id") or f"{namespace}.R{index}"
        )
        if identifier in seen:
            raise ValueError(f"duplicate replacement id: {identifier}")
        seen.add(identifier)
        source = _text("replacement from", item.get("from") or item.get("source"))
        target = _text("replacement to", item.get("to") or item.get("target"))
        result.append({"id": identifier, "from": source, "to": target})
    return result


def _normalize_coverage(raw: Any, *, namespace: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("contract required_coverage must be an array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            item = {"id": f"{namespace}.C{index}", "description": item}
        if not isinstance(item, dict):
            raise ValueError("each required coverage item must be an object or string")
        identifier = _text("coverage id", item.get("id") or f"{namespace}.C{index}")
        if identifier in seen:
            raise ValueError(f"duplicate coverage id: {identifier}")
        seen.add(identifier)
        evidence_kind = _text("coverage evidence kind", item.get("evidence_kind") or "supporting")
        if evidence_kind not in EVIDENCE_KINDS:
            raise ValueError(f"unsupported coverage evidence kind: {evidence_kind}")
        normalized: dict[str, Any] = {
            "id": identifier,
            "description": _text("coverage description", item.get("description") or item.get("text")),
            "evidence_kind": evidence_kind,
        }
        write_gate = item.get("write_gate")
        if write_gate is not None:
            write_gate = _text("coverage write gate", write_gate)
            if write_gate not in WRITE_GATES:
                raise ValueError(f"unsupported coverage write gate: {write_gate}")
            normalized["write_gate"] = write_gate
        artifact_schema = item.get("artifact_schema")
        if artifact_schema is not None:
            normalized["artifact_schema"] = _text("coverage artifact schema", artifact_schema)
        proof_ids = item.get("proof_ids")
        if proof_ids is not None:
            normalized["proof_ids"] = _unique_strings(proof_ids)
        result.append(normalized)
    return result


def normalize_contract(
    raw: Any,
    *,
    default_id: str,
    default_mainline: str = "",
    parent_refs: Iterable[str] = (),
) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("contract must be an object")
    mode = _text("contract mode", raw.get("mode") or "standard")
    if mode not in CONTRACT_MODES:
        raise ValueError(f"unsupported contract mode: {mode}")
    raw_mainline = raw.get("mainline")
    mainline_explicit = bool(str(raw_mainline or "").strip())
    refs = list(dict.fromkeys([
        *_unique_strings(raw.get("parent_refs")),
        *_unique_strings(list(parent_refs)),
    ]))
    identifier = _text("contract id", raw.get("id") or default_id)
    required_coverage = _normalize_coverage(
        raw.get("required_coverage", raw.get("coverage")), namespace=identifier
    )
    # Fork/migration contracts need one evidence-backed reference gate before
    # product work can start. Existing snapshots remain readable; new strict
    # contracts get the default only when they declare a matching coverage.
    if mode in {"legacy-parity", "migration", "fork", "compatibility"} and not any(
        item.get("write_gate") for item in required_coverage
    ):
        for item in required_coverage:
            if item.get("evidence_kind") in PREWRITE_EVIDENCE_KINDS:
                item["write_gate"] = "before_product_write"
                break
    result: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "id": identifier,
        "revision": int(raw.get("revision", 1)),
        "mode": mode,
        "mainline": _text("contract mainline", raw_mainline or default_mainline, required=False),
        "mainline_explicit": mainline_explicit,
        "hard_constraints": _normalize_hard_constraints(
            raw.get("hard_constraints", raw.get("must_preserve")), namespace=identifier
        ),
        "forbidden_moves": _unique_strings(raw.get("forbidden_moves", raw.get("forbidden"))),
        "replacement_map": _normalize_replacements(
            raw.get("replacement_map"), namespace=identifier
        ),
        "required_coverage": required_coverage,
        "non_claims": _unique_strings(raw.get("non_claims")),
        "parent_refs": refs,
    }
    return with_contract_hash(result)


def _merge_records(
    parent: list[dict[str, Any]],
    child: list[dict[str, Any]],
    *,
    key: str,
    label: str,
) -> list[dict[str, Any]]:
    result = copy.deepcopy(parent)
    by_id = {str(item.get(key)): item for item in result if isinstance(item, dict) and item.get(key)}
    for item in child:
        identifier = str(item.get(key) or "")
        existing = by_id.get(identifier)
        if existing is not None and _canonical(existing) != _canonical(item):
            raise ValueError(f"inherited contract conflict for {label}: {identifier}")
        if existing is None:
            result.append(copy.deepcopy(item))
            by_id[identifier] = result[-1]
    return result


def merge_contracts(parent: dict[str, Any] | None, child: dict[str, Any] | None) -> dict[str, Any] | None:
    if parent is None:
        return copy.deepcopy(child) if child is not None else None
    if child is None:
        return copy.deepcopy(parent)
    # Intake and the selected Project Frame intentionally point at the same
    # confirmed contract. Treat that replay as idempotent so lineage hashes
    # remain stable across status reads and Hook refreshes.
    if _canonical(parent) == _canonical(child):
        return copy.deepcopy(parent)
    parent_mainline = _text("parent contract mainline", parent.get("mainline"), required=False)
    child_mainline = _text("child contract mainline", child.get("mainline"), required=False)
    if (
        parent_mainline
        and child_mainline
        and child_mainline != parent_mainline
        and child.get("mainline_explicit", True)
    ):
        raise ValueError("inherited contract conflict for mainline")
    result = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "id": child.get("id") or parent.get("id"),
        "revision": max(int(parent.get("revision", 1)), int(child.get("revision", 1))),
        "mode": child.get("mode") if child.get("mode") in STRICT_CONTRACT_MODES else parent.get("mode", "standard"),
        "mainline": parent_mainline or child_mainline,
        "mainline_explicit": bool(parent.get("mainline_explicit") or child.get("mainline_explicit")),
        "hard_constraints": _merge_records(
            parent.get("hard_constraints", []), child.get("hard_constraints", []),
            key="id", label="hard constraint",
        ),
        "forbidden_moves": list(dict.fromkeys([
            *parent.get("forbidden_moves", []), *child.get("forbidden_moves", []),
        ])),
        "replacement_map": _merge_records(
            parent.get("replacement_map", []), child.get("replacement_map", []),
            key="id", label="replacement mapping",
        ),
        "required_coverage": _merge_records(
            parent.get("required_coverage", []), child.get("required_coverage", []),
            key="id", label="coverage",
        ),
        "non_claims": list(dict.fromkeys([
            *parent.get("non_claims", []), *child.get("non_claims", []),
        ])),
        "parent_refs": list(dict.fromkeys([
            *parent.get("parent_refs", []),
            str(parent.get("hash") or ""),
            *child.get("parent_refs", []),
        ])),
    }
    if result["mode"] not in CONTRACT_MODES:
        result["mode"] = "standard"
    return with_contract_hash(result)


def is_strict(contract: dict[str, Any] | None) -> bool:
    return bool(contract and contract.get("mode") in STRICT_CONTRACT_MODES)


def coverage_ids(contract: dict[str, Any] | None) -> list[str]:
    if not contract:
        return []
    return [str(item["id"]) for item in contract.get("required_coverage", []) if isinstance(item, dict) and item.get("id")]


def missing_coverage(contract: dict[str, Any] | None, covered: Iterable[str]) -> list[str]:
    covered_set = {str(value) for value in covered}
    return [identifier for identifier in coverage_ids(contract) if identifier not in covered_set]


def prewrite_coverage_ids(contract: dict[str, Any] | None) -> list[str]:
    if not contract:
        return []
    return [
        str(item["id"])
        for item in contract.get("required_coverage", [])
        if isinstance(item, dict)
        and item.get("id")
        and item.get("write_gate") == "before_product_write"
    ]


def _capsule_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def capsule(
    contract: dict[str, Any] | None,
    *,
    current_node: str | None = None,
    task_coverage: Iterable[str] = (),
    max_hard: int = 3,
    max_coverage: int = 4,
) -> dict[str, Any]:
    if not contract:
        return {"status": "legacy"}
    relevant = set(str(value) for value in task_coverage)
    all_hard = contract.get("hard_constraints", [])
    anchor_hard = [item for item in all_hard if isinstance(item, dict) and item.get("anchor") is True]
    hard_candidates = anchor_hard + [
        item for item in all_hard
        if isinstance(item, dict) and item not in anchor_hard
    ]
    hard = [
        {
            "id": item.get("id"),
            "kind": item.get("kind"),
            "text": _capsule_text(item.get("text"), 180),
        }
        for item in hard_candidates[:max_hard]
        if isinstance(item, dict)
    ]
    all_required = contract.get("required_coverage", [])
    required = all_required
    if relevant:
        required = [item for item in required if str(item.get("id")) in relevant]
    required = [
        {
            "id": item.get("id"),
            "description": _capsule_text(item.get("description"), 160),
            "evidence_kind": item.get("evidence_kind"),
            **({"write_gate": item["write_gate"]} if item.get("write_gate") else {}),
            **({"artifact_schema": item["artifact_schema"]} if item.get("artifact_schema") else {}),
        }
        for item in required[:max_coverage]
        if isinstance(item, dict)
    ]
    all_forbidden = contract.get("forbidden_moves", [])
    forbidden = [_capsule_text(item, 180) for item in all_forbidden[:3]]
    all_replacements = contract.get("replacement_map", [])
    replacements = [
        {
            "id": item.get("id"),
            "from": _capsule_text(item.get("from"), 100),
            "to": _capsule_text(item.get("to"), 100),
        }
        for item in all_replacements[:3]
        if isinstance(item, dict)
    ]
    return {
        "status": "strict" if is_strict(contract) else "bound",
        "id": contract.get("id"),
        "revision": contract.get("revision", 1),
        "hash": contract.get("hash") or contract_hash(contract),
        "mode": contract.get("mode", "standard"),
        "mainline": _capsule_text(contract.get("mainline"), 220),
        "hard_constraints": hard,
        "forbidden_moves": forbidden,
        "replacement_map": replacements,
        "required_coverage": required,
        "hard_constraint_count": len(all_hard),
        "forbidden_move_count": len(all_forbidden),
        "replacement_count": len(all_replacements),
        "required_coverage_count": len(all_required),
        "task_coverage": list(dict.fromkeys(str(value) for value in task_coverage)),
        "current_node": current_node,
        "non_claims": [_capsule_text(item, 120) for item in contract.get("non_claims", [])[:2]],
    }
