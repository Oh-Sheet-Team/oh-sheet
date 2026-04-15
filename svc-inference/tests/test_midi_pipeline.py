"""Unit tests for the MIDI normalizer, chunker, and stitcher."""
from inference.midi_pipeline import (
    ScoreChunk,
    chunk_performance,
    normalize_midi,
    stitch_chunks,
)

from tests.fixtures import make_sample_midi


def test_normalize_midi_extracts_notes():
    perf = normalize_midi(make_sample_midi(num_notes=6))
    assert len(perf.notes) == 6
    assert perf.time_signature == (4, 4)
    assert perf.tempo_bpm > 0
    # Onsets strictly increasing
    assert [n.onset_sec for n in perf.notes] == sorted(n.onset_sec for n in perf.notes)


def test_chunker_covers_all_notes_with_overlap():
    perf = normalize_midi(make_sample_midi(num_notes=64))  # ~16s at 120 BPM
    chunks = chunk_performance(perf, window_beats=8.0, stride_beats=4.0)
    assert len(chunks) >= 2
    # Every note onset should land in at least one chunk
    covered = {id(n) for c in chunks for n in c.notes}
    assert len(covered) == len(perf.notes)
    # Chunks after the first overlap with the previous one
    assert chunks[1].start_measure < chunks[0].end_measure


def test_chunker_rejects_bad_config():
    perf = normalize_midi(make_sample_midi(num_notes=4))
    try:
        chunk_performance(perf, window_beats=4.0, stride_beats=8.0)
    except ValueError:
        return
    raise AssertionError("expected ValueError for stride > window")


def test_stitch_minimal_fallback_produces_valid_xml_header():
    # Use a dummy ScoreChunk with score=None so the minimal path runs
    perf = normalize_midi(make_sample_midi(num_notes=4))
    chunks = chunk_performance(perf, window_beats=16.0, stride_beats=8.0)
    score_chunks = [ScoreChunk(chunk=c, score=None) for c in chunks]
    out = stitch_chunks(score_chunks, perf)
    assert out.startswith(b"<?xml")
    assert b"score-partwise" in out
