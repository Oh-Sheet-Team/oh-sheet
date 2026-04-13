# Dual Pipeline Design: decompose_assemble Mode

## Summary

Add `"decompose_assemble"` as a third `ScorePipelineMode` value alongside `"arrange"` and `"condense_transform"`. This lets users compare the new decomposer/assembler pipeline against the existing arrangement pipeline on the same input, controlled by a per-job config toggle.

Both pipelines coexist as monolith workers in the same Celery app. The existing `arrange` and `condense_transform` paths are completely untouched.

## Pipeline Routing

`ScorePipelineMode` gains a third value:

```python
ScorePipelineMode = Literal["arrange", "condense_transform", "decompose_assemble"]
```

`get_execution_plan()` replaces `arrange` with `decompose` → `assemble` when `score_pipeline == "decompose_assemble"`, using the same swap pattern as `condense_transform`:

| Variant | `arrange` (default) | `decompose_assemble` |
|---|---|---|
| `full` | ingest → transcribe → arrange → humanize → engrave | ingest → transcribe → decompose → assemble → humanize → engrave |
| `audio_upload` | ingest → transcribe → arrange → humanize → engrave | ingest → transcribe → decompose → assemble → humanize → engrave |
| `midi_upload` | ingest → arrange → humanize → engrave | ingest → decompose → assemble → humanize → engrave |
| `sheet_only` | ingest → transcribe → arrange → engrave | ingest → transcribe → decompose → assemble → engrave |

`skip_humanizer` continues to work orthogonally (removes `humanize` from any plan).

## Stage Contracts

### Decompose: TranscriptionResult → TranscriptionResult

The decomposer is a re-separation stage. It takes a `TranscriptionResult` (whether from audio transcription or `_bundle_to_transcription()` for MIDI upload) and produces a new `TranscriptionResult` with two tracks:

- `instrument: "melody"` — isolated monophonic lead line
- `instrument: "other"` — accompaniment (chords + bass grouped together)

**Algorithm:**
1. Parse notes via mido
2. Logical split via musicpy `split_all()` (pitch density + timing analysis)
3. Fallback: Skyline Algorithm (highest-pitched note at each 16th-note interval)
4. Serialize separated tracks back to `TranscriptionResult`

The decomposer operates on MIDI note data regardless of origin. It merges all notes from all input tracks (ignoring existing `instrument` roles like MELODY/BASS/CHORDS), then re-separates from scratch into exactly two output tracks. For audio variants, this means re-splitting what Demucs/Viterbi already separated — potentially producing different melody isolation to compare.

### Assemble: TranscriptionResult → PianoScore

The assembler takes the decomposer's output and produces a `PianoScore` using strict beginner-level rules. It accepts a `difficulty` parameter via payload envelope (only `"beginner"` implemented for MVP).

**Beginner rules:**
1. **Key transposition** — if >1 sharp/flat, transpose to nearest of C/F/G Major. Run `music21.chord.simplifyEnharmonics()` afterward. Fallback: C Major.
2. **8th-note quantization** — snap all `onset_beat` and `duration_beat` to 0.5-beat grid
3. **Right hand** — 100% of melody notes → RH voice 1 (immune from deletion). Discard all accompaniment notes above middle C. Max 1 note sounding at any time.
4. **Left hand** — lowest concurrent accompaniment note per beat → LH voice 1 (immune from deletion). Discard all other accompaniment notes below middle C. Max 1 note sounding at any time.
5. **Range clamping** — RH: C4–C6 (MIDI 60–84), LH: C2–B3 (MIDI 36–59). Notes outside are octave-shifted inward.

Output matches the existing `PianoScore` contract exactly — `right_hand` and `left_hand` arrays of `ScoreNote` with unique IDs.

## Runner Integration

**STEP_TO_TASK mapping** — two new entries:
```python
"decompose": "decompose.run",
"assemble": "assemble.run",
```

**Celery task routing** — both on the `arrange` queue:
```python
"decompose.run": {"queue": "arrange"},
"assemble.run": {"queue": "arrange"},
```

**Runner dispatch — `decompose` branch:**
- If `txr_dict is None` (midi_upload), builds it from the bundle via `_bundle_to_transcription()` (same as arrange/condense)
- Passes `txr_dict` as input, receives updated `txr_dict` as output

**Runner dispatch — `assemble` branch:**
- Wraps `txr_dict` in an envelope: `{"transcription": txr_dict, "difficulty": settings.assemble_difficulty}`
- Receives `score_dict` as output (same as arrange)

**Difficulty config** lives in `backend/config.py` settings (e.g. `assemble_difficulty: str = "beginner"`), not on `PipelineConfig`. `PipelineConfig` controls which stages run; stage-specific tuning flows through settings or payload envelopes.

## New Files

| File | Purpose |
|---|---|
| `backend/workers/decompose.py` | Celery task — loads payload, calls DecomposeService, writes output |
| `backend/workers/assemble.py` | Celery task — loads payload, calls AssembleService, writes output |
| `backend/services/decompose.py` | Core logic: musicpy split + skyline fallback |
| `backend/services/assemble.py` | Core logic: beginner arrangement rules, accepts difficulty param |

## Modified Files

| File | Change |
|---|---|
| `shared/shared/contracts.py` | Add `"decompose_assemble"` to `ScorePipelineMode`, add `decompose_assemble` branch to `get_execution_plan()` |
| `backend/jobs/runner.py` | Add `"decompose"` and `"assemble"` to `STEP_TO_TASK`, add dispatch branches in `PipelineRunner.run()` |
| `backend/workers/celery_app.py` | Add task routes for `decompose.run` and `assemble.run` |
| `backend/config.py` | Add `assemble_difficulty` setting |
| `docs/decomposer-prd-mvp.md` | Update to reflect monolith worker approach, remove microservice/container sections |
| `docs/assembler-prd-mvp.md` | Update to reflect monolith worker approach, add difficulty parameter, remove microservice/container sections |

## What Is NOT Changing

- **Existing pipelines** — `arrange`, `condense_transform` paths untouched
- **Data contracts** — `TranscriptionResult`, `PianoScore`, `EngravedOutput` stay as-is
- **Humanize and engrave stages** — work unchanged downstream
- **`_bundle_to_transcription()`** — stays as-is for MIDI upload
- **Frontend** — beyond exposing the pipeline mode toggle, no changes to upload/progress/result flow
- **Existing tests** — no modifications; new tests cover new stages and new mode only

## PRD Updates

Both PRDs will be edited to reflect:

- **Microservice → monolith worker**: remove own Dockerfile, own Celery app, own S3/boto3 config, Railway deployment sections. Replace with monolith worker description using existing `backend/workers/` pattern.
- **S3 claim-check → blob store**: replace S3-specific paths with the existing `BlobStore` abstraction (local filesystem, S3 future). Remove `source_stem` URI references from decomposer output — notes stay inline in `TranscriptionResult.midi_tracks[].notes` arrays, matching the existing contract.
- **Pipeline toggle**: new section describing `ScorePipelineMode = "decompose_assemble"` and how it fits alongside existing modes.
- **Assembler difficulty param**: add `difficulty` parameter to the interface (envelope-based), note only `"beginner"` implemented for MVP.
- **Container/deployment sections**: removed entirely (handled by the monolith's existing Dockerfile and deploy config).
