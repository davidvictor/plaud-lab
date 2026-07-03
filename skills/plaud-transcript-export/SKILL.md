---
name: plaud-transcript-export
description: Export Plaud/Plaud AI recordings, transcripts, summaries, outlines, and related generated notes through the Plaud Web internal API. Use when a user asks to download or back up Plaud transcripts or summaries, inspect Plaud network/API behavior, avoid DOM scraping, preserve recording metadata, or build a repeatable local export from an authenticated Plaud account.
---

# Plaud Transcript Export

## Overview

Use Plaud Web's internal API to enumerate files, fetch per-file details, and download short-lived transcript and summary artifacts into local Markdown and JSON. Prefer the bundled exporter script over DOM scraping.

## Safety Rules

- Export only data the user owns or has explicit permission to access.
- Treat Plaud workspace tokens, cookies, signed S3 URLs, and desktop token stores as secrets.
- Never paste tokens into final answers, tracked files, logs, screenshots, or public repos.
- Sanitize raw metadata before saving or sharing: keep artifact host/path/type/expiry, remove signed query strings.
- State that this uses Plaud's unofficial/internal API and may break if Plaud changes endpoints or auth.

## Workflow

1. Confirm the user is authenticated in Plaud Web or has provided an auth token/cookie through a safe local mechanism.
2. Prefer `scripts/export_plaud.py` for repeatable exports:

   ```bash
   export PLAUD_AUTH_TOKEN="Bearer ..."
   python skills/plaud-transcript-export/scripts/export_plaud.py --output ./plaud-export
   ```

   If using a browser session instead of a token, pass `--cookie "$PLAUD_COOKIE"` or set `PLAUD_COOKIE` locally. Do not commit `.env` files.

3. Use the all-files list endpoint:

   ```text
   GET https://api.plaud.ai/file/simple/web?skip=0&limit=99999&is_trash=2&sort_by=start_time&is_desc=true
   ```

4. For each `data_file_list[].id`, fetch:

   ```text
   GET https://api.plaud.ai/file/detail/{file_id}
   ```

5. In `content_list`, download useful completed artifacts immediately. Signed S3 links are short-lived, commonly about 300 seconds.
6. Write outputs under the selected export folder:
   - `files/`: combined per-record Markdown
   - `transcripts/`: transcript-only Markdown
   - `summaries/`: summary-only Markdown
   - `polished-transcripts/`: Plaud's polished transcript when present
   - `outlines/`: topic outline Markdown when present
   - `raw/<file_id>/`: sanitized detail metadata and raw artifact JSON/Markdown
   - `index.json` and `index.csv`: searchable export manifest

## Auth Notes

Plaud Web requests commonly include:

```text
Authorization: Bearer <workspace token>
X-Request-ID: <random id>
app-language: en
app-platform: web
edit-from: web
timezone: <IANA timezone>
x-device-id: <optional Plaud device/user tag>
x-pld-user: <optional Plaud user/distinct id>
Origin: https://web.plaud.ai
Referer: https://web.plaud.ai/
```

The exporter accepts the required token/cookie plus optional header values. If an API call returns 401/403 or Plaud status codes for expired auth, ask the user to refresh Plaud Web and provide a current workspace token/cookie locally.

## Resource

- `scripts/export_plaud.py`: stdlib-only CLI exporter.
- `references/api.md`: endpoint and artifact notes; read when debugging API/auth changes.
