"""H.264 playback copies: `python -m tunealong.playback queue <song id>|all`.

The original keeps the best quality the source offers, usually AV1 or VP9, and
is never changed. Safari only plays AV1 on Macs with a hardware decoder, so
anything that isn't H.264 also gets playback/<song_id>.mp4 at the same
resolution. /media/originals/<id> serves that copy, and renders take their
video from it (audio still comes from the original).

The single worker makes copies when its queue is idle, or first thing if a
render needs one. Output goes to a hidden temp name and is renamed into place.
"""

import logging
import os
import shutil
import sqlite3
from pathlib import Path

from . import config, db, render

log = logging.getLogger(__name__)

_ENCODE = [
    "-map", "0:V:0", "-map", "0:a:0?",
    # libx264 needs even dimensions; a recorded browser tab can have odd ones.
    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-profile:v", "high",
    # Keep every frame at its own time, with a keyframe every 2 s so seeks and A/B loops land quickly.
    "-fps_mode", "passthrough", "-force_key_frames", "expr:gte(t,n_forced*2)",
    "-c:a", "aac", "-b:a", "256k",
    "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart", "-f", "mp4",
]


def encode(src: Path, final: Path, timeout: float | None = None) -> None:
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(f".{final.stem}.tmp.mp4")
    try:
        render.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src.resolve()),
                    *_ENCODE, str(tmp)], timeout)
        os.replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)


def ensure(conn: sqlite3.Connection, settings: config.Settings, song_id: int) -> None:
    """Settle a pending song: make its copy if it needs one. A failure is logged, not raised:
    the song still plays from its original wherever the browser can decode it."""
    song = conn.execute("SELECT original_path, playback_state, kind, status FROM songs WHERE id = ?",
                        (song_id,)).fetchone()
    if (song is None or song["playback_state"] != "pending" or song["kind"] != "media"
            or song["status"] != "ready" or not song["original_path"]):
        return
    final = settings.playback_dir / f"{song_id}.mp4"
    try:
        codec = render.video_codec(settings.root / song["original_path"])
        if codec is None or codec == "h264":
            conn.execute("UPDATE songs SET playback_path = NULL, playback_state = 'done' WHERE id = ?", (song_id,))
            return
        log.info("song %s is %s: making its H.264 copy", song_id, codec)
        encode(settings.root / song["original_path"], final, settings.playback_timeout_s)
    except Exception as e:
        log.warning("song %s: H.264 copy failed: %s", song_id, e)
        conn.execute("UPDATE songs SET playback_state = 'error' WHERE id = ?", (song_id,))
        return
    with db.transaction(conn):
        n = conn.execute("UPDATE songs SET playback_path = ?, playback_state = 'done'"
                         " WHERE id = ? AND original_path = ?",
                         (final.relative_to(settings.root).as_posix(), song_id, song["original_path"])).rowcount
        # Its renders copied the old video stream; they re-render from the copy on demand.
        if n:
            conn.execute("DELETE FROM renders WHERE song_id = ?", (song_id,))
    if n:
        shutil.rmtree(settings.renders_dir / str(song_id), ignore_errors=True)
    else:  # deleted or replaced while encoding
        final.unlink(missing_ok=True)


def run_next(conn: sqlite3.Connection, settings: config.Settings) -> bool:
    """Settle the oldest pending song. False if there is none."""
    row = conn.execute("SELECT id FROM songs WHERE playback_state = 'pending' AND status = 'ready'"
                       " AND kind = 'media' AND original_path IS NOT NULL ORDER BY id LIMIT 1").fetchone()
    if row is None:
        return False
    ensure(conn, settings, row["id"])
    return True


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m tunealong.playback")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queue", help="have the worker (re)check songs and make the copies they need")
    q.add_argument("song", help="a song id, or 'all'")
    args = ap.parse_args(argv)
    settings = config.load()
    conn = db.open_db(settings.db_path, settings.busy_timeout_ms)
    try:
        if args.song == "all":
            n = conn.execute("UPDATE songs SET playback_state = 'pending' WHERE kind = 'media'").rowcount
        else:
            n = conn.execute("UPDATE songs SET playback_state = 'pending' WHERE kind = 'media' AND id = ?",
                             (int(args.song),)).rowcount
    finally:
        conn.close()
    print(f"{n} song(s) queued")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
