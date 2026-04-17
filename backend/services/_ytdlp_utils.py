"""Shared yt-dlp helpers used by both ``ingest`` and ``cover_search``.

Kept separate to avoid circular imports (``ingest`` already imports
from ``cover_search``, so the helper can't live in either one).
"""
from __future__ import annotations

import logging
from pathlib import Path

from backend.config import settings

log = logging.getLogger(__name__)


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
    p = Path(path_str)
    try:
        if p.is_file() and p.stat().st_size > 0:
            ydl_opts["cookiefile"] = str(p)
    except OSError as exc:
        # e.g. permission denied or path raced into existence — don't
        # crash, just log and run anonymously.
        log.warning("ytdlp cookies: cannot stat %s: %s", path_str, exc)
