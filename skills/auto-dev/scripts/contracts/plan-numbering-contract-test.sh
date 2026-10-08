#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="$(mktemp -d)"
PLAN_A="$(mktemp)"
PLAN_B="$(mktemp)"
cleanup() {
  rm -rf "$REPO_DIR" "$PLAN_A" "$PLAN_B"
}
trap cleanup EXIT

git -C "$REPO_DIR" init -q
git -C "$REPO_DIR" config user.name "Auto Dev Numbering Selftest"
git -C "$REPO_DIR" config user.email "auto-dev@example.com"
printf 'fixture\n' >"$REPO_DIR/README.md"
git -C "$REPO_DIR" add README.md
git -C "$REPO_DIR" commit -qm "init"
git -C "$REPO_DIR" checkout -qb numbering-test

python3 "$SCRIPT_ROOT/auto_dev.py" start \
  --repo-root "$REPO_DIR" --tier direct --task "numbering fixture" \
  --requirement-receipt REQ-NUMBERING --confirmation-source "selftest" \
  --acceptance "numbered milestones" --scope README.md --validation "CLI contract" >/dev/null

python3 - "$PLAN_A" <<'PY'
import json
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text(json.dumps({
    "goal": {
        "statement": "numbering fixture",
        "acceptance": ["numbered milestones"],
        "source": "selftest",
    },
    "nodes": [
        {"id": "m9", "title": "M9: original milestone", "status": "done", "outcome": {"kind": "decision", "primary": "Original milestone is recorded", "proofs": [{"id": "m9-proof", "description": "Read original milestone"}]}, "historical_completion": {"summary": "Original milestone predates the fixture", "evidence": ["numbering fixture baseline"], "confirmation_source": "selftest fixture"}},
        {"id": "m9-child", "title": "M9: original child", "status": "done", "parent_id": "m9", "outcome": {"kind": "decision", "primary": "Original child is recorded", "proofs": [{"id": "m9-child-proof", "description": "Read original child"}]}, "historical_completion": {"summary": "Original child predates the fixture", "evidence": ["numbering fixture baseline"], "confirmation_source": "selftest fixture"}},
        {"id": "insert-a", "title": "M9: inserted root A", "status": "active", "depends_on": ["m9"], "outcome": {"kind": "behavior_change", "primary": "Inserted root A is complete", "proofs": [{"id": "insert-a-proof", "description": "Verify root A"}]}},
        {"id": "insert-b", "title": "M9: inserted root B", "status": "planned", "depends_on": ["insert-a"], "outcome": {"kind": "behavior_change", "primary": "Inserted root B is complete", "proofs": [{"id": "insert-b-proof", "description": "Verify root B"}]}},
        {"id": "m10", "title": "M10: later milestone", "status": "planned", "depends_on": ["insert-b"], "outcome": {"kind": "behavior_change", "primary": "Later milestone is complete", "proofs": [{"id": "m10-proof", "description": "Verify later milestone"}]}},
    ],
    "current_node": "insert-a",
    "next_action": "complete inserted root A",
}), encoding="utf-8")
PY

python3 "$SCRIPT_ROOT/auto_dev.py" plan \
  --repo-root "$REPO_DIR" --base-revision 0 --reason "normalize inserted milestones" \
  --plan-file "$PLAN_A" >/dev/null

python3 - "$REPO_DIR/.auto-dev/active.json" "$PLAN_B" <<'PY'
import json
import pathlib
import sys

active_path, plan_path = map(pathlib.Path, sys.argv[1:])
receipt = json.loads(active_path.read_text(encoding="utf-8"))
nodes = receipt["continuity"]["plan"]["nodes"]
nodes.insert(0, {
    "id": "before-m9",
    "title": "M9: rejected terminal renumber",
    "status": "planned",
    "outcome": {"kind": "decision", "primary": "Rejected renumber is recorded", "proofs": [{"id": "before-m9-proof", "description": "Review rejected renumber"}]},
})
pathlib.Path(plan_path).write_text(json.dumps({
    "nodes": nodes,
    "current_node": receipt["continuity"]["current_node"],
    "next_action": receipt["continuity"]["next_action"],
}), encoding="utf-8")
PY

if python3 "$SCRIPT_ROOT/auto_dev.py" plan \
  --repo-root "$REPO_DIR" --base-revision 1 --reason "reject terminal milestone renumber" \
  --plan-file "$PLAN_B" >/dev/null 2>&1; then
  printf 'plan accepted an unconfirmed terminal milestone renumber\n' >&2
  exit 1
fi

python3 - "$REPO_DIR/.auto-dev/active.json" "$PLAN_B" <<'PY'
import json
import pathlib
import sys

active_path, plan_path = map(pathlib.Path, sys.argv[1:])
receipt = json.loads(active_path.read_text(encoding="utf-8"))
nodes = receipt["continuity"]["plan"]["nodes"]
assert receipt["schema_version"] == 15
assert receipt["continuity"]["schema_version"] == 8
assert {node["id"]: node["display_code"] for node in nodes} == {
    "m9": "M9",
    "m9-child": "M9.1",
    "insert-a": "M10",
    "insert-b": "M11",
    "m10": "M12",
}
assert {node["id"]: node["title"] for node in nodes} == {
    "m9": "M9: original milestone",
    "m9-child": "M9.1: original child",
    "insert-a": "M10: inserted root A",
    "insert-b": "M11: inserted root B",
    "m10": "M12: later milestone",
}
assert receipt["events"][-1]["numbering_changes"] == [
    {"id": "m9-child", "from": "M9", "to": "M9.1"},
    {"id": "insert-a", "from": "M9", "to": "M10"},
    {"id": "insert-b", "from": "M9", "to": "M11"},
    {"id": "m10", "from": "M10", "to": "M12"},
]

before = {
    node["id"]: {key: node[key] for key in ("id", "status", "parent_id", "depends_on", "acceptance")}
    for node in nodes
}
index = next(index for index, node in enumerate(nodes) if node["id"] == "m10")
nodes.insert(index, {
    "id": "insert-c",
    "title": "M9: inserted root C",
    "status": "planned",
    "depends_on": ["insert-b"],
    "acceptance": ["inserted root C is preserved"],
    "outcome": {"kind": "behavior_change", "primary": "Inserted root C is complete", "proofs": [{"id": "insert-c-proof", "description": "Verify root C"}]},
})
pathlib.Path(plan_path).write_text(json.dumps({
    "nodes": nodes,
    "current_node": receipt["continuity"]["current_node"],
    "next_action": receipt["continuity"]["next_action"],
    "before": before,
}), encoding="utf-8")
PY

python3 "$SCRIPT_ROOT/auto_dev.py" plan \
  --repo-root "$REPO_DIR" --base-revision 1 --reason "insert another root milestone" \
  --plan-file "$PLAN_B" >/dev/null

python3 - "$REPO_DIR/.auto-dev/active.json" "$PLAN_B" <<'PY'
import json
import pathlib
import sys

active_path, plan_path = map(pathlib.Path, sys.argv[1:])
receipt = json.loads(active_path.read_text(encoding="utf-8"))
plan_input = json.loads(plan_path.read_text(encoding="utf-8"))
nodes = receipt["continuity"]["plan"]["nodes"]
assert receipt["continuity"]["plan"]["revision"] == 2
assert {node["id"]: node["display_code"] for node in nodes} == {
    "m9": "M9",
    "m9-child": "M9.1",
    "insert-a": "M10",
    "insert-b": "M11",
    "insert-c": "M12",
    "m10": "M13",
}
assert {node["id"]: node["title"] for node in nodes}["insert-c"] == "M12: inserted root C"
assert {node["id"]: node["title"] for node in nodes}["m10"] == "M13: later milestone"
assert receipt["events"][-1]["numbering_changes"] == [
    {"id": "insert-c", "from": "M9", "to": "M12"},
    {"id": "m10", "from": "M12", "to": "M13"},
]
after = {
    node["id"]: {key: node[key] for key in ("id", "status", "parent_id", "depends_on", "acceptance")}
    for node in nodes
    if node["id"] in plan_input["before"]
}
assert after == plan_input["before"]
print("plan-numbering-contract-test: PASS")
PY
