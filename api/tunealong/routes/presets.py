"""Presets: named pitch/tempo/loop/volume settings per song."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError

from .. import cache, config, db, library
from ..deps import get_conn, get_settings
from ..models import PresetIn, PresetPatch

router = APIRouter(prefix="/api")


def _write(conn: sqlite3.Connection, song_id: int, p: PresetIn, preset_id: int | None = None) -> int:
    """Insert or update in the caller's transaction. Snaps values and writes cache_key."""
    semitones, tempo = cache.snap(p.semitones) + 0.0, cache.snap(p.tempo)
    values = {
        "name": p.name, "semitones": semitones, "tempo": tempo, "bake_tempo": int(p.bake_tempo),
        "loop_a": p.loop_a, "loop_b": p.loop_b, "is_default": int(p.is_default), "volume": p.volume,
        "cache_key": cache.cache_key(semitones, tempo, p.bake_tempo),
    }
    if p.is_default:
        conn.execute("UPDATE presets SET is_default = 0 WHERE song_id = ? AND is_default = 1"
                     + (" AND id != ?" if preset_id else ""), (song_id, preset_id) if preset_id else (song_id,))
    try:
        if preset_id is None:
            return conn.execute(
                f"INSERT INTO presets (song_id, {', '.join(values)}) VALUES (?{', ?' * len(values)})",
                (song_id, *values.values())).lastrowid
        conn.execute(f"UPDATE presets SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                     (*values.values(), preset_id))
        return preset_id
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e) and "name" in str(e):
            raise HTTPException(409, f"this song already has a preset named {p.name!r}")
        raise HTTPException(422, str(e))


def _get(conn: sqlite3.Connection, preset_id: int) -> dict:
    return library.preset_dict(conn.execute("SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone())


@router.get("/songs/{song_id}/presets")
def list_presets(song_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    if not conn.execute("SELECT 1 FROM songs WHERE id = ?", (song_id,)).fetchone():
        raise HTTPException(404, "song not found")
    return [library.preset_dict(r) for r in conn.execute(
        "SELECT * FROM presets WHERE song_id = ? ORDER BY name COLLATE NOCASE", (song_id,))]


def _saved(conn, settings, preset_id: int) -> dict:
    """After a save: make sure a shifted preset's render is cached or on its way."""
    p = _get(conn, preset_id)
    cache.ensure_render(conn, settings, p["song_id"], p["semitones"], p["tempo"], p["bake_tempo"])
    return p


@router.post("/songs/{song_id}/presets", status_code=201)
def create_preset(song_id: int, body: PresetIn, conn: sqlite3.Connection = Depends(get_conn),
                  settings: config.Settings = Depends(get_settings)) -> dict:
    with db.transaction(conn):
        if not conn.execute("SELECT 1 FROM songs WHERE id = ?", (song_id,)).fetchone():
            raise HTTPException(404, "song not found")
        preset_id = _write(conn, song_id, body)
        return _saved(conn, settings, preset_id)


@router.patch("/presets/{preset_id}")
def patch_preset(preset_id: int, body: PresetPatch, conn: sqlite3.Connection = Depends(get_conn),
                 settings: config.Settings = Depends(get_settings)) -> dict:
    with db.transaction(conn):
        row = conn.execute("SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "preset not found")
        merged = library.preset_dict(row) | body.model_dump(exclude_unset=True)
        try:
            p = PresetIn(**{k: merged[k] for k in PresetIn.model_fields})
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False, include_context=False))
        _write(conn, row["song_id"], p, preset_id)
        return _saved(conn, settings, preset_id)


@router.delete("/presets/{preset_id}", status_code=204)
def delete_preset(preset_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    if conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,)).rowcount == 0:
        raise HTTPException(404, "preset not found")
    return Response(status_code=204)


@router.get("/presets/{preset_id}/playback")
def preset_playback(preset_id: int, conn: sqlite3.Connection = Depends(get_conn),
                    settings: config.Settings = Depends(get_settings)) -> dict:
    row = conn.execute("SELECT p.*, s.status AS song_status FROM presets p JOIN songs s ON s.id = p.song_id"
                       " WHERE p.id = ?", (preset_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "preset not found")
    if row["song_status"] != "ready":
        raise HTTPException(409, f"song is {row['song_status']}, not ready")
    with db.transaction(conn):
        return cache.playback(conn, settings, row["song_id"], row)
