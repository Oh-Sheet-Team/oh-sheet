"""HTTP client for the oh-sheet-ml-pipeline engraver service.

Oh Sheet POSTs MIDI bytes to the service's ``/engrave`` endpoint and
receives MusicXML bytes in response. This is the only engrave path —
there is no local fallback — so failures propagate as job errors.

Transient errors (timeouts, 5xx) retry a small number of times with
backoff before surfacing; this is a different failure-mode than a
fallback (still only the ML service, just one more chance) and keeps
the pipeline tolerant of brief upstream blips without masking real
outages.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from backend.config import settings

log = logging.getLogger(__name__)


class MLEngraverError(RuntimeError):
    """Raised when the engraver service cannot be reached or returns non-2xx."""


# A real seq2seq transcription's MusicXML runs many KB; anything below
# this ceiling almost certainly indicates the service returned the
# in-tree placeholder skeleton (header + empty measure) rather than a
# real score. Treating that as a success would silently surface a blank
# score to the user — the exact failure mode this PR sets out to kill —
# so we raise ``MLEngraverError`` instead and let the job fail loudly.
_STUB_MUSICXML_BYTE_CEILING = 500

# Retry policy for transient upstream failures. The full pipeline has
# already run ingest/transcribe/arrange/humanize by the time we get here,
# so a retry on a momentary timeout or 5xx is cheap insurance — and it's
# NOT a fallback (same service, same contract, just one more attempt).
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SEC = 0.5


def _looks_like_stub(musicxml_bytes: bytes) -> bool:
    return len(musicxml_bytes) < _STUB_MUSICXML_BYTE_CEILING


async def engrave_midi_via_ml_service(midi_bytes: bytes) -> bytes:
    """POST MIDI bytes to the engraver service, return MusicXML bytes.

    Raises ``MLEngraverError`` on transport failure, timeout, non-2xx,
    or a response that looks like the placeholder stub.

    Transient failures (``TimeoutException`` / 5xx) retry up to
    ``_MAX_ATTEMPTS`` times with exponential backoff. Non-retryable
    failures (4xx, placeholder response) surface on the first attempt.
    """
    url = f"{settings.engraver_service_url.rstrip('/')}/engrave"
    timeout = settings.engraver_service_timeout_sec

    log.info("ml_engraver: POST %s bytes_in=%d timeout=%ds", url, len(midi_bytes), timeout)

    last_exc: MLEngraverError | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            musicxml = await _post_once(url, midi_bytes, timeout)
        except MLEngraverError as exc:
            last_exc = exc
            if not _is_retryable(exc) or attempt == _MAX_ATTEMPTS:
                raise
            backoff = _BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            log.warning(
                "ml_engraver: attempt %d/%d failed (%s); retrying in %.1fs",
                attempt, _MAX_ATTEMPTS, exc, backoff,
            )
            await asyncio.sleep(backoff)
            continue
        log.info("ml_engraver: success bytes_out=%d attempt=%d", len(musicxml), attempt)
        return musicxml

    # Unreachable: the loop either returns or raises, but keep mypy happy.
    assert last_exc is not None
    raise last_exc


async def _post_once(url: str, midi_bytes: bytes, timeout: int) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                content=midi_bytes,
                headers={"Content-Type": "application/octet-stream"},
            )
    except httpx.TimeoutException as exc:
        raise MLEngraverError(f"engraver service timed out after {timeout}s") from exc
    except httpx.HTTPError as exc:
        raise MLEngraverError(f"engraver service transport error: {exc}") from exc

    if response.status_code != 200:
        raise MLEngraverError(
            f"engraver service returned HTTP {response.status_code}: {response.text[:200]}"
        )

    musicxml = response.content
    if _looks_like_stub(musicxml):
        raise MLEngraverError(
            f"engraver service returned suspiciously small payload "
            f"(bytes_out={len(musicxml)} < {_STUB_MUSICXML_BYTE_CEILING}); "
            f"service is likely running the in-tree placeholder rather "
            f"than a real model. Refusing to surface a blank score."
        )
    return musicxml


def _is_retryable(exc: MLEngraverError) -> bool:
    """Return True for transient upstream failures worth retrying.

    Timeouts and 5xx are transient. 4xx (bad MIDI, auth, etc.) and the
    stub-payload check are deterministic — retrying would change
    nothing. Transport errors (connection refused, DNS) are also
    treated as transient since Cloud Run / load balancers can drop
    connections briefly.
    """
    msg = str(exc)
    return (
        "timed out" in msg
        or "transport error" in msg
        or "HTTP 5" in msg  # 500, 502, 503, 504
    )
