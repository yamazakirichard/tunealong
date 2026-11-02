"""Settings, read from environment variables only."""

import os
from dataclasses import dataclass
from pathlib import Path


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
    web_dir: Path | None = None
    base_path: str = ""                 # "" or "/songbook" (no trailing slash)
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
        return self.root / "songbook.sqlite"

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
    def artist_images_dir(self) -> Path:
        return self.root / "artist-images"


def load() -> Settings:
    return Settings(
        root=Path(os.environ.get("SONGBOOK_ROOT", "/srv/songbook")).resolve(),
        busy_timeout_ms=int(os.environ.get("SONGBOOK_DB_BUSY_TIMEOUT_MS", "5000")),
        metube_url=os.environ.get("METUBE_URL", "http://metube:8081").rstrip("/"),
        oembed_url=os.environ.get("SONGBOOK_OEMBED_URL", "https://www.youtube.com/oembed").strip(),
        audiodb_url=os.environ.get("SONGBOOK_AUDIODB_URL", "https://www.theaudiodb.com/api/v1/json/123").strip().rstrip("/"),
        download_timeout_s=float(os.environ.get("SONGBOOK_DOWNLOAD_TIMEOUT_S", "900")),
        download_poll_s=float(os.environ.get("SONGBOOK_DOWNLOAD_POLL_S", "2")),
        scan_interval_s=float(os.environ.get("SONGBOOK_SCAN_INTERVAL_S", "300")),
        worker_idle_s=float(os.environ.get("SONGBOOK_WORKER_IDLE_S", "1")),
        render_timeout_s=float(os.environ.get("SONGBOOK_RENDER_TIMEOUT_S", "3600")),
        web_dir=Path(os.environ["SONGBOOK_WEB_DIR"]) if os.environ.get("SONGBOOK_WEB_DIR") else None,
        base_path=normalize_base_path(os.environ.get("SONGBOOK_BASE_PATH", "")),
        auth_user=os.environ.get("SONGBOOK_AUTH_USER") or None,
        auth_password_hash=os.environ.get("SONGBOOK_AUTH_PASSWORD_HASH") or None,
        cache_max_gb=float(os.environ["SONGBOOK_CACHE_MAX_GB"]) if os.environ.get("SONGBOOK_CACHE_MAX_GB") else None,
        gc_interval_s=float(os.environ.get("SONGBOOK_GC_INTERVAL_S", "3600")),
        heartbeat_path=Path(os.environ["SONGBOOK_HEARTBEAT"]) if os.environ.get("SONGBOOK_HEARTBEAT") else None,
        tab_max_mb=float(os.environ.get("SONGBOOK_TAB_MAX_MB", "10")),
        recording_max_mb=float(os.environ.get("SONGBOOK_RECORDING_MAX_MB", "1024")),
    )


def normalize_base_path(raw: str) -> str:
    """"/songbook/", "songbook" and "/songbook" all become "/songbook"; "/" and "" become ""."""
    path = "/" + raw.strip().strip("/")
    if path == "/":
        return ""
    if any(seg in ("", ".", "..") for seg in path[1:].split("/")):
        raise ValueError(f"SONGBOOK_BASE_PATH is not a clean path: {raw!r}")
    return path


def ensure_dirs(settings: Settings) -> None:
    for d in (settings.root, settings.originals_dir, settings.local_dir, settings.tabs_dir, settings.renders_dir,
              settings.artist_images_dir):
        d.mkdir(parents=True, exist_ok=True)
