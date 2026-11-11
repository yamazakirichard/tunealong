"""Artists and categories (the user's groupings), and manual reordering."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import artist_images, config, db
from ..deps import get_conn, get_settings
from ..guess import _squash
from ..models import ArtistIn, ArtistPatch, CategoryIn, CategoryPatch, Reorder

router = APIRouter(prefix="/api")

_ORDER = "sort_order IS NULL, sort_order, name COLLATE NOCASE"


def _create(conn, table: str, values: dict) -> dict:
    try:
        new_id = conn.execute(
            f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
            tuple(values.values())).lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"{values['name']!r} already exists")
    return dict(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (new_id,)).fetchone())


def _patch(conn, table: str, row_id: int, values: dict) -> dict:
    if not conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row_id,)).fetchone():
        raise HTTPException(404, "not found")
    if values:
        try:
            conn.execute(f"UPDATE {table} SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                         (*values.values(), row_id))
        except sqlite3.IntegrityError as e:
            raise HTTPException(409 if "UNIQUE" in str(e) else 422, str(e))
    return dict(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone())


def _delete(conn, table: str, row_id: int) -> Response:
    if conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,)).rowcount == 0:
        raise HTTPException(404, "not found")
    return Response(status_code=204)


def _not_null(body, *fields):
    for f in fields:
        if f in body.model_fields_set and getattr(body, f) is None:
            raise HTTPException(422, f"{f} can't be null")


@router.get("/artists")
def list_artists(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    return [dict(r) for r in conn.execute(f"SELECT * FROM artists ORDER BY {_ORDER}")]


@router.post("/artists", status_code=201)
def create_artist(body: ArtistIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return _create(conn, "artists", body.model_dump())


@router.patch("/artists/{artist_id}")
def patch_artist(artist_id: int, body: ArtistPatch, conn: sqlite3.Connection = Depends(get_conn),
                 settings: config.Settings = Depends(get_settings)) -> dict:
    _not_null(body, "name", "columns", "style")
    old = conn.execute("SELECT name FROM artists WHERE id = ?", (artist_id,)).fetchone()
    out = _patch(conn, "artists", artist_id, body.model_dump(exclude_unset=True))
    if old and _squash(old["name"]) != _squash(out["name"]):
        artist_images.clear(conn, settings, artist_id)  # a different artist now: the worker looks it up again
        out = dict(conn.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone())
    return out


@router.delete("/artists/{artist_id}", status_code=204)
def delete_artist(artist_id: int, conn: sqlite3.Connection = Depends(get_conn),
                  settings: config.Settings = Depends(get_settings)) -> Response:
    row = conn.execute("SELECT image_path FROM artists WHERE id = ?", (artist_id,)).fetchone()
    resp = _delete(conn, "artists", artist_id)  # its songs go to Unsorted (ON DELETE SET NULL)
    artist_images.remove_file(settings, row and row["image_path"])
    return resp


@router.get("/categories")
def list_categories(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    return [dict(r) for r in conn.execute(f"SELECT * FROM categories ORDER BY {_ORDER}")]


@router.post("/categories", status_code=201)
def create_category(body: CategoryIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return _create(conn, "categories", body.model_dump())


@router.patch("/categories/{category_id}")
def patch_category(category_id: int, body: CategoryPatch, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    _not_null(body, "name")
    return _patch(conn, "categories", category_id, body.model_dump(exclude_unset=True))


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(category_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    return _delete(conn, "categories", category_id)  # songs stay; only the links go


@router.post("/reorder")
def reorder(body: Reorder, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """Set sort_order = position in `ids`. Every id must exist and belong to the group."""
    ids = body.ids
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "duplicate ids")
    table = "songs" if body.scope == "songs" else body.scope
    with db.transaction(conn):
        marks = ",".join("?" * len(ids))
        if body.scope == "songs":
            rows = conn.execute(f"SELECT id, artist_id FROM songs WHERE id IN ({marks})", ids).fetchall()
            found = {r["id"] for r in rows if r["artist_id"] == body.group_id}
        else:
            if body.group_id is not None:
                raise HTTPException(422, "group_id only applies to scope 'songs'")
            found = {r[0] for r in conn.execute(f"SELECT id FROM {table} WHERE id IN ({marks})", ids)}
        if bad := [i for i in ids if i not in found]:
            raise HTTPException(422, f"ids not in this group: {bad}")
        conn.executemany(f"UPDATE {table} SET sort_order = ? WHERE id = ?",
                         [(pos, i) for pos, i in enumerate(ids)])
    return {"scope": body.scope, "group_id": body.group_id, "ids": ids}
