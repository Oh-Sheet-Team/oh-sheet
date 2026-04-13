# Codebase Structure

**Analysis Date:** 2026-04-13

## Directory Layout

```
oh-sheet/
├── backend/                    # FastAPI monolith + pipeline orchestration
│   ├── main.py                 # Uvicorn entry point, FastAPI app factory
│   ├── config.py               # Pydantic Settings (OHSHEET_* env vars)
│   ├── contracts.py            # Re-export from shared.contracts
│   ├── api/
│   │   ├── deps.py             # Dependency injection (blob store, runners, singletons)
│   │   └── routes/
│   │       ├── uploads.py       # POST /v1/uploads/{audio,midi}
│   │       ├── jobs.py          # POST /v1/jobs, GET /v1/jobs/{id}
│   │       ├── artifacts.py     # GET /v1/artifacts/{id}/{kind}
│   │       ├── ws.py            # WS /v1/jobs/{id}/ws
│   │       ├── stages.py        # POST /v1/stages/{name} (OrchestratorCommand)
│   │       └── health.py        # GET /v1/health
│   ├── jobs/
│   │   ├── manager.py           # JobManager + JobRecord (in-memory registry)
│   │   ├── runner.py            # PipelineRunner (Celery dispatch)
│   │   └── events.py            # JobEvent schema
│   ├── storage/
│   │   ├── base.py              # BlobStore protocol (re-export)
│   │   └── local.py             # LocalBlobStore (file:// backed)
│   ├── workers/
│   │   ├── celery_app.py        # Celery app instance (Redis broker)
│   │   ├── ingest.py            # @celery_app.task(name="ingest.run")
│   │   ├── transcribe.py         # @celery_app.task(name="transcribe.run")
│   │   ├── arrange.py            # @celery_app.task(name="arrange.run")
│   │   ├── condense.py           # @celery_app.task(name="condense.run")
│   │   ├── transform.py          # @celery_app.task(name="transform.run")
│   │   ├── humanize.py           # @celery_app.task(name="humanize.run")
│   │   └── engrave.py            # @celery_app.task(name="engrave.run")
│   └── services/
│       ├── ingest.py            # Download audio, probe metadata, clean-source search
│       ├── transcribe.py         # Basic Pitch (ONNX), stem separation, cleanup
│       ├── transcribe_pipeline_single.py
│       ├── transcribe_pipeline_stems.py
│       ├── transcribe_audio.py
│       ├── transcribe_inference.py
│       ├── transcribe_midi.py
│       ├── transcribe_result.py
│       ├── stem_separation.py    # Demucs source separation
│       ├── audio_preprocess.py   # HPSS + RMS normalization
│       ├── transcription_cleanup.py  # Heuristic post-processing
│       ├── melody_extraction.py  # Viterbi melody split
│       ├── bass_extraction.py    # Low-register bass identification
│       ├── chord_recognition.py  # librosa chroma_cqt + HMM
│       ├── crepe_melody.py       # CREPE F0 estimator (replaces BP on vocals)
│       ├── onset_refine.py       # Spectral onset snapping
│       ├── duration_refine.py    # CQT energy-based offset refinement
│       ├── key_estimation.py     # Key signature detection
│       ├── audio_timing.py       # Beat tracking (madmom/librosa)
│       ├── arrange.py            # Two-hand piano reduction
│       ├── arrange_simplify.py   # Post-arrange density reduction
│       ├── condense.py           # Stub / legacy condensing
│       ├── transform.py          # Stub / legacy transformation
│       ├── humanize.py           # Expressiveness: timing, velocity, pedal, articulation
│       ├── engrave.py            # music21 → MusicXML, LilyPond → PDF, pretty_midi → MIDI
│       ├── cover_search.py       # YouTube piano cover search (prefer_clean_source)
│       └── __init__.py
├── shared/                      # Contracts and storage protocol (used by backend + workers)
│   ├── pyproject.toml            # Shared package definition
│   └── shared/
│       ├── contracts.py          # Pydantic models (Schema v3.0.0)
│       └── storage/
│           ├── base.py           # BlobStore protocol
│           ├── local.py          # LocalBlobStore
│           └── __pycache__
├── svc-decomposer/              # Separate Celery service (transcription stage stub)
│   ├── pyproject.toml
│   ├── decomposer/
│   │   ├── celery_app.py         # Celery app for decomposer
│   │   ├── tasks.py              # @celery_app.task(name="decomposer.run")
│   │   └── __init__.py
│   └── tests/
│       ├── test_tasks.py
│       └── __init__.py
├── svc-assembler/               # Separate Celery service (engrave/assembly stub)
│   ├── pyproject.toml
│   ├── assembler/
│   │   ├── celery_app.py         # Celery app for assembler
│   │   ├── tasks.py              # @celery_app.task(name="assembler.run")
│   │   └── __init__.py
│   └── tests/
│       ├── test_tasks.py
│       └── __init__.py
├── frontend/                    # Flutter cross-platform app (Web + iOS + Android + macOS)
│   ├── pubspec.yaml              # Dart package manifest
│   ├── analysis_options.yaml     # Dart linter rules
│   ├── lib/
│   │   ├── main.dart             # App shell (home/library/profile bottom nav)
│   │   ├── config.dart           # API_BASE_URL config
│   │   ├── theme.dart            # Kawaii sticker design system (colors, fonts, animations)
│   │   ├── responsive.dart       # Breakpoint definitions
│   │   ├── screens/
│   │   │   ├── upload_screen.dart  # Audio/MIDI/YouTube input + title/artist
│   │   │   ├── progress_screen.dart  # Mascot animations + stage badges + WebSocket listener
│   │   │   └── result_screen.dart   # Sheet music viewer + piano roll + downloads
│   │   ├── api/
│   │   │   ├── client.dart       # OhSheetApi (HTTP multipart, job submission, polling)
│   │   │   ├── ws.dart           # WebSocket client (live events)
│   │   │   └── models.dart       # Dart dataclasses (RemoteAudioFile, JobSummary, etc.)
│   │   └── widgets/
│   │       ├── sheet_music_viewer.dart  # OSMD + Tone.js notation renderer (stub for web)
│   │       ├── sheet_music_viewer_web.dart
│   │       ├── piano_roll.dart   # Custom canvas piano roll visualization (stub)
│   │       ├── piano_roll_web.dart
│   │       ├── pdf_preview.dart  # PDF.js viewer (stub)
│   │       ├── pdf_preview_web.dart
│   │       ├── midi_player.dart  # Tone.js MIDI playback (stub)
│   │       ├── midi_player_web.dart
│   │       ├── sticker_widgets.dart  # Kawaii UI components (buttons, cards, etc.)
│   │       └── version_footer.dart   # Version display + pubspec parsing
│   ├── assets/
│   │   └── mascots/              # SVG mascot expressions (ingest, transcribe, arrange, etc.)
│   ├── web/                      # Flutter web platform scaffolding
│   │   ├── index.html
│   │   └── icons/
│   ├── test/                     # Flutter widget tests
│   │   └── widgets/
│   └── build/                    # Build output (web, ios, android, etc.)
├── tests/                        # Backend pytest suite
│   ├── conftest.py               # Fixtures (client, isolated_blob_root, skip_real_transcription)
│   ├── fixtures/
│   │   └── scores/               # Sample MusicXML, MIDI, audio files
│   ├── test_uploads.py           # POST /v1/uploads/{audio,midi} tests
│   ├── test_jobs.py              # Job submission, polling, WebSocket tests
│   ├── test_artifacts.py         # Artifact download tests
│   ├── test_stages.py            # OrchestratorCommand worker tests
│   ├── test_transcribe.py        # TranscribeService, melody_extraction, etc.
│   ├── test_arrange.py           # ArrangeService tests
│   ├── test_engrave_quality.py   # MusicXML validation (lxml xpath checks)
│   └── ... (more test modules)
├── scripts/
│   ├── eval_transcription.py     # Offline eval harness (mir_eval scoring)
│   └── bench_preprocess.py       # Performance benchmarking
├── eval/
│   └── fixtures/
│       └── clean_midi/           # 25-file baseline for transcription eval
├── docs/
│   ├── wireframes/               # UI mockups
│   ├── superpowers/
│   │   ├── specs/                # Feature specifications
│   │   └── plans/                # Implementation plans
│   └── engrave-improvement-plan.md
├── e2e/                          # End-to-end tests (Playwright)
├── .github/
│   └── workflows/
│       ├── ci.yml                # Lint, typecheck, pytest on PR
│       └── deploy.yml            # Docker build + GCP Cloud Run push
├── .planning/
│   └── codebase/                 # GSD codebase analysis docs (this repo)
├── pyproject.toml                # Backend package definition + extras
├── Makefile                      # Development commands
├── Dockerfile                    # Multi-stage: Flutter web + Python runtime
├── docker-compose.yml            # Local dev: Redis + backend API
├── docker-compose.prod.yml       # Production GCP Cloud Run setup
├── Caddyfile                     # Reverse proxy config
├── .env                          # (Git-ignored) local development config
├── README.md                     # Project overview
├── CLAUDE.md                     # This file
├── LICENSE.txt                   # Proprietary
└── uv.lock                       # Python dependency lock
```

## Directory Purposes

**`backend/`:**
- Purpose: FastAPI HTTP API + Celery task dispatch + orchestration logic
- Contains: Service implementations, API routes, job manager, storage layer, Celery workers
- Key files: `main.py` (entry), `config.py` (settings), `api/deps.py` (DI)

**`backend/api/`:**
- Purpose: HTTP and WebSocket endpoints
- Contains: REST routes for uploads, jobs, artifacts; WebSocket for live events; OrchestratorCommand worker endpoints
- Key files: `routes/` (all endpoint handlers), `deps.py` (singleton injection)

**`backend/jobs/`:**
- Purpose: Job lifecycle management and pipeline orchestration
- Contains: JobManager (registry + pub/sub), PipelineRunner (Celery dispatch), JobEvent schema
- Key files: `manager.py`, `runner.py`, `events.py`

**`backend/storage/`:**
- Purpose: Blob storage abstraction (Claim-Check pattern)
- Contains: BlobStore protocol, LocalBlobStore implementation
- Key files: `base.py`, `local.py`

**`backend/workers/`:**
- Purpose: Celery task wrappers that bridge services and the task queue
- Contains: One .py file per stage; each defines a Celery task that deserializes input from blob URI, calls the service, serializes output
- Key files: `celery_app.py` (Celery instance), `ingest.py` through `engrave.py` (stage tasks)

**`backend/services/`:**
- Purpose: Core business logic for each pipeline stage
- Contains: Pure async functions (IngestService, TranscribeService, etc.) that read from contracts, process, write to contracts
- Key files: Service modules named after their stage (ingest.py, transcribe.py, arrange.py, humanize.py, engrave.py) plus supporting modules for transcription (stem_separation, transcription_cleanup, melody_extraction, etc.)

**`shared/`:**
- Purpose: Shared packages imported by backend, workers, and (conceptually) external orchestrators
- Contains: Pydantic contracts (Schema v3.0.0), BlobStore protocol, LocalBlobStore implementation
- Key files: `shared/contracts.py` (all data models), `shared/storage/base.py` (BlobStore protocol)

**`svc-decomposer/` and `svc-assembler/`:**
- Purpose: Separate Celery services for transcription (decomposer) and engraving (assembler); allow horizontal scaling of heavy stages
- Contains: Minimal Celery app + task definition + stub implementations
- Key files: `*/celery_app.py`, `*/tasks.py`

**`frontend/`:**
- Purpose: Cross-platform Flutter client (Web, iOS, Android, macOS)
- Contains: Dart UI screens, API client, design system, widgets
- Key files: `main.dart` (app shell), `screens/` (3-screen flow), `api/client.dart` (HTTP/WS), `theme.dart` (design system)

**`tests/`:**
- Purpose: Backend pytest test suite
- Contains: HTTP integration tests, service unit tests, contract validation tests
- Key files: `conftest.py` (fixtures), test files named `test_*.py` (one per module)

## Key File Locations

**Entry Points:**
- `backend/main.py`: Uvicorn HTTP server (FastAPI app factory + lifespan hook)
- `frontend/lib/main.dart`: Flutter app shell
- `backend/workers/celery_app.py`: Celery worker initialization
- `svc-decomposer/decomposer/celery_app.py`: Decomposer worker initialization
- `svc-assembler/assembler/celery_app.py`: Assembler worker initialization

**Configuration:**
- `backend/config.py`: Settings class (100+ tunable knobs with OHSHEET_* env prefix)
- `frontend/lib/config.dart`: API base URL configuration
- `.env`: Local development environment (git-ignored)
- `docker-compose.yml`: Local services (Redis, API)

**Core Logic:**
- `backend/jobs/runner.py`: Pipeline execution plan and Celery dispatch
- `backend/jobs/manager.py`: Job state registry and WebSocket pub/sub
- `backend/services/transcribe.py`: Audio-to-MIDI transcription orchestration
- `backend/services/arrange.py`: Two-hand piano reduction
- `backend/services/humanize.py`: Expressiveness post-processing
- `backend/services/engrave.py`: MusicXML and PDF rendering
- `shared/shared/contracts.py`: All Pydantic data models (Schema v3.0.0)

**Testing:**
- `tests/conftest.py`: Pytest fixtures (client, blob store, skip transcription)
- `tests/test_transcribe.py`: TranscribeService tests
- `tests/test_arrange.py`: ArrangeService tests
- `tests/test_engrave_quality.py`: MusicXML lxml validation
- `scripts/eval_transcription.py`: Offline transcription accuracy eval

**Build & Deployment:**
- `Dockerfile`: Multi-stage build (Flutter web + Python backend)
- `docker-compose.yml`: Local Redis + API for development
- `.github/workflows/ci.yml`: GitHub Actions lint/test CI
- `.github/workflows/deploy.yml`: GCP Cloud Run deployment trigger
- `Makefile`: Development shortcuts (make backend, make frontend, make test)

## Naming Conventions

**Files:**
- Services: `{stage_name}.py` (ingest.py, transcribe.py, arrange.py, humanize.py, engrave.py)
- API routes: `{feature_name}.py` (uploads.py, jobs.py, artifacts.py, ws.py, stages.py)
- Tests: `test_{module_name}.py` (test_transcribe.py, test_arrange.py)
- Workers: `{stage_name}.py` in `backend/workers/` (one Celery task per file)
- Celery tasks: Named as `"{stage}.run"` (ingest.run, transcribe.run, etc.)

**Functions:**
- Services: `async def run(input: Contract) -> Contract` (e.g., `async def run(bundle: InputBundle) -> TranscriptionResult`)
- Celery tasks: `@celery_app.task(name="stage.run")` decorator
- API routes: Verb-noun pattern: `upload_audio()`, `create_job()`, `download_artifact()`, `get_job()`
- Helpers (private): Prefix with `_` (e.g., `_stub_transcription()`, `_get_blob_store()`)

**Types/Classes:**
- PascalCase for contracts (InputBundle, TranscriptionResult, HarmonicAnalysis)
- PascalCase for enums (InstrumentRole, SectionLabel, PipelineVariant, JobStatus)
- PascalCase for services (IngestService, TranscribeService) — though mostly just module-level functions
- snake_case for function names, camelCase for Dart function names

**Variables:**
- snake_case for Python variables (job_id, tempo_map, midi_tracks)
- camelCase for Dart variables (jobId, tempoMap, midiTracks)
- UPPER_SNAKE for constants (QUANT_GRID=0.25, SPLIT_PITCH=60, SCHEMA_VERSION="3.0.0")

## Where to Add New Code

**New Feature (UI Screen):**
- Primary code: `frontend/lib/screens/{feature}_screen.dart`
- Tests: `frontend/test/widgets/test_{feature}_screen.dart`
- Styling: Update `frontend/lib/theme.dart` if needed
- API client changes: `frontend/lib/api/client.dart` (add HTTP method or WebSocket handler)

**New Service/Backend Logic:**
- Implementation: `backend/services/{feature}.py` (async function(s) + supporting helpers)
- Contract: Add new input/output models to `shared/shared/contracts.py`
- Celery task: `backend/workers/{feature}.py` (wrapper that calls service)
- Tests: `tests/test_{feature}.py` (service unit tests + integration tests)

**New API Endpoint:**
- Route: `backend/api/routes/{feature}.py` (FastAPI router with endpoints)
- Integration: Import router in `backend/main.py` and call `app.include_router()`
- Tests: `tests/test_{feature}.py` (HTTP tests using httpx.AsyncClient)

**Configuration Knob:**
- Add field to `Settings` class in `backend/config.py`
- Document the knob with a docstring explaining semantics and impact
- Reference the knob in services as `from backend.config import settings; settings.knob_name`
- For environment-based setting: `OHSHEET_{KNOB_NAME}` automatically bound via Pydantic

**Data Migration (Contract Change):**
- Update contracts in `shared/shared/contracts.py`
- Bump `SCHEMA_VERSION` string
- Update all services that touch the contract
- Update worker tasks in `backend/workers/` and separate services (`svc-*/`)
- Add migration logic in PipelineRunner if backward compatibility needed

**New Database/Persistence:**
- If needed (not yet implemented): Create `backend/storage/{backend_name}.py` implementing BlobStore protocol
- Update DI in `backend/api/deps.py` to instantiate new store
- No service changes needed — they use protocol, not concrete type

**Utilities/Helpers:**
- Shared across services: `backend/services/` (e.g., audio_preprocess.py, transcription_cleanup.py)
- Shared cross-platform: `shared/` package (e.g., contracts, storage)
- Tests: `tests/fixtures/` for sample data, `tests/conftest.py` for reusable fixtures

## Special Directories

**`blob/`:**
- Purpose: Local blob storage for development (file:// URI backend)
- Generated: Yes (created by `LocalBlobStore` on app startup)
- Committed: No (git-ignored)
- Contents: Uploaded audio, MIDI, and all intermediate/final artifacts (PDFs, MusicXML, MIDI)

**`build/` and `.dart_tool/`:**
- Purpose: Flutter build artifacts
- Generated: Yes (by `flutter run` and `flutter build`)
- Committed: No (git-ignored)
- Clean with `make clean`

**`eval/fixtures/clean_midi/`:**
- Purpose: Ground-truth MIDI files for transcription accuracy evaluation
- Generated: No (manually curated)
- Committed: Yes
- Used by: `scripts/eval_transcription.py` (offline eval harness)

**`.planning/codebase/`:**
- Purpose: GSD codebase analysis documents (architecture, structure, conventions, etc.)
- Generated: Yes (by /gsd-map-codebase orchestrator)
- Committed: Yes
- Used by: /gsd-plan-phase and /gsd-execute-phase orchestrators

**`test_files/` and `eval/`:**
- Purpose: Sample audio/MIDI for manual testing and evaluation
- Generated: No (committed fixtures)
- Committed: Yes
- Contents: Golden.mid, sample audio files, eval fixtures

**`.github/workflows/`:**
- Purpose: GitHub Actions CI/CD
- Generated: No (committed)
- Files: `ci.yml` (lint/test on PR), `deploy.yml` (manual GCP deployment)

**`.venv/`:**
- Purpose: Python virtual environment for development
- Generated: Yes (by `pip install`)
- Committed: No (git-ignored)
- Create with `python -m venv .venv && source .venv/bin/activate`

---

*Structure analysis: 2026-04-13*
