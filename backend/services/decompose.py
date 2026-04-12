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
