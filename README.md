# Songbook

A self-hosted library for playing along to songs downloaded from YouTube. You
can change pitch and tempo per song and save the settings as presets.

Work in progress: see [plan/songbook-PLAN.md](plan/songbook-PLAN.md).

## Development

Run everything from this directory.

```sh
make fixtures   # generate test media with ffmpeg
make test       # backend (pytest) + frontend (vitest) tests
make dev        # API on :8080, data in ./data
```

Needs Python 3.12, ffmpeg (with libvpx-vp9, libopus, libx264), and later
Node 22 and rubberband-cli.

## Credits

The visual style is forked from
[gethomepage/homepage](https://github.com/gethomepage/homepage) (GPL-3.0). See
[NOTICE](NOTICE).

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
