#!/bin/sh
# TuneAlong container entrypoint: `api` (default), `worker`, or any command.
# Started as root, it makes the data dirs, gives them (top level only, never a
# recursive walk of the library) to PUID:PGID, then re-runs itself as that user.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
ROOT="${TUNEALONG_ROOT:-/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$ROOT/originals/local" "$ROOT/renders" "$ROOT/playback"
    chown "$PUID:$PGID" "$ROOT" "$ROOT/originals" "$ROOT/originals/local" "$ROOT/renders" "$ROOT/playback"
    for f in "$ROOT"/tunealong.sqlite "$ROOT"/tunealong.sqlite-wal "$ROOT"/tunealong.sqlite-shm; do
        [ -e "$f" ] && chown "$PUID:$PGID" "$f"
    done
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$0" "$@"
fi

umask "${UMASK:-022}"
case "${1:-api}" in
    api)
        shift || true
        exec uvicorn --factory tunealong.main:create_app --host 0.0.0.0 --port "${PORT:-8080}" --no-access-log "$@"
        ;;
    worker)
        exec python -m tunealong.worker
        ;;
    *)
        exec "$@"
        ;;
esac
