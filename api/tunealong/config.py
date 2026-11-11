"""Settings, read from environment variables only."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# The app was called Songbook until 2026-11-11; its database was songbook.sqlite.
LEGACY_DB_NAME = "songbook.sqlite"


@dataclass(frozen=True)
class Settings:
    root: Path
    busy_timeout_ms: int = 5000
    metube_url: str = "http://metube:8081"
    oembed_url: str = "https://www.youtube.com/oembed"  # "" turns the Add song title guess off
    audiodb_url: str = "https://www.theaudiodb.com/api/v1/json/123"  # "" turns artist pictures off
    download_timeout_s: float = 900.0
    download_poll_s: float = 2.0
    scan_interval_s: float = 300.0
    worker_idle_s: float = 1.0
    render_timeout_s: float = 3600.0
    playback_timeout_s: float = 14400.0  # an H.264 copy of a long 4K video is slow
    web_dir: Path | None = None
    base_path: str = ""                 # "" or "/tunealong" (no trailing slash)
    auth_user: str | None = None
    auth_password_hash: str | None = None  # bcrypt
    cache_max_gb: float | None = None
    gc_interval_s: float = 3600.0
    heartbeat_path: Path | None = None  # the worker touches this; its healthcheck reads it
    tab_max_mb: float = 10.0            # largest tab file accepted by upload
    recording_max_mb: float = 1024.0    # largest tab recording accepted by upload

    @property
    def auth_enabled(self) -> bool:
        return bool(self.auth_user and self.auth_password_hash)

    @property
    def db_path(self) -> Path:
        return self.root / "tunealong.sqlite"

    @property
    def originals_dir(self) -> Path:
        return self.root / "originals"

    @property
    def local_dir(self) -> Path:
        return self.originals_dir / "local"

    @property
    def tabs_dir(self) -> Path:
        return self.originals_dir / "tabs"

    @property
    def renders_dir(self) -> Path:
        return self.root / "renders"

    @property
    def playback_dir(self) -> Path:
        return self.root / "playback"

    @property
    def artist_images_dir(self) -> Path:
        return self.root / "artist-images"


def load() -> Settings:
    return Settings(
        root=Path(os.environ.get("TUNEALONG_ROOT", "/srv/tunealong")).resolve(),
        busy_timeout_ms=int(os.environ.get("TUNEALONG_DB_BUSY_TIMEOUT_MS", "5000")),
        metube_url=os.environ.get("METUBE_URL", "http://metube:8081").rstrip("/"),
        oembed_url=os.environ.get("TUNEALONG_OEMBED_URL", "https://www.youtube.com/oembed").strip(),
        audiodb_url=os.environ.get("TUNEALONG_AUDIODB_URL", "https://www.theaudiodb.com/api/v1/json/123").strip().rstrip("/"),
        download_timeout_s=float(os.environ.get("TUNEALONG_DOWNLOAD_TIMEOUT_S", "900")),
        download_poll_s=float(os.environ.get("TUNEALONG_DOWNLOAD_POLL_S", "2")),
        scan_interval_s=float(os.environ.get("TUNEALONG_SCAN_INTERVAL_S", "300")),
        worker_idle_s=float(os.environ.get("TUNEALONG_WORKER_IDLE_S", "1")),
        render_timeout_s=float(os.environ.get("TUNEALONG_RENDER_TIMEOUT_S", "3600")),
        playback_timeout_s=float(os.environ.get("TUNEALONG_PLAYBACK_TIMEOUT_S", "14400")),
        web_dir=Path(os.environ["TUNEALONG_WEB_DIR"]) if os.environ.get("TUNEALONG_WEB_DIR") else None,
        base_path=normalize_base_path(os.environ.get("TUNEALONG_BASE_PATH", "")),
        auth_user=os.environ.get("TUNEALONG_AUTH_USER") or None,
        auth_password_hash=os.environ.get("TUNEALONG_AUTH_PASSWORD_HASH") or None,
        cache_max_gb=float(os.environ["TUNEALONG_CACHE_MAX_GB"]) if os.environ.get("TUNEALONG_CACHE_MAX_GB") else None,
        gc_interval_s=float(os.environ.get("TUNEALONG_GC_INTERVAL_S", "3600")),
        heartbeat_path=Path(os.environ["TUNEALONG_HEARTBEAT"]) if os.environ.get("TUNEALONG_HEARTBEAT") else None,
        tab_max_mb=float(os.environ.get("TUNEALONG_TAB_MAX_MB", "10")),
        recording_max_mb=float(os.environ.get("TUNEALONG_RECORDING_MAX_MB", "1024")),
    )


def normalize_base_path(raw: str) -> str:
    """"/tunealong/", "tunealong" and "/tunealong" all become "/tunealong"; "/" and "" become ""."""
    path = "/" + raw.strip().strip("/")
    if path == "/":
        return ""
    if any(seg in ("", ".", "..") for seg in path[1:].split("/")):
        raise ValueError(f"TUNEALONG_BASE_PATH is not a clean path: {raw!r}")
    return path


def ensure_dirs(settings: Settings) -> None:
    for d in (settings.root, settings.originals_dir, settings.local_dir, settings.tabs_dir, settings.renders_dir,
              settings.playback_dir, settings.artist_images_dir):
        d.mkdir(parents=True, exist_ok=True)
    adopt_legacy_db(settings)


def adopt_legacy_db(settings: Settings) -> None:
    """Rename a pre-rename songbook.sqlite (and its WAL sidecars) to the current name.

    Only when the new file is missing, so an existing library is never replaced.
    The sidecars move before the main file: the api and worker start together,
    and whichever sees the main file already moved finds the sidecars moved too.
    """
    new = settings.db_path
    old = settings.root / LEGACY_DB_NAME
    if new.exists() or not old.exists():
        return
    for suffix in ("-wal", "-shm", ""):
        try:
            os.replace(f"{old}{suffix}", f"{new}{suffix}")
        except FileNotFoundError:
            pass  # no such sidecar, or the other process moved it first
    log.info("adopted legacy database %s as %s", old, new)
