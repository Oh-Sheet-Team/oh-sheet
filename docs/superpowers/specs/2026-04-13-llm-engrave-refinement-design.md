# LLM Engrave Refinement Design

**Date**: 2026-04-13
**Status**: Approved
**Linear**: GAU-105

## Overview

Add a new pipeline stage — `refine` — that uses an LLM to research the song being transcribed and produce human-readable metadata (title, composer, key, time signature, tempo marking, section structure, repeats, staff-split hint) that `engrave` consumes to render a more conventional, performer-friendly score.

The LLM does **not** touch notes. It contributes structural and presentational metadata only; deterministic code continues to own pitch, rhythm, and voicing.

## Rationale

LLM calls are slow and flaky, with a latency/failure profile very different from the deterministic LilyPond/music21 rendering in `engrave`. A separate stage gives the refinement its own timeout/retry policy, isolates failure, fits the existing `PipelineRunner`/Celery pattern, and lets the output be cached and inspected independently.

## Pipeline Placement

`refine` runs **after** `humanize` and **before** `engrave` for variants that produce a `HumanizedPerformance`. For `sheet_only` (which skips `humanize`), it runs between `arrange` and `engrave`.

| Variant         | Execution plan (enable_refine = true)                                |
|-----------------|----------------------------------------------------------------------|
| `full`          | ingest → transcribe → arrange → humanize → **refine** → engrave      |
| `audio_upload`  | ingest → transcribe → arrange → humanize → **refine** → engrave      |
| `midi_upload`   | ingest → arrange → humanize → **refine** → engrave                   |
| `sheet_only`    | ingest → transcribe → arrange → **refine** → engrave                 |

`condense_transform` substitution for `arrange` stays unchanged; `refine` slots in the same position relative to `humanize`/`engrave`.

## Contract Changes

`shared/shared/contracts.py` — `SCHEMA_VERSION` bumps from `3.0.0` to `3.1.0`. All changes are additive with safe defaults; existing producers and consumers continue to validate.

### New Model: `Repeat`

```python
class Repeat(BaseModel):
    start_beat: float
    end_beat: float
    kind: Literal["simple", "with_endings"]
```

Beat-based anchoring is consistent with the rest of `PianoScore`. `with_endings` covers 1st/2nd volta brackets. D.C./D.S./Coda deferred until `engrave` can render them reliably.

### Extended: `ScoreSection`

Add one optional field:

```python
class ScoreSection(BaseModel):
    start_beat: float
    end_beat: float
    label: SectionLabel                         # closed enum, unchanged
    phrase_boundaries: list[float] = Field(default_factory=list)
    custom_label: str | None = None             # NEW — free-form refinement, falls back to enum label
```

The LLM picks the closest `SectionLabel` enum value and may add a human-readable `custom_label` ("Bridge → Solo"); engrave renders `custom_label` when present, otherwise the enum.

### Extended: `ScoreMetadata`

```python
class ScoreMetadata(BaseModel):
    key: str
    time_signature: tuple[int, int]
    tempo_map: list[TempoMapEntry]
    difficulty: Difficulty
    sections: list[ScoreSection] = Field(default_factory=list)
    chord_symbols: list[ScoreChordEvent] = Field(default_factory=list)
    # NEW fields (all optional, populated by refine):
    title: str | None = None
    composer: str | None = None
    arranger: str | None = None
    tempo_marking: str | None = None            # e.g., "Andante"
    staff_split_hint: int | None = None         # MIDI pitch, engrave default ~60
    repeats: list[Repeat] = Field(default_factory=list)
```

### Engrave field resolution

`engrave` reads each display field with this precedence:

1. `ScoreMetadata.title` / `.composer` (refine output)
2. `InputMetadata.title` / `.artist` (user-supplied)
3. Defaults (`"Untitled"` / `"Unknown"`)

Refine is authoritative when present; engrave does not invent values.

## LLM I/O

### Provider

Anthropic Claude via the official Python SDK.

- Default model: `claude-sonnet-4-6`.
- Budget model: `claude-haiku-4-5-20251001`, selectable via `OHSHEET_REFINE_MODEL`.
- Uses the built-in `web_search` tool (no second integration).
- Structured output via tool-use: the model is forced to call a single `submit_refinements` tool whose schema mirrors the refinement payload.

### Prompt input

The prompt is assembled from a compact digest of the input score and the user's metadata hint. Individual notes are **not** sent — only aggregated harmonic/rhythmic signal.

```
SYSTEM: You are a music editor refining an automatically-generated piano
        transcription. Use web_search to confirm the song's identity, canonical
        key, form, and tempo marking. Then call submit_refinements with your
        conclusions. Do not invent values you cannot justify.

USER:
  User-provided hint: title="claire de lune", artist=null
  Detected from transcription:
    key = Db major
    time_signature = 4/4
    tempo_bpm = 66
    duration_measures = 128
    pitch_range = C2–E6
  Per-bar chord sketch (Harte notation):
    bars 1–8:   Db | Ab/C | Bbm7 | Gb | ...
    bars 9–16:  ...
    ...
```

Chord sketch granularity: **one chord per bar** (compact, typically <100 lines for a 3-minute song). Derived from `TranscriptionResult.analysis.chords` bucketed by measure.

### Tool definitions

Two tools exposed to the model:

1. **`web_search`** — the built-in Anthropic tool. Capped at **5 calls per refinement** via tracking in the service loop (abort with fallback if exceeded).
2. **`submit_refinements`** — terminal tool whose input schema is the new refinement payload (title, composer, arranger, key_signature, time_signature, tempo_bpm, tempo_marking, sections, repeats, staff_split_hint). The service stops the conversation when this is called, validates the arguments against Pydantic, and merges them into the envelope.

### Output merging

The service takes the original envelope (`PianoScore` or `HumanizedPerformance`) and overwrites only the LLM-contributed fields on `ScoreMetadata`. Notes, voices, chord symbols, existing phrase boundaries — all preserved.

## Worker & Service Architecture

### Files

- `backend/workers/refine.py` — thin Celery task: read input from blob, call service, write output blob, emit `JobEvent`s.
- `backend/services/refine.py` — LLM orchestration: client creation, tool-use loop, retry/timeout/budget enforcement, output validation, merge, caching.
- `backend/services/refine_prompt.py` — pure functions: prompt templates, chord-sketch builder, digest assembly. Easy to unit-test without a network.

### Timeout / retry / fallback policy

| Setting                    | Value                                                    |
|----------------------------|----------------------------------------------------------|
| Per-API-call timeout       | 120s                                                     |
| Overall refine budget      | 300s wall time (covers up to ~5 web_search iterations)   |
| Retry count per API call   | 2 attempts, exponential backoff 1s / 4s                  |
| Retry triggers             | timeout, 5xx, `overloaded_error`, transient network      |
| Stage timeout (outer)      | `PipelineConfig.stage_timeout_sec` (default 600s)        |

**Fallback on any failure** — timeout exceeded, budget exhausted, invalid tool-use output, web_search cap hit without `submit_refinements`, Pydantic validation failure — the stage passes the input envelope through unchanged and appends a warning to `quality.warnings`, for example `"refine: LLM unavailable, passing through"`. Refine is enrichment, never a gate.

### Caching

- Cache key: `sha256(canonical_json(input_envelope) + prompt_version + model_id)` — hash is over the fully serialized input envelope (`PianoScore` or `HumanizedPerformance`) after normalization (sorted keys, fixed float precision), not over the upstream audio file.
- Stored at `blob://refine-cache/{key}.json`.
- Hit → skip LLM call entirely; emit `cache_hit=true` in logs.
- `prompt_version` is a constant string in `refine_prompt.py`; bumping it invalidates the cache.
- No TTL for v1.

### Logging

LLM interaction logs (prompt, tool calls, final tool-use args, retry counts, cache status) go to the same structured logging path as other workers — no dedicated `refine_transcripts/` blob prefix. Sufficient for debugging; avoids a new artifact surface to manage.

## Pipeline Config Plumbing

`shared/shared/contracts.py`:

```python
class PipelineConfig(BaseModel):
    variant: PipelineVariant
    skip_humanizer: bool = False
    enable_refine: bool = True                  # NEW
    stage_timeout_sec: int = 600
    score_pipeline: ScorePipelineMode = "arrange"

    def get_execution_plan(self) -> list[str]:
        ...
        if self.enable_refine and "engrave" in plan:
            # Refine always runs immediately before engrave, regardless of
            # which upstream stages are present (humanize / arrange /
            # condense+transform / skip_humanizer combinations).
            idx = plan.index("engrave")
            plan.insert(idx, "refine")
        return plan
```

Env override via `OHSHEET_REFINE_ENABLED` (default `true`), read into the `PipelineConfig` when the job is created.

## Configuration

Added to `backend/config.py` (Pydantic settings, `OHSHEET_` prefix):

| Env var                      | Default                          | Purpose                              |
|------------------------------|----------------------------------|--------------------------------------|
| `OHSHEET_REFINE_ENABLED`     | `true`                           | Include `refine` in execution plan   |
| `OHSHEET_REFINE_MODEL`       | `claude-sonnet-4-6`              | Anthropic model id                   |
| `OHSHEET_ANTHROPIC_API_KEY`  | (none)                           | Auth for Anthropic API               |
| `OHSHEET_REFINE_MAX_SEARCHES`| `5`                              | Web-search cap per refinement        |
| `OHSHEET_REFINE_BUDGET_SEC`  | `300`                            | Overall wall-time budget             |

Missing API key with `enable_refine=true` logs a warning on boot and forces fallback behavior at runtime (pass-through + warning on each job).

## JobEvent Wiring

Add `"refine"` to the stage allowlist so the frontend progress screen shows it. The frontend keys off the execution plan returned by the backend, so no other frontend changes are required.

## Testing

### Unit tests

- **Fake Anthropic client fixture** — monkeypatched into the service, returns canned tool-use responses. Mirrors the existing `skip_real_transcription` pattern.
- Dedicated fixture `skip_real_refine` to opt into pass-through behavior in tests that exercise adjacent stages.
- Pure unit tests for `refine_prompt.py` covering chord-sketch bucketing and digest formatting (no network).
- Unit tests for the fallback matrix: timeout, budget exceeded, invalid tool args, search cap, missing API key.

### Integration tests

- One VCR-style recorded LLM response committed under `tests/fixtures/refine/` — asserts end-to-end wiring (Celery task → service → merged envelope → engrave input) without live API.

### Live golden-set evaluation

Mirrors the existing transcription eval (`scripts/eval_transcription.py`, `eval/fixtures/clean_midi/`, `make eval`).

- **Fixture set**: `eval/fixtures/refine_golden/` — 10–15 canonical songs spanning classical (Clair de Lune, Für Elise, Gymnopédie No. 1), pop, and game OST. Each fixture contains the input `PianoScore` JSON plus a `ground_truth.json` with expected title, composer, key, time_signature, tempo_bpm, section structure, and repeats.
- **Harness**: `scripts/eval_refine.py` — loads each fixture, runs the **real** refine service against Anthropic, scores output against ground truth, writes `refine-baseline.json` (per-song + aggregate).
- **Metrics**:
  - `title_exact_match_pct`
  - `composer_exact_match_pct`
  - `key_match_pct` (with enharmonic equivalence — Db = C#, etc.)
  - `time_signature_exact_pct`
  - `tempo_within_5bpm_pct`
  - `section_label_f1` (bipartite match against ground-truth sections by overlap)
  - `repeat_f1`
- **Makefile target**: `make eval-refine`. Requires `OHSHEET_ANTHROPIC_API_KEY`. Excluded from default CI (costs money + hits live API); run manually on demand.
- Optional `pytest -m live` marker for a small `tests/live/` that also hits the real API for smoke coverage.

## Out of Scope

- Note-level edits by LLM (covered under approach B's exclusion).
- D.C./D.S./Coda repeat structures (deferred until engrave renders them).
- Fingering generation (future work).
- Multi-provider LLM support (Anthropic only for v1).
- Streaming LLM output to the frontend (refine progress is binary start/done).

## Success Criteria

- `refine` stage ships with all defaults on; existing pipeline variants continue to work.
- Engraved scores for canonical pieces display correct title, composer, key signature, tempo marking, and section labels — verified against the golden-set eval.
- Baseline golden-set metrics captured in `refine-baseline.json`; future PRs diff against it.
- Refine failure (LLM outage, invalid output, timeout) never blocks a pipeline run; `quality.warnings` records the fallback.
- Schema bump to `3.1.0` validates against all existing fixtures without modification.
