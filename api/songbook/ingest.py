"""Scan originals/ and bring the songs table in line with the files on disk.

Never assigns an artist or category, and never overwrites a song's title once
it exists: new songs land in Unsorted with a title the user can change.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import db
from .config import Settings
from .media import LOCAL_NAME_RE, YT_NAME_RE, sha256_file

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)  # "<file>: <reason>"


def scan(conn: sqlite3.Connection, settings: Settings, youtube_id: str | None = None) -> ScanResult:
    """Idempotent. With `youtube_id`, only that ID's file in originals/ is scanned."""
    res = ScanResult()
    # Files whose song the user deleted but kept on disk.
    ignored = {r[0] for r in conn.execute("SELECT path FROM ignored_paths")}
    for path in sorted(settings.originals_dir.iterdir()):
        m = YT_NAME_RE.match(path.name)
        if not m or not path.is_file() or (youtube_id and m.group(1) != youtube_id):
            continue
        if _rel(settings, path) not in ignored:
            _scan_youtube(conn, settings, path, m.group(1), res)
    if youtube_id is None and settings.local_dir.is_dir():
        for path in sorted(settings.local_dir.iterdir()):
            if LOCAL_NAME_RE.match(path.name) and path.is_file() and _rel(settings, path) not in ignored:
                _scan_local(conn, settings, path, res)
    return res


def _rel(settings: Settings, path: Path) -> str:
    return path.relative_to(settings.root).as_posix()


def _info(path: Path) -> tuple[str | None, str | None]:
    """(yt_title, uploader) from <id>.info.json next to the media, if any."""
    info_path = path.with_name(path.name.split(".")[0] + ".info.json")
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if not isinstance(info, dict):
        return None, None
    return info.get("title"), info.get("uploader") or info.get("channel")


def _scan_youtube(conn, settings, path, yid, res: ScanResult) -> None:
    rel = _rel(settings, path)
    yt_title, uploader = _info(path)
    row = conn.execute(
        "SELECT id, status, original_path FROM songs WHERE youtube_id = ?", (yid,)
    ).fetchone()
    try:
        with db.transaction(conn):
            if row is None:
                conn.execute(
                    "INSERT INTO songs (youtube_id, title, yt_title, uploader, original_path,"
                    " original_sha256, status) VALUES (?, ?, ?, ?, ?, ?, 'ready')",
                    (yid, yt_title or yid, yt_title, uploader, rel, sha256_file(path)),
                )
                res.created += 1
                return
            if yt_title or uploader:
                # Reference fields only. The title is replaced only while it is
                # still the placeholder ID given to a song added by URL.
                conn.execute(
                    "UPDATE songs SET yt_title = coalesce(?, yt_title),"
                    " uploader = coalesce(?, uploader),"
                    " title = CASE WHEN title = youtube_id THEN coalesce(?, title) ELSE title END"
                    " WHERE id = ?",
                    (yt_title, uploader, yt_title, row["id"]),
                )
            if row["status"] != "ready" or row["original_path"] != rel:
                conn.execute(
                    "UPDATE songs SET original_path = ?, original_sha256 = ?,"
                    " status = 'ready', error = NULL WHERE id = ?",
                    (rel, sha256_file(path), row["id"]),
                )
                res.updated += 1
            else:
                res.unchanged += 1
    except sqlite3.IntegrityError as e:
        # Same bytes already belong to another song (original_sha256 is UNIQUE).
        log.warning("scan: skipped %s: %s", rel, e)
        res.skipped.append(f"{rel}: {e}")


def _scan_local(conn, settings, path, res: ScanResult) -> None:
    rel = _rel(settings, path)
    if conn.execute("SELECT 1 FROM songs WHERE original_path = ?", (rel,)).fetchone():
        res.unchanged += 1
        return
    try:
        with db.transaction(conn):
            conn.execute(
                "INSERT INTO songs (youtube_id, title, original_path, original_sha256, status)"
                " VALUES (NULL, ?, ?, ?, 'ready')",
                (path.stem, rel, sha256_file(path)),
            )
        res.created += 1
    except sqlite3.IntegrityError as e:
        log.warning("scan: skipped %s: %s", rel, e)
        res.skipped.append(f"{rel}: {e}")
