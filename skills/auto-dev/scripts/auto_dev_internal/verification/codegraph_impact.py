"""Bounded CodeGraph impact analysis and coverage classification."""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Iterable


DEFAULT_MAX_DEPTH = 8
MAX_ALLOWED_DEPTH = 32
INFERRED_TEST_FILTERS = {
    "python": ("tests/test_*.py",),
}


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _depths(max_depth: int) -> list[int]:
    if isinstance(max_depth, bool) or not isinstance(max_depth, int):
        raise ValueError("impact max depth must be an integer")
    if max_depth < 2 or max_depth > MAX_ALLOWED_DEPTH:
        raise ValueError(f"impact max depth must be between 2 and {MAX_ALLOWED_DEPTH}")
    values = list(range(2, max_depth + 1, 2))
    if values[-1] != max_depth:
        values.append(max_depth)
    return values


def _impact_signature(payload: dict[str, Any]) -> str:
    affected = [raw for raw in payload.get("affected", []) if isinstance(raw, dict)]
    affected.sort(key=lambda raw: json.dumps(raw, ensure_ascii=False, sort_keys=True))
    return _canonical_sha256({
        "nodeCount": int(payload.get("nodeCount", 0) or 0),
        "edgeCount": int(payload.get("edgeCount", 0) or 0),
        "affected": affected,
    })


def _test_filters(
    control,
    *,
    explicit: Iterable[str],
    languages: Iterable[str],
) -> tuple[list[str], str]:
    configured = control.merge_unique(explicit)
    if configured:
        return configured, "configured"
    inferred: list[str] = []
    for language in languages:
        for pattern in INFERRED_TEST_FILTERS.get(str(language).casefold(), ()):
            if pattern not in inferred:
                inferred.append(pattern)
    return inferred, "inferred" if inferred else "codegraph_default"


def impact_inspection(
    control,
    repo: pathlib.Path,
    *,
    symbols: Iterable[str],
    files: Iterable[str],
    max_depth: int = DEFAULT_MAX_DEPTH,
    test_filters: Iterable[str] = (),
) -> dict[str, Any]:
    symbol_targets = control.merge_unique(symbols)
    file_targets = control.normalize_scopes(repo, files)
    if not symbol_targets and not file_targets:
        raise ValueError("impact inspection requires at least one --symbol or --file")

    depth_values = _depths(max_depth)
    index = control.codegraph_status_snapshot(repo)
    symbol_results: list[dict[str, Any]] = []
    affected_symbols: list[dict[str, Any]] = []
    invalid_paths: list[str] = []
    coverage_reasons: list[str] = []

    for symbol in symbol_targets:
        previous_signature: str | None = None
        stabilized = False
        depths_checked: list[int] = []
        result: dict[str, Any] = {}
        for depth in depth_values:
            result = control.codegraph_json(repo, ["impact", symbol, "-d", str(depth), "-j"])
            depths_checked.append(depth)
            signature = _impact_signature(result)
            if signature == previous_signature:
                stabilized = True
                break
            previous_signature = signature
        if not stabilized:
            coverage_reasons.append(f"symbol_depth_limit_reached:{symbol}")

        affected: list[dict[str, Any]] = []
        for raw in result.get("affected", []):
            if not isinstance(raw, dict):
                continue
            item = {
                "name": raw.get("name"),
                "kind": raw.get("kind"),
                "file_path": control.normalized_codegraph_path(repo, raw.get("filePath")),
                "start_line": raw.get("startLine"),
            }
            if raw.get("filePath") and item["file_path"] is None:
                invalid_paths.append(str(raw.get("filePath")))
            if item not in affected:
                affected.append(item)
            if item not in affected_symbols:
                affected_symbols.append(item)
        symbol_results.append({
            "symbol": symbol,
            "node_count": int(result.get("nodeCount", 0) or 0),
            "edge_count": int(result.get("edgeCount", 0) or 0),
            "affected": affected,
            "depths_checked": depths_checked,
            "max_depth": max_depth,
            "stabilized": stabilized,
            "coverage_status": "complete" if stabilized else "partial",
            "result_sha256": _canonical_sha256(result),
        })

    affected_tests: list[str] = []
    affected_result: dict[str, Any] | None = None
    if file_targets:
        filters, filter_source = _test_filters(
            control, explicit=test_filters, languages=index.get("languages", [])
        )
        query_filters: list[str | None] = list(filters) or [None]
        query_results: list[dict[str, Any]] = []
        total_dependents = 0
        for pattern in query_filters:
            arguments = ["affected", *file_targets]
            if pattern is not None:
                arguments.extend(["-f", pattern])
            arguments.append("-j")
            raw_affected = control.codegraph_json(repo, arguments)
            total_dependents = max(
                total_dependents,
                int(raw_affected.get("totalDependentsTraversed", 0) or 0),
            )
            for raw in raw_affected.get("affectedTests", []):
                value = raw.get("filePath") if isinstance(raw, dict) else raw
                normalized = control.normalized_codegraph_path(repo, value)
                if normalized and normalized not in affected_tests:
                    affected_tests.append(normalized)
                elif value and normalized is None:
                    invalid_paths.append(str(value))
            query_results.append({
                "filter": pattern,
                "result_sha256": _canonical_sha256(raw_affected),
            })
        discovery_status = "verified" if filters else "unverified"
        affected_result = {
            "changed_files": file_targets,
            "affected_tests": affected_tests,
            "total_dependents_traversed": total_dependents,
            "test_filters": filters,
            "test_discovery": {
                "status": discovery_status,
                "source": filter_source,
                "languages": index.get("languages", []),
            },
            "queries": query_results,
            "result_sha256": _canonical_sha256(query_results),
        }
        if discovery_status != "verified":
            coverage_reasons.append("test_discovery_unverified")
        if not symbol_targets and total_dependents > 0:
            coverage_reasons.append("file_dependents_not_enumerated")

    if invalid_paths:
        coverage_reasons.append("codegraph_paths_outside_workspace")
    coverage_reasons = list(dict.fromkeys(coverage_reasons))
    coverage_status = (
        "unknown"
        if "test_discovery_unverified" in coverage_reasons
        else "partial"
        if coverage_reasons
        else "complete"
    )

    scope_candidates = list(file_targets)
    for item in affected_symbols:
        if item.get("file_path"):
            scope_candidates.append(str(item["file_path"]))
    scope_candidates.extend(affected_tests)
    known_scope = control.merge_unique(scope_candidates)
    dependent_signal = any(
        result["node_count"] > 1 or result["edge_count"] > 0
        for result in symbol_results
    ) or bool(
        affected_result and affected_result["total_dependents_traversed"] > 0
    ) or bool(affected_tests)
    dynamic_risks: list[str] = []
    if not affected_tests:
        dynamic_risks.append("no_affected_tests_reported")
    if not dependent_signal:
        dynamic_risks.append("no_dependents_reported")
    if invalid_paths:
        dynamic_risks.append("codegraph_paths_outside_workspace")

    test_discovery = (
        affected_result["test_discovery"]
        if affected_result
        else {"status": "not_applicable", "source": "no_file_targets", "languages": index.get("languages", [])}
    )
    inspection = {
        "targets": {"symbols": symbol_targets, "files": file_targets},
        "codegraph": {
            **index,
            "symbol_results": symbol_results,
            "affected_result": affected_result,
        },
        "affected_symbols": affected_symbols,
        "affected_tests": affected_tests,
        "test_discovery": test_discovery,
        "known_scope": known_scope,
        "scope": known_scope,
        "scope_sha256": control.workspace_scope_digest(repo, known_scope),
        "impact_signal": dependent_signal,
        "coverage_status": coverage_status,
        "coverage_reasons": coverage_reasons,
        "dynamic_risks": dynamic_risks,
        "invalid_paths": sorted(set(invalid_paths)),
    }
    inspection["inspection_sha256"] = _canonical_sha256(inspection)
    return inspection
