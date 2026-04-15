"""HTTP tests — health, /transcribe happy path, concurrency non-blocking."""
import asyncio
import time

import httpx
import pytest
from inference.app import app
from inference.midi_pipeline import PerfChunk, ScoreChunk
from inference.model import StubModelRunner

from tests.fixtures import make_sample_midi


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://inf") as c:
        yield c


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["runner"] == "stub"


async def test_transcribe_happy_path(client):
    midi = make_sample_midi(num_notes=8)
    r = await client.post(
        "/transcribe",
        content=midi,
        headers={"content-type": "application/octet-stream"},
    )
    assert r.status_code == 200
    assert "musicxml" in r.headers.get("content-type", "")
    assert r.content.startswith(b"<?xml")
    assert b"score-partwise" in r.content
    assert r.headers.get("x-request-id")


async def test_transcribe_rejects_empty_body(client):
    r = await client.post("/transcribe", content=b"")
    assert r.status_code == 400


async def test_transcribe_rejects_bad_midi(client):
    r = await client.post("/transcribe", content=b"not a midi file")
    assert r.status_code == 400


class _BlockingStubRunner(StubModelRunner):
    """Sleeps inside transcribe_chunk to simulate slow tensor ops.

    The point of this test is to prove the event loop isn't blocked:
    if /transcribe held the loop, N concurrent requests would take
    N × delay seconds total. With run_in_executor, they overlap.
    """
    BLOCK_SECONDS = 0.4

    def transcribe_chunk(self, chunk: PerfChunk) -> ScoreChunk:
        time.sleep(self.BLOCK_SECONDS)
        return super().transcribe_chunk(chunk)


async def test_concurrent_requests_do_not_serialize(client):
    """Load-test: 4 concurrent requests should finish in < 2 × single latency.

    The stub runner is swapped in-place for a version that sleeps 0.4s
    per chunk. With max_workers=4 (default) the 4 requests should run
    in parallel, not serially.
    """
    original = app.state.runner
    app.state.runner = _BlockingStubRunner(app.state.settings)
    app.state.runner.load()
    try:
        midi = make_sample_midi(num_notes=4)
        n_concurrent = 4

        async def one():
            r = await client.post("/transcribe", content=midi)
            assert r.status_code == 200

        t0 = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(n_concurrent)))
        elapsed = time.perf_counter() - t0

        # Serial would be ~n * 0.4 = 1.6s. Concurrent should be ~0.4-0.8s.
        # Allow generous headroom for CI variance.
        assert elapsed < (n_concurrent * _BlockingStubRunner.BLOCK_SECONDS) * 0.75, (
            f"requests appear to be serialized: {elapsed:.2f}s for {n_concurrent} reqs"
        )
    finally:
        app.state.runner = original
