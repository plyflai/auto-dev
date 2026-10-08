#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="$(mktemp -d)"
trap 'rm -rf "$REPO_DIR"' EXIT
git -C "$REPO_DIR" init -q
git -C "$REPO_DIR" config user.name "Dependency Registry Selftest"
git -C "$REPO_DIR" config user.email "dependency-registry@example.com"
printf 'fixture\n' >"$REPO_DIR/README.md"
git -C "$REPO_DIR" add README.md
git -C "$REPO_DIR" commit -qm init
git -C "$REPO_DIR" checkout -qb dependency-test

python3 "$SCRIPT_ROOT/dependency_manager.py" record dependency --repo-root "$REPO_DIR" \
  --id frida-py310 --name Frida --purpose "Android instrumentation" \
  --capability android-instrumentation --source "https://github.com/frida/frida" \
  --version "Python 3.10 + Frida 16.5" --environment "Python 3.10" \
  --prerequisite "Android device is attached" --command "frida-ps -U" \
  --runtime-argv "[\"$REPO_DIR/bin/frida\",\"tools/frida/run_probe.py\"]" \
  --success "target process is listed" --evidence "device smoke passed" \
  --scope reverse --status known-good --role preferred >/dev/null

python3 "$SCRIPT_ROOT/dependency_manager.py" record dependency --repo-root "$REPO_DIR" \
  --id frida-py39 --name Frida --purpose "Android instrumentation" \
  --capability android-instrumentation --source "https://github.com/frida/frida" \
  --version "Python 3.9 + Frida 16.5" --environment "Python 3.9" \
  --evidence "attach compatibility failure" --scope reverse \
  --status known-bad --role avoid --incompatible "Python 3.9" \
  --fallback frida-py310 >/dev/null

python3 "$SCRIPT_ROOT/dependency_manager.py" resolve --repo-root "$REPO_DIR" \
  --capability android-instrumentation --scope reverse --environment "Python 3.10" \
  --write-lease | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["status"] == "resolved"
assert value["selected"]["id"] == "frida-py310"
assert value["blocked"][0]["id"] == "frida-py39"
assert value["lease"]["dependency_id"] == "frida-py310"
'
[[ -f "$REPO_DIR/.auto-dev/dependency-lease.json" ]] || {
  echo "dependency-registry-contract-test: FAIL: lease missing" >&2
  exit 1
}
python3 "$SCRIPT_ROOT/dependency_manager.py" gate --repo-root "$REPO_DIR" \
  --capability android-instrumentation \
  --argv-json "[\"$REPO_DIR/bin/frida\",\"tools/frida/run_probe.py\",\"--script\",\"probe.js\"]" | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["status"] == "allowed"
assert value["reason"] == "active_lease"
'
set +e
python3 "$SCRIPT_ROOT/dependency_manager.py" gate --repo-root "$REPO_DIR" \
  --capability android-instrumentation \
  --argv-json '["/tmp/wrong-frida","tools/frida/run_probe.py"]' >"$REPO_DIR/gate-mismatch.json"
gate_status=$?
set -e
[[ "$gate_status" -eq 3 ]] || {
  echo "dependency-registry-contract-test: FAIL: mismatched runtime binding was allowed" >&2
  exit 1
}
python3 - "$REPO_DIR/gate-mismatch.json" <<'PY'
import json, sys
assert json.load(open(sys.argv[1], encoding="utf-8"))["reason"] == "lease_runtime_binding_mismatch"
PY

python3 "$SCRIPT_ROOT/dependency_manager.py" attempt --repo-root "$REPO_DIR" \
  --dependency-id frida-py310 --result failed --classification environment \
  --summary "device was disconnected" --evidence "adb: no devices" \
  --environment "Python 3.10" >/dev/null
python3 "$SCRIPT_ROOT/dependency_manager.py" show frida-py310 --repo-root "$REPO_DIR" --attempts | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["entry"]["status"] == "known-good"
assert value["attempts"][0]["classification"] == "environment"
'

python3 "$SCRIPT_ROOT/dependency_manager.py" record dependency --repo-root "$REPO_DIR" \
  --id frida-next --name Frida --purpose "Android instrumentation" \
  --capability android-instrumentation --source "https://github.com/frida/frida" \
  --version "Python 3.10 + Frida 17" --environment "Python 3.10" \
  --command "frida-ps -U" --success "target process is listed" \
  --evidence "candidate install passed" --scope reverse \
  --status candidate --role candidate --check-policy ttl \
  --next-review "2000-01-01T00:00:00+00:00" >/dev/null
python3 "$SCRIPT_ROOT/dependency_manager.py" review --repo-root "$REPO_DIR" \
  --capability android-instrumentation | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert any(entry["id"] == "frida-next" for entry in value["entries"])
'
python3 "$SCRIPT_ROOT/dependency_manager.py" attempt --repo-root "$REPO_DIR" \
  --dependency-id frida-next --result passed --classification unknown \
  --summary "candidate passed target smoke" --evidence "target is listed" \
  --next-status known-good --next-role fallback >/dev/null
python3 "$SCRIPT_ROOT/dependency_manager.py" show frida-next --repo-root "$REPO_DIR" | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["entry"]["status"] == "known-good"
assert value["entry"]["role"] == "fallback"
assert value["entry"]["revisions"]
'

python3 "$SCRIPT_ROOT/dependency_manager.py" record dependency --repo-root "$REPO_DIR" \
  --id frida-bound-candidate --name Frida --purpose "Android instrumentation candidate" \
  --capability android-instrumentation --source "https://github.com/frida/frida" \
  --version "Python 3.13 + Frida 17" --environment "Python 3.13" \
  --command "python tools/frida/run_probe.py" \
  --runtime-argv "[\"$REPO_DIR/bin/frida17-python\",\"tools/frida/run_probe.py\"]" \
  --success "probe_ready" --evidence "candidate declared" --scope reverse \
  --status candidate --role candidate >/dev/null
python3 "$SCRIPT_ROOT/dependency_manager.py" preflight open --repo-root "$REPO_DIR" \
  --permit-id frida17-preflight --dependency-id frida-bound-candidate \
  --capability android-instrumentation --scope reverse --action-id capture-1 \
  --argv-json "[\"$REPO_DIR/bin/frida17-python\",\"tools/frida/run_probe.py\",\"--script\",\"probe.js\"]" >/dev/null
python3 "$SCRIPT_ROOT/dependency_manager.py" gate --repo-root "$REPO_DIR" \
  --capability android-instrumentation \
  --argv-json "[\"$REPO_DIR/bin/frida17-python\",\"tools/frida/run_probe.py\",\"--script\",\"probe.js\"]" | python3 -c '
import json, sys
assert json.load(sys.stdin)["status"] == "preflight-permitted"
'
python3 "$SCRIPT_ROOT/dependency_manager.py" preflight close --repo-root "$REPO_DIR" \
  --permit-id frida17-preflight --result passed --classification output \
  --summary "bridge probe reached probe_ready" --evidence "probe_ready" --promote >/dev/null
[[ ! -e "$REPO_DIR/.auto-dev/dependency-preflight.json" ]] || {
  echo "dependency-registry-contract-test: FAIL: closed preflight permit remains" >&2
  exit 1
}
python3 "$SCRIPT_ROOT/dependency_manager.py" gate --repo-root "$REPO_DIR" \
  --capability android-instrumentation \
  --argv-json "[\"$REPO_DIR/bin/frida17-python\",\"tools/frida/run_probe.py\",\"--script\",\"probe.js\"]" | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["status"] == "allowed"
assert value["lease"]["dependency_id"] == "frida-bound-candidate"
'
python3 "$SCRIPT_ROOT/dependency_manager.py" preflight open --repo-root "$REPO_DIR" \
  --permit-id frida17-input-failure --dependency-id frida-bound-candidate \
  --capability android-instrumentation --scope reverse --action-id input-failure-1 \
  --argv-json "[\"$REPO_DIR/bin/frida17-python\",\"tools/frida/run_probe.py\",\"--script\",\"probe.js\"]" >/dev/null
python3 "$SCRIPT_ROOT/dependency_manager.py" preflight close --repo-root "$REPO_DIR" \
  --permit-id frida17-input-failure --result failed --classification input \
  --summary "fixture used an invalid target" --evidence "target name typo" >/dev/null
python3 "$SCRIPT_ROOT/dependency_manager.py" gate --repo-root "$REPO_DIR" \
  --capability android-instrumentation \
  --argv-json "[\"$REPO_DIR/bin/frida17-python\",\"tools/frida/run_probe.py\",\"--script\",\"probe.js\"]" | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["status"] == "allowed"
assert value["lease"]["dependency_id"] == "frida-bound-candidate"
'
python3 "$SCRIPT_ROOT/dependency_manager.py" preflight open --repo-root "$REPO_DIR" \
  --permit-id frida17-recheck --dependency-id frida-bound-candidate \
  --capability android-instrumentation --scope reverse --action-id recheck-1 \
  --argv-json "[\"$REPO_DIR/bin/frida17-python\",\"tools/frida/run_probe.py\",\"--script\",\"probe.js\"]" >/dev/null
python3 "$SCRIPT_ROOT/dependency_manager.py" preflight close --repo-root "$REPO_DIR" \
  --permit-id frida17-recheck --result failed --classification compatibility \
  --summary "host and server versions differ" --evidence "major mismatch" >/dev/null
set +e
python3 "$SCRIPT_ROOT/dependency_manager.py" gate --repo-root "$REPO_DIR" \
  --capability android-instrumentation \
  --argv-json "[\"$REPO_DIR/bin/frida17-python\",\"tools/frida/run_probe.py\",\"--script\",\"probe.js\"]" >"$REPO_DIR/gate-recheck.json"
gate_status=$?
set -e
[[ "$gate_status" -eq 3 ]] || {
  echo "dependency-registry-contract-test: FAIL: failed preflight left its lease active" >&2
  exit 1
}
python3 - "$REPO_DIR/gate-recheck.json" <<'PY'
import json, sys
assert json.load(open(sys.argv[1], encoding="utf-8"))["status"] == "preflight-required"
PY
python3 "$SCRIPT_ROOT/dependency_manager.py" show frida-bound-candidate --repo-root "$REPO_DIR" | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert value["entry"]["status"] == "needs-recheck"
assert value["entry"]["role"] == "candidate"
'

python3 "$SCRIPT_ROOT/project_memory.py" record toolchain --repo-root "$REPO_DIR" \
  --id jadx --name jadx --purpose "APK decompiler" --source "https://github.com/skylot/jadx" \
  --version 1.5.1 --prerequisite "JDK 17" --command "jadx app.apk -d out" \
  --success "out/sources exists" --evidence out/sources --scope app.apk >/dev/null
python3 "$SCRIPT_ROOT/dependency_manager.py" list --repo-root "$REPO_DIR" \
  --kind dependency --compact | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert any(entry["id"] == "jadx" and entry["kind"] == "dependency" for entry in value["entries"])
'

if python3 "$SCRIPT_ROOT/dependency_manager.py" record dependency --repo-root "$REPO_DIR" \
  --id bad --name bad --purpose "bad" --capability bad --source "https://example.invalid" \
  --version 1 --command "echo password=secret" --success ok --evidence evidence \
  --scope bad >/dev/null 2>&1; then
  echo "dependency-registry-contract-test: FAIL: accepted secret" >&2
  exit 1
fi

printf 'changed\n' >>"$REPO_DIR/README.md"
git -C "$REPO_DIR" add README.md
git -C "$REPO_DIR" commit -qm changed
python3 "$SCRIPT_ROOT/dependency_manager.py" verify --repo-root "$REPO_DIR" | python3 -c '
import json, sys
value = json.load(sys.stdin)
assert any(item["status"] == "needs-recheck" for item in value["results"])
'
if python3 "$SCRIPT_ROOT/dependency_manager.py" verify --repo-root "$REPO_DIR" --strict >/dev/null 2>&1; then
  echo "dependency-registry-contract-test: FAIL: strict verify accepted recheck" >&2
  exit 1
fi

echo "dependency-registry-contract-test: PASS"
