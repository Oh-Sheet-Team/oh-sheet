---
phase: 03-live-anthropic-and-frontend-toggle
plan: 04
subsystem: frontend/upload-screen
tags:
  - frontend
  - flutter
  - ui
  - capabilities
  - refine
  - ux-01
  - ux-02
  - ux-05
  - d-20
  - d-21
  - d-22
  - d-23
requirements:
  - UX-01
  - UX-02
  - UX-05
dependency_graph:
  requires:
    - frontend/lib/api/client.dart::createJob(enableRefine:)
    - frontend/lib/api/client.dart::getCapabilities()
    - frontend/lib/api/models.dart::Capabilities
  provides:
    - UploadScreen renders an "AI refinement" section on every source variant
    - _enableRefine state field threaded into all four createJob() branches
    - Capabilities-gated disabled state + D-22 helper text on refineAvailable=false
    - Widget test coverage for UX-05 (default-false) + UX-02 (forwarding) + D-22 (disabled state)
  affects:
    - frontend/lib/screens/upload_screen.dart
    - frontend/test/widgets/upload_screen_refine_test.dart
tech_stack:
  added: []
  patterns:
    - Mirror existing _preferCleanSource SwitchListTile pattern (same ValueKey, dense, contentPadding=zero, OhSheetColors.teal activeThumbColor)
    - Capabilities probe-on-mount via initState() + setState on resolution
    - Optimistic default (toggle enabled until probe resolves, disabled-on-failure is the safe fallback)
    - http/testing MockClient + closure-captured POST body (same shape as upload_screen_cover_search_test.dart)
key_files:
  created:
    - frontend/test/widgets/upload_screen_refine_test.dart
  modified:
    - frontend/lib/screens/upload_screen.dart
decisions:
  - "D-20 applied: AI refinement section placed below the conditional mode inputs and above the submit CTA, visible for ALL source variants (not scoped to YouTube)."
  - "D-21 applied verbatim: subtitle reads 'Uses an AI model to polish the generated score. Experimental — may add processing cost and a few seconds of latency.'"
  - "D-22 applied verbatim: refineAvailable=false → SwitchListTile.onChanged=null AND 'AI refinement not configured on this server' helper text rendered below."
  - "D-23 applied: no shared_preferences, no cross-session persistence. State resets to false on every screen construction. Refine is also NOT reset on source-mode change (variant-independent, unlike _preferCleanSource)."
  - "Capabilities probe defaults to enabled while the future is outstanding (optimistic), disabled on failure (safe default). Prevents flicker while still surfacing the disabled state if the probe actually reports false or fails."
metrics:
  duration_seconds: 183
  duration_minutes: 3
  tasks_completed: 2
  files_created: 1
  files_modified: 1
  completed_date: "2026-04-14T04:15:31Z"
---

# Phase 3 Plan 4: Upload Screen Refine Section Summary

Added a dedicated "AI refinement" section to `UploadScreen` with a capabilities-gated `SwitchListTile` wired into all four `createJob()` branches, plus widget tests covering default-false (UX-05), POST-body forwarding (UX-02), and the disabled-state + D-22 helper text path.

## What Shipped

### `frontend/lib/screens/upload_screen.dart` — AI refinement section + state + capabilities probe

- **State:** Added `bool _enableRefine = false` (D-23: defaults false on every screen construction, no persistence) and `Capabilities? _capabilities` populated in `initState()` via a new `_loadCapabilities()` method.
- **Failure semantics:** If `getCapabilities()` throws, state is set to `const Capabilities(refineAvailable: false)` — safe default so the user doesn't submit and get a 400 at the server. The error is silent; this is a pre-flight probe, not a user action.
- **UI:** New section inserted between the conditional mode-input cluster and the submit CTA. Section title is `OhSheetStickerSectionTitle(text: 'AI refinement', accent: OhSheetColors.teal)`. The `SwitchListTile` carries `ValueKey('enableRefineToggle')`, `activeThumbColor: OhSheetColors.teal`, title `'Use AI refinement (experimental)'` (UX-01 SC1 label), and subtitle matching D-21 verbatim.
- **Disabled state (D-22):** When `_capabilities?.refineAvailable == false`, the switch's `onChanged` is `null` (rendering the widget as disabled) AND a `Padding`-wrapped `Text` with `'AI refinement not configured on this server'` is rendered beneath (D-22 verbatim, italic mutedText styling for helper-text feel).
- **Threading (UX-02):** `enableRefine: _enableRefine` added to all four `createJob()` calls in `_submit()`: audio, midi, title, youtube. Grep confirms exactly 4 occurrences of `enableRefine: _enableRefine` in the file.
- **Variant independence:** Refine state is NOT reset on source-mode change — unlike `_preferCleanSource` which is YouTube-only. The planner's specific instruction (plan §D-20 rationale) is honored: refine applies regardless of input type, so the user's opt-in survives a mid-session mode flip.

### `frontend/test/widgets/upload_screen_refine_test.dart` — widget test coverage

Six `testWidgets` cases across three groups:

1. **UX-05 default-false (3 tests):** toggle is rendered (`findsOneWidget`), `widget.value` is false, section title `'AI refinement'` is visible, title text `'Use AI refinement (experimental)'` is visible.
2. **UX-02 forwarding (2 tests):** ticking the toggle and submitting a title-lookup job causes the intercepted `POST /v1/jobs` body to contain `enable_refine: true`; submitting WITHOUT ticking sends `enable_refine: false` (the default-survival assertion).
3. **D-22 disabled state (1 test):** with `refineAvailable=false`, `SwitchListTile.onChanged` is `null` AND the helper text `'AI refinement not configured on this server'` is visible.

The mock API is a `http_testing.MockClient` that returns `/v1/capabilities` canned responses and captures `/v1/jobs` POST bodies into a closure-captured list — same shape as the existing `upload_screen_cover_search_test.dart` fixture pattern.

## Verification

**Automated:**

- `cd frontend && flutter analyze lib/screens/upload_screen.dart` → `No issues found!`
- `cd frontend && flutter analyze` (full) → `No issues found!`
- `cd frontend && flutter test test/widgets/upload_screen_refine_test.dart` → `+6: All tests passed!`
- `cd frontend && flutter test` (full suite) → `+67: All tests passed!` (no regressions in the 61 pre-existing Flutter tests)

**Literal grep checks (plan Task 1 acceptance criteria):**

| Pattern | Found | Expected |
|---------|-------|----------|
| `bool _enableRefine = false;` | line 48 | present |
| `Capabilities? _capabilities;` | line 55 | present |
| `widget.api.getCapabilities()` | line 78 | present |
| `ValueKey('enableRefineToggle')` | line 424 | present |
| `'Use AI refinement (experimental)'` | line 433 | present |
| `'Uses an AI model to polish the generated score. '` | line 441 | present (D-21) |
| `'AI refinement not configured on this server'` | line 454 | present (D-22) |
| `'AI refinement'` (section title) | line 419 | present |
| `activeThumbColor: OhSheetColors.teal` (refine section) | line 431 | present |
| `grep -c 'enableRefine: _enableRefine'` | 4 | 4 |
| `grep -c 'shared_preferences'` | 0 | 0 |

**Literal grep checks (plan Task 2 acceptance criteria):**

| Pattern | File | Found |
|---------|------|-------|
| `ValueKey('enableRefineToggle')` | test file | lines 72, 116, 118, 161 |
| `expect(widget.value, isFalse` | test file | line 77 |
| `mock.lastJobBody['enable_refine']` | test file | lines 128, 150 |
| `widget.onChanged, isNull` | test file | line 162 |

## Deviations from Plan

None — plan executed exactly as written. Two very small editorial judgment calls:

1. The mock-API helper was implemented as a small `_MockApiHandle` class rather than a record-type-return pattern (`({OhSheetApi api, Map<String,dynamic> Function() lastJobBody})`) from the plan's sample code. Dart records with function-type fields interact awkwardly with the closure-captured mutable state the tests need; a two-field class with a `bodyRef` list is simpler, gives identical behavior, and is easier to reason about. All behavior the plan prescribes (capturing POST body, returning it to the test) is preserved; the call site reads `mock.lastJobBody['enable_refine']` exactly as the plan's sample did.
2. The `ensureVisible` step added before the submit tap in the UX-02 tests mirrors what the existing `upload_screen_cover_search_test.dart` already does — the refine section sits below the other form controls, so submit is offscreen in the default test viewport. Without `ensureVisible`, the tap would never land. This is consistent with the pattern the plan's `<read_first>` pointed at.

No Rule-1/2/3 auto-fixes were required; no threat-model mitigations needed new wiring (T-03-21 is a backend concern, already satisfied in Phase 02).

## Known Stubs

None. The refine section is a real, user-facing control; the capabilities gate wires to a real backend endpoint (shipped in Plan 02 of this phase); the createJob threading feeds a real request body.

## Threat Flags

None. The plan's `<threat_model>` enumerated T-03-18..T-03-22 and no new security-relevant surface was introduced beyond what those entries describe. The one `mitigate` disposition (T-03-21) is a backend-side re-check, not a frontend obligation.

## Self-Check: PASSED

**Files created:**
- `frontend/test/widgets/upload_screen_refine_test.dart` — FOUND

**Files modified:**
- `frontend/lib/screens/upload_screen.dart` — FOUND (with 87 insertions)

**Commits:**
- `008484a` — FOUND (`feat(03-04): add AI refinement section + capabilities gate + createJob threading to UploadScreen`)
- `1880da8` — FOUND (`test(03-04): widget tests for UploadScreen AI refinement section (UX-02/UX-05, D-22)`)
