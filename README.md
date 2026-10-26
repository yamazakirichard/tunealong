# Songbook

A self-hosted library for playing along to songs downloaded from YouTube. You
can change pitch and tempo per song and save the settings as presets.

Work in progress: see [plan/songbook-PLAN.md](plan/songbook-PLAN.md).

## Development

Run everything from this directory.

```sh
make fixtures     # generate test media with ffmpeg
make test         # backend (pytest) + frontend (vitest) tests
make test-docker  # backend suite in Docker, with real ffmpeg + rubberband
make e2e          # Playwright (Chromium) in Docker against the dev stack
make dev          # API + worker + fake MeTube + built UI on :8080, scratch data in .dev-data/
```

Needs Python 3.12, ffmpeg (with libvpx-vp9, libopus, libx264), Node 22 and
Docker. rubberband-cli is only needed outside Docker.

## Credits

The visual style is forked from
[gethomepage/homepage](https://github.com/gethomepage/homepage) v2.7.0
(GPL-3.0). Live pitch shifting uses
[SoundTouchJS](https://github.com/cutterbl/SoundTouchJS) (MPL-2.0). See
[NOTICE](NOTICE).

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
