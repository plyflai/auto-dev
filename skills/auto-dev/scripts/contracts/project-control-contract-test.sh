#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLI="$SCRIPT_ROOT/auto_dev.py"
REPO_DIR="$(mktemp -d)"
trap 'rm -rf "$REPO_DIR"' EXIT

fail() {
  echo "project-control-contract-test: FAIL: $*" >&2
  exit 1
}

NO_GIT_DIR="$(mktemp -d)"
trap 'rm -rf "$REPO_DIR" "$NO_GIT_DIR"' EXIT
python3 "$CLI" project inspect --repo-root "$NO_GIT_DIR" | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["status"] == "git_setup_recommended"
assert value["git"] is False
'
[[ ! -e "$NO_GIT_DIR/.auto-dev" ]] || fail "project inspect created control state"
python3 "$CLI" project init --repo-root "$NO_GIT_DIR" --git --initial-branch main \
  --confirmation-source "contract test" >/dev/null
git -C "$NO_GIT_DIR" config user.name "Auto Dev Project Contract"
git -C "$NO_GIT_DIR" config user.email "auto-dev@example.com"
printf 'fixture\n' >"$NO_GIT_DIR/README.md"
git -C "$NO_GIT_DIR" add README.md
git -C "$NO_GIT_DIR" commit -qm init
git -C "$NO_GIT_DIR" checkout -qb feature-a

python3 "$CLI" start --repo-root "$NO_GIT_DIR" --tier direct --task "Task A" \
  --requirement-receipt REQ-A --confirmation-source "contract test" \
  --acceptance "A works" --scope README.md --validation "smoke" >/dev/null
python3 "$CLI" status --repo-root "$NO_GIT_DIR" --compact | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["status"] == "active"
assert value["current_state"]["branch"] == "feature-a"
assert value["context_key"] == "feature-a"
'

git -C "$NO_GIT_DIR" checkout -qb feature-b
python3 "$CLI" status --repo-root "$NO_GIT_DIR" --compact | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["status"] == "idle"
assert value["current_state"]["branch"] == "feature-b"
'
python3 "$CLI" start --repo-root "$NO_GIT_DIR" --tier direct --task "Task B" \
  --requirement-receipt REQ-B --confirmation-source "contract test" \
  --acceptance "B works" --scope README.md --validation "smoke" >/dev/null

git -C "$NO_GIT_DIR" checkout feature-a >/dev/null
read -r TASK_A STATE_A < <(python3 "$CLI" status --repo-root "$NO_GIT_DIR" --compact | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["status"] == "active"
print(value["id"], value["state_revision"])
')
python3 "$CLI" task pause --repo-root "$NO_GIT_DIR" --task-id "$TASK_A" \
  --state-revision "$STATE_A" --reason "switching context" >/dev/null
python3 "$CLI" status --repo-root "$NO_GIT_DIR" --compact | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["status"] == "selection_required"
assert len(value["task_candidates"]) == 1
'
if python3 "$CLI" start --repo-root "$NO_GIT_DIR" --tier direct --task "Task A replacement" \
  --requirement-receipt REQ-A2 --confirmation-source "contract test" \
  --acceptance "replacement works" --scope README.md --validation "smoke" >/dev/null 2>&1; then
  fail "paused task allowed a second current task on the same branch"
fi
read -r PROJECT_REV TASK_ID < <(python3 "$CLI" task list --repo-root "$NO_GIT_DIR" | python3 -c '
import json, sys
value = json.load(sys.stdin)
print(value["project_revision"], value["tasks"][0]["id"])
')
python3 "$CLI" task select --repo-root "$NO_GIT_DIR" --task-id "$TASK_ID" \
  --project-revision "$PROJECT_REV" --confirmation-source "contract test" >/dev/null
python3 "$CLI" status --repo-root "$NO_GIT_DIR" --compact | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["status"] == "active"
assert value["id"]
'

python3 "$CLI" task list --repo-root "$NO_GIT_DIR" --all | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert len(value["tasks"]) == 2
assert {item["branch"] for item in value["tasks"]} == {"feature-a", "feature-b"}
'

echo "project-control-contract-test: PASS"
