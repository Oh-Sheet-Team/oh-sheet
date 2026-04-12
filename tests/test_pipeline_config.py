from __future__ import annotations

from backend.contracts import PipelineConfig


def test_default_plan_uses_arrange() -> None:
    cfg = PipelineConfig(variant="audio_upload")
    assert cfg.get_execution_plan() == [
        "ingest",
        "transcribe",
        "arrange",
        "humanize",
        "engrave",
    ]


def test_condense_transform_replaces_arrange() -> None:
    cfg = PipelineConfig(variant="midi_upload", score_pipeline="condense_transform")
    assert cfg.get_execution_plan() == [
        "ingest",
        "condense",
        "transform",
        "humanize",
        "engrave",
    ]


def test_condense_transform_with_skip_humanizer() -> None:
    cfg = PipelineConfig(
        variant="sheet_only",
        score_pipeline="condense_transform",
        skip_humanizer=True,
    )
    assert cfg.get_execution_plan() == [
        "ingest",
        "transcribe",
        "condense",
        "transform",
        "engrave",
    ]


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
