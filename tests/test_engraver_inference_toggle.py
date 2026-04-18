"""OHSHEET_ENGRAVER_INFERENCE toggle tests.

When the toggle is on, audio_upload and midi_upload jobs should route their
engraving through ``ml_engraver_client.engrave_midi_via_ml_service`` instead
of the local music21 engrave stage. title_lookup jobs should keep the
existing path regardless.
"""
from __future__ import annotations

import pytest
from shared.contracts import (
    InputBundle,
    InputMetadata,
    PipelineConfig,
    RemoteAudioFile,
    RemoteMidiFile,
)
from shared.storage.local import LocalBlobStore

from backend.config import settings
from backend.jobs.runner import PipelineRunner
from backend.services import ml_engraver_client
from backend.workers.celery_app import celery_app

_FAKE_MUSICXML = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="no"?>'
    b'<score-partwise version="3.1"><part id="P1"/></score-partwise>'
)


@pytest.fixture
def blob():
    return LocalBlobStore(settings.blob_root)


@pytest.fixture
def runner(blob):
    return PipelineRunner(blob_store=blob, celery_app=celery_app)


@pytest.fixture
def engraver_inference_on(monkeypatch):
    monkeypatch.setattr(settings, "engraver_inference", True)


@pytest.fixture
def mock_ml_engraver(monkeypatch):
    """Replace the real HTTP call with a deterministic byte-returning coroutine."""
    calls: list[bytes] = []

    async def fake_engrave(midi_bytes: bytes) -> bytes:
        calls.append(midi_bytes)
        return _FAKE_MUSICXML

    monkeypatch.setattr(ml_engraver_client, "engrave_midi_via_ml_service", fake_engrave)
    # The runner function imports the symbol lazily from the module — patch the
    # module attribute so the late import picks up the fake.
    return calls


@pytest.mark.asyncio
async def test_audio_upload_uses_ml_service_when_toggle_on(
    runner, blob, engraver_inference_on, mock_ml_engraver,
):
    bundle = InputBundle(
        audio=RemoteAudioFile(
            uri="file:///fake/audio.wav",
            format="wav",
            sample_rate=44100,
            duration_sec=10.0,
            channels=1,
        ),
        metadata=InputMetadata(title="Toggle Test", artist="Tester", source="audio_upload"),
    )
    config = PipelineConfig(variant="audio_upload", enable_refine=False)

    result = await runner.run(
        job_id="toggle-audio-001",
        bundle=bundle,
        config=config,
    )

    assert len(mock_ml_engraver) == 1, "ML engraver should be called exactly once"
    assert result.musicxml_uri
    assert blob.get_bytes(result.musicxml_uri) == _FAKE_MUSICXML
    # PDF is intentionally skipped on the ML path.
    assert result.pdf_uri == ""
    # humanized MIDI is still produced locally (it's the bytes we shipped to the service).
    assert result.humanized_midi_uri


@pytest.mark.asyncio
async def test_midi_upload_uses_ml_service_when_toggle_on(
    runner, blob, engraver_inference_on, mock_ml_engraver,
):
    bundle = InputBundle(
        midi=RemoteMidiFile(uri="file:///fake/input.mid", ticks_per_beat=480),
        metadata=InputMetadata(title="Toggle MIDI", artist="Tester", source="midi_upload"),
    )
    config = PipelineConfig(variant="midi_upload", enable_refine=False)

    result = await runner.run(
        job_id="toggle-midi-001",
        bundle=bundle,
        config=config,
    )

    assert len(mock_ml_engraver) == 1
    assert blob.get_bytes(result.musicxml_uri) == _FAKE_MUSICXML


@pytest.mark.asyncio
async def test_ml_error_propagates_and_fails_job(
    runner, engraver_inference_on, monkeypatch,
):
    """An MLEngraverError from the client should surface, not silently fall back."""
    async def raising(midi_bytes: bytes) -> bytes:
        raise ml_engraver_client.MLEngraverError("simulated outage")

    monkeypatch.setattr(ml_engraver_client, "engrave_midi_via_ml_service", raising)

    bundle = InputBundle(
        audio=RemoteAudioFile(
            uri="file:///fake/audio.wav",
            format="wav",
            sample_rate=44100,
            duration_sec=10.0,
            channels=1,
        ),
        metadata=InputMetadata(title="Err Test", artist="Tester", source="audio_upload"),
    )
    config = PipelineConfig(variant="audio_upload", enable_refine=False)

    with pytest.raises(ml_engraver_client.MLEngraverError, match="simulated outage"):
        await runner.run(
            job_id="toggle-error-001",
            bundle=bundle,
            config=config,
        )


@pytest.mark.asyncio
async def test_toggle_off_keeps_local_engrave(runner, blob, mock_ml_engraver):
    """Default ``engraver_inference=False`` should never touch the ML client."""
    bundle = InputBundle(
        audio=RemoteAudioFile(
            uri="file:///fake/audio.wav",
            format="wav",
            sample_rate=44100,
            duration_sec=10.0,
            channels=1,
        ),
        metadata=InputMetadata(title="Toggle Off", artist="Tester", source="audio_upload"),
    )
    config = PipelineConfig(variant="audio_upload", enable_refine=False)

    result = await runner.run(
        job_id="toggle-off-001",
        bundle=bundle,
        config=config,
    )

    assert mock_ml_engraver == [], "ML engraver must not be called when toggle is off"
    assert result.musicxml_uri
    assert blob.get_bytes(result.musicxml_uri) != _FAKE_MUSICXML


@pytest.mark.asyncio
@pytest.mark.parametrize("toggle", [True, False])
async def test_title_lookup_never_routes_through_ml_engraver(
    runner, blob, monkeypatch, mock_ml_engraver, toggle,
):
    """Regression guard for runner.py:use_ml_engraver gating.

    title_lookup jobs (TuneChat + cover_search fast-path) must never hit
    the ML engraver service regardless of OHSHEET_ENGRAVER_INFERENCE.
    TuneChat's fast-path integration depends on this invariant.
    """
    monkeypatch.setattr(settings, "engraver_inference", toggle)
    # Keep TuneChat disabled so the pipeline falls through to Oh Sheet's
    # own stages — that's where the source gate in runner.py lives.
    monkeypatch.setattr(settings, "tunechat_enabled", False)

    bundle = InputBundle(
        audio=RemoteAudioFile(
            uri="file:///fake/audio.wav",
            format="wav",
            sample_rate=44100,
            duration_sec=10.0,
            channels=1,
        ),
        metadata=InputMetadata(
            title="Title Lookup Song",
            artist="Tester",
            source="title_lookup",
        ),
    )
    config = PipelineConfig(variant="audio_upload", enable_refine=False)

    result = await runner.run(
        job_id=f"title-lookup-{toggle}",
        bundle=bundle,
        config=config,
    )

    assert mock_ml_engraver == [], (
        f"title_lookup must bypass ML engraver (toggle={toggle}) — "
        "TuneChat's fast-path depends on this."
    )
    assert result.musicxml_uri
    assert blob.get_bytes(result.musicxml_uri) != _FAKE_MUSICXML
