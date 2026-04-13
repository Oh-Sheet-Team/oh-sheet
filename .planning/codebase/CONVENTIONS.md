# Coding Conventions

**Analysis Date:** 2026-04-13

## Naming Patterns

**Files:**
- Python modules use `snake_case.py` (e.g., `arrange.py`, `condense.py`, `audio_preprocess.py`)
- Dart files use `snake_case.dart` (e.g., `upload_screen.dart`, `sticker_widgets.dart`)
- Test files suffixed with `_test.dart` (Flutter) or named `test_*.py` (pytest)

**Functions:**
- Python: `snake_case` for all functions (e.g., `_quantize()`, `_merge_tracks_chronologically()`, `_gm_program_to_role()`)
- Private helpers prefixed with single underscore (e.g., `_parse_grid_candidates()` in `backend/services/arrange.py:69`)
- Dart: `camelCase` for public functions/methods, `_camelCase` for private (e.g., `_app()`, `_mockApi()` in `frontend/test/upload_screen_youtube_test.dart`)

**Variables:**
- Python: `snake_case` (e.g., `beat_onsets`, `min_notes`, `voice_ends` in `backend/services/condense.py`)
- Dart: `camelCase` (e.g., `mockClient`, `onTap` in `frontend/lib/widgets/sticker_widgets.dart`)

**Types and Classes:**
- Python: `PascalCase` for classes (e.g., `InputBundle`, `TranscriptionResult`, `PianoScore` in `backend/contracts.py`)
- Pydantic models inherit from `BaseModel` or `BaseSettings` (e.g., `Settings` in `backend/config.py:17`)
- Dart: `PascalCase` (e.g., `OhSheetApi`, `OhSheetSticker`, `OhSheetApp`)
- Module-level constant classes prefixed with underscore for style-only classes (e.g., `abstract final class OhSheetStickerStyle` in `frontend/lib/widgets/sticker_widgets.dart:11`)

**Constants:**
- Python: `UPPER_SNAKE_CASE` (e.g., `QUANT_GRID = 0.25`, `SPLIT_PITCH = 60` in `backend/services/arrange.py:38-39`)
- Internal tuning constants documented inline with rationale (e.g., Basic Pitch threshold comments in `backend/config.py:66-70`)

## Code Style

**Formatting:**
- Python: Ruff formatter (implicit via `ruff check`)
- Line length: 120 characters (`tool.ruff` in `pyproject.toml:158`)
- Imports sorted by Ruff's import plugin (`tool.ruff.lint` select "I" in `pyproject.toml:161`)
- Dart: Flutter lints with `analysis_options.yaml` including `package:flutter_lints/flutter.yaml` but disabling `avoid_print: true` to allow logging

**Linting:**
- Backend: Ruff with rules enabled: `E`, `F`, `I`, `W`, `UP`, `B`, `SIM` (`pyproject.toml:161`)
  - Disabled: `UP042` (StrEnum), `SIM105` (contextlib.suppress), `SIM108` (ternary), `SIM115` (tempfiles), `E731` (lambda), `B007` (loop var), `B905` (zip strict)
  - Re-exports allowed in `backend/contracts.py` (F401 ignored per-file)
- Frontend: `flutter analyze` via CI (`.github/workflows/ci.yml:63`)
- Type checking: `mypy` with `python_version = "3.11"` (`pyproject.toml:176`)
  - `disallow_untyped_defs = false` — relaxed, allows legacy untyped code
  - Custom overrides for `backend.services.engrave` disabling `union-attr` and `arg-type` errors (`pyproject.toml:183-185`)

## Import Organization

**Order:**
1. `from __future__ import annotations` (top of all Python modules for forward references)
2. Standard library imports (`asyncio`, `logging`, `pathlib`, etc.)
3. Third-party imports (`fastapi`, `pydantic`, `celery`, `pretty_midi`, `music21`)
4. Local imports (`from backend.config`, `from backend.contracts`, etc.)

**Path Aliases:**
- No absolute path aliases configured; imports use relative module paths
- Pydantic models re-exported through `backend/contracts.py` (lines 1-41) for centralized access
- Dart imports use package-relative format (e.g., `import 'package:ohsheet_app/api/client.dart'` in `frontend/test/upload_screen_youtube_test.dart:9`)

## Error Handling

**Patterns:**
- HTTP layer: Raises `HTTPException(status_code=..., detail=...)` for validation and business logic errors
  - Example in `backend/api/routes/jobs.py:90-93` — "Provide audio OR midi, not both."
- Service layer: Fallback to stub results when external dependencies fail
  - `TranscribeService.run()` in `backend/services/transcribe.py` catches exceptions and returns `_stub_result(reason)` (`tests/conftest.py:52-60`)
  - Pipeline stages return shape-correct contracts even on failure to keep downstream stages running
- Worker tasks: Exception logging with `log.exception()` in `backend/api/routes/stages.py` (catches BLE001 boundary exceptions)
- WebSocket cleanup: Try/except around disconnect handling in `backend/api/routes/ws.py` (tries to close connection, ignores errors)

## Logging

**Framework:** Python `logging` module (standard library)

**Patterns:**
- Each module creates a logger at module level: `log = logging.getLogger(__name__)` (e.g., `backend/services/arrange.py:36`, `backend/jobs/runner.py:35`)
- Structured logging with interpolation: `log.info("pipeline finished job_id=%s", job_id)` in `backend/jobs/runner.py`
- Log level configured via `OHSHEET_LOG_LEVEL` environment variable (default "INFO") in `backend/config.py:39`
- Root logger scoped to `backend` package only to avoid library noise (`backend/main.py` setup function)
- Error logging uses `log.exception()` to capture stack traces (`backend/api/routes/stages.py`)
- Warnings for slow operations: `log.warning("dropping slow subscriber for job %s", record.job_id)` in `backend/jobs/manager.py`

**Dart:** Uses `print()` for debugging (allowed by linter config `avoid_print: false` in `frontend/analysis_options.yaml:5`)

## Comments

**When to Comment:**
- Module docstrings explain contract and approach for complex services
  - Example: `backend/services/arrange.py` (lines 1-11) explains hand assignment, quantization, voice assignment steps
  - Example: `backend/services/condense.py` (lines 1-16) references parallel logic in temp1/arrange.py
- Function docstrings for public APIs and complex behavior
  - Example: `frontend/lib/api/client.dart:60-69` explains `preferCleanSource` parameter semantics
- Inline comments for non-obvious heuristics and tuning decisions
  - Example: Basic Pitch threshold tuning comments in `backend/config.py:66-78` (why vocals need higher threshold)
  - Example: Voice cap rationale in `backend/services/arrange.py:40-46` explaining 2-voice limit for OSMD/VexFlow compatibility
- Configuration rationale documented inline (especially for tuning constants)
  - Example: `backend/config.py:42-103` extensively documents preprocessing and threshold defaults with benchmark results

**JSDoc/TSDoc:**
- Python uses standard docstrings (triple-quoted strings)
- Dart uses documentation comments (`/// ` prefix) for public classes and methods
  - Example: `frontend/lib/widgets/sticker_widgets.dart:32` "White panel with thick outline + sticker shadow"
  - Example: `frontend/lib/api/client.dart:60-69` documents parameter intent for backend compatibility

## Function Design

**Size:** 
- Helper functions kept small and composable (10-30 lines typical)
- Example: `_quantize()` in `backend/services/arrange.py:61-62` is 2 lines
- Example: `_assign_voices()` in `backend/services/condense.py:106-132` is 27 lines with complex logic

**Parameters:**
- Positional for required arguments; keyword-only for optional configuration
- Type hints required on all function signatures in new code (mypy configured but lenient)
- Example: `_estimate_best_grid(beat_onsets: list[float], *, candidates: list[float] | None = None, min_notes: int | None = None)` in `backend/services/arrange.py:74-78` uses `*` to enforce keyword args for optional params

**Return Values:**
- Explicit return types on all functions (PEP 484)
- Tuple returns for multiple related values (e.g., `_split_hands()` returns `tuple[list[...], list[...]]` in `backend/services/condense.py:96-103`)
- Optional types used liberally (`Type | None`) per Python 3.10+ union syntax

## Module Design

**Exports:**
- Services expose a `.run()` async function taking a payload and returning result
  - Example: `backend/workers/ingest.py` exports `async def run(job_id: str, payload_uri: str) -> str`
  - All worker functions follow claim-check pattern: read input URI, run logic, write output URI, return URI
- Contracts re-exported centrally in `backend/contracts.py` for single import source
- Private helpers prefixed with underscore; public functions exposed without prefix

**Barrel Files:**
- Minimal barrel exports; contracts module (`backend/contracts.py`) re-exports Pydantic schemas from `shared/contracts.py`
- No aggregated service imports; services imported by specific route handlers

## Async Patterns

**Backend:**
- Services are async-first: all `run()` functions are `async def` and use `await`
- Example: `TranscribeService.run()` in tests is monkeypatched to an async function (`tests/conftest.py:52`)
- API routes async: `async def create_job()` in `backend/api/routes/jobs.py:83`
- Asyncio used for parallel operations within a service (e.g., stem separation runs in parallel via `asyncio.gather()`)
- Celery tasks dispatched asynchronously but awaited in runner via `apply_async()` and result polling

**Frontend:**
- Dart futures and async/await used for HTTP calls
- Example: `uploadAudio()` returns `Future<RemoteAudioFile>` in `frontend/lib/api/client.dart:30`
- Proper resource cleanup: `OhSheetApi.close()` called in `dispose()` (`frontend/lib/main.dart:26`)

## Pydantic Type Safety

**Patterns:**
- All data contracts inherit from Pydantic `BaseModel` (e.g., `InputBundle`, `PianoScore`, `TranscriptionResult`)
- Validators used for configuration constraints via `@field_validator` (e.g., `backend/config.py` validates threshold ranges 0.0-1.0)
- Strict mode enabled for schema validation — mismatched types rejected at deserialization
- `model_dump(mode="json")` explicitly called to serialize for blob storage (`backend/workers/ingest.py:32-34`)
- `model_copy(update={...})` used for functional updates (e.g., `tests/conftest.py:59`)

## Dependency Injection

**Pattern:**
- FastAPI dependencies via `Depends()` with singleton fixtures in `backend/api/deps.py`
- Example: `get_blob_store()` returns cached singleton with `@lru_cache()` decorator
- Tests clear dependency caches in `isolated_blob_root` fixture (`tests/conftest.py:31-37`)

