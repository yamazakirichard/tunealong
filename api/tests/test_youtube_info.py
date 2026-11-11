import dataclasses

import pytest
from fastapi.testclient import TestClient

from tunealong.main import create_app
from tunealong.youtube import oembed

from .conftest import FIXTURES
from .fake_metube import FakeMetube, Server


@pytest.fixture
def yclient(settings):
    oembed.cache_clear()
    fm = FakeMetube(settings.originals_dir, FIXTURES / "originals" / "AAAAAAAAAAA.webm")
    with Server(fm.app) as srv, TestClient(create_app(dataclasses.replace(settings, oembed_url=f"{srv.url}/oembed"))) as c:
        yield c
    oembed.cache_clear()


def test_guesses_artist_and_title(yclient):
    r = yclient.get("/api/youtube", params={"url": "https://youtu.be/Pzzzzzzzzzz?si=x"})
    assert r.status_code == 200
    assert r.json() == {
        "youtube_id": "Pzzzzzzzzzz", "yt_title": "Black Sabbath - Paranoid (Official Video)",
        "uploader": "BlackSabbathVEVO", "in_library": False, "artist": "Black Sabbath", "title": "Paranoid",
    }


def test_uses_known_artists_and_reports_duplicates(yclient):
    # The fake's channel is "Fake Uploader"; as a known artist, it's guessed as the artist.
    assert yclient.post("/api/artists", json={"name": "Fake Uploader"}).status_code == 201
    yclient.post("/api/songs", json={"url": "E0ozmU9cJDg"})
    j = yclient.get("/api/youtube", params={"url": "E0ozmU9cJDg"}).json()
    assert j["in_library"] is True
    assert (j["artist"], j["title"]) == ("Fake Uploader", "YouTube title E0ozmU9cJDg")


def test_bad_url(yclient):
    assert yclient.get("/api/youtube", params={"url": "https://example.com/x"}).status_code == 422


def test_youtube_unreachable_still_answers(settings):
    oembed.cache_clear()
    s = dataclasses.replace(settings, oembed_url="http://127.0.0.1:9/oembed")
    with TestClient(create_app(s)) as c:
        j = c.get("/api/youtube", params={"url": "E0ozmU9cJDg"}).json()
    assert j == {"youtube_id": "E0ozmU9cJDg", "yt_title": None, "uploader": None, "in_library": False,
                 "artist": None, "title": None}


def test_disabled_never_calls_out(settings, monkeypatch):
    monkeypatch.setattr("tunealong.routes.youtube.oembed", lambda *a: pytest.fail("called oEmbed"))
    with TestClient(create_app(dataclasses.replace(settings, oembed_url=""))) as c:
        assert c.get("/api/youtube", params={"url": "E0ozmU9cJDg"}).json()["yt_title"] is None
