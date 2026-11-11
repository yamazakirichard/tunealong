"""The library view, rescans and the job list."""

import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Query

from .. import jobs, library
from ..deps import get_conn

router = APIRouter(prefix="/api")


@router.get("/library")
def get_library(group_by: Literal["artist", "category"] = "artist", category: int | None = None,
                q: str | None = Query(default=None, max_length=200),
                conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return library.build(conn, group_by, category, (q or "").strip() or None)


@router.post("/library/rescan", status_code=202)
def rescan(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return {"queued": jobs.enqueue(conn, "scan", {}, "scan") is not None}


@router.get("/jobs")
def list_jobs(status: Literal["pending", "running", "done", "error"] | None = None,
              limit: int = Query(default=100, ge=1, le=1000),
              conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM jobs" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC LIMIT ?",
        (status, limit) if status else (limit,))
    return [dict(r) | {"payload": json.loads(r["payload"])} for r in rows]
