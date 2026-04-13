"""INT-07 smoke tests for GET /v1/artifacts/{job_id}/lilypond."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import deps
from backend.config import settings


def _audio_payload(blob_root: Path) -> dict:
    audio_file = blob_root / "jobs" / "test" / "uploads" / "audio" / "test.mp3"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_bytes(b"\x00" * 64)
    return {
        "audio": {
            "uri": f"file://{audio_file}",
            "format": "mp3",
            "sample_rate": 44100,
            "duration_sec": 1.0,
            "channels": 2,
        },
        "title": "Test Song",
        "artist": "Tester",
    }


def test_lilypond_404_for_unknown_job(client: TestClient) -> None:
    """Unknown job_id -> 404."""
    response = client.get("/v1/artifacts/nonexistent-job-id/lilypond")
    assert response.status_code == 404
    assert "Job not found" in response.json()["detail"]


def test_lilypond_404_when_source_absent(client: TestClient) -> None:
    """Succeeded job that did not produce .ly (no LilyPond on test host) -> 404."""
    body = _audio_payload(settings.blob_root)
    body["enable_refine"] = False  # regular job, no refine
    r = client.post("/v1/jobs", json=body)
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    # Wait for job to reach a terminal state (reuses polling pattern from test_artifacts.py).
    deadline = time.time() + 5.0
    status: str = "pending"
    while time.time() < deadline:
        resp = client.get(f"/v1/jobs/{job_id}").json()
        status = resp["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    # If LilyPond is not installed in test env, .ly is absent -> 404.
    # If LilyPond IS installed and rendered, .ly is present -> 200. Either
    # outcome is valid for this test; we assert the status code + headers
    # match one of the two valid paths.
    resp = client.get(f"/v1/artifacts/{job_id}/lilypond")
    if resp.status_code == 200:
        assert resp.headers["content-type"] == "application/x-lilypond"
        assert len(resp.content) > 0
    else:
        assert resp.status_code == 404
        # Detail explains why .ly is absent
        detail = resp.json()["detail"]
        assert "LilyPond" in detail or "lilypond" in detail.lower()


def test_lilypond_409_when_job_still_running(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Job present but status != succeeded -> 409."""
    # Inject a record in 'running' state directly.
    from backend.contracts import (
        SCHEMA_VERSION,
        InputBundle,
        InputMetadata,
        PipelineConfig,
        RemoteAudioFile,
    )
    from backend.jobs.manager import JobRecord

    blob_root = settings.blob_root
    audio_file = blob_root / "jobs" / "stuck" / "uploads" / "audio" / "test.mp3"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_bytes(b"\x00" * 64)

    manager = deps.get_job_manager()
    record = JobRecord(
        job_id="stuck-job",
        status="running",
        config=PipelineConfig(variant="audio_upload"),
        bundle=InputBundle(
            schema_version=SCHEMA_VERSION,
            audio=RemoteAudioFile(
                uri=f"file://{audio_file}",
                format="mp3",
                sample_rate=44100,
                duration_sec=1.0,
                channels=2,
            ),
            midi=None,
            metadata=InputMetadata(title="x", artist="y", source="audio_upload"),
        ),
    )
    manager._jobs["stuck-job"] = record

    resp = client.get("/v1/artifacts/stuck-job/lilypond")
    assert resp.status_code == 409
    assert "running" in resp.json()["detail"]
    # Cleanup for next test
    del manager._jobs["stuck-job"]
