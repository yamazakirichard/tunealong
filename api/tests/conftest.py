import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tunealong import config, db
from tunealong.main import create_app

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def settings(tmp_path, monkeypatch) -> config.Settings:
    """A temp TUNEALONG_ROOT with the standard directory layout."""
    root = tmp_path / "tunealong"
    monkeypatch.setenv("TUNEALONG_ROOT", str(root))
    monkeypatch.setenv("TUNEALONG_AUDIODB_URL", "")  # tests never reach TheAudioDB; test_artist_images uses the fake
    s = config.load()
    config.ensure_dirs(s)
    return s


@pytest.fixture
def conn(settings):
    """A fresh, migrated DB per test."""
    c = db.open_db(settings.db_path, settings.busy_timeout_ms)
    yield c
    c.close()


@pytest.fixture
def originals(settings) -> Path:
    """Copies of the generated fixture media in the temp originals/."""
    src = FIXTURES / "originals"
    if not src.is_dir() or not any(src.iterdir()):
        pytest.fail("fixtures missing: run `make fixtures`")
    for f in src.iterdir():
        shutil.copy2(f, settings.originals_dir / f.name)
    return settings.originals_dir


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c
