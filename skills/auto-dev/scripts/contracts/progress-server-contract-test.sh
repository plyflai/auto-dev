#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="$(mktemp -d)"
SECOND_REPO_DIR="$(mktemp -d)"
PLAN_FILE="$(mktemp)"
SERVER_LOG="$(mktemp)"
READY_FILE="$(mktemp)"
SERVER_PID=""
SECOND_SERVER_LOG="$(mktemp)"
SECOND_READY_FILE="$(mktemp)"
SECOND_SERVER_PID=""
cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  if [[ -n "$SECOND_SERVER_PID" ]]; then
    kill "$SECOND_SERVER_PID" 2>/dev/null || true
    wait "$SECOND_SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$REPO_DIR" "$SECOND_REPO_DIR" "$PLAN_FILE" "$SERVER_LOG" "$READY_FILE" "$SECOND_SERVER_LOG" "$SECOND_READY_FILE"
}
trap cleanup EXIT

git -C "$REPO_DIR" init -q
git -C "$REPO_DIR" config user.name "Auto Dev Progress Selftest"
git -C "$REPO_DIR" config user.email "auto-dev@example.com"
printf 'fixture\n' >"$REPO_DIR/README.md"
git -C "$REPO_DIR" add README.md
git -C "$REPO_DIR" commit -qm "init"
git -C "$REPO_DIR" checkout -qb progress-test

python3 "$SCRIPT_ROOT/runctl.py" start \
  --repo-root "$REPO_DIR" --tier direct --task "progress fixture" \
  --requirement-receipt REQ-PROGRESS --confirmation-source "selftest" \
  --acceptance "timeline renders" --scope README.md --validation "API smoke" >/dev/null

python3 "$SCRIPT_ROOT/auto_dev.py" workspace checkpoint create \
  --repo-root "$REPO_DIR" --kind baseline \
  --confirmation-source "progress archive point" >/dev/null

python3 - "$PLAN_FILE" <<'PY'
import json
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text(json.dumps({
    "goal": {"statement": "timeline renders", "acceptance": ["timeline renders"], "source": "selftest"},
    "nodes": [
        {"id": "prepare", "title": "Prepare state", "status": "active", "outcome": {"kind": "behavior_change", "primary": "Progress state is available to the service", "proofs": [{"id": "state-api", "description": "Read the progress state API"}]}},
        {"id": "verify", "title": "Verify state", "status": "planned", "depends_on": ["prepare"], "outcome": {"kind": "behavior_change", "primary": "Progress page renders its state", "proofs": [{"id": "page-smoke", "description": "Open the progress page"}]}},
    ],
    "current_node": "prepare",
    "next_action": "open the progress view",
}), encoding="utf-8")
PY
python3 "$SCRIPT_ROOT/runctl.py" plan --repo-root "$REPO_DIR" --base-revision 0 \
  --reason "progress service fixture" --plan-file "$PLAN_FILE" >/dev/null

PROTECTION_JSON="$(python3 "$SCRIPT_ROOT/auto_dev.py" workspace checkpoint protect \
  --repo-root "$REPO_DIR" --node prepare --scope README.md \
  --confirmation-source "progress checkpoint fixture")"
PROTECTION_ID="$(python3 -c 'import json, sys; print(json.loads(sys.argv[1])["protection"]["id"])' "$PROTECTION_JSON")"
python3 "$SCRIPT_ROOT/auto_dev.py" workspace checkpoint create \
  --repo-root "$REPO_DIR" --kind baseline --protection-id "$PROTECTION_ID" \
  --confirmation-source "progress before point fixture" >/dev/null

PYTHON_BIN="$(command -v python3)"
python3 "$SCRIPT_ROOT/auto_dev.py" deps record dependency --repo-root "$REPO_DIR" \
  --id progress-python --scope progress --evidence "progress server contract" \
  --version "fixture" --name "Python" --purpose "serve the progress view" \
  --capability progress-view --status known-good --source "local test runtime" \
  --command "$PYTHON_BIN" --runtime-argv "[\"$PYTHON_BIN\"]" \
  --success "serves compact progress state" --check-policy on_failure >/dev/null
python3 "$SCRIPT_ROOT/auto_dev.py" deps resolve --repo-root "$REPO_DIR" \
  --capability progress-view --scope progress --write-lease >/dev/null
python3 "$SCRIPT_ROOT/auto_dev.py" deps attempt --repo-root "$REPO_DIR" \
  --dependency-id progress-python --result passed --classification environment \
  --summary "progress dependency verified" --evidence "progress server contract" \
  --next-status known-good >/dev/null
python3 "$SCRIPT_ROOT/auto_dev.py" deps record dependency --repo-root "$REPO_DIR" \
  --id stale-python --scope stale --evidence "expired progress fixture" \
  --version "fixture" --name "Expired Python" --purpose "exercise stale dependency filtering" \
  --capability stale-view --status known-good --source "local test runtime" \
  --command "$PYTHON_BIN" --runtime-argv "[\"$PYTHON_BIN\"]" \
  --success "would serve a stale view" --check-policy ttl \
  --next-review "2000-01-01T00:00:00Z" >/dev/null

python3 "$SCRIPT_ROOT/progress_server.py" --repo-root "$REPO_DIR" --ready-file "$READY_FILE" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
PORT=""
for _ in $(seq 1 40); do
  PORT="$(python3 - "$READY_FILE" <<'PY'
import json
import pathlib
import sys

try:
    value = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    value = {}
port = value.get("port")
print(port if isinstance(port, int) and port > 0 else "")
PY
)"
  [[ -n "$PORT" ]] && break
  sleep 0.1
done
[[ -n "$PORT" ]] || { cat "$SERVER_LOG" >&2; exit 1; }

git -C "$SECOND_REPO_DIR" init -q
git -C "$SECOND_REPO_DIR" config user.name "Auto Dev Second Progress Selftest"
git -C "$SECOND_REPO_DIR" config user.email "auto-dev-second@example.com"
printf 'second fixture\n' >"$SECOND_REPO_DIR/README.md"
git -C "$SECOND_REPO_DIR" add README.md
git -C "$SECOND_REPO_DIR" commit -qm "init"
python3 "$SCRIPT_ROOT/progress_server.py" --repo-root "$SECOND_REPO_DIR" --ready-file "$SECOND_READY_FILE" >"$SECOND_SERVER_LOG" 2>&1 &
SECOND_SERVER_PID=$!
SECOND_PORT=""
for _ in $(seq 1 40); do
  SECOND_PORT="$(python3 - "$SECOND_READY_FILE" <<'PY'
import json
import pathlib
import sys

try:
    value = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    value = {}
port = value.get("port")
print(port if isinstance(port, int) and port > 0 else "")
PY
)"
  [[ -n "$SECOND_PORT" ]] && break
  sleep 0.1
done
[[ -n "$SECOND_PORT" ]] || { cat "$SECOND_SERVER_LOG" >&2; exit 1; }
[[ "$PORT" != "$SECOND_PORT" ]] || { echo "automatic ports collided" >&2; exit 1; }

python3 - "$PORT" <<'PY'
import json
import sys
import time
import urllib.request

port = sys.argv[1]
url = f"http://127.0.0.1:{port}"
for _ in range(40):
    try:
        with urllib.request.urlopen(url + "/api/state", timeout=1) as response:
            state = json.load(response)
        assert state["view"] == "compact"
        assert "events" not in state
        assert state["continuity_summary"]["plan_revision"] == 1
        assert state["continuity_summary"]["current_node"] == "prepare"
        assert state["bootstrap_status"] == "ready"
        assert state["outcome_summary"]["contracted_outcomes"] == 2
        assert state["outcome_summary"]["required_proofs"] == 2
        assert state["outcome_summary"]["passed_proofs"] == 0
        assert state["outcome_summary"]["legacy_nodes"] == 0
        assert state["continuity"]["proofs"] == []
        assert state["continuity_summary"]["workspace_points"][0]["status"] == "recorded"
        assert state["continuity_summary"]["workspace_points"][0]["checkpoint"]["archive_phase"] == "before_change"
        milestone_points = state["workspace_checkpoint_nodes"]["prepare"][0]
        assert milestone_points["before"]["status"] == "recorded"
        assert milestone_points["before"]["short_hash"] == milestone_points["before"]["object"][:8]
        assert milestone_points["after"]["status"] == "pending"
        dependencies = state["dependencies"]
        assert dependencies["status"] == "ready"
        assert dependencies["trusted"][0]["id"] == "progress-python"
        assert all(item["id"] != "stale-python" for item in dependencies["trusted"])
        assert dependencies["trusted"][0]["active_lease_count"] == 1
        assert dependencies["leases"][0]["dependency_id"] == "progress-python"
        assert any(event["type"] == "attempt" for event in dependencies["timeline"])
        with urllib.request.urlopen(url + "/", timeout=1) as response:
            html = response.read().decode("utf-8")
        assert "任务进度" in html
        assert "/api/events" in html
        assert "state.continuity_summary" in html
        assert "buildProjection" in html
        assert "roots.slice().reverse()" in html
        assert "children.slice().reverse()" in html
        assert "detail-group" in html
        assert "node-details" in html
        assert "summary class=\"node-title\"" in html
        assert "detail-action" not in html
        assert "node.display_code" in html
        assert "data-depth" in html
        assert "投影 v8" in html
        assert "Projection v8" in html
        assert 'id="diagnostic-summary"' in html
        assert 'id="impact-summary"' in html
        assert "outcome-overview" in html
        assert 'id="execution-card"' in html
        assert 'id="project-overview"' in html
        assert 'id="focus-grid"' not in html
        assert "intakePlain" in html
        assert "nodeProofView" in html
        assert "outcome-primary" in html
        assert "proof-state" in html
        assert "id=\"unattributed\"" in html
        assert "unattributedActions" in html
        assert "state.unattributed_actions" in html
        assert "reviewReady" in html
        assert "taskLifecycle" in html
        assert "review_ready" in html
        assert "id=\"dependency-panel\"" in html
        assert "renderDependencies" in html
        assert "dependencyTimeline" in html
        assert "trustedDependencies" in html
        assert "id=\"archive-points\"" in html
        assert "renderArchivePoints" in html
        assert "archivePointStatus" in html
        assert "renderMilestoneCheckpointChain" in html
        assert "workspace_checkpoint_nodes" in html
        assert "milestone-checkpoint-chain" in html
        assert "POLL_INTERVAL_MS = 60 * 1000" in html
        assert "setInterval(() => { if (!sseHealthy) fetchState(); }, POLL_INTERVAL_MS)" in html
        with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
            health = json.load(response)
        assert health["task_id"] == state["id"]
        assert health["state_revision"] == state["state_revision"]
        assert health["repo_fingerprint"]
        break
    except (OSError, TimeoutError):
        time.sleep(0.1)
else:
    raise SystemExit("progress server did not become ready")
PY

python3 - "$PORT" "$REPO_DIR" "$SCRIPT_ROOT/runctl.py" <<'PY'
import json
import subprocess
import sys
import urllib.request

port, repo, runctl = sys.argv[1:]
with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events", timeout=4) as response:
    first = None
    while first is None:
        line = response.readline().decode("utf-8")
        if line.startswith("data: "):
            first = json.loads(line[6:])
    assert first["continuity_summary"]["current_node"] == "prepare"
    subprocess.run([
        sys.executable, runctl, "proof", "--repo-root", repo,
        "--plan-revision", str(first["continuity_summary"]["plan_revision"]),
        "--state-revision", str(first["state_revision"]),
        "--node", "prepare", "--proof-id", "state-api",
        "--command", "python3 -c 'pass'",
    ], check=True, stdout=subprocess.DEVNULL)
    with open(f"{repo}/.auto-dev/active.json", encoding="utf-8") as handle:
        current = json.load(handle)
    subprocess.run([
        sys.executable, runctl, "checkpoint", "--repo-root", repo,
        "--plan-revision", str(first["continuity_summary"]["plan_revision"]),
        "--state-revision", str(current["state_revision"]),
        "--node", "prepare", "--status", "done", "--summary", "prepare complete",
        "--next-node", "verify", "--next-action", "verify state",
        "--evidence", "progress API",
    ], check=True, stdout=subprocess.DEVNULL)
    second = None
    while second is None:
        line = response.readline().decode("utf-8")
        if not line:
            break
        if line.startswith("data: "):
            candidate = json.loads(line[6:])
            if candidate["continuity_summary"]["current_node"] == "verify":
                second = candidate
    assert second is not None, "SSE did not publish the checkpoint update"
    assert second["continuity"]["last_checkpoint"]["node_id"] == "prepare"
    assert second["outcome_summary"]["passed_proofs"] == 1
    assert second["outcome_summary"]["proved_outcomes"] == 1
    assert second["continuity"]["proofs"][0]["proof_id"] == "state-api"
    assert "command" not in second["continuity"]["proofs"][0]
print("progress-server-contract-test: PASS")
PY
