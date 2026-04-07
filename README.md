https://github.com/user-attachments/assets/444634d1-0c96-484a-9329-af9d62a8a187

# Oh Sheet

An automated pipeline that transforms any song into playable piano sheet music. Upload an MP3 or MIDI file, and Oh Sheet transcribes, arranges, humanizes, and engraves it into a PDF and interactive MusicXML score.

## How It Works

```
MP3 / MIDI / Song Link
        │
        ▼
┌─── INGEST ───┐    Validate input, normalize audio, extract metadata
└───────┬───────┘
        ▼
┌─ TRANSCRIBE ─┐    Full-mix audio → MIDI (MT3 / custom conformer)
│              │    Chord detection, beat tracking, key/tempo analysis
└───────┬───────┘
        ▼
┌── ARRANGE ───┐    Multi-instrument MIDI → two-handed piano score
│              │    Melody → right hand, bass + chords → left hand
└───────┬───────┘
        ▼
┌── HUMANIZE ──┐    Add micro-timing, velocity dynamics, pedal marks
│              │    Makes it sound played by a human, not a computer
└───────┬───────┘
        ▼
┌── ENGRAVE ───┐    Piano score → MusicXML → LilyPond → PDF
│              │    Publication-quality sheet music
└───────┬───────┘
        ▼
  PDF + MusicXML + Humanized MIDI
```

### Pipeline Variants

| Variant | Entry Point | Stages | Use Case |
|---------|-------------|--------|----------|
| `full` | Song title/link | 1 → 2 → 3 → 4 → 5 | "Turn this Spotify song into sheet music" |
| `audio_upload` | MP3/WAV file | 2 → 3 → 4 → 5 | User uploads their own audio |
| `midi_upload` | MIDI file | 3 → 4 → 5 | Skip transcription, arrange existing MIDI |
| `sheet_only` | Audio/MIDI | 1/2 → 3 → 5 | Skip humanization, quantized output only |

### Data Flow Between Stages

```
InputBundle          TranscriptionResult      PianoScore
  audio ──────────►   stems (separated)  ──►   right_hand[]
  midi (optional)     midi_tracks[]            left_hand[]
  metadata            harmonic_analysis        metadata (key, tempo, difficulty)
                        chords[]
                        sections[]

PianoScore           HumanizedPerformance     EngravedOutput
  ──────────────►     expressive_notes[] ──►   pdf (bytes)
                      expression_map           musicxml (string)
                        dynamics               humanized_midi (bytes)
                        articulations
                        pedal_events
```

## Tech Stack

| Stage | Primary Tool | Fallback |
|-------|-------------|----------|
| Transcription | MT3 / Custom Conformer | Basic Pitch |
| Chord/Structure | madmom | librosa |
| Arrangement | music21 | LLM (GPT-4) |
| Humanization | Rule-based + ML | — |
| Engraving | LilyPond | MuseScore CLI |

## Status

This repo currently contains the **API skeleton**. Each stage service is a
stub that returns shape-correct contract objects but does **not** run real ML
inference, `music21`, LilyPond, etc. The wrappers will delegate to the
existing pipeline implementations in a follow-up PR.

## Architecture

### Backend (FastAPI)

```
ohsheet/
├── main.py              # FastAPI app factory + uvicorn entry
├── config.py            # Pydantic settings
├── contracts.py         # Pydantic models — mirrors api-contracts-v2.md (3.0.0)
├── storage/             # BlobStore abstraction (Claim-Check pattern)
│   ├── base.py
│   └── local.py         # file:// backed local store; S3 stub goes here next
├── services/            # Stage workers — STUBS
│   ├── ingest.py
│   ├── transcribe.py    # → wraps MT4 v5
│   ├── arrange.py       # → wraps temp1/arrange.py
│   ├── humanize.py      # → wraps temp1/humanize.py
│   └── engrave.py       # → wraps temp1/engrave.py (LilyPond)
├── jobs/                # Async job runner + WebSocket pub/sub
│   ├── manager.py       # In-memory JobManager (swap for Redis later)
│   ├── runner.py        # Walks PipelineConfig.get_execution_plan()
│   └── events.py        # JobEvent schema
└── api/
    └── routes/
        ├── health.py
        ├── uploads.py   # POST /v1/uploads/{audio,midi} → Claim-Check URIs
        ├── jobs.py      # POST /v1/jobs, GET /v1/jobs/{id}, list
        ├── stages.py    # POST /v1/stages/{ingest,…} — worker envelope
        └── ws.py        # WS  /v1/jobs/{id}/ws — live event stream
```

### System Overview

```
┌──────────────┐                ┌──────────────┐                ┌──────────────┐
│  Oh Sheet    │   job request  │  Oh Sheet    │   artifacts    │  TuneChat    │
│  Frontend    │ ──────────────►│  Pipeline    │ ──────────────►│  (optional)  │
│  (SPA)       │                │  (FastAPI)   │                │              │
│              │◄─── progress ──│              │                │  Rooms       │
│  Upload      │   via WS      │  MT3         │                │  Shared Piano│
│  Progress    │                │  music21     │                │  AI Coach    │
│  Download    │                │  LilyPond    │                │  Live Playback│
└──────────────┘                └──────────────┘                └──────────────┘
```

## Run

```bash
pip install -e ".[dev]"
ohsheet                              # or: uvicorn ohsheet.main:app --reload
```

OpenAPI docs at <http://localhost:8000/docs>.

## Submit a job

```bash
# 1. Upload an audio file → returns a RemoteAudioFile (Claim-Check URI)
curl -F "file=@song.mp3" http://localhost:8000/v1/uploads/audio

# 2. Submit a job referencing the upload
curl -X POST http://localhost:8000/v1/jobs \
  -H "content-type: application/json" \
  -d '{"audio": <RemoteAudioFile from step 1>, "title": "My Song"}'

# 3. Stream live updates over WebSocket
wscat -c ws://localhost:8000/v1/jobs/<job_id>/ws
```

## Per-stage worker endpoints

For Temporal / Step Functions style orchestration, each stage is also exposed
as a stateless worker that takes an `OrchestratorCommand` and returns a
`WorkerResponse` (see contracts §1):

- `POST /v1/stages/ingest`
- `POST /v1/stages/transcribe`
- `POST /v1/stages/arrange`
- `POST /v1/stages/humanize`
- `POST /v1/stages/engrave`

## TuneChat Integration

Oh Sheet can optionally deliver results to [TuneChat](https://github.com/robin-raq/TuneChat) — a real-time collaborative music learning platform. When results are pushed to a TuneChat room, users can view interactive sheet music, play along on a shared piano, and get AI coaching.

**Endpoints on TuneChat's side (already implemented):**

```bash
# Send progress updates to a room
POST https://<tunechat>/api/v1/service/rooms/{room_id}/messages
  Authorization: Bearer $SERVICE_TOKEN
  {"text": "Arranging for piano...", "display_as": "Pipeline"}

# Deliver completed artifacts
POST https://<tunechat>/api/v1/service/rooms/{room_id}/artifacts
  Authorization: Bearer $SERVICE_TOKEN
  {"job": {"job_id": "...", "status": "completed"},
   "artifacts": [{"kind": "musicxml", "url": "..."}],
   "title": "Song Title"}
```

Full API spec: [TuneChat API Contracts](https://github.com/robin-raq/TuneChat/blob/master/docs/api-contracts.md)

## Tests

```bash
pytest
```

## Wiring real services

Each file under `ohsheet/services/` has a top-of-file docstring marking what
to replace. The plan:

1. Move (or `pip install -e`) the existing pipeline modules so they're
   importable.
2. Replace the stub bodies with calls into the real implementations.
3. Use `asyncio.to_thread()` for CPU-bound stages (MT4 inference, LilyPond).
4. Add an `S3BlobStore` alongside `LocalBlobStore`.
