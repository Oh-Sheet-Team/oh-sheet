# PRD: Decomposer (Pipeline Stage)

## 1. Meta Information

* **Stage Name:** decompose
* **Status:** READY FOR DEVELOPMENT
* **Tech Stack:** Python 3.10+, Celery + Redis, mido (parsing)
* **Pipeline Stage:** Runs after transcribe (audio variants) or after ingest (midi_upload)
* **Pipeline Mode:** Active when `score_pipeline = "decompose_assemble"`

## 2. Overview & Objective

The decomposer re-separates transcription tracks into a monophonic melody line and an accompaniment track. It merges all notes from all input tracks (ignoring existing instrument roles), then applies the Skyline Algorithm to extract the highest-pitched note at each time interval as melody. Everything else becomes accompaniment.

This stage is a monolith worker (`backend/workers/decompose.py`) dispatched by `PipelineRunner` — not a separate microservice.

## 3. Pipeline Integration

The decomposer activates via `ScorePipelineMode = "decompose_assemble"`, which replaces `arrange` with `decompose` → `assemble` in the execution plan:

| Variant | Execution Plan |
|---|---|
| `midi_upload` | ingest → decompose → assemble → humanize → engrave |
| `audio_upload` | ingest → transcribe → decompose → assemble → humanize → engrave |
| `full` | ingest → transcribe → decompose → assemble → humanize → engrave |
| `sheet_only` | ingest → transcribe → decompose → assemble → engrave |

## 4. Data Contracts

* **Consumes:** `TranscriptionResult` — notes in seconds domain with instrument roles, analysis, quality signal
* **Produces:** `TranscriptionResult` — same schema, but with exactly two tracks:
  - `instrument: InstrumentRole.MELODY` — isolated monophonic lead line
  - `instrument: InstrumentRole.OTHER` — accompaniment (chords + bass grouped)

Notes stay inline in `midi_tracks[].notes` arrays (no separate MIDI file export).

## 5. Algorithm

1. **Merge:** Collect all notes from all input tracks, ignoring existing `instrument` roles
2. **Sort:** Order by onset time, then descending pitch
3. **Skyline split:** Group notes by quantized onset (16th-note resolution). Within each group, the highest-pitched note becomes melody; all others become accompaniment.
4. **Emit:** Two-track `TranscriptionResult` with analysis and quality passed through unchanged

### Skyline Algorithm Detail

At each quantized time slot (≈0.0625 sec at 120 BPM):
- All notes with onsets in that slot are grouped
- The note with the highest MIDI pitch is assigned to melody
- All remaining notes are assigned to accompaniment
- This guarantees monophonic melody output

## 6. Celery Task

* **Task name:** `decompose.run`
* **Queue:** `arrange`
* **Worker file:** `backend/workers/decompose.py`
* **Service file:** `backend/services/decompose.py`
* **Payload:** `(job_id: str, payload_uri: str)` — standard claim-check pattern via `BlobStore`
