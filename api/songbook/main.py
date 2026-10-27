"""FastAPI app. Run with `uvicorn --factory songbook.main:create_app`, so
nothing touches the filesystem at import time."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.applications import Starlette
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route

from . import config, db
from .auth import BasicAuth
from .routes import groups, library, media, presets, songs, youtube


def create_app(settings: config.Settings | None = None):
    settings = settings or config.load()
    app = _build(settings)
    outer = app
    if settings.base_path:
        # SONGBOOK_BASE_PATH is read at runtime: the same image (and the same
        # relative-URL UI build) serves at / or under a subpath.
        base = settings.base_path

        async def to_base(request):
            return RedirectResponse(f"{base}/", status_code=308)

        outer = Starlette(
            routes=[Route(base, to_base), Mount(base, app=app)],
            lifespan=lambda _: app.router.lifespan_context(app),  # mounted apps don't get lifespan events
        )
        outer.state.settings = settings
    if settings.auth_enabled:
        return BasicAuth(outer, settings.auth_user, settings.auth_password_hash,
                         open_paths=(f"{settings.base_path}/api/health",))
    return outer


def _build(settings: config.Settings) -> FastAPI:
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

    for module in (songs, presets, groups, library, media, youtube):
        app.include_router(module.router)

    # The built UI (web/dist), served last so the API routes win. The UI uses
    # only relative URLs, so it works at / or under any subpath.
    if settings.web_dir and (settings.web_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")

    return app
