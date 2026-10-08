#!/usr/bin/env bash

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME="$SKILL_DIR/references/control-plane/runtime-diagnostics.md"
INTAKE="$SKILL_DIR/references/intake/requirement-intake.md"
VERIFY="$SKILL_DIR/references/verification/verification.md"
RESUME="$SKILL_DIR/references/continuity/resume-handoff.md"

fail() {
  echo "runtime-diagnostics-contract-test: FAIL: $*" >&2
  exit 1
}

[[ -f "$RUNTIME" ]] || fail "runtime diagnostics contract is missing"

for outcome in covered augment foundation not_applicable; do
  rg -q --fixed-strings "\`$outcome\`" "$RUNTIME" || fail "missing outcome: $outcome"
done

rg -q --fixed-strings "这里不新增确认门" "$RUNTIME" || fail "contract permits a new confirmation gate"
rg -q --fixed-strings ".auto-dev/runtime-diagnostics.json" "$RUNTIME" || fail "contract lacks persistent diagnostics manifest"
rg -q --fixed-strings "运行诊断结论" "$INTAKE" || fail "final receipt does not include diagnostics"
rg -q --fixed-strings ".auto-dev/runtime-diagnostics.json" "$VERIFY" || fail "verification does not read diagnostics manifest"
rg -q --fixed-strings ".auto-dev/runtime-diagnostics.json" "$RESUME" || fail "resume does not read diagnostics manifest"
rg -q --fixed-strings "不包含凭据、令牌" "$RUNTIME" || fail "manifest read methods may expose credentials"

echo "runtime-diagnostics-contract-test: PASS"
