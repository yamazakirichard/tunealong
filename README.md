# Songbook

A self-hosted library for playing along to songs: downloaded from YouTube,
recorded from a browser tab, or loaded from Guitar Pro / MusicXML tab files.

- Your songs appear in a grid grouped by artist (or by your own categories),
  in a style forked from [Homepage](https://github.com/gethomepage/homepage).
- Click a song and it plays in a near-full-screen player. Close it with ✕ or Esc.
- Change pitch (semitones) and tempo, and save the settings as named presets.
  A song reopens with the preset you last saved or picked (or the original, if you picked that).
- Saved presets are rendered once with Rubber Band (pitch and tempo; the video
  is retimed, never re-encoded) and cached, so next time they play instantly
  at full quality. While you experiment, a lighter live preview plays.
- Paste a YouTube URL to add a song. Artist and title are guessed from the
  video's YouTube title (`SONGBOOK_OEMBED_URL=` turns that off). The same video
  is never downloaded twice.
- Add tab files too (Guitar Pro or MusicXML). They play in the browser with
  [alphaTab](https://github.com/CoderLine/alphaTab): the tab scrolls with a
  cursor, and pitch, tempo, volume, loops and presets work as for videos,
  with no render needed.
- Or record another browser tab (picture and sound) straight into the library:
  you start playback there yourself, then press Stop.
- Each artist's picture is shown beside their name. The worker looks every
  artist up once on [TheAudioDB](https://www.theaudiodb.com) and keeps the
  picture in `data/artist-images/` (`SONGBOOK_AUDIODB_URL=` turns that off).

It runs as three containers: `api` (web UI and API on one port), `worker`
(downloads, renders, library scans) and a bundled
[MeTube](https://github.com/alexta69/metube).

## Quick start

```sh
cp .env.example .env      # adjust PUID/PGID to your user (`id -u`, `id -g`)
docker compose up -d
```

Open <http://localhost:8080>. The first `up` builds the image, which takes a
few minutes. Everything is stored in `./data` (set `SONGBOOK_DATA` to change
it):

```
data/
├── songbook.sqlite        the library: songs, artists, categories, presets
├── originals/             downloaded and imported media (MeTube writes here)
├── playback/              H.264 copies of originals in other codecs: rebuildable
├── renders/               pitch/tempo renders: a disposable cache
├── artist-images/         artist pictures from TheAudioDB
└── metube-state/          MeTube's queue
```

All settings are environment variables, documented in
[.env.example](.env.example). Note that variables already set in your shell
win over `.env` (that's how Compose works). If `PUID`/`PGID` are exported in
your environment, they're the ones used.

> **Live pitch needs HTTPS (or localhost).** The player shifts pitch live with
> a Web Audio worklet, which browsers only allow in a secure context. On plain
> `http://<server-ip>:8080` the player still works, but it shows "live pitch
> unavailable": saved presets play shifted from their cached renders, and only
> tempo changes live. Put Songbook behind HTTPS (see below) to get live pitch
> from other devices.

## Importing your existing MeTube downloads

If you already have a folder of MeTube downloads with arbitrary names
(`Artist - Title [id].webm`, `Some title.mp4`, …), import them once:

```sh
# 1. See what would happen. Nothing is changed:
docker compose run --rm -v /path/to/old/downloads:/import:ro api \
  python -m songbook.import_legacy /import --dry-run

# 2. Then for real:
docker compose run --rm -v /path/to/old/downloads:/import:ro api \
  python -m songbook.import_legacy /import
```

- A file with an `[id]` suffix becomes a YouTube song, so adding that URL later
  is recognised as a duplicate. Anything else becomes a "local" song, which you
  can link to a YouTube URL later from its menu.
- The artist and title are guessed from `Artist - Title`. Check the dry run:
  names like `Song - Artist - Lesson` guess wrong. You can fix them in the UI
  afterwards, or rename the files first.
- When the same title exists as both audio and video, only the video is
  imported. Files already in the library are skipped.
- Supported: webm, mp4, mkv, mp3, m4a. Source files are never moved or
  deleted: they are hardlinked when on the same filesystem, otherwise copied.

## Adding tab files

In **Add song**, pick **Tab file** and choose a Guitar Pro (`.gp`, `.gp3`,
`.gp4`, `.gp5`, `.gpx`) or MusicXML (`.musicxml`, `.xml`, `.mxl`) file. The
artist and title come from the file itself, and you can change them before
adding. The same file can't be added twice.

- Tab files are stored in `data/originals/tabs/` and belong in backups like
  the other originals. Files you copy into that folder yourself are picked up
  by the next library scan, if they're named `<16 hex characters>.<ext>` like
  the uploaded ones.
- The player shows one track at a time (pick it under **Track**; the choice is
  remembered) and plays all of them. Click a note to jump there.
- Pitch moves in whole semitones for tabs. Tempo, volume (up to 200%), A/B
  loops and presets work exactly as for videos. Nothing is rendered: alphaTab's
  built-in synthesizer plays the notes live, so there's no "rendering…" wait.
- Uploads are limited to `SONGBOOK_TAB_MAX_MB` (default 10).

## Recording a browser tab

In **Add song**, pick **Record a tab** (Chrome or Edge, over HTTPS):

1. Press **Record**. In the browser's share dialog, pick the tab to record and
   tick **Also share tab audio**.
2. Go to that tab and start playback there yourself.
3. Come back and press **Stop** (or use **Stop sharing** in the browser's bar).
   Check the preview, set artist and title, and press **Add**.

The recording becomes a local video song. The server remuxes it with ffmpeg
(streams copied, not re-encoded) so it can be seeked, and from then on it
works like any other song: Rubber Band presets, loops, volume. Recordings go to
`data/originals/local/`, up to `SONGBOOK_RECORDING_MAX_MB` (default 1024).
Songbook only receives what the browser's screen sharing gives it. It never
opens, controls or reads the other tab. What you record is up to you, and so
is following that site's terms.

## Video formats

Downloads keep the best quality the source offers, and `originals/` is never
changed. That is often AV1 or VP9, and Safari only plays AV1 on Macs with a
hardware decoder, so the worker also makes an H.264 copy at the same resolution
of anything else that arrives (`playback/<song id>.mp4`). The player and new
renders use that copy once it's ready; until then the song plays only where the
browser can decode the original. Songs already in the library when this arrived
are left as they are. To convert them, run this in the worker container:

```
python -m songbook.playback queue <song id>   # or: queue all
```

## Backups

Back up `data/originals/`, `data/songbook.sqlite` and `data/artist-images/`
(small; the database records which artists already have one). **Leave out
`data/renders/`**: it's a cache that rebuilds itself as songs are played. You
can also leave out `data/playback/`: `python -m songbook.playback queue all`
remakes it from the originals.
For a consistent copy of the database while the app is running, use
`sqlite3 data/songbook.sqlite ".backup songbook-backup.sqlite"`.

The render cache is kept under `SONGBOOK_CACHE_MAX_GB` (default 20). The worker
checks every hour and removes the least-used renders first.

## Optional built-in login

Off by default: leave it off if your reverse proxy or SSO already handles
login. To turn on HTTP Basic auth for everything except `/api/health`:

```sh
docker compose run --rm api python -c \
  "import bcrypt,getpass; print(bcrypt.hashpw(getpass.getpass().encode(), bcrypt.gensalt()).decode())"
```

Put the hash in `.env` with **every `$` doubled**, or Compose will mangle it:

```
SONGBOOK_AUTH_USER=me
SONGBOOK_AUTH_PASSWORD_HASH=$$2b$$12$$…
```

## Running behind a reverse proxy

Songbook serves everything (UI, API, media) on one port, so any reverse proxy
works. A few things matter:

- **Forward the `Range` header and don't buffer media responses.** Seeking in
  the player relies on HTTP range requests.
- **Subpath:** to serve under `https://example.com/songbook/`, set
  `SONGBOOK_BASE_PATH=/songbook` and have the proxy pass the path through
  unchanged. No rebuild is needed.
- Set `SONGBOOK_BIND=127.0.0.1` if the proxy runs on the same host, so port
  8080 isn't reachable directly.

One-line examples, for a root domain:

```
# Caddy
songbook.example.com { reverse_proxy localhost:8080 }

# nginx (inside a server block)
location / { proxy_pass http://127.0.0.1:8080; proxy_buffering off; proxy_set_header Range $http_range; proxy_set_header If-Range $http_if_range; }

# Traefik (labels on the api service)
traefik.http.routers.songbook.rule=Host(`songbook.example.com`)
```

## Using an existing MeTube

To use a MeTube you already run instead of the bundled one:

1. Set `METUBE_URL` in `.env` to its address, as reachable from the worker
   container (for example `http://metube:8081` on a shared Docker network).
2. Mount the same download folder as Songbook's `originals/`: MeTube's
   download directory and `SONGBOOK_DATA/originals` must be the same place.
3. Configure that MeTube with:
   ```
   OUTPUT_TEMPLATE=%(id)s.%(ext)s
   YTDL_OPTIONS={"writeinfojson": true, "merge_output_format": "mp4"}
   ```
   **Don't enable `download_archive`.** Songbook does its own dedup, and an
   archive would silently block re-downloading a song you deleted.
4. Remove or scale down the bundled `metube` service, for example with
   `docker compose up -d api worker`.

To also use the bundled MeTube's own web UI, add `-f compose.yml -f
compose.metube-ui.yml`, which publishes it on `127.0.0.1:8081`.

## Development

Run everything from this directory.

```sh
make fixtures      # generate test media with ffmpeg
make test          # backend (pytest) + frontend (vitest)
make test-docker   # backend suite in Docker, with real ffmpeg + rubberband
make e2e           # Playwright (Chromium) in Docker against the dev stack
make compose-test  # the compose deployment end to end (needs port 8080 free)
make dev           # API + worker + fake MeTube + built UI on :8080, scratch data in .dev-data/
```

Needs Python 3.12, ffmpeg (with libvpx-vp9, libopus, libx264), Node 22 and
Docker. rubberband-cli is only needed outside Docker. No test touches the
network: downloads go to a fake MeTube.

How the components fit together is described in
[ARCHITECTURE.md](ARCHITECTURE.md). Design decisions are recorded in
[DECISIONS.md](DECISIONS.md), and the original plan is in
[plan/songbook-PLAN.md](plan/songbook-PLAN.md).

## Credits

The visual style is forked from
[gethomepage/homepage](https://github.com/gethomepage/homepage) v2.7.0
(GPL-3.0). Live pitch shifting uses
[SoundTouchJS](https://github.com/cutterbl/SoundTouchJS) (MPL-2.0). Tab files
are drawn and played by [alphaTab](https://github.com/CoderLine/alphaTab)
(MPL-2.0), with the Bravura music font (SIL OFL 1.1) and the Sonivox SoundFont
(Apache-2.0) it ships. Offline
renders use [Rubber Band](https://breakfastquay.com/rubberband/) and
[FFmpeg](https://ffmpeg.org/). See [NOTICE](NOTICE).

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
