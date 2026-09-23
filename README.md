# CamSuite

Self-hosted recorder for public live cam shows. It watches a list of models,
records their **public (free chat) shows** automatically, and gives you a web UI
to watch live, browse recordings, cut clips and manage storage.

Supported sites: **Flirt4Free** (more can be added through the site-adapter
layer, see below).

The UI and recording engine are derived from TikRecGUI.

## Quick start (Docker)

```bash
cp .env.example .env        # set APP_PASSWORD
docker compose up -d --build
```

Open http://localhost:3000 and sign in with `APP_PASSWORD` (if unset, a
password is generated and printed once in `docker compose logs backend`).

Data lives next to the compose file:

| Path | Contents |
|---|---|
| `./recordings/` | Finished MP4s, thumbnails, sprite sheets, `clips/` |
| `./data/` | SQLite DB, settings, login secret, cached avatars, backups |

## How it works

- **Watchlist**: add a model by name (`sara-laurent`) or profile URL
  (`https://www.flirt4free.com/?model=sara-laurent`). Each card shows the room
  state: **LIVE** (public show), **PRIVATE** (private/group/fan show), or offline.
- **Monitoring**: every *check interval* (default 2 min) one request fetches
  Flirt4Free's online list and updates every watchlist model. Monitored
  models in a public show are confirmed against the room itself and then
  recorded.
- **Private shows are never recorded.** If a public show turns private
  mid-recording, capture pauses and resumes if it goes public again. Otherwise
  the recording is finalized.
- **Recording**: ffmpeg pulls the HLS stream (preferred quality is
  configurable) into resumable `.partNNN.ts` segments, which are stitched into
  one faststart MP4 named `F4F_<model>_<YYYY.MM.DD_HH-MM-SS>.mp4`. Thumbnails
  and hover-scrub sprites are generated afterwards.
- **Compression**: after a recording finishes it is re-encoded to AV1
  (SVT-AV1, Opus audio) in the background and the smaller file replaces the
  original, after its duration and codec have been verified. Measured on 1080p
  captures: ~1.4 GB/hour becomes ~0.35 GB/hour at the default "Balanced"
  quality, with no visible difference. One job runs at a time, at low priority,
  on all but two CPU cores. Configure in Settings → Compression, which also
  has a "Compress existing recordings" button for older files.
- **Clips**: cut from any finished recording, or capture a clip live from the
  Live player while it records.
- **Notifications**: in-app feed (SSE), plus optional ntfy / Discord /
  Telegram delivery.

## Development

```bash
# backend (Python 3.12+, ffmpeg on PATH)
cd backend
pip install -r requirements.txt pytest
APP_PASSWORD=dev uvicorn app.main:app --reload --port 8000
pytest

# frontend (Node 20+)
cd frontend
npm install
npm run dev          # http://localhost:3000, proxies /api to :8000
npm run build        # tsc + contrast check + vite build
```

## Adding another cam site

Everything site-specific lives in `backend/app/core/sites/`:

1. Implement `SiteAdapter` (`base.py`): `normalize_username`, `check_status`,
   `bulk_status`, `is_public`, `get_stream_url`, `get_playback_url`,
   `profile_url`, plus the optional `screencap_url`, `fetch_bytes` and
   `reachability`.
2. Register it in `registry.py`.
3. Add its label and profile URL in `frontend/src/lib/sites.ts`.

The monitor, recorder, clips and UI work unchanged. Models are stored per
`(site, username)`.

### Flirt4Free endpoints used

| Purpose | Endpoint |
|---|---|
| All online models + room letter (`O` public, `P`/`F` private) | `GET /?tpl=index2&model=json` (XHR) |
| Single model status / id | `GET ws.vs3.com/rooms/check-model-status.php?model_name=` |
| Authoritative room state | `GET /ws/rooms/chat-room-interface.php?a=login_room&model_id=` |
| HLS master playlist | `GET /ws/chat/get-stream-urls.php?model_id=` then `data.hls[0].url` |
| Live snapshot | `live-screencaps.vscdns.com/{model_id}-desktop.jpg` |

If the site ever serves its "Checking your browser" page, the adapter tries to
solve it with Node (installed in the image). If that fails, the dashboard shows
a "site blocked" warning; setting a proxy in Settings usually helps.
