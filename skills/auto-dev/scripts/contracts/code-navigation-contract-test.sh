#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTRACT="$SCRIPT_ROOT/../references/control-plane/code-navigation.md"
[[ -f "$CONTRACT" ]] || { echo "code-navigation-contract-test: FAIL: contract missing" >&2; exit 1; }
for token in "codegraph status" "codegraph init -i" "codegraph explore" "codegraph impact" "stale" "Raw Read 降级"; do
  if ! rg -q --fixed-strings "$token" "$CONTRACT"; then
    echo "code-navigation-contract-test: FAIL: missing $token" >&2
    exit 1
  fi
done
echo "code-navigation-contract-test: PASS"
