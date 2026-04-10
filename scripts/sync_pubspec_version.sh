#!/usr/bin/env bash
# Syncs frontend/pubspec.yaml version to match the root pyproject.toml version.
# The build number (+N suffix) is incremented by 1 from its current value.
set -euo pipefail

PYPROJECT="pyproject.toml"
PUBSPEC="frontend/pubspec.yaml"

# Extract version from pyproject.toml (e.g., "0.2.0")
NEW_VERSION=$(grep -m1 '^version' "$PYPROJECT" | sed 's/version *= *"\(.*\)"/\1/')

# Extract current build number from pubspec.yaml (e.g., 1 from "0.1.0+1")
CURRENT_BUILD=$(grep -m1 '^version:' "$PUBSPEC" | sed 's/.*+\([0-9]*\)/\1/')
NEXT_BUILD=$((CURRENT_BUILD + 1))

# Replace the version line in pubspec.yaml
sed -i.bak "s/^version: .*/version: ${NEW_VERSION}+${NEXT_BUILD}/" "$PUBSPEC"
rm -f "${PUBSPEC}.bak"

echo "Synced $PUBSPEC to ${NEW_VERSION}+${NEXT_BUILD}"
