# PRD: Assembler (Pipeline Stage)

## 1. Meta Information

* **Stage Name:** assemble
* **Status:** READY FOR DEVELOPMENT
* **Tech Stack:** Python 3.10+, Celery + Redis, music21
* **Pipeline Stage:** Runs after decompose
* **Pipeline Mode:** Active when `score_pipeline = "decompose_assemble"`

## 2. Overview & Objective

The assembler takes the decomposer's two-track output (melody + accompaniment) and produces a `PianoScore` using strict difficulty-specific rules. It accepts a `difficulty` parameter via payload envelope; only `"beginner"` is implemented for MVP.

This stage is a monolith worker (`backend/workers/assemble.py`) dispatched by `PipelineRunner` — not a separate microservice.

## 3. Pipeline Integration

The assembler is the second half of the `decompose_assemble` pipeline mode. It receives the decomposer's re-separated `TranscriptionResult` and outputs a `PianoScore` that feeds into humanize → engrave (same as `arrange` output).

## 4. Data Contracts

* **Consumes:** Envelope `{"transcription": TranscriptionResult, "difficulty": str}`
* **Produces:** `PianoScore` (JSON) — `right_hand` and `left_hand` arrays of `ScoreNote` with unique IDs

## 5. Difficulty Parameter

The assembler accepts `difficulty` in the payload envelope. The runner reads `settings.assemble_difficulty` (env: `OHSHEET_ASSEMBLE_DIFFICULTY`, default: `"beginner"`).

Only `"beginner"` is implemented. Other values raise `NotImplementedError`.

## 6. Beginner Rules

### 6.1 8th-Note Quantization

Snap every `onset_beat` and `duration_beat` to the nearest 0.5-beat grid. Minimum duration is 0.5 beats. This eliminates fast runs and syncopation.

### 6.2 Right Hand: Melody Only

* Map all melody track notes to RH Voice 1
* **Monophony:** max 1 note per quantized beat (highest pitch wins at each onset)
* **No accompaniment filler:** accompaniment notes are never added to RH
* **Range:** C4–C6 (MIDI 60–84). Notes outside are octave-shifted inward.

### 6.3 Left Hand: Bass Only

* **Filter:** discard all accompaniment notes at or above middle C (MIDI ≥ 60)
* Map the lowest remaining note at each quantized beat to LH Voice 1
* **Monophony:** max 1 note per quantized beat (lowest pitch wins at each onset)
* **Range:** C2–B3 (MIDI 36–59). Notes outside are octave-shifted inward.

### 6.4 Velocity

Clamp all velocities to 1–127.

## 7. Celery Task

* **Task name:** `assemble.run`
* **Queue:** `arrange`
* **Worker file:** `backend/workers/assemble.py`
* **Service file:** `backend/services/assemble.py`
* **Payload:** `(job_id: str, payload_uri: str)` — standard claim-check pattern via `BlobStore`

## 8. Future: Key Transposition (Not in MVP)

The original PRD specified auto-transposing to C/F/G Major when >1 sharp/flat, plus `music21.chord.simplifyEnharmonics()`. This is deferred past MVP — the infrastructure for it exists in music21 but adds complexity to the initial implementation. The `difficulty` parameter interface supports adding this in a future difficulty level or as a separate config knob.
