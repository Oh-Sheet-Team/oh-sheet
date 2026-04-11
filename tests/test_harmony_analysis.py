"""Unit tests for symbolic chordal harmony analysis."""
from __future__ import annotations

from backend.contracts import InstrumentRole, RealtimeChordEvent, TempoMapEntry
from backend.services.harmony_analysis import (
    analyze_chordal_harmony,
    chord_progression_dump_text,
    format_chord_progression,
)

_TEMPO_MAP = [TempoMapEntry(time_sec=0.0, beat=0.0, bpm=120.0)]


def _event(
    start_sec: float,
    end_sec: float,
    pitch: int,
    amp: float = 0.8,
):
    return (start_sec, end_sec, pitch, amp, None)


def test_symbolic_harmony_detects_c_to_g_progression():
    events_by_role = {
        InstrumentRole.CHORDS: [
            _event(0.0, 1.0, 60),  # C4
            _event(0.0, 1.0, 64),  # E4
            _event(0.0, 1.0, 67),  # G4
            _event(1.0, 2.0, 55),  # G3
            _event(1.0, 2.0, 59),  # B3
            _event(1.0, 2.0, 62),  # D4
        ],
        InstrumentRole.BASS: [
            _event(0.0, 1.0, 36),  # C2
            _event(1.0, 2.0, 43),  # G2
        ],
    }

    chords, stats = analyze_chordal_harmony(
        events_by_role,
        tempo_map=_TEMPO_MAP,
        key_label="C:major",
        hmm_enabled=False,
    )

    assert not stats.skipped
    assert [chord.label for chord in chords] == ["C:maj", "G:maj"]
    assert [chord.root for chord in chords] == [0, 7]
    assert [chord.quality for chord in chords] == ["maj", "maj"]
    assert [chord.roman_numeral for chord in chords] == ["I", "V"]
    assert all(chord.source == "symbolic" for chord in chords)


def test_symbolic_harmony_detects_inversion_and_roman_numeral():
    events_by_role = {
        InstrumentRole.CHORDS: [
            _event(0.0, 1.0, 60),  # C4
            _event(0.0, 1.0, 64),  # E4
            _event(0.0, 1.0, 67),  # G4
        ],
        InstrumentRole.BASS: [
            _event(0.0, 1.0, 52),  # E3
        ],
    }

    chords, _stats = analyze_chordal_harmony(
        events_by_role,
        tempo_map=_TEMPO_MAP,
        key_label="C:major",
        hmm_enabled=False,
    )

    assert len(chords) == 1
    chord = chords[0]
    assert chord.label == "C:maj/E"
    assert chord.quality == "maj"
    assert chord.bass == 4
    assert chord.roman_numeral == "I6"


def test_symbolic_harmony_falls_back_to_audio_guide_when_note_stream_is_sparse():
    events_by_role = {
        InstrumentRole.MELODY: [
            _event(0.0, 1.0, 72),
        ],
    }
    guide = [
        RealtimeChordEvent(
            time_sec=0.0,
            duration_sec=1.0,
            label="C:maj",
            root=0,
            confidence=0.82,
        )
    ]

    chords, stats = analyze_chordal_harmony(
        events_by_role,
        tempo_map=_TEMPO_MAP,
        key_label="C:major",
        guide_chords=guide,
        hmm_enabled=False,
    )

    assert not stats.skipped
    assert len(chords) == 1
    chord = chords[0]
    assert chord.label == "C:maj"
    assert chord.quality == "maj"
    assert chord.roman_numeral == "I"
    assert chord.source == "audio"


def test_format_chord_progression_renders_compact_terminal_summary():
    chords = [
        RealtimeChordEvent(
            time_sec=0.0,
            duration_sec=1.0,
            label="C:maj",
            root=0,
            confidence=0.9,
            roman_numeral="I",
        ),
        RealtimeChordEvent(
            time_sec=1.0,
            duration_sec=1.0,
            label="G:maj",
            root=7,
            confidence=0.9,
            roman_numeral="V",
        ),
    ]

    summary = format_chord_progression(chords)

    assert summary == "0.00s C:maj (I) -> 1.00s G:maj (V)"

    full = format_chord_progression(chords, max_items=None)
    assert full == summary


def test_format_chord_progression_truncates_when_max_items_set():
    chords = [
        RealtimeChordEvent(
            time_sec=float(i),
            duration_sec=1.0,
            label=f"P{i}:maj",
            root=i % 12,
            confidence=0.9,
        )
        for i in range(15)
    ]
    truncated = format_chord_progression(chords, max_items=12)
    assert "... (+3 more)" in truncated
    full = format_chord_progression(chords, max_items=None)
    assert "... (+3 more)" not in full
    assert "14.00s" in full


def test_chord_progression_dump_text_multiline():
    chords = [
        RealtimeChordEvent(
            time_sec=0.0,
            duration_sec=1.0,
            label="C:maj",
            root=0,
            confidence=0.9,
            roman_numeral="I",
        ),
    ]
    text = chord_progression_dump_text(chords, key="C:major", job_id="job-1")
    assert "job_id: job-1" in text
    assert "key: C:major" in text
    assert "chord_count: 1" in text
    assert "C:maj" in text
    assert "roman=I" in text
