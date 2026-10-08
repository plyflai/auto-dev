"""Registry list, show, verify, and review queries."""

from __future__ import annotations

from auto_dev_internal.memory.store import *
from auto_dev_internal.memory.entries import *

def filter_entries(document: dict[str, Any], kind: str | None, scope: str | None) -> list[dict[str, Any]]:
    normalized_kind = normalize_kind(kind) if kind else None
    entries = [
        entry for entry in document["entries"]
        if normalized_kind is None or entry.get("kind") == normalized_kind
    ]
    return [entry for entry in entries if scope_matches(entry.get("scope", []), scope)]


def list_entries(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo_root)
    document = load(registry_path(repo))
    entries = filter_entries(document, args.kind, args.scope)
    payload = {
        "path": ".auto-dev/project-memory.json",
        "schema_version": document["schema_version"],
        "count": len(entries),
        "entries": [compact(entry) if args.compact else entry for entry in entries],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def show(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo_root)
    document = load(registry_path(repo))
    entry_id = identifier(args.entry_id)
    _, entry = find_entry(document, entry_id)
    if entry is None:
        raise ValueError(f"dependency registry entry not found: {entry_id}")
    payload = {"entry": entry}
    if args.attempts:
        payload["attempts"] = [
            attempt for attempt in document["attempts"] if attempt.get("dependency_id") == entry_id
        ]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def verify(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo_root)
    document = load(registry_path(repo))
    selected = filter_entries(document, args.kind, None)
    if args.entry_id:
        expected = identifier(args.entry_id)
        selected = [entry for entry in selected if entry.get("id") == expected]
    head = current_head(repo)
    current = datetime.now().astimezone()
    results = []
    for entry in selected:
        if entry.get("kind") == "dependency":
            required = ["name", "purpose", "capabilities", "source", "version", "status", "role", "evidence", "scope"]
            if entry.get("status") != "known-bad":
                required.extend(["commands", "success_criteria"])
        elif entry.get("kind") == "gotcha":
            required = ["symptom", "observed_behavior", "impact", "evidence", "confidence"]
        else:
            required = [
                "case_type", "title", "keywords", "symptom_signals", "root_cause", "cause_class",
                "resolution_summary", "lesson", "evidence_refs", "source_task_id", "status",
            ]
        missing = [field for field in required if not entry.get(field)]
        reasons = review_reasons(entry, current) if entry.get("kind") == "dependency" else []
        head_changed = bool(entry.get("observed_head") and head and entry.get("observed_head") != head)
        status = "incomplete" if missing else "needs-recheck" if reasons else "current"
        results.append({
            "id": entry.get("id"),
            "kind": entry.get("kind"),
            "status": status,
            "missing": missing,
            "reasons": reasons,
            "project_head_changed": head_changed,
            "observed_head": entry.get("observed_head"),
            "current_head": head,
        })
    print(json.dumps({"count": len(results), "results": results}, ensure_ascii=False, indent=2))
    return 1 if any(item["status"] == "incomplete" or (args.strict and item["status"] == "needs-recheck") for item in results) else 0


def review(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo_root)
    document = load(registry_path(repo))
    current = datetime.now().astimezone()
    entries = [
        compact(entry, review=reasons)
        for entry in document["entries"]
        if entry.get("kind") == "dependency"
        and (not args.capability or capability_matches(entry, args.capability))
        and (reasons := review_reasons(entry, current))
    ]
    print(json.dumps({
        "count": len(entries),
        "entries": entries,
        "next_action": "Inspect upstream only for listed dependencies; do not switch versions without a verified attempt.",
    }, ensure_ascii=False, indent=2))
    return 0
