"""Media streaming with HTTP Range (FileResponse handles Range and If-Range).

Paths come from the DB only. The URL carries a numeric id, never a path.
"""

import mimetypes
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import config
from ..deps import get_conn, get_settings

router = APIRouter(prefix="/media")

_TYPES = {".webm": "video/webm", ".mp4": "video/mp4", ".mkv": "video/x-matroska",
          ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}


def _file(settings: config.Settings, base: Path, rel: str | None, headers: dict | None = None) -> FileResponse:
    if not rel:
        raise HTTPException(404)
    try:
        path = (settings.root / rel).resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(404)
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise HTTPException(404)
    media_type = _TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers=headers)


def _id(raw: str) -> int:
    if not raw.isdigit() or len(raw) > 18:
        raise HTTPException(404)
    return int(raw)


@router.get("/originals/{song_id}")
def original(song_id: str, conn: sqlite3.Connection = Depends(get_conn),
             settings: config.Settings = Depends(get_settings)) -> FileResponse:
    row = conn.execute("SELECT original_path FROM songs WHERE id = ?", (_id(song_id),)).fetchone()
    return _file(settings, settings.originals_dir, row and row[0])


@router.get("/renders/{render_id}")
def render(render_id: str, conn: sqlite3.Connection = Depends(get_conn),
           settings: config.Settings = Depends(get_settings)) -> FileResponse:
    rid = _id(render_id)
    row = conn.execute("SELECT path FROM renders WHERE id = ?", (rid,)).fetchone()
    resp = _file(settings, settings.renders_dir, row and row[0])
    conn.execute("UPDATE renders SET last_used_at = datetime('now') WHERE id = ?", (rid,))
    return resp


@router.get("/artists/{artist_id}")
def artist_image(artist_id: str, conn: sqlite3.Connection = Depends(get_conn),
                 settings: config.Settings = Depends(get_settings)) -> FileResponse:
    row = conn.execute("SELECT image_path FROM artists WHERE id = ?", (_id(artist_id),)).fetchone()
    # The URL carries ?v=<when it was fetched>, so a new picture gets a new URL.
    return _file(settings, settings.artist_images_dir, row and row[0],
                 headers={"Cache-Control": "private, max-age=2592000, immutable"})
