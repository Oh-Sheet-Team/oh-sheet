"""Prompt + tool-schema builders for the refine stage. Pure, no network.

The refine stage sends Claude a compact digest of the PianoScore + the
user's title hint, plus the ``web_search`` server tool and a
``submit_refinements`` client tool. The model is expected to research
the song, then emit a single ``submit_refinements`` tool call with the
metadata it was able to justify.
"""
from __future__ import annotations

from typing import Any

from shared.contracts import (
    PianoScore,
    ScoreChordEvent,
    SectionLabel,
)

# Bumping this invalidates the refine cache. See backend/services/refine.py.
PROMPT_VERSION = "v2"

SYSTEM_PROMPT = (
    "You are a music editor refining an automatically-generated piano "
    "transcription. Use the web_search tool to confirm the song's identity, "
    "canonical key signature, form, section structure, and tempo marking. "
    "Then call submit_refinements exactly once with your conclusions.\n\n"
    "Rules:\n"
    " * Only submit song-specific values (title, composer, arranger, "
    "section/repeat structure) when you can justify them from your research. "
    "Omit song-specific fields you are not confident about.\n"
    " * Do NOT invent note data. You are only editing metadata.\n"
    " * Prefer canonical published key signatures over the detected key "
    "when they disagree.\n"
    " * Section boundaries should align with the chord sketch when possible.\n"
    " * You MUST ALWAYS call submit_refinements — never return an empty or "
    "missing call. If title/artist/filename + web_search do not let you "
    "identify the song, fall back to common-sense music-editing defaults "
    "derived from the detected data:\n"
    "     - Set tempo_marking from the detected BPM: Largo (≤60), "
    "Adagio (~66), Andante (~76), Moderato (~108), Allegro (~120), "
    "Vivace (~140), Presto (≥168). Pick the nearest bucket.\n"
    "     - Set staff_split_hint to 60 (middle C) unless the pitch range "
    "clearly suggests otherwise.\n"
    "     - Leave key_signature and time_signature unset (they fall back "
    "to the detected values).\n"
    "     - If a filename hint is provided and no better title is known, "
    "use the filename with the extension stripped and separators "
    "(_, -) replaced with spaces as the title.\n"
)


def build_chord_sketch(
    chord_symbols: list[ScoreChordEvent],
    time_signature: tuple[int, int],
) -> list[tuple[int, list[str]]]:
    """Bucket chord events by 1-based measure number.

    Uses the time-signature numerator as beats-per-measure, which matches
    how the rest of the pipeline counts beats (quarter-note-based when
    ``denominator == 4``). Returns measures in ascending order, each
    paired with its in-order chord labels.
    """
    beats_per_measure = time_signature[0]
    if beats_per_measure <= 0 or not chord_symbols:
        return []
    by_measure: dict[int, list[str]] = {}
    for ev in chord_symbols:
        measure = int(ev.beat // beats_per_measure) + 1
        by_measure.setdefault(measure, []).append(ev.label)
    return sorted(by_measure.items())


def format_chord_sketch(sketch: list[tuple[int, list[str]]]) -> str:
    if not sketch:
        return "  (no chord analysis available)"
    lines = []
    for measure, chords in sketch:
        lines.append(f"  bar {measure}: {' | '.join(chords)}")
    return "\n".join(lines)


def build_user_prompt(
    *,
    title_hint: str | None,
    artist_hint: str | None,
    score: PianoScore,
    filename_hint: str | None = None,
) -> str:
    """Assemble the user-facing refinement prompt from a PianoScore digest."""
    md = score.metadata
    beats_per_measure = md.time_signature[0] or 4

    last_beat = 0.0
    for n in score.right_hand:
        end = n.onset_beat + n.duration_beat
        if end > last_beat:
            last_beat = end
    for n in score.left_hand:
        end = n.onset_beat + n.duration_beat
        if end > last_beat:
            last_beat = end
    measures = int(last_beat / beats_per_measure) + 1

    pitches = [n.pitch for n in score.right_hand] + [n.pitch for n in score.left_hand]
    low = min(pitches) if pitches else 60
    high = max(pitches) if pitches else 60

    tempo_bpm = md.tempo_map[0].bpm if md.tempo_map else 120.0

    sketch = build_chord_sketch(md.chord_symbols, md.time_signature)

    return (
        "User-provided hint:\n"
        f"  title={title_hint!r}, artist={artist_hint!r}, filename={filename_hint!r}\n"
        "\n"
        "Detected from transcription:\n"
        f"  key = {md.key}\n"
        f"  time_signature = {md.time_signature[0]}/{md.time_signature[1]}\n"
        f"  tempo_bpm = {tempo_bpm:g}\n"
        f"  duration_measures = {measures}\n"
        f"  pitch_range = MIDI {low}-{high}\n"
        "\n"
        "Per-bar chord sketch (Harte notation):\n"
        f"{format_chord_sketch(sketch)}\n"
    )


def submit_refinements_tool_schema() -> dict[str, Any]:
    """JSON-schema tool definition for the terminal ``submit_refinements`` call.

    Field names mirror the new ScoreMetadata refinement fields (see
    shared/shared/contracts.py). All fields are optional — the model is
    instructed to omit values it cannot justify.
    """
    section_label_values = [e.value for e in SectionLabel]
    return {
        "name": "submit_refinements",
        "description": (
            "Submit refined metadata for the piano score. Call exactly once. "
            "Omit fields you are not confident about."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "composer": {"type": "string"},
                "arranger": {"type": "string"},
                "key_signature": {
                    "type": "string",
                    "description": "Harte-style key like 'Db:major' or 'A:minor'.",
                },
                "time_signature": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "[numerator, denominator] — e.g., [4,4] or [3,4].",
                },
                "tempo_bpm": {"type": "number"},
                "tempo_marking": {
                    "type": "string",
                    "description": "Italian marking like 'Andante' or 'Allegro con brio'.",
                },
                "staff_split_hint": {
                    "type": "integer",
                    "description": "MIDI pitch where left/right hand split (typically 60).",
                },
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_beat": {"type": "number"},
                            "end_beat": {"type": "number"},
                            "label": {"type": "string", "enum": section_label_values},
                            "custom_label": {"type": "string"},
                        },
                        "required": ["start_beat", "end_beat", "label"],
                    },
                },
                "repeats": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_beat": {"type": "number"},
                            "end_beat": {"type": "number"},
                            "kind": {"type": "string", "enum": ["simple", "with_endings"]},
                        },
                        "required": ["start_beat", "end_beat", "kind"],
                    },
                },
            },
        },
    }


def web_search_tool_schema(max_uses: int) -> dict[str, Any]:
    """Anthropic server-side web_search tool — returns inline search results."""
    return {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": max_uses,
    }
