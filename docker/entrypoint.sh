#!/bin/sh
# Songbook container entrypoint: `api` (default), `worker`, or any command.
# Started as root, it makes the data dirs, gives them (top level only, never a
# recursive walk of the library) to PUID:PGID, then re-runs itself as that user.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
ROOT="${SONGBOOK_ROOT:-/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$ROOT/originals/local" "$ROOT/renders"
    chown "$PUID:$PGID" "$ROOT" "$ROOT/originals" "$ROOT/originals/local" "$ROOT/renders"
    for f in "$ROOT"/songbook.sqlite "$ROOT"/songbook.sqlite-wal "$ROOT"/songbook.sqlite-shm; do
        [ -e "$f" ] && chown "$PUID:$PGID" "$f"
    done
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$0" "$@"
fi

umask "${UMASK:-022}"
case "${1:-api}" in
    api)
        shift || true
        exec uvicorn --factory songbook.main:create_app --host 0.0.0.0 --port "${PORT:-8080}" --no-access-log "$@"
        ;;
    worker)
        exec python -m songbook.worker
        ;;
    *)
        exec "$@"
        ;;
esac
