"""Unit tests for backend/services/refine_validate.py (STG-04, STG-05; D-13, D-14, D-15)."""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from shared.contracts import (
    ExpressionMap,
    ExpressiveNote,
    HumanizedPerformance,
    PianoScore,
    QualitySignal,
    RefineEditOp,
    ScoreMetadata,
    ScoreNote,
    TempoMapEntry,
)

from backend.services.refine_validate import (
    PIANO_HIGH_MIDI,
    PIANO_LOW_MIDI,
    RefineValidator,
)


@dataclass
class _FakeSettings:
    """Duck-typed Settings stand-in; keeps validator tests independent of env."""
    refine_ghost_velocity_max: int = 40


def _piano_score(rh_notes: list[tuple[int, float, int]] | None = None,
                 lh_notes: list[tuple[int, float, int]] | None = None) -> PianoScore:
    """rh_notes / lh_notes: list of (pitch, onset_beat, velocity) tuples."""
    rh_notes = rh_notes or [(60, 0.0, 80), (64, 1.0, 80)]
    lh_notes = lh_notes or [(48, 0.0, 80), (52, 1.0, 80)]
    return PianoScore(
        right_hand=[
            ScoreNote(id=f"rh-{i:04d}", pitch=p, onset_beat=o,
                      duration_beat=0.5, velocity=v, voice=1)
            for i, (p, o, v) in enumerate(rh_notes)
        ],
        left_hand=[
            ScoreNote(id=f"lh-{i:04d}", pitch=p, onset_beat=o,
                      duration_beat=0.5, velocity=v, voice=1)
            for i, (p, o, v) in enumerate(lh_notes)
        ],
        metadata=ScoreMetadata(
            key="C:major",
            time_signature=(4, 4),
            tempo_map=[TempoMapEntry(time_sec=0.0, beat=0.0, bpm=120.0)],
            difficulty="intermediate",
        ),
    )


def _humanized(score: PianoScore | None = None) -> HumanizedPerformance:
    score = score or _piano_score()
    exp_notes = []
    for n in score.right_hand:
        exp_notes.append(ExpressiveNote(
            score_note_id=n.id, pitch=n.pitch, onset_beat=n.onset_beat,
            duration_beat=n.duration_beat, velocity=n.velocity, hand="rh",
            voice=n.voice, timing_offset_ms=0.0, velocity_offset=0,
        ))
    for n in score.left_hand:
        exp_notes.append(ExpressiveNote(
            score_note_id=n.id, pitch=n.pitch, onset_beat=n.onset_beat,
            duration_beat=n.duration_beat, velocity=n.velocity, hand="lh",
            voice=n.voice, timing_offset_ms=0.0, velocity_offset=0,
        ))
    return HumanizedPerformance(
        expressive_notes=exp_notes,
        expression=ExpressionMap(),
        score=score,
        quality=QualitySignal(overall_confidence=0.9, warnings=[]),
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_delete_passes_cleanly() -> None:
    """Baseline: a delete edit on an existing, non-ghost note is applied."""
    perf = _humanized()
    edits = [RefineEditOp(
        op="delete", target_note_id="r-0000", rationale="ghost_note_removal",
    )]
    v = RefineValidator(_FakeSettings())
    applied, rejected = v.validate(perf, edits)
    assert len(applied) == 1
    assert applied[0].target_note_id == "r-0000"
    assert rejected == []


def test_valid_modify_passes_cleanly() -> None:
    """Modify edit with in-range pitch on a loud note is applied."""
    perf = _humanized(score=_piano_score(rh_notes=[(60, 0.0, 90)]))
    edits = [RefineEditOp(
        op="modify", target_note_id="r-0000", rationale="octave_correction", pitch=72,
    )]
    v = RefineValidator(_FakeSettings())
    applied, rejected = v.validate(perf, edits)
    assert len(applied) == 1
    assert rejected == []


def test_piano_score_source_happy_path() -> None:
    """Validator accepts PianoScore source (sheet_only variant)."""
    ps = _piano_score()
    edits = [RefineEditOp(
        op="delete", target_note_id="l-0000", rationale="ghost_note_removal",
    )]
    v = RefineValidator(_FakeSettings())
    applied, rejected = v.validate(ps, edits)
    assert len(applied) == 1


def test_applied_preserves_input_order() -> None:
    """Applied list is in original edit-list order."""
    perf = _humanized()
    edits = [
        RefineEditOp(op="delete", target_note_id="l-0000", rationale="other"),
        RefineEditOp(op="delete", target_note_id="r-0000", rationale="other"),
    ]
    v = RefineValidator(_FakeSettings())
    applied, _ = v.validate(perf, edits)
    assert [e.target_note_id for e in applied] == ["l-0000", "r-0000"]


# ---------------------------------------------------------------------------
# STG-04: unknown target_note_id
# ---------------------------------------------------------------------------


def test_unknown_target_note_id_is_rejected() -> None:
    perf = _humanized()
    edits = [RefineEditOp(
        op="delete", target_note_id="r-9999", rationale="ghost_note_removal",
    )]
    v = RefineValidator(_FakeSettings())
    applied, rejected = v.validate(perf, edits)
    assert applied == []
    assert len(rejected) == 1
    assert rejected[0][1] == "unknown_target_note_id"


def test_malformed_target_note_id_is_rejected_before_lookup() -> None:
    """ID_PATTERN gate runs first; malformed IDs never hit the map."""
    perf = _humanized()
    # Shape violations: wrong separator count, uppercase, legacy 'rh-' prefix, etc.
    for bad_id in ["rh-0042", "R-0001", "r-42", "r-00000", "r_0001", ""]:
        edits = [RefineEditOp(
            op="delete", target_note_id=bad_id, rationale="other",
        )]
        v = RefineValidator(_FakeSettings())
        applied, rejected = v.validate(perf, edits)
        assert applied == [], f"should reject malformed id {bad_id!r}"
        assert rejected[0][1] == "malformed_target_note_id", \
            f"expected malformed_target_note_id, got {rejected[0][1]!r} for id {bad_id!r}"


# ---------------------------------------------------------------------------
# STG-05 / D-13: ghost-note harmony_correction guard
# ---------------------------------------------------------------------------


def test_harmony_correction_on_ghost_note_is_rejected() -> None:
    """D-13: velocity <= threshold + rationale=harmony_correction → reject."""
    perf = _humanized(score=_piano_score(rh_notes=[(60, 0.0, 30)]))  # velocity 30, below 40
    edits = [RefineEditOp(
        op="modify", target_note_id="r-0000", rationale="harmony_correction", pitch=61,
    )]
    v = RefineValidator(_FakeSettings(refine_ghost_velocity_max=40))
    applied, rejected = v.validate(perf, edits)
    assert applied == []
    assert rejected[0][1] == "ghost_harmony_correction"


def test_harmony_correction_on_loud_note_passes() -> None:
    perf = _humanized(score=_piano_score(rh_notes=[(60, 0.0, 80)]))
    edits = [RefineEditOp(
        op="modify", target_note_id="r-0000", rationale="harmony_correction", pitch=61,
    )]
    v = RefineValidator(_FakeSettings(refine_ghost_velocity_max=40))
    applied, rejected = v.validate(perf, edits)
    assert len(applied) == 1
    assert rejected == []


def test_ghost_guard_is_inclusive_at_threshold() -> None:
    """D-13: velocity == threshold IS a ghost (inclusive bound)."""
    perf = _humanized(score=_piano_score(rh_notes=[(60, 0.0, 40)]))
    edits = [RefineEditOp(
        op="modify", target_note_id="r-0000", rationale="harmony_correction", pitch=61,
    )]
    v = RefineValidator(_FakeSettings(refine_ghost_velocity_max=40))
    applied, rejected = v.validate(perf, edits)
    assert applied == []
    assert rejected[0][1] == "ghost_harmony_correction"


def test_ghost_guard_ignores_non_harmony_rationales() -> None:
    """ghost_note_removal on a ghost note is the INTENDED correction — must pass."""
    perf = _humanized(score=_piano_score(rh_notes=[(60, 0.0, 20)]))
    edits = [RefineEditOp(
        op="delete", target_note_id="r-0000", rationale="ghost_note_removal",
    )]
    v = RefineValidator(_FakeSettings(refine_ghost_velocity_max=40))
    applied, rejected = v.validate(perf, edits)
    assert len(applied) == 1
    assert rejected == []


# ---------------------------------------------------------------------------
# STG-05 / D-14: piano pitch range [21, 108]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_pitch", [0, 20, 109, 120, 127])
def test_out_of_range_pitch_is_rejected(bad_pitch: int) -> None:
    perf = _humanized()
    edits = [RefineEditOp(
        op="modify", target_note_id="r-0000", rationale="octave_correction", pitch=bad_pitch,
    )]
    v = RefineValidator(_FakeSettings())
    applied, rejected = v.validate(perf, edits)
    assert applied == []
    assert rejected[0][1] == "pitch_out_of_range"


@pytest.mark.parametrize("edge_pitch", [PIANO_LOW_MIDI, 60, PIANO_HIGH_MIDI])
def test_edge_of_piano_range_is_accepted(edge_pitch: int) -> None:
    perf = _humanized()
    edits = [RefineEditOp(
        op="modify", target_note_id="r-0000", rationale="octave_correction", pitch=edge_pitch,
    )]
    v = RefineValidator(_FakeSettings())
    applied, rejected = v.validate(perf, edits)
    assert len(applied) == 1
    assert rejected == []


def test_delete_edit_has_no_pitch_check() -> None:
    """Deletes never set pitch — pitch-range guard is a no-op."""
    perf = _humanized()
    edits = [RefineEditOp(
        op="delete", target_note_id="r-0000", rationale="ghost_note_removal",
    )]
    v = RefineValidator(_FakeSettings())
    applied, rejected = v.validate(perf, edits)
    assert len(applied) == 1


# ---------------------------------------------------------------------------
# D-15: duplicate target_note_id → entire list rejected
# ---------------------------------------------------------------------------


def test_duplicate_target_rejects_entire_list() -> None:
    perf = _humanized()
    edits = [
        RefineEditOp(op="delete", target_note_id="r-0000", rationale="ghost_note_removal"),
        RefineEditOp(op="modify", target_note_id="r-0000", rationale="velocity_cleanup", velocity=50),
        RefineEditOp(op="delete", target_note_id="l-0000", rationale="other"),
    ]
    v = RefineValidator(_FakeSettings())
    applied, rejected = v.validate(perf, edits)
    assert applied == []
    assert len(rejected) == 3
    assert all(reason == "duplicate_target_note_id" for _, reason in rejected)


def test_duplicate_detection_short_circuits_before_other_gates() -> None:
    """Duplicate check runs BEFORE ID cross-reference — even invalid IDs count."""
    perf = _humanized()
    edits = [
        RefineEditOp(op="delete", target_note_id="r-9999", rationale="other"),  # unknown id
        RefineEditOp(op="delete", target_note_id="r-9999", rationale="other"),  # dup
    ]
    v = RefineValidator(_FakeSettings())
    applied, rejected = v.validate(perf, edits)
    assert applied == []
    # Duplicate short-circuit wins over malformed/unknown gate.
    assert rejected[0][1] == "duplicate_target_note_id"


def test_no_duplicates_allows_normal_gate_processing() -> None:
    """Sanity: two distinct IDs flow through per-edit gates normally."""
    perf = _humanized()
    edits = [
        RefineEditOp(op="delete", target_note_id="r-0000", rationale="ghost_note_removal"),
        RefineEditOp(op="delete", target_note_id="l-0000", rationale="duplicate_removal"),
    ]
    v = RefineValidator(_FakeSettings())
    applied, rejected = v.validate(perf, edits)
    assert len(applied) == 2
    assert rejected == []
