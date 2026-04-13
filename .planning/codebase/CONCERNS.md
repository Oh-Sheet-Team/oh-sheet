# Codebase Concerns

**Analysis Date:** 2026-04-13

## Stub Implementations (Critical Path Blocking)

**Decomposer transcription service:**
- Issue: `/Users/jackjiang/GitHub/oh-sheet/svc-decomposer/decomposer/tasks.py:32-60` returns hardcoded 4-note stub with 0.3 confidence instead of real Demucs+Basic-Pitch transcription
- Files: `svc-decomposer/decomposer/tasks.py`
- Impact: When decomposer service is invoked (not yet integrated), produces placeholder output; jobs will run to completion with incorrect transcription data
- Fix approach: Implement real transcription pipeline using Demucs stem separation + per-stem Basic Pitch inference matching `backend/services/transcribe_pipeline_stems.py` logic

**Assembler arrangement service:**
- Issue: `/Users/jackjiang/GitHub/oh-sheet/svc-assembler/assembler/tasks.py:29-54` returns hardcoded 1 RH + 1 LH note stub
- Files: `svc-assembler/assembler/tasks.py`
- Impact: Arrangement stage produces minimal placeholder score instead of actual hand assignment/quantization; jobs complete but result is unplayable
- Fix approach: Port arrangement logic from `backend/services/arrange.py` into the assembler service; currently only `backend/` has real implementation

**Stub fallbacks in pipeline runner:**
- Issue: `backend/jobs/runner.py:63-88` `_stub_transcription()` and `backend/jobs/runner.py:91-191` `_bundle_to_transcription()` fallback to minimal correct shapes when pretty_midi parsing fails
- Files: `backend/jobs/runner.py`
- Impact: MIDI upload variant jobs can silently succeed with stub data if pretty_midi is missing or file is corrupted; no explicit warning to client
- Fix approach: Raise explicit error instead of stubbing; add validation in uploads route to reject malformed MIDI early

---

## State Persistence & Recovery Issues

**In-memory job state is process-scoped:**
- Issue: `backend/jobs/manager.py` entire JobManager class stores state in `self._jobs: dict[str, JobRecord]` — single-process assumption
- Files: `backend/jobs/manager.py:1-6`, `backend/api/deps.py:32-34` uses `@lru_cache` singleton
- Impact: On server restart, all in-flight jobs are lost; no resumption; clients polling a restarted instance see 404 for previously submitted jobs
- Deployment risk: Cloud Run cold starts or container restarts = job history wiped; users never know what happened
- Fix approach: Persist JobRecord to Redis/Postgres; load on startup; emit `job_resumed` event for reconnecting clients

**WebSocket late-subscriber event replay is in-memory:**
- Issue: `backend/jobs/manager.py:136-137` replay comes from `record.events` list which exists only while job is in `_jobs` dict
- Files: `backend/jobs/manager.py:129-139`
- Impact: If a client disconnects and reconnects after server restart, it gets empty event stream instead of seeing what happened
- Fix approach: Persist events to blob store as JSON-Lines file; replay from disk on reconnect

**No cross-process job coordination:**
- Issue: Multiple orchestrator instances would each have their own `_jobs` dict with no synchronization
- Impact: Horizontal scaling is broken — load balancer could route job-status queries to a different instance that has no record of that job
- Fix approach: Move JobManager to Redis Streams or Postgres LISTEN-NOTIFY before adding second orchestrator instance

---

## Untrusted Input Handling & Security

**YouTube URL validation is minimal:**
- Issue: `backend/services/ingest.py:47-66` `extract_youtube_id()` does URL parsing and regex on user-supplied string; `_download_youtube_sync:69-138` passes to yt-dlp
- Files: `backend/services/ingest.py`
- Impact: Malicious YouTube URLs could exploit yt-dlp vulnerabilities; no download size limit, no timeout enforcement beyond socket_timeout=30
- Risk: Denial of service — user uploads 10-hour livestream URL, yt-dlp downloads full stream, exhausts disk/memory
- Fix approach: Add max-download-size limit before yt-dlp; enforce wall-time timeout with `asyncio.wait_for()`; validate URL hostname against allowlist

**Upload filename handling:**
- Issue: `backend/api/routes/uploads.py:33-34` `_ext()` splits on last dot but doesn't validate filename length or characters
- Files: `backend/api/routes/uploads.py`
- Impact: Long/malicious filenames could be logged verbatim in error messages; type: ignore on line 56 bypasses media-type validation
- Risk: XSS in error responses if filename is echoed to frontend; filename in form field could be crafted for filesystem attacks
- Fix approach: Sanitize filenames; reject names >255 chars; whitelist safe characters; don't trust user-provided filename, use digest instead

**Blob store path traversal defense is string-based:**
- Issue: `shared/shared/storage/local.py:23-27` checks for `".."` in `Path(normalized).parts` after `lstrip("/")`
- Files: `shared/shared/storage/local.py`
- Impact: Defense relies on Path.parts behavior which is OS-specific; Windows backslashes might bypass check on Linux; no validation of absolute paths
- Risk: Malicious blob key like `jobs/../../etc/passwd` could escape blob root if parsing is inconsistent
- Fix approach: Use `path.resolve().relative_to(root)` and catch ValueError; explicit check that resolved path is inside root

**No upload size limits:**
- Issue: `backend/api/routes/uploads.py:49` and `44` just call `file.read()` without checking Content-Length or streaming
- Files: `backend/api/routes/uploads.py`
- Impact: Attacker uploads 100GB file; memory exhausted; Denial of Service
- Fix approach: Check `request.headers.get("content-length")` before reading; stream to disk in chunks; reject if >1GB

---

## Performance Bottlenecks & Latency

**Basic Pitch inference is synchronous and single-threaded:**
- Issue: `backend/services/transcribe.py:52-120` calls Basic Pitch inside `asyncio.to_thread()` — blocks one thread per job
- Files: `backend/services/transcribe.py`, `backend/workers/transcribe.py`
- Impact: On a 4-core machine, only ~4 concurrent transcriptions before queueing; Basic Pitch can take 30-60s per 3-minute song
- Scaling path: Celery worker pool size multiplied by job duration = long queue times for users
- Fix approach: Use Basic Pitch's built-in parallel inference (batch mode) or switch to streaming inference if available

**Demucs stem separation adds 2-10x latency:**
- Issue: `backend/config.py:267` Demucs is enabled by default; `backend/services/stem_separation.py` adds ~80MB model load + 0.2-5x real-time processing
- Files: `backend/config.py:245-261`, `backend/services/stem_separation.py`
- Impact: User perceives 2-10x slower pipeline; commercial deployments risk hitting Cloud Run 3600s timeout on long songs
- Fix approach: Demucs is configurable but default-on is aggressive; consider making opt-in via per-job flag; or implement streaming stem separation

**LilyPond PDF rendering is subprocess-based and single-threaded:**
- Issue: `backend/services/engrave.py:5` "LilyPond (preferred)" is called via subprocess.run() without parallelism; fallback to stub PDF is 60 bytes
- Files: `backend/services/engrave.py`
- Impact: LilyPond on a large score takes 10-30s; if lilypond is not installed, users get a 60-byte stub PDF with no warning
- Fix approach: Pre-check lilypond availability at startup; use thread pool for concurrent LilyPond calls; implement real PDF fallback (MuseScore CLI or reportlab)

**Config file is 506 lines with 100+ tunable parameters:**
- Issue: `backend/config.py:1-507` Pydantic settings with 100+ fields; many interdependent (cleanup_*, arrange_*, demucs_*, crepe_*, key_detection_*, etc.)
- Files: `backend/config.py`
- Impact: Tuning becomes error-prone; no documentation of safe ranges; a single bad OHSHEET_* env var can crash the pipeline or produce wrong output
- Fix approach: Split into functional groups (transcription.py, arrangement.py, etc.); add `@field_validator` for cross-field constraints; document safe ranges

---

## Error Recovery & Failure Modes

**Pipeline stage failures are not isolated:**
- Issue: `backend/jobs/runner.py:378-383` catches Exception from entire stage but emits one generic "stage failed" event; no retry logic
- Files: `backend/jobs/runner.py`
- Impact: If engrave crashes, user never knows which artifact failed (PDF? MIDI? both?); no exponential backoff; transient failures (network blip in yt-dlp) kill the entire job
- Fix approach: Implement per-artifact retry with exponential backoff; emit granular stage-failure events with specific artifact kind; allow partial job success

**MIDI parsing fallback is silent when pretty_midi is missing:**
- Issue: `backend/jobs/runner.py:108-111` returns stub if pretty_midi not installed
- Files: `backend/jobs/runner.py`
- Impact: `midi_upload` variant jobs produce fake sheet music from stub data instead of actual MIDI content; user gets wrong score with no error
- Fix approach: Raise explicit ImportError; require pretty_midi for MIDI variant; document as hard dependency

**Cover search is best-effort with silent fallback:**
- Issue: `backend/services/ingest.py:163-210` cover_search exceptions are caught and logged but return original URL
- Files: `backend/services/ingest.py:180-184`
- Impact: If YouTube search breaks, users get the original polyphonic mix transcribed; no way to know cover-search was attempted
- Fix approach: Add metadata flag to InputBundle to track whether cover-search was skipped; expose in job events

**yt-dlp download failures are terminal:**
- Issue: `backend/services/ingest.py:69-138` if download fails, exception propagates and kills job; no retry, no partial download resume
- Files: `backend/services/ingest.py`
- Impact: YouTube URLs that are region-restricted, removed, or temporarily unavailable kill the job permanently
- Fix approach: Implement retry with exponential backoff; log intermediate failures as warnings; allow job to continue even if download times out

---

## Coupling & Architectural Issues

**Backend and svc-* services duplicate code:**
- Issue: `svc-decomposer/decomposer/tasks.py` and `svc-assembler/assembler/tasks.py` each have separate stubs; real impl is only in `backend/services/`
- Files: `svc-decomposer/decomposer/tasks.py`, `svc-assembler/assembler/tasks.py`, `backend/services/arrange.py`, `backend/services/transcribe_pipeline_stems.py`
- Impact: When real logic is moved to svc-*, code must be ported, not shared; divergence risk; two maintenance burdens
- Fix approach: Either (a) make svc-* services thin wrappers that import from backend, or (b) move all core logic to a shared library that all services depend on

**Claim-check pattern relies on fragile URI semantics:**
- Issue: `backend/jobs/runner.py:210-213`, workers serialize stage input to `f"jobs/{job_id}/{step}/input.json"` and trust blob.get_json() to find it later
- Files: `backend/jobs/runner.py`, `shared/shared/storage/local.py`
- Impact: If blob URI format changes, intermediate state becomes inaccessible; no versioning on blob keys; no TTL on intermediate files (disk bloat)
- Fix approach: Version blob key format; implement garbage collection on failed jobs; add blob store transaction semantics

**Job status is authoritative only on one orchestrator instance:**
- Issue: `backend/api/deps.py:32-34` creates singleton JobManager per process; no shared state
- Files: `backend/api/deps.py`, `backend/jobs/manager.py`
- Impact: If orchestrator is load-balanced, polling same job_id from different IPs gives different results; no consistency
- Fix approach: Store authoritative state in Redis or Postgres; orchestrator becomes stateless

---

## Data Integrity & Contracts

**Pipeline contracts are loosely validated:**
- Issue: Pydantic models in `shared/shared/contracts.py:365` define contracts but no mutation validation; stage input is deserialized from JSON without type checks on mutation paths
- Files: `shared/shared/contracts.py`, `backend/jobs/runner.py:300-375`
- Impact: If a stage corrupts data (e.g., sets negative velocity), downstream stages may produce incorrect output without warning
- Fix approach: Add post-deserialization validators to catch impossible states; log stage output hash for integrity checking

**Stub note velocities hardcoded to fixed values:**
- Issue: Stubs in `backend/jobs/runner.py:69`, `svc-decomposer/decomposer/tasks.py:39-41` all use velocity=80 or 70
- Files: `backend/jobs/runner.py`, `svc-decomposer/decomposer/tasks.py`, `svc-assembler/assembler/tasks.py`
- Impact: Sheet music velocity dynamics are lost; all notes play at same volume
- Fix approach: Infer velocity distribution from transcription output (if available); randomize to avoid obviously fake appearance

**Time-signature and key detection are hardcoded defaults:**
- Issue: `backend/services/ingest.py` (for audio) and `backend/jobs/runner.py:158-169` (for MIDI) hardcode `(4, 4)` and `"C:major"`
- Files: `backend/services/ingest.py`, `backend/jobs/runner.py`
- Impact: Every piece renders in C major 4/4 unless key_detection_enabled and meter_detection_enabled are on; sheet music has wrong key signature and accidentals
- Fix approach: Key/meter detection is implemented but defaults may not be enabled; verify config in production

---

## Missing Error Reporting

**No WebSocket error details on connection failure:**
- Issue: `backend/api/routes/ws.py:36` sends JSON error object on connection refuse, but `frontend/lib/api/ws.dart:37-39` just wraps it in StateError
- Files: `backend/api/routes/ws.py`, `frontend/lib/api/ws.dart`
- Impact: User sees generic "connection error" instead of "job not found"; hard to debug why WebSocket isn't working
- Fix approach: Add error code enum (job_not_found, server_error, etc.); propagate to frontend error screen with actionable message

**Upload validation errors don't distinguish MIME vs magic header:**
- Issue: `backend/api/routes/uploads.py:43-46` and `70-89` return 415 for format mismatch and magic-header mismatch with different messages but same status
- Files: `backend/api/routes/uploads.py`
- Impact: Client can't programmatically distinguish "bad extension" from "corrupted file"; error message mixes extension and content
- Fix approach: Return 400 for extension mismatch, 422 for magic-header mismatch; provide structured error response

**Queue-full warnings are silent:**
- Issue: `backend/jobs/manager.py:49-51` drops slow WebSocket subscribers with a warning log
- Files: `backend/jobs/manager.py`
- Impact: If subscriber queue overflows, client gets no notification that it missed events; frontend shows stale progress
- Fix approach: Send explicit "events_skipped" event before resuming; client can refresh job status

---

## Deployment & Infrastructure Risks

**Cloud Run cold starts + Celery startup overhead:**
- Issue: On Cloud Run, first request to orchestrator waits for container start + Celery app init + Redis connection check + LRU cache population
- Files: `backend/main.py:41-46`, `backend/api/deps.py:19-34`
- Impact: First job submission can take 10-30s before it even queues; user sees timeout
- Fix approach: Pre-warm container with health check; use lazy-loaded imports for heavy dependencies; or use Cloud Tasks instead of in-process Celery

**Redis connection is single point of failure:**
- Issue: `backend/workers/celery_app.py:6-10` Celery broker and backend are both Redis; no fallback
- Files: `backend/workers/celery_app.py`, `backend/config.py:27-28`
- Impact: If Redis is down, all job submission fails; no graceful degradation; no queue persistence
- Fix approach: Use RabbitMQ instead of Redis for higher durability; or implement local queue fallback when Redis is unavailable

**Dockerfile has single-layer Python deps:**
- Issue: `Dockerfile:34-36` installs pyproject.toml without separate layer for lockfile
- Files: `Dockerfile`
- Impact: Every code change rebuilds Python environment; adds 5-10min to CI time
- Fix approach: Add `requirements.txt` layer; separate build cache for deps vs code

**LilyPond is optional but critical for PDF output:**
- Issue: `Dockerfile:24-27` installs lilypond but `backend/services/engrave.py:34` has fallback to stub PDF; no validation at startup
- Files: `Dockerfile`, `backend/services/engrave.py`
- Impact: If lilypond is missing from image, PDF is 60 bytes with no error; users can't tell
- Fix approach: Verify lilypond availability in health check; refuse to start if PDF rendering is required but unavailable

---

## Test Coverage Gaps

**No e2e tests for job persistence:**
- Issue: Tests are in `tests/` but no test exercises server restart scenario
- Files: `tests/` (no coverage of process death/restart)
- Impact: Persistence bugs won't be caught until production; the in-memory job state loss is untested
- Fix approach: Add test that kills JobManager and verifies state recovery from blob store

**No tests for partial pipeline failure:**
- Issue: Tests in `tests/` assume all stages succeed
- Files: `tests/` (no negative test cases for stage failure)
- Impact: Error recovery code is untested; retry logic won't work if it ever gets used
- Fix approach: Mock Celery to raise exceptions; verify job_failed event is emitted with correct stage name

**No tests for concurrent job limits:**
- Issue: No test verifies behavior when 100+ concurrent jobs are submitted
- Files: `tests/` (no concurrency stress tests)
- Impact: Thread pool saturation and queue backlog are untested; Cloud Run may silently drop tasks
- Fix approach: Add load test that submits many jobs in parallel; measure latency percentiles

**No CORS origin validation in tests:**
- Issue: `backend/main.py:56-62` sets CORS to `["*"]` in dev and leaves it wide open; no test of restricted origins
- Files: `backend/main.py`, `tests/`
- Impact: If default config is copied to production, any origin can make cross-origin requests
- Fix approach: Add test that verifies CORS origins are restricted in prod config; require allowlist in environment

---

## Known Bugs & Workarounds

**Voice assignment caps at 2 voices per staff:**
- Issue: `backend/services/arrange.py:47-48` `MAX_VOICES_RH = 2` and `MAX_VOICES_LH = 2`; comment says "OSMD's VexFlow backend crashes on voice-3"
- Files: `backend/services/arrange.py`
- Impact: Complex music with dense counterpoint will have notes silently dropped if >2 overlapping notes per hand
- Workaround: Notes beyond 2 voices are dropped in `_resolve_overlaps` line 215 without warning
- Fix approach: Fall back to single voice or implement voice merging algorithm instead of dropping

**Humanization seed is hardcoded to 42:**
- Issue: `backend/services/humanize.py:277` default seed in HumanizeService.__init__
- Files: `backend/services/humanize.py`
- Impact: All performances are identical unless explicitly seeded differently; no randomness between plays
- Workaround: Job submission can pass seed through config (if implemented)
- Fix approach: Make seed configurable via PipelineConfig; randomize by job_id if not provided

**Stub quality confidence is 0.3-0.7:**
- Issue: `backend/jobs/runner.py:85` stub has 0.5 confidence; decomposer stub has 0.3; MIDI-from-MIDI is 0.95
- Files: `backend/jobs/runner.py`, `svc-decomposer/decomposer/tasks.py`, `backend/jobs/runner.py:188`
- Impact: Quality signal is inconsistent across paths; downstream users can't trust confidence metric
- Fix approach: Explicitly track which path was taken (real transcription vs stub); set confidence to 0.0 for stubs

---

## Security Considerations

**WebSocket connections have no rate limiting:**
- Issue: `backend/api/routes/ws.py:26-31` accepts any job_id and creates a queue; no auth check
- Files: `backend/api/routes/ws.py`
- Impact: Attacker can open 10,000 WebSocket connections to the same job and exhaust memory
- Fix approach: Add rate limiting by IP; require job ownership token; close idle connections after 5min

**Artifact download has no access control:**
- Issue: `backend/api/routes/artifacts.py:32-82` downloads any artifact for any job_id without checking ownership or permissions
- Files: `backend/api/routes/artifacts.py`
- Impact: Attacker can guess job_ids and download other users' sheet music/MIDI
- Risk: Privacy violation; users can see each other's uploads
- Fix approach: Add job ownership token; require token in artifact download request

**No rate limiting on job submission:**
- Issue: `backend/api/routes/jobs.py:82-157` accepts job submission without checking source IP or user
- Files: `backend/api/routes/jobs.py`
- Impact: Attacker can spam 1000 jobs per second; exhaust disk with blob storage; DOS Redis queue
- Fix approach: Add per-IP rate limit; require API key; implement sliding-window bucket algorithm

**CORS is wide open:**
- Issue: `backend/main.py:56-62` `allow_origins=["*"]` in all environments
- Files: `backend/main.py`
- Impact: Any website can make cross-origin requests to your API
- Risk: If user is logged into your site, attacker can steal session via CSRF
- Fix approach: Restrict origins to production domain; require CSRF token for mutating endpoints

---

## Fragile Areas

**Cover search scoring is deterministic but corpus-dependent:**
- Issue: `backend/services/cover_search.py:707` scoring uses YouTube view counts and upload dates; no normalization across regions
- Files: `backend/services/cover_search.py`
- Impact: Same song searched from different regions may return different covers; results vary by YouTube algorithm updates
- Fix approach: Cache cover search results; add allowlist of known-good covers; manually curate top results

**Melody/bass extraction uses Viterbi with fixed parameters:**
- Issue: `backend/services/melody_extraction.py:732` and `backend/services/bass_extraction.py` Viterbi uses hardcoded transition weights
- Files: `backend/services/melody_extraction.py`, `backend/services/bass_extraction.py`
- Impact: Voice split fails on music with blurred boundaries (vocal duets, overlapping instruments)
- Fix approach: Make weights configurable; implement adaptive model based on piece characteristics

**Key estimation confidence floor is 0.55:**
- Issue: `backend/config.py:385` `key_min_confidence: float = 0.55` is arbitrary
- Files: `backend/config.py`, `backend/services/key_estimation.py`
- Impact: Atonal music or percussion-heavy recordings may get wrong key with high confidence
- Fix approach: Cross-validate key estimate with detected chord roots (already implemented as key_chord_validation_enabled)

---

## Missing Critical Features

**No job cancellation:**
- Issue: `backend/api/routes/jobs.py` no DELETE or CANCEL endpoint
- Impact: If a job gets stuck (yt-dlp hanging, transcription in infinite loop), user can't stop it; wastes resources until timeout
- Fix approach: Add POST /v1/jobs/{id}/cancel endpoint; signal Celery task cancellation; set job status to "cancelled"

**No intermediate artifact download during execution:**
- Issue: `backend/api/routes/artifacts.py:50-51` only allows artifact download when job.status == "succeeded"
- Impact: User can't access partial results (transcription MIDI) while humanization is running
- Fix approach: Add query param to return intermediate artifacts; check that stage has completed instead of entire job

**No job priority/queue positioning:**
- Issue: Celery tasks are FIFO; no way for user to prioritize their job
- Impact: User submits urgent job but it waits behind 50 slow transcriptions
- Fix approach: Add priority field to PipelineConfig; use Celery priority queue

**No batch job submission:**
- Issue: POST /v1/jobs accepts single bundle; no batch endpoint
- Impact: Transcribing a playlist requires N separate HTTP requests; no atomic transaction
- Fix approach: Add POST /v1/jobs/batch endpoint; validate all inputs before queueing any

---

## Scaling Limitations

**In-process Celery worker pool is O(cores):**
- Issue: Docker container runs orchestrator + workers in one process via `task_always_eager` in tests
- Files: `docker-compose.yml` runs separate worker containers (good), but production may run monolith
- Impact: Single machine can only process as many jobs as it has CPU cores
- Fix approach: Separate orchestrator from workers; scale workers independently

**Blob storage is local filesystem:**
- Issue: `shared/shared/storage/local.py` and `LocalBlobStore` only support file:// URIs
- Files: `shared/shared/storage/local.py`, `backend/storage/local.py`
- Impact: Scaling to multiple machines requires shared NFS mount or manual S3 implementation
- Fix approach: Implement S3BlobStore; abstract blob storage interface; allow configuration

**Job state cannot be queried across instances:**
- Issue: `backend/jobs/manager.py:124-125` list() returns only jobs in current instance
- Impact: Multi-instance deployment can't show user a unified job history
- Fix approach: Query from Redis/Postgres instead of instance memory

---

## Technical Debt Summary

| Category | Count | Severity | Timeline |
|----------|-------|----------|----------|
| Stub implementations | 3 | Critical | Block production use |
| State persistence | 3 | High | Breaks on restart |
| Security gaps | 4 | High | Fix before public deploy |
| Error recovery | 4 | Medium | Affects reliability |
| Performance | 3 | Medium | Matters at scale |
| Scaling limits | 3 | Medium | Blocks multi-machine setup |
| Test coverage | 4 | Low | Nice to have |

