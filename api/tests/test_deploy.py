"""Phase 7: runtime base path, optional Basic auth, worker GC and heartbeat."""

import base64
import dataclasses
import os
import time

import bcrypt
import pytest
from fastapi.testclient import TestClient

from tunealong import cache, config, ingest
from tunealong.main import create_app
from tunealong.worker import Worker

HASH = bcrypt.hashpw(b"s3cret pass", bcrypt.gensalt(rounds=4)).decode()


def basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


@pytest.fixture
def web(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text('<!doctype html><script src="./assets/app.js"></script>')
    (d / "assets" / "app.js").write_text("console.log(1)")
    return d


def make(settings, **kw):
    return TestClient(create_app(dataclasses.replace(settings, **kw)))


# --- config ---------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("", ""), ("/", ""), ("tunealong", "/tunealong"), ("/tunealong/", "/tunealong"), ("/a/b", "/a/b"), (" /x ", "/x"),
])
def test_normalize_base_path(raw, expected):
    assert config.normalize_base_path(raw) == expected


@pytest.mark.parametrize("raw", ["/a/../b", "/a//b", "/./a"])
def test_bad_base_path_is_rejected(raw):
    with pytest.raises(ValueError):
        config.normalize_base_path(raw)


def test_env_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("TUNEALONG_ROOT", str(tmp_path))
    monkeypatch.setenv("TUNEALONG_BASE_PATH", "tunealong/")
    monkeypatch.setenv("TUNEALONG_CACHE_MAX_GB", "2.5")
    monkeypatch.setenv("TUNEALONG_AUTH_USER", "me")
    s = config.load()
    assert (s.base_path, s.cache_max_gb, s.auth_enabled) == ("/tunealong", 2.5, False)  # no hash: auth stays off
    monkeypatch.setenv("TUNEALONG_AUTH_PASSWORD_HASH", HASH)
    assert config.load().auth_enabled


# --- base path ----------------------------------------------------------------------

def test_base_path_serves_ui_api_and_media(settings, originals, web, conn):
    ingest.scan(conn, settings)
    sid = conn.execute("SELECT id FROM songs WHERE youtube_id = 'AAAAAAAAAAA'").fetchone()[0]
    with make(settings, base_path="/tunealong", web_dir=web) as c:
        assert c.get("/tunealong/api/health").json() == {"status": "ok"}
        assert "./assets/app.js" in c.get("/tunealong/").text
        assert c.get("/tunealong/assets/app.js").status_code == 200
        lib = c.get("/tunealong/api/library").json()
        song = next(s for g in lib["groups"] for s in g["songs"] if s["id"] == sid)
        # Relative media URLs resolve under the subpath.
        r = c.get(f"/tunealong/{song['media_url']}", headers={"Range": "bytes=0-99"})
        assert r.status_code == 206 and len(r.content) == 100
        r = c.get("/tunealong", follow_redirects=False)
        assert r.status_code == 308 and r.headers["location"] == "/tunealong/"
        assert c.get("/api/health").status_code == 404
        assert c.get("/").status_code == 404


def test_no_base_path_serves_at_root(settings, web):
    with make(settings, web_dir=web) as c:
        assert c.get("/api/health").status_code == 200
        assert "./assets/app.js" in c.get("/").text


# --- auth ---------------------------------------------------------------------------

def test_auth_off_by_default(settings):
    with make(settings) as c:
        assert c.get("/api/library").status_code == 200


def test_auth_on(settings, web):
    with make(settings, auth_user="me", auth_password_hash=HASH, web_dir=web) as c:
        assert c.get("/api/health").status_code == 200  # stays open for healthchecks
        r = c.get("/api/library")
        assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic ")
        assert c.get("/").status_code == 401
        assert c.get("/media/originals/1").status_code == 401
        assert c.get("/api/library", headers=basic("me", "s3cret pass")).status_code == 200
        assert c.get("/", headers=basic("me", "s3cret pass")).status_code == 200
        assert c.get("/api/library", headers=basic("me", "wrong")).status_code == 401
        assert c.get("/api/library", headers=basic("you", "s3cret pass")).status_code == 401
        assert c.get("/api/library", headers={"Authorization": "Basic !!!"}).status_code == 401
        assert c.get("/api/library", headers={"Authorization": "Bearer x"}).status_code == 401


def test_auth_with_base_path(settings):
    with make(settings, auth_user="me", auth_password_hash=HASH, base_path="/sb") as c:
        assert c.get("/sb/api/health").status_code == 200
        assert c.get("/sb/api/library").status_code == 401
        assert c.get("/sb/api/library", headers=basic("me", "s3cret pass")).status_code == 200


def test_auth_caches_verified_headers(settings, monkeypatch):
    calls = []
    real = bcrypt.checkpw
    monkeypatch.setattr(bcrypt, "checkpw", lambda p, h: calls.append(1) or real(p, h))
    with make(settings, auth_user="me", auth_password_hash=HASH) as c:
        for _ in range(5):
            assert c.get("/api/library", headers=basic("me", "s3cret pass")).status_code == 200
    assert len(calls) == 1


def test_malformed_hash_denies(settings):
    with make(settings, auth_user="me", auth_password_hash="not-a-bcrypt-hash") as c:
        assert c.get("/api/library", headers=basic("me", "x")).status_code == 401
        assert c.get("/api/health").status_code == 200


# --- worker: heartbeat and scheduled GC ------------------------------------------------

def test_heartbeat(settings, client, tmp_path):
    hb = tmp_path / "hb"
    w = Worker(dataclasses.replace(settings, heartbeat_path=hb))
    w.beat()
    assert hb.exists() and time.time() - hb.stat().st_mtime < 5


def test_scheduled_gc(settings, client, conn, monkeypatch):
    d = settings.renders_dir / "9"
    d.mkdir(parents=True)
    (d / "stray.webm").write_bytes(b"x" * 10)
    w = Worker(dataclasses.replace(settings, cache_max_gb=1.0, gc_interval_s=3600))
    w.maybe_gc()
    assert not (d / "stray.webm").exists()
    assert w._next_gc > time.monotonic() + 3000


def test_gc_off_without_budget(settings, client):
    d = settings.renders_dir / "9"
    d.mkdir(parents=True)
    (d / "stray.webm").write_bytes(b"x")
    Worker(settings).maybe_gc()
    assert (d / "stray.webm").exists()


def test_gc_leaves_in_flight_temp_files(settings, client, conn):
    d = settings.renders_dir / "9"
    (d / ".k.work").mkdir(parents=True)
    (d / ".k.work" / "in.wav").write_bytes(b"x")
    (d / ".k.tmp.webm").write_bytes(b"x")
    old = d / ".old.tmp.webm"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 10 * 86400,) * 2)
    cache.gc(conn, settings, max_bytes=0)
    assert (d / ".k.work" / "in.wav").exists() and (d / ".k.tmp.webm").exists()
    assert not old.exists()
