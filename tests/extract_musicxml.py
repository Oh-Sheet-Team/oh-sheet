#!/usr/bin/env python
"""Extract sanitized MusicXML from a PianoScore JSON fixture.

Runs only _render_musicxml_bytes() (which includes _sanitize_musicxml_for_osmd())
— no MIDI, no PDF, no blob storage, no pipeline.

Usage:
    python tests/extract_musicxml.py <fixture_name> [output_path]

Examples:
    python tests/extract_musicxml.py two_hand_chordal
    python tests/extract_musicxml.py c_major_scale /tmp/scale.musicxml
    python tests/extract_musicxml.py --list
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))


def main() -> None:
    from backend.contracts import HumanizedPerformance  # noqa: PLC0415
    from backend.services.engrave import _render_musicxml_bytes  # noqa: PLC0415
    from tests.fixtures import FIXTURE_NAMES, load_score_fixture  # noqa: PLC0415

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        print(f"Available fixtures: {', '.join(FIXTURE_NAMES)}")
        sys.exit(0)

    if sys.argv[1] == "--list":
        for name in FIXTURE_NAMES:
            print(name)
        sys.exit(0)

    name = sys.argv[1]
    if name not in FIXTURE_NAMES:
        print(f"Unknown fixture {name!r}. Use --list to see available fixtures.")
        sys.exit(1)

    fixture = load_score_fixture(name)
    if isinstance(fixture, HumanizedPerformance):
        score, perf = fixture.score, fixture
    else:
        score, perf = fixture, None

    musicxml, chord_count = _render_musicxml_bytes(score, perf, title=name, composer="test")

    output = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"tests/fixtures/scores/{name}.musicxml")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(musicxml)
    print(f"Wrote {len(musicxml):,} bytes -> {output}  (chord_symbols_rendered={chord_count})")


if __name__ == "__main__":
    main()
