# Architecture

**Analysis Date:** 2026-04-13

## Pattern Overview

**Overall:** Asynchronous multi-stage pipeline with Claim-Check blob storage and in-process job orchestration backed by Celery/Redis. The system implements a 5-7 stage transformation (Ingest → Transcribe → Arrange → Humanize → Engrave) where each stage reads its input from blob storage by URI, emits events via WebSocket, and writes results back to storage for the next stage.

**Key Characteristics:**
- Schema v3.0.0 Pydantic data contracts define all inter-stage communication
- URI-based Claim-Check pattern keeps heavy media (audio, MIDI, PDF) in blob storage
- FastAPI HTTP API with WebSocket pub/sub for live progress events
- Celery task dispatch for pipeline stage execution with optional Redis backend
- Per-stage services encapsulate business logic; all I/O mediated through BlobStore protocol
- Fallback stubs in transcription allow end-to-end testing without ML dependencies
- Frontend (Flutter) streams WebSocket events to render progress indicators

## Layers

**API (HTTP + WebSocket):**
- Purpose: REST and streaming interfaces for job submission, status polling, artifact download, and live event broadcast
- Location: `backend/api/routes/` (uploads.py, jobs.py, artifacts.py, ws.py, stages.py, health.py)
- Contains: FastAPI routers with request/response models, dependency injection
- Depends on: JobManager, BlobStore, Services
- Used by: Flutter frontend, external orchestrators, CLI clients

**Job Manager (In-Memory Job Registry):**
- Purpose: Tracks job state, manages asyncio task lifecycle, fans out JobEvents to WebSocket subscribers
- Location: `backend/jobs/manager.py`
- Contains: JobRecord dataclass (job_id, status, config, bundle, result, subscribers list), event replay on subscribe
- Depends on: PipelineRunner, contracts
- Used by: API routes, backend workers

**Pipeline Runner (Orchestration):**
- Purpose: Owns execution plan (which stages run in what order), dispatches each stage as a Celery task via URIs, waits for result URIs, deserializes outputs
- Location: `backend/jobs/runner.py`
- Contains: STEP_TO_TASK mapping, per-variant execution plans (full, audio_upload, midi_upload, sheet_only), stage coordination logic
- Depends on: BlobStore, Celery app, contracts
- Used by: JobManager

**Services (Pipeline Stage Logic):**
- Purpose: Implement individual pipeline stages as async functions with pure business logic
- Location: `backend/services/`
- Contains: IngestService, TranscribeService, ArrangeService, HumanizeService, EngraveService, and supporting modules (stem_separation, audio_preprocess, transcription_cleanup, melody_extraction, etc.)
- Depends on: InputBundle/contracts, BlobStore, external ML libraries (Basic Pitch, Demucs, music21, librosa)
- Used by: PipelineRunner (via Celery tasks in backend/workers/), stages API route

**Celery Workers (Task Queue):**
- Purpose: Execute pipeline stages asynchronously, serialize inputs/outputs via blob storage URIs
- Location: `backend/workers/` (monolith), `svc-decomposer/decomposer/`, `svc-assembler/assembler/`
- Contains: Task wrappers that call services and emit JobEvents
- Depends on: Services, BlobStore, contracts
- Used by: PipelineRunner (apply_async dispatch)

**BlobStore (Claim-Check Pattern):**
- Purpose: Abstraction for reading/writing heavy media files (audio, MIDI, MusicXML, PDF) — decouples pipeline from storage backend
- Location: `shared/shared/storage/base.py` (protocol), `shared/shared/storage/local.py` (LocalBlobStore implementation)
- Contains: Protocol methods (put_bytes, get_bytes, put_json, get_json); file:// URIs returned
- Depends on: Nothing (storage-agnostic)
- Used by: All services, API routes, Celery tasks

**Configuration:**
- Purpose: Load settings from environment variables (OHSHEET_* prefix), provide typed access throughout the app
- Location: `backend/config.py`
- Contains: Pydantic Settings with 100+ tunable knobs for ML/arrangement/humanize thresholds
- Depends on: Pydantic
- Used by: App initialization, all services

## Data Flow

**Full Pipeline (YouTube URL → Sheet Music):**

1. **Ingest** — Client posts title/YouTube URL to `POST /v1/jobs`
   - IngestService calls yt-dlp to download audio, probes metadata
   - Optional: cover_search finds a piano cover if prefer_clean_source=True
   - Emits InputBundle(audio_uri, metadata) to blob storage

2. **Transcribe** — TranscribeService (Basic Pitch + optional Demucs)
   - If Demucs enabled: stem_separation produces {vocals, bass, other, drums} stems
   - Per-stem or single-mix Basic Pitch inference → note_events
   - transcription_cleanup applies heuristics (merge gaps, remove ghosts, octave filtering)
   - melody_extraction / bass_extraction split notes into {MELODY, BASS, CHORDS} via Viterbi
   - Chord recognition via librosa chroma_cqt + HMM
   - Beat tracking (madmom/librosa), key detection, meter estimation
   - Outputs TranscriptionResult(midi_tracks, HarmonicAnalysis) to blob storage

3. **Arrange** — ArrangeService (two-hand piano reduction)
   - Split tracks by InstrumentRole and pitch: melody→RH, bass→LH, chords→both
   - Quantize onsets/durations to adaptive grid (1/16th default)
   - Voice assignment (≤2 voices per hand for MusicXML compliance)
   - Velocity normalization
   - Outputs PianoScore (beat-domain note list + chords + sections) to blob storage

4. **Humanize** — HumanizeService (performance expressiveness)
   - Micro-timing variations per note
   - Velocity dynamics (soft vs. loud)
   - Pedal marks, articulation
   - Outputs HumanizedPerformance to blob storage

5. **Engrave** — EngraveService (notation rendering)
   - music21 → MusicXML (score.musicxml)
   - LilyPond engine → PDF (sheet.pdf) via external binary or python-ly
   - pretty_midi → humanized MIDI file (humanized.mid)
   - Outputs EngravedOutput(pdf_uri, musicxml_uri, humanized_midi_uri) to blob storage

**Audio Upload Variant:**
- Client uploads MP3 → Ingest writes to blob and returns RemoteAudioFile
- POST /v1/jobs with audio field → PipelineRunner skips cover_search, runs Transcribe→Arrange→Humanize→Engrave

**MIDI Upload Variant:**
- Client uploads .mid → Ingest writes to blob and returns RemoteMidiFile
- POST /v1/jobs with midi field → PipelineRunner calls _bundle_to_transcription (pretty_midi parse) to skip Transcribe, runs Arrange→Humanize→Engrave

**State Management:**
- Job state lives in JobManager._jobs (in-memory dict keyed by job_id)
- Execution plan determined at submit time based on variant + input type
- Each stage emits JobEvent (stage_started, stage_progress, stage_completed, or stage_failed) → fanned out to all WebSocket subscribers
- Final result (EngravedOutput) stored on JobRecord.result
- Blob storage serves as the source of truth for all artifacts

## Key Abstractions

**Contracts (Pydantic Models):**
- Purpose: Define the shape of data at each pipeline boundary, enable schema versioning
- Examples: `InputBundle`, `TranscriptionResult`, `PianoScore`, `HumanizedPerformance`, `EngravedOutput`, `OrchestratorCommand`, `WorkerResponse`
- Pattern: Schema version embedded (v3.0.0 string), field validation via Pydantic, JSON round-trip via model_dump(mode="json")/model_validate()

**Service Async Interface:**
- Purpose: Encapsulate stage logic in stateless async functions
- Examples: `TranscribeService.run(bundle)`, `ArrangeService.run(result)`, `EngraveService.run(score)`
- Pattern: `async def run(input: InputType) -> OutputType`, all I/O via BlobStore, no side effects outside blob storage

**Celery Task Wrapper:**
- Purpose: Bridge the async service and the Celery task queue
- Examples: `backend/workers/ingest.py`, `svc-decomposer/decomposer/tasks.py`
- Pattern: Deserialize payload from blob URI, call service, serialize result to blob, return output URI

**JobEvent Streaming:**
- Purpose: Communicate pipeline progress to frontend in real-time
- Examples: `JobEvent(job_id, type="stage_completed", stage="transcribe", data=...)`
- Pattern: Emitted by PipelineRunner, fanned out by JobManager to asyncio Queues, sent to WebSocket clients

## Entry Points

**HTTP API Server:**
- Location: `backend/main.py` (uvicorn entry point)
- Triggers: `uvicorn backend.main:app --reload` or Docker container
- Responsibilities: Create FastAPI app, wire routers, set up CORS, mount static frontend assets, initialize blob storage

**Celery Task Execution:**
- Location: `backend/workers/` (monolith ingest/transcribe/arrange/humanize/engrave), `svc-decomposer/`, `svc-assembler/`
- Triggers: PipelineRunner.run() calls celery_app.tasks[name].apply_async(kwargs)
- Responsibilities: Deserialize OrchestratorCommand from Celery message, call per-stage Celery task, return output URI as job result

**Job Submission (POST /v1/jobs):**
- Location: `backend/api/routes/jobs.py` (create_job handler)
- Triggers: HTTP POST with JobCreateRequest
- Responsibilities: Validate inputs, build PipelineConfig + InputBundle, call JobManager.submit(), return JobSummary with job_id

**WebSocket Connection (WS /v1/jobs/{id}/ws):**
- Location: `backend/api/routes/ws.py` (job_events_ws handler)
- Triggers: WebSocket connection from frontend
- Responsibilities: Subscribe to job event stream via JobManager, replay history, stream events as JSON, close after terminal event

**Artifact Download (GET /v1/artifacts/{id}/{kind}):**
- Location: `backend/api/routes/artifacts.py` (download_artifact handler)
- Triggers: HTTP GET for pdf/musicxml/midi/transcription_midi
- Responsibilities: Look up job, resolve kind to URI attribute, read bytes via BlobStore, stream with correct Content-Type

## Error Handling

**Strategy:** Layered — services catch domain errors early, Celery tasks catch runtime errors, API routes catch everything and return HTTP errors.

**Patterns:**
- Services raise domain exceptions (e.g., IngestServiceError) with user-facing messages
- Celery task wrappers catch Exception and emit stage_failed event with error message
- JobManager._execute wraps PipelineRunner in try/except, emits job_failed event
- API routes return HTTPException(status_code, detail) for user errors; 5xx for system errors
- Stub fallbacks allow pipeline to continue even if a stage is unavailable (e.g., Basic Pitch not installed → _stub_transcription)

## Cross-Cutting Concerns

**Logging:** Uses Python logging module scoped to `backend.*` + service-specific loggers. Configuration via `OHSHEET_LOG_LEVEL` env var (default INFO). Uvicorn stdout captures logs for Docker/GCP Cloud Run.

**Validation:** Pydantic v2 validates all contract boundaries. Services validate their inputs before processing. API routes validate OrchestratorCommand schema_version before delegating to workers. Upload endpoints check file magic bytes (MIDI → MThd header).

**Authentication:** Not implemented in v1 — CORS wide-open for dev (`cors_origins=["*"]` by default). Production deployments should add JWT/API-key validation at the API layer.

**Concurrency:** In-process job execution uses asyncio for concurrent HTTP requests. Celery workers run in separate processes (Redis broker). WebSocket pub/sub fans out to multiple subscribers safely via asyncio Queue (bounded, 256 max, drops slow subscribers with warning).

**Storage Abstraction:** BlobStore protocol enables swapping backends without changing services. LocalBlobStore (current) writes to filesystem; S3BlobStore (future) would implement same protocol. file:// URIs are backend-agnostic.

---

*Architecture analysis: 2026-04-13*
