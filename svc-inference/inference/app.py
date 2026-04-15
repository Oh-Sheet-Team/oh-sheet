"""FastAPI entry point for the inference microservice.

Endpoints:
  GET  /health      — liveness + runner status
  POST /transcribe  — body: raw performance MIDI; response: MusicXML

Concurrency model: the lifespan hook builds a bounded
``ThreadPoolExecutor`` and loads the model once. Each request offloads
the full synchronous pipeline (normalize → chunk → runner × N → stitch)
to the executor via ``run_in_executor``, so PyTorch tensor ops and the
constrained beam-search loop never block the event loop.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response

from inference.config import Settings, get_settings
from inference.logging_config import setup_logging
from inference.midi_pipeline import (
    NormalizedPerformance,
    ScoreChunk,
    chunk_performance,
    normalize_midi,
    stitch_chunks,
)
from inference.model import ModelRunner, create_runner

log = logging.getLogger("inference")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    setup_logging(settings.log_level)

    runner = create_runner(settings)
    runner.load()
    executor = ThreadPoolExecutor(
        max_workers=settings.max_workers,
        thread_name_prefix="inference-worker",
    )

    app.state.settings = settings
    app.state.runner = runner
    app.state.executor = executor
    log.info(
        "inference service started",
        extra={
            "runner": runner.name,
            "max_workers": settings.max_workers,
            "device": settings.device,
        },
    )
    try:
        yield
    finally:
        executor.shutdown(wait=True, cancel_futures=False)
        log.info("inference service stopped")


app = FastAPI(title="Oh Sheet Inference", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    runner: ModelRunner = request.app.state.runner
    return {
        "status": "ok",
        "runner": runner.name,
        "device": settings.device,
        "max_workers": settings.max_workers,
    }


@app.post("/transcribe")
async def transcribe(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    runner: ModelRunner = request.app.state.runner
    executor: ThreadPoolExecutor = request.app.state.executor

    midi_bytes = await request.body()
    if not midi_bytes:
        raise HTTPException(status_code=400, detail="empty request body")

    req_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()
    try:
        musicxml = await loop.run_in_executor(
            executor, _run_sync_pipeline, midi_bytes, runner, settings, req_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    log.info(
        "transcribe complete",
        extra={
            "request_id": req_id,
            "latency_ms": latency_ms,
            "bytes_in": len(midi_bytes),
            "bytes_out": len(musicxml),
        },
    )
    return Response(
        content=musicxml,
        media_type="application/vnd.recordare.musicxml+xml",
        headers={"x-request-id": req_id},
    )


def _run_sync_pipeline(
    midi_bytes: bytes,
    runner: ModelRunner,
    settings: Settings,
    req_id: str,
) -> bytes:
    t_norm = time.perf_counter()
    perf: NormalizedPerformance = normalize_midi(midi_bytes)
    norm_ms = round((time.perf_counter() - t_norm) * 1000, 1)

    t_chunk = time.perf_counter()
    chunks = chunk_performance(
        perf,
        window_beats=settings.chunk_window_beats,
        stride_beats=settings.chunk_stride_beats,
    )
    chunk_ms = round((time.perf_counter() - t_chunk) * 1000, 1)

    results: list[ScoreChunk] = []
    decode_steps_total = 0
    rejected_total = 0
    parse_failures = 0
    t_decode = time.perf_counter()
    for ch in chunks:
        sc = runner.transcribe_chunk(ch)
        results.append(sc)
        decode_steps_total += sc.decode_steps
        rejected_total += sc.rejected_tokens
        if sc.parse_failed:
            parse_failures += 1
    decode_ms = round((time.perf_counter() - t_decode) * 1000, 1)

    t_stitch = time.perf_counter()
    musicxml = stitch_chunks(results, perf)
    stitch_ms = round((time.perf_counter() - t_stitch) * 1000, 1)

    log.info(
        "transcribe stages",
        extra={
            "request_id": req_id,
            "chunk_count": len(chunks),
            "note_count": len(perf.notes),
            "tempo_bpm": perf.tempo_bpm,
            "time_signature": f"{perf.time_signature[0]}/{perf.time_signature[1]}",
            "normalize_ms": norm_ms,
            "chunk_ms": chunk_ms,
            "decode_ms": decode_ms,
            "stitch_ms": stitch_ms,
            "beam_width": settings.beam_width,
            "decode_steps": decode_steps_total,
            "rejected_tokens": rejected_total,
            "parse_gate_failures": parse_failures,
        },
    )
    return musicxml
