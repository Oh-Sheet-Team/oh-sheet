# Testing Patterns

**Analysis Date:** 2026-04-13

## Test Framework

**Runner:**
- pytest 8.0+ with pytest-asyncio 0.24+ for async test support (`pyproject.toml:24-25`)
- Config: `pyproject.toml` `[tool.pytest.ini_options]` (lines 150-154)
  - Testpaths: `["tests"]` — all tests in `tests/` directory
  - `asyncio_mode = "auto"` — pytest-asyncio auto-detects async tests
  - `filterwarnings = ["ignore::DeprecationWarning"]` — suppress deprecation noise
  - Coverage enabled by default with `--cov=backend --cov-report=term-missing --cov-report=xml`

**Assertion Library:**
- Built-in pytest assertions (no external library)
- Simple equality: `assert result == expected`
- Widget testing in Dart uses `flutter_test` with `expect(find.X, matcher)` pattern

**Run Commands:**
```bash
make test                 # Run all pytest tests with coverage
pytest tests/            # Run specific test file or directory
pytest tests/test_artifacts.py::test_artifact_download_pdf -v  # Single test
flutter test             # Run Flutter widget tests
```

## Test File Organization

**Location:**
- Backend: Co-located in `tests/` directory at project root (parallel to `backend/` package)
- Frontend: Co-located in `frontend/test/` directory (parallel to `frontend/lib/`)

**Naming:**
- Python: `test_*.py` prefix (e.g., `test_worker_tasks.py`, `test_artifacts.py`, `test_celery_dispatch.py`)
- Dart: `*_test.dart` suffix (e.g., `upload_screen_youtube_test.dart`, `main_nav_test.dart`, `theme_test.dart`)

**Structure:**
```
tests/
├── conftest.py          # Shared fixtures (client, isolated_blob_root, skip_real_transcription)
├── test_artifacts.py    # API artifact download tests
├── test_celery_dispatch.py  # Pipeline orchestration via Celery
├── test_stages.py       # Worker stage endpoint tests
├── test_worker_tasks.py # Individual task unit tests (ingest, humanize, engrave)
├── test_pipeline_config.py  # Pipeline variant execution plans
└── test_transcribe_*.py # Transcription-specific tests (stems, cleanup, etc.)

frontend/test/
├── main_nav_test.dart           # Navigation bar widget tests
├── upload_screen_*_test.dart    # Upload screen mode tests (YouTube, cover search)
├── progress_screen_test.dart    # Job progress display tests
├── result_screen_test.dart      # Result/artifact viewer tests
└── widgets/
    └── version_footer_test.dart # Version display widget tests
```

## Test Structure

**Suite Organization:**

**Python (pytest):**
```python
def test_single_function_behavior(client):
    """Test description as docstring."""
    job_id = _submit_midi_job(client)
    status = _wait_for_succeeded(client, job_id)
    assert status["status"] == "succeeded"
```

**Class-based test suites:**
```python
class TestIngestTask:
    def test_reads_blob_runs_service_writes_output(self, blob):
        from backend.workers.ingest import run as ingest_run
        # Test setup and assertions
```

**Async test patterns:**
```python
@pytest.mark.asyncio
async def test_full_pipeline_via_celery(runner):
    """Async test automatically awaited by pytest-asyncio."""
    result = await runner.run(
        job_id="test-celery-001",
        bundle=bundle,
        config=config,
    )
    assert result.pdf_uri
```

**Dart (flutter_test):**
```dart
void main() {
  group('Bottom navigation bar', () {
    testWidgets('shows three tabs: Home, Library, Profile', (tester) async {
      await tester.pumpWidget(_app());
      expect(find.text('Home'), findsOneWidget);
    });
  });
}
```

## Key Fixtures

**Backend (pytest):**

**`client` fixture (`tests/conftest.py:75-82`):**
- TestClient wrapper around FastAPI app inside `with` block to keep lifespan and ASGI portal alive
- Allows background asyncio tasks to progress between sync calls
- Used by all HTTP API tests (e.g., `test_artifacts.py`, `test_stages.py`)

**`isolated_blob_root` fixture (`tests/conftest.py:24-37`):**
- Auto-use fixture that runs before every test
- Fresh temporary directory for blob storage (`tmp_path / "blob"`)
- Clears DI singleton caches (`get_blob_store`, `get_runner`, `get_job_manager`) before and after
- Ensures test isolation — no shared state between tests
- Monkeypatch approach: `monkeypatch.setattr(settings, "blob_root", blob)`

**`skip_real_transcription` fixture (`tests/conftest.py:40-62`):**
- Auto-use fixture that disables Basic Pitch inference in all tests
- Monkeypatches `TranscribeService.run()` to an async stub that returns shape-correct `_stub_result()`
- Optionally writes fake MIDI bytes to blob store if `job_id` provided
- Rationale: Real transcription slow (cold-start ML) and flaky on fake audio; tests care about orchestration, not quality
- Implementation: `async def _fake_run(self, payload, *, job_id=None)` replaces real method

**`celery_eager_mode` fixture (`tests/conftest.py:65-72`):**
- Auto-use fixture that enables Celery eager mode for all tests
- `task_always_eager = True` — tasks execute in-process synchronously, no Redis needed
- `task_eager_propagates = True` — exceptions propagate immediately instead of async failure
- Resets after test via `yield` teardown

**`blob` fixture (e.g., `test_worker_tasks.py:18-21`):**
- Test-scoped fixture returning `LocalBlobStore(settings.blob_root)`
- Used by worker task tests to read/write blob payloads
- Depends on `isolated_blob_root` for fresh storage per test

**`runner` fixture (e.g., `test_celery_dispatch.py:30-31`):**
- Returns `PipelineRunner(blob_store=blob, celery_app=celery_app)`
- Used by pipeline orchestration tests to exercise full stage execution

**Frontend (Flutter):**
- No formal fixture framework; instead uses helper functions like `_mockApi()` and `_app()` (`frontend/test/upload_screen_youtube_test.dart:13-34`)
- Mock HTTP client via `http_testing.MockClient` that intercepts requests and returns canned responses

## Mocking

**Framework:**
- Python: `unittest.mock` via pytest's `monkeypatch` fixture for method replacement
- Dart: `http/testing.dart` `MockClient` for HTTP stubbing

**Patterns:**

**Python monkeypatch (real example):**
```python
# tests/conftest.py:52-62
async def _fake_run(self, payload, *, job_id=None):
    stub = transcribe_module._stub_result("real transcription disabled in tests")
    if self.blob_store is not None and job_id is not None:
        fake_midi = b"MThd\x00\x00\x00\x06\x00\x00\x00\x00\x00\x00"
        uri = self.blob_store.put_bytes(
            f"jobs/{job_id}/transcription/basic-pitch.mid", fake_midi,
        )
        stub = stub.model_copy(update={"transcription_midi_uri": uri})
    return stub

monkeypatch.setattr(transcribe_module.TranscribeService, "run", _fake_run)
```

**Dart MockClient (real example from `frontend/test/upload_screen_youtube_test.dart:13-30`):**
```dart
OhSheetApi _mockApi() {
  final mockClient = http_testing.MockClient((request) async {
    if (request.url.path == '/v1/jobs') {
      return http.Response(
        jsonEncode({
          'job_id': 'test-123',
          'status': 'queued',
        }),
        202,
        headers: {'content-type': 'application/json'},
      );
    }
    return http.Response('Not found', 404);
  });
  return OhSheetApi(client: mockClient);
}
```

**What to Mock:**
- External dependencies: Basic Pitch transcription, file I/O beyond test-isolated blob store
- HTTP calls in unit tests: Use MockClient to inject canned responses
- Long-running operations: Replaced with instant stubs

**What NOT to Mock:**
- Pydantic model serialization/deserialization — test with real models to catch schema bugs
- Blob store operations — use isolated temporary directory instead
- Celery dispatch — run in eager mode (in-process) instead
- Database operations — not applicable (no persistent DB in this project)

## Async Test Patterns

**Pytest-asyncio:**
```python
@pytest.mark.asyncio
async def test_pipeline_runs_async(runner):
    """Mark with @pytest.mark.asyncio; pytest-asyncio auto-awaits."""
    result = await runner.run(
        job_id="test-async-001",
        bundle=bundle,
        config=config,
    )
    assert result.pdf_uri
```

**Event collection pattern:**
```python
@pytest.mark.asyncio
async def test_full_pipeline_via_celery(runner):
    events: list[JobEvent] = []
    result = await runner.run(
        job_id="test-celery-001",
        bundle=bundle,
        config=config,
        on_event=events.append,  # Callback receives JobEvent stream
    )
    stage_names = [e.stage for e in events if e.type == "stage_completed"]
    assert stage_names == ["ingest", "transcribe", "arrange", "humanize", "engrave"]
```

**Dart async tests:**
```dart
testWidgets('submit button is enabled with a valid YouTube URL', (tester) async {
    await tester.pumpWidget(_app(_mockApi()));
    await tester.tap(find.text('YouTube'));
    await tester.pumpAndSettle();  // Wait for all animations/futures
    // Assertions
});
```

## Polling and Wait Patterns

**Backend (real example from `test_artifacts.py:7-16`):**
```python
def _wait_for_succeeded(client, job_id: str, deadline_sec: float = 5.0) -> dict:
    """Poll job status until succeeded/failed or timeout."""
    deadline = time.time() + deadline_sec
    status: dict | None = None
    while time.time() < deadline:
        status = client.get(f"/v1/jobs/{job_id}").json()
        if status["status"] in ("succeeded", "failed"):
            return status
        time.sleep(0.05)
    assert status is not None
    return status
```

**Pattern:** Used in integration tests where Celery tasks run in-process; tight polling loop (50ms interval) detects completion

**Dart: `pumpAndSettle()`**
```dart
await tester.pumpAndSettle();  // Waits for all animations and futures to complete
```

## Test Types

**Unit Tests:**
- Scope: Single function or service in isolation
- Example: `test_worker_tasks.py` — each task (ingest, humanize, engrave) tested independently with mocked dependencies
- Pattern: Set up input blob, call task, assert output blob

**Integration Tests:**
- Scope: Multiple stages working together via Celery dispatch
- Example: `test_celery_dispatch.py` — full pipeline execution (5 stages in sequence)
- Pattern: Create bundle, submit to runner, await completion, assert artifacts

**API/End-to-End Tests:**
- Scope: HTTP requests through FastAPI routes with real middleware
- Example: `test_artifacts.py` — exercise upload → job creation → completion → artifact download
- Pattern: Use `client` fixture to POST/GET, poll for job completion, verify response headers/content

**Widget Tests (Flutter):**
- Scope: Individual widgets or widget trees without running on device
- Example: `upload_screen_youtube_test.dart` — tests YouTube URL input mode, validation, button state
- Pattern: `pumpWidget()` to render, `tester.tap()` to interact, `find.*` to locate elements, `expect()` assertions
- Use MockClient for API calls to avoid network

**E2E Tests:**
- Not explicitly present; integration tests serve this role
- Could be added: Selenium/WebDriver on web build or mobile device testing

## Flutter-Specific Testing

**Test Organization:**
- Widget tests in `frontend/test/` with `_test.dart` suffix
- Helper functions at module top (`_app()`, `_mockApi()`) to reduce boilerplate
- Grouped tests via `group()` for related test cases (e.g., "YouTube segment button" group in `upload_screen_youtube_test.dart:37`)

**Test Structure:**
```dart
void main() {
  group('Feature group', () {
    testWidgets('description of behavior', (tester) async {
      await tester.pumpWidget(_app(mockApi));
      // Interact
      await tester.tap(find.text('Button'));
      // Assert
      expect(find.text('Expected'), findsOneWidget);
    });
  });
}
```

**Finders:** `find.text()`, `find.byKey()`, `find.byType()`, `find.descendant()` — locate widgets
**Interactions:** `tester.tap()`, `tester.enterText()` — simulate user input
**Assertions:** `expect(finder, matcher)` — matcher examples: `findsOneWidget`, `findsNothing`, `findsWidgets`, `isNotNull`
**Pump:** `tester.pump()` to rebuild once, `tester.pumpAndSettle()` to wait for animations/futures

**TDD Approach:**
Tests written before implementation (e.g., `frontend/test/upload_screen_youtube_test.dart:1-2` comment "Written FIRST, before implementation").

## Coverage

**Requirements:** 
- No explicit minimum enforced; coverage reports generated and uploaded to CI artifacts
- Command: `pytest --cov=backend --cov-report=html` generates HTML report in `htmlcov/`
- CI uploads `coverage.xml` as artifact (`.github/workflows/ci.yml:46-51`)

**View Coverage:**
```bash
pytest --cov=backend --cov-report=html
open htmlcov/index.html
```

## CI Integration

**Workflow:** `.github/workflows/ci.yml`

**Backend Tests:**
- Job: `backend-test` (lines 36-51)
- Runs on: `ubuntu-latest` with Python 3.13
- Steps: Install dev deps (`pip install -e ".[dev]"`), run pytest, upload coverage XML
- Triggers on: Push to qa/main, PRs to qa/main

**Backend Lint:**
- Job: `backend-lint` (lines 14-23)
- Runs: `ruff check backend tests`
- Enforces code style before tests run

**Backend Typecheck:**
- Job: `backend-typecheck` (lines 25-34)
- Runs: `mypy` with config from `pyproject.toml`
- Enforces type safety

**Frontend Lint:**
- Job: `frontend-lint` (lines 53-64)
- Runs: `flutter analyze` in `frontend/` directory
- Enforces Dart style

**CI Parallelization:**
- All jobs run in parallel; any failure blocks merge
- Concurrency group prevents redundant runs on force-push (`.github/workflows/ci.yml:9-11`)

## Error Testing

**Pattern (Python):**
```python
def test_stage_rejects_schema_version_mismatch(client):
    """Submit a stage request with schema version mismatch."""
    response = client.post(
        "/v1/stages/ingest",
        json={
            "payload_type": "InputBundle",
            "schema_version": "99.99.99",  # Wrong version
            "payload": {},
        },
    )
    assert response.status_code == 400
    assert "schema version" in response.json()["detail"]
```

**Pattern (Dart):**
```dart
testWidgets('shows error for invalid URL format', (tester) async {
    await tester.pumpWidget(_app(_mockApi()));
    await tester.tap(find.text('YouTube'));
    await tester.pumpAndSettle();
    
    // Enter invalid URL
    await tester.enterText(find.widgetWithText(TextField, 'YouTube URL'), 'not a url');
    await tester.pumpAndSettle();
    
    // Expect error state
    expect(find.text('Invalid YouTube URL'), findsOneWidget);
});
```

## Test Isolation

**Strategies:**
1. **Blob store isolation:** `isolated_blob_root` fixture creates fresh `tmp_path/blob` per test
2. **DI singleton clearing:** `deps.get_blob_store.cache_clear()`, `deps.get_runner.cache_clear()`, etc. before/after each test
3. **Celery eager mode:** Tasks execute in-process, no shared Redis state
4. **Monkeypatch resets:** pytest automatically restores original methods after each test
5. **No shared test data:** Each test creates its own input bundles, files, job IDs

## Test Naming

**Python:**
- Descriptive names starting with `test_` prefix
- Examples: `test_full_pipeline_via_celery`, `test_artifact_download_pdf`, `test_ingest_task`
- Docstrings explain what's being tested, not how

**Dart:**
- Descriptive names passed to `testWidgets()`
- Examples: `'shows three tabs: Home, Library, Profile'`, `'submit button is enabled with a valid YouTube URL'`
- Read as test report: "YouTube segment is visible in the SegmentedButton"

