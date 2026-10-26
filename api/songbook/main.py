"""FastAPI app. Run with `uvicorn --factory songbook.main:create_app`, so
nothing touches the filesystem at import time."""

import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response

from . import artists, config, db, jobs
from .models import Song, SongAdd, SongAdded
from .youtube import parse_id


def create_app(settings: config.Settings | None = None) -> FastAPI:
    settings = settings or config.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config.ensure_dirs(settings)
        app.state.db = db.open_db(settings.db_path, settings.busy_timeout_ms)
        try:
            yield
        finally:
            app.state.db.close()

    app = FastAPI(title="Songbook", lifespan=lifespan)
    app.state.settings = settings

    def get_conn():
        # One connection per request: sync endpoints run in a thread pool, and
        # transactions on a shared connection would interleave.
        conn = db.connect(settings.db_path, settings.busy_timeout_ms)
        try:
            yield conn
        finally:
            conn.close()

    @app.get("/api/health")
    def health(request: Request) -> dict:
        request.app.state.db.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.post("/api/songs", response_model=SongAdded, status_code=201)
    def add_song(body: SongAdd, response: Response, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            yid = parse_id(body.url)
        except ValueError as e:
            raise HTTPException(422, str(e))
        with db.transaction(conn):
            row = conn.execute("SELECT * FROM songs WHERE youtube_id = ?", (yid,)).fetchone()
            if row is not None and row["status"] == "ready":
                response.status_code = 200
                return SongAdded(song=Song(**row), duplicate=True)
            if row is not None and row["status"] in ("queued", "downloading"):
                response.status_code = 202
                return SongAdded(song=Song(**row))
            if row is not None:  # error: try again
                conn.execute("UPDATE songs SET status = 'queued', error = NULL WHERE id = ?", (row["id"],))
                response.status_code = 202
                song_id = row["id"]
            else:
                artist_id = artists.get_or_create(conn, body.artist.strip()) if body.artist and body.artist.strip() else None
                title = (body.title or "").strip() or yid
                song_id = conn.execute(
                    "INSERT INTO songs (youtube_id, artist_id, title, status) VALUES (?, ?, ?, 'queued')",
                    (yid, artist_id, title),
                ).lastrowid
            jobs.enqueue(conn, "download", {"youtube_id": yid}, f"dl:{yid}")
            row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
        return SongAdded(song=Song(**row))

    @app.post("/api/library/rescan", status_code=202)
    def rescan(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        job_id = jobs.enqueue(conn, "scan", {}, "scan")
        return {"queued": job_id is not None}

    return app
