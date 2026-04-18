"""HTTP client for the oh-sheet-ml-pipeline engraver service.

Oh Sheet POSTs MIDI bytes to the service's ``/engrave`` endpoint and
receives MusicXML bytes in response. Gated by
``settings.engraver_inference``.

Unlike ``tunechat_client``, this raises on failure: the engraver-inference
toggle is operator-controlled and an outage should surface loudly rather
than silently falling back to the pretty_midi path — that's what
``OHSHEET_ENGRAVER_INFERENCE=false`` is for.
"""
from __future__ import annotations

import logging

import httpx

from backend.config import settings

log = logging.getLogger(__name__)


class MLEngraverError(RuntimeError):
    """Raised when the engraver service cannot be reached or returns non-2xx."""


# Catches the header-only placeholder that oh-sheet-ml-pipeline's /engrave
# returns before a real seq2seq model is wired. A real transcription's
# MusicXML runs many KB; the stub is a few hundred bytes of boilerplate.
_STUB_MUSICXML_BYTE_CEILING = 500


def _looks_like_stub(musicxml_bytes: bytes) -> bool:
    return len(musicxml_bytes) < _STUB_MUSICXML_BYTE_CEILING


async def engrave_midi_via_ml_service(midi_bytes: bytes) -> bytes:
    """POST MIDI bytes to the engraver service, return MusicXML bytes.

    Raises ``MLEngraverError`` on transport failure, timeout, or non-2xx.
    """
    url = f"{settings.engraver_service_url.rstrip('/')}/engrave"
    timeout = settings.engraver_service_timeout_sec

    log.info("ml_engraver: POST %s bytes_in=%d timeout=%ds", url, len(midi_bytes), timeout)
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
        log.warning(
            "ml_engraver: engraver_inference=true but response appears to be "
            "the ML pipeline stub placeholder (bytes_out=%d < %d). Confirm "
            "a real model is deployed before trusting these artifacts.",
            len(musicxml),
            _STUB_MUSICXML_BYTE_CEILING,
        )
    log.info("ml_engraver: success bytes_out=%d", len(musicxml))
    return musicxml
