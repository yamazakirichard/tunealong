"""The single background worker: `python -m songbook.worker`.

There is exactly one worker, so on startup anything still `running` was
orphaned by a crash and goes back to `pending`.
"""

import json
import logging
import sqlite3
import threading
import time

from . import artist_images, cache, config, db, ingest, jobs, playback, render
from .media import YT_NAME_RE
from .metube import MetubeClient

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


class DownloadFailed(Exception):
    pass


class Worker:
    def __init__(self, settings: config.Settings, metube: MetubeClient | None = None,
                 conn: sqlite3.Connection | None = None):
        self.settings = settings
        self.metube = metube or MetubeClient(settings.metube_url)
        self.conn = conn or db.open_db(settings.db_path, settings.busy_timeout_ms)
        self._next_scan = 0.0
        self._next_gc = 0.0
        self._next_artist_image = 0.0

    def startup(self) -> None:
        with db.transaction(self.conn):
            n = self.conn.execute(
                "UPDATE jobs SET status = 'pending' WHERE status = 'running'").rowcount
        if n:
            log.info("reclaimed %d orphaned job(s)", n)
        self.enqueue_scan()

    def enqueue_scan(self) -> None:
        jobs.enqueue(self.conn, "scan", {}, "scan")
        self._next_scan = time.monotonic() + self.settings.scan_interval_s

    def run_once(self) -> bool:
        """Run one job if there is one. Returns False when the queue was empty."""
        with db.transaction(self.conn):
            job = jobs.claim(self.conn)
            if job is None:
                return False
            payload = json.loads(job["payload"])
            if job["kind"] == "download":
                self.conn.execute("UPDATE songs SET status = 'downloading' WHERE youtube_id = ?",
                                  (payload["youtube_id"],))
        try:
            if job["kind"] == "download":
                self._download(payload["youtube_id"])
            elif job["kind"] == "render":
                self._render(payload)
            elif job["kind"] == "scan":
                ingest.scan(self.conn, self.settings)
            else:
                raise ValueError(f"no handler for job kind {job['kind']!r}")
        except Exception as e:
            self._failed(job, payload, e)
        else:
            self.conn.execute("UPDATE jobs SET status = 'done', error = NULL,"
                              " finished_at = datetime('now') WHERE id = ?", (job["id"],))
        return True

    def run_until_idle(self) -> None:
        while self.run_once():
            pass

    def run_forever(self) -> None:
        self.startup()
        if self.settings.heartbeat_path:
            # A thread, so a long render doesn't look like a dead worker.
            threading.Thread(target=self._beat_forever, daemon=True, name="heartbeat").start()
        while True:
            now = time.monotonic()
            if now >= self._next_scan:
                self.enqueue_scan()
            if now >= self._next_gc:
                self.maybe_gc()
            if not self.run_once() and not self.maybe_playback() and not self.maybe_artist_image():
                time.sleep(self.settings.worker_idle_s)

    def _beat_forever(self) -> None:
        while True:
            self.beat()
            time.sleep(15)

    def beat(self) -> None:
        """Touch the heartbeat file the container healthcheck reads."""
        if self.settings.heartbeat_path:
            try:
                self.settings.heartbeat_path.touch()
            except OSError as e:
                log.warning("heartbeat: %s", e)

    def maybe_gc(self) -> None:
        """Evict renders over SONGBOOK_CACHE_MAX_GB. Runs between jobs, so never mid-render."""
        self._next_gc = time.monotonic() + self.settings.gc_interval_s
        if self.settings.cache_max_gb is None:
            return
        try:
            removed = cache.gc(self.conn, self.settings, int(self.settings.cache_max_gb * 1024 ** 3))
        except Exception:
            log.exception("cache gc failed")
            return
        if removed:
            log.info("cache gc removed %d file(s)", len(removed))

    def maybe_playback(self) -> bool:
        """Make one song's H.264 copy when the queue is idle. True if a song was handled."""
        try:
            return playback.run_next(self.conn, self.settings)
        except Exception:
            log.exception("playback copy failed")
            return False

    def maybe_artist_image(self) -> bool:
        """Look up one artist's picture when the queue is idle. True if it did.

        At most one every 2 s (TheAudioDB's free key allows 30 requests a
        minute); with nothing to look up, check again in 10 s, and if
        TheAudioDB is unreachable, in 10 minutes.
        """
        if not self.settings.audiodb_url or time.monotonic() < self._next_artist_image:
            return False
        try:
            done = artist_images.fetch_one(self.conn, self.settings)
        except Exception as e:
            log.warning("artist picture lookup failed, retrying in 10 min: %s", e)
            self._next_artist_image = time.monotonic() + 600
            return False
        self._next_artist_image = time.monotonic() + (2 if done else 10)
        return done

    def _download(self, yid: str) -> None:
        if self._file_for(yid) is None:
            # If a previous attempt already got the file, don't ask MeTube again.
            self.metube.clear_failure(yid)
            self.metube.add(yid)
        deadline = time.monotonic() + self.settings.download_timeout_s
        while self._file_for(yid) is None:
            msg = self.metube.failure(yid)
            if msg:
                raise DownloadFailed(msg)
            if time.monotonic() >= deadline:
                raise DownloadFailed(f"timed out after {self.settings.download_timeout_s:g}s"
                                     f" waiting for originals/{yid}.*")
            time.sleep(self.settings.download_poll_s)
        res = ingest.scan(self.conn, self.settings, youtube_id=yid)
        if res.skipped:
            raise DownloadFailed("; ".join(res.skipped))

    def _render(self, payload: dict) -> None:
        song_id, key = payload["song_id"], payload["cache_key"]
        song = self.conn.execute("SELECT original_path, kind FROM songs WHERE id = ?", (song_id,)).fetchone()
        if song is None or not song["original_path"]:
            log.info("render %s for song %s skipped: song or original gone", key, song_id)
            return
        if song["kind"] == "tab":
            log.info("render %s for song %s skipped: tab songs are played by alphaTab", key, song_id)
            return
        # A render copies its video stream, so the song's H.264 copy has to exist first.
        playback.ensure(self.conn, self.settings, song_id)
        copy = self.conn.execute("SELECT playback_path FROM songs WHERE id = ?", (song_id,)).fetchone()
        video = self.settings.root / copy["playback_path"] if copy and copy["playback_path"] else None
        out_dir = self.settings.renders_dir / str(song_id)
        final = render.render(render.Job(
            original=self.settings.root / song["original_path"], out_dir=out_dir, key=key,
            semitones=payload["semitones"], tempo=payload["tempo"], bake_tempo=payload["bake_tempo"],
            video=video if video and video.is_file() else None,
        ), timeout=self.settings.render_timeout_s)
        rel = final.relative_to(self.settings.root).as_posix()
        try:
            with db.transaction(self.conn):
                self.conn.execute(
                    "INSERT INTO renders (song_id, cache_key, path, bytes) VALUES (?, ?, ?, ?)"
                    " ON CONFLICT (song_id, cache_key) DO UPDATE SET path = excluded.path,"
                    " bytes = excluded.bytes, created_at = datetime('now')",
                    (song_id, key, rel, final.stat().st_size))
        except sqlite3.IntegrityError:
            final.unlink(missing_ok=True)  # the song was deleted while rendering
            log.info("render %s for song %s dropped: song deleted meanwhile", key, song_id)

    def _file_for(self, yid: str):
        for p in self.settings.originals_dir.glob(f"{yid}.*"):
            if YT_NAME_RE.match(p.name) and p.is_file():
                return p
        return None

    def _failed(self, job: sqlite3.Row, payload: dict, e: Exception) -> None:
        msg = f"{type(e).__name__}: {e}" if not isinstance(e, DownloadFailed) else str(e)
        final = job["attempts"] >= MAX_ATTEMPTS
        log.warning("job %d (%s) attempt %d failed%s: %s", job["id"], job["kind"],
                    job["attempts"], "; giving up" if final else "", msg)
        with db.transaction(self.conn):
            self.conn.execute(
                "UPDATE jobs SET status = :st, error = :msg,"
                " finished_at = CASE WHEN :st = 'error' THEN datetime('now') END WHERE id = :id",
                {"st": "error" if final else "pending", "msg": msg, "id": job["id"]},
            )
            if job["kind"] == "download":
                self.conn.execute(
                    "UPDATE songs SET status = ?, error = ? WHERE youtube_id = ?",
                    ("error" if final else "queued", msg if final else None, payload["youtube_id"]),
                )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = config.load()
    config.ensure_dirs(settings)
    Worker(settings).run_forever()


if __name__ == "__main__":
    main()
