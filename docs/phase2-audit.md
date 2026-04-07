# Phase 2 Readiness Audit (Current Codebase)

## Scope Audited

- Backend API/job system in `backend/`
- Pipeline services in `backend/services/`
- Job orchestration in `backend/jobs/`
- Frontend UX flow in `frontend/lib/`
- Existing tests under `tests/`

## Executive Verdict

Current code can support parts of Phase 2, but not as-is for production scale.

- **1) Asynchronous processing for long audio files:** **Partially ready**
  - Async non-blocking flow exists.
  - Missing distributed queue/workers and YouTube ingest implementation.
- **2) Shared community library with search/caching:** **Not ready**
  - No database-backed library model, no search endpoints, no cache lookup.
- **3) Automated difficulty classification logic:** **Partially ready**
  - Difficulty enum exists but is mostly fixed/manual, not computed level 1-10.

## Feature-by-Feature Audit

### 1) Async processing for long audio (yt-dlp + background workers)

**What already exists (reusable):**
- `JobManager` + background `asyncio.create_task()` orchestration.
- Stage-based `PipelineRunner` with event streaming to websocket.
- File upload endpoints and artifact download endpoints.
- CPU-heavy stages already pushed to `asyncio.to_thread()` in several services.

**What is missing:**
- No `yt-dlp` URL ingestion endpoint/worker stage.
- In-memory job registry only; does not survive process restarts.
- No distributed worker model (single-process memory lifecycle).
- No retry/backoff/dead-letter/idempotency guard for long-running tasks.

**Risk:**
- Any backend restart loses active job state.
- Horizontal scaling is blocked by in-memory job/event store.

### 2) Shared community library with search/caching

**What already exists (reusable):**
- Artifact URIs and metadata contract models are already clear.
- Upload hash (`content_hash`) exists for input dedup potential.
- Existing API shape can be extended without breaking current flow.

**What is missing:**
- No persistent DB models for users, library entries, or source mapping.
- No endpoint for search/filter/listing community scores.
- No cache lookup before running pipeline.
- No canonical source key management (`youtube_id`, normalized URL signatures).
- Local filesystem blob storage only (no multi-instance shared object store).

**Risk:**
- Compute is re-spent on repeated requests.
- No user-visible shared repository experience.

### 3) Automated difficulty classification

**What already exists (reusable):**
- Contract includes difficulty metadata on scores.
- Arrangement stage already computes note-level structure that can feed heuristics.

**What is missing:**
- Difficulty is currently set as coarse enum and defaults to `"intermediate"`.
- No score analytics module for density/span/rhythm metrics.
- No persistence or API exposure for numeric level and explanation.

**Risk:**
- Difficulty labels are not trustworthy enough for user-facing filtering.

## Keep vs Replace Recommendations

- **Keep:** current stage contract design and event-driven runner pattern.
- **Keep:** upload + artifact delivery endpoints as integration shell.
- **Replace/Upgrade:** in-memory `JobManager` with Redis/Celery (or RQ/Arq).
- **Add:** Postgres schema for jobs/library/cache + search indexes.
- **Add:** YouTube ingestion service stage and canonical source mapping.
- **Add:** deterministic difficulty scorer module with unit tests.
- **Add:** S3-backed blob store for deploy-safe artifact storage.

## Minimal Change Path (Avoid Recreating the Wheel)

1. Preserve existing API contracts and pipeline stage names.
2. Introduce persistence layer (Postgres) behind current route handlers.
3. Swap job execution backend from local in-memory to queue workers.
4. Add cache lookup at job creation before enqueue.
5. Implement difficulty scorer as standalone pure function module.
6. Keep frontend flow; add library/search screens incrementally.

## Recommended Phase 2 Acceptance Criteria

- Jobs survive API restarts and can be resumed/inspected.
- Duplicate YouTube submissions return cached artifacts in <2s.
- Library supports text search + difficulty filter + sort.
- Difficulty level 1-10 generated automatically with explainable sub-metrics.
- At least one smoke test covers each new subsystem (queue, cache, search, classifier).
