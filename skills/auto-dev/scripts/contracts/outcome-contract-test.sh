#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="$(mktemp -d)"
trap 'rm -rf "$REPO_DIR"' EXIT

fail() {
  echo "outcome-contract-test: FAIL: $*" >&2
  exit 1
}

revisions() {
  python3 - "$REPO_DIR/.auto-dev/active.json" <<'PY'
import json
import sys
receipt = json.load(open(sys.argv[1], encoding="utf-8"))
print(receipt["continuity"]["plan"]["revision"], receipt["state_revision"])
PY
}

git -C "$REPO_DIR" init -q
git -C "$REPO_DIR" config user.name "Auto Dev Outcome Selftest"
git -C "$REPO_DIR" config user.email "auto-dev@example.com"
printf 'fixture\n' >"$REPO_DIR/README.md"
git -C "$REPO_DIR" add README.md
git -C "$REPO_DIR" commit -qm init
git -C "$REPO_DIR" checkout -qb outcome-test

python3 "$SCRIPT_ROOT/auto_dev.py" start \
  --repo-root "$REPO_DIR" --tier direct --task "outcome fixture" \
  --requirement-receipt REQ-OUTCOME --confirmation-source selftest \
  --acceptance "completion requires proof" --scope README.md --validation "outcome contract" >/dev/null

if python3 "$SCRIPT_ROOT/auto_dev.py" plan --repo-root "$REPO_DIR" \
  --base-revision 0 --reason "reject performative plan" \
  --plan-json '{"goal":{"statement":"outcome fixture","acceptance":["completion requires proof"],"source":"selftest"},"nodes":[{"id":"report","title":"Write a report","status":"active"}],"current_node":"report","next_action":"write report"}' \
  >/dev/null 2>&1; then
  fail "new plan accepted a node without an outcome contract"
fi

if python3 "$SCRIPT_ROOT/auto_dev.py" plan --repo-root "$REPO_DIR" \
  --base-revision 0 --reason "reject unauthorized document" \
  --plan-json '{"goal":{"statement":"outcome fixture","acceptance":["completion requires proof"],"source":"selftest"},"nodes":[{"id":"report","title":"Write a report","status":"active","outcome":{"kind":"document","primary":"A report exists","proofs":[{"id":"report-proof","description":"Read report"}]}}],"current_node":"report","next_action":"write report"}' \
  >/dev/null 2>&1; then
  fail "document outcome passed without explicit authorization"
fi

python3 "$SCRIPT_ROOT/auto_dev.py" plan --repo-root "$REPO_DIR" \
  --base-revision 0 --reason "outcome contract fixture" \
  --plan-json '{"goal":{"statement":"outcome fixture","acceptance":["completion requires proof"],"source":"selftest"},"nodes":[{"id":"deliver","title":"Deliver behavior","status":"active","outcome":{"kind":"behavior_change","primary":"The target behavior is observable","proofs":[{"id":"target-smoke","description":"Run the target behavior smoke"}]}},{"id":"blocked","title":"Exercise honest blocking","status":"planned","depends_on":["deliver"],"outcome":{"kind":"defect_resolution","primary":"The external defect is resolved","proofs":[{"id":"external-smoke","description":"Run the unavailable external smoke"}]}}],"current_node":"deliver","next_action":"run the target smoke"}' >/dev/null

if python3 "$SCRIPT_ROOT/auto_dev.py" plan --repo-root "$REPO_DIR" \
  --base-revision 1 --reason "attempt to bypass proof" \
  --plan-json '{"nodes":[{"id":"deliver","title":"Deliver behavior","status":"done"},{"id":"blocked","title":"Exercise honest blocking","status":"active","depends_on":["deliver"]}],"current_node":"blocked","next_action":"skip proof"}' \
  >/dev/null 2>&1; then
  fail "plan changed an active node directly to done"
fi

read -r PLAN_REVISION STATE_REVISION < <(revisions)
if python3 "$SCRIPT_ROOT/auto_dev.py" checkpoint --repo-root "$REPO_DIR" \
  --node deliver --status done --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --summary "looks complete" >/dev/null 2>&1; then
  fail "done passed without a proof receipt"
fi

set +e
python3 "$SCRIPT_ROOT/auto_dev.py" proof --repo-root "$REPO_DIR" \
  --node deliver --proof-id target-smoke --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --command "python3 -c 'raise SystemExit(7)'" >/dev/null
FAILED_PROOF_STATUS=$?
set -e
[[ "$FAILED_PROOF_STATUS" -eq 1 ]] || fail "failed proof did not return exit 1"

read -r PLAN_REVISION STATE_REVISION < <(revisions)
if python3 "$SCRIPT_ROOT/auto_dev.py" checkpoint --repo-root "$REPO_DIR" \
  --node deliver --status done --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --summary "failed proof is not completion" >/dev/null 2>&1; then
  fail "done accepted a failed proof"
fi

python3 "$SCRIPT_ROOT/auto_dev.py" proof --repo-root "$REPO_DIR" \
  --node deliver --proof-id target-smoke --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --command "python3 -c 'pass'" >/dev/null
read -r PLAN_REVISION STATE_REVISION < <(revisions)
python3 "$SCRIPT_ROOT/auto_dev.py" checkpoint --repo-root "$REPO_DIR" \
  --node deliver --status done --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --summary "target behavior proved" --next-node blocked --next-action "check external dependency" >/dev/null

read -r PLAN_REVISION STATE_REVISION < <(revisions)
if python3 "$SCRIPT_ROOT/auto_dev.py" checkpoint --repo-root "$REPO_DIR" \
  --node blocked --status blocked --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --summary "cannot continue" >/dev/null 2>&1; then
  fail "blocked checkpoint passed without a gap and attempt evidence"
fi

python3 "$SCRIPT_ROOT/auto_dev.py" checkpoint --repo-root "$REPO_DIR" \
  --node blocked --status blocked --plan-revision "$PLAN_REVISION" --state-revision "$STATE_REVISION" \
  --summary "external service is unavailable" --evidence "connection attempt returned a deterministic refusal" \
  --gap-id external-service --gap-summary "External service must become reachable before verification" \
  --gap-owner external --next-action "retry the external smoke after service recovery" >/dev/null

python3 "$SCRIPT_ROOT/auto_dev.py" status --repo-root "$REPO_DIR" --compact | python3 -c '
import json
import sys
value = json.load(sys.stdin)
assert value["continuity_summary"]["current_node"] == "blocked"
assert value["continuity"]["last_checkpoint"]["status"] == "blocked"
assert any(gap["id"] == "external-service" and gap["status"] == "open" for gap in value["continuity"]["gaps"])
'

python3 "$SCRIPT_ROOT/auto_dev.py" finish --repo-root "$REPO_DIR" --status blocked \
  --summary "fixture blocked by external service" >/dev/null
python3 "$SCRIPT_ROOT/auto_dev.py" start --repo-root "$REPO_DIR" --tier direct \
  --task "one-shot direct fixture" --requirement-receipt REQ-DIRECT --confirmation-source selftest \
  --acceptance "one-shot behavior is verified" --scope README.md --validation "direct smoke" \
  --outcome-kind behavior_change --primary-outcome "One-shot behavior is verified" \
  --proof-id direct-smoke --proof-description "Run the one-shot behavior smoke" >/dev/null

if python3 "$SCRIPT_ROOT/auto_dev.py" finish --repo-root "$REPO_DIR" --status passed \
  --summary "unproven direct result" --validation "direct smoke" >/dev/null 2>&1; then
  fail "one-shot Direct run passed without a proof receipt"
fi
if python3 "$SCRIPT_ROOT/auto_dev.py" task review --repo-root "$REPO_DIR" \
  --state-revision 1 --summary "unproven direct result" --file README.md \
  --validation "direct smoke" >/dev/null 2>&1; then
  fail "review_ready accepted a one-shot Direct run without a proof receipt"
fi
python3 "$SCRIPT_ROOT/auto_dev.py" proof --repo-root "$REPO_DIR" --node run \
  --proof-id direct-smoke --plan-revision 0 --state-revision 1 \
  --command "python3 -c 'pass'" >/dev/null
STATE_REVISION="$(python3 - "$REPO_DIR/.auto-dev/active.json" <<'PY'
import json
import pathlib
import sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["state_revision"])
PY
)"
python3 "$SCRIPT_ROOT/auto_dev.py" task review --repo-root "$REPO_DIR" \
  --state-revision "$STATE_REVISION" --summary "one-shot result is ready for review" \
  --file README.md --validation "direct smoke" >/dev/null
python3 "$SCRIPT_ROOT/auto_dev.py" finish --repo-root "$REPO_DIR" --status passed \
  --summary "one-shot direct result accepted" --confirmation-source selftest >/dev/null

echo "outcome-contract-test: PASS"
