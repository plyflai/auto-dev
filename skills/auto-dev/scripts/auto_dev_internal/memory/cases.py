"""Incident-case search and promotion for project memory."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any, Iterable


def memory_digest(control, document: dict[str, Any]) -> str:
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def query_digest(control, values: Iterable[str]) -> str:
    normalized = [value.strip().casefold() for value in values if value.strip()]
    encoded = json.dumps(
        sorted(dict.fromkeys(normalized)), ensure_ascii=False, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def search_terms(control, values: Iterable[str]) -> set[str]:
    terms: set[str] = set()
    for value in values:
        text = value.strip().casefold()
        if not text:
            continue
        terms.add(text)
        terms.update((token for token in re.findall("[\\w./-]+", text) if len(token) >= 2))
    return terms


def incident_case_compact(
    control, entry: dict[str, Any], *, score: int, warnings: list[str]
) -> dict[str, Any]:
    return {
        key: entry.get(key)
        for key in (
            "id",
            "kind",
            "case_type",
            "title",
            "keywords",
            "symptom_signals",
            "scope",
            "component_refs",
            "environment",
            "observed_version",
            "root_cause",
            "cause_class",
            "distinguishing_signals",
            "resolution_summary",
            "protective_tests",
            "lesson",
            "evidence_refs",
            "source_task_id",
            "status",
            "observed_head",
            "created_at",
            "updated_at",
        )
        if key in entry
    } | {"score": score, "warnings": warnings}


def search_incident_cases(
    control,
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
    document = control.load(control.registry_path(repo))
    symptom_values = control.safe_list("case symptom", symptoms, required=False)
    keyword_values = control.safe_list("case keyword", keywords, required=False)
    scope_values = control.safe_list("case scope", scopes, required=False)
    component_values = control.safe_list("case component", components, required=False)
    environment_values = control.safe_list("case environment", environment, required=False)
    version = control.optional_safe("case observed version", observed_version)
    query_values = [
        *symptom_values,
        *keyword_values,
        *scope_values,
        *component_values,
        *environment_values,
        *([version] if version else []),
    ]
    if not query_values:
        raise ValueError(
            "incident case search requires at least one symptom, keyword, scope, component, environment, or version"
        )
    requested = search_terms(control, query_values)
    requested_environment = {value.casefold() for value in environment_values}
    requested_scopes = {value.casefold() for value in scope_values}
    requested_components = {value.casefold() for value in component_values}
    matches: list[tuple[int, dict[str, Any], list[str]]] = []
    for entry in document.get("entries", []):
        if (
            not isinstance(entry, dict)
            or entry.get("kind") != "incident_case"
            or entry.get("status") != "confirmed"
        ):
            continue
        searchable: list[str] = []
        for key in (
            "title",
            "keywords",
            "symptom_signals",
            "scope",
            "component_refs",
            "environment",
            "root_cause",
            "cause_class",
            "distinguishing_signals",
            "resolution_summary",
            "lesson",
        ):
            value = entry.get(key)
            (
                searchable.extend((str(item) for item in value))
                if isinstance(value, list)
                else searchable.append(str(value or ""))
            )
        available = search_terms(control, searchable)
        overlap = requested & available
        score = len(overlap)
        entry_scopes = {str(value).casefold() for value in entry.get("scope", [])}
        entry_components = {str(value).casefold() for value in entry.get("component_refs", [])}
        entry_environment = {str(value).casefold() for value in entry.get("environment", [])}
        if requested_scopes & entry_scopes:
            score += 4
        if requested_components & entry_components:
            score += 4
        if requested_environment and requested_environment.issubset(entry_environment):
            score += 2
        warnings: list[str] = []
        if (
            requested_environment
            and entry_environment
            and (not requested_environment.issubset(entry_environment))
        ):
            warnings.append("environment_mismatch")
        entry_version = str(entry.get("observed_version") or "")
        if version and entry_version:
            if version.casefold() == entry_version.casefold():
                score += 2
            else:
                warnings.append("version_mismatch")
        if entry.get("observed_head") and entry.get("observed_head") != control.current_head(repo):
            warnings.append("project_head_changed")
        if score > 0:
            matches.append((score, entry, warnings))
    matches.sort(key=lambda item: (item[0], str(item[1].get("updated_at") or "")), reverse=True)
    selected = matches[: max(1, min(limit, 20))]
    return {
        "status": "match" if selected else "miss",
        "memory_revision": int(document.get("memory_revision", 0)),
        "memory_digest": memory_digest(control, document),
        "query_digest": query_digest(control, query_values),
        "count": len(selected),
        "cases": [
            incident_case_compact(control, entry, score=score, warnings=warnings)
            for (score, entry, warnings) in selected
        ],
    }


def promote_incident_case(
    control, repo: pathlib.Path, *, expected_revision: int, entry: dict[str, Any]
) -> tuple[str, int]:
    path = control.registry_path(repo)
    document = control.load(path)
    loaded_revision = int(document.get("memory_revision", 0))
    if loaded_revision != expected_revision:
        raise ValueError(
            f"project memory revision conflict: expected {loaded_revision}, received {expected_revision}"
        )
    case_id = control.identifier(str(entry.get("id") or ""))
    (index, existing) = control.find_entry(document, case_id)
    if existing is not None:
        if existing.get("kind") == "incident_case" and existing.get(
            "source_diagnostic_digest"
        ) == entry.get("source_diagnostic_digest"):
            return ("already_promoted", loaded_revision)
        raise ValueError(f"project memory entry already exists: {case_id}")
    normalized = {
        "id": case_id,
        "kind": "incident_case",
        "case_type": control.safe("incident case type", str(entry.get("case_type") or "")),
        "title": control.safe("incident case title", str(entry.get("title") or "")),
        "keywords": control.safe_list("incident case keyword", entry.get("keywords", [])),
        "symptom_signals": control.safe_list(
            "incident case symptom", entry.get("symptom_signals", [])
        ),
        "scope": control.safe_list("incident case scope", entry.get("scope", []), required=False),
        "component_refs": control.safe_list(
            "incident case component", entry.get("component_refs", []), required=False
        ),
        "environment": control.safe_list(
            "incident case environment", entry.get("environment", []), required=False
        ),
        "observed_version": control.optional_safe(
            "incident case observed version", entry.get("observed_version")
        ),
        "root_cause": control.safe("incident case root cause", str(entry.get("root_cause") or "")),
        "cause_class": control.safe(
            "incident case cause class", str(entry.get("cause_class") or "")
        ),
        "distinguishing_signals": control.safe_list(
            "incident case distinguishing signal",
            entry.get("distinguishing_signals", []),
            required=False,
        ),
        "resolution_summary": control.safe(
            "incident case resolution", str(entry.get("resolution_summary") or "")
        ),
        "protective_tests": control.safe_list(
            "incident case protective test", entry.get("protective_tests", []), required=False
        ),
        "lesson": control.safe("incident case lesson", str(entry.get("lesson") or "")),
        "evidence_refs": control.safe_list(
            "incident case evidence", entry.get("evidence_refs", [])
        ),
        "source_task_id": control.safe(
            "incident case source task", str(entry.get("source_task_id") or "")
        ),
        "source_diagnostic_digest": control.safe(
            "incident case source diagnostic digest",
            str(entry.get("source_diagnostic_digest") or ""),
        ),
        "confirmation_source_digest": control.safe(
            "incident case confirmation digest", str(entry.get("confirmation_source_digest") or "")
        ),
        "observed_head": control.current_head(repo),
        "review_policy": entry.get("review_policy", "on_mismatch"),
        "status": "confirmed",
        "created_at": control.now(),
        "updated_at": control.now(),
        "revisions": [],
    }
    document["entries"].append(normalized)
    document["updated_at"] = normalized["updated_at"]
    control.ensure_storage_root(repo)
    revision = control.write_registry(repo, document, expected_revision=expected_revision)
    return ("case_promoted", revision)
