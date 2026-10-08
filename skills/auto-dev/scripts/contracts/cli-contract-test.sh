#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLI="$SCRIPT_ROOT/auto_dev.py"
REPO_DIR="$(mktemp -d)"
BEFORE_EXCLUDE="$(mktemp)"
trap 'rm -rf "$REPO_DIR" "$BEFORE_EXCLUDE"' EXIT

fail() {
  echo "cli-contract-test: FAIL: $*" >&2
  exit 1
}

git -C "$REPO_DIR" init -q
git -C "$REPO_DIR" config user.name "Auto Dev CLI Contract"
git -C "$REPO_DIR" config user.email "auto-dev@example.com"
printf 'fixture\n' >"$REPO_DIR/README.md"
git -C "$REPO_DIR" add README.md
git -C "$REPO_DIR" commit -qm "init"

EXCLUDE_PATH="$REPO_DIR/.git/info/exclude"
cp "$EXCLUDE_PATH" "$BEFORE_EXCLUDE"

python3 "$CLI" --help | grep -q 'Stable CLI front door' || fail "top-level help is missing"
CHECKPOINT_HELP="$(python3 "$CLI" help checkpoint)"
[[ "$CHECKPOINT_HELP" == *"usage: auto_dev.py checkpoint"* ]] || fail "checkpoint help exposed a compatibility entrypoint"
[[ "$CHECKPOINT_HELP" == *"--plan-revision"* ]] || fail "checkpoint help is unreachable"
WORKSPACE_HELP="$(python3 "$CLI" help workspace)"
[[ "$WORKSPACE_HELP" == *"{checkpoint,rollback}"* ]] || fail "workspace namespace is unreachable"
PROOF_HELP="$(python3 "$CLI" help proof)"
[[ "$PROOF_HELP" == *"usage: auto_dev.py proof"* ]] || fail "proof help exposed a compatibility entrypoint"
[[ "$PROOF_HELP" == *"--proof-id"* ]] || fail "proof command is unreachable"
[[ "$PROOF_HELP" == *"--revalidate"* ]] || fail "governed proof revalidation is unreachable"
IMPACT_HELP="$(python3 "$CLI" help impact)"
[[ "$IMPACT_HELP" == *"{inspect,record}"* ]] || fail "impact namespace is unreachable"
DEBUG_HELP="$(python3 "$CLI" help debug)"
[[ "$DEBUG_HELP" == *"{inspect,begin,case-search,reproduction,hypothesis,observe,resolve,recovery}"* ]] || fail "debug namespace is unreachable"
MEMORY_HELP="$(python3 "$CLI" help memory)"
[[ "$MEMORY_HELP" == *"{case}"* ]] || fail "memory namespace is unreachable"
DEPS_HELP="$(python3 "$CLI" deps --help)"
[[ "$DEPS_HELP" == *"usage: auto_dev.py deps"* ]] || fail "dependency help exposed a compatibility entrypoint"
[[ "$DEPS_HELP" == *"resolve"* ]] || fail "dependency namespace help is unreachable"
[[ "$DEPS_HELP" == *"gate"* ]] || fail "dependency gate is unreachable"
PROGRESS_HELP="$(python3 "$CLI" progress --help)"
[[ "$PROGRESS_HELP" == *"usage: auto_dev.py progress"* ]] || fail "progress help exposed a compatibility entrypoint"
[[ "$PROGRESS_HELP" == *"--port"* ]] || fail "progress help is unreachable"
PROJECT_HELP="$(python3 "$CLI" help project)"
[[ "$PROJECT_HELP" == *"{inspect,init,migrate}"* ]] || fail "project namespace is unreachable"
TASK_HELP="$(python3 "$CLI" help task)"
[[ "$TASK_HELP" == *"{list,select,pause,amend-scope,review,resume,attribute}"* ]] || fail "task namespace is unreachable"
INTAKE_HELP="$(python3 "$CLI" help intake)"
[[ "$INTAKE_HELP" == *"{turn,status,assess,resolve,confirm,reopen,show}"* ]] || fail "intake namespace is unreachable"
OUTCOME_HELP="$(python3 "$CLI" help outcome)"
[[ "$OUTCOME_HELP" == *"{list,show,add,set,link,move}"* ]] || fail "outcome namespace is unreachable"
FIX_HELP="$(python3 "$CLI" help fix)"
[[ "$FIX_HELP" == *"{inspect,apply}"* ]] || fail "fix namespace is unreachable"
LEGACY_UPGRADE_HELP="$(python3 "$CLI" help legacy-upgrade)"
[[ "$LEGACY_UPGRADE_HELP" == *"{inspect,apply}"* ]] || fail "legacy upgrade namespace is unreachable"
SNAPSHOT_HELP="$(python3 "$CLI" help snapshot)"
[[ "$SNAPSHOT_HELP" == *"{prune}"* ]] || fail "snapshot namespace is unreachable"
EVIDENCE_HELP="$(python3 "$CLI" help evidence)"
[[ "$EVIDENCE_HELP" == *"{link}"* ]] || fail "evidence namespace is unreachable"
EVIDENCE_LINK_HELP="$(python3 "$CLI" evidence link --help)"
[[ "$EVIDENCE_LINK_HELP" == *"--action-id"* ]] || fail "evidence link command is unreachable"
MILESTONE_HELP="$(python3 "$CLI" milestone --help)"
[[ "$MILESTONE_HELP" == *"{frontier,compile,execution,handoff,integration,review,worker}"* ]] || fail "milestone handoff namespace is unreachable"
WORKER_HELP="$(python3 "$CLI" milestone worker --help)"
[[ "$WORKER_HELP" == *"{prepare,bind,inspect,capture,apply,finalize,cleanup}"* ]] || fail "worker bind command is unreachable"
HANDOFF_HELP="$(python3 "$CLI" milestone handoff --help)"
[[ "$HANDOFF_HELP" == *"{take}"* ]] || fail "milestone handoff take is unreachable"
python3 "$CLI" version | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["cli_schema_version"] == 17
assert value["state_schema_version"] >= 14
assert value["project_schema_version"] >= 2
assert value["control_plane_upgrade_version"] >= 2
'

python3 "$CLI" bootstrap inspect --repo-root "$REPO_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["classification"] == "no_control"
'
python3 "$CLI" fix inspect --repo-root "$REPO_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["status"] == "unavailable"
assert value["reason"] == "no_auto_dev_control"
'
python3 "$CLI" legacy-upgrade inspect --repo-root "$REPO_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["status"] == "unavailable"
assert value["changes"] == []
'
python3 "$CLI" snapshot prune --repo-root "$REPO_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["status"] == "dry_run"
assert value["deletion_performed"] is False
'
python3 "$CLI" workspace checkpoint list --repo-root "$REPO_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value == {"status": "ready", "checkpoints": []}
'
python3 "$CLI" deps list --repo-root "$REPO_DIR" --compact | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["count"] == 0
'
python3 "$CLI" memory case search --repo-root "$REPO_DIR" --symptom absent | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["status"] == "miss"
assert value["memory_revision"] == 0
'
python3 "$CLI" deps review --repo-root "$REPO_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["count"] == 0
'
python3 "$CLI" deps verify --repo-root "$REPO_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value == {"count": 0, "results": []}
'
python3 "$CLI" deps resolve --repo-root "$REPO_DIR" --capability absent | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["status"] == "miss"
assert value["lease"] is None
'
set +e
GATE_OUTPUT="$(python3 "$CLI" deps gate --repo-root "$REPO_DIR" --capability absent --argv-json '["tool"]')"
GATE_STATUS=$?
set -e
[[ "$GATE_STATUS" -eq 3 ]] || fail "deps gate without a lease did not return blocked status"
printf '%s' "$GATE_OUTPUT" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["status"] == "preflight-required"
assert value["reason"] == "lease_missing"
'
set +e
python3 "$CLI" deps show absent --repo-root "$REPO_DIR" >/dev/null 2>&1
DEPS_SHOW_STATUS=$?
set -e
[[ "$DEPS_SHOW_STATUS" -ne 0 ]] || fail "deps show unexpectedly found an absent entry"
set +e
python3 "$CLI" deps attempt --repo-root "$REPO_DIR" --dependency-id absent \
  --result failed --classification environment --summary absent --evidence fixture >/dev/null 2>&1
DEPS_ATTEMPT_STATUS=$?
set -e
[[ "$DEPS_ATTEMPT_STATUS" -ne 0 ]] || fail "deps attempt unexpectedly accepted an absent dependency"

(
  cd /
  python3 "$CLI" status --repo-root "$REPO_DIR" --compact
) | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value == {"status": "idle", "bootstrap_status": "needs_plan_discovery"}
'

[[ ! -e "$REPO_DIR/.auto-dev" ]] || fail "read-only commands created .auto-dev"
cmp -s "$BEFORE_EXCLUDE" "$EXCLUDE_PATH" || fail "read-only commands changed git info/exclude"

set +e
RESUME_OUTPUT="$(python3 "$CLI" resume --repo-root "$REPO_DIR" 2>/dev/null)"
RESUME_STATUS=$?
set -e
[[ "$RESUME_STATUS" -eq 2 ]] || fail "resume without control state did not return strict status 2"
printf '%s' "$RESUME_OUTPUT" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["status"] == "idle"
'
[[ ! -e "$REPO_DIR/.auto-dev" ]] || fail "read-only resume created .auto-dev"
cmp -s "$BEFORE_EXCLUDE" "$EXCLUDE_PATH" || fail "read-only resume changed git info/exclude"

set +e
CHECKPOINT_ERROR="$(python3 "$CLI" checkpoint --repo-root "$REPO_DIR" --summary missing-revisions 2>&1 >/dev/null)"
CHECKPOINT_STATUS=$?
set -e
[[ "$CHECKPOINT_STATUS" -eq 2 ]] || fail "checkpoint accepted missing revision guards"
[[ "$CHECKPOINT_ERROR" == *"--plan-revision"* ]] || fail "checkpoint error omitted plan revision requirement"
[[ "$CHECKPOINT_ERROR" == *"--state-revision"* ]] || fail "checkpoint error omitted state revision requirement"

set +e
python3 "$CLI" unknown-command >/dev/null 2>&1
UNKNOWN_STATUS=$?
set -e
[[ "$UNKNOWN_STATUS" -eq 2 ]] || fail "unknown front-door command did not return 2"

echo "cli-contract-test: PASS"
