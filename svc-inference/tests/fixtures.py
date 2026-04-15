"""Tiny MIDI fixture helpers — keeps tests independent of on-disk assets."""
from __future__ import annotations


def make_sample_midi(num_notes: int = 8) -> bytes:
    """Build a minimal single-track MIDI file in-memory using pretty_midi."""
    import pretty_midi

    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0, name="Piano")
    step = 0.25  # 8th notes at 120 BPM
    for i in range(num_notes):
        start = i * step
        inst.notes.append(pretty_midi.Note(
            velocity=80, pitch=60 + (i % 12),
            start=start, end=start + step * 0.9,
        ))
    pm.instruments.append(inst)

    import tempfile
    from pathlib import Path
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        pm.write(str(tmp_path))
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)
