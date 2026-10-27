import dataclasses

import pytest
from fastapi.testclient import TestClient

from songbook import artist_images
from songbook.main import create_app
from songbook.worker import Worker

from .conftest import FIXTURES
from .fake_metube import FakeMetube, Server


@pytest.fixture
def fake(settings):
    fm = FakeMetube(settings.originals_dir, FIXTURES / "originals" / "AAAAAAAAAAA.webm")
    with Server(fm.app) as srv:
        fm.url = srv.url
        yield fm


@pytest.fixture
def asettings(settings, fake):
    return dataclasses.replace(settings, metube_url=fake.url, audiodb_url=f"{fake.url}/audiodb")


@pytest.fixture
def aclient(asettings):
    with TestClient(create_app(asettings)) as c:
        yield c


def _row(conn, name):
    return conn.execute("SELECT * FROM artists WHERE name = ?", (name,)).fetchone()


def test_fetches_every_artist_once_and_serves_the_picture(aclient, asettings, conn, fake):
    # Existing artists (the backfill) and new ones are the same: never looked up.
    aclient.post("/api/artists", json={"name": "black sabbath"})
    aclient.post("/api/artists", json={"name": "Nobody Knows Us"})
    assert artist_images.fetch_one(conn, asettings)
    assert artist_images.fetch_one(conn, asettings)
    assert not artist_images.fetch_one(conn, asettings)
    assert fake.audiodb_calls == ["black sabbath", "Nobody Knows Us"]

    bs = _row(conn, "Black Sabbath")
    assert bs["image_path"] == f"artist-images/{bs['id']}.png" and bs["image_checked_at"]
    assert (asettings.root / bs["image_path"]).read_bytes().startswith(b"\x89PNG")
    nobody = _row(conn, "Nobody Knows Us")
    assert nobody["image_path"] is None and nobody["image_checked_at"]  # a miss, recorded

    groups = {g["name"]: g for g in aclient.get("/api/library").json()["groups"]}
    url = groups["black sabbath"]["image_url"]
    assert url.startswith(f"media/artists/{bs['id']}?v=2")
    assert groups["Nobody Knows Us"]["image_url"] is None
    r = aclient.get("/" + url)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "max-age" in r.headers["cache-control"]
    assert aclient.get(f"/media/artists/{nobody['id']}").status_code == 404


def test_only_takes_an_artist_of_the_same_name(asettings, conn, fake):
    conn.execute("INSERT INTO artists (name) VALUES ('Sabbath')")  # the fuzzy search finds Black Sabbath
    assert artist_images.fetch_one(conn, asettings)
    assert fake.audiodb_calls == ["Sabbath"]
    assert _row(conn, "Sabbath")["image_path"] is None


def test_spelling_differences_still_match(asettings, conn):
    conn.execute("INSERT INTO artists (name) VALUES ('BLACK SABBATH')")
    artist_images.fetch_one(conn, asettings)
    assert _row(conn, "Black Sabbath")["image_path"]


def test_stale_misses_are_retried(asettings, conn, fake):
    conn.execute("INSERT INTO artists (name, image_checked_at) VALUES ('Fake Uploader', datetime('now', '-31 days'))")
    conn.execute("INSERT INTO artists (name, image_checked_at) VALUES ('Recent Miss', datetime('now', '-1 day'))")
    assert artist_images.fetch_one(conn, asettings)
    assert not artist_images.fetch_one(conn, asettings)
    assert fake.audiodb_calls == ["Fake Uploader"]
    assert _row(conn, "Fake Uploader")["image_path"]


def test_unreachable_records_nothing_and_the_worker_backs_off(asettings, conn, fake):
    conn.execute("INSERT INTO artists (name) VALUES ('Black Sabbath')")
    fake.audiodb_status = 503
    with pytest.raises(artist_images.Unreachable):
        artist_images.fetch_one(conn, asettings)
    assert _row(conn, "Black Sabbath")["image_checked_at"] is None

    w = Worker(asettings, conn=conn)
    assert not w.maybe_artist_image()
    assert not w.maybe_artist_image()  # backing off: no second request
    assert len(fake.audiodb_calls) == 2

    fake.audiodb_status = None
    w._next_artist_image = 0
    assert w.maybe_artist_image()
    assert _row(conn, "Black Sabbath")["image_path"]

    off = Worker(dataclasses.replace(asettings, audiodb_url=""), conn=conn)
    conn.execute("INSERT INTO artists (name) VALUES ('Fake Uploader')")
    assert not off.maybe_artist_image()
    assert len(fake.audiodb_calls) == 3


def test_rename_looks_up_again_and_delete_removes_the_file(aclient, asettings, conn, fake):
    aid = aclient.post("/api/artists", json={"name": "Black Sabbath"}).json()["id"]
    artist_images.fetch_one(conn, asettings)
    old = asettings.root / _row(conn, "Black Sabbath")["image_path"]
    assert old.is_file()

    # Other settings and a case-only rename keep the picture.
    aclient.patch(f"/api/artists/{aid}", json={"columns": 3})
    aclient.patch(f"/api/artists/{aid}", json={"name": "BLACK SABBATH"})
    assert old.is_file() and _row(conn, "Black Sabbath")["image_path"]

    j = aclient.patch(f"/api/artists/{aid}", json={"name": "Fake Uploader"}).json()
    assert j["image_path"] is None and j["image_checked_at"] is None and not old.exists()
    artist_images.fetch_one(conn, asettings)
    new = asettings.root / _row(conn, "Fake Uploader")["image_path"]
    assert new.is_file()

    assert aclient.delete(f"/api/artists/{aid}").status_code == 204
    assert not new.exists()


def test_renamed_while_looking_up_drops_the_result(asettings, conn, monkeypatch):
    conn.execute("INSERT INTO artists (name) VALUES ('Black Sabbath')")
    real = artist_images.lookup

    def rename_meanwhile(endpoint, name):
        url = real(endpoint, name)
        conn.execute("UPDATE artists SET name = 'Someone Else'")
        return url

    monkeypatch.setattr(artist_images, "lookup", rename_meanwhile)
    artist_images.fetch_one(conn, asettings)
    assert _row(conn, "Someone Else")["image_checked_at"] is None
    assert list(asettings.artist_images_dir.iterdir()) == []
