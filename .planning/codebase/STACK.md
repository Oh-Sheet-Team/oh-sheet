# Technology Stack

**Analysis Date:** 2026-04-13

## Languages

**Primary:**
- Python 3.10+ (backend) - FastAPI REST API, Celery task workers, ML services (Basic Pitch, Demucs, CREPE)
- Dart 3.3.0+ (frontend) - Flutter cross-platform UI (web, iOS, Android, macOS)
- Shell (Makefile orchestration)

**Secondary:**
- JavaScript/TypeScript (E2E tests via Playwright)

## Runtime

**Environment:**
- Python 3.12 (production Dockerfile) / 3.10+ (development minimum)
- Flutter 3.19.0+
- Dart SDK bundled with Flutter

**Package Manager:**
- pip (Python) - Lockfile: `pyproject.toml` with pinned versions and optional extras
- pubspec (Dart/Flutter) - Lockfile: `pubspec.lock` (checked in)

## Frameworks

**Core:**
- FastAPI 0.110+ (REST API framework, async support)
- Uvicorn 0.27+ (ASGI server, HTTP + WebSocket)
- Celery 5.3+ (task queue - JSON serialization)
- Flutter 3.19.0+ (cross-platform UI framework)

**Backend ML/Audio:**
- basic-pitch 0.4.0 (Spotify polyphonic pitch tracking via ONNX/CoreML/TensorFlow)
- demucs 4.0+ (optional: stem separation via torch - CC BY-NC 4.0 license)
- torchcrepe 0.0.22+ (optional: vocal melody F0 via CREPE model)
- librosa 0.8.0+ (audio analysis, HPSS, beat tracking)
- madmom 0.16+ (beat tracking alternative, DNNBeatProcessor)
- pretty_midi 0.2.10+ (MIDI construction from note events)
- music21 9.1+ (MusicXML generation from PianoScore)
- pydantic 2.5+ (data contracts, validation)

**Frontend:**
- http 1.2.0 (HTTP client for REST API)
- web_socket_channel 2.4.0 (WebSocket client for live job updates)
- file_picker 8.0.0 (native file selection)
- url_launcher 6.2.5 (external URL handling)
- flutter_svg 2.2.4 (SVG asset rendering)
- package_info_plus 8.1.2 (version detection, app info)

**Testing:**
- pytest 8.0+ (Python unit/integration tests)
- pytest-asyncio 0.24+ (async test support)
- pytest-cov 5.0+ (coverage reporting)
- httpx 0.26+ (async HTTP client for testing)
- flutter_test (Dart/Flutter built-in test framework)
- playwright (E2E test framework)

**Build/Dev:**
- hatchling (Python packaging backend)
- ruff 0.4+ (Python linting - E, F, I, W, UP, B, SIM rules)
- mypy 1.10+ (Python type checking, ignore_missing_imports=true)
- semantic-release (python-semantic-release - automated versioning)
- lxml 5.0+ (XPath evaluation for MusicXML quality harness)

**System/CLI:**
- yt-dlp 2024.1+ (YouTube audio extraction - optional youtube extra)
- ffmpeg (system binary via apt/brew - audio extraction, transcoding)
- lilypond (system binary via apt - MusicXML → PDF rendering)
- curl (system binary - health checks, Slack notifications)
- make (orchestration - 40+ targets)

## Key Dependencies

**Critical:**
- pydantic 2.5+ (data serialization layer for all inter-stage contracts via `shared/shared/contracts.py`)
- redis 7-alpine (Docker image) - Celery message broker + result backend
- websockets 12.0+ (native WebSocket support in FastAPI)

**Infrastructure:**
- celery[redis] 5.3+ - Redis integration for task queue
- python-multipart 0.0.9 - Form data upload handling
- pydantic-settings 2.1+ - environment-driven config via OHSHEET_* prefix

**ML/Audio (conditional):**
- tensorflow-macos (Darwin only, skipped in CI to avoid 3.13 incompatibility)
- onnxruntime 1.19+ (ONNX backend for Basic Pitch)
- coremltools (Darwin only - CoreML backend)
- numpy 1.26+, scipy 1.4.1+, scikit-learn (scientific computing)
- resampy 0.2.2+ (audio resampling)
- torch, torchaudio 2.0+ (Demucs/CREPE backends - optional demucs extra)
- mir_eval 0.6.0 (evaluation metrics - pulls in transitively via basic-pitch)

## Configuration

**Environment:**
- `.env` file (via pydantic-settings `env_file=".env"`)
- `OHSHEET_*` prefix for all settings (e.g., `OHSHEET_BLOB_ROOT`, `OHSHEET_REDIS_URL`)
- `PYTHONDONTWRITEBYTECODE=1` (Docker - disable .pyc files)
- `DOMAIN` (production - Caddyfile reverse proxy domain)

**Build:**
- `pyproject.toml` - Core dependencies, extras (dev, youtube, basic-pitch, demucs, eval, madmom)
- `pubspec.yaml` - Flutter dependencies and version constraints (SDK 3.3.0+ required)
- `Dockerfile` - Multi-stage: Flutter web build (stage 1) + Python 3.12-slim runtime (stage 2)
- `Dockerfile.dev` - Lightweight dev image with Basic Pitch support (no Flutter)
- `docker-compose.yml` - Development orchestration (Redis + 5 workers + API)
- `docker-compose.prod.yml` - Production deployment with Caddy reverse proxy
- `.github/workflows/ci.yml` - Lint (ruff), typecheck (mypy), test (pytest), frontend lint (flutter analyze)
- `.github/workflows/deploy.yml` - Build & deploy to GCP via docker push + VM SSH
- `Makefile` - 40+ targets: install-*, backend, frontend, test, lint, typecheck, eval

## Platform Requirements

**Development:**
- macOS / Linux (Dockerfile targets `python:3.12-slim`)
- Flutter SDK on PATH or via `FLUTTER=/path` make override
- Python 3.10+ (3.12 in Docker, 3.13 in CI)
- Docker + Docker Compose (for `make backend`)
- ffmpeg (system binary - audio extraction)
- Optional: madmom build requires Cython + setuptools (handled by Makefile `install-basic-pitch`)

**Production:**
- Docker 20+ with Docker Compose 1.29+
- GCP Artifact Registry (docker.pkg.dev - image storage)
- Linux VM (deployed via SSH from GitHub Actions)
- Caddy 2 (reverse proxy, TLS termination)
- Redis 7 (message broker)
- ffmpeg + lilypond (system deps in container, apt-get installed in Dockerfile)

**Frontend Target Platforms:**
- Chrome (default via `flutter run -d chrome`)
- iOS, Android, macOS (via DEVICE= make override)
- Flutter web via `flutter build web`
