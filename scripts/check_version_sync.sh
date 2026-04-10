#!/usr/bin/env bash
# Verifies all version sources match the root pyproject.toml version.
set -euo pipefail

ROOT_VERSION=$(grep -m1 '^version' pyproject.toml | sed 's/version *= *"\(.*\)"/\1/')
EXIT=0

check() {
  local file="$1" actual="$2"
  if [ "$actual" != "$ROOT_VERSION" ]; then
    echo "MISMATCH: $file has '$actual', expected '$ROOT_VERSION'"
    EXIT=1
  else
    echo "OK: $file = $actual"
  fi
}

check "backend/__init__.py" \
  "$(grep '__version__' backend/__init__.py | sed 's/.*"\(.*\)".*/\1/')"

check "shared/pyproject.toml" \
  "$(grep -m1 '^version' shared/pyproject.toml | sed 's/version *= *"\(.*\)"/\1/')"

check "svc-decomposer/pyproject.toml" \
  "$(grep -m1 '^version' svc-decomposer/pyproject.toml | sed 's/version *= *"\(.*\)"/\1/')"

check "svc-assembler/pyproject.toml" \
  "$(grep -m1 '^version' svc-assembler/pyproject.toml | sed 's/version *= *"\(.*\)"/\1/')"

# Check semver portion of pubspec (strip +build_number)
PUBSPEC_VERSION=$(grep -m1 '^version:' frontend/pubspec.yaml | sed 's/version: *\([^+]*\).*/\1/')
check "frontend/pubspec.yaml" "$PUBSPEC_VERSION"

exit $EXIT
