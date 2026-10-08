#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="$(mktemp -d)"
BOOTSTRAP_DIR="$(mktemp -d)"
BOOTSTRAP_PLAN_FILE="$(mktemp)"
trap 'rm -rf "$REPO_DIR" "$BOOTSTRAP_DIR" "$BOOTSTRAP_PLAN_FILE"' EXIT

fail() {
  echo "runctl-selftest: FAIL: $*" >&2
  exit 1
}

revisions() {
  python3 - "$1/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys

receipt = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(receipt["continuity"]["plan"]["revision"], receipt["state_revision"])
PY
}

git -C "$BOOTSTRAP_DIR" init -q
git -C "$BOOTSTRAP_DIR" config user.name "Auto Dev Bootstrap Selftest"
git -C "$BOOTSTRAP_DIR" config user.email "auto-dev@example.com"
printf 'bootstrap fixture\n' >"$BOOTSTRAP_DIR/README.md"
git -C "$BOOTSTRAP_DIR" add README.md
git -C "$BOOTSTRAP_DIR" commit -qm "init"
git -C "$BOOTSTRAP_DIR" checkout -qb bootstrap-test
cat >"$BOOTSTRAP_PLAN_FILE" <<'JSON'
{
  "goal": {"statement": "bootstrap control plane", "acceptance": ["continuity is ready"]},
  "nodes": [
    {"id": "survey", "title": "Survey project", "status": "active", "outcome": {"kind": "decision", "primary": "Control-plane state is classified", "proofs": [{"id": "survey-readback", "description": "Read bootstrap state"}]}},
    {"id": "verify", "title": "Verify control", "status": "planned", "depends_on": ["survey"], "outcome": {"kind": "behavior_change", "primary": "Control-plane verification is available", "proofs": [{"id": "control-smoke", "description": "Run bootstrap smoke"}]}}
  ],
  "current_node": "survey",
  "next_action": "run verification"
}
JSON

python3 "$SCRIPT_ROOT/runctl.py" bootstrap inspect --repo-root "$BOOTSTRAP_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["classification"] == "no_control"
assert value["bootstrap_status"] == "needs_plan_discovery"
assert value["survey_required"] is True
'

if python3 "$SCRIPT_ROOT/runctl.py" bootstrap apply --repo-root "$BOOTSTRAP_DIR" \
  --mode fresh --tier direct --plan-file "$BOOTSTRAP_PLAN_FILE" \
  --requirement-receipt REQ-BOOTSTRAP --goal-confirmation-source "" \
  --plan-confirmation-source "user confirmed plan" >/dev/null 2>&1; then
  fail "fresh bootstrap accepted an empty goal confirmation"
fi
[[ ! -f "$BOOTSTRAP_DIR/.auto-dev/active.json" ]] || fail "rejected fresh bootstrap created active state"

python3 "$SCRIPT_ROOT/runctl.py" bootstrap apply --repo-root "$BOOTSTRAP_DIR" \
  --mode fresh --tier direct --plan-file "$BOOTSTRAP_PLAN_FILE" \
  --requirement-receipt REQ-BOOTSTRAP --goal-confirmation-source "user confirmed goal" \
  --plan-confirmation-source "user confirmed plan" --scope README.md --validation "bootstrap smoke" >/dev/null
python3 "$SCRIPT_ROOT/runctl.py" bootstrap inspect --repo-root "$BOOTSTRAP_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["classification"] == "current_ready"
assert value["bootstrap_status"] == "ready"
'
python3 "$SCRIPT_ROOT/runctl.py" status --compact --repo-root "$BOOTSTRAP_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["bootstrap_status"] == "ready"
assert value["continuity"]["bootstrap"]["mode"] == "fresh"
'

python3 - "$BOOTSTRAP_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys

active = pathlib.Path(sys.argv[1])
active.write_text(json.dumps({
    "schema_version": 1,
    "id": "AUTO-DEV-LEGACY-BOOTSTRAP",
    "status": "active",
    "tier": "direct",
    "task": "legacy bootstrap fixture",
    "acceptance": ["legacy can be adopted"],
    "requirement_receipt": "REQ-LEGACY",
    "confirmation_source": "legacy",
    "planned_scope": ["README.md"],
    "validation_plan": ["bootstrap smoke"],
    "base_branch": "bootstrap-test",
    "base_head": None,
    "budgets": {},
    "capabilities": {"enabled": [], "skipped": {}, "evidence": {}},
}), encoding="utf-8")
PY
python3 "$SCRIPT_ROOT/runctl.py" bootstrap inspect --repo-root "$BOOTSTRAP_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["classification"] == "legacy_recoverable"
assert value["bootstrap_status"] == "needs_plan_confirmation"
'
if python3 "$SCRIPT_ROOT/runctl.py" bootstrap apply --repo-root "$BOOTSTRAP_DIR" \
  --mode adopt --expected-task-id WRONG --tier direct --plan-file "$BOOTSTRAP_PLAN_FILE" \
  --requirement-receipt REQ-ADOPT --goal-confirmation-source "user confirmed goal" \
  --plan-confirmation-source "user confirmed plan" >/dev/null 2>&1; then
  fail "adopt accepted a mismatched expected task id"
fi
python3 "$SCRIPT_ROOT/runctl.py" bootstrap apply --repo-root "$BOOTSTRAP_DIR" \
  --mode adopt --expected-task-id AUTO-DEV-LEGACY-BOOTSTRAP --tier direct \
  --plan-file "$BOOTSTRAP_PLAN_FILE" --requirement-receipt REQ-ADOPT \
  --goal-confirmation-source "user confirmed goal" --plan-confirmation-source "user confirmed plan" \
  --scope README.md --validation "bootstrap smoke" >/dev/null
python3 - "$BOOTSTRAP_DIR/.auto-dev/active.json" "$BOOTSTRAP_DIR/.auto-dev/runs/AUTO-DEV-LEGACY-BOOTSTRAP.json" <<'PY'
import json
import pathlib
import sys

active = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
old = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
assert active["continuity"]["bootstrap"]["mode"] == "adopt"
assert active["continuity"]["bootstrap"]["adopted_from_task_id"] == "AUTO-DEV-LEGACY-BOOTSTRAP"
assert old["status"] == "superseded"
assert old["superseded_by"] == active["id"]
PY

ADOPTED_TASK_ID="$(python3 - "$BOOTSTRAP_DIR/.auto-dev/active.json" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1]))["id"])
PY
)"
if python3 "$SCRIPT_ROOT/runctl.py" bootstrap apply --repo-root "$BOOTSTRAP_DIR" \
  --mode adopt --expected-task-id "$ADOPTED_TASK_ID" --tier direct --plan-file "$BOOTSTRAP_PLAN_FILE" \
  --requirement-receipt REQ-ADOPT-2 --goal-confirmation-source "user confirmed goal" \
  --plan-confirmation-source "user confirmed plan" >/dev/null 2>&1; then
  fail "adopt accepted a current plan"
fi
BEFORE_REPLACE="$(shasum -a 256 "$BOOTSTRAP_DIR/.auto-dev/active.json")"
if python3 "$SCRIPT_ROOT/runctl.py" bootstrap apply --repo-root "$BOOTSTRAP_DIR" \
  --mode replace --expected-task-id "$ADOPTED_TASK_ID" --tier direct \
  --plan-json '{"goal":{"statement":"invalid bootstrap","acceptance":["never applies"]},"nodes":[{"id":"bad","title":"Bad","status":"active","depends_on":["missing"]}],"current_node":"bad","next_action":"stop"}' \
  --requirement-receipt REQ-INVALID --goal-confirmation-source "user confirmed goal" \
  --plan-confirmation-source "user confirmed plan" >/dev/null 2>&1; then
  fail "replace accepted invalid dependency state"
fi
AFTER_REPLACE="$(shasum -a 256 "$BOOTSTRAP_DIR/.auto-dev/active.json")"
[[ "$BEFORE_REPLACE" == "$AFTER_REPLACE" ]] || fail "invalid bootstrap partially mutated active state"
python3 "$SCRIPT_ROOT/runctl.py" bootstrap apply --repo-root "$BOOTSTRAP_DIR" \
  --mode replace --expected-task-id "$ADOPTED_TASK_ID" --tier direct \
  --plan-file "$BOOTSTRAP_PLAN_FILE" --requirement-receipt REQ-REPLACE \
  --goal-confirmation-source "user confirmed goal" --plan-confirmation-source "user confirmed plan" \
  --scope README.md --validation "bootstrap smoke" >/dev/null

printf '{broken' >"$BOOTSTRAP_DIR/.auto-dev/active.json"
python3 "$SCRIPT_ROOT/runctl.py" bootstrap inspect --repo-root "$BOOTSTRAP_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["classification"] == "current_ready"
assert value["bootstrap_status"] == "ready"
assert value["active_projection_error"]
'
python3 - "$BOOTSTRAP_DIR/.auto-dev/active.bak" "$BOOTSTRAP_DIR/.auto-dev/active.json" <<'PY'
import pathlib
import sys

pathlib.Path(sys.argv[1]).unlink()
pathlib.Path(sys.argv[2]).write_text("{broken", encoding="utf-8")
PY
if python3 "$SCRIPT_ROOT/runctl.py" bootstrap apply --repo-root "$BOOTSTRAP_DIR" \
  --mode fresh --tier direct --plan-file "$BOOTSTRAP_PLAN_FILE" \
  --requirement-receipt REQ-CORRUPT --goal-confirmation-source "user confirmed goal" \
  --plan-confirmation-source "user confirmed plan" >/dev/null 2>&1; then
  fail "fresh bootstrap overwrote unrecoverable state"
fi
python3 "$SCRIPT_ROOT/runctl.py" bootstrap inspect --repo-root "$BOOTSTRAP_DIR" | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["classification"] == "current_ready"
assert value["active_projection_error"]
'

git -C "$REPO_DIR" init -q
git -C "$REPO_DIR" config user.name "Auto Dev Selftest"
git -C "$REPO_DIR" config user.email "auto-dev@example.com"
printf 'fixture\n' >"$REPO_DIR/README.md"
git -C "$REPO_DIR" add README.md
git -C "$REPO_DIR" commit -qm "init"

if python3 "$SCRIPT_ROOT/runctl.py" start \
  --repo-root "$REPO_DIR" --tier direct --task "protected" \
  --requirement-receipt REQ-1 --confirmation-source "user confirmed" \
  --acceptance "rejected on protected branch" >/dev/null 2>&1; then
  fail "Direct started on protected branch"
fi

if python3 "$SCRIPT_ROOT/runctl.py" start \
  --repo-root "$REPO_DIR" --tier team --task "protected team" \
  --requirement-receipt REQ-1 --confirmation-source "user confirmed" \
  --acceptance "rejected on protected branch" >/dev/null 2>&1; then
  fail "Team started on protected branch"
fi

git -C "$REPO_DIR" checkout -qb auto-dev-selftest

python3 "$SCRIPT_ROOT/runctl.py" start \
  --repo-root "$REPO_DIR" --tier direct --task "direct fixture" \
  --requirement-receipt REQ-2 --confirmation-source "user confirmed" \
  --acceptance "direct finishes" --scope README.md \
  --validation "target smoke" >/dev/null

[[ -f "$REPO_DIR/.auto-dev/active.json" ]] || fail "active receipt missing"
grep -qxF ".auto-dev/" "$REPO_DIR/.git/info/exclude" || fail "local exclude missing"

PLAN_FILE="$(mktemp)"
python3 - "$PLAN_FILE" <<'PY'
import json
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text(json.dumps({
    "goal": {
        "statement": "direct fixture continuity",
        "acceptance": ["direct finishes"],
        "source": "selftest",
    },
    "nodes": [
        {"id": "implementation", "title": "Implement fixture", "status": "active", "outcome": {"kind": "behavior_change", "primary": "Fixture implementation is complete", "proofs": [{"id": "implementation-smoke", "description": "Run fixture implementation smoke"}]}},
        {
            "id": "review",
            "title": "Review fixture",
            "status": "planned",
            "depends_on": ["implementation"],
            "outcome": {"kind": "decision", "primary": "Fixture review result is recorded", "proofs": [{"id": "review-smoke", "description": "Run fixture review smoke"}]},
        },
    ],
    "current_node": "implementation",
    "next_action": "Implement fixture",
}), encoding="utf-8")
PY

python3 "$SCRIPT_ROOT/runctl.py" plan \
  --repo-root "$REPO_DIR" --base-revision 0 --reason "continuity fixture" \
  --plan-file "$PLAN_FILE" --durability portable >/dev/null

python3 - "$REPO_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys

receipt = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert receipt["schema_version"] == 15
assert receipt["continuity"]["goal"]["revision"] == 1
assert receipt["continuity"]["plan"]["revision"] == 1
assert receipt["continuity"]["durability"]["level"] == "portable"
PY

read -r PLAN_REVISION STATE_REVISION < <(revisions "$REPO_DIR")

printf 'changed\n' >>"$REPO_DIR/README.md"

python3 "$SCRIPT_ROOT/runctl.py" proof \
  --repo-root "$REPO_DIR" --node implementation --proof-id implementation-smoke \
  --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --command "python3 -c 'pass'" >/dev/null

read -r PLAN_REVISION STATE_REVISION < <(revisions "$REPO_DIR")

if python3 "$SCRIPT_ROOT/runctl.py" checkpoint \
  --repo-root "$REPO_DIR" --node implementation --status active \
  --summary "missing revisions" >/dev/null 2>&1; then
  fail "checkpoint accepted missing revision guards"
fi

if python3 "$SCRIPT_ROOT/runctl.py" checkpoint \
  --repo-root "$REPO_DIR" --node review --status active \
  --summary "dependency not ready" --plan-revision "$PLAN_REVISION" \
  --state-revision "$STATE_REVISION" >/dev/null 2>&1; then
  fail "checkpoint activated a node with unfinished dependencies"
fi

if python3 "$SCRIPT_ROOT/runctl.py" checkpoint \
  --repo-root "$REPO_DIR" --node implementation --status active \
  --summary "stale state writer" --plan-revision "$PLAN_REVISION" \
  --state-revision 1 >/dev/null 2>&1; then
  fail "checkpoint accepted a stale state revision"
fi

python3 "$SCRIPT_ROOT/runctl.py" checkpoint \
  --repo-root "$REPO_DIR" --node implementation --status done \
  --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --summary "implementation checkpoint" --next-node review \
  --next-action "review fixture" --evidence "selftest evidence" >/dev/null

python3 "$SCRIPT_ROOT/runctl.py" status --repo-root "$REPO_DIR" | python3 -c '
import json
import sys

receipt = json.load(sys.stdin)
assert receipt["continuity_status"] == "ready"
assert receipt["continuity_summary"]["current_node"] == "review"
assert receipt["continuity"]["last_checkpoint"]["node_id"] == "implementation"
'

read -r PLAN_REVISION STATE_REVISION < <(revisions "$REPO_DIR")

if python3 "$SCRIPT_ROOT/runctl.py" checkpoint \
  --repo-root "$REPO_DIR" --node review --status active --summary "stale writer" \
  --plan-revision 0 --state-revision "$STATE_REVISION" >/dev/null 2>&1; then
  fail "checkpoint accepted a stale plan revision"
fi

if python3 "$SCRIPT_ROOT/runctl.py" event \
  --repo-root "$REPO_DIR" --type long_tool --summary "unbound long tool" \
  --action-id ACT-0 --phase started --expected "long tool result" >/dev/null 2>&1; then
  fail "event accepted an action phase without a node"
fi

python3 "$SCRIPT_ROOT/runctl.py" event \
  --repo-root "$REPO_DIR" --type long_tool --summary "long tool started" \
  --node review --action-id ACT-1 --phase started --expected "long tool result" >/dev/null

if python3 "$SCRIPT_ROOT/runctl.py" status --strict --repo-root "$REPO_DIR" >/dev/null 2>&1; then
  fail "strict status accepted a pending action"
fi

python3 "$SCRIPT_ROOT/runctl.py" event \
  --repo-root "$REPO_DIR" --type long_tool --summary "long tool completed" \
  --node review --action-id ACT-1 --phase result >/dev/null

python3 - "$REPO_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys

active_path = pathlib.Path(sys.argv[1])
receipt = json.loads(active_path.read_text(encoding="utf-8"))
receipt["events"].extend([
    {
        "type": "legacy_device_capture",
        "at": "2026-01-01T00:00:00+00:00",
        "summary": "legacy capture started without node attribution",
        "evidence": [],
        "action_id": "LEGACY-CAPTURE",
        "phase": "started",
    },
    {
        "type": "legacy_device_capture",
        "at": "2026-01-01T00:01:00+00:00",
        "summary": "legacy capture was temporally insufficient",
        "evidence": ["legacy-manifest.json"],
        "action_id": "LEGACY-CAPTURE",
        "phase": "result",
    },
])
task_path = active_path.parent / "tasks" / f"{receipt['id']}.json"
encoded = json.dumps(receipt)
active_path.write_text(encoded, encoding="utf-8")
task_path.write_text(encoded, encoding="utf-8")
PY

if python3 "$SCRIPT_ROOT/runctl.py" status --strict --repo-root "$REPO_DIR" >/dev/null 2>&1; then
  fail "strict status accepted unattributed action evidence"
fi

read -r PLAN_REVISION STATE_REVISION < <(revisions "$REPO_DIR")
python3 "$SCRIPT_ROOT/runctl.py" evidence link \
  --repo-root "$REPO_DIR" --node review --action-id LEGACY-CAPTURE \
  --classification partial --summary "legacy capture is partial supporting evidence" \
  --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" >/dev/null

python3 "$SCRIPT_ROOT/runctl.py" status --strict --repo-root "$REPO_DIR" | python3 -c '
import json
import sys

receipt = json.load(sys.stdin)
assert receipt["continuity_status"] == "ready"
assert receipt["unattributed_actions"] == []
assert receipt["continuity"]["evidence_links"][0]["action_id"] == "LEGACY-CAPTURE"
'

if python3 "$SCRIPT_ROOT/runctl.py" plan \
  --repo-root "$REPO_DIR" --base-revision 1 --reason "unconfirmed goal change" \
  --plan-json '{"goal":{"statement":"changed goal","acceptance":["changed"]},"nodes":[{"id":"implementation","title":"Implement fixture","status":"done"},{"id":"review","title":"Review fixture","status":"active","depends_on":["implementation"]}],"current_node":"review"}' \
  >/dev/null 2>&1; then
  fail "plan accepted an unconfirmed goal change"
fi

if python3 "$SCRIPT_ROOT/runctl.py" diagnostics \
  --repo-root "$REPO_DIR" --id checkout --component checkout --scope README.md \
  --layer "app logger" --storage "local server log" --retention "7 days" \
  --read "npm run logs -- --component checkout" --event checkout.failed \
  --field timestamp --field level --field component --field event --field outcome \
  --field correlation_id --correlation "request ID" --redaction "tokens are excluded" \
  --verify "failure path read back" >/dev/null 2>&1; then
  fail "runtime diagnostics accepted a missing required field"
fi

python3 "$SCRIPT_ROOT/runctl.py" diagnostics \
  --repo-root "$REPO_DIR" --id checkout --component checkout --scope README.md \
  --layer "app logger" --storage "local server log" --retention "7 days" \
  --read "npm run logs -- --component checkout" --event checkout.started --event checkout.failed \
  --field timestamp --field level --field component --field event --field outcome \
  --field correlation_id --field error --correlation "request ID" \
  --redaction "tokens are excluded" --verify "success and failure paths read back" >/dev/null

python3 "$SCRIPT_ROOT/runctl.py" diagnostics \
  --repo-root "$REPO_DIR" --id checkout --component checkout --scope README.md \
  --layer "app logger" --storage "local server log" --retention "14 days" \
  --read "npm run logs -- --component checkout --since 10m" \
  --event checkout.started --event checkout.failed \
  --field timestamp --field level --field component --field event --field outcome \
  --field correlation_id --field error --correlation "request ID" \
  --redaction "tokens are excluded" --verify "success and failure paths read back" \
  --limit "local logs are only retained for 14 days" >/dev/null

python3 - "$REPO_DIR/.auto-dev/runtime-diagnostics.json" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert manifest["schema_version"] == 1
assert len(manifest["entries"]) == 1
entry = manifest["entries"][0]
assert entry["id"] == "checkout"
assert entry["scope"] == ["README.md"]
assert entry["retention"] == "14 days"
assert entry["fields"] == [
    "timestamp", "level", "component", "event", "outcome", "correlation_id", "error"
]
assert entry["limitations"] == ["local logs are only retained for 14 days"]
PY

if python3 "$SCRIPT_ROOT/runctl.py" escalate \
  --repo-root "$REPO_DIR" --reason "public contract discovered" \
  --capability data-contract \
  --skip 'architecture=no architecture boundary' \
  --skip 'debug-observability=root cause is known' \
  --skip 'gui=no user-visible interface' \
  --skip 'release=no deployment' \
  --skip 'parallel-work=single workflow' \
  --skip 'compliance=no security boundary' >/dev/null 2>&1; then
  fail "Team escalation accepted an enabled capability without evidence"
fi

python3 "$SCRIPT_ROOT/runctl.py" escalate \
  --repo-root "$REPO_DIR" --reason "public contract discovered" \
  --capability data-contract \
  --capability-evidence 'data-contract=public schema boundary changed' \
  --skip 'architecture=no architecture boundary' \
  --skip 'debug-observability=root cause is known' \
  --skip 'gui=no user-visible interface' \
  --skip 'release=no deployment' \
  --skip 'parallel-work=single workflow' \
  --skip 'compliance=no security boundary' \
  --budget implementation_repair=2 >/dev/null

python3 - "$REPO_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys

receipt = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert receipt["schema_version"] == 15
assert receipt["tier"] == "team"
assert receipt["capabilities"]["enabled"] == ["data-contract"]
assert receipt["capabilities"]["evidence"]["data-contract"] == "public schema boundary changed"
assert receipt["budgets"]["implementation_repair"] == 2
assert receipt["budget_usage"]["implementation_repair"] == 0
assert any(event["type"] == "direct_to_team" for event in receipt["events"])
PY

python3 "$SCRIPT_ROOT/runctl.py" capabilities \
  --repo-root "$REPO_DIR" --enable data-contract --enable compliance \
  --capability-evidence 'data-contract=public schema boundary changed' \
  --capability-evidence 'compliance=authorization boundary discovered' \
  --skip 'architecture=no architecture boundary' \
  --skip 'debug-observability=root cause is known' \
  --skip 'gui=no user-visible interface' \
  --skip 'release=no deployment' \
  --skip 'parallel-work=single workflow' \
  --budget review_passes=2 >/dev/null

python3 "$SCRIPT_ROOT/runctl.py" event \
  --repo-root "$REPO_DIR" --type review_pass \
  --summary "risk boundary review completed" --consume review_passes=1 \
  --evidence "review receipt" >/dev/null

python3 - "$REPO_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys

receipt = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert receipt["budget_usage"]["review_passes"] == 1
assert receipt["exhausted_budgets"] == []
assert receipt["events"][-1]["type"] == "review_pass"
PY

if python3 "$SCRIPT_ROOT/runctl.py" finish \
  --repo-root "$REPO_DIR" --status passed --summary "should not pass" \
  --validation "target smoke passed" >/dev/null 2>&1; then
  fail "finish passed with an unfinished continuity node"
fi

read -r PLAN_REVISION STATE_REVISION < <(revisions "$REPO_DIR")

python3 "$SCRIPT_ROOT/runctl.py" proof \
  --repo-root "$REPO_DIR" --node review --proof-id review-smoke \
  --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --command "python3 -c 'pass'" >/dev/null

read -r PLAN_REVISION STATE_REVISION < <(revisions "$REPO_DIR")

python3 "$SCRIPT_ROOT/runctl.py" checkpoint \
  --repo-root "$REPO_DIR" --node review --status done \
  --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --summary "review checkpoint" --evidence "review passed" >/dev/null

if python3 "$SCRIPT_ROOT/runctl.py" finish \
  --repo-root "$REPO_DIR" --status passed --summary "team finished" \
  --file README.md --validation "target smoke passed" >/dev/null 2>&1; then
  fail "passed task skipped review_ready"
fi

read -r PLAN_REVISION STATE_REVISION < <(revisions "$REPO_DIR")
python3 "$SCRIPT_ROOT/runctl.py" task review \
  --repo-root "$REPO_DIR" --state-revision "$STATE_REVISION" \
  --summary "team result is ready for user review" --file README.md \
  --validation "target smoke passed" >/dev/null

python3 "$SCRIPT_ROOT/runctl.py" status --repo-root "$REPO_DIR" --compact | python3 -c '
import json
import sys

value = json.load(sys.stdin)
assert value["status"] == "review_ready"
assert value["continuity_status"] == "review_ready"
assert "review_ready" in value["strict_blockers"]
assert value["continuity"]["plan"]["nodes"][-1]["display_code"].startswith("M")
'
[[ -f "$REPO_DIR/.auto-dev/active.json" ]] || fail "review_ready lost selected task projection"

STATE_REVISION="$(python3 - "$REPO_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["state_revision"])
PY
)"
python3 "$SCRIPT_ROOT/runctl.py" task resume \
  --repo-root "$REPO_DIR" --state-revision "$STATE_REVISION" \
  --reason "user requested a related follow-up" \
  --confirmation-source "user follow-up" >/dev/null

STATE_REVISION="$(python3 - "$REPO_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["state_revision"])
PY
)"
python3 "$SCRIPT_ROOT/runctl.py" task review \
  --repo-root "$REPO_DIR" --state-revision "$STATE_REVISION" \
  --summary "related follow-up is also ready for review" --file README.md \
  --validation "target smoke passed after follow-up" >/dev/null

python3 "$SCRIPT_ROOT/runctl.py" finish \
  --repo-root "$REPO_DIR" --status passed --summary "user accepted team result" \
  --confirmation-source "user accepted review" >/dev/null

[[ ! -f "$REPO_DIR/.auto-dev/active.json" ]] || fail "finish left active receipt"
[[ -s "$REPO_DIR/.auto-dev/history.jsonl" ]] || fail "history missing"

if python3 "$SCRIPT_ROOT/runctl.py" start \
  --repo-root "$REPO_DIR" --tier team --task "team fixture" \
  --requirement-receipt REQ-3 --confirmation-source "user confirmed" \
  --acceptance "team rejects dirty worktree without scope" >/dev/null 2>&1; then
  fail "dirty Team run started without explicit scope"
fi

python3 "$SCRIPT_ROOT/runctl.py" start \
  --repo-root "$REPO_DIR" --tier team --task "team fixture" \
  --requirement-receipt REQ-3 --confirmation-source "user confirmed" \
  --acceptance "team blocks unknown packs" --scope README.md \
  --validation "target smoke" \
  --skip 'architecture=no architecture boundary' \
  --skip 'data-contract=no contract change' \
  --skip 'debug-observability=root cause is known' \
  --skip 'gui=no user-visible interface' \
  --skip 'release=no deployment' \
  --skip 'parallel-work=single workflow' \
  --skip 'compliance=no security boundary' >/dev/null

STATE_REVISION="$(python3 - "$REPO_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["state_revision"])
PY
)"
python3 "$SCRIPT_ROOT/runctl.py" task amend-scope \
  --repo-root "$REPO_DIR" --state-revision "$STATE_REVISION" --scope tests \
  --kind adjacent --reason "add adjacent coverage" >/dev/null

STATE_REVISION="$(python3 - "$REPO_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["state_revision"])
PY
)"
if python3 "$SCRIPT_ROOT/runctl.py" task amend-scope \
  --repo-root "$REPO_DIR" --state-revision "$STATE_REVISION" --scope public-api \
  --kind requirement-diff --reason "public boundary expanded" >/dev/null 2>&1; then
  fail "requirement-diff scope amendment accepted without confirmation"
fi
python3 "$SCRIPT_ROOT/runctl.py" task amend-scope \
  --repo-root "$REPO_DIR" --state-revision "$STATE_REVISION" --scope public-api \
  --kind requirement-diff --reason "public boundary expanded" \
  --confirmation-source "user confirmed Requirement Diff" >/dev/null
python3 - "$REPO_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys

receipt = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert receipt["planned_scope"] == ["README.md", "tests", "public-api"]
assert [item["kind"] for item in receipt["scope_amendments"]] == ["adjacent", "requirement-diff"]
assert receipt["scope_amendments"][1]["confirmation_source"] == "user confirmed Requirement Diff"
PY

if python3 "$SCRIPT_ROOT/runctl.py" capabilities \
  --repo-root "$REPO_DIR" --enable imaginary-pack >/dev/null 2>&1; then
  fail "unknown capability was accepted"
fi

python3 "$SCRIPT_ROOT/runctl.py" event \
  --repo-root "$REPO_DIR" --type repair_attempt \
  --summary "two repair attempts consumed" --consume implementation_repair=2 >/dev/null

if python3 "$SCRIPT_ROOT/runctl.py" event \
  --repo-root "$REPO_DIR" --type repair_attempt \
  --summary "should be rejected" --consume implementation_repair=1 >/dev/null 2>&1; then
  fail "event consumed an already exhausted budget"
fi

git -C "$REPO_DIR" checkout -qb auto-dev-selftest-drift
printf 'outside\n' >"$REPO_DIR/OUTSIDE.md"

python3 "$SCRIPT_ROOT/runctl.py" status --repo-root "$REPO_DIR" | python3 -c '
import json
import sys

receipt = json.load(sys.stdin)
assert receipt["status"] == "idle"
assert receipt["current_state"]["branch"] == "auto-dev-selftest-drift"
'

if python3 "$SCRIPT_ROOT/runctl.py" finish \
  --repo-root "$REPO_DIR" --status passed --summary "should not pass" \
  --validation "target smoke passed" >/dev/null 2>&1; then
  fail "run finished a task from the wrong branch"
fi

git -C "$REPO_DIR" checkout auto-dev-selftest >/dev/null
python3 "$SCRIPT_ROOT/runctl.py" finish \
  --repo-root "$REPO_DIR" --status budget_exhausted \
  --summary "fixture exhausted its repair budget" >/dev/null

LEGACY_BRANCH="$(git -C "$REPO_DIR" branch --show-current)"
python3 - "$REPO_DIR/.auto-dev/active.json" "$REPO_DIR" "$LEGACY_BRANCH" <<'PY'
import json
import pathlib
import sys

active = pathlib.Path(sys.argv[1])
repo = pathlib.Path(sys.argv[2])
branch = sys.argv[3]
active.write_text(json.dumps({
    "schema_version": 1,
    "id": "AUTO-DEV-LEGACY",
    "status": "active",
    "tier": "direct",
    "task": "legacy fixture",
    "planned_scope": ["README.md"],
    "base_branch": branch,
    "base_head": None,
    "budgets": {"implementation_repair": 2},
    "capabilities": {"enabled": [], "skipped": {}},
    "repo_root": str(repo),
}), encoding="utf-8")
PY

python3 "$SCRIPT_ROOT/runctl.py" status --repo-root "$REPO_DIR" | python3 -c '
import json
import sys

receipt = json.load(sys.stdin)
assert receipt["schema_version"] == 1
assert receipt["budget_usage"]["implementation_repair"] == 0
assert receipt["capabilities"]["evidence"] == {}
'

python3 "$SCRIPT_ROOT/runctl.py" migrate --repo-root "$REPO_DIR" >/dev/null
python3 - "$REPO_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys

receipt = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert receipt["schema_version"] == 15
assert receipt["events"][-1]["type"] == "schema_migrated"
PY

python3 "$SCRIPT_ROOT/runctl.py" abandon \
  --repo-root "$REPO_DIR" --reason "legacy receipt replaced" >/dev/null

[[ ! -f "$REPO_DIR/.auto-dev/active.json" ]] || fail "abandon left active receipt"
[[ -f "$REPO_DIR/.auto-dev/runs/AUTO-DEV-LEGACY.json" ]] || fail "legacy receipt was not archived"

SOURCE_DIR="$REPO_DIR/handoff-source"
TARGET_DIR="$REPO_DIR/handoff-target"
HANDOFF_FILE="$REPO_DIR/handoff.json"
for directory in "$SOURCE_DIR" "$TARGET_DIR"; do
  git -C "$REPO_DIR" init -q "$directory"
  git -C "$directory" config user.name "Auto Dev Handoff Selftest"
  git -C "$directory" config user.email "auto-dev@example.com"
  printf 'fixture\n' >"$directory/README.md"
  git -C "$directory" add README.md
  git -C "$directory" commit -qm "init"
  git -C "$directory" checkout -qb handoff-test
done

python3 "$SCRIPT_ROOT/runctl.py" start \
  --repo-root "$SOURCE_DIR" --tier direct --task "handoff fixture" \
  --requirement-receipt REQ-HANDOFF --confirmation-source "user confirmed" \
  --acceptance "handoff imports" --scope README.md --validation "handoff smoke" >/dev/null

python3 "$SCRIPT_ROOT/runctl.py" plan \
  --repo-root "$SOURCE_DIR" --base-revision 0 --reason "handoff plan" \
  --plan-json '{"goal":{"statement":"handoff fixture","acceptance":["handoff imports"],"source":"api_key=secret"},"nodes":[{"id":"handoff","title":"Handoff state","status":"active","outcome":{"kind":"behavior_change","primary":"Handoff state can be exported and restored","proofs":[{"id":"handoff-smoke","description":"Run handoff smoke"}]}}],"current_node":"handoff"}' >/dev/null

read -r PLAN_REVISION STATE_REVISION < <(revisions "$SOURCE_DIR")

python3 "$SCRIPT_ROOT/runctl.py" proof \
  --repo-root "$SOURCE_DIR" --node handoff --proof-id handoff-smoke \
  --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --command "python3 -c 'pass'" >/dev/null

read -r PLAN_REVISION STATE_REVISION < <(revisions "$SOURCE_DIR")

python3 "$SCRIPT_ROOT/runctl.py" checkpoint \
  --repo-root "$SOURCE_DIR" --node handoff --status done \
  --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --summary "handoff ready" --evidence "handoff evidence" >/dev/null

python3 "$SCRIPT_ROOT/dependency_manager.py" record dependency --repo-root "$SOURCE_DIR" \
  --id handoff-tool --name "Handoff Tool" --purpose "fixture capability" \
  --capability fixture-capability --source "https://example.invalid/tool" \
  --version "Python 3.10 + tool 1.0" --environment "Python 3.10" \
  --command "tool --smoke" --success "fixture passes" \
  --evidence "dependency smoke" --scope README.md --status known-good --role preferred >/dev/null
python3 "$SCRIPT_ROOT/dependency_manager.py" resolve --repo-root "$SOURCE_DIR" \
  --capability fixture-capability --scope README.md --environment "Python 3.10" \
  --write-lease >/dev/null

python3 - "$SOURCE_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
receipt = json.loads(path.read_text(encoding="utf-8"))
receipt["continuity"]["bootstrap"] = {
    "mode": "fresh",
    "status": "ready",
    "goal_confirmation_source": "selftest",
    "plan_confirmation_source": "selftest",
}
path.write_text(json.dumps(receipt), encoding="utf-8")
PY

python3 "$SCRIPT_ROOT/runctl.py" handoff export \
  --repo-root "$SOURCE_DIR" --out "$HANDOFF_FILE" >/dev/null

grep -q '\[REDACTED\]' "$HANDOFF_FILE" || fail "handoff packet did not redact sensitive text"
python3 - "$HANDOFF_FILE" <<'PY'
import json
import pathlib
import sys

packet = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert packet["packet_schema_version"] == 4, packet.get("packet_schema_version")
assert packet["dependency_registry"]["schema_version"] == 4, packet.get("dependency_registry")
assert packet["dependency_lease"]["schema_version"] == 2, packet.get("dependency_lease")
assert packet["dependency_lease"]["leases"][0]["dependency_id"] == "handoff-tool", packet.get("dependency_lease")
PY

python3 "$SCRIPT_ROOT/runctl.py" handoff import \
  --repo-root "$TARGET_DIR" --file "$HANDOFF_FILE" >/dev/null

python3 - "$TARGET_DIR/.auto-dev/project-memory.json" "$TARGET_DIR/.auto-dev/dependency-lease.json" <<'PY'
import json
import pathlib
import sys

registry = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
lease = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
assert registry["schema_version"] == 4
assert any(entry["id"] == "handoff-tool" for entry in registry["entries"])
assert lease["schema_version"] == 2
assert lease["leases"][0]["dependency_id"] == "handoff-tool"
PY

python3 "$SCRIPT_ROOT/runctl.py" status --compact --repo-root "$TARGET_DIR" | python3 -c '
import json
import sys

receipt = json.load(sys.stdin)
assert receipt["view"] == "compact"
assert receipt["continuity"]["plan"]["nodes"][0]["status"] == "done"
assert receipt["continuity"]["bootstrap"]["mode"] == "fresh"
assert "events" not in receipt
'

printf '{broken' >"$SOURCE_DIR/.auto-dev/active.json"
python3 "$SCRIPT_ROOT/runctl.py" status --compact --repo-root "$SOURCE_DIR" | python3 -c '
import json
import sys

receipt = json.load(sys.stdin)
assert receipt["continuity_status"] == "ready"
assert receipt["recovery_source"] is None
assert receipt["project_id"]
'
python3 "$SCRIPT_ROOT/runctl.py" recover --repo-root "$SOURCE_DIR" >/dev/null
python3 "$SCRIPT_ROOT/runctl.py" status --compact --repo-root "$SOURCE_DIR" | python3 -c '
import json
import sys

receipt = json.load(sys.stdin)
assert receipt["continuity_status"] == "ready"
'

echo "runctl-selftest: PASS"
