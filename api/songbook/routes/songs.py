"""Songs: add by URL or tab file, read, edit, delete, link to YouTube, categories, playback."""

import hashlib
import os
import shutil
import sqlite3
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse

from .. import artists, cache, config, db, jobs, library
from ..deps import get_conn, get_settings
from ..media import TAB_EXTS
from ..models import LinkIn, SongAdd, SongPatch
from ..youtube import parse_id

router = APIRouter(prefix="/api")


def _song_or_404(conn: sqlite3.Connection, song_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "song not found")
    return row


def _parse(url: str) -> str:
    try:
        return parse_id(url)
    except ValueError as e:
        raise HTTPException(422, str(e))


def _unignore(conn: sqlite3.Connection, yid: str) -> None:
    # The ID charset has no GLOB metacharacters.
    conn.execute("DELETE FROM ignored_paths WHERE path GLOB ?", (f"originals/{yid}.*",))


@router.post("/songs", status_code=201)
def add_song(body: SongAdd, response: Response, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    yid = _parse(body.url)
    with db.transaction(conn):
        row = conn.execute("SELECT * FROM songs WHERE youtube_id = ?", (yid,)).fetchone()
        if row is not None and row["status"] == "ready":
            response.status_code = 200
            return {"song": library.song_dict(row), "duplicate": True}
        if row is not None and row["status"] in ("queued", "downloading"):
            response.status_code = 202
            return {"song": library.song_dict(row), "duplicate": False}
        if row is not None:  # error: try again
            conn.execute("UPDATE songs SET status = 'queued', error = NULL WHERE id = ?", (row["id"],))
            response.status_code = 202
            song_id = row["id"]
        else:
            artist_id = artists.get_or_create(conn, body.artist) if body.artist else None
            song_id = conn.execute(
                "INSERT INTO songs (youtube_id, artist_id, title, status) VALUES (?, ?, ?, 'queued')",
                (yid, artist_id, body.title or yid),
            ).lastrowid
        _unignore(conn, yid)
        jobs.enqueue(conn, "download", {"youtube_id": yid}, f"dl:{yid}")
        row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    return {"song": library.song_dict(row), "duplicate": False}


def _form_text(value: str | None, max_len: int) -> str | None:
    value = (value or "").strip()
    if len(value) > max_len:
        raise HTTPException(422, f"longer than {max_len} characters")
    return value or None


@router.post("/songs/tab", status_code=201)
async def add_tab(file: UploadFile = File(...), artist: str | None = Form(None), title: str | None = Form(None),
                  conn: sqlite3.Connection = Depends(get_conn),
                  settings: config.Settings = Depends(get_settings)):
    """Upload a Guitar Pro / MusicXML file as a tab song. The same bytes twice is a 409."""
    name = os.path.basename(file.filename or "")
    stem, _, ext = name.rpartition(".")
    ext = ext.lower()
    if not stem or ext not in TAB_EXTS:
        raise HTTPException(415, f"not a tab file; expected one of: {', '.join(TAB_EXTS)}")
    artist, title = _form_text(artist, 200), _form_text(title, 500) or stem
    limit = int(settings.tab_max_mb * 1024 * 1024)
    settings.tabs_dir.mkdir(parents=True, exist_ok=True)
    h, size = hashlib.sha256(), 0
    fd, tmp_name = tempfile.mkstemp(prefix=".upload-", dir=settings.tabs_dir)
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"tab file is larger than {settings.tab_max_mb:g} MB")
                h.update(chunk)
                out.write(chunk)
        if size == 0:
            raise HTTPException(422, "the file is empty")
        sha = h.hexdigest()
        dest = settings.tabs_dir / f"{sha[:16]}.{ext}"
        rel = dest.relative_to(settings.root).as_posix()
        with db.transaction(conn):
            other = conn.execute("SELECT * FROM songs WHERE original_sha256 = ?", (sha,)).fetchone()
            if other is not None:
                return JSONResponse(status_code=409, content={
                    "detail": "this file is already in the library", "song": library.song_dict(other)})
            os.replace(tmp_name, dest)
            tmp_name = None
            # A file kept on disk after its song was deleted: uploading it again brings it back.
            conn.execute("DELETE FROM ignored_paths WHERE path = ?", (rel,))
            artist_id = artists.get_or_create(conn, artist) if artist else None
            song_id = conn.execute(
                "INSERT INTO songs (youtube_id, artist_id, title, original_path, original_sha256, status, kind)"
                " VALUES (NULL, ?, ?, ?, ?, 'ready', 'tab')",
                (artist_id, title, rel, sha),
            ).lastrowid
            row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    finally:
        if tmp_name:
            os.unlink(tmp_name)
    return {"song": library.song_dict(row), "duplicate": False}


@router.get("/songs/{song_id}")
def get_song(song_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    song = library.full_song(conn, song_id)
    if song is None:
        raise HTTPException(404, "song not found")
    return song


@router.patch("/songs/{song_id}")
def patch_song(song_id: int, body: SongPatch, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    fields = body.model_fields_set
    with db.transaction(conn):
        row = _song_or_404(conn, song_id)
        sets: dict = {}
        if "artist_id" in fields:
            if body.artist_id is not None and not conn.execute(
                    "SELECT 1 FROM artists WHERE id = ?", (body.artist_id,)).fetchone():
                raise HTTPException(422, "unknown artist_id")
            sets["artist_id"] = body.artist_id
        if "artist_name" in fields:
            sets["artist_id"] = artists.get_or_create(conn, body.artist_name) if body.artist_name else None
        if "artist_id" in sets and sets["artist_id"] != row["artist_id"]:
            sets["sort_order"] = None  # a manual position belongs to the old group
        if "title" in fields:
            sets["title"] = body.title
        if "notes" in fields:
            sets["notes"] = body.notes
        if "tab_track" in fields:
            if row["kind"] != "tab":
                raise HTTPException(422, "tab_track is only for tab songs")
            sets["tab_track"] = body.tab_track
        if sets:
            conn.execute(f"UPDATE songs SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                         (*sets.values(), song_id))
    return library.full_song(conn, song_id)


@router.delete("/songs/{song_id}", status_code=204)
def delete_song(song_id: int, delete_file: bool = False, conn: sqlite3.Connection = Depends(get_conn),
                settings: config.Settings = Depends(get_settings)) -> Response:
    with db.transaction(conn):
        row = _song_or_404(conn, song_id)
        conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))  # cascades presets, renders, categories
        if row["youtube_id"]:
            conn.execute("UPDATE jobs SET status = 'error', error = 'cancelled: song deleted',"
                         " finished_at = datetime('now')"
                         " WHERE dedupe_key = ? AND status = 'pending'", (f"dl:{row['youtube_id']}",))
        original = _inside(settings.originals_dir, settings.root / row["original_path"]) \
            if row["original_path"] else None
        if original and not delete_file:
            # Keep the file, but stop the next scan from re-adding it.
            conn.execute("INSERT OR IGNORE INTO ignored_paths (path) VALUES (?)", (row["original_path"],))
    shutil.rmtree(settings.renders_dir / str(song_id), ignore_errors=True)
    if original and delete_file:
        original.unlink(missing_ok=True)
    return Response(status_code=204)


@router.post("/songs/{song_id}/link")
def link_song(song_id: int, body: LinkIn, conn: sqlite3.Connection = Depends(get_conn)):
    yid = _parse(body.url)
    with db.transaction(conn):
        row = _song_or_404(conn, song_id)
        if row["kind"] == "tab":
            raise HTTPException(422, "a tab song can't be linked to a YouTube video")
        if row["youtube_id"] == yid:
            return library.full_song(conn, song_id)
        other = conn.execute("SELECT * FROM songs WHERE youtube_id = ?", (yid,)).fetchone()
        if other is not None:
            return JSONResponse(status_code=409, content={
                "detail": "another song already has this YouTube ID", "song": library.song_dict(other)})
        if row["youtube_id"]:
            raise HTTPException(422, "song is already linked to a different YouTube ID")
        conn.execute("UPDATE songs SET youtube_id = ? WHERE id = ?", (yid, song_id))
    return library.full_song(conn, song_id)


@router.put("/songs/{song_id}/categories")
def set_categories(song_id: int, ids: list[int], conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    ids = list(dict.fromkeys(ids))
    with db.transaction(conn):
        _song_or_404(conn, song_id)
        known = {r[0] for r in conn.execute(
            f"SELECT id FROM categories WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else set()
        if unknown := [i for i in ids if i not in known]:
            raise HTTPException(422, f"unknown category ids: {unknown}")
        conn.execute("DELETE FROM song_categories WHERE song_id = ?", (song_id,))
        conn.executemany("INSERT INTO song_categories (song_id, category_id) VALUES (?, ?)",
                         [(song_id, i) for i in ids])
    return library.full_song(conn, song_id)


@router.get("/songs/{song_id}/playback")
def song_playback(song_id: int, conn: sqlite3.Connection = Depends(get_conn),
                  settings: config.Settings = Depends(get_settings)) -> dict:
    """What to play when the song opens: its default preset, else the original as-is."""
    row = _song_or_404(conn, song_id)
    if row["status"] != "ready" or not row["original_path"]:
        raise HTTPException(409, f"song is {row['status']}, not ready")
    p = conn.execute("SELECT * FROM presets WHERE song_id = ? AND is_default = 1", (song_id,)).fetchone()
    with db.transaction(conn):
        return cache.playback(conn, settings, song_id, p)


def _inside(base, path):
    """`path` resolved, if it really is inside `base`; else None."""
    try:
        resolved = path.resolve()
        return resolved if resolved.is_relative_to(base.resolve()) else None
    except (OSError, ValueError):
        return None
