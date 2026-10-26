"""FastAPI app. Run with `uvicorn --factory songbook.main:create_app`, so
nothing touches the filesystem at import time."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from . import config, db
from .routes import groups, library, media, presets, songs


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

    for module in (songs, presets, groups, library, media):
        app.include_router(module.router)

    # The built UI (web/dist), served last so the API routes win. The UI uses
    # only relative URLs, so it works at / or under any subpath.
    if settings.web_dir and (settings.web_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")

    return app
