# Version Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically increment the project version on every PR merge using conventional commits, and display the version in the frontend UI footer and backend health endpoint.

**Architecture:** `python-semantic-release` parses conventional commits on push to `main`, bumps a single unified version across all components, creates a git tag, and pushes back to `main` (triggering the existing deploy workflow). The frontend reads the version at build time via `--dart-define`, and the backend health endpoint returns it at runtime.

**Tech Stack:** python-semantic-release, GitHub Actions, Flutter `String.fromEnvironment`, FastAPI

---

### Task 1: Configure python-semantic-release in pyproject.toml

**Files:**
- Modify: `pyproject.toml:108` (after `[tool.hatch.build.targets.wheel]`)

- [ ] **Step 1: Add semantic-release config to pyproject.toml**

Append the following after the existing `[tool.hatch.build.targets.wheel]` section (after line 117):

```toml
[tool.semantic_release]
version_toml = [
    "pyproject.toml:project.version",
    "shared/pyproject.toml:project.version",
    "svc-decomposer/pyproject.toml:project.version",
    "svc-assembler/pyproject.toml:project.version",
]
version_variables = [
    "backend/__init__.py:__version__",
]
branch = "main"
commit_message = "chore(release): v{version}"
tag_format = "v{version}"
build_command = false
upload_to_repository = false
```

- [ ] **Step 2: Install python-semantic-release locally and dry-run**

Run: `pip install python-semantic-release && semantic-release version --dry-run --no-vcs-release 2>&1 | head -20`

Expected: No errors parsing the config. Output shows the current version `0.1.0` and what the next version would be (or "no release" if no bumpable commits exist).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: configure python-semantic-release for unified versioning"
```

---

### Task 2: Add version to backend health endpoint

**Files:**
- Modify: `backend/api/routes/health.py`
- Modify: `tests/test_health.py`

- [ ] **Step 1: Write the failing test**

Replace the contents of `tests/test_health.py` with:

```python
import backend


def test_health_returns_ok_with_version_and_commit(client, monkeypatch):
    monkeypatch.setenv("COMMIT_SHA", "abc1234")
    # Re-import to pick up the patched env var — but the module-level
    # _COMMIT_SHA was already evaluated.  Patch it directly instead.
    import backend.api.routes.health as health_mod
    monkeypatch.setattr(health_mod, "_COMMIT_SHA", "abc1234")

    response = client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == "3.0.0"
    assert body["version"] == backend.__version__
    assert body["commit"] == "abc1234"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_health.py -v`

Expected: FAIL — `KeyError: 'version'` because the health endpoint doesn't return `version` yet.

- [ ] **Step 3: Add version to health endpoint**

Update `backend/api/routes/health.py` to:

```python
from __future__ import annotations

import os

from fastapi import APIRouter

import backend
from backend.contracts import SCHEMA_VERSION

router = APIRouter()

_COMMIT_SHA = os.environ.get("COMMIT_SHA", "unknown")


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "version": backend.__version__,
        "commit": _COMMIT_SHA,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_health.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/routes/health.py tests/test_health.py
git commit -m "feat: add version to health endpoint"
```

---

### Task 3: Add version footer to Flutter frontend

**Files:**
- Create: `frontend/lib/widgets/version_footer.dart`
- Modify: `frontend/lib/main.dart`

- [ ] **Step 1: Create the version footer widget**

Create `frontend/lib/widgets/version_footer.dart`:

```dart
import 'package:flutter/material.dart';

import '../theme.dart';

const appVersion = String.fromEnvironment('APP_VERSION', defaultValue: 'dev');

class VersionFooter extends StatelessWidget {
  const VersionFooter({super.key});

  @override
  Widget build(BuildContext context) {
    return Text(
      'v$appVersion',
      style: TextStyle(
        fontSize: 11,
        color: OhSheetColors.mutedText.withValues(alpha: 0.5),
        fontWeight: FontWeight.w500,
      ),
    );
  }
}
```

- [ ] **Step 2: Add footer to the wide layout Scaffold**

In `frontend/lib/main.dart`, add the import at the top with the other imports:

```dart
import 'widgets/version_footer.dart';
```

Then in the wide layout's `Scaffold` (around line 62), wrap the existing `body` in a `Stack` to overlay the version footer:

Replace the wide layout Scaffold's `body:` value. Change:

```dart
          return Scaffold(
            backgroundColor: OhSheetColors.cream,
            body: Row(
              children: [
                DecoratedBox(
```

to:

```dart
          return Scaffold(
            backgroundColor: OhSheetColors.cream,
            body: Stack(
              children: [
                Row(
                  children: [
                    DecoratedBox(
```

And close the Stack after the Row's closing. Change:

```dart
                ),
              ],
            ),
          );
        }
```

(the end of the wide Scaffold's Row) to:

```dart
                  ),
                ],
              ),
              const Positioned(
                right: 12,
                bottom: 8,
                child: VersionFooter(),
              ),
            ]),
          );
        }
```

- [ ] **Step 3: Add footer to the narrow layout Scaffold**

In the narrow layout Scaffold (around line 114), similarly wrap the body. Change:

```dart
        return Scaffold(
          backgroundColor: OhSheetColors.cream,
          body: IndexedStack(
            index: _currentIndex,
            children: pages,
          ),
```

to:

```dart
        return Scaffold(
          backgroundColor: OhSheetColors.cream,
          body: Stack(
            children: [
              IndexedStack(
                index: _currentIndex,
                children: pages,
              ),
              const Positioned(
                right: 12,
                bottom: 8,
                child: VersionFooter(),
              ),
            ],
          ),
```

- [ ] **Step 4: Write widget test for VersionFooter**

Create `frontend/test/widgets/version_footer_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ohsheet_app/widgets/version_footer.dart';

void main() {
  testWidgets('VersionFooter displays version text', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: VersionFooter(),
        ),
      ),
    );

    // Default value when APP_VERSION is not defined at compile time
    expect(find.text('vdev'), findsOneWidget);
  });
}
```

- [ ] **Step 5: Run Flutter tests**

Run: `cd frontend && flutter test test/widgets/version_footer_test.dart -v`

Expected: PASS — finds `vdev` text (default when `APP_VERSION` not set).

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/widgets/version_footer.dart frontend/lib/main.dart frontend/test/widgets/version_footer_test.dart
git commit -m "feat: add version footer to all screens"
```

---

### Task 4: Pass version to Docker build as build arg

**Files:**
- Modify: `Dockerfile:6-8`

- [ ] **Step 1: Add APP_VERSION build arg to Dockerfile**

In the Dockerfile, add a `ARG` before the Flutter build step. Change:

```dockerfile
RUN flutter pub get
# Empty API_BASE_URL → client uses same-origin relative URLs (/v1/...)
RUN flutter build web --release --dart-define=API_BASE_URL=
```

to:

```dockerfile
RUN flutter pub get
# Empty API_BASE_URL → client uses same-origin relative URLs (/v1/...)
ARG APP_VERSION=dev
RUN flutter build web --release --dart-define=API_BASE_URL= --dart-define=APP_VERSION=${APP_VERSION}
```

- [ ] **Step 2: Verify Docker build still works locally**

Run: `docker build --build-arg APP_VERSION=0.1.0 -t oh-sheet-test . 2>&1 | tail -5`

Expected: Build completes successfully (or at least the Flutter stage passes).

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "build: pass APP_VERSION to Flutter build via Docker arg"
```

---

### Task 5: Create pubspec sync script

**Files:**
- Create: `scripts/sync_pubspec_version.sh`

- [ ] **Step 1: Write the sync script**

Create `scripts/sync_pubspec_version.sh`:

```bash
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
```

- [ ] **Step 2: Make executable and test**

Run: `chmod +x scripts/sync_pubspec_version.sh && bash scripts/sync_pubspec_version.sh`

Expected: Prints `Synced frontend/pubspec.yaml to 0.1.0+2` (version stays 0.1.0, build number increments from 1 to 2).

- [ ] **Step 3: Verify pubspec was updated**

Run: `grep '^version:' frontend/pubspec.yaml`

Expected: `version: 0.1.0+2`

- [ ] **Step 4: Reset pubspec (script test only — real bump happens in CI)**

Run: `git checkout frontend/pubspec.yaml`

- [ ] **Step 5: Commit**

```bash
git add scripts/sync_pubspec_version.sh
git commit -m "build: add pubspec version sync script"
```

---

### Task 6: Create release.yml GitHub Actions workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create the release workflow**

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false

jobs:
  release:
    name: Semantic Release
    runs-on: ubuntu-latest
    # Skip release commits to avoid infinite loop
    if: "!startsWith(github.event.head_commit.message, 'chore(release):')"
    permissions:
      contents: write

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          token: ${{ secrets.RELEASE_PAT }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Install semantic-release
        run: pip install python-semantic-release

      - name: Run semantic-release
        id: release
        env:
          GH_TOKEN: ${{ secrets.RELEASE_PAT }}
        run: |
          OUTPUT=$(semantic-release version --no-vcs-release 2>&1) || true
          echo "$OUTPUT"
          if echo "$OUTPUT" | grep -q "no release will be made"; then
            echo "released=false" >> "$GITHUB_OUTPUT"
          else
            echo "released=true" >> "$GITHUB_OUTPUT"
          fi

      - name: Sync pubspec.yaml
        if: steps.release.outputs.released == 'true'
        run: bash scripts/sync_pubspec_version.sh

      - name: Commit and push release
        if: steps.release.outputs.released == 'true'
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add -A
          git commit --amend --no-edit
          git push --follow-tags
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add semantic-release workflow for auto-versioning"
```

---

### Task 7: Update deploy.yml to pass version as Docker build arg

**Files:**
- Modify: `.github/workflows/deploy.yml:42-54`

- [ ] **Step 1: Extract version and pass as build arg**

In `.github/workflows/deploy.yml`, add a step before "Build and push container images" to extract the version:

Add after the "Authorize Docker push" step (after line 40):

```yaml
      - name: Extract version
        id: version
        run: |
          VERSION=$(grep -m1 '^version' pyproject.toml | sed 's/version *= *"\(.*\)"/\1/')
          echo "version=$VERSION" >> "$GITHUB_OUTPUT"
```

Then update the "Build and push container images" step to pass `APP_VERSION` as a build arg. Change:

```yaml
      - name: Build and push container images
        run: |
          docker build -t ${{ env.IMAGE }}:${{ github.sha }} -t ${{ env.IMAGE }}:latest .
```

to:

```yaml
      - name: Build and push container images
        run: |
          docker build --build-arg APP_VERSION=${{ steps.version.outputs.version }} -t ${{ env.IMAGE }}:${{ github.sha }} -t ${{ env.IMAGE }}:latest .
```

- [ ] **Step 2: Include version in Slack success notification**

Update the Slack success message (around line 97). Change:

```yaml
            -d "{
              \"text\": \":white_check_mark: *oh-sheet deployed* \`${COMMIT_SHORT}\` to <https://oh-sheet.duckdns.org> — <${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}|View run>\"
            }"
```

to:

```yaml
            -d "{
              \"text\": \":white_check_mark: *oh-sheet deployed* v${{ steps.version.outputs.version }} (\`${COMMIT_SHORT}\`) to <https://oh-sheet.duckdns.org> — <${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}|View run>\"
            }"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: pass app version to Docker build and Slack notifications"
```

---

### Task 8: Add version-sync CI lint check

**Files:**
- Create: `scripts/check_version_sync.sh`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the version sync check script**

Create `scripts/check_version_sync.sh`:

```bash
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
```

- [ ] **Step 2: Make executable and test locally**

Run: `chmod +x scripts/check_version_sync.sh && bash scripts/check_version_sync.sh`

Expected: All `OK` lines, exit code 0.

- [ ] **Step 3: Add version-sync job to ci.yml**

Add a new job at the end of `.github/workflows/ci.yml`:

```yaml

  version-sync:
    name: Version Sync Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: bash scripts/check_version_sync.sh

  semantic-release-dry-run:
    name: Semantic Release Dry Run
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install python-semantic-release
      - run: semantic-release version --dry-run --no-vcs-release
```

- [ ] **Step 4: Commit**

```bash
git add scripts/check_version_sync.sh .github/workflows/ci.yml
git commit -m "ci: add version-sync lint check"
```

---

### Task 9: Manual validation and cleanup

- [ ] **Step 1: Run all backend tests**

Run: `pytest -v`

Expected: All tests pass, including the updated health test.

- [ ] **Step 2: Run Flutter tests**

Run: `cd frontend && flutter test`

Expected: All tests pass, including the version footer test.

- [ ] **Step 3: Run version sync check**

Run: `bash scripts/check_version_sync.sh`

Expected: All OK.

- [ ] **Step 4: Run lint and typecheck**

Run: `make lint && make typecheck`

Expected: Clean.

- [ ] **Step 5: Document the RELEASE_PAT secret requirement**

Add a note to the PR description: a GitHub PAT with `contents: write` permission must be added as the `RELEASE_PAT` repository secret. This token is needed so the release workflow's push triggers the deploy workflow (the default `GITHUB_TOKEN` does not trigger downstream workflows).
