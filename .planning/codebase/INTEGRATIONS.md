# External Integrations

**Analysis Date:** 2026-04-13

## APIs & External Services

**YouTube:**
- Service: YouTube video hosting (audio extraction)
  - SDK/Client: `yt-dlp` 2024.1+ (CLI wrapper, installed via `pip install ohsheet[youtube]`)
  - Auth: None (public URL parsing)
  - Used by: `backend/services/ingest.py` → `_download_youtube_sync()` for remote audio ingestion

**Machine Learning Models:**
- **Basic Pitch** (Spotify): Polyphonic pitch tracking
  - SDK/Client: `basic-pitch` 0.4.0 (Python package with bundled ICASSP-2022 model weights)
  - Auth: None (model weights included in wheel)
  - Used by: `backend/services/transcribe_inference.py` → `_BasicPitchPass` for note detection
  - Backends: Auto-selects from CoreML (macOS) → ONNX → TensorFlow Lite → TensorFlow

- **Demucs** (Meta): Source separation (drums/bass/vocals/other stems)
  - SDK/Client: `demucs` 4.0+ (Python package)
  - Auth: None (public models, CC BY-NC 4.0 license for `htdemucs` weights)
  - Models: Downloaded from `dl.fbaipublicfiles.com` on first use (~250 MB for htdemucs)
  - Used by: `backend/services/stem_separation.py` → `separate_stems()` (optional, falls back to single-mix)
  - Config: `OHSHEET_DEMUCS_ENABLED` (default: true), `OHSHEET_DEMUCS_DEVICE`, `OHSHEET_DEMUCS_MODEL`

- **CREPE** (torchcrepe): Vocal melody F0 estimation
  - SDK/Client: `torchcrepe` 0.0.22+ (Python package with bundled model weights)
  - Auth: None (model weights included in wheel)
  - Used by: `backend/services/crepe_melody.py` → `extract_vocal_melody_crepe()` on vocals stem
  - Config: `OHSHEET_CREPE_VOCAL_MELODY_ENABLED` (default: true), `OHSHEET_CREPE_MODEL` (tiny/full)
  - Hybrid mode: Fuses CREPE pitch accuracy with Basic Pitch onset/offset timing via `OHSHEET_CREPE_HYBRID_ENABLED`

## Data Storage

**Databases:**
- Redis 7-alpine
  - Connection: `OHSHEET_REDIS_URL` (default: `redis://localhost:6379/0`)
  - Role: Celery message broker + result backend
  - Client: `celery[redis]` 5.3+ (Redis wire protocol)
  - Persistence: Optional volume mount at `/data` in Docker Compose (`redis-data` volume)

**File Storage:**
- Local filesystem only (production-ready with extensibility)
  - Connection: `OHSHEET_BLOB_ROOT` (default: `./blob`)
  - Role: Claim-check pattern - stores intermediate MIDI, audio, MusicXML artifacts
  - Client: `backend/storage/local.py` → `LocalBlobStore` (path-based URI scheme: `file://...`)
  - Future: S3 support via storage abstraction layer (base class in `backend/storage/base.py`)

**Caching:**
- Redis (implicit via Celery result backend for transient task outputs)

## Authentication & Identity

**Auth Provider:**
- None (public API - no authentication or authorization)
- CORS: Wildcard `["*"]` in development, can be tightened via `OHSHEET_CORS_ORIGINS` in production

## Monitoring & Observability

**Error Tracking:**
- None (application logs to stdout/stderr)

**Logs:**
- Structured logging via Python `logging` module
  - Backend: `backend.*` logger scoped to `OHSHEET_LOG_LEVEL` (default: INFO)
  - Workers: Celery task logs via `--loglevel=info` (dev) / `--loglevel=warning` (prod)
  - Output: stdout → container runtime (Docker logs, Cloud Run logs)

**Health Checks:**
- `GET /v1/health` - HTTP endpoint for orchestrator liveness
  - Used by: Docker Compose healthchecks, GCP Cloud Run, deployment verification in CI

## CI/CD & Deployment

**Hosting:**
- GCP (inferred from `.github/workflows/deploy.yml` references):
  - Artifact Registry: `{REGION}-docker.pkg.dev/{GCP_PROJECT_ID}/oh-sheet/{app,decomposer,assembler}`
  - Workload Identity Federation (WIF) for GitHub Actions authentication
  - Environment variables: `GCP_PROJECT_ID`, `GCP_REGION` (default: us-central1)
- VM-based deployment (not Cloud Run, despite references):
  - Target: SSH to VM via private key
  - Reverse proxy: Caddy 2 (TLS, reverse_proxy to orchestrator:8000)

**CI Pipeline:**
- GitHub Actions (`.github/workflows/`)
  - `ci.yml`: Lint (ruff) → Typecheck (mypy) → Test (pytest) → Frontend lint (flutter analyze) on every PR/push
  - `deploy.yml`: Docker build → Artifact Registry push → SSH deploy to VM (on push to main/qa)
  - `release.yml`: Semantic versioning via python-semantic-release
  - `branch-guard.yml`: Branch protection rules

**Deployment Flow:**
1. Push to main/qa triggers `deploy.yml`
2. Build three Docker images: app (main orchestrator + workers), decomposer, assembler
3. Push to GCP Artifact Registry with `${COMMIT_SHA}` + `latest` tags
4. SSH to VM, generate `.env` with image tags
5. Pull images, `docker compose up -d` (orchestrator, 5 workers, Redis, Caddy)
6. Verify health with `curl /v1/health`

## Environment Configuration

**Required env vars (backend):**
- `OHSHEET_REDIS_URL` - Redis connection (default: `redis://localhost:6379/0`)
- `OHSHEET_BLOB_ROOT` - Blob storage directory (default: `./blob`)
- `OHSHEET_LOG_LEVEL` - Logging verbosity (default: INFO)
- `PORT` - HTTP port (default: 8080 in Cloud Run, 8000 locally)

**Optional env vars (transcription tuning):**
- `OHSHEET_BASIC_PITCH_ONSET_THRESHOLD` (default: 0.5)
- `OHSHEET_BASIC_PITCH_FRAME_THRESHOLD` (default: 0.3)
- `OHSHEET_DEMUCS_ENABLED` (default: true)
- `OHSHEET_CREPE_VOCAL_MELODY_ENABLED` (default: true)
- `OHSHEET_MELODY_EXTRACTION_ENABLED` (default: true)
- `OHSHEET_CHORD_RECOGNITION_ENABLED` (default: true)
- Full list in `backend/config.py` (100+ tunable parameters)

**Frontend env vars:**
- `API_BASE_URL` - Backend URL (default: same-origin `/v1/...` via empty string)
  - Passed to `flutter build web` via `--dart-define=API_BASE_URL=...`
  - Passed to `flutter run` via `--dart-define=API_BASE_URL=...`
- `APP_VERSION` - Version display in UI (default: dev)

**Secrets location:**
- `.env` file (not checked in - `.gitignore`)
- GitHub Actions: Repository/environment secrets
  - `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT` (GCP Workload Identity)
  - `VM_SSH_PRIVATE_KEY`, `VM_HOST`, `VM_USER` (deployment)
  - `SLACK_WEBHOOK_URL` (deployment notifications)

## Webhooks & Callbacks

**Incoming:**
- None (pipeline is request-driven)

**Outgoing:**
- Slack webhook (deployment success/failure notifications)
  - URL: `${SLACK_WEBHOOK_URL}` (GitHub Actions secret)
  - Trigger: Deploy workflow completion (on main/qa push)
  - Payload: JSON with deployment status, commit SHA, environment (prod/qa)

## Message Queue & Task Distribution

**Celery Workers:**
- Broker: Redis (via `OHSHEET_REDIS_URL`)
- Serialization: JSON (no pickle)
- Task routing (fixed queues):
  - `ingest` → `backend/workers/ingest.py` (probe metadata, download YouTube)
  - `transcribe` → `backend/workers/transcribe.py` (Basic Pitch + stem separation)
  - `arrange` → `backend/workers/arrange.py` (quantization + simplification)
  - `humanize` → `backend/workers/humanize.py` (timing/velocity adjustments)
  - `engrave` → `backend/workers/engrave.py` (MusicXML + PDF + MIDI rendering)
  - `decomposer` → `svc-decomposer/` (external worker - orchestration stub)
  - `assembler` → `svc-assembler/` (external worker - arrangement stub)
- Configuration: `backend/workers/celery_app.py` (task_serializer=json, task_track_started=true)

## WebSocket Streaming

**Live Job Updates:**
- Endpoint: `WS /v1/jobs/{job_id}/ws`
- Client: Flutter via `web_socket_channel` 2.4.0
- Protocol: JSON-encoded `JobEvent` messages streamed from `JobManager`
- Implementation: `backend/api/routes/ws.py` → asyncio Queue-based event fan-out

## Audio Processing Pipeline

**ffmpeg Integration:**
- System binary (installed via apt in Docker: `RUN apt-get install -y ffmpeg`)
- Used by: `yt-dlp` (audio extraction from YouTube)
- Used by: `backend/services/transcribe_audio.py` (audio format detection, librosa loads via ffmpeg)

**Sheet Music Rendering Chain:**
- music21 9.1+ → MusicXML generation
- LilyPond (system binary, installed via apt: `RUN apt-get install -y lilypond`)
  - `musicxml2ly` (part of LilyPond) → MusicXML → .ly
  - `lilypond` → .ly → PDF (fallback if unavailable: stub PDF)
- MuseScore CLI (optional alternative if on $PATH)
- Implementation: `backend/services/engrave.py` → `_render_pdf_bytes()`

## Data Contracts

**Shared Pydantic Models** (`shared/shared/contracts.py`):
- `InputBundle` (upload metadata)
- `TranscriptionResult` (note events + harmonic analysis)
- `PianoScore` (arranged MIDI with tempo map)
- `HumanizedPerformance` (performance with expression layer)
- `EngravedOutput` (PDF/MusicXML/MIDI artifacts)
- `OrchestratorCommand` (worker task envelope)
- `WorkerResponse` (result envelope)
- SCHEMA_VERSION: Vendored in Pydantic models, contract versioning via field defaults

## External Configuration Files

**GCP Deployment:**
- `.github/workflows/deploy.yml` references:
  - `vars.GCP_PROJECT_ID`, `vars.GCP_REGION` (environment variables)
  - `secrets.WIF_PROVIDER`, `secrets.WIF_SERVICE_ACCOUNT` (Workload Identity)
  - Image registry pattern: `{REGION}-docker.pkg.dev/{PROJECT_ID}/oh-sheet/{service}`

**Reverse Proxy:**
- `Caddyfile` (loaded by Caddy service in docker-compose.prod.yml)
  - Template: `{$DOMAIN:localhost}` (reverse_proxy to `orchestrator:8000`)
  - TLS: Auto via Caddy
  - Volume: `/etc/caddy/Caddyfile:ro`, `/data`, `/config`
