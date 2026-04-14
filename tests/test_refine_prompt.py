"""Unit tests for the refine prompt module — pure functions, no network."""
from __future__ import annotations

from shared.contracts import (
    PianoScore,
    ScoreChordEvent,
    ScoreMetadata,
    ScoreNote,
    TempoMapEntry,
)

from backend.services.refine_prompt import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_chord_sketch,
    build_user_prompt,
    format_chord_sketch,
    submit_refinements_tool_schema,
    web_search_tool_schema,
)


def test_prompt_version_is_a_stable_string() -> None:
    assert isinstance(PROMPT_VERSION, str)
    assert PROMPT_VERSION != ""


def test_system_prompt_mentions_web_search_and_submit() -> None:
    assert "web_search" in SYSTEM_PROMPT
    assert "submit_refinements" in SYSTEM_PROMPT


def test_build_chord_sketch_buckets_by_measure() -> None:
    chords = [
        ScoreChordEvent(beat=0.0, duration_beat=2.0, label="C:maj", root=0),
        ScoreChordEvent(beat=2.0, duration_beat=2.0, label="F:maj", root=5),
        ScoreChordEvent(beat=4.0, duration_beat=4.0, label="G:maj", root=7),
        ScoreChordEvent(beat=8.0, duration_beat=4.0, label="C:maj", root=0),
    ]
    sketch = build_chord_sketch(chords, time_signature=(4, 4))
    assert sketch == [
        (1, ["C:maj", "F:maj"]),
        (2, ["G:maj"]),
        (3, ["C:maj"]),
    ]


def test_build_chord_sketch_handles_empty() -> None:
    assert build_chord_sketch([], time_signature=(4, 4)) == []


def test_build_chord_sketch_handles_three_four() -> None:
    chords = [
        ScoreChordEvent(beat=0.0, duration_beat=3.0, label="D:min", root=2),
        ScoreChordEvent(beat=3.0, duration_beat=3.0, label="A:maj", root=9),
    ]
    sketch = build_chord_sketch(chords, time_signature=(3, 4))
    assert sketch == [(1, ["D:min"]), (2, ["A:maj"])]


def test_format_chord_sketch_renders_bar_lines() -> None:
    sketch = [(1, ["C:maj", "F:maj"]), (2, ["G:maj"])]
    out = format_chord_sketch(sketch)
    assert "bar 1: C:maj | F:maj" in out
    assert "bar 2: G:maj" in out


def test_format_chord_sketch_handles_empty() -> None:
    assert "(no chord analysis available)" in format_chord_sketch([])


def _score_fixture() -> PianoScore:
    return PianoScore(
        right_hand=[
            ScoreNote(id="rh-1", pitch=72, onset_beat=0.0, duration_beat=1.0, velocity=80, voice=1),
            ScoreNote(id="rh-2", pitch=76, onset_beat=4.0, duration_beat=1.0, velocity=80, voice=1),
        ],
        left_hand=[
            ScoreNote(id="lh-1", pitch=48, onset_beat=0.0, duration_beat=2.0, velocity=70, voice=1),
        ],
        metadata=ScoreMetadata(
            key="C:major",
            time_signature=(4, 4),
            tempo_map=[TempoMapEntry(time_sec=0.0, beat=0.0, bpm=100.0)],
            difficulty="intermediate",
            chord_symbols=[
                ScoreChordEvent(beat=0.0, duration_beat=4.0, label="C:maj", root=0),
            ],
        ),
    )


def test_build_user_prompt_includes_detected_fields_and_hint() -> None:
    score = _score_fixture()
    prompt = build_user_prompt(
        title_hint="Test Song",
        artist_hint="Test Artist",
        score=score,
    )
    assert "Test Song" in prompt
    assert "Test Artist" in prompt
    assert "C:major" in prompt
    assert "4/4" in prompt
    assert "100" in prompt
    assert "48" in prompt  # pitch range
    assert "76" in prompt
    assert "C:maj" in prompt  # chord sketch


def test_build_user_prompt_handles_missing_hints() -> None:
    score = _score_fixture()
    prompt = build_user_prompt(title_hint=None, artist_hint=None, score=score)
    assert "None" in prompt or "null" in prompt.lower()


def test_build_user_prompt_includes_filename_hint() -> None:
    score = _score_fixture()
    prompt = build_user_prompt(
        title_hint=None,
        artist_hint=None,
        filename_hint="my-heart-will-go-on.mid",
        score=score,
    )
    assert "my-heart-will-go-on.mid" in prompt


def test_system_prompt_requires_heuristic_fallback() -> None:
    # Must instruct the model to ALWAYS call submit_refinements with
    # common-sense defaults when the song cannot be identified.
    assert "submit_refinements" in SYSTEM_PROMPT
    assert "tempo_marking" in SYSTEM_PROMPT
    assert "staff_split_hint" in SYSTEM_PROMPT
    assert "filename" in SYSTEM_PROMPT.lower()


def test_submit_refinements_tool_schema_shape() -> None:
    schema = submit_refinements_tool_schema()
    assert schema["name"] == "submit_refinements"
    props = schema["input_schema"]["properties"]
    for field in (
        "title",
        "composer",
        "arranger",
        "key_signature",
        "time_signature",
        "tempo_bpm",
        "tempo_marking",
        "staff_split_hint",
        "sections",
        "repeats",
    ):
        assert field in props, f"missing field {field!r} in submit_refinements schema"
    # sections items use SectionLabel enum values
    section_label_enum = props["sections"]["items"]["properties"]["label"]["enum"]
    assert "verse" in section_label_enum
    assert "chorus" in section_label_enum
    # repeats items constrain kind
    assert props["repeats"]["items"]["properties"]["kind"]["enum"] == ["simple", "with_endings"]


def test_web_search_tool_schema_has_max_uses() -> None:
    schema = web_search_tool_schema(5)
    assert schema["type"] == "web_search_20250305"
    assert schema["name"] == "web_search"
    assert schema["max_uses"] == 5
