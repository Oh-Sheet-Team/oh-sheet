# yt-dlp cookies — refresh recipe

YouTube periodically flags our VM's IP as bot traffic and demands a
logged-in session. When that happens, users see the following error:

```
yt-dlp download failed for https://...: ERROR: [youtube] ...:
Sign in to confirm you're not a bot.
```

The fix is to provide yt-dlp with a cookies file exported from a
browser where you're signed in to YouTube. The cookies live in the
`OHSHEET_YTDLP_COOKIES` GitHub secret; refreshing them is a 5-minute
process run from your local machine.

## When to refresh

- **Users report the "Sign in to confirm" error** — refresh immediately
- **Cookies are ~3 months old** — refresh proactively (Google rotates
  session tokens over time)
- **After switching Google accounts** for YouTube access

## Export recipe (Chrome / Brave / Edge / Firefox)

### Option A — browser extension (easiest)

1. Install [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookies-txt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   (or the Firefox equivalent "cookies.txt")
2. Sign in to <https://www.youtube.com> in that browser
3. Click the extension icon, choose "Export as Netscape cookies.txt"
4. Save to `~/Downloads/youtube-cookies.txt`

### Option B — via yt-dlp itself (CLI)

If you have yt-dlp installed locally:

```bash
yt-dlp --cookies-from-browser chrome \
       --cookies ~/Downloads/youtube-cookies.txt \
       --skip-download \
       https://www.youtube.com
```

Replace `chrome` with `firefox`, `brave`, `safari`, or `edge` as
appropriate. The `--cookies` flag writes out the extracted cookies in
Netscape format.

## Upload to GitHub

From your local machine (where the cookies file lives):

```bash
cd /path/to/oh-sheet

# Verify the cookies file looks right (first line should be a Netscape
# header comment, subsequent lines should be tab-separated cookie records)
head -3 ~/Downloads/youtube-cookies.txt

# Push to both environments (same cookies for qa + prod by default)
gh secret set OHSHEET_YTDLP_COOKIES --env qa   < ~/Downloads/youtube-cookies.txt
gh secret set OHSHEET_YTDLP_COOKIES --env prod < ~/Downloads/youtube-cookies.txt

# Verify
gh secret list --env qa   | grep OHSHEET_YTDLP_COOKIES
gh secret list --env prod | grep OHSHEET_YTDLP_COOKIES
```

Deleting `~/Downloads/youtube-cookies.txt` afterward is good hygiene —
the cookies are session credentials, treat them like a password.

## Trigger a redeploy

Setting the secret doesn't automatically redeploy. Push an empty commit
to the target branch (qa or main) or re-run the latest deploy workflow:

```bash
gh workflow run "Deploy to VM" --ref qa
```

## How it wires through

1. **GitHub Secret**: `OHSHEET_YTDLP_COOKIES` (env-scoped to `qa` + `prod`)
2. **Deploy step** reads secret → writes `/tmp/youtube-cookies.txt` →
   `scp`s to `~/oh-sheet/youtube-cookies.txt` on the VM
3. **docker-compose.prod.yml** bind-mounts the file into containers at
   `/app/youtube-cookies.txt` (read-only)
4. **backend/config.py** exposes the path via
   `settings.ytdlp_cookies_path` (env: `OHSHEET_YTDLP_COOKIES_PATH`)
5. **backend/services/_ytdlp_utils.py** `apply_ytdlp_cookies()` adds
   `cookiefile` to yt-dlp's options ONLY IF the file exists and is
   non-empty. Unset/empty = run anonymously.

## Anonymous fallback

When the secret is unset (or empty), everything still works — yt-dlp
runs without cookies. This is the "works on a fresh VM with no setup"
mode, and it's what you hit on any new deployment before cookies are
provisioned. Users may see the bot error intermittently; refresh
cookies when that happens.

## Adding yt-dlp to a new service

The cookies file is bind-mounted into **orchestrator** and
**worker-ingest** today, because those are the only services that call
yt-dlp (orchestrator via `cover_search`, worker-ingest via `_download_youtube_sync`).

If a future service adds a yt-dlp call site, it needs three things to
pick up the cookies:

1. **Bind mount** in `docker-compose.prod.yml` — add
   `./youtube-cookies.txt:/app/youtube-cookies.txt:ro` to the service's
   `volumes:` block.
2. **Env var** — add `OHSHEET_YTDLP_COOKIES_PATH: /app/youtube-cookies.txt`
   to the service's `environment:` block.
3. **Helper call** — wherever yt-dlp's `YoutubeDL(opts)` is constructed,
   call `apply_ytdlp_cookies(opts)` from `backend.services._ytdlp_utils`
   before the `YoutubeDL(...)` line. The helper is a no-op when cookies
   aren't present, so the new service stays safe on unprovisioned VMs.

If any of the three is missed, the service runs anonymously and may
hit the bot-detection wall — silently, because `apply_ytdlp_cookies`
doesn't raise on missing config.

## Security

- Cookies are session credentials — anyone with them can act as the
  Google account they came from. Treat like a password.
- File permissions enforced via `chmod 600` on the VM
- GitHub masks the secret in workflow logs automatically
- NEVER commit the cookies file to git — `.gitignore` should cover it
  (double-check that `youtube-cookies.txt` is ignored before pushing)
