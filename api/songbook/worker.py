"""The single background worker: `python -m songbook.worker`.

There is exactly one worker, so on startup anything still `running` was
orphaned by a crash and goes back to `pending`.
"""

import json
import logging
import sqlite3
import time

from . import config, db, ingest, jobs
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
        while True:
            if time.monotonic() >= self._next_scan:
                self.enqueue_scan()
            if not self.run_once():
                time.sleep(self.settings.worker_idle_s)

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
