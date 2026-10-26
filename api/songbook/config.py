"""Settings, read from environment variables only."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path
    busy_timeout_ms: int

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
    def renders_dir(self) -> Path:
        return self.root / "renders"


def load() -> Settings:
    return Settings(
        root=Path(os.environ.get("SONGBOOK_ROOT", "/srv/songbook")).resolve(),
        busy_timeout_ms=int(os.environ.get("SONGBOOK_DB_BUSY_TIMEOUT_MS", "5000")),
    )


def ensure_dirs(settings: Settings) -> None:
    for d in (settings.root, settings.originals_dir, settings.local_dir, settings.renders_dir):
        d.mkdir(parents=True, exist_ok=True)
