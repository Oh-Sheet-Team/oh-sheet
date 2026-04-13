# Dual Pipeline (decompose_assemble) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `"decompose_assemble"` as a third `ScorePipelineMode` so users can compare the new decomposer/assembler pipeline against the existing arrangement pipeline on the same input.

**Architecture:** Extend the existing `ScorePipelineMode` / `get_execution_plan()` pattern — the runner swaps `arrange` for `decompose` → `assemble` when the new mode is selected. Both new stages are monolith workers on the `arrange` queue, following the same Celery task pattern as existing workers. Decompose is a TranscriptionResult → TranscriptionResult re-separation; assemble is a TranscriptionResult → PianoScore beginner arrangement.

**Tech Stack:** Python 3.10+, Pydantic, Celery, mido (already installed), musicpy (new dep), music21 (already installed)

**Spec:** `docs/superpowers/specs/2026-04-12-dual-pipeline-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `shared/shared/contracts.py` | Add `"decompose_assemble"` to `ScorePipelineMode`, add routing branch to `get_execution_plan()` |
| `backend/config.py` | Add `assemble_difficulty` setting |
| `backend/workers/celery_app.py` | Add task routes for `decompose.run` and `assemble.run` |
| `backend/jobs/runner.py` | Add `STEP_TO_TASK` entries and dispatch branches for `decompose` and `assemble` |
| `backend/services/decompose.py` | Core decomposer logic: merge tracks, musicpy split, skyline fallback |
| `backend/services/assemble.py` | Core assembler logic: beginner rules (monophony, range, quantization, key transposition) |
| `backend/workers/decompose.py` | Celery task wrapping `DecomposeService` |
| `backend/workers/assemble.py` | Celery task wrapping `AssembleService` |
| `backend/api/routes/stages.py` | Add `/stages/decompose` and `/stages/assemble` orchestrator endpoints |
| `tests/conftest.py` | Register new worker imports for eager mode |
| `tests/test_pipeline_config.py` | Tests for new `get_execution_plan()` routing |
| `tests/test_decompose.py` | Unit tests for `DecomposeService` |
| `tests/test_assemble.py` | Unit tests for `AssembleService` |
| `tests/test_jobs.py` | E2E test for MIDI job through `decompose_assemble` pipeline |
| `docs/decomposer-prd-mvp.md` | Update to monolith worker approach |
| `docs/assembler-prd-mvp.md` | Update to monolith worker approach + difficulty param |

---

### Task 1: Pipeline Routing — ScorePipelineMode + get_execution_plan

**Files:**
- Modify: `shared/shared/contracts.py:338` (ScorePipelineMode) and `:347-365` (get_execution_plan)
- Test: `tests/test_pipeline_config.py`

- [ ] **Step 1: Write failing tests for decompose_assemble routing**

Add to `tests/test_pipeline_config.py`:

```python
def test_decompose_assemble_replaces_arrange_midi_upload() -> None:
    cfg = PipelineConfig(variant="midi_upload", score_pipeline="decompose_assemble")
    assert cfg.get_execution_plan() == [
        "ingest",
        "decompose",
        "assemble",
        "humanize",
        "engrave",
    ]


def test_decompose_assemble_replaces_arrange_audio_upload() -> None:
    cfg = PipelineConfig(variant="audio_upload", score_pipeline="decompose_assemble")
    assert cfg.get_execution_plan() == [
        "ingest",
        "transcribe",
        "decompose",
        "assemble",
        "humanize",
        "engrave",
    ]


def test_decompose_assemble_replaces_arrange_full() -> None:
    cfg = PipelineConfig(variant="full", score_pipeline="decompose_assemble")
    assert cfg.get_execution_plan() == [
        "ingest",
        "transcribe",
        "decompose",
        "assemble",
        "humanize",
        "engrave",
    ]


def test_decompose_assemble_replaces_arrange_sheet_only() -> None:
    cfg = PipelineConfig(variant="sheet_only", score_pipeline="decompose_assemble")
    assert cfg.get_execution_plan() == [
        "ingest",
        "transcribe",
        "decompose",
        "assemble",
        "engrave",
    ]


def test_decompose_assemble_with_skip_humanizer() -> None:
    cfg = PipelineConfig(
        variant="audio_upload",
        score_pipeline="decompose_assemble",
        skip_humanizer=True,
    )
    assert cfg.get_execution_plan() == [
        "ingest",
        "transcribe",
        "decompose",
        "assemble",
        "engrave",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline_config.py -v`
Expected: FAIL — Pydantic rejects `"decompose_assemble"` as invalid literal value

- [ ] **Step 3: Update ScorePipelineMode and get_execution_plan**

In `shared/shared/contracts.py`, change:

```python
ScorePipelineMode = Literal["arrange", "condense_transform", "decompose_assemble"]
```

And in `get_execution_plan()`, add the `decompose_assemble` branch after the `condense_transform` branch:

```python
        if self.score_pipeline == "condense_transform":
            try:
                idx = plan.index("arrange")
            except ValueError:
                pass
            else:
                plan[idx : idx + 1] = ["condense", "transform"]
        elif self.score_pipeline == "decompose_assemble":
            try:
                idx = plan.index("arrange")
            except ValueError:
                pass
            else:
                plan[idx : idx + 1] = ["decompose", "assemble"]
        return plan
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pipeline_config.py -v`
Expected: All PASS (existing + new)

- [ ] **Step 5: Commit**

```bash
git add shared/shared/contracts.py tests/test_pipeline_config.py
git commit -m "feat: add decompose_assemble to ScorePipelineMode routing"
```

---

### Task 2: Config + Celery Wiring

**Files:**
- Modify: `backend/config.py:503` (add setting)
- Modify: `backend/workers/celery_app.py:18-26` (add routes)
- Modify: `backend/jobs/runner.py:40-48` (add STEP_TO_TASK entries)

- [ ] **Step 1: Add assemble_difficulty setting**

In `backend/config.py`, add before the `score_pipeline` line (around line 501):

```python
    # Difficulty level for the assembler stage. Only "beginner" is implemented.
    # Env: ``OHSHEET_ASSEMBLE_DIFFICULTY``.
    assemble_difficulty: str = "beginner"
```

- [ ] **Step 2: Add Celery task routes**

In `backend/workers/celery_app.py`, add to the `task_routes` dict:

```python
        "decompose.run": {"queue": "arrange"},
        "assemble.run": {"queue": "arrange"},
```

- [ ] **Step 3: Add STEP_TO_TASK entries**

In `backend/jobs/runner.py`, add to the `STEP_TO_TASK` dict:

```python
    "decompose": "decompose.run",
    "assemble": "assemble.run",
```

- [ ] **Step 4: Run existing tests to verify nothing breaks**

Run: `pytest tests/ -v`
Expected: All existing tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/config.py backend/workers/celery_app.py backend/jobs/runner.py
git commit -m "feat: wire decompose/assemble into Celery routing and config"
```

---

### Task 3: DecomposeService — Core Logic

**Files:**
- Create: `backend/services/decompose.py`
- Test: `tests/test_decompose.py`

- [ ] **Step 1: Write failing tests for DecomposeService**

Create `tests/test_decompose.py`:

```python
"""Unit tests for the decompose service."""
from __future__ import annotations

import pytest

from shared.contracts import (
    HarmonicAnalysis,
    InstrumentRole,
    MidiTrack,
    Note,
    QualitySignal,
    TempoMapEntry,
    TranscriptionResult,
)

from backend.services.decompose import DecomposeService


def _make_txr(notes_per_track: list[list[Note]], roles: list[InstrumentRole] | None = None) -> TranscriptionResult:
    """Helper to build a TranscriptionResult with given note lists."""
    if roles is None:
        roles = [InstrumentRole.PIANO] * len(notes_per_track)
    tracks = [
        MidiTrack(notes=notes, instrument=role, program=0, confidence=0.9)
        for notes, role in zip(notes_per_track, roles)
    ]
    return TranscriptionResult(
        midi_tracks=tracks,
        analysis=HarmonicAnalysis(
            key="C:major",
            time_signature=(4, 4),
            tempo_map=[TempoMapEntry(time_sec=0.0, beat=0.0, bpm=120.0)],
            chords=[],
            sections=[],
        ),
        quality=QualitySignal(overall_confidence=0.9),
    )


def test_produces_exactly_two_tracks():
    """Decomposer must always output exactly two tracks: melody and other."""
    notes = [
        Note(pitch=72, onset_sec=0.0, offset_sec=0.5, velocity=80),
        Note(pitch=60, onset_sec=0.0, offset_sec=0.5, velocity=60),
        Note(pitch=48, onset_sec=0.0, offset_sec=0.5, velocity=60),
    ]
    txr = _make_txr([notes])
    result = DecomposeService().run(txr)

    assert len(result.midi_tracks) == 2
    roles = {t.instrument for t in result.midi_tracks}
    assert roles == {InstrumentRole.MELODY, InstrumentRole.OTHER}


def test_merges_all_input_tracks():
    """Notes from multiple input tracks should all appear in the output."""
    track1 = [Note(pitch=72, onset_sec=0.0, offset_sec=0.5, velocity=80)]
    track2 = [Note(pitch=48, onset_sec=0.0, offset_sec=0.5, velocity=60)]
    txr = _make_txr(
        [track1, track2],
        roles=[InstrumentRole.MELODY, InstrumentRole.BASS],
    )
    result = DecomposeService().run(txr)

    total_out = sum(len(t.notes) for t in result.midi_tracks)
    total_in = len(track1) + len(track2)
    assert total_out == total_in


def test_melody_track_is_monophonic():
    """Melody track should have at most one note sounding at any onset."""
    # Three simultaneous notes — only the highest should be melody
    notes = [
        Note(pitch=72, onset_sec=0.0, offset_sec=1.0, velocity=80),
        Note(pitch=60, onset_sec=0.0, offset_sec=1.0, velocity=70),
        Note(pitch=48, onset_sec=0.0, offset_sec=1.0, velocity=60),
    ]
    txr = _make_txr([notes])
    result = DecomposeService().run(txr)

    melody = next(t for t in result.midi_tracks if t.instrument == InstrumentRole.MELODY)
    # Group by onset — each onset should have exactly 1 note
    onsets: dict[float, int] = {}
    for n in melody.notes:
        onsets[n.onset_sec] = onsets.get(n.onset_sec, 0) + 1
    assert all(count == 1 for count in onsets.values())


def test_preserves_analysis_and_quality():
    """Analysis and quality signal must pass through unchanged."""
    notes = [Note(pitch=60, onset_sec=0.0, offset_sec=0.5, velocity=80)]
    txr = _make_txr([notes])
    result = DecomposeService().run(txr)

    assert result.analysis.key == txr.analysis.key
    assert result.analysis.tempo_map == txr.analysis.tempo_map
    assert result.schema_version == txr.schema_version


def test_empty_input_returns_empty_tracks():
    """An input with no notes should produce two empty tracks."""
    txr = _make_txr([[]])
    result = DecomposeService().run(txr)

    assert len(result.midi_tracks) == 2
    assert all(len(t.notes) == 0 for t in result.midi_tracks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_decompose.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.decompose'`

- [ ] **Step 3: Implement DecomposeService**

Create `backend/services/decompose.py`:

```python
"""Decompose stage — re-separate transcription tracks into melody + accompaniment.

Takes a TranscriptionResult (from any source — audio transcription or MIDI
passthrough) and produces a new TranscriptionResult with exactly two tracks:
  - melody (InstrumentRole.MELODY): monophonic lead line
  - other (InstrumentRole.OTHER): everything else (chords + bass)

Algorithm:
  1. Merge all notes from all input tracks (ignore existing roles)
  2. Sort by onset time
  3. Extract melody via skyline algorithm (highest pitch at each time slot)
  4. Remaining notes become the accompaniment track
"""
from __future__ import annotations

import logging

from shared.contracts import (
    InstrumentRole,
    MidiTrack,
    Note,
    TranscriptionResult,
)

log = logging.getLogger(__name__)

# Skyline resolution: quantize time to 16th-note intervals for overlap detection.
_SKYLINE_GRID = 0.0625  # seconds (≈ 16th note at 120 BPM)


class DecomposeService:
    def run(self, txr: TranscriptionResult) -> TranscriptionResult:
        # 1. Merge all notes from all tracks, ignoring existing roles.
        all_notes: list[Note] = []
        for track in txr.midi_tracks:
            all_notes.extend(track.notes)

        if not all_notes:
            return txr.model_copy(
                update={
                    "midi_tracks": [
                        MidiTrack(notes=[], instrument=InstrumentRole.MELODY, program=0, confidence=0.9),
                        MidiTrack(notes=[], instrument=InstrumentRole.OTHER, program=0, confidence=0.9),
                    ],
                },
            )

        all_notes.sort(key=lambda n: (n.onset_sec, -n.pitch))

        melody_notes, accomp_notes = self._skyline_split(all_notes)

        log.info(
            "decompose: %d input notes → %d melody + %d accompaniment",
            len(all_notes),
            len(melody_notes),
            len(accomp_notes),
        )

        return txr.model_copy(
            update={
                "midi_tracks": [
                    MidiTrack(
                        notes=melody_notes,
                        instrument=InstrumentRole.MELODY,
                        program=0,
                        confidence=0.9,
                    ),
                    MidiTrack(
                        notes=accomp_notes,
                        instrument=InstrumentRole.OTHER,
                        program=0,
                        confidence=0.9,
                    ),
                ],
            },
        )

    def _skyline_split(self, notes: list[Note]) -> tuple[list[Note], list[Note]]:
        """Skyline algorithm: at each time slot, the highest-pitched note is melody.

        Groups notes by quantized onset time. Within each group, the note with
        the highest pitch becomes melody; all others become accompaniment.
        """
        # Group notes by quantized onset
        groups: dict[int, list[Note]] = {}
        for note in notes:
            slot = round(note.onset_sec / _SKYLINE_GRID)
            groups.setdefault(slot, []).append(note)

        melody: list[Note] = []
        accomp: list[Note] = []

        for slot in sorted(groups):
            group = groups[slot]
            # Sort by pitch descending — highest is melody
            group.sort(key=lambda n: -n.pitch)
            melody.append(group[0])
            accomp.extend(group[1:])

        return melody, accomp
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_decompose.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/decompose.py tests/test_decompose.py
git commit -m "feat: add DecomposeService with skyline melody extraction"
```

---

### Task 4: AssembleService — Core Logic

**Files:**
- Create: `backend/services/assemble.py`
- Test: `tests/test_assemble.py`

- [ ] **Step 1: Write failing tests for AssembleService**

Create `tests/test_assemble.py`:

```python
"""Unit tests for the assemble service."""
from __future__ import annotations

import pytest

from shared.contracts import (
    HarmonicAnalysis,
    InstrumentRole,
    MidiTrack,
    Note,
    QualitySignal,
    TempoMapEntry,
    TranscriptionResult,
)

from backend.services.assemble import AssembleService


def _make_txr(
    melody_notes: list[Note],
    accomp_notes: list[Note],
    key: str = "C:major",
    bpm: float = 120.0,
) -> TranscriptionResult:
    """Build a TranscriptionResult with melody + other tracks."""
    return TranscriptionResult(
        midi_tracks=[
            MidiTrack(notes=melody_notes, instrument=InstrumentRole.MELODY, program=0, confidence=0.9),
            MidiTrack(notes=accomp_notes, instrument=InstrumentRole.OTHER, program=0, confidence=0.9),
        ],
        analysis=HarmonicAnalysis(
            key=key,
            time_signature=(4, 4),
            tempo_map=[TempoMapEntry(time_sec=0.0, beat=0.0, bpm=bpm)],
            chords=[],
            sections=[],
        ),
        quality=QualitySignal(overall_confidence=0.9),
    )


def test_melody_goes_to_right_hand():
    """All melody notes should appear in right_hand."""
    melody = [Note(pitch=72, onset_sec=0.0, offset_sec=0.5, velocity=80)]
    accomp = [Note(pitch=48, onset_sec=0.0, offset_sec=0.5, velocity=60)]
    txr = _make_txr(melody, accomp)

    score = AssembleService().run(txr, difficulty="beginner")
    assert len(score.right_hand) == 1
    assert score.right_hand[0].pitch == 72


def test_bass_goes_to_left_hand():
    """Lowest accompaniment note at each beat should appear in left_hand."""
    melody = [Note(pitch=72, onset_sec=0.0, offset_sec=0.5, velocity=80)]
    accomp = [Note(pitch=48, onset_sec=0.0, offset_sec=0.5, velocity=60)]
    txr = _make_txr(melody, accomp)

    score = AssembleService().run(txr, difficulty="beginner")
    assert len(score.left_hand) == 1
    assert score.left_hand[0].pitch == 48


def test_right_hand_is_monophonic():
    """RH should have max 1 note per quantized beat."""
    melody = [
        Note(pitch=72, onset_sec=0.0, offset_sec=0.5, velocity=80),
        Note(pitch=74, onset_sec=0.0, offset_sec=0.5, velocity=70),
    ]
    txr = _make_txr(melody, [])

    score = AssembleService().run(txr, difficulty="beginner")
    # Group by onset_beat — each should have at most 1 note
    onsets: dict[float, int] = {}
    for n in score.right_hand:
        onsets[n.onset_beat] = onsets.get(n.onset_beat, 0) + 1
    assert all(count == 1 for count in onsets.values())


def test_left_hand_is_monophonic():
    """LH should have max 1 note per quantized beat."""
    accomp = [
        Note(pitch=48, onset_sec=0.0, offset_sec=0.5, velocity=60),
        Note(pitch=52, onset_sec=0.0, offset_sec=0.5, velocity=60),
        Note(pitch=55, onset_sec=0.0, offset_sec=0.5, velocity=60),
    ]
    txr = _make_txr([], accomp)

    score = AssembleService().run(txr, difficulty="beginner")
    onsets: dict[float, int] = {}
    for n in score.left_hand:
        onsets[n.onset_beat] = onsets.get(n.onset_beat, 0) + 1
    assert all(count == 1 for count in onsets.values())


def test_eighth_note_quantization():
    """All onsets and durations should snap to 0.5-beat grid."""
    # onset_sec=0.1 at 120 BPM = 0.2 beats → should snap to 0.0
    melody = [Note(pitch=72, onset_sec=0.1, offset_sec=0.4, velocity=80)]
    txr = _make_txr(melody, [])

    score = AssembleService().run(txr, difficulty="beginner")
    for n in score.right_hand:
        assert n.onset_beat % 0.5 == 0.0
        assert n.duration_beat % 0.5 == 0.0 or n.duration_beat >= 0.5


def test_range_clamping_rh():
    """RH notes outside C4-C6 (60-84) should be octave-shifted inward."""
    # Pitch 90 (above C6=84) should be shifted down by one octave to 78
    melody = [Note(pitch=90, onset_sec=0.0, offset_sec=0.5, velocity=80)]
    txr = _make_txr(melody, [])

    score = AssembleService().run(txr, difficulty="beginner")
    assert all(60 <= n.pitch <= 84 for n in score.right_hand)


def test_range_clamping_lh():
    """LH notes outside C2-B3 (36-59) should be octave-shifted inward."""
    # Pitch 30 (below C2=36) should be shifted up by one octave to 42
    accomp = [Note(pitch=30, onset_sec=0.0, offset_sec=0.5, velocity=60)]
    txr = _make_txr([], accomp)

    score = AssembleService().run(txr, difficulty="beginner")
    assert all(36 <= n.pitch <= 59 for n in score.left_hand)


def test_accompaniment_above_middle_c_discarded_from_rh():
    """Accompaniment notes above middle C should NOT go to RH."""
    melody = [Note(pitch=72, onset_sec=0.0, offset_sec=0.5, velocity=80)]
    # Accompaniment note above middle C — should be discarded entirely
    accomp = [Note(pitch=65, onset_sec=0.5, offset_sec=1.0, velocity=60)]
    txr = _make_txr(melody, accomp)

    score = AssembleService().run(txr, difficulty="beginner")
    # RH should only have the melody note, not the accompaniment
    assert len(score.right_hand) == 1
    assert score.right_hand[0].pitch == 72


def test_difficulty_not_implemented_raises():
    """Non-beginner difficulty should raise NotImplementedError."""
    txr = _make_txr([], [])
    with pytest.raises(NotImplementedError):
        AssembleService().run(txr, difficulty="advanced")


def test_score_metadata():
    """Output metadata should have correct difficulty and key."""
    melody = [Note(pitch=72, onset_sec=0.0, offset_sec=0.5, velocity=80)]
    txr = _make_txr(melody, [], key="C:major")

    score = AssembleService().run(txr, difficulty="beginner")
    assert score.metadata.difficulty == "beginner"
    assert score.metadata.key == "C:major"


def test_note_ids_are_unique():
    """Each ScoreNote should have a unique id."""
    melody = [
        Note(pitch=72, onset_sec=0.0, offset_sec=0.5, velocity=80),
        Note(pitch=74, onset_sec=0.5, offset_sec=1.0, velocity=80),
    ]
    accomp = [
        Note(pitch=48, onset_sec=0.0, offset_sec=0.5, velocity=60),
        Note(pitch=50, onset_sec=0.5, offset_sec=1.0, velocity=60),
    ]
    txr = _make_txr(melody, accomp)

    score = AssembleService().run(txr, difficulty="beginner")
    all_ids = [n.id for n in score.right_hand + score.left_hand]
    assert len(all_ids) == len(set(all_ids))


def test_empty_input_returns_empty_score():
    """No notes in → empty score out."""
    txr = _make_txr([], [])
    score = AssembleService().run(txr, difficulty="beginner")

    assert len(score.right_hand) == 0
    assert len(score.left_hand) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_assemble.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.assemble'`

- [ ] **Step 3: Implement AssembleService**

Create `backend/services/assemble.py`:

```python
"""Assemble stage — strict rule-based piano arrangement.

Takes a TranscriptionResult (expected from the decomposer: melody + other tracks)
and produces a PianoScore using rigid difficulty-specific rules.

Currently only "beginner" difficulty is implemented:
  - 8th-note quantization (0.5-beat grid)
  - Melody → RH, max 1 note per beat (highest pitch wins)
  - Lowest accompaniment note per beat → LH, max 1 note per beat
  - Accompaniment notes above middle C discarded
  - RH range: C4–C6 (MIDI 60–84), LH range: C2–B3 (MIDI 36–59)
  - Notes outside range octave-shifted inward
"""
from __future__ import annotations

import logging

from shared.contracts import (
    SCHEMA_VERSION,
    HarmonicAnalysis,
    InstrumentRole,
    MidiTrack,
    Note,
    PianoScore,
    ScoreMetadata,
    ScoreNote,
    ScoreSection,
    ScoreChordEvent,
    Section,
    RealtimeChordEvent,
    TempoMapEntry,
    TranscriptionResult,
    sec_to_beat,
)

log = logging.getLogger(__name__)

# Beginner constants
_QUANT_GRID = 0.5  # 8th note
_RH_MIN = 60       # C4
_RH_MAX = 84       # C6
_LH_MIN = 36       # C2
_LH_MAX = 59       # B3
_SPLIT_PITCH = 60  # Middle C


def _quantize(value: float, grid: float) -> float:
    """Snap a value to the nearest grid point."""
    return round(value / grid) * grid


def _clamp_pitch(pitch: int, lo: int, hi: int) -> int:
    """Octave-shift a pitch until it falls within [lo, hi]."""
    while pitch > hi:
        pitch -= 12
    while pitch < lo:
        pitch += 12
    return pitch


def _sec_to_beat_notes(
    notes: list[Note],
    tempo_map: list[TempoMapEntry],
) -> list[tuple[float, float, Note]]:
    """Convert notes from seconds to beats, return (onset_beat, duration_beat, original)."""
    result = []
    for n in notes:
        onset = sec_to_beat(n.onset_sec, tempo_map)
        offset = sec_to_beat(n.offset_sec, tempo_map)
        duration = max(offset - onset, 0.01)
        result.append((onset, duration, n))
    return result


class AssembleService:
    def run(self, txr: TranscriptionResult, *, difficulty: str = "beginner") -> PianoScore:
        if difficulty != "beginner":
            raise NotImplementedError(f"difficulty={difficulty!r} is not implemented; only 'beginner' is supported")

        tempo_map = txr.analysis.tempo_map
        melody_notes: list[Note] = []
        accomp_notes: list[Note] = []

        for track in txr.midi_tracks:
            if track.instrument == InstrumentRole.MELODY:
                melody_notes.extend(track.notes)
            else:
                accomp_notes.extend(track.notes)

        rh = self._build_right_hand(melody_notes, tempo_map)
        lh = self._build_left_hand(accomp_notes, tempo_map)

        # Convert chords and sections to beat domain
        chord_symbols = [
            ScoreChordEvent(
                beat=sec_to_beat(c.time_sec, tempo_map),
                duration_beat=max(
                    sec_to_beat(c.time_sec + c.duration_sec, tempo_map)
                    - sec_to_beat(c.time_sec, tempo_map),
                    0.01,
                ),
                label=c.label,
                root=c.root,
                confidence=c.confidence,
            )
            for c in txr.analysis.chords
        ]
        sections = [
            ScoreSection(
                start_beat=sec_to_beat(s.start_sec, tempo_map),
                end_beat=sec_to_beat(s.end_sec, tempo_map),
                label=s.label,
            )
            for s in txr.analysis.sections
        ]

        log.info(
            "assemble beginner: %d melody → %d RH, %d accomp → %d LH",
            len(melody_notes), len(rh),
            len(accomp_notes), len(lh),
        )

        return PianoScore(
            schema_version=SCHEMA_VERSION,
            right_hand=rh,
            left_hand=lh,
            metadata=ScoreMetadata(
                key=txr.analysis.key,
                time_signature=txr.analysis.time_signature,
                tempo_map=tempo_map,
                difficulty="beginner",
                sections=sections,
                chord_symbols=chord_symbols,
            ),
        )

    def _build_right_hand(
        self,
        melody_notes: list[Note],
        tempo_map: list[TempoMapEntry],
    ) -> list[ScoreNote]:
        """Melody → RH: quantize, enforce monophony (highest pitch wins), clamp range."""
        beat_notes = _sec_to_beat_notes(melody_notes, tempo_map)

        # Quantize onsets and durations to 8th-note grid
        quantized: list[tuple[float, float, Note]] = []
        for onset, dur, note in beat_notes:
            q_onset = _quantize(onset, _QUANT_GRID)
            q_dur = max(_quantize(dur, _QUANT_GRID), _QUANT_GRID)
            quantized.append((q_onset, q_dur, note))

        # Enforce monophony: group by quantized onset, keep highest pitch
        groups: dict[float, list[tuple[float, float, Note]]] = {}
        for onset, dur, note in quantized:
            groups.setdefault(onset, []).append((onset, dur, note))

        rh: list[ScoreNote] = []
        idx = 0
        for onset in sorted(groups):
            group = groups[onset]
            # Highest pitch wins
            group.sort(key=lambda t: -t[2].pitch)
            _, dur, note = group[0]
            pitch = _clamp_pitch(note.pitch, _RH_MIN, _RH_MAX)
            rh.append(ScoreNote(
                id=f"rh-{idx:04d}",
                pitch=pitch,
                onset_beat=onset,
                duration_beat=dur,
                velocity=min(max(note.velocity, 1), 127),
                voice=1,
            ))
            idx += 1

        return rh

    def _build_left_hand(
        self,
        accomp_notes: list[Note],
        tempo_map: list[TempoMapEntry],
    ) -> list[ScoreNote]:
        """Accompaniment → LH: discard above middle C, quantize, enforce monophony (lowest wins), clamp range."""
        # Filter: only notes below middle C
        below_split = [n for n in accomp_notes if n.pitch < _SPLIT_PITCH]

        beat_notes = _sec_to_beat_notes(below_split, tempo_map)

        # Quantize
        quantized: list[tuple[float, float, Note]] = []
        for onset, dur, note in beat_notes:
            q_onset = _quantize(onset, _QUANT_GRID)
            q_dur = max(_quantize(dur, _QUANT_GRID), _QUANT_GRID)
            quantized.append((q_onset, q_dur, note))

        # Enforce monophony: group by quantized onset, keep lowest pitch
        groups: dict[float, list[tuple[float, float, Note]]] = {}
        for onset, dur, note in quantized:
            groups.setdefault(onset, []).append((onset, dur, note))

        lh: list[ScoreNote] = []
        idx = 0
        for onset in sorted(groups):
            group = groups[onset]
            # Lowest pitch wins
            group.sort(key=lambda t: t[2].pitch)
            _, dur, note = group[0]
            pitch = _clamp_pitch(note.pitch, _LH_MIN, _LH_MAX)
            lh.append(ScoreNote(
                id=f"lh-{idx:04d}",
                pitch=pitch,
                onset_beat=onset,
                duration_beat=dur,
                velocity=min(max(note.velocity, 1), 127),
                voice=1,
            ))
            idx += 1

        return lh
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_assemble.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/assemble.py tests/test_assemble.py
git commit -m "feat: add AssembleService with beginner difficulty rules"
```

---

### Task 5: Celery Worker Tasks

**Files:**
- Create: `backend/workers/decompose.py`
- Create: `backend/workers/assemble.py`
- Modify: `tests/conftest.py:8-16` (register imports)

- [ ] **Step 1: Create decompose worker task**

Create `backend/workers/decompose.py`:

```python
"""Celery task for the decompose pipeline stage."""
from shared.contracts import TranscriptionResult
from shared.storage.local import LocalBlobStore

from backend.config import settings
from backend.services.decompose import DecomposeService
from backend.workers.celery_app import celery_app


@celery_app.task(name="decompose.run")
def run(job_id: str, payload_uri: str) -> str:
    blob = LocalBlobStore(settings.blob_root)
    raw = blob.get_json(payload_uri)
    txr = TranscriptionResult.model_validate(raw)

    service = DecomposeService()
    result = service.run(txr)

    output_uri = blob.put_json(
        f"jobs/{job_id}/decompose/output.json",
        result.model_dump(mode="json"),
    )
    return output_uri
```

- [ ] **Step 2: Create assemble worker task**

Create `backend/workers/assemble.py`:

```python
"""Celery task for the assemble pipeline stage."""
from shared.contracts import TranscriptionResult
from shared.storage.local import LocalBlobStore

from backend.config import settings
from backend.services.assemble import AssembleService
from backend.workers.celery_app import celery_app


@celery_app.task(name="assemble.run")
def run(job_id: str, payload_uri: str) -> str:
    blob = LocalBlobStore(settings.blob_root)
    raw = blob.get_json(payload_uri)

    # The runner wraps the payload in an envelope with difficulty.
    # If no envelope, treat raw as TranscriptionResult directly.
    if "transcription" in raw:
        txr = TranscriptionResult.model_validate(raw["transcription"])
        difficulty = raw.get("difficulty", settings.assemble_difficulty)
    else:
        txr = TranscriptionResult.model_validate(raw)
        difficulty = settings.assemble_difficulty

    service = AssembleService()
    result = service.run(txr, difficulty=difficulty)

    output_uri = blob.put_json(
        f"jobs/{job_id}/assemble/output.json",
        result.model_dump(mode="json"),
    )
    return output_uri
```

- [ ] **Step 3: Register workers in conftest.py**

In `tests/conftest.py`, add two imports alongside the existing worker imports (around lines 8-16):

```python
import backend.workers.assemble  # noqa: F401
import backend.workers.decompose  # noqa: F401
```

- [ ] **Step 4: Run all tests to verify nothing breaks**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/workers/decompose.py backend/workers/assemble.py tests/conftest.py
git commit -m "feat: add decompose and assemble Celery worker tasks"
```

---

### Task 6: Runner Dispatch Branches

**Files:**
- Modify: `backend/jobs/runner.py:290-377` (add elif branches in `PipelineRunner.run`)

- [ ] **Step 1: Write failing E2E test**

Add to `tests/test_jobs.py`:

```python
def test_midi_job_decompose_assemble_pipeline(monkeypatch, client):
    monkeypatch.setattr(settings, "score_pipeline", "decompose_assemble")

    midi = client.post(
        "/v1/uploads/midi",
        files={"file": ("a.mid", b"MThd\x00\x00\x00\x06\x00\x00\x00\x00\x00\x00", "audio/midi")},
    ).json()
    create = client.post("/v1/jobs", json={"midi": midi, "title": "Decompose path"}).json()
    job_id = create["job_id"]

    deadline = time.time() + 5
    status = None
    while time.time() < deadline:
        status = client.get(f"/v1/jobs/{job_id}").json()
        if status["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    assert status is not None
    assert status["status"] == "succeeded", status

    with client.websocket_connect(f"/v1/jobs/{job_id}/ws") as ws:
        events = []
        while True:
            event = ws.receive_json()
            events.append(event)
            if event["type"] in ("job_succeeded", "job_failed"):
                break

    completed = [e["stage"] for e in events if e["type"] == "stage_completed"]
    assert "decompose" in completed
    assert "assemble" in completed
    assert "arrange" not in completed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_jobs.py::test_midi_job_decompose_assemble_pipeline -v`
Expected: FAIL — `RuntimeError: unknown stage in execution plan: 'decompose'`

- [ ] **Step 3: Add dispatch branches to PipelineRunner.run**

In `backend/jobs/runner.py`, inside the `for i, step in enumerate(plan):` loop, add two new `elif` branches after the `condense` branch (after line 335) and before the `transform` branch:

```python
                elif step == "decompose":
                    if txr_dict is None:
                        bundle_obj = InputBundle.model_validate(current_payload)
                        log.info(
                            "pipeline job_id=%s decompose: using MIDI→TranscriptionResult passthrough",
                            job_id,
                        )
                        txr_obj = _bundle_to_transcription(bundle_obj)
                        txr_dict = txr_obj.model_dump(mode="json")
                    payload_uri = self._serialize_stage_input(job_id, step, txr_dict)
                    output_uri = await self._dispatch_task(task_name, job_id, payload_uri, config.stage_timeout_sec)
                    txr_dict = self.blob_store.get_json(output_uri)

                elif step == "assemble":
                    if txr_dict is None:
                        raise RuntimeError(
                            "assemble stage requires a TranscriptionResult — none was produced"
                        )
                    assemble_envelope = {
                        "transcription": txr_dict,
                        "difficulty": settings.assemble_difficulty,
                    }
                    payload_uri = self._serialize_stage_input(job_id, step, assemble_envelope)
                    output_uri = await self._dispatch_task(task_name, job_id, payload_uri, config.stage_timeout_sec)
                    score_dict = self.blob_store.get_json(output_uri)
```

Also add the import at top of `backend/jobs/runner.py` if not already present:

```python
from backend.config import settings
```

- [ ] **Step 4: Run E2E test to verify it passes**

Run: `pytest tests/test_jobs.py::test_midi_job_decompose_assemble_pipeline -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/jobs/runner.py tests/test_jobs.py
git commit -m "feat: add decompose/assemble dispatch branches to PipelineRunner"
```

---

### Task 7: Orchestrator Stage Endpoints

**Files:**
- Modify: `backend/api/routes/stages.py` (add /stages/decompose and /stages/assemble)

- [ ] **Step 1: Add decompose and assemble stage endpoints**

In `backend/api/routes/stages.py`, add the imports at the top:

```python
from backend.services.decompose import DecomposeService
from backend.services.assemble import AssembleService
```

Then add the two new endpoints (follow the pattern of the existing arrange endpoint):

```python
@router.post("/stages/decompose", response_model=WorkerResponse)
async def stage_decompose(
    cmd: OrchestratorCommand,
    blob: Annotated[LocalBlobStore, Depends(get_blob_store)],
) -> WorkerResponse:
    decompose = DecomposeService()

    async def coro(payload: TranscriptionResult) -> TranscriptionResult:
        return decompose.run(payload)

    return await _run_stage(
        cmd,
        blob,
        input_model=TranscriptionResult,
        coro=coro,
        output_key="decompose.json",
    )


@router.post("/stages/assemble", response_model=WorkerResponse)
async def stage_assemble(
    cmd: OrchestratorCommand,
    blob: Annotated[LocalBlobStore, Depends(get_blob_store)],
) -> WorkerResponse:
    assemble = AssembleService()

    async def coro(payload: TranscriptionResult) -> PianoScore:
        return assemble.run(payload, difficulty="beginner")

    return await _run_stage(
        cmd,
        blob,
        input_model=TranscriptionResult,
        coro=coro,
        output_key="assemble.json",
    )
```

- [ ] **Step 2: Run full test suite to verify nothing breaks**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add backend/api/routes/stages.py
git commit -m "feat: add /stages/decompose and /stages/assemble orchestrator endpoints"
```

---

### Task 8: Update PRDs

**Files:**
- Modify: `docs/decomposer-prd-mvp.md`
- Modify: `docs/assembler-prd-mvp.md`

- [ ] **Step 1: Rewrite decomposer PRD**

Replace the contents of `docs/decomposer-prd-mvp.md` with:

```markdown
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
```

- [ ] **Step 2: Rewrite assembler PRD**

Replace the contents of `docs/assembler-prd-mvp.md` with:

```markdown
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
```

- [ ] **Step 3: Commit**

```bash
git add docs/decomposer-prd-mvp.md docs/assembler-prd-mvp.md
git commit -m "docs: update decomposer and assembler PRDs for monolith worker approach"
```

---

### Task 9: Add musicpy Dependency

**Files:**
- Modify: `pyproject.toml`

**Note:** The current DecomposeService implementation uses the skyline algorithm only (no musicpy dependency). musicpy integration is a future enhancement per the PRD. However, the PRD lists musicpy in the tech stack, so add it as an optional dependency now for future use.

- [ ] **Step 1: Check if musicpy is needed for MVP**

The `DecomposeService` in Task 3 uses only the skyline algorithm — no musicpy import. musicpy's `split_all()` is listed as a future enhancement. Skip adding the dependency for now — it can be added when musicpy integration is implemented.

This task is a no-op for MVP. Move on.

- [ ] **Step 2: Commit (skip — nothing to commit)**

---

### Task 10: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Run linter**

Run: `make lint`
Expected: No errors

- [ ] **Step 3: Run type checker**

Run: `make typecheck`
Expected: No errors

- [ ] **Step 4: Manual smoke test (optional)**

```bash
make backend
# In another terminal, upload a MIDI file with decompose_assemble mode:
# Set OHSHEET_SCORE_PIPELINE=decompose_assemble in .env, then:
curl -X POST http://localhost:8000/v1/uploads/midi -F "file=@test.mid"
# Use the returned JSON to create a job and check the result
```

- [ ] **Step 5: Final commit if any fixups needed**

```bash
git add -A
git commit -m "fix: address lint/type issues from dual pipeline implementation"
```
