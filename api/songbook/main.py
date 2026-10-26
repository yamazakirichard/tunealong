"""FastAPI app. Run with `uvicorn --factory songbook.main:create_app`, so
nothing touches the filesystem at import time."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from . import config, db


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

    @app.get("/api/health")
    def health(request: Request) -> dict:
        request.app.state.db.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    return app
