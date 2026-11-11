"""Artist pictures from TheAudioDB, fetched once by the worker and kept on disk.

Every artist is looked up once, so new artists and ones that existed before
this feature (the backfill) are treated the same. The small thumbnail is saved
as artist-images/<id>.<ext> and served by the api. An artist TheAudioDB doesn't
know is tried again after RETRY_MISS_DAYS. When TheAudioDB is unreachable,
nothing is recorded and the worker backs off.
"""

import logging
import os
import sqlite3

import httpx

from . import config, db
from .guess import _squash

log = logging.getLogger(__name__)

RETRY_MISS_DAYS = 30
MAX_BYTES = 2 * 1024 * 1024
_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class Unreachable(Exception):
    """TheAudioDB is down, rate-limiting or answering nonsense: try again later, record nothing."""


def pending(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """The next artist to look up: never-looked-up ones first, then stale misses."""
    return conn.execute(
        "SELECT id, name FROM artists WHERE image_path IS NULL AND (image_checked_at IS NULL"
        f" OR image_checked_at < datetime('now', '-{RETRY_MISS_DAYS} days'))"
        " ORDER BY image_checked_at IS NOT NULL, image_checked_at, id LIMIT 1").fetchone()


def lookup(endpoint: str, name: str) -> str | None:
    """The artist's thumbnail URL, or None when TheAudioDB has no artist by that name."""
    try:
        r = httpx.get(f"{endpoint}/search.php", params={"s": name}, timeout=10.0, follow_redirects=True)
        if r.status_code == 429 or r.status_code >= 500:
            raise Unreachable(f"search answered HTTP {r.status_code}")
        r.raise_for_status()
        artists = r.json().get("artists") or []
    except (httpx.TransportError, ValueError, AttributeError) as e:
        raise Unreachable(f"search failed: {e}") from e
    # Search is fuzzy; only take an artist whose name (or alternate name) is this one.
    want = _squash(name)
    for a in artists:
        names = [a.get("strArtist") or "", *(a.get("strArtistAlternate") or "").split(",")]
        if a.get("strArtistThumb") and any(_squash(n) == want for n in names if n.strip()):
            return a["strArtistThumb"]
    return None


def download(url: str) -> tuple[bytes, str]:
    """(bytes, extension) of the small version of a TheAudioDB image, else the full one."""
    try:
        r = httpx.get(f"{url}/small", timeout=20.0, follow_redirects=True)
        if r.status_code == 404:
            r = httpx.get(url, timeout=20.0, follow_redirects=True)
    except httpx.TransportError as e:
        raise Unreachable(f"image download failed: {e}") from e
    if r.status_code == 429 or r.status_code >= 500:
        raise Unreachable(f"image answered HTTP {r.status_code}")
    r.raise_for_status()
    ext = _EXT.get(r.headers.get("content-type", "").split(";")[0].strip().lower())
    if ext is None:
        raise ValueError(f"not an image: {r.headers.get('content-type')!r}")
    if len(r.content) > MAX_BYTES:
        raise ValueError(f"image too big: {len(r.content)} bytes")
    return r.content, ext


def fetch_one(conn: sqlite3.Connection, settings: config.Settings) -> bool:
    """Look up the next pending artist. False when there was none.

    Raises Unreachable when TheAudioDB couldn't be asked; anything else
    (no match, a broken image) is recorded as a miss.
    """
    row = pending(conn)
    if row is None:
        return False
    artist_id, name = row["id"], row["name"]
    path = None
    try:
        url = lookup(settings.audiodb_url, name)
        if url:
            data, ext = download(url)
            path = settings.artist_images_dir / f"{artist_id}{ext}"
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
    except Unreachable:
        raise
    except (httpx.HTTPError, ValueError, OSError) as e:
        log.info("no picture for artist %r: %s", name, e)
        path = None
    rel = path.relative_to(settings.root).as_posix() if path else None
    with db.transaction(conn):
        # Only if the artist is still there under the same name (not renamed or deleted meanwhile).
        n = conn.execute("UPDATE artists SET image_path = ?, image_checked_at = datetime('now')"
                         " WHERE id = ? AND name = ?", (rel, artist_id, name)).rowcount
    if path and n == 0:
        path.unlink(missing_ok=True)
    elif n:
        log.info("artist %r: %s", name, f"picture saved as {rel}" if rel else "no picture on TheAudioDB")
    return True


def clear(conn: sqlite3.Connection, settings: config.Settings, artist_id: int) -> None:
    """Forget an artist's picture (on rename), so it's looked up again."""
    row = conn.execute("SELECT image_path FROM artists WHERE id = ?", (artist_id,)).fetchone()
    conn.execute("UPDATE artists SET image_path = NULL, image_checked_at = NULL WHERE id = ?", (artist_id,))
    remove_file(settings, row and row["image_path"])


def remove_file(settings: config.Settings, rel: str | None) -> None:
    if rel:
        path = (settings.root / rel).resolve()
        if path.is_relative_to(settings.artist_images_dir.resolve()):
            path.unlink(missing_ok=True)


def main() -> None:
    """Look up every pending artist now: `python -m tunealong.artist_images`. The worker does this anyway."""
    import time

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = config.load()
    if not settings.audiodb_url:
        raise SystemExit("TUNEALONG_AUDIODB_URL is empty: artist pictures are off")
    config.ensure_dirs(settings)
    conn = db.open_db(settings.db_path, settings.busy_timeout_ms)
    while fetch_one(conn, settings):
        time.sleep(2)  # the free key allows 30 requests a minute


if __name__ == "__main__":
    main()
