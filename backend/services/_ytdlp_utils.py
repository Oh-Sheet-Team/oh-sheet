"""Shared yt-dlp helpers used by both ``ingest`` and ``cover_search``.

Kept separate to avoid circular imports (``ingest`` already imports
from ``cover_search``, so the helper can't live in either one).
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from backend.config import settings

log = logging.getLogger(__name__)


# yt-dlp treats the cookiefile as read/write — it rotates session auth
# tokens during a download and writes them back to disk. The deployed
# source file is bind-mounted ``:ro`` in docker-compose.prod.yml, so
# pointing yt-dlp directly at it crashes with
# ``[Errno 30] Read-only file system``. We copy the source into a
# pid-scoped tmp file on each call and hand yt-dlp the writable copy.
# The copy is ephemeral — any rotations yt-dlp writes get overwritten
# on the next call from the read-only source of truth.
_TMP_COOKIES = Path(tempfile.gettempdir()) / f"ytdlp-cookies-{os.getpid()}.txt"


def apply_ytdlp_cookies(ydl_opts: dict) -> None:
    """Inject the configured cookies file into a yt-dlp options dict.

    YouTube periodically flags known data-center IPs (GCP, AWS, ...) as
    bot traffic and demands a signed-in session. When that happens,
    yt-dlp returns "Sign in to confirm you're not a bot" and the job
    fails. Passing cookies from a logged-in browser session bypasses
    the check.

    Reads ``settings.ytdlp_cookies_path``. Only activates the cookiefile
    when the path points at an existing non-empty file — a missing or
    empty file (the default state before the OHSHEET_YTDLP_COOKIES
    secret is set) is treated as "no cookies, run anonymously." This
    makes the deploy safe whether or not cookies are provisioned.
    """
    path_str = settings.ytdlp_cookies_path
    if not path_str:
        return
    src = Path(path_str)
    try:
        if not (src.is_file() and src.stat().st_size > 0):
            return
    except OSError as exc:
        # e.g. permission denied or path raced into existence — don't
        # crash, just log and run anonymously.
        log.warning("ytdlp cookies: cannot stat %s: %s", path_str, exc)
        return

    try:
        shutil.copyfile(src, _TMP_COOKIES)
    except OSError as exc:
        # Tmp dir full / permission-denied — yt-dlp runs without
        # cookies rather than crashing the job.
        log.warning(
            "ytdlp cookies: cannot copy %s to %s: %s",
            src, _TMP_COOKIES, exc,
        )
        return

    ydl_opts["cookiefile"] = str(_TMP_COOKIES)
