from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from shared.contracts import (
    SCHEMA_VERSION,
    HarmonicAnalysis,
    InputBundle,
    InstrumentRole,
    MidiTrack,
    Note,
    PianoScore,
    QualitySignal,
    ScoreMetadata,
    ScoreNote,
    TempoMapEntry,
    TranscriptionResult,
)
from shared.storage.local import LocalBlobStore

import backend.workers.engrave  # noqa: F401
import backend.workers.humanize  # noqa: F401

# Import monolith worker modules so their tasks are registered on the celery_app.
import backend.workers.ingest  # noqa: F401
from backend.api import deps
from backend.config import settings
from backend.main import create_app
from backend.services import transcribe as transcribe_module
from backend.workers.celery_app import celery_app as _celery_app

# Register decomposer and assembler tasks on the monolith celery_app.
#
# The external services have their own Celery apps in production, but for
# testing we need the task functions registered on the single app instance
# the PipelineRunner dispatches through.
#
# Stubs are inlined here (not imported from svc-decomposer/svc-assembler)
# because CI only installs the backend and shared packages.


@_celery_app.task(name="decomposer.run")
def _decomposer_run(job_id: str, payload_uri: str) -> str:
    blob = LocalBlobStore(settings.blob_root)
    raw = blob.get_json(payload_uri)
    InputBundle.model_validate(raw)

    # Persist a fake transcription MIDI so the URI survives through the pipeline
    midi_uri = blob.put_bytes(
        f"jobs/{job_id}/transcription/basic-pitch.mid",
        b"MThd\x00\x00\x00\x06\x00\x00\x00\x00\x00\x00",
    )

    result = TranscriptionResult(
        schema_version=SCHEMA_VERSION,
        midi_tracks=[
            MidiTrack(
                notes=[
                    Note(pitch=60, onset_sec=0.0, offset_sec=0.5, velocity=80),
                    Note(pitch=64, onset_sec=0.5, offset_sec=1.0, velocity=80),
                    Note(pitch=67, onset_sec=1.0, offset_sec=1.5, velocity=80),
                    Note(pitch=72, onset_sec=1.5, offset_sec=2.0, velocity=80),
                ],
                instrument=InstrumentRole.MELODY,
                program=None,
                confidence=0.7,
            ),
        ],
        analysis=HarmonicAnalysis(
            key="C:major",
            time_signature=(4, 4),
            tempo_map=[TempoMapEntry(time_sec=0.0, beat=0.0, bpm=120.0)],
            chords=[],
            sections=[],
        ),
        quality=QualitySignal(
            overall_confidence=0.3,
            warnings=["conftest stub — real transcription not wired"],
        ),
        transcription_midi_uri=midi_uri,
    )

    output_uri = blob.put_json(
        f"jobs/{job_id}/decomposer/output.json",
        result.model_dump(mode="json"),
    )
    return output_uri


@_celery_app.task(name="assembler.run")
def _assembler_run(job_id: str, payload_uri: str) -> str:
    blob = LocalBlobStore(settings.blob_root)
    raw = blob.get_json(payload_uri)
    txr = TranscriptionResult.model_validate(raw)

    tempo_map = txr.analysis.tempo_map or [
        TempoMapEntry(time_sec=0.0, beat=0.0, bpm=120.0)
    ]
    result = PianoScore(
        schema_version=SCHEMA_VERSION,
        right_hand=[
            ScoreNote(
                id="rh-0001", pitch=60, onset_beat=0.0,
                duration_beat=1.0, velocity=80, voice=1,
            ),
        ],
        left_hand=[
            ScoreNote(
                id="lh-0001", pitch=48, onset_beat=0.0,
                duration_beat=1.0, velocity=70, voice=1,
            ),
        ],
        metadata=ScoreMetadata(
            key=txr.analysis.key,
            time_signature=txr.analysis.time_signature,
            tempo_map=tempo_map,
            difficulty="intermediate",
        ),
    )

    output_uri = blob.put_json(
        f"jobs/{job_id}/assembler/output.json",
        result.model_dump(mode="json"),
    )
    return output_uri


@pytest.fixture(autouse=True)
def isolated_blob_root(tmp_path: Path, monkeypatch):
    """Each test gets a fresh blob root and fresh DI singletons."""
    blob = tmp_path / "blob"
    blob.mkdir()
    monkeypatch.setattr(settings, "blob_root", blob)

    deps.get_blob_store.cache_clear()
    deps.get_runner.cache_clear()
    deps.get_job_manager.cache_clear()
    yield
    deps.get_blob_store.cache_clear()
    deps.get_runner.cache_clear()
    deps.get_job_manager.cache_clear()


@pytest.fixture(autouse=True)
def skip_real_transcription(monkeypatch):
    """Force TranscribeService onto its stub-fallback path in every test.

    The suite uses fake audio bytes to exercise pipeline orchestration — not
    transcription quality — and running real Basic Pitch inference on those
    bytes is both slow (cold-start CoreML/ONNX compilation) and flaky
    (librosa silently decodes garbage into zero-length audio). Raising an
    exception from the sync inference helper routes TranscribeService.run
    through its `except Exception -> _stub_result` branch, which is exactly
    what the pipeline tests need.
    """
    def _fail_fast(*_args, **_kwargs):
        raise RuntimeError("real transcription disabled in tests")

    monkeypatch.setattr(transcribe_module, "_run_basic_pitch_sync", _fail_fast)


@pytest.fixture(autouse=True)
def celery_eager_mode():
    """Run Celery tasks in-process for all tests."""
    _celery_app.conf.task_always_eager = True
    _celery_app.conf.task_eager_propagates = True
    yield
    _celery_app.conf.task_always_eager = False
    _celery_app.conf.task_eager_propagates = False


@pytest.fixture
def client():
    """TestClient inside a `with` block so the lifespan and ASGI portal stay alive
    for the whole test. Without this, background asyncio tasks created during
    a request never get a chance to progress between sync calls."""
    app = create_app()
    with TestClient(app) as c:
        yield c
