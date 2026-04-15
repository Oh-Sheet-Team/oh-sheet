"""MIDI normalizer, sliding-window chunker, and measure-boundary stitcher.

The inference path:

    raw MIDI bytes
        │  normalize_midi()
        ▼
    NormalizedPerformance(notes, tempo_bpm, time_signature, end_sec)
        │  chunk_performance()
        ▼
    list[PerfChunk]  (beat-aligned windows w/ overlap)
        │  runner.transcribe_chunk() for each
        ▼
    list[ScoreChunk]  (one per chunk, scoped to its measure range)
        │  stitch_chunks()
        ▼
    MusicXML bytes

Both the normalizer and chunker are intentionally model-agnostic: they
produce ``PerfNote`` values that match the ``rl_model.core.PerfNote``
shape shown in the system diagram, so the seq2seq runner can feed them
straight into ``midi_vocab.encode_perf`` without a re-shape step.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PerfNote:
    pitch: int
    onset_sec: float
    offset_sec: float
    velocity: int


@dataclass
class NormalizedPerformance:
    notes: list[PerfNote]
    tempo_bpm: float
    time_signature: tuple[int, int]
    end_sec: float

    @property
    def seconds_per_beat(self) -> float:
        return 60.0 / max(1e-6, self.tempo_bpm)

    @property
    def seconds_per_measure(self) -> float:
        beats_per_measure = self.time_signature[0] * (4.0 / self.time_signature[1])
        return self.seconds_per_beat * beats_per_measure


@dataclass
class PerfChunk:
    index: int
    notes: list[PerfNote]
    start_beat: float
    end_beat: float
    start_measure: int
    end_measure: int  # exclusive
    is_overlap_head: bool = False  # first N measures overlap with previous chunk


@dataclass
class ScoreChunk:
    """A transcribed chunk — music21 score fragment scoped to its measures.

    ``score`` is typed as ``object`` so that this module doesn't force an
    import of music21. Runners build the object via their own lazy
    import, and ``stitch_chunks`` pulls music21 in only when needed.
    """
    chunk: PerfChunk
    score: object
    decode_steps: int = 0
    rejected_tokens: int = 0
    parse_failed: bool = False
    notes_emitted: int = 0


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------

def normalize_midi(midi_bytes: bytes) -> NormalizedPerformance:
    """Parse raw performance MIDI into a flat PerfNote list."""
    try:
        import pretty_midi  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "pretty_midi is required to normalize MIDI input. "
            "Install with `pip install pretty_midi`."
        ) from exc

    try:
        pm = pretty_midi.PrettyMIDI(io.BytesIO(midi_bytes))
    except Exception as exc:  # pretty_midi wraps mido errors in a grab-bag
        raise ValueError(f"Unable to parse MIDI bytes: {exc}") from exc

    notes: list[PerfNote] = []
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for n in inst.notes:
            if n.end <= n.start:
                continue
            notes.append(PerfNote(
                pitch=int(n.pitch),
                onset_sec=float(n.start),
                offset_sec=float(n.end),
                velocity=int(max(1, min(127, n.velocity))),
            ))
    notes.sort(key=lambda n: (n.onset_sec, n.pitch))

    tempo_changes = pm.get_tempo_changes()
    tempo_bpm = float(tempo_changes[1][0]) if len(tempo_changes[1]) else 120.0
    ts = pm.time_signature_changes
    time_signature: tuple[int, int] = (int(ts[0].numerator), int(ts[0].denominator)) if ts else (4, 4)

    end_sec = max((n.offset_sec for n in notes), default=0.0)
    return NormalizedPerformance(
        notes=notes,
        tempo_bpm=tempo_bpm,
        time_signature=time_signature,
        end_sec=end_sec,
    )


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------

def chunk_performance(
    perf: NormalizedPerformance,
    window_beats: float,
    stride_beats: float,
) -> list[PerfChunk]:
    """Slide a beat-aligned window across the performance.

    Windows are rounded up to whole measures so chunks join cleanly at
    barlines during stitching. Overlap = window - stride.
    """
    if window_beats <= 0 or stride_beats <= 0 or stride_beats > window_beats:
        raise ValueError(f"invalid chunker cfg: window={window_beats} stride={stride_beats}")

    beats_per_measure = perf.time_signature[0] * (4.0 / perf.time_signature[1])
    window_measures = max(1, int(round(window_beats / beats_per_measure)))
    stride_measures = max(1, int(round(stride_beats / beats_per_measure)))
    overlap_measures = max(0, window_measures - stride_measures)

    sec_per_beat = perf.seconds_per_beat
    total_beats = perf.end_sec / sec_per_beat if sec_per_beat > 0 else 0.0
    total_measures = max(1, int(total_beats / beats_per_measure) + 1)

    chunks: list[PerfChunk] = []
    start_measure = 0
    idx = 0
    while start_measure < total_measures:
        end_measure = min(total_measures, start_measure + window_measures)
        start_beat = start_measure * beats_per_measure
        end_beat = end_measure * beats_per_measure
        start_sec = start_beat * sec_per_beat
        end_sec = end_beat * sec_per_beat

        chunk_notes = [
            n for n in perf.notes
            if n.onset_sec >= start_sec and n.onset_sec < end_sec
        ]
        chunks.append(PerfChunk(
            index=idx,
            notes=chunk_notes,
            start_beat=start_beat,
            end_beat=end_beat,
            start_measure=start_measure,
            end_measure=end_measure,
            is_overlap_head=(idx > 0 and overlap_measures > 0),
        ))
        idx += 1
        if end_measure >= total_measures:
            break
        start_measure += stride_measures

    return chunks


# ---------------------------------------------------------------------------
# Stitcher
# ---------------------------------------------------------------------------

def stitch_chunks(
    chunks: list[ScoreChunk],
    perf: NormalizedPerformance,
    title: str = "Untitled",
    composer: str = "",
) -> bytes:
    """Merge per-chunk music21 scores at measure boundaries → MusicXML bytes.

    Strategy: take measures from each chunk, skipping the overlap head of
    chunks after the first so we don't double-emit shared measures. The
    stitched score is a fresh Score with one part populated by measures
    in original order.

    Falls back to a minimal hand-rolled MusicXML body if music21 isn't
    installed so tests / container builds without the optional dep still
    get valid output.
    """
    try:
        from music21 import clef, metadata, meter, note, stream, tempo  # noqa: PLC0415
    except ImportError:
        log.warning("music21 not installed — emitting minimal stub MusicXML")
        return _minimal_musicxml(chunks, perf, title, composer)

    beats_per_measure = perf.time_signature[0] * (4.0 / perf.time_signature[1])
    overlap_measures_from = _detect_overlap(chunks)

    merged = stream.Score()
    merged.metadata = metadata.Metadata()
    merged.metadata.title = title or "Untitled"
    merged.metadata.composer = composer or ""

    part = stream.Part()
    part.append(clef.TrebleClef())
    part.append(meter.TimeSignature(f"{perf.time_signature[0]}/{perf.time_signature[1]}"))
    part.append(tempo.MetronomeMark(number=perf.tempo_bpm))

    parse_failures = 0
    for sc in chunks:
        if sc.parse_failed:
            parse_failures += 1
            continue
        skip_measures = overlap_measures_from if sc.chunk.index > 0 else 0
        try:
            _append_chunk_measures(sc, part, skip_measures, beats_per_measure, note)
        except Exception as exc:  # noqa: BLE001
            log.warning("stitch: chunk %d append failed: %s", sc.chunk.index, exc)
            parse_failures += 1

    merged.append(part)

    try:
        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(suffix=".musicxml", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            merged.write("musicxml", fp=str(tmp_path))
            return tmp_path.read_bytes()
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("music21 write failed (%s); emitting minimal stub", exc)
        return _minimal_musicxml(chunks, perf, title, composer)


def _detect_overlap(chunks: list[ScoreChunk]) -> int:
    if len(chunks) < 2:
        return 0
    first, second = chunks[0].chunk, chunks[1].chunk
    return max(0, first.end_measure - second.start_measure)


def _append_chunk_measures(
    sc: ScoreChunk,
    part: object,
    skip_measures: int,
    beats_per_measure: float,
    m21_note_mod: object,
) -> None:
    """Append notes from a chunk's score to the merged part.

    Music21 scores from the decoder are flat note streams; we partition
    them into measures by onset beat offset from the chunk start and
    drop the first ``skip_measures`` to avoid double-emitting overlap.
    """
    chunk_score = sc.score
    if chunk_score is None:
        return
    try:
        flat_notes = list(chunk_score.flatten().notes) if hasattr(chunk_score, "flatten") else []
    except Exception:  # noqa: BLE001
        flat_notes = []

    for n in flat_notes:
        try:
            offset_beats = float(n.offset)
        except Exception:  # noqa: BLE001
            continue
        measure_idx = int(offset_beats // beats_per_measure)
        if measure_idx < skip_measures:
            continue
        absolute_beat = sc.chunk.start_beat + offset_beats
        try:
            part.insert(absolute_beat, n)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            continue


def _minimal_musicxml(
    chunks: list[ScoreChunk],
    perf: NormalizedPerformance,
    title: str,
    composer: str,
) -> bytes:
    from xml.sax.saxutils import escape

    ts = perf.time_signature
    divisions = 4

    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8" standalone="no"?>')
    parts.append(
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">'
    )
    parts.append('<score-partwise version="3.1">')
    parts.append(f'<work><work-title>{escape(title or "Untitled")}</work-title></work>')
    parts.append(
        f'<identification><creator type="composer">{escape(composer or "Unknown")}</creator></identification>'
    )
    parts.append(
        '<part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>'
    )
    parts.append('<part id="P1"><measure number="1"><attributes>')
    parts.append(f'<divisions>{divisions}</divisions>')
    parts.append('<key><fifths>0</fifths></key>')
    parts.append(f'<time><beats>{ts[0]}</beats><beat-type>{ts[1]}</beat-type></time>')
    parts.append('<clef><sign>G</sign><line>2</line></clef>')
    parts.append('</attributes>')
    parts.append(f'<sound tempo="{perf.tempo_bpm:.2f}"/>')

    note_count = 0
    for sc in chunks:
        if sc.parse_failed:
            continue
        for pn in sc.chunk.notes:
            step, alter, octave = _midi_to_step_alter_octave(pn.pitch)
            alter_xml = f"<alter>{alter}</alter>" if alter else ""
            parts.append(
                "<note>"
                f"<pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch>"
                f"<duration>{divisions}</duration><voice>1</voice>"
                "</note>"
            )
            note_count += 1
            if note_count >= 32:
                break
        if note_count >= 32:
            break

    parts.append('</measure></part></score-partwise>')
    return "".join(parts).encode("utf-8")


_PITCH_NAMES: list[tuple[str, int]] = [
    ("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0),
    ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0),
]


def _midi_to_step_alter_octave(midi: int) -> tuple[str, int, int]:
    midi = max(0, min(127, midi))
    octave = (midi // 12) - 1
    step, alter = _PITCH_NAMES[midi % 12]
    return step, alter, octave
